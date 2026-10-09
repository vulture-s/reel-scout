"""yt-dlp never gets the user's own cookies file (2026-10-09).

yt-dlp writes its cookie jar back to `--cookies <file>` when it exits, by
truncating the file in place (`open(file, 'w')`) and rewriting it -- not
atomically. Two reel-scout runs at once (a batch plus an MCP analyze, two batch
workers, reel-queue-consume) therefore race on the one file: measured with four
processes loading and closing a 300-cookie jar for 20 s, 3 of 4 died with
"does not look like a Netscape format cookies file" (reel-scout reports that
as "need cookies?"), and the file ended with **60** cookies. The partial jar a
reader saw is what it wrote back; the IG session is gone until the user
re-exports.

Each invocation now gets a private copy; the original is only ever read.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys

import pytest

from reel_scout import config
from reel_scout.crawl import instagram, ytdlp

JAR = "# Netscape HTTP Cookie File\n" + "".join(
    ".instagram.com\tTRUE\t/\tTRUE\t2000000000\tc%03d\t%s\n" % (i, "v" * 40)
    for i in range(50))


@pytest.fixture
def jar(tmp_path, monkeypatch):
    p = tmp_path / "cookies.txt"
    p.write_text(JAR, encoding="utf-8")
    monkeypatch.setenv("IG_COOKIES_FILE", str(p))
    monkeypatch.setattr(config, "IG_COOKIES_FILE", str(p))
    return p


def test_yt_dlp_is_handed_a_copy_not_the_original(jar):
    args = instagram._cookie_args()
    assert args[0] == "--cookies"
    copy = args[1]
    assert os.path.abspath(copy) != os.path.abspath(str(jar))
    with open(copy, encoding="utf-8") as f:
        assert f.read() == JAR


def test_the_copy_is_private(jar):
    copy = instagram._cookie_args()[1]
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(copy).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(os.path.dirname(copy)).st_mode) == 0o700


def test_each_invocation_gets_its_own_copy(jar):
    a = instagram._cookie_args()[1]
    b = instagram._cookie_args()[1]
    assert a != b


def test_what_yt_dlp_writes_back_never_reaches_the_original(jar):
    """Drive the real yt-dlp cookie jar (no network): load and close, which is
    the save-on-exit every invocation performs, against the path we hand it --
    after first truncating that path the way a racing writer would."""
    copy = instagram._cookie_args()[1]
    open(copy, "w").close()                      # what a reader mid-race sees
    code = (
        "import sys\n"
        "from yt_dlp import YoutubeDL\n"
        "with YoutubeDL({'cookiefile': sys.argv[1], 'quiet': True}) as y:\n"
        "    len(y.cookiejar)\n")
    subprocess.run([sys.executable, "-c", code, copy], capture_output=True, timeout=60)
    assert jar.read_text(encoding="utf-8") == JAR


def test_copies_are_cleaned_up(jar):
    copy = instagram._cookie_args()[1]
    ytdlp._cleanup_cookie_copies()
    assert not os.path.exists(copy)
