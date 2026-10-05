"""`pyproject.toml` has to parse, and its URLs have to be distinct.

🔴 **Why this file exists.** On 2026-10-05 an edit to `[project.urls]` added a
`Homepage`/`Issues`/`Changelog` block above keys of the same name that were
already there. TOML rejects a duplicate key, so `pip install -e .` died with
`TOMLDecodeError: Cannot overwrite a value` on all five matrix legs.

The part worth remembering is **why the local run was green: it ran before the
edit.** The suite went green, then `pyproject.toml` was changed, then the commit
went out without re-running. Nothing was wrong with the tooling — pytest reads
`pyproject.toml` itself, so a broken file fails at collection and is impossible
to miss. The gap was in the order of operations.

So this module is not really a new safety net; collection already was one. What
it adds is a *named* failure. `tomllib` reports `Cannot overwrite a value` with
a line and column and no key, as a collection error with no test name attached
— a slow thing to read. `test_project_urls_have_no_duplicate_keys` says which
key was repeated.

It is also not a substitute for the install step, which is the only thing that
can catch a dependency that does not resolve.
"""
from __future__ import annotations

import io
import os
import re
from typing import Dict

try:  # 3.11+
    import tomllib
except ModuleNotFoundError:  # 3.9 / 3.10 — the declared floor is 3.9
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(ROOT, "pyproject.toml")


def _load() -> Dict[str, object]:
    with io.open(PYPROJECT, "rb") as fh:
        return tomllib.load(fh)


def test_pyproject_parses() -> None:
    assert _load()["project"]


def test_project_urls_have_no_duplicate_keys() -> None:
    """The parse above already rejects duplicates — this names the failure.

    `tomllib` raises `TOMLDecodeError: Cannot overwrite a value` with a line
    and column but no key name, which is a slow thing to read at 2am. Scanning
    the raw text tells you *which* key was repeated.
    """
    with io.open(PYPROJECT, encoding="utf-8") as fh:
        text = fh.read()
    block = re.search(r"^\[project\.urls\]\n(.*?)(?=^\[|\Z)", text, re.S | re.M)
    assert block, "pyproject.toml has no [project.urls] section"
    keys = re.findall(r"^([A-Za-z][A-Za-z0-9_-]*)\s*=", block.group(1), re.M)
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert not dupes, "duplicate keys in [project.urls]: %s" % ", ".join(dupes)


def test_the_duplicate_scan_can_actually_fire() -> None:
    """The negative case: the regex above must not silently match nothing.

    A `[project.urls]` section that stopped matching (renamed, reformatted)
    would make the duplicate test vacuous while still reading as a pass, which
    is the exact shape of the bug this module was written for.
    """
    sample = "[project.urls]\nHomepage = \"a\"\nIssues = \"b\"\nHomepage = \"c\"\n\n[next]\n"
    block = re.search(r"^\[project\.urls\]\n(.*?)(?=^\[|\Z)", sample, re.S | re.M)
    assert block
    keys = re.findall(r"^([A-Za-z][A-Za-z0-9_-]*)\s*=", block.group(1), re.M)
    assert sorted({k for k in keys if keys.count(k) > 1}) == ["Homepage"]


def test_homepage_points_at_the_site_not_the_repo() -> None:
    """PyPI renders `Homepage` as the project's main link.

    That link is where most people meet this project, and a README cannot
    answer "how is this different from pasting the URL into an AI". The repo is
    still one click away as `Repository`.
    """
    urls = _load()["project"]["urls"]  # type: ignore[index]
    assert urls["Homepage"] == "https://vulture-s.github.io/reel-scout/"
    assert urls["Repository"] == "https://github.com/vulture-s/reel-scout"
