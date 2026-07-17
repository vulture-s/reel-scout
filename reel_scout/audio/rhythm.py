"""Audio rhythm signals — energy + BPM, the audio half of §4E.

These back the pacing score with *measured* audio evidence, independent of the
optional PANNs event detector (which needs onnxruntime + a downloaded model).
Energy (RMS loudness) is pure-stdlib and always available. BPM (tempo) uses an
onset-envelope autocorrelation and is numpy-gated + best-effort — it returns
None rather than a shaky guess when it can't find a stable tempo.

No librosa/scipy: that would drag numba+scipy and break the repo's minimal-deps
+ py3.9 principle. numpy is already the `audio` optional extra.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from .panns import _read_wav_samples


def _rms(samples: List[float]) -> float:
    """Root-mean-square loudness of normalized (-1..1) samples. Pure stdlib."""
    if not samples:
        return 0.0
    total = 0.0
    for s in samples:
        total += s * s
    return math.sqrt(total / len(samples))


def estimate_bpm(samples: List[float], sr: int) -> Optional[float]:
    """Best-effort tempo (BPM) via onset-envelope autocorrelation. numpy-gated;
    returns None on missing numpy, too-short audio, or no stable peak."""
    try:
        import numpy as np
    except ImportError:
        return None
    try:
        x = np.asarray(samples, dtype=np.float32)
        frame, hop = 1024, 512
        if x.size < frame * 4:
            return None
        n_frames = 1 + (x.size - frame) // hop
        env = np.empty(n_frames, dtype=np.float32)
        for i in range(n_frames):
            seg = x[i * hop: i * hop + frame]
            env[i] = math.sqrt(float(np.mean(seg * seg)))
        # onset strength = positive first difference of the energy envelope
        onset = np.diff(env)
        onset[onset < 0] = 0.0
        if onset.size < 4 or float(onset.std()) == 0.0:
            return None
        onset = onset - onset.mean()
        ac = np.correlate(onset, onset, mode="full")
        ac = ac[ac.size // 2:]
        fps = sr / hop  # envelope frames per second
        min_bpm, max_bpm = 60.0, 180.0
        min_lag = int(fps * 60.0 / max_bpm)
        max_lag = int(fps * 60.0 / min_bpm)
        if min_lag < 1 or max_lag >= ac.size:
            return None
        window = ac[min_lag: max_lag + 1]
        if window.size == 0:
            return None
        best_lag = int(np.argmax(window)) + min_lag
        if best_lag <= 0:
            return None
        return round(fps * 60.0 / best_lag, 1)
    except Exception:  # noqa: BLE001 — best-effort; any numeric hiccup → no BPM
        return None


def compute_rhythm(wav_path: str) -> Dict[str, Optional[float]]:
    """Read a mono WAV and return {'energy': float|None, 'bpm': float|None}."""
    try:
        samples, sr = _read_wav_samples(wav_path)
    except (OSError, ValueError, EOFError):
        return {"energy": None, "bpm": None}
    if not samples:
        return {"energy": None, "bpm": None}
    return {
        "energy": round(_rms(samples), 4),
        "bpm": estimate_bpm(samples, sr),
    }
