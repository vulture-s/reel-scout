"""Threads crawler -- no yt-dlp, no login.

yt-dlp has no Threads extractor (``Unsupported URL``), and the post code is
*not* an Instagram shortcode in disguise: the same ID fed to
``instagram.com/p/<ID>/`` comes back "Instagram API is not granting access"
even with valid cookies, while a known IG reel in the same call succeeds.
Same ID format, different object store.

What does work (measured 2026-10-05, 5/5 queued posts): the post page itself.
Threads serves a login-wall shell to browsers and plain ``curl``, but serves
search-engine crawlers a server-rendered page whose
``<script type="application/json">`` blocks carry the full post object:
``result.data.media`` with ``video_versions`` (direct fbcdn mp4 URLs, fetchable
without cookies), the caption, author, timestamp and engagement counts.

That makes the User-Agent the single fragile assumption here, so it lives in
``config.THREADS_USER_AGENT`` rather than in this file, and every way the page
can come back without a post raises instead of returning an empty meta.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .base import BaseCrawler, VideoMeta
from .rate_limiter import get_limiter
from .. import config
from .. import ffprobe
from ..utils.stderr import warn


_POST_RE = re.compile(r"threads\.(?:com|net)/@[^/]+/post/([A-Za-z0-9_-]+)")
_SHARE_RE = re.compile(r"threads\.(?:com|net)/share/([A-Za-z0-9_-]+)")
_JSON_SCRIPT_RE = re.compile(
    r'<script type="application/json"[^>]*>(.*?)</script>', re.S)


def _walk_media_fragments(node: Any) -> Iterator[Dict[str, Any]]:
    """Yield every ``result.data.media`` dict on the page.

    The page nests it under a few layers of ``require``/``__bbox`` arrays whose
    shape is Meta's to change; searching for the stable leaf is less brittle
    than hard-coding the path.
    """
    if isinstance(node, dict):
        result = node.get("result")
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict):
                media = data.get("media")
                if isinstance(media, dict):
                    yield media
        for v in node.values():
            for m in _walk_media_fragments(v):
                yield m
    elif isinstance(node, list):
        for v in node:
            for m in _walk_media_fragments(v):
                yield m


def parse_post(html: str) -> Dict[str, Any]:
    """Return the root post object embedded in a Threads post page.

    The page streams one post as several ``result.data.media`` fragments in
    separate script blocks, all sharing the post's ``id``: one carries
    ``code``/caption/media, a later one carries
    ``text_post_app_info.self_thread`` and ``direct_replies``. Taking only the
    fragment with ``code`` silently drops the author's follow-up posts (seen
    live: 1 follow-up on the page, 0 returned), so the fragments are merged.

    Replies and follow-ups also carry ``code`` and ``caption``, but they sit
    *inside* ``text_post_app_info``, never at ``result.data.media`` -- so the
    fragment with a ``code`` is the post the URL points at.
    """
    fragments: List[Dict[str, Any]] = []
    for m in _JSON_SCRIPT_RE.finditer(html):
        blob = m.group(1)
        if '"result"' not in blob or '"media"' not in blob:
            continue
        try:
            doc = json.loads(blob)
        except ValueError:
            continue
        fragments.extend(_walk_media_fragments(doc))

    root = next((f for f in fragments if f.get("code")), None)
    if root is not None:
        post = dict(root)
        tpi = dict(post.get("text_post_app_info") or {})
        for frag in fragments:
            if frag is root or frag.get("id") != post.get("id"):
                continue
            for k, v in (frag.get("text_post_app_info") or {}).items():
                tpi.setdefault(k, v)
        post["text_post_app_info"] = tpi
        return post
    raise RuntimeError(
        "Threads page has no embedded post object -- either the post is gone/"
        "private, or Threads stopped serving the server-rendered page to "
        "THREADS_USER_AGENT=%r (it served a login wall instead)"
        % config.THREADS_USER_AGENT)


def pick_videos(post: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every video in the post, in display order.

    Three places a Threads video can live, all observed on real posts:
      * ``video_versions`` on the post itself      (media_type 2, single video)
      * ``carousel_media[*].video_versions``       (media_type 8, carousel)
      * ``text_post_app_info.linked_inline_media`` (media_type 19, text post
        with an inline video)
    Each entry is the ``video_versions`` list of one video.
    """
    found: List[Dict[str, Any]] = []
    if post.get("video_versions"):
        found.append(post)
    for item in post.get("carousel_media") or []:
        if isinstance(item, dict) and item.get("video_versions"):
            found.append(item)
    inline = (post.get("text_post_app_info") or {}).get("linked_inline_media")
    if isinstance(inline, dict) and inline.get("video_versions"):
        found.append(inline)
    return found


def post_texts(post: Dict[str, Any]) -> Tuple[str, List[str]]:
    """(caption, the author's own follow-up posts in the same thread)."""
    caption = ((post.get("caption") or {}).get("text") or "").strip()
    tpi = post.get("text_post_app_info") or {}
    follow_ups: List[str] = []
    edges = ((tpi.get("self_thread") or {}).get("posts") or {}).get("edges") or []
    for edge in edges:
        node = (edge or {}).get("node") or {}
        text = ((node.get("caption") or {}).get("text") or "").strip()
        if text:
            follow_ups.append(text)
    return caption, follow_ups


def _fetch(url: str, user_agent: str, timeout: int = 60) -> Tuple[str, bytes]:
    """GET ``url`` following redirects; return (final URL, body)."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.geturl(), resp.read()


class ThreadsCrawler(BaseCrawler):
    platform = "threads"

    def extract_id(self, url: str) -> str:
        m = _POST_RE.search(url)
        if m:
            return m.group(1)
        # Share links (threads.com/share/<X>) 302 to /@user/post/<code>, and
        # the share token is not the post code. Like TikTok's vm.tiktok.com,
        # it stays the ID only until download() resolves the real one.
        m = _SHARE_RE.search(url)
        if m:
            return m.group(1)
        raise ValueError("Not a Threads post URL: %s" % url)

    def download(self, url: str, output_dir: Optional[str] = None) -> VideoMeta:
        if output_dir is None:
            output_dir = config.VIDEOS_DIR

        limiter = get_limiter(self.platform)
        limiter.wait()

        final_url, body = _fetch(url, config.THREADS_USER_AGENT)
        post = parse_post(body.decode("utf-8", errors="replace"))
        code = post["code"]

        videos = pick_videos(post)
        if not videos:
            raise RuntimeError(
                "Threads post %s has no video (media_type=%s) -- text/image "
                "posts have nothing for reel-scout to analyze"
                % (code, post.get("media_type")))
        if len(videos) > 1:
            # One post -> one row: the videos table is keyed on the post.
            warn("  Threads post %s has %d videos; analyzing the first only"
                 % (code, len(videos)))

        video_url = videos[0]["video_versions"][0]["url"]
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, "th_%s.mp4" % code)
        # The CDN URL is signed; it needs no cookie and no special UA.
        _, data = _fetch(video_url, "Mozilla/5.0", timeout=300)
        if not data:
            raise RuntimeError("Threads video for %s downloaded 0 bytes" % code)
        with open(file_path, "wb") as fh:
            fh.write(data)

        try:
            ffprobe.warn_if_not_apple_playable(file_path, os.path.basename(file_path))
        except Exception as exc:  # noqa: BLE001 - same contract as tiktok.py
            warn("  codec check skipped: %r" % (exc,))

        user = post.get("user") or {}
        tpi = post.get("text_post_app_info") or {}
        caption, follow_ups = post_texts(post)
        taken_at = post.get("taken_at")
        upload_date = (
            datetime.fromtimestamp(int(taken_at), tz=timezone.utc).strftime("%Y%m%d")
            if taken_at else "")

        extra = {
            "caption": caption,
            "self_thread": json.dumps(follow_ups, ensure_ascii=False),
            "video_count": str(len(videos)),
            "media_type": str(post.get("media_type", "")),
            "like_count": str(post.get("like_count", "")),
            "reply_count": str(tpi.get("direct_reply_count", "")),
            "repost_count": str(tpi.get("repost_count", "")),
            "quote_count": str(tpi.get("quote_count", "")),
            "resolved_url": final_url,
        }

        return VideoMeta(
            platform=self.platform,
            platform_id=code,
            url=url,
            title=caption[:100],
            uploader=user.get("username", ""),
            duration_sec=ffprobe.probe_duration(file_path) or 0.0,
            upload_date=upload_date,
            file_path=file_path,
            file_size_bytes=os.path.getsize(file_path),
            extra=extra,
        )
