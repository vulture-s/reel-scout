"""The site's paper tokens must be the ones the tool itself uses.

🔴 **Why this file exists.** `site/src/styles/paper.css` restates the colour and
type tokens that live in `reel_scout/theme.py`. It has to: the site builds with
Astro on GitHub Actions, where there is no Python, so the values cannot be read
out of `theme.py` at build time.

A copy drifts. The way it drifts here is specific and not visible in a diff
review: someone adjusts `--ink` in `theme.py` because the viewer's text reads
too soft, the site keeps the old value, and now the official site and the tool
it documents are two slightly different shades of brown that nobody can see
side by side. So the copy is asserted rather than trusted -- the same move as
`test_docs_are_current.py`, applied to CSS instead of prose.

Deliberately narrow: only the tokens the site actually restates are checked.
The site has paper-texture tokens of its own (`--paper-fiber-opacity`,
`--paper-rule-step`, `--paper-rule-ink`) that `theme.py` has never had, and the
site uses the editorial `--col`/`--col-wide` rather than the tool's wide
`--col-tool`. Those differences are intentional and narrated in both files; a
test that demanded the two be identical would be wrong, not strict.
"""
from __future__ import annotations

import io
import os
import re
from typing import Dict

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE_CSS = os.path.join(ROOT, "site", "src", "styles", "paper.css")

# 只比這些 —— 其餘的差異是刻意的，見檔頭。
SHARED = [
    "--bg", "--surface", "--surface-2",
    "--ink", "--ink-2",
    "--rule", "--rule-soft", "--quiet", "--frame",
    "--display", "--sans", "--mono",
    "--col", "--col-wide",
]


def _decls(css: str) -> Dict[str, str]:
    """Every `--name:value` in the text, whitespace-normalised.

    Comments are stripped first: `theme.py` carries long `/* ... */` rationale
    blocks between declarations, and one of them mentions `--col-tool`.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: Dict[str, str] = {}
    for name, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;}]+)", css):
        out[name] = " ".join(value.split())
    return out


def _site_css() -> str:
    with io.open(SITE_CSS, encoding="utf-8") as fh:
        return fh.read()


def _theme_tokens() -> Dict[str, str]:
    from reel_scout import theme

    return _decls(theme.TOKENS)


def test_the_site_stylesheet_exists() -> None:
    """A missing file would make every parametrised check below vacuous.

    Without this, deleting `paper.css` turns the whole module green: `_decls`
    would raise inside each case, which pytest reports as an error rather than
    a pass -- but a rename that moved the file somewhere else and left a stub
    would not. Assert the thing is where the build expects it.
    """
    assert os.path.isfile(SITE_CSS), SITE_CSS


@pytest.mark.parametrize("token", SHARED)
def test_site_token_matches_theme(token: str) -> None:
    site = _decls(_site_css())
    theme_tokens = _theme_tokens()
    assert token in theme_tokens, "%s is no longer in theme.py -- update SHARED" % token
    assert token in site, "%s is missing from site/src/styles/paper.css" % token
    assert site[token] == theme_tokens[token], (
        "%s drifted: site has %r, theme.py has %r" % (token, site[token], theme_tokens[token])
    )


def test_the_comparison_can_actually_fail() -> None:
    """The negative case.

    `_decls` strips comments and normalises whitespace, which is exactly the
    kind of helper that can end up normalising two different values into the
    same string. Feed it a value that differs only in the way a real edit would
    differ, and require that it survives as a difference.
    """
    a = _decls(":root{--ink:#231916}")
    b = _decls(":root{--ink:#241916}")
    assert a["--ink"] != b["--ink"]
    # ...while cosmetic differences that are not edits do NOT read as drift.
    c = _decls(":root{\n  /* note */\n  --ink:  #231916 ;\n}")
    assert c["--ink"] == a["--ink"]


def test_the_site_keeps_its_own_paper_tokens() -> None:
    """The texture tokens are the site's alone and must not be 'fixed' into theme.py.

    If someone later copies them across to make the two files identical, the
    viewer and the take-home export would start rendering a page texture behind
    keyframes and waveforms -- which is the one thing `theme.py`'s canon ('the
    chrome is quiet so the content is loud') tells them not to do.
    """
    site = _decls(_site_css())
    theme_tokens = _theme_tokens()
    for token in ("--paper-fiber-opacity", "--paper-rule-step", "--paper-rule-ink"):
        assert token in site, token
        assert token not in theme_tokens, (
            "%s belongs to the site only -- see the docstring" % token
        )
