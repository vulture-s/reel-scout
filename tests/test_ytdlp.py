"""yt-dlp resolution + error surfacing (roadmap 5B)."""
from __future__ import annotations

import sys

from reel_scout import config
from reel_scout.crawl import ytdlp


def test_base_cmd_honors_explicit_override(monkeypatch):
    monkeypatch.setattr(config, "YTDLP_BIN", "/opt/custom/yt-dlp")
    ytdlp.base_cmd.cache_clear()
    try:
        assert ytdlp.base_cmd() == ("/opt/custom/yt-dlp",)
        assert ytdlp.cmd("--version") == ["/opt/custom/yt-dlp", "--version"]
    finally:
        ytdlp.base_cmd.cache_clear()


def test_base_cmd_prefers_package_module_over_path(monkeypatch):
    # yt_dlp is a dependency, so with no override we must invoke *this*
    # interpreter's module, not a bare PATH binary that could be stale.
    monkeypatch.setattr(config, "YTDLP_BIN", "")
    ytdlp.base_cmd.cache_clear()
    try:
        assert ytdlp.base_cmd() == (sys.executable, "-m", "yt_dlp")
    finally:
        ytdlp.base_cmd.cache_clear()


def test_format_error_surfaces_error_line_under_leading_warning():
    # The exact footgun: the real ERROR sits *after* a deprecation warning, so a
    # blind head-cut showed the warning and hid the failure.
    stderr = (
        "WARNING: [youtube] Deprecated Feature: Support for Python version "
        "3.10 has been deprecated ...\n"
        "ERROR: unable to download video data: HTTP Error 429: Too Many Requests"
    )
    out = ytdlp.format_error(stderr)
    assert "HTTP Error 429" in out
    assert out.startswith("ERROR:")


def test_format_error_falls_back_to_tail_when_no_error_line():
    stderr = "line one\nline two\nthe actual failure is here at the end"
    out = ytdlp.format_error(stderr)
    assert "at the end" in out


def test_format_error_hints_update_on_broken_extractor():
    out = ytdlp.format_error("ERROR: Unable to extract player response")
    assert "-U" in out and "outdated" in out


def test_format_error_no_hint_on_ordinary_error():
    out = ytdlp.format_error("ERROR: HTTP Error 429: Too Many Requests")
    assert "-U" not in out


def test_format_error_empty():
    assert ytdlp.format_error("") == ""
