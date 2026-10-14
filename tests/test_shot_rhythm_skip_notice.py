"""When the shot table comes back None, the pipeline must say so on stderr.

It used to skip the measurement silently: no cuts/min, no line, so "the step
never ran" and "it ran and failed" were indistinguishable afterwards. The audio
half already printed `Audio rhythm skipped: <reason>`; this pins the cut half to
the same shape. Paired with the good case: a real table must print no skip line.
"""
from __future__ import annotations

import json

from reel_scout import shots
from reel_scout.analyze import pipeline
from reel_scout.audio import extract as audio_extract

from tests.test_invalid_media_pipeline import _harness, _options


def _frames():
    return [
        type("KF", (), {"frame_index": i, "timestamp_sec": float(i),
                        "file_path": "f%d.jpg" % i, "strategy": "scene"})()
        for i in range(6)
    ]


def _run(tmp_path, monkeypatch, fake_table):
    conn, url, vid = _harness(tmp_path, monkeypatch, duration=60.0)
    monkeypatch.setattr(pipeline.config, "SHOT_METRICS_ENABLED", True)
    monkeypatch.setattr(pipeline, "extract_keyframes", lambda *a, **k: _frames())
    monkeypatch.setattr(shots, "compute_shot_table", fake_table)

    def no_audio(*a, **k):
        raise RuntimeError("no audio in test")
    monkeypatch.setattr(audio_extract, "extract_wav", no_audio)
    # Pre-seed the analysis so merge is skipped without reaching an LLM.
    db = pipeline.db
    db.save_analysis(conn, vid, summary="s", topics_json="[]", hooks_json="{}",
                     style_json="{}", engagement_signals_json="{}",
                     full_json=json.dumps({"content_type": "educational"}))
    try:
        assert pipeline._process_single(conn, url, _options()) == vid
    finally:
        conn.close()


def test_none_table_prints_the_reason(tmp_path, monkeypatch, capsys):
    def fake(path, duration_sec=None, on_skip=None, **kw):
        on_skip("ffmpeg scene pass exited 1: moov atom not found")
        return None
    _run(tmp_path, monkeypatch, fake)
    err = capsys.readouterr().err
    assert "  Shot rhythm skipped: ffmpeg scene pass exited 1: moov atom not found\n" in err
    # Same shape as the audio half it mirrors.
    assert "  Audio rhythm skipped: no audio in test\n" in err


def test_none_table_without_a_reason_still_speaks(tmp_path, monkeypatch, capsys):
    _run(tmp_path, monkeypatch, lambda *a, **k: None)
    err = capsys.readouterr().err
    assert "  Shot rhythm skipped: no shot table (reason not reported)\n" in err


def test_a_real_table_prints_no_skip_line(tmp_path, monkeypatch, capsys):
    table = (shots.metrics_from_cuts(2, 60.0), shots.shots_from_cuts([10.0, 20.0], 60.0))
    _run(tmp_path, monkeypatch, lambda *a, **k: table)
    out = capsys.readouterr()
    assert "Shot rhythm skipped" not in out.err
    assert "Shot metrics: 2.00 cuts/min, 3 shots" in out.out
