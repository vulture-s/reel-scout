"""vulture shell: tokens, bundled fonts, and the two font-delivery modes."""
from __future__ import annotations

import os

from reel_scout import theme


def test_tokens_carry_brand_values():
    css = theme.stylesheet()
    # Values come from the brand SSOT; drifting them is a real regression.
    assert "--bg:#f1efe9" in css
    assert "--ink:#231916" in css
    assert "Archivo Black" in css and "JetBrains Mono" in css


def test_shell_stays_mono_no_cyan_fill():
    """Canon caps cyan at the tv./wordmark, which reel-scout doesn't carry, so
    the shell must not spend the accent anywhere."""
    css = theme.stylesheet()
    # the ramp is declared (so an ink panel can't accidentally get cyan) but
    # never actually painted onto chrome
    assert "--cyan-raw:#26B6DA" in css
    assert "fill:var(--accent)" not in css
    assert "background:var(--accent)" not in css


def test_bundled_font_files_exist():
    for _family, filename, _weight in theme._FACES:
        assert os.path.exists(os.path.join(theme.FONT_DIR, filename)), filename


def test_font_face_server_mode_links_not_embeds():
    css = theme.font_face_css(embed=False)
    assert "url(/font/archivo-black-400.woff2)" in css
    assert "base64" not in css


def test_font_face_export_mode_embeds():
    css = theme.font_face_css(embed=True)
    assert "data:font/woff2;base64," in css
    assert "url(/font/" not in css


def test_font_path_rejects_traversal():
    # basename-only, so a crafted name can't escape the asset dir
    assert theme.font_path("../../../../etc/passwd").startswith(theme.FONT_DIR)
    assert theme.font_path("../../etc/passwd").endswith("passwd")
    assert not os.path.exists(theme.font_path("../../../../etc/passwd"))


def test_cjk_subset_degrades_without_source():
    # No source font configured → empty, so an export falls back to the reader's
    # system CJK face instead of failing.
    assert theme.cjk_subset("中文測試", source_ttf="/nonexistent-font.ttf") == b""
    assert theme.cjk_subset("ascii only") == b""


def test_stylesheet_can_inline_a_cjk_subset():
    css = theme.stylesheet(cjk_woff2=b"fake-woff2-bytes")
    assert "Noto Sans TC" in css
    assert "data:font/woff2;base64," in css
