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


# --- URL forms -------------------------------------------------------------
#
# Instagram's own share button emits the account-scoped form
# (instagram.com/<handle>/reel/<code>/). A 24-clip batch run on 2026-07-25 hit
# this: 20 of 21 collected links were account-scoped and every one raised
# "Cannot extract Instagram post ID". Single-URL use never surfaced it because
# links pasted from a browser address bar are canonical.

CANONICAL = "https://www.instagram.com/reel/Da3UcDsudRN/"
ACCOUNT_SCOPED = "https://www.instagram.com/zacharywinterton/reel/Da3UcDsudRN/"


@pytest.mark.parametrize("url", [
    CANONICAL,
    ACCOUNT_SCOPED,
    "https://www.instagram.com/zacharywinterton/reels/Da3UcDsudRN/",
    "https://www.instagram.com/some.user_1/p/Da3UcDsudRN/",
    "https://www.instagram.com/p/Da3UcDsudRN/",
    "https://www.instagram.com/reels/Da3UcDsudRN/",
])
def test_every_share_form_yields_the_same_post_id(url):
    assert InstagramCrawler().extract_id(url) == "Da3UcDsudRN"


def test_account_scoped_and_canonical_are_the_same_post():
    c = InstagramCrawler()
    assert c.extract_id(ACCOUNT_SCOPED) == c.extract_id(CANONICAL)


@pytest.mark.parametrize("url", [
    "https://www.instagram.com/someuser/",
    "https://www.instagram.com/someuser",
    "https://www.instagram.com/someuser/reels/",
])
def test_profile_pages_are_still_profiles_not_posts(url):
    """The broader post regex must not start swallowing profile/tab URLs —
    that would route a browse request into a single-post download."""
    c = InstagramCrawler()
    assert c.is_profile_url(url) is True


@pytest.mark.parametrize("url", [CANONICAL, ACCOUNT_SCOPED])
def test_post_urls_are_never_treated_as_profiles(url):
    assert InstagramCrawler().is_profile_url(url) is False


def test_a_url_with_no_post_code_still_raises():
    with pytest.raises(ValueError, match="Cannot extract Instagram post ID"):
        InstagramCrawler().extract_id("https://www.instagram.com/someuser/reels/")


# --- duration --------------------------------------------------------------
#
# yt-dlp routinely omits duration for Instagram. Storing 0.0 is a *real* value,
# so the COALESCE-based repair paths downstream consider duration known and
# never correct it — 20/20 reels in the 2026-07-25 batch landed with 0.0.


def _download_mocks(info_json):
    meta = MagicMock(returncode=0, stdout=info_json)
    dl = MagicMock(returncode=0)
    return [meta, dl]


def _run_download(info_json, probed):
    c = InstagramCrawler()
    with _patch_basecmd(), \
         patch("reel_scout.crawl.instagram.get_limiter"), \
         patch("reel_scout.crawl.instagram.subprocess.run",
               side_effect=_download_mocks(info_json)), \
         patch("reel_scout.crawl.instagram.os.path.exists", return_value=True), \
         patch("reel_scout.crawl.instagram.os.path.getsize", return_value=1234), \
         patch("reel_scout.crawl.instagram.ffprobe.probe_duration",
               return_value=probed) as probe,          patch("reel_scout.crawl.instagram.ffprobe.warn_if_not_apple_playable"):
        meta = c.download(CANONICAL, output_dir="/tmp")
    return meta, probe


def test_missing_duration_is_measured_from_the_downloaded_file():
    meta, probe = _run_download('{"id": "x", "uploader": "u"}', 13.14)
    probe.assert_called_once()
    assert meta.duration_sec == pytest.approx(13.14)


def test_null_duration_is_also_measured_not_crashed_on():
    meta, probe = _run_download('{"id": "x", "duration": null}', 9.5)
    probe.assert_called_once()
    assert meta.duration_sec == pytest.approx(9.5)


def test_a_duration_yt_dlp_does_report_is_trusted_without_probing():
    meta, probe = _run_download('{"id": "x", "duration": 42}', 999.0)
    probe.assert_not_called()
    assert meta.duration_sec == pytest.approx(42.0)


def test_an_unprobeable_file_stays_zero_rather_than_inventing_a_number():
    meta, _ = _run_download('{"id": "x"}', None)
    assert meta.duration_sec == 0.0


# --- the drift PR #78 did not cover (2026-08-25) -------------------------
#
# This file's crawler spent months on a bare "bestvideo+bestaudio/best" -- no
# codec condition at all, not even the av01 exclusion youtube.py carried. 88 of
# the 103 files that would not play on an iPad came through it. Nothing failed
# when that happened, because nothing asserted anything about the selector.


def test_download_asks_for_a_codec_apple_can_decode():
    """Assert on the argv this crawler actually sends, not on the shared helper.

    A test that only exercises ytdlp.apple_safe_format() would stay green while
    this module went back to a bare selector -- which is precisely the failure
    being prevented.
    """
    c = InstagramCrawler()
    calls = []

    def _rec(cmd, **kw):
        calls.append(cmd)
        return MagicMock(returncode=0, stdout='{"id": "x", "duration": 5}')

    with _patch_basecmd(),          patch("reel_scout.crawl.instagram.get_limiter"),          patch("reel_scout.crawl.instagram.subprocess.run", side_effect=_rec),          patch("reel_scout.crawl.instagram.os.path.exists", return_value=True),          patch("reel_scout.crawl.instagram.os.path.getsize", return_value=1234),          patch("reel_scout.crawl.instagram.ffprobe.warn_if_not_apple_playable"):
        c.download(CANONICAL, output_dir="/tmp")

    dl = [x for x in calls if "--merge-output-format" in x][0]
    fmt = dl[dl.index("-f") + 1]
    alts = fmt.split("/")
    assert "vcodec^=avc1" in alts[0]
    assert "acodec^=mp4a" in alts[0]
    # and the tail stays unconstrained, so a VP9-only reel still enters the library
    assert any("vcodec" not in a for a in alts[3:])


def test_download_measures_the_file_that_actually_landed():
    """The selector states a preference; yt-dlp may walk down to the
    unconstrained tail. Something has to look at what arrived."""
    c = InstagramCrawler()

    with _patch_basecmd(),          patch("reel_scout.crawl.instagram.get_limiter"),          patch("reel_scout.crawl.instagram.subprocess.run",
               return_value=MagicMock(returncode=0, stdout='{"id": "x", "duration": 5}')),          patch("reel_scout.crawl.instagram.os.path.exists", return_value=True),          patch("reel_scout.crawl.instagram.os.path.getsize", return_value=1234),          patch("reel_scout.crawl.instagram.ffprobe.warn_if_not_apple_playable") as chk:
        c.download(CANONICAL, output_dir="/tmp")

    chk.assert_called_once()


# A photo carousel fails once per slide with "No video formats found!", which
# the generic extractor hint reads as "update yt-dlp / need cookies?".

_PHOTO_STDERR = "\n".join(
    "ERROR: [Instagram] Dbpz6%s: No video formats found!; please report this issue" % i
    for i in range(3)
)


def _metadata_failure(stderr):
    c = InstagramCrawler()
    fail = MagicMock(returncode=1, stdout="", stderr=stderr)
    with _patch_basecmd(), \
         patch("reel_scout.crawl.instagram.get_limiter"), \
         patch("reel_scout.crawl.instagram.subprocess.run", return_value=fail):
        with pytest.raises(RuntimeError) as exc:
            c.download("https://www.instagram.com/p/Dbp0bVtIGoh/", output_dir="/tmp")
    return str(exc.value)


def test_photo_carousel_says_no_video_not_update_yt_dlp():
    msg = _metadata_failure(_PHOTO_STDERR)
    assert "no video" in msg and "3 item" in msg
    assert "yt-dlp -U" not in msg and "need cookies" not in msg


def test_a_mixed_failure_keeps_the_real_error_and_hint():
    msg = _metadata_failure(_PHOTO_STDERR + "\nERROR: [Instagram] x: login required")
    assert "need cookies" in msg and "login required" in msg


_DNS_STDERR = ("ERROR: [Instagram] DZWQLaksluN: Unable to download webpage: "
               "HTTPSConnection(host='www.instagram.com', port=443): Failed to resolve "
               "'www.instagram.com' ([Errno 8] nodename nor servname provided, or not known)")


def test_a_dns_failure_is_reported_as_network_not_cookies_or_yt_dlp():
    msg = _metadata_failure(_DNS_STDERR)
    assert "(network)" in msg and "network failed" in msg
    assert "need cookies" not in msg and "yt-dlp -U" not in msg


# --- carousels: one JSON line per slide ---------------------------------------

import json as _json


def _slide(i, vid=True):
    d = {"id": "S%d" % i, "playlist_index": i, "title": "t", "uploader": "u", "duration": 5}
    if vid:
        d["formats"] = [{"format_id": "1"}]
    return _json.dumps(d)


def _carousel_download(stdout, url, returncode=0, stderr=""):
    calls = []

    def _rec(cmd, **kw):
        calls.append(cmd)
        if "--dump-json" in cmd:
            return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)
        return MagicMock(returncode=0, stdout="", stderr="")

    c = InstagramCrawler()
    with _patch_basecmd(), \
         patch("reel_scout.crawl.instagram.get_limiter"), \
         patch("reel_scout.crawl.instagram.subprocess.run", side_effect=_rec), \
         patch("reel_scout.crawl.instagram.os.path.exists", return_value=True), \
         patch("reel_scout.crawl.instagram.os.path.getsize", return_value=1234), \
         patch("reel_scout.crawl.instagram.ffprobe.warn_if_not_apple_playable"):
        meta = c.download(url, output_dir="/tmp")
    dl = [cmd for cmd in calls if "--dump-json" not in cmd][0]
    return meta, dl


def test_a_video_carousel_downloads_one_slide_not_crash_on_extra_data():
    out = "\n".join(_slide(i) for i in range(1, 6))
    meta, dl = _carousel_download(out, "https://www.instagram.com/p/Dc4nX4FiBJx/")
    assert dl[dl.index("--playlist-items") + 1] == "1"
    assert meta.platform_id == "Dc4nX4FiBJx"


def test_img_index_picks_the_slide_the_link_points_at():
    out = "\n".join(_slide(i) for i in range(1, 6))
    _meta, dl = _carousel_download(out, "https://www.instagram.com/p/Dc4nX4FiBJx/?img_index=4")
    assert dl[dl.index("--playlist-items") + 1] == "4"


def test_a_mixed_carousel_that_exits_non_zero_still_gets_its_video():
    out = _slide(2)  # slides 1 and 3 were photos and only produced stderr
    _meta, dl = _carousel_download(out, "https://www.instagram.com/p/X/", returncode=1,
                                   stderr=_PHOTO_STDERR)
    assert dl[dl.index("--playlist-items") + 1] == "2"


def test_a_single_reel_does_not_get_playlist_items():
    reel = _json.dumps({"id": "R", "title": "t", "duration": 5, "formats": [{}]})
    _meta, dl = _carousel_download(reel, "https://www.instagram.com/reel/R/")
    assert "--playlist-items" not in dl
