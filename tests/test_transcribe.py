"""Transcriber kwargs building — guards the bilingual/code-switching fix.

whisper large-v3 locks language from the opening window and garbles the other
language on long code-switching files. The fix is opt-in per-chunk re-detection
(WHISPER_MULTILINGUAL=1 + WHISPER_CHUNK_LENGTH=15). These tests pin the mapping
from config -> faster-whisper transcribe() kwargs without loading a model.
"""
from __future__ import annotations

import sys

from reel_scout import config
from reel_scout.transcribe.faster_whisper import FasterWhisperTranscriber, _apply_guard


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


# ---------------------------------------------------------------------------
# R-guard — whisper-guard anti-hallucination filtering on the transcribe path
# ---------------------------------------------------------------------------

class _GuardSeg:
    """A faster-whisper-shaped segment carrying the per-segment probabilities the
    guard reads (the real Segment dataclass drops these)."""
    def __init__(self, start, end, text, no_speech_prob=0.0, avg_logprob=-0.1,
                 compression_ratio=1.0):
        self.start = start
        self.end = end
        self.text = text
        self.no_speech_prob = no_speech_prob
        self.avg_logprob = avg_logprob
        self.compression_ratio = compression_ratio


def _run_transcribe(monkeypatch, segs, **cfg):
    defaults = dict(
        WHISPER_LANGUAGE="", WHISPER_TASK="transcribe",
        WHISPER_MULTILINGUAL=False, WHISPER_CHUNK_LENGTH=0,
        WHISPER_GUARD_ENABLED=True,
    )
    defaults.update(cfg)
    for k, v in defaults.items():
        monkeypatch.setattr(config, k, v)

    class _Model:
        def transcribe(self, audio_path, **kwargs):
            return iter(segs), _FakeInfo()

    t = FasterWhisperTranscriber()
    t._model = _Model()
    return t.transcribe("dummy.wav")


def test_guard_drops_hallucinated_segments(monkeypatch):
    segs = [
        _GuardSeg(0.0, 2.0, "真正的語音內容在這裡。"),               # kept
        _GuardSeg(2.0, 2.8, "字幕", no_speech_prob=0.95),           # silence → dropped
        _GuardSeg(2.8, 4.5, "低信心幻覺段落", avg_logprob=-2.0),      # low logprob → dropped
    ]
    result = _run_transcribe(monkeypatch, segs)
    assert [s.text for s in result.segments] == ["真正的語音內容在這裡。"]
    # text_full is rebuilt from the kept segments, so it excludes the dropped ones
    assert result.text_full == "真正的語音內容在這裡。"


def test_guard_disabled_keeps_all_segments(monkeypatch):
    segs = [
        _GuardSeg(0.0, 2.0, "good"),
        _GuardSeg(2.0, 2.8, "noise", no_speech_prob=0.95),
    ]
    result = _run_transcribe(monkeypatch, segs, WHISPER_GUARD_ENABLED=False)
    assert [s.text for s in result.segments] == ["good", "noise"]


def test_apply_guard_degrades_when_package_missing(monkeypatch):
    # A partial install (whisper-guard absent) must not hard-fail transcription.
    monkeypatch.setitem(sys.modules, "whisper_guard", None)  # force ImportError
    monkeypatch.setattr(config, "WHISPER_GUARD_ENABLED", True)
    raw = [{"start": 0.0, "end": 1.0, "text": "hi", "no_speech_prob": 0.0,
            "avg_logprob": -0.1, "compression_ratio": 1.0}]
    assert _apply_guard(raw) == raw   # returned unchanged, no exception


def test_apply_guard_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "WHISPER_GUARD_ENABLED", False)
    raw = [{"start": 0.0, "end": 1.0, "text": "anything", "no_speech_prob": 0.99}]
    assert _apply_guard(raw) is raw   # exact same object, not even re-filtered
