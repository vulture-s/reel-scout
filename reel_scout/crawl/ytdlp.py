"""yt-dlp invocation helpers.

Two long-standing footguns live here (roadmap 5B):

1. Crawlers used to shell out to a bare ``["yt-dlp", ...]``, which resolves to
   the *first* yt-dlp on PATH — often a stale system/homebrew build, NOT the
   version pinned in reel-scout's own venv. yt-dlp breaks constantly (its
   extractors chase moving platforms), so an old binary silently produces
   baffling errors while ``pyproject.toml``'s pinned dependency sits unused.

2. Error messages printed a blind ``stderr[:500]``, which buries the real
   ``ERROR:`` line under leading warnings (e.g. yt-dlp's Python-version
   deprecation banner). Users saw the warning, not the 429/extractor failure.
"""
from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from typing import List, Tuple

from .. import config


@lru_cache(maxsize=1)
def base_cmd() -> Tuple[str, ...]:
    """Resolve the yt-dlp invocation, preferring the copy that ships with this
    package over whatever ``yt-dlp`` happens to be first on PATH.

    Resolution order:
      1. ``config.YTDLP_BIN`` (explicit override)
      2. ``python -m yt_dlp`` via *this* interpreter, if ``yt_dlp`` is importable
         here — guarantees the version that travels with the install
      3. bare ``yt-dlp`` from PATH (last resort)
    """
    if config.YTDLP_BIN:
        return (config.YTDLP_BIN,)
    if importlib.util.find_spec("yt_dlp") is not None:
        return (sys.executable, "-m", "yt_dlp")
    return ("yt-dlp",)


def cmd(*args: str) -> List[str]:
    """yt-dlp base invocation + the given arguments, ready for subprocess.run."""
    return list(base_cmd()) + list(args)


def format_error(stderr: str) -> str:
    """Surface the real failure from yt-dlp's stderr instead of a blind head-cut.

    Keeps the ``ERROR:`` lines when present; otherwise falls back to the tail of
    stderr (the failure is far likelier at the end than in the first 500 chars),
    and appends an update hint when the failure smells like a broken extractor.
    """
    if not stderr:
        return ""
    lines = stderr.strip().splitlines()
    errors = [ln for ln in lines if ln.lstrip().startswith("ERROR:")]
    if errors:
        msg = "\n".join(errors)[:500]
    else:
        msg = stderr.strip()[-500:]
    return msg + _extractor_hint(msg)


def _extractor_hint(msg: str) -> str:
    lowered = msg.lower()
    markers = (
        "unable to extract", "unsupported url", "not available",
        "no video formats", "unable to download webpage",
        "requested format is not available", "unable to download api page",
    )
    if any(m in lowered for m in markers):
        shown = " ".join(base_cmd())
        return (
            "\n[hint] the platform extractor may have changed or yt-dlp is "
            "outdated — update it: `%s -U` (or `pip install -U yt-dlp`)." % shown
        )
    return ""
