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
