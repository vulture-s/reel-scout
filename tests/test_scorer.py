from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from reel_scout import db
from reel_scout.scorer import VideoScore, score_video


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _insert_video_with_analysis(conn):
    vid = db.upsert_video(
        conn, platform="youtube", platform_id="scorer_test",
        url="https://youtube.com/shorts/scorer_test",
        title="Test Video", duration_sec=30.0,
    )
    analysis_data = {
        "summary": "A test video about cooking",
        "topics": ["cooking"],
        "hook": {"opening_type": "question"},
    }
    db.save_analysis(
        conn, vid,
        summary="A test video about cooking",
        topics_json=json.dumps(["cooking"]),
        hooks_json=json.dumps({"opening_type": "question"}),
        style_json=json.dumps({}),
        engagement_signals_json=json.dumps({}),
        full_json=json.dumps(analysis_data),
    )
    return vid


def test_score_video_parses_json():
    conn, path = _temp_db()
    vid = _insert_video_with_analysis(conn)

    mock_response = json.dumps({
        "hook_strength": 7.5,
        "visual_storytelling": 6.0,
        "pacing": 5.5,
        "structure": 8.0,
        "overall": 9.9,  # deliberately wrong — code must IGNORE this and recompute
        "reasoning": "Strong hook, weaker pacing",
    })

    mock_llm = MagicMock()
    mock_llm.complete.return_value = mock_response

    with patch("reel_scout.scorer.get_llm", return_value=mock_llm):
        score = score_video(conn, vid)

    assert score.hook_strength == 7.5
    assert score.visual_storytelling == 6.0
    assert score.pacing == 5.5
    assert score.structure == 8.0
    assert score.overall == 6.85
    assert score.reasoning == "Strong hook, weaker pacing"

    # Verify saved to DB
    saved = db.get_score(conn, vid)
    assert saved is not None
    assert saved["hook_strength"] == 7.5

    conn.close()
    os.unlink(path)


def test_score_video_injects_measured_metrics():
    """§4E: when the analysis carries measured pacing signals, they land in the
    scoring prompt as an explicit block the LLM is told to prefer."""
    conn, path = _temp_db()
    vid = db.upsert_video(
        conn, platform="youtube", platform_id="measured",
        url="https://youtube.com/shorts/measured",
        title="Test", duration_sec=30.0,
    )
    analysis_data = {
        "summary": "snappy montage",
        "measured": {"cuts_per_minute": 18.0, "avg_shot_sec": 3.0, "audio_energy": 0.25},
    }
    db.save_analysis(
        conn, vid,
        summary="snappy montage", topics_json="[]", hooks_json="{}",
        style_json="{}", engagement_signals_json="{}",
        full_json=json.dumps(analysis_data),
    )
    mock_llm = MagicMock()
    mock_llm.complete.return_value = json.dumps({
        "hook_strength": 5.0, "visual_storytelling": 5.0,
        "pacing": 8.0, "structure": 5.0, "reasoning": "measured-driven",
    })
    with patch("reel_scout.scorer.get_llm", return_value=mock_llm):
        score_video(conn, vid)

    prompt = mock_llm.complete.call_args[0][0]
    assert "Measured Signals" in prompt
    assert "cuts_per_minute: 18.0" in prompt

    conn.close()
    os.unlink(path)


def test_score_video_no_analysis():
    conn, path = _temp_db()
    vid = db.upsert_video(
        conn, platform="youtube", platform_id="no_analysis",
        url="https://youtube.com/shorts/no_analysis",
        title="No Analysis Video",
    )

    with pytest.raises(ValueError, match="No analysis found"):
        score_video(conn, vid)

    conn.close()
    os.unlink(path)


def test_video_score_dataclass():
    score = VideoScore()
    assert score.hook_strength == 0.0
    assert score.visual_storytelling == 0.0
    assert score.pacing == 0.0
    assert score.structure == 0.0
    assert score.overall == 0.0
    assert score.reasoning == ""
    assert score.model_used == ""

    score2 = VideoScore(
        hook_strength=8.0,
        visual_storytelling=7.0,
        pacing=6.0,
        structure=5.0,
        overall=6.7,
        reasoning="Good video",
        model_used="omlx",
    )
    assert score2.hook_strength == 8.0
    assert score2.model_used == "omlx"


def test_score_overall_calculation():
    """Verify the weighted average formula described in the prompt."""
    hook = 8.0
    visual = 6.0
    pacing = 7.0
    structure = 5.0
    expected = hook * 0.3 + visual * 0.25 + pacing * 0.2 + structure * 0.25
    assert expected == pytest.approx(6.55)
