"""Audit E6 (2026-10-09) LOW items: option-shaped URLs and .env shell habits."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from reel_scout import config
from reel_scout.crawl import get_crawler
from reel_scout.crawl.instagram import InstagramCrawler
from reel_scout.crawl.tiktok import TikTokCrawler


# --- a URL is never an option -------------------------------------------------

def test_option_shaped_url_is_refused_before_dispatch():
    # The audit repro: re.search found "tiktok.com" inside it and dispatched.
    with pytest.raises(ValueError, match="Not a URL"):
        get_crawler("--batch-file=/x/tiktok.com")


def _argv_of(crawler, url, module):
    calls = []

    def _run(cmd, **kw):
        calls.append(list(cmd))
        return MagicMock(returncode=1, stdout="", stderr="ERROR: stubbed")

    with patch("reel_scout.crawl.%s.get_limiter" % module), \
         patch("reel_scout.crawl.%s.ytdlp.base_cmd" % module, return_value=["yt-dlp"]), \
         patch("reel_scout.crawl.%s.subprocess.run" % module, side_effect=_run):
        try:
            crawler.download(url, output_dir="/tmp")
        except Exception:
            pass
    return calls


@pytest.mark.parametrize("crawler,module,url", [
    (TikTokCrawler(), "tiktok", "https://www.tiktok.com/@u/video/123"),
    (InstagramCrawler(), "instagram", "https://www.instagram.com/reel/ABCDEFGHIJK/"),
])
def test_url_follows_a_double_dash(crawler, module, url):
    calls = _argv_of(crawler, url, module)
    assert calls
    for argv in calls:
        assert argv[-2:] == ["--", url], argv


# --- .env -----------------------------------------------------------------------

@pytest.mark.parametrize("line,expected", [
    ("export VLM_BACKEND=ollama", ("VLM_BACKEND", "ollama")),
    ("export\tVLM_BACKEND=ollama", ("VLM_BACKEND", "ollama")),
    ('WHISPER_TASK=transcribe  # or "translate" to force English output',
     ("WHISPER_TASK", "transcribe")),
    ("A=b#c", ("A", "b#c")),                       # no space before '#': kept
    ('A="x # y"', ("A", "x # y")),                 # quoted: verbatim
    ("A='x' # note", ("A", "x")),
    ("A=", ("A", "")),
    ("  KEY = value  ", ("KEY", "value")),
    ("# comment", None),
    ("", None),
    ("no equals sign", None),
])
def test_parse_env_line(line, expected):
    assert config._parse_env_line(line) == expected


def test_audit_repro_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('WHISPER_TASK=transcribe  # or "translate" to force English output\n'
                   "export VLM_BACKEND=ollama\n", encoding="utf-8")
    import os
    fake = {}
    monkeypatch.setattr(os, "environ", fake)  # nothing leaks into other tests
    config._parse_env_file(env)
    assert fake == {"WHISPER_TASK": "transcribe", "VLM_BACKEND": "ollama"}


def test_instagram_download_argv_also_ends_with_double_dash():
    """The download argv is only built after metadata succeeds, so the stub
    above (rc=1) never reaches it -- that is how it was missed."""
    calls = []

    def _run(cmd, **kw):
        calls.append(list(cmd))
        return MagicMock(returncode=0, stdout='{"id": "x", "duration": 5}', stderr="")

    url = "https://www.instagram.com/reel/ABCDEFGHIJK/"
    with patch("reel_scout.crawl.instagram.get_limiter"), \
         patch("reel_scout.crawl.instagram.ytdlp.base_cmd", return_value=["yt-dlp"]), \
         patch("reel_scout.crawl.instagram.subprocess.run", side_effect=_run), \
         patch("reel_scout.crawl.instagram.os.path.exists", return_value=True), \
         patch("reel_scout.crawl.instagram.os.path.getsize", return_value=1234), \
         patch("reel_scout.crawl.instagram.ffprobe.warn_if_not_apple_playable"):
        InstagramCrawler().download(url, output_dir="/tmp")
    dl = [c for c in calls if "--merge-output-format" in c]
    assert dl, calls
    for argv in calls:
        assert argv[-2:] == ["--", url], argv
