"""Structural guard: every CLI subcommand's failure path must exit non-zero.

Bug class (recurring — see docs/known-bug-classes.md §1): a handler prints
"Error: …" / "Video not found" and then returns None, so the shell sees rc 0.
`batch` (and any script or agent driving the CLI) judges success by rc, so a
quiet failure is recorded as done. PR #198 fixed this for score/export bundle;
this test makes the *next* subcommand that does it fail CI.

How it stays structural rather than a list of single regressions:

* The subcommand set is read from the real argparse tree (not hard-coded), and
  ``test_every_subcommand_is_classified`` fails when a new leaf command appears
  that is in neither ``FAILING_INVOCATIONS`` nor ``NO_FAILURE_INPUT``. Adding a
  command therefore forces a decision about how it reports failure.
* Each failing invocation runs against an empty temp DB with the network and
  child processes blocked, so it can only fail locally and fast.
* ``KNOWN_RC0`` is a ratchet: the commands that still exit 0 on failure today.
  It may only shrink — its size can never grow past ``KNOWN_RC0_BASELINE`` and
  no command outside it may exit 0; a listed command that gets fixed warns
  "remove it from KNOWN_RC0".
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import warnings

import pytest

from reel_scout import cli

MISSING_ID = "zz-no-such-video-0000"
UNSUPPORTED_URL = "https://example.invalid/not-a-platform/123"


def _leaf_commands():
    """Walk the parser main() really builds and return every leaf command path."""
    captured = {}
    orig = argparse.ArgumentParser.parse_args

    def grab(self, *a, **k):
        captured["parser"] = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = grab
    try:
        try:
            cli.main([])
        except SystemExit:
            pass
    finally:
        argparse.ArgumentParser.parse_args = orig

    out = []

    def walk(p, prefix):
        subs = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
        if not subs:
            out.append(" ".join(prefix))
            return
        for name, sp in subs[0].choices.items():
            walk(sp, prefix + [name])

    walk(captured["parser"], [])
    return out


def _failing_invocations(tmp, make_files=True):
    missing_file = os.path.join(tmp, "does-not-exist.json")
    bad_json = os.path.join(tmp, "bad.json")
    # A path whose parent is a regular file: no write can ever succeed there.
    blocker = os.path.join(tmp, "blocker")
    if make_files:
        with open(bad_json, "w", encoding="utf-8") as f:
            f.write("{not json")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("x")
    unwritable = os.path.join(blocker, "sub", "out")
    return {
        "browse": ["browse", UNSUPPORTED_URL],
        "crawl": ["crawl", UNSUPPORTED_URL],
        "analyze": ["analyze", os.path.join(tmp, "missing.mp4")],
        "transcribe": ["transcribe", os.path.join(tmp, "missing.mp4")],
        "vision": ["vision", os.path.join(tmp, "missing.mp4")],
        "show": ["show", MISSING_ID],
        "note": ["note", MISSING_ID, "--text", "x"],
        "group rename": ["group", "rename", "no-such-group", "new"],
        "group rm": ["group", "rm", "no-such-group"],
        "mark": ["mark", MISSING_ID, "--at", "1", "--label", "x"],
        "inspect": ["inspect", MISSING_ID, "--no-open"],
        "translate": ["translate", MISSING_ID],
        "storyboard-diff": ["storyboard-diff", MISSING_ID, missing_file],
        "shot-size": ["shot-size", MISSING_ID],
        "motion": ["motion", MISSING_ID],
        "export": ["export", "--format", "bundle", "--video", MISSING_ID,
                   "-o", os.path.join(tmp, "export")],
        "score": ["score", MISSING_ID],
        "ingest vision": ["ingest", "vision", MISSING_ID, "--from-json", bad_json],
        "ingest analysis": ["ingest", "analysis", MISSING_ID, "--from-json", bad_json],
        "ingest score": ["ingest", "score", MISSING_ID, "--from-json", bad_json],
        "compare": ["compare", MISSING_ID],
        "research": ["research", "--niche", "x", "--channels", UNSUPPORTED_URL,
                     "--no-analyze"],
        "inspire": ["inspire", "--based-on", MISSING_ID],
        "track": ["track", "--my-video", MISSING_ID, "--views", "1"],
        "batch": ["batch", "--file", missing_file, "--out", os.path.join(tmp, "b")],
        "mcp install": ["mcp", "install", "--path", unwritable, "--force"],
    }


# Commands with no input that is *guaranteed* to fail locally (pure listings,
# read-only reports over an empty DB, servers, maintenance that is a no-op on
# an empty DB). Each needs a reason; a new command may not land here silently.
NO_FAILURE_INPUT = {
    "list": "listing; empty result is not a failure",
    "pending": "listing of pending work; empty is not a failure",
    "group list": "listing",
    "group add": "any non-empty name is valid",
    "view": "starts a long-running HTTP server",
    "stats": "read-only aggregate; empty corpus is not a failure",
    "patterns": "read-only aggregate; empty corpus is not a failure",
    "skill install": "copies packaged assets; no local-only failing input",
    "skill path": "prints a path",
    "mcp path": "prints config locations",
    "db stats": "read-only",
    "db reset": "destructive; not exercised here",
    "db migrate": "idempotent on a fresh DB",
    "db normalize-paths": "no-op on an empty DB",
    "db backfill-text": "no-op on an empty DB",
    "db health": "report over an empty DB",
    "db backfill-shots": "no-op on an empty DB",
    "db check-invalid": "report over an empty DB",
    "config show": "prints resolved config",
    "config check": "probes external tools; result depends on the host",
}

# Ratchet: these still exit 0 on the failing invocation above (baseline taken
# 2026-10-09 on master de60655). It may only shrink: the size can never exceed
# KNOWN_RC0_BASELINE, and nothing outside this set may exit 0. score/export are
# fixed by open PR #198. A listed command that starts exiting non-zero only
# *warns* (asking for its removal) instead of failing, so fix PRs that are in
# flight in parallel do not turn each other's CI red by merge order.
KNOWN_RC0 = {
    "browse", "compare", "crawl", "export", "ingest analysis", "ingest score",
    "ingest vision", "motion", "research", "score", "shot-size", "show",
    "storyboard-diff", "translate",
}
KNOWN_RC0_BASELINE = 14


def _block_side_effects(monkeypatch):
    def no_net(*a, **k):
        raise OSError("network blocked in test_cli_failure_exit_codes")

    def no_proc(*a, **k):
        raise OSError("child processes blocked in test_cli_failure_exit_codes")

    monkeypatch.setattr(socket.socket, "connect", no_net)
    monkeypatch.setattr(socket, "create_connection", no_net)
    monkeypatch.setattr(subprocess, "Popen", no_proc)
    monkeypatch.setattr(subprocess, "run", no_proc)
    # inspect/view would otherwise open a browser.
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: False)


def _exit_code(argv):
    try:
        cli.main(argv)
    except SystemExit as e:
        if e.code is None:
            return 0
        return e.code if isinstance(e.code, int) else 1
    except Exception:  # an uncaught exception exits 1 under `python -m`
        return 1
    return 0


def test_every_subcommand_is_classified(tmp_path):
    leaves = set(_leaf_commands())
    classified = set(_failing_invocations(str(tmp_path), make_files=False)) | set(NO_FAILURE_INPUT)
    unclassified = sorted(leaves - classified)
    assert not unclassified, (
        "New CLI subcommand(s) %s: add a guaranteed-failing invocation to "
        "_failing_invocations() (and make it exit non-zero), or list it in "
        "NO_FAILURE_INPUT with a reason." % unclassified)
    stale = sorted(classified - leaves)
    assert not stale, "Classified commands that no longer exist: %s" % stale


def test_known_rc0_ratchet_only_shrinks():
    assert len(KNOWN_RC0) <= KNOWN_RC0_BASELINE, (
        "KNOWN_RC0 grew — a new subcommand must exit non-zero on failure, not be "
        "added to the allow-list.")


_NAMES = sorted(_failing_invocations("/x", make_files=False))


@pytest.mark.parametrize("name", _NAMES)
def test_failure_path_exits_nonzero(name, temp_db, tmp_path, monkeypatch, capsys):
    argv = _failing_invocations(str(tmp_path))[name]
    _block_side_effects(monkeypatch)
    rc = _exit_code(argv)
    capsys.readouterr()
    if name in KNOWN_RC0:
        if rc != 0:
            warnings.warn(
                "`reel-scout %s` now exits %r on failure — remove %r from "
                "KNOWN_RC0 and lower KNOWN_RC0_BASELINE." % (" ".join(argv), rc, name))
    else:
        assert rc != 0, (
            "`reel-scout %s` failed but exited 0. A handler that prints an error "
            "must return a non-zero code (see cli.main: `if code: raise "
            "SystemExit(code)`)." % " ".join(argv))


# --- batch trusts the child's exit code -------------------------------------
#
# batch.run_batch shells out to its own CLI (`self_cmd(...)`) and judges every
# step by rc alone: `analyze` rc 0 -> claim, `export` rc 0 -> bundle done,
# `score` rc 0 -> item_scored. So any subcommand batch invokes MUST be outside
# KNOWN_RC0, or a quiet failure becomes a "done" row. The subcommand list is
# read from batch.py's source, so a new self_cmd("...") step is covered too.
#
# export/score are the #198 pair (open PR, review-only). Once it lands, empty
# this set; it may never gain a member.
BATCH_STEPS_STILL_RC0_PENDING_FIX = {"export", "score"}


def _batch_self_cmd_steps():
    import ast
    import inspect

    from reel_scout import batch

    tree = ast.parse(inspect.getsource(batch))
    steps = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "self_cmd" and node.args
                and isinstance(node.args[0], ast.Constant)):
            steps.add(node.args[0].value)
    return steps


def test_batch_finds_its_self_cmd_steps():
    # The scan must see the three steps it is guarding, or it guards nothing.
    assert {"analyze", "export", "score"} <= _batch_self_cmd_steps()


def test_batch_steps_exit_nonzero_on_failure():
    steps = _batch_self_cmd_steps()
    trusted_but_rc0 = sorted((steps & KNOWN_RC0) - BATCH_STEPS_STILL_RC0_PENDING_FIX)
    assert not trusted_but_rc0, (
        "batch judges %s by exit code, but they exit 0 on failure (KNOWN_RC0). "
        "Fix the handler before batch relies on it." % trusted_but_rc0)
    assert BATCH_STEPS_STILL_RC0_PENDING_FIX <= {"export", "score"}, (
        "BATCH_STEPS_STILL_RC0_PENDING_FIX may only shrink.")
    for step in steps:
        assert step in _failing_invocations("/x", make_files=False), (
            "batch step %r has no failing invocation in this file." % step)
