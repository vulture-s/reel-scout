"""§4E integration seam: merge_analysis folds measured shot metrics into the
saved analysis blob (full_json) so the scorer can read them."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

from reel_scout import db
from reel_scout.analyze import merger


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def test_merge_folds_measured_metrics_into_full_json():
    conn, path = _temp_db()
    try:
        vid = db.upsert_video(
            conn, platform="youtube", platform_id="merge_measured",
            url="https://youtube.com/shorts/merge_measured",
            title="T", duration_sec=30.0,
        )
        db.save_shot_metrics(
            conn, vid, shot_count=10, cuts_per_minute=18.0,
            avg_shot_sec=3.0, audio_bpm=120.0, audio_energy=0.25,
        )
        mock_llm = MagicMock()
        mock_llm.complete.return_value = json.dumps(
            {"summary": "s", "topics": [], "style": {"pacing": "fast"}}
        )
        with patch("reel_scout.analyze.merger.get_llm", return_value=mock_llm):
            merger.merge_analysis(conn, vid)

        full = json.loads(db.get_analysis(conn, vid)["full_json"])
        assert "measured" in full
        assert full["measured"]["cuts_per_minute"] == 18.0
        assert full["measured"]["audio_bpm"] == 120.0
    finally:
        conn.close()
        os.unlink(path)


def test_merge_without_metrics_omits_measured():
    conn, path = _temp_db()
    try:
        vid = db.upsert_video(
            conn, platform="youtube", platform_id="merge_none",
            url="https://youtube.com/shorts/merge_none", title="T", duration_sec=30.0,
        )
        mock_llm = MagicMock()
        mock_llm.complete.return_value = json.dumps({"summary": "s", "topics": []})
        with patch("reel_scout.analyze.merger.get_llm", return_value=mock_llm):
            merger.merge_analysis(conn, vid)
        full = json.loads(db.get_analysis(conn, vid)["full_json"])
        assert "measured" not in full
    finally:
        conn.close()
        os.unlink(path)
