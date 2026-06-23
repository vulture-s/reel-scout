from __future__ import annotations

import json
import os
import re
import subprocess
from typing import List, Optional

from .base import BaseCrawler, VideoMeta
from .rate_limiter import get_limiter
from .. import config


class YouTubeCrawler(BaseCrawler):
    platform = "youtube"

    def extract_id(self, url: str) -> str:
        # Handle youtu.be/ID, youtube.com/watch?v=ID, youtube.com/shorts/ID
        patterns = [
            re.compile(r"youtu\.be/([a-zA-Z0-9_-]{11})"),
            re.compile(r"youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})"),
            re.compile(r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})"),
        ]
        for p in patterns:
            m = p.search(url)
            if m:
                return m.group(1)
        raise ValueError(f"Cannot extract YouTube video ID from: {url}")

    def download(self, url: str, output_dir: Optional[str] = None) -> VideoMeta:
        if output_dir is None:
            output_dir = config.VIDEOS_DIR

        limiter = get_limiter(self.platform)
        limiter.wait()

        vid = self.extract_id(url)
        output_template = os.path.join(output_dir, f"yt_{vid}.%(ext)s")

        # First get metadata
        meta_cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-download",
            "--remote-components", "ejs:github",
            url,
        ]
        result = subprocess.run(
            meta_cmd, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp metadata failed: {result.stderr[:500]}")

        info = json.loads(result.stdout)

        # Download. Also grab native + auto-generated subtitles (招①): when present
        # they let the transcribe step skip local Whisper entirely. Converted to vtt
        # so the stdlib VTT parser can read them. Cloud ASR is intentionally NOT used.
        dl_cmd = [
            "yt-dlp",
            "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
            "--merge-output-format", "mp4",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", "en.*,zh.*",
            "--convert-subs", "vtt",
            # Subtitle fetch is best-effort: a sub-only failure (e.g. HTTP 429 on the
            # caption endpoint, or no captions for this video) must NOT abort the media
            # download — we just fall back to local Whisper. Real media failure is still
            # caught below by the "no mp4 produced" check.
            "--no-abort-on-error",
            "-o", output_template,
            "--no-playlist",
            "--remote-components", "ejs:github",
            url,
        ]
        result = subprocess.run(
            dl_cmd, capture_output=True, text=True, timeout=300,
        )

        # Find downloaded file
        expected = os.path.join(output_dir, f"yt_{vid}.mp4")
        if not os.path.exists(expected):
            # No media produced -> genuine download failure (not a subtitle hiccup).
            raise RuntimeError(f"yt-dlp download failed: {result.stderr[:500]}")
        file_path = expected
        file_size = os.path.getsize(file_path) if file_path else 0

        meta = VideoMeta(
            platform=self.platform,
            platform_id=vid,
            url=url,
            title=info.get("title", ""),
            uploader=info.get("uploader", info.get("channel", "")),
            duration_sec=float(info.get("duration", 0)),
            upload_date=info.get("upload_date", ""),
            file_path=file_path,
            file_size_bytes=file_size,
        )
        # Record any subtitle yt-dlp wrote next to the media (en.* / zh.* .vtt).
        if file_path:
            from ..transcribe import find_subtitle
            sub = find_subtitle(file_path)
            if sub:
                meta.extra["subtitle_path"] = sub
        return meta

    def browse(self, url: str, limit: int = 30) -> List[VideoMeta]:
        """List videos from a YouTube channel/playlist page."""
        cmd = [
            "yt-dlp",
            "--flat-playlist",
            "--dump-json",
            "--no-download",
            "--playlist-end", str(limit),
            "--remote-components", "ejs:github",
            url,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"yt-dlp browse failed: {result.stderr[:500]}")

        entries = []
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            try:
                info = json.loads(line)
            except json.JSONDecodeError:
                continue

            vid = info.get("id", "")
            entry_url = info.get("url") or info.get("webpage_url", "")
            if not entry_url and vid:
                entry_url = f"https://www.youtube.com/watch?v={vid}"

            entries.append(VideoMeta(
                platform=self.platform,
                platform_id=vid,
                url=entry_url,
                title=info.get("title", ""),
                uploader=info.get("uploader", info.get("channel", "")),
                duration_sec=float(info.get("duration") or 0),
                upload_date=info.get("upload_date", ""),
            ))

        return entries
