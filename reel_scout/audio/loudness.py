"""Programme loudness (EBU R128 / ITU-R BS.1770) measured by ffmpeg's ebur128 filter.

Why ffmpeg and not a numpy implementation: the K-weighting is a pair of IIR
biquads, and running them over minutes of 48 kHz audio needs scipy's lfilter —
which this repo deliberately does not carry (see `rhythm.py`). ffmpeg is already
required for everything else, ebur128 is the reference implementation most
mixing tools are checked against, and it measures at ~200x realtime on an M2 Max.

The three numbers that answer "how loud is this reel mixed":

    integrated_lufs   BS.1770 integrated loudness (gated)          e.g. -14.3
    lra_lu            loudness range (EBU Tech 3342)                e.g.   7.9
    true_peak_dbtp    4x-oversampled peak, the one platforms limit  e.g.  -0.7

`sample_peak_dbfs` is kept next to it because a true peak well above the sample
peak is itself a finding (inter-sample overs from a hot limiter).

Read the integrated number per platform, not across them. Meta re-encodes
uploads to a loudness target: on 2026-11-10, 15 Instagram reels sampled from
the M2 Max library all read -14.0 to -14.6 LUFS, and Threads the same, while
YouTube files (normalised at playback, not in the file) spread from -30 to
-12. So for IG / Threads the integrated value says "Meta's target", not "how
the creator mixed it" -- LRA and true peak still carry the mix. YouTube
integrated loudness is the creator's own.

A file with no audio stream is not an error worth a traceback, and it is not a
measurement of silence either: `measure` raises `NoAudio` for it so the caller
can store nothing rather than a fake -70. Digital silence *is* measured —
ebur128 reports -70 LUFS, and that is the honest answer for a muted reel.
"""
from __future__ import annotations

import re
import subprocess
from typing import Dict, Optional

from .. import config
from ..utils.stderr import tail_stderr

#: ebur128 has no integrated value below its absolute gate; it prints -70.0.
SILENCE_LUFS = -70.0


class NoAudio(Exception):
    """The input has no audio stream to measure."""


_NUM = r"(-?inf|-?\d+(?:\.\d+)?)"
_PATTERNS = {
    "integrated_lufs": re.compile(r"Integrated loudness:\s*\n\s*I:\s*" + _NUM + r"\s*LUFS"),
    "lra_lu": re.compile(r"Loudness range:\s*\n\s*LRA:\s*" + _NUM + r"\s*LU"),
    "sample_peak_dbfs": re.compile(r"Sample peak:\s*\n\s*Peak:\s*" + _NUM + r"\s*dBFS"),
    "true_peak_dbtp": re.compile(r"True peak:\s*\n\s*Peak:\s*" + _NUM + r"\s*dBFS"),
}


def _num(s: str) -> Optional[float]:
    if s.endswith("inf"):
        return None
    return float(s)


def parse_summary(stderr: str) -> Dict[str, Optional[float]]:
    """Read the `Summary:` block ebur128 prints at the end of a run.

    Only the summary is read, never the per-frame progress lines above it (they
    carry momentary values with the same labels). A field ffmpeg did not print
    is None rather than a guess.
    """
    i = stderr.rfind("Summary:")
    if i < 0:
        raise ValueError("ebur128 printed no summary")
    block = stderr[i:]
    out: Dict[str, Optional[float]] = {}
    for key, rx in _PATTERNS.items():
        m = rx.search(block)
        out[key] = _num(m.group(1)) if m else None
    if out["integrated_lufs"] is None:
        raise ValueError("ebur128 summary has no integrated loudness")
    return out


def measure(path: str, timeout: int = 600) -> Dict[str, Optional[float]]:
    """Measure one file's first audio stream. Raises NoAudio if it has none."""
    cmd = [
        config.FFMPEG_BIN, "-nostdin", "-hide_banner", "-nostats",
        "-i", path,
        "-map", "0:a:0",
        "-af", "ebur128=peak=true+sample",
        "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    err = r.stderr or ""
    if r.returncode != 0:
        if "matches no streams" in err or "does not contain any stream" in err:
            raise NoAudio("no audio stream in %s" % path)
        raise RuntimeError("ebur128 failed: %s" % tail_stderr(err))
    return parse_summary(err)
