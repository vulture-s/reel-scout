from __future__ import annotations

import json
import os
import re
import subprocess
from typing import List, Optional, Tuple

from .base import BaseCrawler, VideoMeta
from .rate_limiter import get_limiter
from . import ytdlp
from .. import config
from .. import ffprobe
from ..utils.stderr import warn


def _video_entries(stdout: str) -> List[Tuple[int, dict]]:
    """[(1-based playlist index, info)] for every slide yt-dlp returned with formats.

    A single reel is one line; a carousel is one line per slide. Lines that do
    not parse are skipped rather than fatal -- a mixed carousel exits non-zero
    for its photo slides while still printing the video ones.
    """
    parsed: List[Tuple[int, dict]] = []
    for n, line in enumerate((stdout or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            info = json.loads(line)
        except ValueError:
            continue
        if isinstance(info, dict):
            parsed.append((int(info.get("playlist_index") or n), info))
    if len(parsed) <= 1:
        # A single reel: trust it as before, whatever fields it carries.
        return parsed
    return [(i, info) for i, info in parsed if info.get("formats") or info.get("url")]


def _pick_entry(entries: List[Tuple[int, dict]], url: str) -> int:
    """Position in *entries* of the slide the link points at, else 0."""
    m = re.search(r"[?&]img_index=(\d+)", url)
    if m:
        want = int(m.group(1))
        for i, (idx, _info) in enumerate(entries):
            if idx == want:
                return i
    return 0


def photo_only_count(stderr: str) -> int:
    """How many items failed as "No video formats found", if that is *every* error.

    A photo carousel (instagram.com/p/<code>/?img_index=N) comes back from
    yt-dlp as one "No video formats found!" per slide. format_error reads that
    marker as a broken extractor and tells the user to update yt-dlp and check
    cookies -- both wrong, and both send them off to fix something that works.
    Returns 0 when any other error is present, so real failures keep their text.
    """
    errors = [ln for ln in (stderr or "").splitlines() if ln.lstrip().startswith("ERROR:")]
    if not errors:
        return 0
    if all("no video formats found" in ln.lower() for ln in errors):
        return len(errors)
    return 0



def _cookie_args() -> List[str]:
    """`--cookies <path>` for yt-dlp, resolved at call time.

    A configured path that does not exist is reported on stderr rather than
    raised: public reels still work logged-out, and a stale IG_COOKIES_FILE in
    .env should not break them -- but it must not be silent either, or the
    later "need cookies?" error sends the user to re-export cookies that were
    never being sent.
    """
    path = config.ig_cookies_file()
    if not path:
        return []
    if not os.path.exists(path):
        warn("[instagram] IG_COOKIES_FILE does not exist, crawling without "
             "cookies: %s" % path)
        return []
    return ["--cookies", path]

class InstagramCrawler(BaseCrawler):
    platform = "instagram"

    # Single post/reel URL. The account-scoped form
    # (instagram.com/<handle>/reel/<code>/) is what Instagram's own share
    # button produces, so it must parse as readily as the canonical form.
    _SINGLE_RE = re.compile(
        r"instagram\.com/(?:[a-zA-Z0-9_.]+/)?(?:p|reel|reels)/([a-zA-Z0-9_-]+)"
    )
    # Profile/channel page (with optional /reels/ tab)
    _PROFILE_RE = re.compile(r"instagram\.com/([a-zA-Z0-9_.]+)(?:/reels)?/?$")

    def is_profile_url(self, url: str) -> bool:
        """Return True if the URL points to a profile/reels page, not a single post."""
        return bool(self._PROFILE_RE.search(url)) and not self._SINGLE_RE.search(url)

    def extract_id(self, url: str) -> str:
        # Handle /p/CODE/, /reel/CODE/, /reels/CODE/
        m = self._SINGLE_RE.search(url)
        if m:
            return m.group(1)
        raise ValueError(f"Cannot extract Instagram post ID from: {url}")

    def download(self, url: str, output_dir: Optional[str] = None) -> VideoMeta:
        if output_dir is None:
            output_dir = config.VIDEOS_DIR

        limiter = get_limiter(self.platform)
        limiter.wait()

        post_id = self.extract_id(url)
        output_template = os.path.join(output_dir, f"ig_{post_id}.%(ext)s")

        # Build command with cookies if available
        base_cmd = list(ytdlp.base_cmd()) + _cookie_args()

        # Get metadata
        meta_cmd = base_cmd + ["--dump-json", "--no-download", url]
        result = subprocess.run(
            meta_cmd, capture_output=True, text=True, timeout=60,
        )
        entries = _video_entries(result.stdout)
        if result.returncode != 0 and not entries:
            photos = photo_only_count(result.stderr)
            if photos:
                raise RuntimeError(
                    "Instagram post has no video: all %d item(s) are photos. "
                    "Nothing to analyze -- not a cookies or yt-dlp problem." % photos
                )
            if ytdlp.is_network_error(result.stderr):
                raise RuntimeError(
                    f"yt-dlp IG metadata failed (network): {ytdlp.format_error(result.stderr)}"
                )
            raise RuntimeError(
                f"yt-dlp IG metadata failed (need cookies?): {ytdlp.format_error(result.stderr)}"
            )
        if not entries:
            raise RuntimeError("yt-dlp IG metadata returned no video entry")

        # A carousel prints one JSON object per slide, and json.loads on the
        # whole stdout died with "Extra data: line 2 column 1" (Dc4nX4FiBJx, five
        # video slides, 2026-10-02). One URL is one library row, so pick one
        # slide: the one the shared link points at (img_index), else the first.
        pick = _pick_entry(entries, url)
        playlist_index, info = entries[pick]
        if len(entries) > 1:
            print("  carousel with %d video slide(s); analyzing slide %d"
                  % (len(entries), playlist_index))

        # Download
        # Was a bare "bestvideo+bestaudio/best" -- no codec condition at all,
        # not even the av01 exclusion youtube.py carried. 88 of the 103
        # unplayable files in the 2026-08-25 audit came through this line.
        dl_cmd = base_cmd + [
            "-f", ytdlp.apple_safe_format(),
            "--merge-output-format", "mp4",
            "-o", output_template,
        ]
        if len(entries) > 1 or info.get("playlist_index"):
            # A carousel slide, even a lone video among photos: without this
            # every slide renders to the same ig_<post>.mp4 template, and the
            # photo slides fail the whole download.
            dl_cmd += ["--playlist-items", str(playlist_index)]
        dl_cmd.append(url)
        result = subprocess.run(
            dl_cmd, capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp IG download failed: {ytdlp.format_error(result.stderr)}")

        expected = os.path.join(output_dir, f"ig_{post_id}.mp4")
        file_path = expected if os.path.exists(expected) else ""
        file_size = os.path.getsize(file_path) if file_path else 0

        if file_path:
            # The selector states a preference; yt-dlp is free to walk down to
            # an unconstrained rung. Until this line existed, nothing anywhere
            # measured the file that actually landed -- the clip downloaded,
            # analyzed and scored perfectly and failed only when a human opened
            # it on a phone. Warn, never fail: a bad codec is still worth its
            # transcript, keyframes and score.
            try:
                ffprobe.warn_if_not_apple_playable(file_path, os.path.basename(file_path))
            except Exception as exc:  # noqa: BLE001 - see below
                # The promise "a failed probe never costs a download that already
                # succeeded" has to be kept here, where the download is. ffprobe
                # catches the failures it knows about; this catches the ones it
                # does not. A missing binary must not turn a working clip into an
                # exception three frames up the stack.
                warn("  codec check skipped: %r" % (exc,))

        # yt-dlp routinely reports no duration for Instagram. Writing 0.0 is
        # worse than it looks: it is a *real* value, so the COALESCE-based
        # repair paths downstream treat duration as already known and never
        # correct it. We hold the file already, so measure it.
        duration = float(info.get("duration") or 0)
        if not duration and file_path:
            duration = ffprobe.probe_duration(file_path) or 0.0

        return VideoMeta(
            platform=self.platform,
            platform_id=post_id,
            url=url,
            title=info.get("title", info.get("description", "")[:100]),
            uploader=info.get("uploader", info.get("uploader_id", "")),
            duration_sec=duration,
            upload_date=info.get("upload_date", ""),
            file_path=file_path,
            file_size_bytes=file_size,
        )

    def browse(self, url: str, limit: int = 30) -> List[VideoMeta]:
        """List reels from an Instagram profile page using yt-dlp --flat-playlist.

        Returns VideoMeta entries with metadata only (no downloaded files).
        Requires cookies for most profiles.
        """
        base_cmd = list(ytdlp.base_cmd()) + _cookie_args()

        cmd = base_cmd + [
            "--flat-playlist",
            "--dump-json",
            "--no-download",
            "--playlist-end", str(limit),
            url,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            # yt-dlp's IG extractor breaks periodically (roadmap Non-goals #1). Try
            # the instaloader fallback (optional `instagram` extra) before giving up;
            # if it isn't installed, surface the original yt-dlp error unchanged.
            yt_err = ytdlp.format_error(result.stderr)
            try:
                return self._browse_instaloader(url, limit)
            except ImportError:
                raise RuntimeError(
                    "yt-dlp browse failed (need cookies?): %s "
                    "(install the `instagram` extra for an instaloader fallback)" % yt_err
                )
            except Exception as e:  # noqa: BLE001 — report both failures
                raise RuntimeError(
                    "yt-dlp browse failed (%s); instaloader fallback also failed: %s"
                    % (yt_err, e)
                )

        entries = []
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            try:
                info = json.loads(line)
            except json.JSONDecodeError:
                continue

            platform_id = info.get("id", "")
            entry_url = info.get("url") or info.get("webpage_url", "")
            if not entry_url and platform_id:
                entry_url = f"https://www.instagram.com/reel/{platform_id}/"

            entries.append(VideoMeta(
                platform=self.platform,
                platform_id=platform_id,
                url=entry_url,
                title=info.get("title", info.get("description", ""))[:100] if info.get("title") or info.get("description") else "",
                uploader=info.get("uploader", info.get("uploader_id", "")),
                duration_sec=float(info.get("duration") or 0),
                upload_date=info.get("upload_date", ""),
            ))

        return entries

    def _browse_instaloader(self, url: str, limit: int) -> List[VideoMeta]:
        """Fallback profile browse via instaloader (optional `instagram` extra),
        used when yt-dlp's IG extractor is down. Raises ImportError when the extra
        isn't installed so the caller can keep the original yt-dlp error."""
        import instaloader  # ImportError -> caller surfaces the yt-dlp error

        m = self._PROFILE_RE.search(url)
        if not m:
            raise ValueError("Not an Instagram profile URL: %s" % url)
        username = m.group(1)

        loader = instaloader.Instaloader(
            quiet=True, download_pictures=False, download_videos=False,
            download_comments=False, save_metadata=False,
        )
        profile = instaloader.Profile.from_username(loader.context, username)
        entries: List[VideoMeta] = []
        for post in profile.get_posts():
            if len(entries) >= limit:  # checked first so limit=0 yields 0, not 1
                break
            if not getattr(post, "is_video", False):
                continue
            entries.append(VideoMeta(
                platform=self.platform,
                platform_id=post.shortcode,
                url="https://www.instagram.com/reel/%s/" % post.shortcode,
                title=(post.caption or "")[:100],
                uploader=username,
                duration_sec=float(getattr(post, "video_duration", 0) or 0),
                upload_date=post.date_utc.strftime("%Y%m%d"),
            ))
        return entries
