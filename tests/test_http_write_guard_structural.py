"""Structural guard: every HTTP write verb in the package goes through
`inspector.write_refusal` before it reads a body or touches the database.

Bug class (recurring — docs/known-bug-classes.md §3): a localhost server that
accepts writes without a Host/Origin check is writable by any page in the same
browser (CSRF) and, via DNS rebinding, by any site at all. #183 fixed the
inspector's do_POST; this scans *every* BaseHTTPRequestHandler subclass in
reel_scout, so a new do_PUT/do_DELETE/do_PATCH, or a second server module, that
skips the guard fails CI instead of shipping. Route-level behaviour (403 for
each POST prefix) lives in tests/test_inspector_csrf.py; this file proves no
write entry point exists outside it.
"""
from __future__ import annotations

import ast
import os

import reel_scout

PKG = os.path.dirname(reel_scout.__file__)
READ_VERBS = {"do_GET", "do_HEAD", "do_OPTIONS"}
# Calls that consume the request or reach state. The guard must come first.
SIDE_EFFECT_MARKERS = ("rfile", "handle_api", "_request_analysis", "get_connection",
                       "request_analysis", "upsert", "execute", "set_annotation")


def _handler_classes():
    for root, _dirs, files in os.walk(PKG):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = [ast.unparse(b) if hasattr(ast, "unparse") else getattr(b, "attr", getattr(b, "id", ""))
                         for b in node.bases]
                if any("BaseHTTPRequestHandler" in b or "HTTPRequestHandler" in b
                       for b in bases):
                    yield os.path.relpath(path, PKG), node


def _call_name(call):
    f = call.func
    parts = []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    return ".".join(reversed(parts))


def _write_methods():
    out = []
    for rel, cls in _handler_classes():
        for item in cls.body:
            if (isinstance(item, ast.FunctionDef) and item.name.startswith("do_")
                    and item.name not in READ_VERBS):
                out.append((rel, cls.name, item))
    return out


def test_scan_sees_the_known_handlers():
    # Non-vacuous: the scan must find the viewer and inspector handlers and
    # the inspector's do_POST, or every assertion below passes on nothing.
    classes = {(rel, c.name) for rel, c in _handler_classes()}
    rels = {rel for rel, _ in classes}
    assert "inspector.py" in rels and "viewer.py" in rels, classes
    assert any(m.name == "do_POST" for _, _, m in _write_methods())


def test_every_write_verb_calls_write_refusal_first():
    bad = []
    for rel, cls, meth in _write_methods():
        calls = [n for n in ast.walk(meth) if isinstance(n, ast.Call)]
        guard = [c.lineno for c in calls if _call_name(c).endswith("write_refusal")]
        if not guard:
            bad.append("%s:%s.%s never calls write_refusal" % (rel, cls, meth.name))
            continue
        first = min(guard)
        early = sorted({_call_name(c) for c in calls if c.lineno < first
                        and any(m in _call_name(c) for m in SIDE_EFFECT_MARKERS)})
        if early:
            bad.append("%s:%s.%s does %s before write_refusal" % (rel, cls, meth.name, early))
    assert not bad, "\n".join(bad)


def test_write_api_dispatch_only_from_guarded_methods():
    # annotate.handle_api is the HTTP-facing dispatcher; its non-GET methods
    # write. Outside a guarded do_<WRITE> method (do_GET, _route, helpers) it
    # may only ever be called with the literal "GET" -- otherwise a plain
    # <img src> or a rebinding page reaches a write without the guard.
    write_ids = {(rel, cls, m.name) for rel, cls, m in _write_methods()}
    bad, seen = [], 0
    for rel, cls in _handler_classes():
        for item in cls.body:
            if (not isinstance(item, ast.FunctionDef)
                    or (rel, cls.name, item.name) in write_ids):
                continue
            for n in ast.walk(item):
                if isinstance(n, ast.Call) and _call_name(n).endswith("handle_api"):
                    seen += 1
                    m = n.args[1] if len(n.args) > 1 else None
                    if not (isinstance(m, ast.Constant) and m.value == "GET"):
                        bad.append("%s:%s.%s line %d" % (rel, cls.name, item.name, n.lineno))
    assert seen, "scan found no read-side handle_api calls; it is not looking where the code is"
    assert not bad, "unguarded write dispatch: %s" % bad
