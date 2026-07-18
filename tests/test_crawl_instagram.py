"""InstagramCrawler.browse + instaloader fallback (roadmap 3A)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from reel_scout.crawl.base import VideoMeta
from reel_scout.crawl.instagram import InstagramCrawler


def _patch_basecmd():
    return patch("reel_scout.crawl.instagram.ytdlp.base_cmd", return_value=["yt-dlp"])


def test_browse_success_no_fallback():
    c = InstagramCrawler()
    ok = MagicMock()
    ok.returncode = 0
    ok.stdout = ('{"id": "xyz", "url": "https://www.instagram.com/reel/xyz/", '
                 '"uploader": "u", "duration": 12}')
    with _patch_basecmd(), \
         patch("reel_scout.crawl.instagram.subprocess.run", return_value=ok), \
         patch.object(InstagramCrawler, "_browse_instaloader") as fb:
        out = c.browse("https://www.instagram.com/someuser/", limit=5)
    fb.assert_not_called()
    assert out[0].platform_id == "xyz"


def test_browse_falls_back_to_instaloader_on_ytdlp_failure():
    c = InstagramCrawler()
    fail = MagicMock()
    fail.returncode = 1
    fail.stderr = "ERROR: Instagram extractor broke"
    fake = [VideoMeta(platform="instagram", platform_id="abc",
                      url="https://www.instagram.com/reel/abc/")]
    with _patch_basecmd(), \
         patch("reel_scout.crawl.instagram.subprocess.run", return_value=fail), \
         patch.object(InstagramCrawler, "_browse_instaloader", return_value=fake) as fb:
        out = c.browse("https://www.instagram.com/someuser/", limit=5)
    fb.assert_called_once()
    assert out == fake


def test_browse_surfaces_ytdlp_error_when_instaloader_missing():
    c = InstagramCrawler()
    fail = MagicMock()
    fail.returncode = 1
    fail.stderr = "ERROR: Instagram extractor broke"
    with _patch_basecmd(), \
         patch("reel_scout.crawl.instagram.subprocess.run", return_value=fail), \
         patch.object(InstagramCrawler, "_browse_instaloader",
                      side_effect=ImportError("no instaloader")):
        with pytest.raises(RuntimeError, match="yt-dlp browse failed"):
            c.browse("https://www.instagram.com/someuser/", limit=5)
