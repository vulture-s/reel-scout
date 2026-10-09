"""compute_rhythm must not hold a whole clip's audio in memory.

It used to read the entire 16 kHz WAV into a Python list of floats: measured
2026-10-09 at ~70 MB of resident memory per minute of audio, linear, so a
four-hour livestream (the library has them) needed ~17 GB for a step that
only wants an energy number and a tempo. On a 16 GB machine that is not an
exception anyone can catch -- the process is swapped to a halt or killed.

The answer must not change: the streamed envelope is checked against the
whole-file path on the same audio.
"""
from __future__ import annotations

import array
import math
import os
import tracemalloc
import wave

import pytest

from reel_scout.audio import rhythm
from reel_scout.audio.panns import _read_wav_samples

np = pytest.importorskip("numpy")

SR = 16000


def _click_track(path, seconds, bpm=120.0, channels=1):
    period = int(SR * 60.0 / bpm)
    n = SR * seconds
    a = array.array("h", [0]) * (n * channels)
    for start in range(0, n, period):
        for k in range(min(200, n - start)):
            for c in range(channels):
                a[(start + k) * channels + c] = 26000
    # a little noise floor so the envelope is not flat between clicks
    for i in range(0, n * channels, 97):
        a[i] = 300
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(a.tobytes())


def _whole_file_answer(path):
    samples, sr = _read_wav_samples(path)
    out = rhythm.analyze_bpm(samples, sr)
    out["energy"] = round(rhythm._rms(samples), 4)
    return out


@pytest.mark.parametrize("channels", [1, 2])
def test_streamed_answer_matches_the_whole_file_answer(tmp_path, channels):
    path = str(tmp_path / "click.wav")
    _click_track(path, 20, channels=channels)
    streamed = rhythm.compute_rhythm(path)
    whole = _whole_file_answer(path)
    assert streamed["energy"] == pytest.approx(whole["energy"], abs=1e-4)
    assert streamed["candidate_bpm"] == whole["candidate_bpm"]
    assert streamed["bpm"] == whole["bpm"]
    assert streamed["peak_ratio"] == pytest.approx(whole["peak_ratio"], abs=2e-3)


def test_memory_does_not_scale_with_the_clip(tmp_path):
    path = str(tmp_path / "long.wav")
    _click_track(path, 300)  # five minutes: ~4.8M samples
    tracemalloc.start()
    try:
        rhythm.compute_rhythm(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # The whole-file path peaks well above 150 MB here; streaming holds one
    # chunk plus a 31-values-per-second envelope.
    assert peak < 48 * 1024 * 1024, "peak %.0f MB" % (peak / 1e6)


def test_too_short_is_still_blank(tmp_path):
    path = str(tmp_path / "short.wav")
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(array.array("h", [1000] * 2000).tobytes())
    r = rhythm.compute_rhythm(path)
    assert r["bpm"] is None and r["candidate_bpm"] is None
    assert r["energy"] == pytest.approx(round(1000 / 32768.0, 4), abs=1e-4)


# Review follow-up (2026-10-09): the equivalence test above is 20 s, which is
# inside one read (_CHUNK is ~65 s at 16 kHz), so the cross-chunk path was never
# compared. Shrink the chunk so the same clip spans ~150 reads, with a length
# that is not a whole number of hops, and require the same answer.
@pytest.mark.parametrize("channels", [1, 2])
def test_the_answer_is_the_same_across_many_chunk_boundaries(tmp_path, monkeypatch, channels):
    path = str(tmp_path / "click.wav")
    _click_track(path, 20, channels=channels)
    with wave.open(path, "rb") as wf:                 # trim to a ragged length
        params, frames = wf.getparams(), wf.readframes(wf.getnframes() - 333)
    with wave.open(path, "wb") as wf:
        wf.setparams(params)
        wf.writeframes(frames)
    whole = _whole_file_answer(path)
    monkeypatch.setattr(rhythm, "_CHUNK", rhythm._HOP * 4)
    streamed = rhythm.compute_rhythm(path)
    assert streamed["energy"] == pytest.approx(whole["energy"], abs=1e-4)
    assert streamed["candidate_bpm"] == whole["candidate_bpm"]
    assert streamed["bpm"] == whole["bpm"]
    assert streamed["peak_ratio"] == pytest.approx(whole["peak_ratio"], abs=2e-3)
    _sr, _total, _sumsq, blocks = rhythm._stream_wav(path)
    assert blocks.size == _total // rhythm._HOP       # no block lost or split


def test_the_chunk_stays_a_whole_number_of_hops():
    # The reader carries nothing across reads; that is only correct while
    # every read but the last ends on a hop boundary.
    assert rhythm._CHUNK % rhythm._HOP == 0
