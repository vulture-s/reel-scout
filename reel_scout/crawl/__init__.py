from __future__ import annotations

import re
from typing import Optional

from .youtube import YouTubeCrawler
from .instagram import InstagramCrawler
from .tiktok import TikTokCrawler
from .base import BaseCrawler


_PLATFORM_PATTERNS = [
    (re.compile(r"(youtube\.com|youtu\.be)"), "youtube"),
    (re.compile(r"instagram\.com"), "instagram"),
    (re.compile(r"tiktok\.com"), "tiktok"),
    (re.compile(r"twitter\.com|x\.com"), "twitter"),
]

_CRAWLERS = {
    "youtube": YouTubeCrawler,
    "instagram": InstagramCrawler,
    "tiktok": TikTokCrawler,
}


def detect_platform(url: str) -> Optional[str]:
    for pattern, name in _PLATFORM_PATTERNS:
        if pattern.search(url):
            return name
    return None


def get_crawler(url: str) -> BaseCrawler:
    platform = detect_platform(url)
    if platform is None or platform not in _CRAWLERS:
        raise ValueError(f"Unsupported platform for URL: {url}")
    return _CRAWLERS[platform]()


def is_profile_url(url: str) -> bool:
    """Check if a URL is a profile/channel page rather than a single video.

    Answers what the URL *is*, not whether we can browse it — a TikTok profile
    is a profile even though TikTokCrawler has no browse(). Callers that need
    listing support should let browse() raise NotImplementedError.

    YouTube playlists are deliberately excluded: they are not profiles, and the
    caller distinguishes them via a separate flag.
    """
    platform = detect_platform(url)
    if platform == "instagram":
        return InstagramCrawler().is_profile_url(url)
    if platform == "youtube":
        # Channel, @handle, or /shorts tab
        return bool(re.search(
            r"youtube\.com/(?:@[^/]+|channel/|c/|user/|[^/]+/shorts)", url
        ))
    if platform == "tiktok":
        # tiktok.com/@user, optionally with a tab suffix, but not /@user/video/123
        return bool(re.search(r"tiktok\.com/@[^/]+(?:/(?!video/)[^/]*)?/?$", url))
    return False
