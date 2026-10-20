"""mlx-whisper backend (issue #113) — selection, fallback, output-shape parity.

No model is loaded or downloaded: a fake ``mlx_whisper`` module is put in
``sys.modules`` and the platform is pinned, so these run anywhere (CI is Linux).
"""
from __future__ import annotations

import json
import platform
import sqlite3
import sys
import types

import pytest

from reel_scout import config, db
from reel_scout import transcribe as tr
from reel_scout.transcribe.faster_whisper import FasterWhisperTranscriber
from reel_scout.transcribe.mlx_whisper import MlxWhisperTranscriber, resolve_mlx_repo
from reel_scout.utils import stderr as stderr_mod

SIMP = "这个视频说的是开发软件的经验"

#: One raw Whisper segment as each engine hands it back -- same values, each
#: engine's own shape (faster-whisper: objects; mlx-whisper: dicts).
_RAW = [
    dict(start=0.0, end=1.5, text=" 这个视频说的是", no_speech_prob=0.01,
         avg_logprob=-0.2, compression_ratio=1.1),
    dict(start=1.5, end=3.0, text=" 开发软件的经验", no_speech_prob=0.02,
         avg_logprob=-0.3, compression_ratio=1.2),
]


def _fake_mlx(language="zh", raw=_RAW):
    mod = types.ModuleType("mlx_whisper")
    mod.calls = []

    def transcribe(audio, **kwargs):
        mod.calls.append((audio, kwargs))
        return {"text": "".join(r["text"] for r in raw),
                "segments": [dict(r, id=i, seek=0, tokens=[], temperature=0.0)
                             for i, r in enumerate(raw)],
                "language": language}

    mod.transcribe = transcribe
    return mod


@pytest.fixture
def apple_silicon(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")


@pytest.fixture
def fake_mlx(monkeypatch):
    mod = _fake_mlx()
    monkeypatch.setitem(sys.modules, "mlx_whisper", mod)
    return mod


@pytest.fixture
def plain_cfg(monkeypatch):
    for k, v in dict(WHISPER_LANGUAGE="", WHISPER_TASK="transcribe",
                     WHISPER_MULTILINGUAL=False, WHISPER_CHUNK_LENGTH=0,
                     WHISPER_ZH_SCRIPT="off", WHISPER_GUARD_ENABLED=False,
                     WHISPER_MODEL="large-v3-turbo").items():
        monkeypatch.setattr(config, k, v)
    from reel_scout import ffprobe
    monkeypatch.setattr(ffprobe, "probe_duration", lambda _p: 3.0)


def _warnings(monkeypatch):
    seen = []
    monkeypatch.setattr(stderr_mod, "warn", lambda m: seen.append(m))
    return seen


# ------------------------------------------------------------------ selection

def test_explicit_faster_whisper_is_kept_even_where_mlx_runs(monkeypatch, apple_silicon, fake_mlx):
    # mlx installed on Apple Silicon must NOT override an explicit choice.
    monkeypatch.setattr(config, "WHISPER_BACKEND", "faster-whisper")
    assert isinstance(tr.get_transcriber(), FasterWhisperTranscriber)


def test_default_backend_is_auto():
    # Read the getenv default from source: reloading config would re-read the
    # developer's own .env (which may pin a backend) and leak it into os.environ.
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(config))
    defaults = [n.value.args[1].value for n in ast.walk(tree)
                if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == "WHISPER_BACKEND" for t in n.targets)
                and isinstance(n.value, ast.Call)]
    assert defaults == ["auto"]
    assert "auto" in config.WHISPER_BACKENDS


def test_auto_picks_mlx_where_it_runs(monkeypatch, apple_silicon, fake_mlx, plain_cfg):
    warned = _warnings(monkeypatch)
    monkeypatch.setattr(tr, "_auto_note_shown", False)
    monkeypatch.setattr(config, "WHISPER_BACKEND", "auto")
    assert isinstance(tr.get_transcriber(), MlxWhisperTranscriber)
    assert warned == []


def test_auto_is_silent_off_apple_silicon(monkeypatch, fake_mlx):
    warned = _warnings(monkeypatch)
    monkeypatch.setattr(tr, "_auto_note_shown", False)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert isinstance(tr.get_transcriber("auto"), FasterWhisperTranscriber)
    assert warned == []


def test_auto_without_mlx_on_apple_silicon_notes_it_once(monkeypatch, apple_silicon):
    warned = _warnings(monkeypatch)
    monkeypatch.setattr(tr, "_auto_note_shown", False)
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)   # import raises
    for _ in range(3):                                        # e.g. one per video in a batch
        assert isinstance(tr.get_transcriber("auto"), FasterWhisperTranscriber)
    assert len(warned) == 1
    assert "auto using faster-whisper" in warned[0] and "reel-scout[mlx]" in warned[0]


def test_mlx_selected_when_opted_in_and_available(monkeypatch, apple_silicon, fake_mlx, plain_cfg):
    warned = _warnings(monkeypatch)
    monkeypatch.setattr(config, "WHISPER_BACKEND", "mlx")
    t = tr.get_transcriber()
    assert isinstance(t, MlxWhisperTranscriber)
    assert t._repo == "mlx-community/whisper-large-v3-turbo"
    assert warned == []


def test_explicit_backend_argument_wins_over_config(monkeypatch, apple_silicon, fake_mlx, plain_cfg):
    monkeypatch.setattr(config, "WHISPER_BACKEND", "faster-whisper")
    assert isinstance(tr.get_transcriber("mlx"), MlxWhisperTranscriber)


@pytest.mark.parametrize("model, repo", [
    ("large-v3", "mlx-community/whisper-large-v3-mlx"),
    ("large-v3-turbo", "mlx-community/whisper-large-v3-turbo"),
    ("someone/whisper-custom", "someone/whisper-custom"),
])
def test_model_name_maps_to_an_mlx_repo(model, repo):
    assert resolve_mlx_repo(model) == repo


def test_unknown_short_model_name_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="no known mlx repo"):
        resolve_mlx_repo("medium.en")


def test_cli_accepts_mlx_and_rejects_typos(monkeypatch, capsys):
    from reel_scout import cli
    from reel_scout.transcribe.base import TranscriptResult

    asked = []

    class _Stub:
        def transcribe(self, path):
            return TranscriptResult(language="en", text_full="ok")

    monkeypatch.setattr(tr, "get_transcriber", lambda b=None: asked.append(b) or _Stub())
    cli.main(["transcribe", "x.mp4", "--backend", "mlx"])
    assert asked == ["mlx"]
    with pytest.raises(SystemExit):
        cli.main(["transcribe", "x.mp4", "--backend", "mlxx"])
    assert "invalid choice" in capsys.readouterr().err


# ------------------------------------------------------------------ fallback

def test_fallback_when_mlx_not_installed(monkeypatch, apple_silicon):
    warned = _warnings(monkeypatch)
    monkeypatch.setitem(sys.modules, "mlx_whisper", None)   # import raises
    monkeypatch.setattr(config, "WHISPER_BACKEND", "mlx")
    t = tr.get_transcriber()
    assert isinstance(t, FasterWhisperTranscriber)
    assert len(warned) == 1 and "falling back to faster-whisper" in warned[0]
    assert "not importable" in warned[0]


def test_fallback_when_not_apple_silicon(monkeypatch, fake_mlx):
    warned = _warnings(monkeypatch)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    t = tr.get_transcriber("mlx")
    assert isinstance(t, FasterWhisperTranscriber)
    assert len(warned) == 1 and "not Apple Silicon" in warned[0]


def test_rosetta_python_counts_as_not_apple_silicon(monkeypatch, fake_mlx):
    # An x86_64 interpreter on an M-series Mac cannot run Metal mlx.
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert "not Apple Silicon" in tr.mlx_unavailable_reason()


# ------------------------------------------------------------------ decode kwargs

def test_decode_kwargs_have_no_beam_search(monkeypatch, apple_silicon, fake_mlx, plain_cfg):
    MlxWhisperTranscriber("large-v3-turbo").transcribe("a.mp4")
    audio, kw = fake_mlx.calls[-1]
    assert audio == "a.mp4"
    assert kw["path_or_hf_repo"] == "mlx-community/whisper-large-v3-turbo"
    assert "beam_size" not in kw          # mlx-whisper raises NotImplementedError on it
    assert kw["word_timestamps"] is True and kw["hallucination_silence_threshold"] == 2.0
    assert "language" not in kw and "initial_prompt" not in kw


def test_forced_language_and_task_pass_through(monkeypatch, apple_silicon, fake_mlx, plain_cfg):
    monkeypatch.setattr(config, "WHISPER_LANGUAGE", "en")
    monkeypatch.setattr(config, "WHISPER_TASK", "translate")
    MlxWhisperTranscriber().transcribe("a.mp4")
    kw = fake_mlx.calls[-1][1]
    assert kw["language"] == "en" and kw["task"] == "translate"


def test_multilingual_is_ignored_out_loud(monkeypatch, apple_silicon, fake_mlx, plain_cfg):
    warned = _warnings(monkeypatch)
    monkeypatch.setattr(config, "WHISPER_MULTILINGUAL", True)
    MlxWhisperTranscriber().transcribe("a.mp4")
    assert "multilingual" not in fake_mlx.calls[-1][1]
    assert any("WHISPER_MULTILINGUAL" in w for w in warned)


def test_traditional_seed_uses_the_shared_rule(monkeypatch, apple_silicon, fake_mlx, plain_cfg):
    monkeypatch.setattr(config, "WHISPER_ZH_SCRIPT", "traditional")
    monkeypatch.setattr(config, "WHISPER_ZH_PROMPT", "以下是一段繁體中文的逐字稿。")
    t = MlxWhisperTranscriber()
    monkeypatch.setattr(t, "_probe_language", lambda _p: "zh")
    t.transcribe("a.mp4")
    kw = fake_mlx.calls[-1][1]
    assert kw["initial_prompt"] == "以下是一段繁體中文的逐字稿。" and kw["language"] == "zh"


def test_japanese_audio_gets_no_seed(monkeypatch, apple_silicon, fake_mlx, plain_cfg):
    monkeypatch.setattr(config, "WHISPER_ZH_SCRIPT", "traditional")
    t = MlxWhisperTranscriber()
    monkeypatch.setattr(t, "_probe_language", lambda _p: "ja")
    t.transcribe("a.mp4")
    assert "initial_prompt" not in fake_mlx.calls[-1][1]


def test_language_probe_goes_through_mlx_transcribe(monkeypatch, apple_silicon, plain_cfg):
    mod = _fake_mlx(language="yue")
    monkeypatch.setitem(sys.modules, "mlx_whisper", mod)
    assert MlxWhisperTranscriber()._detect_language("ARRAY") == "yue"
    audio, kw = mod.calls[-1]
    assert audio == "ARRAY" and "language" not in kw


def test_guard_gets_the_probability_fields(monkeypatch, apple_silicon, fake_mlx, plain_cfg):
    seen = []
    from reel_scout.transcribe import faster_whisper as fw
    monkeypatch.setattr(fw, "_apply_guard", lambda segs: seen.extend(segs) or segs[:1])
    res = MlxWhisperTranscriber().transcribe("a.mp4")
    assert {"no_speech_prob", "avg_logprob", "compression_ratio"} <= set(seen[0])
    assert len(res.segments) == 1        # what the guard kept is what comes back


# ------------------------------------------------------------------ output-shape parity

class _Seg:
    def __init__(self, d):
        self.__dict__.update(d)


class _Info:
    language = "zh"
    duration = 3.0


class _FakeFW:
    def transcribe(self, audio_path, **kwargs):
        return iter([_Seg(r) for r in _RAW]), _Info()


def _both(monkeypatch):
    fw = FasterWhisperTranscriber("large-v3-turbo")
    fw._model = _FakeFW()
    return fw.transcribe("a.mp4"), MlxWhisperTranscriber("large-v3-turbo").transcribe("a.mp4")


def test_result_shape_matches_faster_whisper(monkeypatch, apple_silicon, fake_mlx, plain_cfg):
    a, b = _both(monkeypatch)
    assert type(a) is type(b)
    for field in ("language", "text_full", "duration_sec"):
        assert getattr(a, field) == getattr(b, field), field
    assert [vars(s) for s in a.segments] == [vars(s) for s in b.segments]
    assert a.model == "large-v3-turbo"
    assert b.model == "mlx:mlx-community/whisper-large-v3-turbo"   # provenance for A/B


def test_saved_rows_are_identical_incl_zh_conversion(monkeypatch, temp_db, need_opencc,
                                                     apple_silicon, fake_mlx, plain_cfg):
    """Through `save_transcript` both engines land the same row: s2twp applied,
    the received Simplified kept in the v21 `*_original` columns."""
    monkeypatch.setattr(config, "ZH_CONVERT", "s2twp")
    monkeypatch.setattr(config, "ZH_HOTWORDS", "")
    monkeypatch.setattr(db, "_zh_missing_warned", False)
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    rows = []
    for i, res in enumerate(_both(monkeypatch)):
        vid = db.upsert_video(conn, platform="youtube", platform_id="p%d" % i,
                              url="u%d" % i, title="t")
        segs = [{"start": s.start, "end": s.end, "text": s.text, "confidence": s.confidence}
                for s in res.segments]       # what pipeline.py / cli.py serialize
        db.save_transcript(conn, vid, language=res.language, text_full=res.text_full,
                           segments_json=json.dumps(segs, ensure_ascii=False),
                           whisper_model=res.model, duration_sec=res.duration_sec)
        rows.append(dict(conn.execute("SELECT * FROM transcripts WHERE video_id=?",
                                      (vid,)).fetchone()))
    conn.close()
    a, b = rows
    for k in ("language", "text_full", "segments_json", "text_full_original",
              "segments_json_original", "zh_conversion", "duration_sec"):
        assert a[k] == b[k], k
    assert b["text_full"] == "這個影片說的是 開發軟體的經驗"
    assert b["text_full_original"] == "这个视频说的是 开发软件的经验"
    assert b["zh_conversion"] == "s2twp"
