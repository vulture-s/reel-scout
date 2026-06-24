from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from reel_scout import db
from reel_scout.analyze.merger import merge_analysis, MUSIC_CONF_THRESHOLD


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _video(conn, pid="merger_test"):
    return db.upsert_video(
        conn, platform="youtube", platform_id=pid,
        url="https://youtube.com/shorts/%s" % pid,
        title="Test", duration_sec=30.0,
    )


# The mocked LLM deliberately returns the WRONG has_background_music so the tests
# prove the detector's measured value overrides the LLM guess.
_LLM_SAYS_NO_MUSIC = json.dumps({
    "summary": "x",
    "topics": [],
    "hook": {},
    "style": {"format": "talking_head", "has_background_music": False},
    "engagement_signals": {},
})


def _merge_with_mocked_llm(conn, vid, llm_output=_LLM_SAYS_NO_MUSIC):
    fake_llm = type("FakeLLM", (), {"complete": lambda self, *a, **k: llm_output})()
    with patch("reel_scout.analyze.merger.get_llm", return_value=fake_llm):
        merge_analysis(conn, vid)
    style = json.loads(db.get_analysis(conn, vid)["style_json"])
    return style


def test_music_label_above_threshold_forces_true():
    """PANNs measured Music >= threshold -> True, even though the LLM said False."""
    conn, path = _temp_db()
    try:
        vid = _video(conn)
        db.save_audio_events(conn, vid, [
            {"event_type": "speech", "label": "Speech",
             "start_sec": 0.0, "end_sec": 14.0, "confidence": 0.91},
            {"event_type": "music", "label": "Music",
             "start_sec": 14.0, "end_sec": 16.0, "confidence": 0.84},
        ])
        style = _merge_with_mocked_llm(conn, vid)
        assert style["has_background_music"] is True
    finally:
        conn.close()
        os.unlink(path)


def test_only_subthreshold_or_nonmusic_is_false():
    """Audio ran but no music label clears the threshold -> False."""
    conn, path = _temp_db()
    try:
        vid = _video(conn)
        db.save_audio_events(conn, vid, [
            {"event_type": "speech", "label": "Speech",
             "start_sec": 0.0, "end_sec": 20.0, "confidence": 0.95},
            # a music label but below threshold -> must not flip to True
            {"event_type": "music", "label": "Music",
             "start_sec": 20.0, "end_sec": 21.0, "confidence": MUSIC_CONF_THRESHOLD - 0.05},
        ])
        # LLM here says True; detector must override to False.
        llm_says_yes = json.dumps({"summary": "x", "style": {"has_background_music": True}})
        style = _merge_with_mocked_llm(conn, vid, llm_says_yes)
        assert style["has_background_music"] is False
    finally:
        conn.close()
        os.unlink(path)


def test_no_audio_events_is_none():
    """Audio skipped (default path) -> unknown (None), not a fabricated bool."""
    conn, path = _temp_db()
    try:
        vid = _video(conn)
        # no save_audio_events at all
        style = _merge_with_mocked_llm(conn, vid)  # LLM says False
        assert style["has_background_music"] is None
    finally:
        conn.close()
        os.unlink(path)
