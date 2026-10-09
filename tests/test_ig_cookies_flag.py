"""`--cookies` / MCP `crawl.cookies` must reach yt-dlp's argv.

Audit E6 (2026-10-09): all three entry points wrote os.environ after
config.IG_COOKIES_FILE had been frozen at import, so yt-dlp never saw
`--cookies` and the failure message then asked "need cookies?".
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from reel_scout import cli, config
from reel_scout.crawl import instagram

IG = "https://www.instagram.com/reel/ABCDEFGHIJK/"


@pytest.fixture
def no_cookies_env(monkeypatch):
    monkeypatch.delenv("IG_COOKIES_FILE", raising=False)
    monkeypatch.setattr(config, "IG_COOKIES_FILE", "")


@pytest.fixture
def recorded():
    """Stub yt-dlp (no network) and record every argv it was given."""
    calls = []

    def _run(cmd, **kw):
        calls.append(list(cmd))
        return MagicMock(returncode=1, stdout="", stderr="ERROR: stubbed, no network")

    with patch("reel_scout.crawl.instagram.get_limiter"), \
         patch("reel_scout.crawl.instagram.ytdlp.base_cmd", return_value=["yt-dlp"]), \
         patch("reel_scout.crawl.instagram.subprocess.run", side_effect=_run):
        yield calls


def _cookie_values(calls):
    return [c[c.index("--cookies") + 1] for c in calls if "--cookies" in c]


def test_cli_crawl_cookies_flag_reaches_ytdlp(temp_db, no_cookies_env, recorded,
                                             tmp_path, monkeypatch):
    jar = tmp_path / "cookies.txt"
    jar.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(sys, "argv", ["reel-scout", "crawl", IG, "--cookies", str(jar)])
    try:
        cli.main()
    except SystemExit:
        pass
    assert recorded, "yt-dlp was never invoked"
    assert _cookie_values(recorded) == [str(jar)] * len(recorded)


def test_cli_crawl_missing_cookies_file_is_an_error(temp_db, no_cookies_env, recorded,
                                                    tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["reel-scout", "crawl", IG,
                                      "--cookies", str(tmp_path / "nope.txt")])
    try:
        cli.main()
    except SystemExit:
        pass
    assert "cookies file not found" in capsys.readouterr().out
    assert recorded == []  # refused before any request


def test_mcp_crawl_cookies_reach_ytdlp_and_do_not_leak(temp_db, no_cookies_env,
                                                        recorded, tmp_path):
    from reel_scout.mcp import tools
    jar = tmp_path / "cookies.txt"
    jar.write_text("# Netscape HTTP Cookie File\n")
    tools.call_tool("crawl", {"urls": [IG], "cookies": str(jar)})
    assert recorded and _cookie_values(recorded) == [str(jar)] * len(recorded)
    # The MCP server is long-lived: the next call must not inherit the jar.
    assert "IG_COOKIES_FILE" not in os.environ
    del recorded[:]
    tools.call_tool("crawl", {"urls": [IG]})
    assert recorded and _cookie_values(recorded) == []


def test_mcp_crawl_missing_cookies_file_is_an_error(temp_db, no_cookies_env, recorded,
                                                    tmp_path):
    from reel_scout.mcp import tools
    res = tools.call_tool("crawl", {"urls": [IG], "cookies": str(tmp_path / "nope.txt")})
    assert res.get("isError")
    assert "cookies file not found" in res["content"][0]["text"]
    assert recorded == []


def test_configured_but_missing_cookies_warns_and_continues(no_cookies_env, monkeypatch,
                                                           tmp_path, capsys):
    monkeypatch.setenv("IG_COOKIES_FILE", str(tmp_path / "gone.txt"))
    assert instagram._cookie_args() == []
    assert "does not exist" in capsys.readouterr().err


def test_env_set_after_import_wins(no_cookies_env, monkeypatch, tmp_path):
    jar = tmp_path / "c.txt"
    jar.write_text("x")
    monkeypatch.setenv("IG_COOKIES_FILE", str(jar))
    assert instagram._cookie_args() == ["--cookies", str(jar)]


def test_import_time_value_still_works_without_env(no_cookies_env, monkeypatch, tmp_path):
    jar = tmp_path / "c.txt"
    jar.write_text("x")
    monkeypatch.setattr(config, "IG_COOKIES_FILE", str(jar))
    assert instagram._cookie_args() == ["--cookies", str(jar)]


def test_cli_browse_cookies_flag_reaches_ytdlp(no_cookies_env, tmp_path, monkeypatch):
    """`browse --cookies` is the profile-listing path -- the one that most
    needs a login -- and was a no-op the same way as `crawl --cookies`."""
    jar = tmp_path / "cookies.txt"
    jar.write_text("# Netscape HTTP Cookie File\n")
    calls = []

    def _run(cmd, **kw):
        calls.append(list(cmd))
        # rc 0 + empty listing: no instaloader fallback, no network.
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sys, "argv", ["reel-scout", "browse",
                                      "https://www.instagram.com/someuser/",
                                      "--cookies", str(jar)])
    with patch("reel_scout.crawl.instagram.get_limiter"), \
         patch("reel_scout.crawl.instagram.ytdlp.base_cmd", return_value=["yt-dlp"]), \
         patch("reel_scout.crawl.instagram.subprocess.run", side_effect=_run):
        try:
            cli.main()
        except SystemExit:
            pass
    assert calls, "yt-dlp was never invoked"
    assert _cookie_values(calls) == [str(jar)] * len(calls)
