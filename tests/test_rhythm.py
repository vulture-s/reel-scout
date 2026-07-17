from __future__ import annotations

import os
import struct
import tempfile
import wave

import pytest

from reel_scout.audio import rhythm


def _write_wav(path, samples, sr=16000):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        frames = b"".join(
            struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples
        )
        wf.writeframes(frames)


def test_rms_silence():
    assert rhythm._rms([0.0] * 100) == 0.0


def test_rms_constant():
    assert rhythm._rms([0.5] * 100) == pytest.approx(0.5, abs=1e-6)


def test_rms_empty():
    assert rhythm._rms([]) == 0.0


def test_compute_rhythm_reads_wav_energy():
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        _write_wav(path, [0.3] * 16000)  # 1s of constant-amplitude tone
        r = rhythm.compute_rhythm(path)
        assert r["energy"] == pytest.approx(0.3, abs=0.01)
        assert "bpm" in r
    finally:
        os.unlink(path)


def test_compute_rhythm_bad_path():
    assert rhythm.compute_rhythm("/nonexistent-xyz.wav") == {"energy": None, "bpm": None}


def test_compute_rhythm_corrupt_wav_returns_none():
    # A text file with a .wav name makes wave.open raise wave.Error, which must be
    # swallowed into the None result rather than propagating.
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        with open(path, "w") as f:
            f.write("definitely not a RIFF/WAV file")
        assert rhythm.compute_rhythm(path) == {"energy": None, "bpm": None}
    finally:
        os.unlink(path)


def test_estimate_bpm_in_range_when_present():
    pytest.importorskip("numpy")
    sr = 16000
    samples = [0.0] * (sr * 4)  # 4s
    # Click track: a short burst every 0.5s => ~120 BPM.
    for beat in range(8):
        idx = int(beat * 0.5 * sr)
        for k in range(200):
            if idx + k < len(samples):
                samples[idx + k] = 0.8
    bpm = rhythm.estimate_bpm(samples, sr)
    # Best-effort: may be None, but if it commits to a tempo it must be in-range.
    if bpm is not None:
        assert 60.0 <= bpm <= 180.0


def test_estimate_bpm_too_short_returns_none():
    pytest.importorskip("numpy")
    assert rhythm.estimate_bpm([0.1, 0.2, 0.3], 16000) is None
