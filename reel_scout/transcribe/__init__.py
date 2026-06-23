from __future__ import annotations

import glob
import os
from typing import List, Optional

from .base import BaseTranscriber, TranscriptResult
from .. import config

# Preferred subtitle languages, in priority order, for 招① (subtitle-first).
_SUB_LANG_PREFIXES = ("en", "zh")


def find_subtitle(video_path: str) -> Optional[str]:
    """Find a native subtitle (.vtt) sitting next to a downloaded video.

    yt-dlp writes subs as ``<stem>.<lang>.vtt`` alongside the media file. We prefer
    English then Chinese, falling back to any .vtt. Returns None when none exist —
    the caller then runs local Whisper as before.
    """
    if not video_path:
        return None
    stem = os.path.splitext(video_path)[0]
    candidates = sorted(glob.glob(stem + ".*.vtt"))
    if not candidates:
        return None
    for prefix in _SUB_LANG_PREFIXES:
        for c in candidates:
            lang = os.path.basename(c)[len(os.path.basename(stem)) + 1:]
            if lang.lower().startswith(prefix):
                return c
    return candidates[0]


def get_transcriber(backend: Optional[str] = None) -> BaseTranscriber:
    backend = backend or config.WHISPER_BACKEND
    if backend == "faster-whisper":
        from .faster_whisper import FasterWhisperTranscriber
        return FasterWhisperTranscriber(model=config.WHISPER_MODEL)
    elif backend == "whisper-cpp":
        from .whisper_cpp import WhisperCppTranscriber
        return WhisperCppTranscriber(model=config.WHISPER_MODEL)
    else:
        raise ValueError(f"Unknown whisper backend: {backend}")
