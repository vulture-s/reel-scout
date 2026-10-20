from __future__ import annotations

import glob
import os
from typing import List, Optional

from .base import BaseTranscriber, TranscriptResult
from .. import config

# Preferred subtitle languages, in priority order, for 招① (subtitle-first).
# Only consulted as a tie-break between *original* tracks. It used to be
# ("en", "zh"), and that is how three 2026-10-02 clips (壽司／紅眼／Snaplab)
# ended up with English transcripts: the creator had uploaded an English
# *translation* under a plain ``en``/``en-US`` code -- a shape
# `is_translated_track` cannot see -- next to the ``zh``/``zh-TW`` original, and
# English won the tie-break. Chinese first now; within Chinese see
# `zh_track_rank`.
_SUB_LANG_PREFIXES = ("zh", "en")

#: Chinese caption codes in preference order. Traditional first, because that is
#: what this corpus is read in -- and a native Traditional track is the cheapest
#: way to get there: the conversion happens at the source (the creator or the
#: platform wrote it), so nothing downstream needs opencc. Simplified codes rank
#: last but are *kept* as a candidate: for a Simplified-language creator the
#: Simplified track is the faithful one, and turning it into Traditional would be
#: a presentation choice, not a correction.
_ZH_PREFERENCE = ("zh-hant", "zh-tw", "zh-hk", "zh")
_ZH_HANS_TAGS = {"hans", "cn", "sg", "my"}


def zh_track_rank(code: str) -> int:
    """Sort key for Chinese caption codes; lower is better.

    ``zh-Hant`` < ``zh-TW`` < ``zh-HK`` < bare ``zh`` < any other Chinese code
    (``zh-MO``, ``zh-Hant-TW``) < Simplified (``zh-Hans``, ``zh-CN``) <
    non-Chinese. yt-dlp's ``-orig`` marker is ignored: ``zh-Hant-orig`` ranks as
    ``zh-Hant``. Whether a track is uploaded or auto-generated is *not* decided
    here -- that is a separate, earlier axis (see
    `reel_scout.crawl.youtube.choose_caption_track`).
    """
    c = code.lower()
    if c.endswith("-orig"):
        c = c[:-5]
    if c in _ZH_PREFERENCE:
        return _ZH_PREFERENCE.index(c)
    parts = c.split("-")
    if parts[0] != "zh":
        return len(_ZH_PREFERENCE) + 2
    if set(parts[1:]) & _ZH_HANS_TAGS:
        return len(_ZH_PREFERENCE) + 1
    return len(_ZH_PREFERENCE)


def _subtag_is_language(subtag: str) -> bool:
    """True when a BCP-47 subtag is a *language* rather than a script or region.

    Language subtags are 2-3 lowercase letters (``zh``, ``bho``); script subtags are
    four Titlecase letters (``Hant``); region subtags are two uppercase letters or
    three digits (``TW``, ``419``). yt-dlp preserves that casing in the filenames it
    writes, and that is what lets ``zh-TW`` (a locale) be told apart from
    ``en-zh-TW`` (a translation).
    """
    return 2 <= len(subtag) <= 3 and subtag.isalpha() and subtag.islower()


def is_translated_track(lang: str) -> bool:
    """True for YouTube's auto-*translated* caption tracks.

    YouTube names them ``<target>-<source>``. `yt-dlp --list-subs` on a Taiwanese
    video shows the original as a bare ``zh-TW`` with no display name, followed by
    ~100 translations of it: ``en-zh-TW`` is listed as "English from Chinese
    (Taiwan)", ``zh-Hant-zh-TW`` as "Chinese (Traditional) from Chinese (Taiwan)".

    Every translated code therefore carries a *second* language subtag, and a plain
    locale never does::

        zh-TW          -> TW   is a region    -> original
        zh-Hant        -> Hant is a script    -> original
        pt-BR          -> BR   is a region    -> original
        en-orig        -> orig is 4 chars     -> original (yt-dlp's own marker)
        en-zh-TW       -> zh   is a language  -> translation
        zh-Hant-zh-TW  -> zh   is a language  -> translation
    """
    parts = lang.split("-")
    return any(_subtag_is_language(p) for p in parts[1:])


def find_subtitle(video_path: str) -> Optional[str]:
    """Find a usable native subtitle (.vtt) sitting next to a downloaded video.

    yt-dlp writes subs as ``<stem>.<lang>.vtt`` alongside the media file.

    Auto-translated tracks are skipped outright. They used to win: the download
    step asks for ``--sub-langs en.*,zh.*``, which happily matches ``en-zh-TW``,
    and the old preference order tried ``en`` first — so a Mandarin video came back
    with an English machine translation and nothing said so. The stored transcript
    for one 壹加壹 video opened "I'm so nervous!" for a sentence nobody spoke in
    English. Everything downstream (VLM prompts, search, swipe extraction, quoting)
    then inherits a paraphrase as if it were what the speaker said.

    Local Whisper on the original audio beats somebody else's machine translation
    for all of those, so when only translations are on disk this returns None and
    lets the caller fall back — loudly, rather than silently preferring the wrong
    thing.
    """
    if not video_path:
        return None
    stem = os.path.splitext(video_path)[0]
    candidates = sorted(glob.glob(stem + ".*.vtt"))
    if not candidates:
        return None

    base = os.path.basename(stem)
    originals: List[tuple] = []
    for c in candidates:
        lang = os.path.basename(c)[len(base) + 1:]
        if lang.lower().endswith(".vtt"):
            lang = lang[:-4]
        if is_translated_track(lang):
            continue
        originals.append((lang, c))

    if not originals:
        print(
            "  Only auto-translated subtitles found ("
            + ", ".join(sorted(lang_c for lang_c in
                               (os.path.basename(c) for c in candidates)))
            + "); using Whisper on the original audio instead."
        )
        return None

    zh = [(zh_track_rank(lang), lang, c) for lang, c in originals
          if lang.lower().split("-")[0] == "zh"]
    if zh:
        return min(zh)[2]
    for prefix in _SUB_LANG_PREFIXES:
        for lang, c in originals:
            if lang.lower().split("-")[0] == prefix:
                return c
    return originals[0][1]


def mlx_unavailable_reason() -> Optional[str]:
    """Why the mlx backend cannot run here, or None when it can.

    Apple Silicon (Darwin/arm64) *and* an importable ``mlx_whisper``. The import
    is real, not `find_spec`: a half-installed mlx (wheel present, Metal library
    missing) passes `find_spec` and then dies at the first transcription.
    """
    import platform

    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return "not Apple Silicon (%s/%s)" % (platform.system(), platform.machine())
    try:
        import mlx_whisper  # noqa: F401
    except Exception as exc:                                   # noqa: BLE001
        return "mlx-whisper not importable (%s: %s)" % (type(exc).__name__, exc)
    return None


_auto_note_shown = False


def resolve_auto_backend() -> str:
    """What ``WHISPER_BACKEND=auto`` runs here: ``mlx`` or ``faster-whisper``."""
    return "mlx" if mlx_unavailable_reason() is None else "faster-whisper"


def get_transcriber(backend: Optional[str] = None) -> BaseTranscriber:
    global _auto_note_shown
    backend = backend or config.WHISPER_BACKEND
    if backend == "auto":
        backend = resolve_auto_backend()
        reason = mlx_unavailable_reason() if backend != "mlx" else None
        # `auto` promised nothing, so off Apple Silicon this is silent. On Apple
        # Silicon without a working mlx the user is on the CPU path that is ~10x
        # slower -- say so once per process, not once per video.
        if reason and not reason.startswith("not Apple Silicon") and not _auto_note_shown:
            _auto_note_shown = True
            from ..utils.stderr import warn
            warn("  note: WHISPER_BACKEND=auto using faster-whisper (CPU) — %s; "
                 "pip install 'reel-scout[mlx]' for Metal" % reason)
    if backend == "mlx":
        reason = mlx_unavailable_reason()
        if reason is None:
            from .mlx_whisper import MlxWhisperTranscriber
            return MlxWhisperTranscriber(model=config.WHISPER_MODEL)
        # Opt-in that cannot be honored falls back -- loudly, one line -- to the
        # default engine, so a config shared between a Mac and the PC keeps working.
        from ..utils.stderr import warn
        warn("  note: WHISPER_BACKEND=mlx unavailable — %s; falling back to "
             "faster-whisper (pip install 'reel-scout[mlx]' on Apple Silicon)" % reason)
        backend = "faster-whisper"
    if backend == "faster-whisper":
        from .faster_whisper import FasterWhisperTranscriber
        return FasterWhisperTranscriber(model=config.WHISPER_MODEL)
    elif backend == "whisper-cpp":
        from .whisper_cpp import WhisperCppTranscriber
        return WhisperCppTranscriber(model=config.WHISPER_MODEL)
    else:
        raise ValueError(f"Unknown whisper backend: {backend}")
