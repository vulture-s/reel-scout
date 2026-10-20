"""Simplified transcripts are stored as Traditional at the source, original kept.

Hevin 2026-10-14: transcripts / subtitles used to be *detected* as mixed
(`db.scan_script_mix`) and never converted. Now `save_transcript` converts a
Simplified one with the same converter inspire uses (`zh_convert`:
REEL_SCOUT_ZH_CONVERT, s2twp by default, then hotwords) and keeps the received
text in `text_full_original` / `segments_json_original` (schema v21), so the
SSOT is never overwritten. Native Traditional caption tracks are still picked
first (`zh_track_rank`); this only handles "what we got was Simplified".
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from reel_scout import config, db

SIMP = "这个视频说的是开发软件的经验，总之这样应该会更好。"
TRAD_TW = "這個影片說的是開發軟體的經驗，總之這樣應該會更好。"
TRAD_NATIVE = "這個影片說的是開發的經驗，總之這樣應該會更好。"


def _segs(*texts):
    return json.dumps([{"start": float(i), "end": float(i + 1), "text": t, "confidence": 0.9}
                       for i, t in enumerate(texts)], ensure_ascii=False)


@pytest.fixture
def conn(temp_db, monkeypatch):
    monkeypatch.setattr(config, "ZH_CONVERT", "s2twp")
    monkeypatch.setattr(config, "ZH_HOTWORDS", "")
    monkeypatch.setattr(db, "_zh_missing_warned", False)
    c = sqlite3.connect(temp_db)
    c.row_factory = sqlite3.Row
    db.init_db(c)
    try:
        yield c
    finally:
        c.close()


def _video(c, pid="p1"):
    return db.upsert_video(c, platform="youtube", platform_id=pid, url="u-" + pid, title="t")


def _row(c, vid):
    return c.execute("SELECT * FROM transcripts WHERE video_id=?", (vid,)).fetchone()


# ------------------------------------------------------------------ schema

def test_fresh_db_has_the_v21_columns(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(transcripts)")}
    assert {"text_full_original", "segments_json_original", "zh_conversion"} <= cols
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION >= 21


def test_v20_database_upgrades_and_keeps_its_rows(temp_db):
    c = sqlite3.connect(temp_db)
    c.row_factory = sqlite3.Row
    # Rebuild transcripts the way v20 had it, with a row in it.
    c.executescript("""
        ALTER TABLE transcripts RENAME TO transcripts_v21;
        CREATE TABLE transcripts (
            video_id TEXT PRIMARY KEY REFERENCES videos(id), language TEXT,
            text_full TEXT, segments_json TEXT, whisper_model TEXT,
            duration_sec REAL, created_at TEXT DEFAULT (datetime('now')));
        INSERT INTO transcripts (video_id, language, text_full, segments_json, whisper_model, duration_sec)
            VALUES ('old', 'zh', '这个旧的', '[]', 'w', 1.0);
        UPDATE schema_version SET version = 20;
    """)
    c.commit()
    db.init_db(c)
    assert c.execute("SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION
    cols = {r[1] for r in c.execute("PRAGMA table_info(transcripts)")}
    assert {"text_full_original", "segments_json_original", "zh_conversion"} <= cols
    row = _row(c, "old")
    # Upgrading never converts existing rows: that is a per-creator decision.
    assert row["text_full"] == "这个旧的"
    assert row["text_full_original"] is None and row["zh_conversion"] is None
    db.init_db(c)  # idempotent
    c.close()


@pytest.mark.parametrize("code,hans", [
    ("zh-Hans", True), ("zh-CN", True), ("zh_cn", True), ("zh-Hans-orig", True), ("zh-SG", True),
    ("zh", False), ("zh-Hant", False), ("zh-TW", False), ("en", False), ("", False), (None, False),
])
def test_is_simplified_tag(code, hans):
    assert db.is_simplified_tag(code) is hans


# ------------------------------------------------------------------ conversion (needs the zh extra)

def test_simplified_transcript_is_stored_traditional_with_original_kept(conn, capsys, need_opencc):
    vid = _video(conn)
    segs = _segs("这个视频说的是", "开发软件的经验")
    db.save_transcript(conn, vid, "zh", SIMP, segs, "large-v3", 2.0)
    row = _row(conn, vid)
    assert row["text_full"] == TRAD_TW
    assert row["text_full_original"] == SIMP              # SSOT kept, byte for byte
    assert row["segments_json_original"] == segs
    assert [s["text"] for s in json.loads(row["segments_json"])] == ["這個影片說的是", "開發軟體的經驗"]
    assert json.loads(row["segments_json"])[1]["start"] == 1.0   # only text is touched
    assert row["zh_conversion"] == "s2twp"
    assert row["language"] == "zh"
    err = capsys.readouterr().err
    assert "stored as Traditional (s2twp)" in err
    assert "mixes traditional" not in err                 # what is stored is not mixed


def test_mixed_transcript_is_converted_and_no_longer_reported_as_mixed(conn, capsys, need_opencc):
    vid = _video(conn)
    db.save_transcript(conn, vid, "zh", TRAD_NATIVE + SIMP, "[]", "w", 1.0)
    row = _row(conn, vid)
    assert db.scan_script_mix(row["text_full"])[1] == 0
    assert row["text_full_original"] == TRAD_NATIVE + SIMP
    assert "mixes traditional" not in capsys.readouterr().err


def test_simplified_caption_tag_triggers_conversion_without_detector_hits(conn, need_opencc):
    # 视频/软件 are not in the detector's 20-character list; the zh-Hans tag is
    # what says the track is Simplified.
    text = "视频软件"
    v1 = _video(conn, "a")
    db.save_transcript(conn, v1, "zh-Hans", text, "[]", "vtt", 1.0)
    assert _row(conn, v1)["text_full"] == "影片軟體"
    v2 = _video(conn, "b")
    db.save_transcript(conn, v2, "zh", text, "[]", "vtt", 1.0)
    assert _row(conn, v2)["text_full"] == text            # no signal -> stored as received
    assert _row(conn, v2)["zh_conversion"] is None


def test_traditional_and_english_are_stored_as_received(conn, capsys, need_opencc):
    v1 = _video(conn, "a")
    db.save_transcript(conn, v1, "zh-TW", TRAD_NATIVE, _segs(TRAD_NATIVE), "vtt", 1.0)
    v2 = _video(conn, "b")
    db.save_transcript(conn, v2, "en", "hello world", "[]", "w", 1.0)
    for v, text in ((v1, TRAD_NATIVE), (v2, "hello world")):
        row = _row(conn, v)
        assert row["text_full"] == text
        assert row["text_full_original"] is None and row["segments_json_original"] is None
        assert row["zh_conversion"] is None
    assert "zh:" not in capsys.readouterr().err


def test_s2tw_mode_and_hotwords(conn, tmp_path, monkeypatch, need_opencc):
    hot = tmp_path / "hot.yaml"
    hot.write_text("软件: 軟件\n", encoding="utf-8")
    monkeypatch.setattr(config, "ZH_CONVERT", "s2tw")
    monkeypatch.setattr(config, "ZH_HOTWORDS", str(hot))
    vid = _video(conn)
    db.save_transcript(conn, vid, "zh", "这个视频软件", "[]", "w", 1.0)
    row = _row(conn, vid)
    assert row["text_full"] == "這個視頻軟件"               # per character, hotword wins
    assert row["zh_conversion"] == "s2tw+hotwords"


def test_resave_as_traditional_clears_the_original(conn, need_opencc):
    vid = _video(conn)
    db.save_transcript(conn, vid, "zh", SIMP, "[]", "w", 1.0)
    assert _row(conn, vid)["text_full_original"] == SIMP
    db.save_transcript(conn, vid, "zh-TW", TRAD_NATIVE, "[]", "vtt", 1.0)
    row = _row(conn, vid)
    assert row["text_full"] == TRAD_NATIVE and row["text_full_original"] is None


def test_restore_transcript_originals_rolls_back(conn, need_opencc):
    v1, v2, v3 = _video(conn, "a"), _video(conn, "b"), _video(conn, "c")
    segs = _segs("这个视频")
    db.save_transcript(conn, v1, "zh", SIMP, segs, "w", 1.0)
    db.save_transcript(conn, v2, "zh", SIMP, "[]", "w", 1.0)
    db.save_transcript(conn, v3, "zh-TW", TRAD_NATIVE, "[]", "w", 1.0)
    assert db.restore_transcript_originals(conn, v1) == 1
    row = _row(conn, v1)
    assert row["text_full"] == SIMP and row["segments_json"] == segs
    assert row["text_full_original"] is None and row["zh_conversion"] is None
    assert _row(conn, v2)["text_full"] == TRAD_TW          # untouched by the scoped call
    assert db.restore_transcript_originals(conn) == 1      # the rest (v2); v3 had nothing
    assert _row(conn, v2)["text_full"] == SIMP
    assert _row(conn, v3)["text_full"] == TRAD_NATIVE


# ------------------------------------------------------------------ fallbacks (no extra needed)

def test_mode_off_stores_simplified_as_received(conn, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ZH_CONVERT", "off")
    # off means "as received" for a transcript -- a hotword table (which
    # inspire still applies in off mode) must not half-rewrite it either.
    hot = tmp_path / "hot.yaml"
    hot.write_text("视频: 影片\n", encoding="utf-8")
    monkeypatch.setattr(config, "ZH_HOTWORDS", str(hot))
    vid = _video(conn)
    db.save_transcript(conn, vid, "zh-Hans", SIMP, "[]", "w", 1.0)
    row = _row(conn, vid)
    assert row["text_full"] == SIMP and row["text_full_original"] is None
    assert "opencc" not in capsys.readouterr().err


def test_without_opencc_store_as_received_and_warn_once(conn, capsys, no_opencc):
    v1, v2 = _video(conn, "a"), _video(conn, "b")
    db.save_transcript(conn, v1, "zh", SIMP, "[]", "w", 1.0)
    row = _row(conn, v1)
    assert row["text_full"] == SIMP and row["text_full_original"] is None
    err = capsys.readouterr().err
    assert "opencc is not installed" in err and 'pip install "reel-scout[zh]"' in err
    db.save_transcript(conn, v2, "zh", SIMP, "[]", "w", 1.0)
    assert "opencc is not installed" not in capsys.readouterr().err


def test_unusable_settings_cost_the_conversion_not_the_transcript(conn, capsys, monkeypatch):
    monkeypatch.setattr(config, "ZH_CONVERT", "s2xx")
    vid = _video(conn)
    db.save_transcript(conn, vid, "zh", SIMP, "[]", "w", 1.0)
    assert _row(conn, vid)["text_full"] == SIMP
    assert "unusable" in capsys.readouterr().err
    monkeypatch.setattr(config, "ZH_CONVERT", "s2twp")
    monkeypatch.setattr(config, "ZH_HOTWORDS", "/nonexistent/hot.yaml")
    v2 = _video(conn, "b")
    db.save_transcript(conn, v2, "zh", SIMP, "[]", "w", 1.0)
    assert _row(conn, v2)["text_full"] == SIMP
    assert "unusable" in capsys.readouterr().err
