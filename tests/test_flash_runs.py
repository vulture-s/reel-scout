"""Flash runs: strobe / flash-montage / stop-motion stretches counted as one beat.

The cut detector is right about these clips -- `DU0c4QzCBvM` really changes
picture every two frames (110 cuts in 8.9s, 731 cuts/min) and `DZugvfhNmz2`
("19 bottles, 20, 21 ...") every three. What cuts/min cannot say is that a
viewer reads each stretch as one beat. These pin the segment view: its numbers,
that it never touches clips without such runs, that the keyframe cap grows by
segments rather than cuts, and that merge and score both get told.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from reel_scout import config, db, scorer, shots
from reel_scout.analyze import merger
from reel_scout.vision import keyframe

KOMPAN_CUTS = [
    2.36, 3.8, 5.08, 7.2, 7.96, 9.36, 11.08, 12.52, 14.28, 17.6, 20.04,
    20.96, 22.88, 24.52, 24.68, 24.76, 24.84, 24.92, 25.28, 27.08, 28.48,
    30.64,
]
KOMPAN_DURATION = 36.0


def _spans(cuts, duration):
    return [(s.start_sec, s.end_sec) for s in shots.shots_from_cuts(cuts, duration)]


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setattr(config, "MICRO_SHOT_SEC", 0.2)
    monkeypatch.setattr(config, "MICRO_RUN_MIN", 3)


def test_kompan_has_one_flash_run_of_four_shots():
    runs = shots.flash_runs(_spans(KOMPAN_CUTS, KOMPAN_DURATION))
    assert len(runs) == 1
    r = runs[0]
    assert (round(r.start_sec, 2), round(r.end_sec, 2), r.shots) == (24.52, 24.92, 4)


def test_segment_summary_numbers():
    s = shots.segment_summary(_spans(KOMPAN_CUTS, KOMPAN_DURATION), KOMPAN_DURATION)
    assert s["segment_count"] == 20                 # 23 shots, run of 4 counted once
    assert s["segments_per_minute"] == round(19 / 0.6, 2)
    assert s["micro_shot_ratio"] == round(4 / 23, 3)
    assert s["flash_runs"] == [[24.52, 24.92, 4]]


def test_two_short_shots_are_not_a_run():
    spans = [(0, 1), (1, 1.1), (1.1, 1.2), (1.2, 3)]
    assert shots.flash_runs(spans) == []
    assert shots.segment_count(spans) == 4


def test_a_run_that_ends_the_clip_is_closed():
    spans = [(0, 2)] + [(2 + 0.07 * i, 2 + 0.07 * (i + 1)) for i in range(5)]
    runs = shots.flash_runs(spans)
    assert len(runs) == 1 and runs[0].shots == 5
    assert shots.segment_count(spans) == 2


def test_a_strobe_reel_collapses_but_its_longer_shots_still_count():
    # DU0c4QzCBvM's pattern: six 2-frame shots, then one 0.2s shot, repeated.
    spans, t = [], 0.0
    for _ in range(15):
        for _ in range(6):
            spans.append((t, t + 0.067)); t += 0.067
        spans.append((t, t + 0.21)); t += 0.21
    assert len(spans) == 105
    assert shots.segment_count(spans) == 30          # each run + each 0.2s shot


def test_no_table_no_fields():
    assert shots.segment_summary([], 10.0) == {}


# --- keyframe cap grows by segments ----------------------------------------

def _stub_ffmpeg(monkeypatch, cuts, duration):
    class _CutsPopen:
        def __init__(self, cmd, **kw):
            self.stderr = io.StringIO(
                "".join("n:%d pts_time:%g\n" % (i, t) for i, t in enumerate(cuts)))
            self.returncode = None

        def poll(self):
            return self.returncode

        def kill(self):
            pass

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    def _fake_run(cmd, **kw):
        open(cmd[-1], "wb").close()
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(keyframe.subprocess, "Popen", _CutsPopen)
    monkeypatch.setattr(keyframe.subprocess, "run", _fake_run)
    monkeypatch.setattr(keyframe, "_get_duration", lambda p: duration)
    monkeypatch.setattr(config, "KEYFRAME_DEDUPE", False)
    monkeypatch.setattr(config, "KEYFRAME_MAX", 12)
    monkeypatch.setattr(config, "KEYFRAME_SHOT_CAP", 30)


def test_stop_motion_reel_no_longer_spends_the_whole_cap(tmp_path, monkeypatch):
    cuts = [round(0.1 * i, 2) for i in range(1, 140)]   # 140 3-frame shots, 14s
    _stub_ffmpeg(monkeypatch, cuts, 14.0)
    frames = keyframe.extract_keyframes("x.mp4", str(tmp_path), "vid", strategy="scene")
    # One flash run -> one segment -> the flat cap, not KEYFRAME_SHOT_CAP.
    assert len(frames) == config.KEYFRAME_MAX


def test_clip_without_flash_runs_picks_what_it_did_before(tmp_path, monkeypatch):
    cuts = [0.5 * i for i in range(1, 40)]               # 0.5s shots: none micro
    _stub_ffmpeg(monkeypatch, cuts, 20.0)
    frames = keyframe.extract_keyframes("x.mp4", str(tmp_path), "vid", strategy="scene")
    assert len(frames) == config.KEYFRAME_SHOT_CAP


# --- merge and score are told ----------------------------------------------

@pytest.fixture
def conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    db.init_db(c)
    yield c
    c.close()
    os.unlink(path)


def _kompan(conn):
    vid = db.upsert_video(
        conn, platform="youtube", platform_id="kompan",
        url="https://youtube.com/watch?v=kompan", title="T",
        duration_sec=KOMPAN_DURATION)
    db.save_shot_metrics(conn, vid, shot_count=23, cuts_per_minute=36.67,
                         avg_shot_sec=1.57)
    db.save_shots(conn, vid, shots.shots_from_cuts(KOMPAN_CUTS, KOMPAN_DURATION))
    return vid


def test_merge_prompt_names_the_flash_run_and_blob_carries_it(conn):
    vid = _kompan(conn)
    llm = MagicMock()
    llm.complete.return_value = json.dumps({"summary": "s", "topics": []})
    with patch("reel_scout.analyze.merger.get_llm", return_value=llm):
        merger.merge_analysis(conn, vid)

    prompt = llm.complete.call_args[0][0]
    assert "24.5-24.9s: 4 shots" in prompt
    measured = json.loads(db.get_analysis(conn, vid)["full_json"])["measured"]
    assert measured["segment_count"] == 20
    assert measured["flash_runs"] == [[24.52, 24.92, 4]]
    assert measured["cuts_per_minute"] == 36.67     # the raw rate is untouched


def test_backfill_adds_segment_fields_to_an_existing_analysis(conn):
    vid = _kompan(conn)
    db.save_analysis(
        conn, vid, summary="s", topics_json="[]", hooks_json="{}",
        style_json="{}", engagement_signals_json="{}",
        full_json=json.dumps({"summary": "s", "measured": {"cuts_per_minute": 36.67}}),
    )
    merger.backfill_measured(conn, vid)
    measured = json.loads(db.get_analysis(conn, vid)["full_json"])["measured"]
    assert measured["segment_count"] == 20


def test_score_prompt_carries_segments_and_runs():
    block = scorer._measured_block(json.dumps({"measured": {
        "cuts_per_minute": 36.67, "segments_per_minute": 31.67,
        "micro_shot_ratio": 0.174, "flash_runs": [[24.52, 24.92, 4]]}}))
    assert "segments_per_minute: 31.67" in block
    assert "[[24.52, 24.92, 4]]" in block


def test_unmeasured_clip_merge_prompt_says_so(conn):
    vid = db.upsert_video(conn, platform="youtube", platform_id="none",
                          url="https://youtube.com/watch?v=none", title="T",
                          duration_sec=10.0)
    llm = MagicMock()
    llm.complete.return_value = json.dumps({"summary": "s", "topics": []})
    with patch("reel_scout.analyze.merger.get_llm", return_value=llm):
        merger.merge_analysis(conn, vid)
    assert "## Cut Rhythm (measured)\n(not measured)" in llm.complete.call_args[0][0]
