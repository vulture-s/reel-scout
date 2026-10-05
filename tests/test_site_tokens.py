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

Deliberately narrow: only the tokens the site actually restates are checked,
and one token is asserted to *differ*. `--paper-col` is the width the ruled
lines span, and it is the whole reason the texture rule can be byte-identical
in both files: the tool is wide (`--col-tool`), the site is editorial
(`--col-wide`). A test that demanded the two files be identical would be wrong,
not strict.
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
    # 紙質。2026-10-05 下沉到 theme.py，所以 viewer / inspector / 匯出單檔與官網
    # 用的是同一組值 —— 它們必須相等，而不是各自好看。
    "--paper-fiber-opacity", "--paper-rule-step", "--paper-rule-ink",
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


SITE_ONLY = ["--desk", "--margin-rule", "--margin-x", "--col-site"]


@pytest.mark.parametrize("token", SITE_ONLY)
def test_sheet_tokens_belong_to_the_site_only(token: str) -> None:
    """The sheet-on-a-desk tokens must not be "harmonised" into the tool.

    The site draws the content column as a sheet of paper lying on a slightly
    darker desk, with a notebook margin rule down its left side. That reads
    well on an editorial column. The tool is a wide data surface -- the library
    view is one full-width table -- so a margin rule there would land on top of
    the first column and a desk border would crop the very width that view was
    widened for (see `theme.py`'s narrated deviation on `--col-tool`).

    The natural tidy-up is to move these into `theme.py` so the two files
    match. That is why it is asserted rather than left to a comment.
    """
    site = _decls(_site_css())
    theme_tokens = _theme_tokens()
    assert token in site, "%s is missing from the site stylesheet" % token
    assert token not in theme_tokens, (
        "%s belongs to the site only -- see the docstring" % token
    )


def test_paper_col_is_the_one_token_that_differs() -> None:
    """The ruled lines span the content column, and the two columns differ.

    This is asserted rather than left implicit because the obvious "tidy-up"
    is to make the two files identical. Doing that would either draw the site's
    ruled lines out to 2400px (past the text, into margins meant to be empty)
    or pull the tool's in to 1080px (a stripe down the middle of a 2400px
    library table). Neither is a cosmetic difference.
    """
    site = _decls(_site_css())
    theme_tokens = _theme_tokens()
    assert site["--paper-col"] == "var(--col-site)"
    assert theme_tokens["--paper-col"] == "var(--col-tool)"
    assert site["--paper-col"] != theme_tokens["--paper-col"]
