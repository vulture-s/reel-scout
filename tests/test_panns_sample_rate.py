"""PANNs is fed the sample rate its front-end was trained on (2026-10-09).

Cnn14 bakes a 32 kHz mel front-end into the graph. The analyze pipeline
extracted the WAV for it with `extract_wav`'s 16 kHz default -- the rate
Whisper wants -- so every 2-second window reached the model as one second of
audio at double pitch. Measured on one local clip, same 120 s, only the rate
changed: 16 kHz gave Speech 95 windows plus Gargling 5 / Animal 3 / Frog 2;
32 kHz gave Speech 118 and no animals at all. The "it mishears talk as animal
noise" caveat in `analyze/audio_summary.py` was this, not the detector.

The fix (commit 6ed54db) sat on `fix/panns-32khz` and never reached master.
Pinned at both ends this time: the analyzer refuses a WAV at the wrong rate
instead of inferring on it, and the pipeline extracts at the analyzer's rate.
"""
from __future__ import annotations

import os
import sqlite3
import struct
import tempfile
import wave

import pytest

from reel_scout import db
from reel_scout.analyze import pipeline
from reel_scout.audio import panns
from reel_scout.audio.base import AudioTimeline


def _wav(rate, seconds=2.0):
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    n = int(rate * seconds)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % n, *([0] * n)))
    return path


class _Session:
    def get_inputs(self):
        class _In:
            name = "input"
        return [_In()]

    def run(self, _o, feed):
        import numpy as np
        return [np.array([[0.9] + [0.001] * 4], dtype=np.float32)]


def _analyzer():
    a = panns.PannsAnalyzer(model_path="/fake")
    a._session = _Session()
    a._labels = ["Speech", "Music", "Animal", "Frog", "Gargling"]
    return a


def test_the_analyzer_declares_32k():
    assert panns.SAMPLE_RATE == 32000
    assert panns.PannsAnalyzer(model_path="/fake").sample_rate == 32000


def test_a_16k_wav_is_refused_not_inferred_on():
    path = _wav(16000)
    try:
        with pytest.raises(ValueError, match="32000"):
            _analyzer().analyze(path)
    finally:
        os.unlink(path)


def test_a_32k_wav_is_analyzed_with_2s_windows():
    path = _wav(32000, seconds=3.0)
    try:
        tl = _analyzer().analyze(path)
    finally:
        os.unlink(path)
    assert tl.duration_sec == 3.0
    # A 2-second window is 2 seconds of audio again, not 4.
    assert (tl.events[0].start_sec, tl.events[0].end_sec) == (0.0, 2.0)


class _Stop(Exception):
    pass


def test_the_pipeline_extracts_audio_at_the_analyzers_rate(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline.config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline.config, "KEYFRAMES_DIR", str(tmp_path / "kf"))
    monkeypatch.setattr(pipeline.config, "VIDEOS_DIR", str(tmp_path / "videos"))
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"\x00")
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    url = "https://www.youtube.com/watch?v=pannsrate"
    db.upsert_video(conn, platform="youtube", platform_id="pannsrate", url=url,
                    title="t", duration_sec=10.0, file_path=str(media),
                    file_size_bytes=1)

    rates = []

    def fake_extract(video_path, output_path, sample_rate=16000):
        rates.append(sample_rate)
        with open(output_path, "wb") as f:
            f.write(b"")
        return output_path

    class _Fake:
        sample_rate = panns.SAMPLE_RATE

        def analyze(self, _p):
            return AudioTimeline()

    import reel_scout.audio as audio_pkg
    import reel_scout.audio.extract as extract_mod
    monkeypatch.setattr(extract_mod, "extract_wav", fake_extract)
    monkeypatch.setattr(audio_pkg, "get_audio_analyzer", lambda *a, **k: _Fake())
    # Stop the run right after the audio step.
    monkeypatch.setattr(pipeline, "extract_keyframes",
                        lambda *a, **k: (_ for _ in ()).throw(_Stop()))
    opts = pipeline.PipelineOptions(skip_transcribe=True, skip_vision=True,
                                    skip_audio=False, skip_diarize=True)
    try:
        with pytest.raises(_Stop):
            pipeline._process_single(conn, url, opts)
    finally:
        conn.close()
    assert rates == [32000]


# --- memory: 32 kHz doubled the per-minute cost of the Python-list reader -----
# Review follow-up (2026-10-09). The analyzer now reads one float32 array; the
# values must be exactly what the list reader produced (the model got them as
# float32 anyway), and the peak must not scale at ~40 bytes per sample.

def _wav_pattern(rate, seconds, width=2, channels=1):
    import random
    rnd = random.Random(7)
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    n = int(rate * seconds) * channels
    lim = 32767 if width == 2 else 2147483647
    vals = [rnd.randint(-lim - 1, lim) for _ in range(n)]
    with wave.open(path, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(struct.pack("<%d%s" % (n, "h" if width == 2 else "i"), *vals))
    return path


@pytest.mark.parametrize("width,channels", [(2, 1), (2, 2), (4, 1), (4, 2)])
def test_the_array_reader_matches_the_list_reader_bit_for_bit(width, channels):
    import numpy as np
    path = _wav_pattern(8000, 0.5, width=width, channels=channels)
    try:
        listed, sr1 = panns._read_wav_samples(path)
        arr, sr2 = panns._read_wav_array(path)
    finally:
        os.unlink(path)
    assert sr1 == sr2 == 8000
    assert arr.dtype == np.float32
    assert np.array_equal(arr, np.array(listed, dtype=np.float32))


def test_analyzing_a_minute_does_not_hold_a_python_float_per_sample():
    import tracemalloc
    path = _wav(32000, seconds=60.0)          # 1.92 M samples
    try:
        a = _analyzer()
        tracemalloc.start()
        a.analyze(path)
        _cur, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    finally:
        os.unlink(path)
    # list-of-floats: ~1.92 M x ~40 B = ~75 MB. float32 + raw bytes: ~12 MB.
    assert peak < 30 * 1024 * 1024, "peak %.1f MB" % (peak / 1048576.0)
