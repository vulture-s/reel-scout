#!/usr/bin/env python3
"""Reel Scout skill setup preflight.

Checks that the pieces the skill needs to run the full pipeline are present:
  - python (the interpreter running this is proof enough)
  - ffmpeg / ffprobe (keyframe extraction + audio)
  - yt-dlp (download + native captions)
  - the ``reel-scout`` console entry point (``pip install reel-scout``, or
    ``pip install -e .`` when run from a clone)

Exit codes (consumed by SKILL.md Step 0):
  0  ready                  -> silent, proceed
  2  missing system binary  -> ffmpeg/ffprobe/yt-dlp not on PATH
  3  reel-scout not installed-> ``pip install reel-scout`` (or ``-e .`` in a clone)
  4  both                    -> binary(ies) AND reel-scout missing

``--check``   exit-code-only, no stdout on success (preflight default)
``--json``    machine-readable status object on stdout
no flag       human-readable remediation hints on stdout

Python 3.9 compatible. Stdlib only — no new dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Dict, List, Optional

# System binaries the pipeline shells out to.
REQUIRED_BINARIES = ["ffmpeg", "ffprobe", "yt-dlp"]


def _missing_binaries() -> List[str]:
    return [b for b in REQUIRED_BINARIES if shutil.which(b) is None]


def _reel_scout_installed() -> bool:
    """True if the package import works OR the console script is on PATH."""
    if shutil.which("reel-scout") is not None:
        return True
    try:
        import reel_scout  # noqa: F401
        return True
    except Exception:
        return False


def _status(missing: List[str], installed: bool) -> str:
    if missing and not installed:
        return "needs_install_and_deps"
    if missing:
        return "needs_deps"
    if not installed:
        return "needs_install"
    return "ready"


def _exit_code(status: str) -> int:
    return {
        "ready": 0,
        "needs_deps": 2,
        "needs_install": 3,
        "needs_install_and_deps": 4,
    }[status]


def _repo_root() -> Optional[str]:
    # scripts/setup.py -> repo root is one level up.
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    if os.path.exists(os.path.join(root, "pyproject.toml")):
        return root
    return None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Reel Scout skill setup preflight")
    parser.add_argument("--check", action="store_true", help="Exit-code only, silent on success")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON status")
    args = parser.parse_args(argv)

    missing = _missing_binaries()
    installed = _reel_scout_installed()
    status = _status(missing, installed)
    code = _exit_code(status)

    if args.as_json:
        payload: Dict[str, object] = {
            "status": status,
            "missing_binaries": missing,
            "reel_scout_installed": installed,
            "repo_root": _repo_root(),
            "platform": sys.platform,
        }
        print(json.dumps(payload, ensure_ascii=False))
        return code

    if args.check:
        # Silent on success; remediation hint to stderr on failure.
        if code != 0:
            sys.stderr.write("reel-scout setup incomplete (run without --check for details)\n")
        return code

    # Human-readable remediation.
    if status == "ready":
        print("reel-scout: ready (ffmpeg, yt-dlp, and reel-scout all present).")
        return 0

    print("reel-scout setup incomplete:")
    if missing:
        print("  Missing system binaries: " + ", ".join(missing))
        brew_pkgs = [b for b in missing if b not in ("ffprobe", "yt-dlp")]
        if "yt-dlp" in missing:
            brew_pkgs.append("yt-dlp")
        if "ffprobe" in missing and "ffmpeg" not in brew_pkgs:
            brew_pkgs.append("ffmpeg")  # ffprobe ships with ffmpeg
        # Platform-specific, because telling a Windows user to run `brew install`
        # is worse than saying nothing: it reads like an instruction and isn't one.
        pkgs = " ".join(brew_pkgs or ["ffmpeg"])
        if sys.platform == "win32":
            print("    winget:            winget install Gyan.FFmpeg")
            print("    or Chocolatey:     choco install ffmpeg")
            print("    or Scoop:          scoop install ffmpeg")
            print("    then RESTART the terminal so PATH is picked up.")
        elif sys.platform == "darwin":
            print("    macOS (Homebrew):  brew install " + pkgs)
        else:
            print("    Debian/Ubuntu:     sudo apt install ffmpeg")
            print("    Fedora:            sudo dnf install ffmpeg")
        print("    yt-dlp via pip:    pip install -U yt-dlp")
        print("    (ffprobe ships with ffmpeg.)")
    if not installed:
        root = _repo_root()
        if root:
            # Running inside a clone: editable, so local edits take effect.
            print("  reel-scout not installed. From this clone, run:")
            print("    pip install -e \"" + root + "\"")
            print("    # add transcription support: pip install -e \"" + root + "[whisper]\"")
        else:
            # No clone anywhere — the ordinary user, who wants the published
            # package. This branch used to print an editable install against a
            # literal "<repo-root>" placeholder, i.e. it sent someone who had
            # never cloned anything to a directory that does not exist.
            print("  reel-scout not installed. Run:")
            print("    pip install reel-scout")
            print("    # add transcription support: pip install \"reel-scout[whisper]\"")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
