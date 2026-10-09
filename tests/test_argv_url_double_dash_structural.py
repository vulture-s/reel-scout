"""Structural guard: a URL placed in a child-process argv is always preceded by "--".

Bug class (docs/known-bug-classes.md §4): a URL that starts with "-" (from a
pasted list, a doc, an MCP caller) is parsed by yt-dlp as an *option* --
`--exec`, `--config-location`, `-o` -- i.e. argument injection. #184 put "--"
before the URL in each crawler and tests those call sites one by one
(tests/test_low_hardening.py). This scans every argv-shaped list and every
`<tool>.cmd(...)` call in the package, so the next crawler or the next
subprocess that takes a URL is covered without anyone remembering to add a test.
"""
from __future__ import annotations

import ast
import os

import reel_scout

PKG = os.path.dirname(reel_scout.__file__)


def _argv_sites():
    """(file, line, var, ok) for each url-named variable inside an argv."""
    out = []
    for root, _dirs, files in os.walk(PKG):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(root, fn)
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.List):
                    elts = node.elts
                    # argv-shaped: carries at least one option string.
                    if not any(isinstance(e, ast.Constant) and isinstance(e.value, str)
                               and e.value.startswith("-") for e in elts):
                        continue
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                      and node.func.attr == "cmd"):
                    elts = node.args
                else:
                    continue
                for i, e in enumerate(elts):
                    if isinstance(e, ast.Name) and "url" in e.id.lower():
                        prev = elts[i - 1] if i else None
                        ok = isinstance(prev, ast.Constant) and prev.value == "--"
                        out.append((os.path.relpath(path, PKG), node.lineno, e.id, ok))
    return out


def test_scan_finds_the_crawler_call_sites():
    files = {f for f, _l, _v, _ok in _argv_sites()}
    # youtube/instagram/tiktok all hand URLs to yt-dlp; if the scan stops
    # seeing them it has stopped guarding anything.
    for name in ("youtube.py", "instagram.py", "tiktok.py"):
        assert os.path.join("crawl", name) in files, files
    assert len(_argv_sites()) >= 9


def test_every_url_in_an_argv_follows_double_dash():
    bad = ["%s:%d %s" % (f, line, var) for f, line, var, ok in _argv_sites() if not ok]
    assert not bad, ("URL passed to a child process without a preceding \"--\" "
                     "(an option-shaped URL becomes a yt-dlp option): %s" % bad)
