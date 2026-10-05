"""Content declared in an .astro frontmatter must actually be rendered.

🔴 Why this exists: `index.astro` carried two content arrays -- `diffs` (four
differentiators) and `layers` (the five-signal reliability table, which the
README calls the tool's core claim) -- that were written, reviewed, kept in sync
with the code, and **never put on the page**. Nothing failed. The build was
green, every link resolved, and a source-level grep for their text found it.

That is the expensive shape of this bug: dead copy is indistinguishable from
live copy in everything except the rendered page. It also fed a CI gate a false
pass (the front-page platform check, fixed in the same series) because the words
were in the file.

⚠️ Deliberately a *declaration* check, not a text check. Asserting specific
sentences appear would break on every edit; asserting that a declared array is
referenced somewhere in the template catches the failure without owning the
copy.
"""
import pathlib
import re

import pytest

PAGES = sorted((pathlib.Path(__file__).resolve().parent.parent
                / "site" / "src" / "pages").glob("*.astro"))

# arrays that exist to configure the build rather than to be rendered
EXEMPT = {"base"}


def _split_frontmatter(text):
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    return parts[1], parts[2]


@pytest.mark.skipif(not PAGES, reason="site not checked out")
@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_declared_content_arrays_are_rendered(page):
    front, body = _split_frontmatter(page.read_text(encoding="utf-8"))
    names = re.findall(r"^const\s+([A-Za-z_$][\w$]*)\s*=\s*\[", front, re.M)
    # ⚠️ Match a *use*, not the bare name: `class="diffs"` contains "diffs", so a
    # word-boundary search passes even with every `{diffs.map(...)}` deleted.
    # That was the first version of this test, and its negative check caught it.
    dead = []
    for n in names:
        if n in EXEMPT:
            continue
        used = re.search(r"[{(]\s*%s\b" % re.escape(n), body) or \
            re.search(r"\b%s\s*\.\s*map\s*\(" % re.escape(n), body)
        if not used:
            dead.append(n)
    assert not dead, (
        "%s declares %s and never renders them -- the copy is written but "
        "nobody sees it" % (page.name, dead))
