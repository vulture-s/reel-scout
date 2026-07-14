"""Transcriber kwargs building — guards the bilingual/code-switching fix.

whisper large-v3 locks language from the opening window and garbles the other
language on long code-switching files. The fix is opt-in per-chunk re-detection
(WHISPER_MULTILINGUAL=1 + WHISPER_CHUNK_LENGTH=15). These tests pin the mapping
from config -> faster-whisper transcribe() kwargs without loading a model.
"""
from __future__ import annotations

from reel_scout import config
from reel_scout.transcribe.faster_whisper import FasterWhisperTranscriber


class _FakeSeg:
    start = 0.0
    end = 1.0
    text = "hi"
    avg_logprob = -0.1


class _FakeInfo:
    language = "en"
    duration = 1.0


class _FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio_path, **kwargs):
        self.calls.append(kwargs)
        return iter([_FakeSeg()]), _FakeInfo()


def _run(monkeypatch, **cfg):
    defaults = dict(
        WHISPER_LANGUAGE="", WHISPER_TASK="transcribe",
        WHISPER_MULTILINGUAL=False, WHISPER_CHUNK_LENGTH=0,
    )
    defaults.update(cfg)
    for k, v in defaults.items():
        monkeypatch.setattr(config, k, v)
    t = FasterWhisperTranscriber()
    fake = _FakeModel()
    t._model = fake  # skip _ensure_model / real model load
    t.transcribe("dummy.wav")
    return fake.calls[0]


def test_defaults_reproduce_prior_behavior(monkeypatch):
    kw = _run(monkeypatch)
    assert kw == {"beam_size": 5, "vad_filter": True}
    assert "language" not in kw and "task" not in kw and "multilingual" not in kw


def test_force_language(monkeypatch):
    kw = _run(monkeypatch, WHISPER_LANGUAGE="en")
    assert kw["language"] == "en"


def test_translate_task(monkeypatch):
    kw = _run(monkeypatch, WHISPER_TASK="translate")
    assert kw["task"] == "translate"


def test_multilingual_with_chunk(monkeypatch):
    kw = _run(monkeypatch, WHISPER_MULTILINGUAL=True, WHISPER_CHUNK_LENGTH=15)
    assert kw["multilingual"] is True
    assert kw["chunk_length"] == 15


def test_multilingual_ignored_when_language_forced(monkeypatch):
    # per-chunk detection is meaningless if a single language is forced
    kw = _run(monkeypatch, WHISPER_LANGUAGE="zh", WHISPER_MULTILINGUAL=True, WHISPER_CHUNK_LENGTH=15)
    assert kw["language"] == "zh"
    assert "multilingual" not in kw
