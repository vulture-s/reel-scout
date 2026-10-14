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


# --- output language: always zh-TW + bilingual gloss (2026-10-14 Hevin 拍板，取代 #208 的「跟隨 angle」) ---

_EN_ANALYSIS = {"summary": "a snappy coffee tutorial", "content_structure": "hook-body-cta",
                "style": {"editing": "fast jump cuts, high dynamic range grade"}}
_ZH_ANALYSIS = {"summary": "快節奏的咖啡教學", "content_structure": "開場鉤子-主體-行動呼籲",
                "style": {"editing": "快速跳切、高動態範圍調色"}}

_ANGLES = {
    "zh_angle": "拆結構套回自己的分鏡",
    "en_angle": "for a tea shop instead",
    "no_angle": "",
}
_ANALYSES = {"zh_analysis": _ZH_ANALYSIS, "en_analysis": _EN_ANALYSIS}


def _prompt_for(angle, analysis=None):
    conn, path = _temp_db()
    try:
        vid = db.upsert_video(
            conn, platform="youtube", platform_id="lang",
            url="https://youtube.com/shorts/lang", title="Proven", duration_sec=25.0,
        )
        full = analysis if analysis is not None else _EN_ANALYSIS
        db.save_analysis(
            conn, vid, summary=full["summary"], topics_json="[]",
            hooks_json="{}", style_json="{}", engagement_signals_json="{}",
            full_json=json.dumps(full, ensure_ascii=False),
        )
        mock_llm = MagicMock()
        mock_llm.complete.return_value = json.dumps({"titles": ["x"]})
        with patch("reel_scout.inspire.get_llm", return_value=mock_llm):
            inspire.generate_inspiration(conn, vid[:8], angle=angle)
        return mock_llm.complete.call_args[0][0]
    finally:
        conn.close()
        os.unlink(path)


def _assert_zh_tw_bilingual_rule(prompt):
    assert "## Output language" in prompt
    # Traditional Chinese, Taiwan
    assert "Traditional Chinese" in prompt and "zh-TW" in prompt
    # Simplified explicitly forbidden
    assert "NEVER use Simplified Chinese" in prompt
    # bilingual gloss for English domain terms, with the canonical example
    assert "Bilingual gloss" in prompt
    assert "動態範圍（Dynamic Range）" in prompt
    # gloss is scoped to terms — whole titles must not get an English translation tacked on
    assert "never append an English translation to a whole title" in prompt
    # brands / model numbers stay verbatim
    assert "brand names, product model numbers" in prompt
    # the rule must not be conditional on the angle's language any more
    assert "same language as the requested angle" not in prompt


@pytest.mark.parametrize("analysis_key", sorted(_ANALYSES))
@pytest.mark.parametrize("angle_key", sorted(_ANGLES))
def test_every_angle_and_analysis_language_gets_zh_tw_bilingual_rule(angle_key, analysis_key):
    """中文 angle／英文 angle／無 angle × 中文底片／英文底片 → 全部都釘繁中＋雙語對照。"""
    prompt = _prompt_for(_ANGLES[angle_key], _ANALYSES[analysis_key])
    _assert_zh_tw_bilingual_rule(prompt)
    # the analysis and the angle still reach the prompt untouched
    assert _ANALYSES[analysis_key]["summary"] in prompt
    if _ANGLES[angle_key]:
        assert _ANGLES[angle_key] in prompt


def test_japanese_angle_also_gets_zh_tw_rule():
    # #208 exempted kana angles; under the 2026-10-14 rule output is zh-TW regardless
    _assert_zh_tw_bilingual_rule(_prompt_for("コーヒーの代わりに抹茶で"))


def test_language_rule_appears_exactly_once():
    prompt = _prompt_for("for a tea shop instead", _ZH_ANALYSIS)
    assert prompt.count("## Output language") == 1


def test_language_rule_is_angle_independent():
    assert inspire._language_rule("") == inspire._language_rule("拆結構") == inspire._language_rule("for tea")
