"""Performance tracking + corpus comparison (roadmap 4D)."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from reel_scout import db, track
from reel_scout.scorer import VideoScore


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _add_scored(conn, pid, structure, pacing, overall, cpm=None):
    vid = db.upsert_video(
        conn, platform="youtube", platform_id=pid,
        url="https://youtube.com/shorts/" + pid,
    )
    db.save_analysis(
        conn, vid, summary="s", topics_json="[]", hooks_json="{}",
        style_json=json.dumps({"pacing": pacing}), engagement_signals_json="{}",
        full_json=json.dumps({"content_structure": structure, "style": {"pacing": pacing}}),
    )
    db.save_score(conn, vid, VideoScore(overall=overall))
    if cpm is not None:
        db.save_shot_metrics(conn, vid, cuts_per_minute=cpm)
    return vid


def test_performance_table_exists_and_migrates():
    # v8 DB (no performance) migrates up to current and gains the table.
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    conn.execute("DROP TABLE IF EXISTS performance")
    conn.execute("UPDATE schema_version SET version = 8")
    conn.commit()
    db.init_db(conn)
    assert conn.execute(
        "SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "performance" in tables
    conn.close()
    os.unlink(path)


def test_record_and_compare_to_corpus():
    conn, path = _temp_db()
    try:
        mine = _add_scored(conn, "mine", "listicle", "slow", 5.0, cpm=5.0)
        _add_scored(conn, "c1", "hook-body-cta", "fast", 8.0, cpm=15.0)
        _add_scored(conn, "c2", "hook-body-cta", "fast", 9.0, cpm=17.0)

        vid = track.record_performance(conn, mine, views=1000, likes=50, notes="my first")
        assert vid == mine
        perf = db.get_performance(conn, mine)
        assert perf["views"] == 1000 and perf["notes"] == "my first"

        cmp = track.compare_to_corpus(conn, mine)
        assert cmp["corpus"]["n"] == 2
        assert cmp["corpus"]["top_structure"] == "hook-body-cta"
        joined = " ".join(cmp["suggestions"])
        assert "restructuring" in joined
        assert "cut faster" in joined
    finally:
        conn.close()
        os.unlink(path)


def test_compare_empty_corpus():
    conn, path = _temp_db()
    try:
        mine = _add_scored(conn, "solo", "listicle", "slow", 5.0)
        cmp = track.compare_to_corpus(conn, mine)
        assert cmp["corpus"]["n"] == 0
        assert "No high-scoring corpus" in cmp["suggestions"][0]
    finally:
        conn.close()
        os.unlink(path)


def test_partial_performance_update_preserves():
    """A later track call that sets only some fields must keep the earlier ones
    (COALESCE upsert), not wipe them (INSERT OR REPLACE would)."""
    conn, path = _temp_db()
    try:
        vid = _add_scored(conn, "pp", "listicle", "slow", 5.0)
        db.save_performance(conn, vid, views=1000)
        db.save_performance(conn, vid, likes=50)  # only likes this call
        perf = db.get_performance(conn, vid)
        assert perf["views"] == 1000  # preserved
        assert perf["likes"] == 50
    finally:
        conn.close()
        os.unlink(path)


def test_resolve_my_video_by_url_and_prefix_and_missing():
    conn, path = _temp_db()
    try:
        vid = _add_scored(conn, "res", "listicle", "slow", 5.0)
        # by URL
        assert track.resolve_my_video(conn, "https://youtube.com/shorts/res") == vid
        # by id prefix
        assert track.resolve_my_video(conn, vid[:8]) == vid
        # missing
        with pytest.raises(ValueError, match="No video found"):
            track.resolve_my_video(conn, "ffffffffffffffff")
    finally:
        conn.close()
        os.unlink(path)
