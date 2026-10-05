"""The nightly scripts must work from whatever checkout they are sitting in.

🔴 **Why this file exists.** `translate-all.sh` and `shot-size-rerun.sh` lived
in `~/Library/Application Support/reel-scout/` until 2026-10-05 -- outside any
repository. `translate-all.sh` is the sole producer of the ~11,800 rows in the
`translations` table, and neither script was recoverable from a fresh machine:
the launchd plist for the nightly translate job had a template nowhere, and the
thing it executed had a template nowhere either.

They are in `scripts/` now, which only helps if they stay checkout-agnostic.
Both used to open with `REPO=/Users/hevinyeh/Projects/reel-scout`, and that one
line is the whole reason a copy in a repo would still have been a copy of one
machine. So the seam under test is: **the path each script derives for itself
is the root of the checkout it was run from** -- not a literal, and not the
process's cwd.

A re-hardcode is the realistic regression (it is one keystroke, and it works
fine on the author's machine, which is exactly why nothing notices). Checking
for the absence of an absolute home path would pass a script that derived the
wrong directory, so the derivation is actually executed here rather than
pattern-matched.

🔴 **The first version of this file could not catch that regression at all.**
It ran the derivation in place and asserted the answer equalled the repo root.
Re-hardcoding `REPO=/Users/hevinyeh/Projects/reel-scout` left it green -- on
this machine that literal *is* the repo root, so the assertion was comparing
the wrong thing to the right answer. A guard that only passes because the
author's checkout happens to live where the literal points is not a guard.

So the test relocates the script: a copy is run from a different root, and
`REPO` has to follow the copy. That fails for a literal on every machine,
including the one where the literal is correct.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ["translate-all.sh", "shot-size-rerun.sh"]


def _repo_assignment(text: str) -> str:
    """The script's own `REPO=...` line, verbatim."""
    for line in text.splitlines():
        if line.startswith("REPO="):
            return line
    raise AssertionError("no REPO= assignment found")


def _resolve(script: Path) -> str:
    """Run the script's `REPO=` line as a real file sitting beside the script.

    `BASH_SOURCE` cannot be assigned -- bash maintains it and rejects the
    write (`bash -c 'BASH_SOURCE=(x)'` exits 1) -- so there is no way to spoof
    it. The derivation therefore has to be executed from the same directory as
    the script it came from, which is why a probe file is written next to it
    and removed again.

    The probe runs with cwd `/`: a derivation that had quietly fallen back to
    `$PWD` would otherwise look correct whenever the test ran from the repo
    root, which is exactly where pytest starts.
    """
    probe = script.parent / f".repo-probe-{os.getpid()}.sh"
    probe.write_text(f'{_repo_assignment(script.read_text())}\nprintf %s "$REPO"\n')
    try:
        done = subprocess.run(
            ["bash", str(probe)], capture_output=True, text=True, cwd="/", check=True
        )
    finally:
        probe.unlink(missing_ok=True)
    # `cd && pwd` in bash reports the logical path, so on macOS a temp dir comes
    # back as /var/... while Python resolves it to /private/var/... . Both sides
    # go through realpath so the comparison is about the directory, not the
    # spelling.
    return os.path.realpath(done.stdout)


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_is_present_and_executable(name: str) -> None:
    path = REPO_ROOT / "scripts" / name
    assert path.is_file(), f"scripts/{name} is gone -- it is the only copy now"
    assert path.stat().st_mode & 0o111, f"scripts/{name} is not executable"


@pytest.mark.parametrize("name", SCRIPTS)
def test_script_parses(name: str) -> None:
    path = REPO_ROOT / "scripts" / name
    done = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("name", SCRIPTS)
def test_repo_path_follows_a_relocated_copy(name: str) -> None:
    """The load-bearing assertion: move the script, and `REPO` moves with it."""
    with tempfile.TemporaryDirectory() as tmp:
        fake_root = Path(tmp) / "elsewhere"
        (fake_root / "scripts").mkdir(parents=True)
        copy = fake_root / "scripts" / name
        shutil.copy(REPO_ROOT / "scripts" / name, copy)
        assert _resolve(copy) == os.path.realpath(fake_root)


@pytest.mark.parametrize("name", SCRIPTS)
def test_repo_path_is_the_repo_root_when_run_in_place(name: str) -> None:
    """And the derivation is still correct where the script actually lives.

    On its own this proves nothing (see the module docstring); it is the other
    half of the pair, catching a derivation that is relocatable but off by a
    directory.
    """
    assert _resolve(REPO_ROOT / "scripts" / name) == os.path.realpath(REPO_ROOT)


def test_a_hardcoded_path_fails_the_relocation_check(tmp_path: Path) -> None:
    """The negative case, in the shape that actually bit: the old literal.

    This is the exact line both scripts opened with before 2026-10-05. It has
    to come back as the literal rather than as the directory it was run from,
    or the relocation check above is decoration.
    """
    root = tmp_path / "elsewhere"
    (root / "scripts").mkdir(parents=True)
    bad = root / "scripts" / "bad.sh"
    bad.write_text("#!/bin/bash\nREPO=/Users/hevinyeh/Projects/reel-scout\n")
    assert _resolve(bad) == "/Users/hevinyeh/Projects/reel-scout"
    assert _resolve(bad) != os.path.realpath(root)


def test_derivation_ignores_the_process_cwd(tmp_path: Path) -> None:
    """A derivation that leaned on `$PWD` must not be able to pass.

    `_resolve` runs from `/`, so a script that resolved to the repo root only
    because pytest happened to start there would come back as `/` here.
    """
    stub = tmp_path / "sub" / "stub.sh"
    stub.parent.mkdir()
    stub.write_text('#!/bin/bash\nREPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n')
    assert _resolve(stub) == os.path.realpath(tmp_path)
