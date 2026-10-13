"""Coverage report: percentage *and* max gap, for transcripts and keyframes."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from types import SimpleNamespace

from reel_scout import coverage, db


def test_max_gap_is_in_the_middle_even_when_coverage_looks_fine():
    # 2026-10-02 shape: reach looks healthy, the hole is mid-clip.
    r = coverage.span_coverage([(0, 10), (70, 100)], 100)
    assert r["covered_pct"] == 40.0
    assert r["max_gap_sec"] == 60.0
    assert r["max_gap_at"] == 10.0


def test_head_gap_counts():
    r = coverage.span_coverage([(25, 30), (31, 40)], 40)
    assert r["max_gap_sec"] == 25.0 and r["max_gap_at"] == 0.0


def test_tail_gap_counts():
    r = coverage.span_coverage([(0, 5), (6, 10)], 60)
    assert r["max_gap_sec"] == 50.0 and r["max_gap_at"] == 10.0


def test_overlapping_and_unsorted_segments_merge():
    r = coverage.span_coverage([(5, 9), (0, 6), (8, 10)], 10)
    assert r["covered_pct"] == 100.0 and r["max_gap_sec"] == 0.0


def test_no_segments_means_the_whole_clip_is_one_gap():
    r = coverage.span_coverage([], 42)
    assert r == {"covered_pct": 0.0, "max_gap_sec": 42.0, "max_gap_at": 0.0}


def test_unknown_duration_is_unmeasured_not_zero():
    for d in (None, 0, -1):
        r = coverage.span_coverage([(0, 1)], d)
        assert r == {"covered_pct": None, "max_gap_sec": None, "max_gap_at": None}


def test_segments_past_the_end_are_clipped():
    r = coverage.span_coverage([(0, 5), (8, 99)], 10)
    assert r["covered_pct"] == 70.0 and r["max_gap_sec"] == 3.0


def test_keyframes_report_reach_and_gap():
    r = coverage.point_coverage([0.0, 2.0, 4.0, 69.0], 100)
    assert r["frames"] == 4
    assert r["reach_pct"] == 69.0
    assert r["max_gap_sec"] == 65.0 and r["max_gap_at"] == 4.0


def _db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def test_compute_reads_both_layers_and_sorts_worst_first():
    conn, path = _db()
    try:
        a = db.upsert_video(conn, platform="youtube", platform_id="a",
                            url="https://y/a", uploader="Chan", duration_sec=100)
        b = db.upsert_video(conn, platform="youtube", platform_id="b",
                            url="https://y/b", uploader="Chan", duration_sec=20)
        db.upsert_video(conn, platform="youtube", platform_id="c",
                        url="https://y/c", uploader="Chan", duration_sec=30)
        db.save_transcript(conn, a, "zh-TW", "x", json.dumps(
            [{"start": 0, "end": 10, "text": "x"}, {"start": 90, "end": 100, "text": "y"}]),
            "native-subtitles", 100)
        db.save_transcript(conn, b, "zh-TW", "x", json.dumps(
            [{"start": 0, "end": 19, "text": "x"}]), "native-subtitles", 20)
        db.save_keyframes(conn, b, [
            {"frame_index": i, "timestamp_sec": t, "file_path": "/k%d.jpg" % i,
             "strategy": "scene"} for i, t in enumerate((0.0, 5.0, 19.0))])
        rows = coverage.compute(conn)
        assert [r["video_id"] for r in rows] == [a, b]  # c has neither layer
        assert rows[0]["transcript"]["max_gap_sec"] == 80.0
        assert rows[0]["transcript"]["source"] == "native-subtitles"
        assert rows[0]["keyframes"] is None
        assert rows[1]["keyframes"]["max_gap_sec"] == 14.0
        text = coverage.format_rows(rows)
        assert "80.0s" in text and "14.0s" in text
    finally:
        conn.close()
        os.unlink(path)


def test_cli_coverage_json(temp_db, capsys):
    from reel_scout import cli
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    v = db.upsert_video(conn, platform="youtube", platform_id="z",
                        url="https://y/z", duration_sec=60)
    db.save_transcript(conn, v, "zh", "x", json.dumps(
        [{"start": 30, "end": 60, "text": "x"}]), "native-subtitles", 60)
    conn.close()
    cli._cmd_coverage(SimpleNamespace(channel=None, limit=0, json=True))
    out = json.loads(capsys.readouterr().out)
    assert out[0]["transcript"]["max_gap_sec"] == 30.0
