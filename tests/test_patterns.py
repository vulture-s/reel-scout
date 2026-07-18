"""Per-channel pattern analysis (roadmap 3B)."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

from reel_scout import db, patterns


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _add(conn, pid, uploader, dur, upload_date, structure, pacing, opening, cta, overall):
    vid = db.upsert_video(
        conn, platform="youtube", platform_id=pid,
        url="https://youtube.com/shorts/" + pid,
        uploader=uploader, duration_sec=dur, upload_date=upload_date,
    )
    full = {
        "content_structure": structure, "style": {"pacing": pacing, "format": "vlog"},
        "hook": {"opening_type": opening, "cta_type": cta},
    }
    db.save_analysis(
        conn, vid, summary="s", topics_json="[]",
        hooks_json=json.dumps(full["hook"]), style_json=json.dumps(full["style"]),
        engagement_signals_json="{}", full_json=json.dumps(full),
    )
    from reel_scout.scorer import VideoScore
    db.save_score(conn, vid, VideoScore(overall=overall, pacing=5.0))
    return vid


def test_compute_patterns_aggregates_channel():
    conn, path = _temp_db()
    try:
        _add(conn, "a1", "Cool Creator", 20.0, "20260101", "hook-body-cta", "fast", "question", "follow", 8.0)
        _add(conn, "a2", "Cool Creator", 40.0, "20260111", "listicle", "medium", "statement", "none", 4.0)
        _add(conn, "a3", "Cool Creator", 30.0, "20260121", "story-arc", "fast", "visual", "visit", 6.0)
        # A different channel that must not leak in.
        _add(conn, "b1", "Other Person", 99.0, "20260101", "raw-moment", "slow", "none", "none", 2.0)

        p = patterns.compute_patterns(conn, "Cool Creator")
        assert p["total_videos"] == 3
        assert p["analyzed_videos"] == 3
        assert p["avg_duration_sec"] == 30.0  # (20+40+30)/3
        assert p["distributions"]["opening_type"] == {"question": 1, "statement": 1, "visual": 1}
        # High/low split at median: 3 scored -> low=[4.0], high=[6.0, 8.0].
        hl = p["high_vs_low"]
        assert hl["scored"] == 3
        assert hl["high"]["n"] == 2
        assert hl["low"]["n"] == 1
        assert hl["high"]["avg_overall"] > hl["low"]["avg_overall"]
        # Cadence: 3 dated posts, 10-day gaps -> avg 10.0.
        assert p["cadence"]["dated_posts"] == 3
        assert p["cadence"]["avg_gap_days"] == 10.0
    finally:
        conn.close()
        os.unlink(path)


def test_compute_patterns_empty_channel():
    conn, path = _temp_db()
    try:
        p = patterns.compute_patterns(conn, "Nobody")
        assert p["total_videos"] == 0
        assert p["avg_duration_sec"] is None
        assert p["high_vs_low"]["scored"] == 0
        assert p["cadence"]["dated_posts"] == 0
        # format must not crash on an empty channel
        assert "Channel patterns" in patterns.format_patterns(p)
    finally:
        conn.close()
        os.unlink(path)


def test_format_patterns_renders():
    conn, path = _temp_db()
    try:
        _add(conn, "c1", "Chan", 15.0, "20260101", "hook-body-cta", "fast", "question", "follow", 7.0)
        _add(conn, "c2", "Chan", 25.0, "20260103", "listicle", "medium", "statement", "like", 5.0)
        out = patterns.format_patterns(patterns.compute_patterns(conn, "Chan"))
        assert "Channel patterns" in out
        assert "Cadence" in out
        assert "Avg duration" in out
    finally:
        conn.close()
        os.unlink(path)
