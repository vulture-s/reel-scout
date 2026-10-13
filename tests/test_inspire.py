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


def test_generate_inspiration_non_json_fallback():
    """LLM prose containing braces that aren't valid JSON must degrade to raw,
    not crash the second json.loads in the fallback path."""
    conn, path = _temp_db()
    try:
        vid = _video_with_analysis(conn)
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "Sure — try {this hook} for it"
        with patch("reel_scout.inspire.get_llm", return_value=mock_llm):
            data = inspire.generate_inspiration(conn, vid)
        assert data["raw"] == "Sure — try {this hook} for it"
        assert data["based_on"] == vid
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


# --- output language follows the angle (2026-07-29: Chinese angle → English titles) ---

def _prompt_for(angle):
    conn, path = _temp_db()
    try:
        vid = _video_with_analysis(conn)
        mock_llm = MagicMock()
        mock_llm.complete.return_value = json.dumps({"titles": ["x"]})
        with patch("reel_scout.inspire.get_llm", return_value=mock_llm):
            inspire.generate_inspiration(conn, vid[:8], angle=angle)
        return mock_llm.complete.call_args[0][0]
    finally:
        conn.close()
        os.unlink(path)


def test_chinese_angle_pins_traditional_chinese_output():
    prompt = _prompt_for("拆結構套回自己的分鏡")
    assert "## Output language" in prompt
    assert "Traditional Chinese" in prompt and "zh-TW" in prompt
    assert "never English" in prompt


def test_english_angle_is_not_forced_into_chinese():
    prompt = _prompt_for("for tea instead")
    assert "## Output language" in prompt
    assert "same language as the requested angle" in prompt
    assert "Traditional Chinese" not in prompt


def test_japanese_angle_is_not_forced_into_chinese():
    # Han + kana = Japanese; must not get the zh-TW rule
    prompt = _prompt_for("コーヒーの代わりに抹茶で")
    assert "Traditional Chinese" not in prompt
    assert "same language as the requested angle" in prompt


def test_no_angle_adds_no_language_rule():
    prompt = _prompt_for("")
    assert "## Output language" not in prompt
    assert "Traditional Chinese" not in prompt
