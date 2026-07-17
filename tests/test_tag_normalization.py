"""Normalized analysis tag columns + v4->v5 migration/backfill (roadmap 3C)."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

from reel_scout import db


_FULL = {
    "content_type": "educational",
    "hook": {"opening_type": "question", "cta_type": "visit"},
    "style": {"format": "talking_head", "pacing": "fast"},
    "engagement_signals": {"emotion": "enthusiastic"},
}


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _seed_video(conn, pid="abc"):
    return db.upsert_video(
        conn, platform="youtube", platform_id=pid,
        url="https://youtube.com/shorts/%s" % pid, title="t",
    )


def test_extract_tag_columns_pulls_from_nested_blobs():
    tags = db._extract_tag_columns(_FULL)
    assert tags == {
        "content_type": "educational",
        "opening_type": "question",
        "cta_type": "visit",
        "style_format": "talking_head",
        "style_pacing": "fast",
        "emotion": "enthusiastic",
    }


def test_extract_tag_columns_missing_blobs_are_none():
    tags = db._extract_tag_columns({})
    assert all(v is None for v in tags.values())


def test_fresh_install_has_tag_columns_at_v5():
    conn, path = _fresh_db()
    try:
        assert db.SCHEMA_VERSION == 5
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 5
        cols = {r[1] for r in conn.execute("PRAGMA table_info(analyses)")}
        for c in ("content_type", "opening_type", "cta_type",
                  "style_format", "style_pacing", "emotion"):
            assert c in cols
    finally:
        conn.close()
        os.unlink(path)


def test_save_analysis_populates_tag_columns():
    conn, path = _fresh_db()
    try:
        vid = _seed_video(conn)
        db.save_analysis(
            conn, vid, summary="s",
            topics_json="[]",
            hooks_json=json.dumps(_FULL["hook"]),
            style_json=json.dumps(_FULL["style"]),
            engagement_signals_json=json.dumps(_FULL["engagement_signals"]),
            full_json=json.dumps(_FULL),
        )
        row = db.get_analysis(conn, vid)
        assert row["content_type"] == "educational"
        assert row["opening_type"] == "question"
        assert row["cta_type"] == "visit"
        assert row["style_format"] == "talking_head"
        assert row["style_pacing"] == "fast"
        assert row["emotion"] == "enthusiastic"
    finally:
        conn.close()
        os.unlink(path)


def test_save_analysis_bad_full_json_leaves_columns_null():
    conn, path = _fresh_db()
    try:
        vid = _seed_video(conn)
        db.save_analysis(
            conn, vid, summary="s", topics_json="[]", hooks_json="{}",
            style_json="{}", engagement_signals_json="{}",
            full_json="not valid json",
        )
        row = db.get_analysis(conn, vid)
        assert row["content_type"] is None
        assert row["style_format"] is None
    finally:
        conn.close()
        os.unlink(path)


def test_v4_to_v5_migration_backfills_from_full_json():
    # Build a v4-shaped DB by hand (no tag columns), insert an analysis row with
    # only full_json, then run init_db to migrate → columns must be backfilled.
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
            INSERT INTO schema_version (version) VALUES (4);
            CREATE TABLE videos (id TEXT PRIMARY KEY, platform TEXT, platform_id TEXT,
                url TEXT, title TEXT, uploader TEXT, duration_sec REAL, upload_date TEXT,
                file_path TEXT, file_size_bytes INTEGER, status TEXT, error_message TEXT,
                created_at TEXT, updated_at TEXT);
            CREATE TABLE analyses (video_id TEXT PRIMARY KEY, summary TEXT,
                topics_json TEXT, hooks_json TEXT, style_json TEXT,
                engagement_signals_json TEXT, full_json TEXT, created_at TEXT);
        """)
        conn.execute("INSERT INTO videos (id, platform, platform_id, url) VALUES (?,?,?,?)",
                     ("vid1", "youtube", "abc", "https://x"))
        conn.execute(
            "INSERT INTO analyses (video_id, full_json) VALUES (?,?)",
            ("vid1", json.dumps(_FULL)),
        )
        conn.commit()

        db.init_db(conn)  # runs _migrate_v4_to_v5

        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 5
        row = db.get_analysis(conn, "vid1")
        assert row["content_type"] == "educational"
        assert row["cta_type"] == "visit"
        assert row["style_format"] == "talking_head"
        assert row["emotion"] == "enthusiastic"
    finally:
        conn.close()
        os.unlink(path)
