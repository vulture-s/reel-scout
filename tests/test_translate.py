"""Side-by-side translation of the free text (roadmap §7E)."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from unittest.mock import patch

from reel_scout import db, translate


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _clip(conn, pid="a"):
    vid = db.upsert_video(conn, "youtube", pid, "https://y/%s" % pid, title=pid)
    conn.execute("UPDATE videos SET status='analyzed' WHERE id=?", (vid,))
    conn.commit()
    return vid


def test_text_that_is_already_chinese_is_not_translated():
    # Running a translator over it produces a worse version of what was there,
    # and a quarter of the real corpus is already Chinese.
    assert translate.needs_translation("這是一段中文描述，講的是鏡頭裡有什麼") is False
    assert translate.needs_translation("a close-up of a hand") is True
    assert translate.needs_translation("") is False
    assert translate.needs_translation(None) is False


def test_mixed_script_still_counts_as_chinese_past_the_ratio():
    assert translate.cjk_ratio("完全中文") == 1.0
    assert translate.needs_translation("Claude 教學：完整設定一次搞懂") is False


def test_units_are_collected_per_addressable_piece():
    conn, path = _temp_db()
    try:
        vid = _clip(conn)
        conn.execute("INSERT INTO keyframes (id, video_id, frame_index, "
                     "timestamp_sec, file_path, strategy) VALUES (1,?,0,1.0,'/x','scene')",
                     (vid,))
        conn.execute("INSERT INTO vision_descriptions (keyframe_id, description) "
                     "VALUES (1, 'a close-up of a hand')")
        db.save_transcript(conn, vid, "en", "hello there",
                           json.dumps([{"start": 0, "end": 1, "text": "hello there"},
                                       {"start": 1, "end": 2, "text": "這句是中文"}]),
                           "test", 2.0)
        db.save_analysis(conn, vid, summary="A clip about hands", topics_json="[]",
                         hooks_json="{}", style_json="{}", engagement_signals_json="{}",
                         full_json=json.dumps({"timeline": [{"event": "a hand appears"}]}))
        conn.commit()
        units = translate.collect_units(conn, vid)
        kinds = sorted({k for k, _, _ in units})
        assert kinds == ["description", "summary", "timeline", "transcript_segment"]
        # The Chinese segment is not a unit.
        segs = [u for u in units if u[0] == "transcript_segment"]
        assert len(segs) == 1 and segs[0][1] == "0"
    finally:
        conn.close(); os.unlink(path)


def test_a_translation_records_the_engine_and_model():
    conn, path = _temp_db()
    try:
        vid = _clip(conn)
        db.save_translation(conn, vid, "summary", "", "zh", "hello", "你好",
                            "ollama", "qwen2.5:14b")
        row = db.get_translations(conn, vid)[0]
        assert row["engine"] == "ollama" and row["model"] == "qwen2.5:14b"
        assert row["text"] == "你好"
    finally:
        conn.close(); os.unlink(path)


def test_a_translation_knows_which_source_it_was_made_from():
    # 🔴 The load-bearing part. Descriptions get re-run and transcripts re-cut;
    # a translation without a fingerprint goes on being displayed beside text it
    # no longer matches, looking exactly like a current one.
    conn, path = _temp_db()
    try:
        vid = _clip(conn)
        db.save_translation(conn, vid, "summary", "", "zh", "hello", "你好",
                            "ollama", "m")
        row = db.get_translations(conn, vid)[0]
        assert translate.is_stale(row, "hello") is False
        assert translate.is_stale(row, "hello, again") is True
    finally:
        conn.close(); os.unlink(path)


def test_stale_translations_are_refreshed_by_default():
    conn, path = _temp_db()
    try:
        vid = _clip(conn)
        db.save_analysis(conn, vid, summary="new english text", topics_json="[]",
                         hooks_json="{}", style_json="{}",
                         engagement_signals_json="{}", full_json="{}")
        db.save_translation(conn, vid, "summary", "", "zh", "OLD english text",
                            "舊的翻譯", "ollama", "m")
        with patch.object(translate, "translate_text", return_value="新的翻譯"):
            tally = translate.translate_video(conn, vid, "m")
        assert tally["refreshed"] == 1 and tally["translated"] == 0
        assert db.get_translations(conn, vid)[0]["text"] == "新的翻譯"
    finally:
        conn.close(); os.unlink(path)


def test_keep_stale_leaves_it_alone_but_still_counts_it():
    conn, path = _temp_db()
    try:
        vid = _clip(conn)
        db.save_analysis(conn, vid, summary="new english text", topics_json="[]",
                         hooks_json="{}", style_json="{}",
                         engagement_signals_json="{}", full_json="{}")
        db.save_translation(conn, vid, "summary", "", "zh", "OLD", "舊", "ollama", "m")
        with patch.object(translate, "translate_text") as t:
            tally = translate.translate_video(conn, vid, "m", refresh_stale=False)
        t.assert_not_called()
        assert tally["skipped_existing"] == 1
        assert db.get_translations(conn, vid)[0]["text"] == "舊"
    finally:
        conn.close(); os.unlink(path)


def test_a_current_translation_is_not_redone():
    conn, path = _temp_db()
    try:
        vid = _clip(conn)
        db.save_analysis(conn, vid, summary="same text", topics_json="[]",
                         hooks_json="{}", style_json="{}",
                         engagement_signals_json="{}", full_json="{}")
        db.save_translation(conn, vid, "summary", "", "zh", "same text", "同樣",
                            "ollama", "m")
        with patch.object(translate, "translate_text") as t:
            tally = translate.translate_video(conn, vid, "m")
        t.assert_not_called()
        assert tally["skipped_existing"] == 1
    finally:
        conn.close(); os.unlink(path)


def test_a_failed_translation_stores_nothing():
    # A placeholder beside the original would read as a translation.
    conn, path = _temp_db()
    try:
        vid = _clip(conn)
        db.save_analysis(conn, vid, summary="english", topics_json="[]",
                         hooks_json="{}", style_json="{}",
                         engagement_signals_json="{}", full_json="{}")
        with patch.object(translate, "translate_text", return_value=None):
            tally = translate.translate_video(conn, vid, "m")
        assert tally["failed"] == 1 and db.get_translations(conn, vid) == []
    finally:
        conn.close(); os.unlink(path)


def test_kinds_filter_and_limit():
    conn, path = _temp_db()
    try:
        vid = _clip(conn)
        db.save_analysis(conn, vid, summary="english summary", topics_json="[]",
                         hooks_json="{}", style_json="{}", engagement_signals_json="{}",
                         full_json=json.dumps({"timeline": [{"event": "one"},
                                                            {"event": "two"}]}))
        with patch.object(translate, "translate_text", return_value="X"):
            t1 = translate.translate_video(conn, vid, "m", kinds=["summary"])
        assert t1["candidates"] == 1 and t1["translated"] == 1
        with patch.object(translate, "translate_text", return_value="X"):
            t2 = translate.translate_video(conn, vid, "m", kinds=["timeline"], limit=1)
        assert t2["candidates"] == 2 and t2["translated"] == 1
    finally:
        conn.close(); os.unlink(path)


def test_the_prompt_asks_for_taiwan_wording_not_just_traditional_characters():
    # The first run returned 「該視頻」 — Traditional characters, mainland
    # vocabulary. Both are zh-Hant; only one is the house style.
    assert "Taiwan" in translate.PROMPT
    # The contrast pairs, not just the words: asking for zh-TW alone still
    # returns mainland vocabulary, so the prompt has to name what to avoid.
    assert "Taiwanese vocabulary" in translate.PROMPT
    for pair in ("影片 not 視頻", "品質 not 質量", "網路 not 網絡"):
        assert pair in translate.PROMPT, pair


def _transcript(conn, vid, texts):
    segs = [{"start": float(i), "end": float(i + 1), "text": t} for i, t in enumerate(texts)]
    db.save_transcript(conn, vid, language="en", text_full=" ".join(texts),
                       segments_json=json.dumps(segs), whisper_model="native-subtitles",
                       duration_sec=float(len(texts)))


def test_translations_for_segments_that_no_longer_exist_are_pruned():
    """Re-cut into fewer segments: the tail translations address nothing."""
    conn, path = _temp_db()
    try:
        vid = _clip(conn)
        _transcript(conn, vid, ["one line", "two line"])
        for i, t in enumerate(["one line", "two line", "gone line", "gone too"]):
            db.save_translation(conn, vid, "transcript_segment", str(i), "zh", t,
                                "譯%d" % i, "ollama", "m")
        with patch.object(translate, "translate_text") as tr:
            tally = translate.translate_video(conn, vid, "m")
        tr.assert_not_called()
        assert tally["pruned"] == 2
        refs = sorted(r["ref"] for r in db.get_translations(conn, vid))
        assert refs == ["0", "1"]
    finally:
        conn.close(); os.unlink(path)


def test_keep_stale_keeps_orphans_too():
    conn, path = _temp_db()
    try:
        vid = _clip(conn)
        _transcript(conn, vid, ["one line"])
        db.save_translation(conn, vid, "transcript_segment", "5", "zh", "gone",
                            "舊", "ollama", "m")
        tally = translate.translate_video(conn, vid, "m", refresh_stale=False)
        assert tally["pruned"] == 0
        assert len(db.get_translations(conn, vid)) == 1
    finally:
        conn.close(); os.unlink(path)


def test_kinds_filter_scopes_the_pruning():
    conn, path = _temp_db()
    try:
        vid = _clip(conn)
        _transcript(conn, vid, ["one line"])
        db.save_translation(conn, vid, "transcript_segment", "5", "zh", "gone",
                            "舊", "ollama", "m")
        with patch.object(translate, "translate_text", return_value="譯"):
            tally = translate.translate_video(conn, vid, "m", kinds=["summary"])
        assert tally["pruned"] == 0
        assert len(db.get_translations(conn, vid, kind="transcript_segment")) == 1
    finally:
        conn.close(); os.unlink(path)


def test_the_decoded_hook_and_cta_lines_are_translatable():
    # They are free text in the 解構分析 block and were never collected, so
    # they stayed English in the Chinese UI on every clip.
    conn, path = _temp_db()
    try:
        vid = _clip(conn)
        db.save_analysis(conn, vid, summary="", topics_json="[]", hooks_json="{}",
                         style_json="{}", engagement_signals_json="{}",
                         full_json=json.dumps({"hook": {
                             "opening_text": "A street scene with parked motorcycles",
                             "cta_text": "Follow for more", "opening_type": "visual"}}))
        conn.commit()
        units = {(k, r): t for k, r, t in translate.collect_units(conn, vid)}
        assert units[("opening_text", "")] == "A street scene with parked motorcycles"
        assert units[("cta_text", "")] == "Follow for more"
    finally:
        conn.close(); os.unlink(path)
