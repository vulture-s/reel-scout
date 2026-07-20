"""Lay the agent-facing half of the tool down where Claude will find it.

`pip install reel-scout` installs a CLI. It does not install a skill, and the
skill is what makes the CLI usable by an agent — SKILL.md carries the pipeline
procedure and the L0/L1/L2 tier rules, `commands/scout.md` is the slash command,
`prompts/` is the reverse-decode pack, `scripts/setup.py` is the preflight
SKILL.md Step 0 shells out to. Until this existed, all of that shipped only to
people who cloned the repo, which is the opposite of who needs it.

Two source layouts are supported deliberately:

- **installed** — the assets are vendored into the wheel at `reel_scout/skill/`
  (see the force-include block in pyproject.toml).
- **clone** — no vendored copy, so fall back to the repo root. A contributor
  running `pip install -e .` gets the live files, not a stale snapshot.
"""

import os
import shutil
from typing import List, Optional, Tuple

#: Where Claude Code looks for user-level skills.
DEFAULT_DEST = os.path.join("~", ".claude", "skills", "reel-scout")

#: Everything an agent needs, relative to whichever source root wins.
ASSETS = ("SKILL.md", "commands", "prompts", "scripts")


def bundled_root() -> Optional[str]:
    """The vendored copy inside the installed package, if this is a wheel install."""
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skill")
    return root if os.path.isfile(os.path.join(root, "SKILL.md")) else None


def repo_root() -> Optional[str]:
    """The working tree, for a clone / editable install."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return root if os.path.isfile(os.path.join(root, "SKILL.md")) else None


def source_root() -> Tuple[Optional[str], str]:
    """(path, which) where which is 'bundled' | 'clone' | 'missing'."""
    bundled = bundled_root()
    if bundled:
        return bundled, "bundled"
    repo = repo_root()
    if repo:
        return repo, "clone"
    return None, "missing"


def _present(root: str) -> List[str]:
    """Asset names that actually exist under `root`.

    `scripts/` is only partly vendored (just setup.py), and a clone carries more
    than the skill needs, so copying by name and skipping absences keeps the two
    layouts producing the same destination tree.
    """
    return [a for a in ASSETS if os.path.exists(os.path.join(root, a))]


def install(dest: str = DEFAULT_DEST, force: bool = False) -> Tuple[str, List[str]]:
    """Copy the skill assets to `dest`. Returns (resolved_dest, copied names).

    Refuses a non-empty destination unless `force`: the user may have edited the
    skill in place, and silently overwriting that is worse than making them ask.
    """
    root, which = source_root()
    if which == "missing":
        raise RuntimeError(
            "skill assets not found — this build shipped without them; "
            "reinstall with `pip install -U reel-scout` or run from a clone")

    dest = os.path.abspath(os.path.expanduser(dest))
    if os.path.isdir(dest) and os.listdir(dest) and not force:
        raise RuntimeError(
            "%s already exists and is not empty — pass --force to overwrite it" % dest)

    names = _present(root)
    if not names:
        raise RuntimeError("no skill assets under %s" % root)

    os.makedirs(dest, exist_ok=True)
    copied = []
    for name in names:
        src = os.path.join(root, name)
        target = os.path.join(dest, name)
        if os.path.isdir(src):
            if os.path.isdir(target):
                shutil.rmtree(target)
            # A clone's scripts/ carries more than the skill uses; take only what
            # SKILL.md actually shells out to so the installed tree stays honest.
            if name == "scripts":
                os.makedirs(target, exist_ok=True)
                setup = os.path.join(src, "setup.py")
                if not os.path.isfile(setup):
                    continue
                shutil.copy2(setup, os.path.join(target, "setup.py"))
            else:
                shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
        copied.append(name)

    return dest, copied
