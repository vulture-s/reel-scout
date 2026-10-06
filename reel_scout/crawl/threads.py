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

It is also why the crawler is OFF unless that setting is filled in: presenting
a crawler User-Agent impersonates a crawler, and Threads' robots.txt prohibits
automated collection without written permission. A public package does not do
that on install; a user who sets it is choosing to, for their own posts.
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
_MEDIA_RE = re.compile(r"[?&]media=(\d+)")
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


def _image_url(item: Dict[str, Any]) -> Tuple[str, int, int]:
    cands = ((item.get("image_versions2") or {}).get("candidates") or [])
    if not cands:
        return "", 0, 0
    best = cands[0]  # Threads lists the largest rendition first
    return best.get("url", ""), int(best.get("width") or 0), int(best.get("height") or 0)


def media_items(post: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every media item in the post, in display order, numbered from 1.

    Three places a Threads video can live, all observed on real posts:
      * ``video_versions`` on the post itself      (media_type 2, single video)
      * ``carousel_media[*]``                      (media_type 8, carousel of
        videos and/or photos)
      * ``text_post_app_info.linked_inline_media`` (media_type 19, text post
        with an inline video)

    The number is the position a person sees when swiping the post, and it is
    what ``?media=N`` on a post URL refers to.
    """
    raw: List[Dict[str, Any]] = []
    carousel = [c for c in (post.get("carousel_media") or []) if isinstance(c, dict)]
    if carousel:
        raw = carousel
    elif post.get("video_versions"):
        raw = [post]
    else:
        inline = (post.get("text_post_app_info") or {}).get("linked_inline_media")
        if isinstance(inline, dict) and inline.get("video_versions"):
            raw = [inline]
        elif post.get("image_versions2"):
            raw = [post]

    items: List[Dict[str, Any]] = []
    for n, item in enumerate(raw, 1):
        if item.get("video_versions"):
            items.append({
                "idx": n, "kind": "video",
                "url": item["video_versions"][0].get("url", ""),
                "width": int(item.get("original_width") or 0),
                "height": int(item.get("original_height") or 0),
            })
        else:
            url, w, h = _image_url(item)
            if url:
                items.append({"idx": n, "kind": "image", "url": url,
                              "width": w, "height": h})
    return items


def media_param(url: str) -> Optional[int]:
    """``?media=N`` on a post URL: analyze the N-th item instead of the first
    video. Encoded in the URL rather than passed as an option so the row it
    produces has a URL of its own -- dedupe, ``batch`` and the queue all key on
    the URL and keep working unchanged."""
    m = _MEDIA_RE.search(url)
    return int(m.group(1)) if m else None


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
        n = media_param(url)
        suffix = "#%d" % n if n else ""
        m = _POST_RE.search(url)
        if m:
            return m.group(1) + suffix
        # Share links (threads.com/share/<X>) 302 to /@user/post/<code>, and
        # the share token is not the post code. Like TikTok's vm.tiktok.com,
        # it stays the ID only until download() resolves the real one.
        m = _SHARE_RE.search(url)
        if m:
            return m.group(1) + suffix
        raise ValueError("Not a Threads post URL: %s" % url)

    def download(self, url: str, output_dir: Optional[str] = None) -> VideoMeta:
        if output_dir is None:
            output_dir = config.VIDEOS_DIR

        if not config.THREADS_USER_AGENT:
            # Checked before the rate limiter and before any request: off means
            # nothing leaves this machine.
            raise RuntimeError(
                "Threads is off by default. Fetching a post only works by "
                "presenting a search-crawler User-Agent, and Threads' robots.txt "
                "prohibits automated collection without written permission. To "
                "opt in for your own single posts, at your own risk, set "
                "THREADS_USER_AGENT (see docs/threads.md, 'Off by default').")

        limiter = get_limiter(self.platform)
        limiter.wait()

        final_url, body = _fetch(url, config.THREADS_USER_AGENT)
        post = parse_post(body.decode("utf-8", errors="replace"))
        code = post["code"]

        items = media_items(post)
        wanted = media_param(url)
        if wanted is not None:
            target = next((i for i in items if i["idx"] == wanted), None)
            if target is None or target["kind"] != "video":
                raise RuntimeError(
                    "Threads post %s has no video at media=%d (items: %s)"
                    % (code, wanted, ", ".join("%d=%s" % (i["idx"], i["kind"])
                                               for i in items) or "none"))
        else:
            target = next((i for i in items if i["kind"] == "video"), None)
            if target is None:
                raise RuntimeError(
                    "Threads post %s has no video (media_type=%s) -- text/image "
                    "posts have nothing for reel-scout to analyze"
                    % (code, post.get("media_type")))

        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, "th_%s_m%d.mp4" % (code, target["idx"]))
        # The CDN URL is signed; it needs no cookie and no special UA.
        _, data = _fetch(target["url"], "Mozilla/5.0", timeout=300)
        if not data:
            raise RuntimeError("Threads video for %s downloaded 0 bytes" % code)
        with open(file_path, "wb") as fh:
            fh.write(data)
        target["file_path"] = file_path

        if wanted is None:
            # The first video is the one analyzed; photos are stored now (they
            # are small, and the signed URLs expire). Other videos are only
            # recorded -- their URLs expire too, so an on-demand analysis
            # re-fetches the post page for a fresh one rather than trusting
            # what is stored here.
            for item in items:
                if item["kind"] != "image":
                    continue
                img = os.path.join(output_dir, "th_%s_m%d.jpg" % (code, item["idx"]))
                try:
                    _, blob = _fetch(item["url"], "Mozilla/5.0", timeout=60)
                    with open(img, "wb") as fh:
                        fh.write(blob)
                    item["file_path"] = img
                except Exception as exc:  # noqa: BLE001 - a photo never costs the video
                    warn("  Threads photo %d of %s not saved: %r" % (item["idx"], code, exc))

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
            "post_code": code,
            "caption": caption,
            "self_thread": json.dumps(follow_ups, ensure_ascii=False),
            "video_count": str(sum(1 for i in items if i["kind"] == "video")),
            "media_type": str(post.get("media_type", "")),
            "like_count": str(post.get("like_count", "")),
            "reply_count": str(tpi.get("direct_reply_count", "")),
            "repost_count": str(tpi.get("repost_count", "")),
            "quote_count": str(tpi.get("quote_count", "")),
            "resolved_url": final_url,
        }
        if wanted is None:
            extra["analyzed_idx"] = str(target["idx"])
            extra["post_media_json"] = json.dumps(items, ensure_ascii=False)
        else:
            extra["media_index"] = str(wanted)

        return VideoMeta(
            platform=self.platform,
            platform_id=code + ("#%d" % wanted if wanted is not None else ""),
            url=url,
            title=caption[:100],
            uploader=user.get("username", ""),
            duration_sec=ffprobe.probe_duration(file_path) or 0.0,
            upload_date=upload_date,
            file_path=file_path,
            file_size_bytes=os.path.getsize(file_path),
            extra=extra,
        )
