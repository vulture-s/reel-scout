"""Cross-video comparison (roadmap 3B)."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

from reel_scout import compare, db


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _seed_video(conn, platform_id, *, title, duration, full=None, score=None):
    vid = db.upsert_video(
        conn, platform="youtube", platform_id=platform_id,
        url="https://youtube.com/shorts/%s" % platform_id,
        title=title, duration_sec=duration,
    )
    if full is not None:
        db.save_analysis(
            conn, vid,
            summary=full.get("summary", ""),
            topics_json=json.dumps(full.get("topics", [])),
            hooks_json=json.dumps(full.get("hook", {})),
            style_json=json.dumps(full.get("style", {})),
            engagement_signals_json=json.dumps(full.get("engagement_signals", {})),
            full_json=json.dumps(full),
        )
    if score is not None:
        conn.execute(
            """INSERT INTO scores (video_id, hook_strength, visual_storytelling,
               pacing, structure, overall) VALUES (?,?,?,?,?,?)""",
            (vid, *score),
        )
        conn.commit()
    return vid


def test_build_comparison_pulls_analysis_and_score_fields():
    conn, path = _temp_db()
    try:
        vid = _seed_video(
            conn, "aaa", title="Great hook", duration=18.4,
            full={
                "content_type": "educational",
                "style": {"format": "talking_head", "pacing": "fast"},
                "hook": {"opening_type": "question", "cta_type": "visit"},
            },
            score=(8.5, 7.0, 9.0, 6.5, 7.75),
        )
        result = compare.build_comparison(conn, [vid])
        assert result["errors"] == []
        row = result["videos"][0]
        assert row["format"] == "talking_head"
        assert row["opening_type"] == "question"
        assert row["cta_type"] == "visit"
        assert row["content_type"] == "educational"
        assert row["hook_strength"] == 8.5
        assert row["overall"] == 7.75
        assert row["duration_sec"] == 18.4
    finally:
        conn.close()
        os.unlink(path)


def test_missing_analysis_leaves_fields_none_not_fabricated():
    conn, path = _temp_db()
    try:
        vid = _seed_video(conn, "bbb", title="Raw", duration=10.0)  # no analysis/score
        row = compare.build_comparison(conn, [vid])["videos"][0]
        assert row["platform"] == "youtube"
        assert row["duration_sec"] == 10.0
        assert row["format"] is None
        assert row["overall"] is None
        # Rendered as an em dash, never a made-up value.
        assert compare._fmt("overall", row["overall"]) == compare._MISSING
    finally:
        conn.close()
        os.unlink(path)


def test_resolve_ref_accepts_unique_prefix_and_flags_ambiguity():
    conn, path = _temp_db()
    try:
        vid = _seed_video(conn, "ccc", title="X", duration=5.0)
        # A short-enough unique prefix resolves to the full id.
        resolved, matches = compare.resolve_ref(conn, vid[:6])
        assert resolved == vid
        # A non-existent ref resolves to nothing.
        resolved2, matches2 = compare.resolve_ref(conn, "zzzzzz")
        assert resolved2 is None and matches2 == []
    finally:
        conn.close()
        os.unlink(path)


def test_unknown_ref_goes_to_errors_not_crash():
    conn, path = _temp_db()
    try:
        result = compare.build_comparison(conn, ["deadbeef"])
        assert result["videos"] == []
        assert any("not found" in e for e in result["errors"])
    finally:
        conn.close()
        os.unlink(path)


def test_format_table_renders_fields_and_errors():
    conn, path = _temp_db()
    try:
        vid = _seed_video(
            conn, "ddd", title="Tbl", duration=20.0,
            full={"style": {"format": "vlog", "pacing": "slow"},
                  "hook": {"opening_type": "visual", "cta_type": "follow"}},
        )
        comparison = compare.build_comparison(conn, [vid, "missing1"])
        out = compare.format_table(comparison)
        assert "Hook type" in out
        assert "visual" in out
        assert "vlog" in out
        assert "! Video not found: missing1" in out
    finally:
        conn.close()
        os.unlink(path)
