"""Setup preflight remediation strings (`scripts/setup.py`).

This script is the first thing an agent runs and the only thing that tells a new
user how to install. It had no tests, which is how the not-installed branch spent
its life printing an editable install against a literal ``<repo-root>`` — correct
for a developer inside a clone, useless for the person it was actually written
for, who has never cloned anything.
"""
from __future__ import annotations

import importlib.util
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP_PY = os.path.join(REPO_ROOT, "scripts", "setup.py")


@pytest.fixture
def setup_mod():
    spec = importlib.util.spec_from_file_location("rs_setup", SETUP_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, monkeypatch, capsys, *, missing, installed, repo_root):
    monkeypatch.setattr(mod, "_missing_binaries", lambda: list(missing))
    monkeypatch.setattr(mod, "_reel_scout_installed", lambda: installed)
    monkeypatch.setattr(mod, "_repo_root", lambda: repo_root)
    code = mod.main([])
    return code, capsys.readouterr().out


def test_no_clone_points_at_pypi_not_a_placeholder(setup_mod, monkeypatch, capsys):
    """The student case: nothing cloned, so the only install that works is PyPI."""
    code, out = _run(setup_mod, monkeypatch, capsys,
                     missing=[], installed=False, repo_root=None)
    assert code == 3
    assert "pip install reel-scout" in out
    assert "<repo-root>" not in out
    assert "pip install -e" not in out


def test_inside_a_clone_keeps_the_editable_install(setup_mod, monkeypatch, capsys):
    code, out = _run(setup_mod, monkeypatch, capsys,
                     missing=[], installed=False, repo_root="/somewhere/reel-scout")
    assert code == 3
    assert 'pip install -e "/somewhere/reel-scout"' in out


def test_missing_binaries_are_named_with_a_command(setup_mod, monkeypatch, capsys):
    code, out = _run(setup_mod, monkeypatch, capsys,
                     missing=["ffmpeg", "yt-dlp"], installed=True, repo_root=None)
    assert code == 2
    assert "ffmpeg" in out and "yt-dlp" in out
    assert "brew install" in out


def test_both_missing_reports_both(setup_mod, monkeypatch, capsys):
    code, out = _run(setup_mod, monkeypatch, capsys,
                     missing=["ffmpeg"], installed=False, repo_root=None)
    assert code == 4
    assert "brew install" in out
    assert "pip install reel-scout" in out


def test_ready_is_silent_under_check(setup_mod, monkeypatch, capsys):
    """Step 0 runs on every invocation; noise on success trains agents to ignore it."""
    monkeypatch.setattr(setup_mod, "_missing_binaries", list)
    monkeypatch.setattr(setup_mod, "_reel_scout_installed", lambda: True)
    assert setup_mod.main(["--check"]) == 0
    assert capsys.readouterr().out == ""


def test_json_status_is_machine_readable(setup_mod, monkeypatch, capsys):
    import json

    monkeypatch.setattr(setup_mod, "_missing_binaries", lambda: ["ffmpeg"])
    monkeypatch.setattr(setup_mod, "_reel_scout_installed", lambda: False)
    setup_mod.main(["--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "needs_install_and_deps"
    assert payload["missing_binaries"] == ["ffmpeg"]
    assert payload["reel_scout_installed"] is False


# --- platform-appropriate remediation ---------------------------------------

@pytest.mark.parametrize("plat,expect,forbid", [
    ("win32", "winget", "brew install"),
    ("darwin", "brew install", "winget"),
    ("linux", "apt install", "brew install"),
])
def test_missing_binary_advice_matches_the_platform(
        setup_mod, monkeypatch, capsys, plat, expect, forbid):
    """Telling a Windows user to `brew install` is worse than silence — it reads
    like an instruction and isn't one. Found while handing the flow to a PC."""
    monkeypatch.setattr(setup_mod.sys, "platform", plat)
    _, out = _run(setup_mod, monkeypatch, capsys,
                  missing=["ffmpeg"], installed=True, repo_root=None)
    assert expect in out
    assert forbid not in out
