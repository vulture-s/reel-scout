"""Content-structure classification + v5->v6 migration (roadmap 3C part 2)."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

from reel_scout import db
from reel_scout.analyze import merger


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def test_merge_prompt_declares_content_structure_enum():
    tmpl = merger._MERGE_PROMPT_TEMPLATE
    assert '"content_structure"' in tmpl
    for label in ("hook-body-cta", "problem-solution", "listicle",
                  "story-arc", "raw-moment"):
        assert label in tmpl


def test_extract_and_save_populate_content_structure():
    conn, path = _fresh_db()
    try:
        assert db.SCHEMA_VERSION == 6
        full = {"content_type": "educational", "content_structure": "listicle"}
        assert db._extract_tag_columns(full)["content_structure"] == "listicle"
        vid = db.upsert_video(conn, platform="youtube", platform_id="x",
                              url="https://y", title="t")
        db.save_analysis(conn, vid, summary="s", topics_json="[]", hooks_json="{}",
                         style_json="{}", engagement_signals_json="{}",
                         full_json=json.dumps(full))
        assert db.get_analysis(conn, vid)["content_structure"] == "listicle"
    finally:
        conn.close()
        os.unlink(path)


def test_v5_to_v6_migration_adds_and_backfills_content_structure():
    # v5-shaped analyses (has v5 tag columns, no content_structure).
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
            INSERT INTO schema_version (version) VALUES (5);
            CREATE TABLE videos (id TEXT PRIMARY KEY, platform TEXT, platform_id TEXT,
                url TEXT, status TEXT);
            CREATE TABLE analyses (video_id TEXT PRIMARY KEY, summary TEXT,
                topics_json TEXT, hooks_json TEXT, style_json TEXT,
                engagement_signals_json TEXT, full_json TEXT,
                content_type TEXT, opening_type TEXT, cta_type TEXT,
                style_format TEXT, style_pacing TEXT, emotion TEXT, created_at TEXT);
        """)
        conn.execute("INSERT INTO videos (id, platform, platform_id, url) VALUES (?,?,?,?)",
                     ("v1", "youtube", "a", "https://x"))
        conn.execute("INSERT INTO analyses (video_id, full_json) VALUES (?,?)",
                     ("v1", json.dumps({"content_structure": "story-arc"})))
        conn.commit()

        db.init_db(conn)  # runs v5->v6

        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 6
        cols = {r[1] for r in conn.execute("PRAGMA table_info(analyses)")}
        assert "content_structure" in cols
        assert db.get_analysis(conn, "v1")["content_structure"] == "story-arc"
    finally:
        conn.close()
        os.unlink(path)
