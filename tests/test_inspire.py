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


# --- (b) source-side Traditional conversion + real-names rule (2026-10-14) ---

_SIMPLIFIED_ANALYSIS = {
    "summary": "视频揭示了使用GEV和Sony FX3通关的案例，软件是DaVinci Resolve 18",
    "topics": ["AI模型", "游戏作弊"],
    "timeline": [{"timestamp": "0.1-37.3s", "event": "展示ASTRA和JEV在游戏中的互动"}],
    "hook": {"opening_type": "statement", "opening_text": "最近网上有很多酷炫案例", "cta_text": ""},
    "engagement_signals": {"spoken_language": "zh", "face_count": 0},
    "measured": {"cuts_per_minute": 11.36},
}


def _video_with_simplified_analysis(conn):
    vid = db.upsert_video(
        conn, platform="youtube", platform_id="simp",
        url="https://youtube.com/shorts/simp", title="Simplified", duration_sec=60.0,
    )
    raw = json.dumps(_SIMPLIFIED_ANALYSIS, ensure_ascii=False)
    db.save_analysis(
        conn, vid, summary=_SIMPLIFIED_ANALYSIS["summary"], topics_json="[]",
        hooks_json="{}", style_json="{}", engagement_signals_json="{}", full_json=raw,
    )
    return vid, raw


def _prompt_from_db(conn, vid, angle=""):
    mock_llm = MagicMock()
    mock_llm.complete.return_value = json.dumps({"titles": ["t"]})
    with patch("reel_scout.inspire.get_llm", return_value=mock_llm):
        inspire.generate_inspiration(conn, vid, angle=angle)
    return mock_llm.complete.call_args[0][0]


def _analysis_block(prompt):
    start = prompt.index("## Proven video analysis\n") + len("## Proven video analysis\n")
    end = prompt.index("\n\n## Requested angle")
    return json.loads(prompt[start:end])


def test_simplified_analysis_reaches_prompt_as_traditional(need_opencc):
    conn, path = _temp_db()
    try:
        vid, _raw = _video_with_simplified_analysis(conn)
        sent = _analysis_block(_prompt_from_db(conn, vid, angle="for a photography channel instead"))
        # values are Traditional (Taiwan phrasing: 视频 -> 影片, 软件 -> 軟體)
        assert sent["summary"].startswith("影片揭示了")
        assert "軟體" in sent["summary"] and "通關" in sent["summary"]
        assert sent["topics"] == ["AI模型", "遊戲作弊"]
        assert sent["timeline"][0]["event"] == "展示ASTRA和JEV在遊戲中的互動"
        assert sent["hook"]["opening_text"] == "最近網上有很多酷炫案例"
        # no Simplified form survives anywhere in the analysis block
        blob = json.dumps(sent, ensure_ascii=False)
        for simp in ("视频", "软件", "游戏", "网上", "互动", "关"):
            assert simp not in blob
    finally:
        conn.close()
        os.unlink(path)


def test_conversion_keeps_keys_latin_and_non_strings():
    conn, path = _temp_db()
    try:
        vid, _raw = _video_with_simplified_analysis(conn)
        sent = _analysis_block(_prompt_from_db(conn, vid))
        # keys untouched, structure identical
        assert sent.keys() == _SIMPLIFIED_ANALYSIS.keys()
        assert sent["hook"].keys() == _SIMPLIFIED_ANALYSIS["hook"].keys()
        # brands / model numbers / Latin tokens unchanged
        for latin in ("GEV", "Sony FX3", "DaVinci Resolve 18", "ASTRA", "JEV"):
            assert latin in sent["summary"] + sent["timeline"][0]["event"]
        assert sent["engagement_signals"] == {"spoken_language": "zh", "face_count": 0}
        assert sent["measured"] == {"cuts_per_minute": 11.36}
        assert sent["timeline"][0]["timestamp"] == "0.1-37.3s"
        assert sent["hook"]["cta_text"] == ""
    finally:
        conn.close()
        os.unlink(path)


def test_conversion_does_not_touch_the_db_row():
    conn, path = _temp_db()
    try:
        vid, raw = _video_with_simplified_analysis(conn)
        _prompt_from_db(conn, vid)
        assert db.get_analysis(conn, vid)["full_json"] == raw
        assert "视频" in db.get_analysis(conn, vid)["full_json"]
    finally:
        conn.close()
        os.unlink(path)


def test_model_output_is_not_converted():
    # The fix is at the source only: Simplified in the model's answer is
    # reported as-is, never rewritten after the fact.
    conn, path = _temp_db()
    try:
        vid, _raw = _video_with_simplified_analysis(conn)
        mock_llm = MagicMock()
        mock_llm.complete.return_value = json.dumps({"titles": ["视频标题"], "rationale": "这个结构"})
        with patch("reel_scout.inspire.get_llm", return_value=mock_llm):
            data = inspire.generate_inspiration(conn, vid)
        assert data["titles"] == ["视频标题"]
        assert data["rationale"] == "这个结构"
    finally:
        conn.close()
        os.unlink(path)


def test_non_json_analysis_is_still_converted(need_opencc):
    out = inspire._analysis_for_prompt("not json: 视频软件 Sony FX3")
    assert out == "not json: 影片軟體 Sony FX3"


def test_missing_opencc_warns_and_passes_through(no_opencc, monkeypatch, capsys):
    monkeypatch.setattr(inspire.config, "ZH_HOTWORDS", "")
    raw = json.dumps({"summary": "视频"}, ensure_ascii=False)
    assert inspire._analysis_for_prompt(raw) == raw
    err = capsys.readouterr().err
    assert "opencc not installed" in err
    # the warning tells you how to fix it
    assert 'pip install "reel-scout[zh]"' in err


def test_prompt_requires_real_names_kept():
    conn, path = _temp_db()
    try:
        vid = _video_with_analysis(conn)
        prompt = _prompt_from_db(conn, vid)
        assert "## Real names stay real (mandatory)" in prompt
        assert prompt.count("## Real names stay real") == 1
        for needle in ("tool, app", "brand", "product model", "person's name", "channel name",
                       "exactly as it appears", "do not rename", "invent a substitute",
                       "transliterate", "never swapping out a real entity"):
            assert needle in prompt, needle
        # rule sits before the output format, i.e. it is part of the instructions
        assert prompt.index("## Real names stay real") < prompt.index("## Output Format")
    finally:
        conn.close()
        os.unlink(path)
