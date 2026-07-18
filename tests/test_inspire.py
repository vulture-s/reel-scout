"""Content inspiration generator (roadmap 4B)."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from reel_scout import db, inspire


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _video_with_analysis(conn):
    vid = db.upsert_video(
        conn, platform="youtube", platform_id="insp",
        url="https://youtube.com/shorts/insp", title="Proven", duration_sec=25.0,
    )
    db.save_analysis(
        conn, vid, summary="a snappy tutorial", topics_json='["coffee"]',
        hooks_json="{}", style_json="{}", engagement_signals_json="{}",
        full_json=json.dumps({"summary": "a snappy tutorial", "content_structure": "hook-body-cta"}),
    )
    return vid


def test_generate_inspiration_parses():
    conn, path = _temp_db()
    try:
        vid = _video_with_analysis(conn)
        mock_llm = MagicMock()
        mock_llm.complete.return_value = json.dumps({
            "titles": ["T1", "T2", "T3"],
            "hook_script": "Watch this in 3 seconds",
            "structure_outline": ["beat 1", "beat 2"],
            "recommended_length_sec": 28,
            "rationale": "reuses the proven hook-body-cta",
        })
        with patch("reel_scout.inspire.get_llm", return_value=mock_llm):
            data = inspire.generate_inspiration(conn, vid[:8], angle="for tea instead")
        assert data["based_on"] == vid
        assert data["angle"] == "for tea instead"
        assert data["titles"] == ["T1", "T2", "T3"]
        # the angle reached the prompt
        prompt = mock_llm.complete.call_args[0][0]
        assert "for tea instead" in prompt
    finally:
        conn.close()
        os.unlink(path)


def test_generate_inspiration_no_analysis():
    conn, path = _temp_db()
    try:
        vid = db.upsert_video(
            conn, platform="youtube", platform_id="noanalysis_insp",
            url="https://youtube.com/shorts/noanalysis_insp",
        )
        with pytest.raises(ValueError, match="No analysis"):
            inspire.generate_inspiration(conn, vid)
    finally:
        conn.close()
        os.unlink(path)


def test_generate_inspiration_unknown_ref():
    conn, path = _temp_db()
    try:
        with pytest.raises(ValueError, match="No video found"):
            inspire.generate_inspiration(conn, "deadbeefdeadbeef")
    finally:
        conn.close()
        os.unlink(path)


def test_format_inspiration_renders():
    out = inspire.format_inspiration({
        "based_on": "abc", "angle": "x", "titles": ["A"],
        "hook_script": "H", "structure_outline": ["b1"],
        "recommended_length_sec": 30, "rationale": "r",
    })
    assert "Titles:" in out and "Hook:" in out and "Structure:" in out
