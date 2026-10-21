"""The mixed-script finding is stored with the transcript, not only printed (#114).

`save_transcript` has detected traditional/simplified mixing since 2026-08-15,
but the result went to stderr and nowhere else: months later, `get_transcript`,
`show`, MCP `show_video` and `export` said nothing, and a keyword search over
the transcript silently missed half of it. Schema v22 stores it in
`transcripts.script_mix`; these tests pin both halves of the wire -- that the
column is written, and that every consumer actually reads it (the reverse test
turns the detector off and checks the consumers go quiet).
"""
from __future__ import annotations

import json
import os
import sqlite3
import types

import pytest

from reel_scout import cli, config, db
from reel_scout.export.json_export import export_json
from reel_scout.mcp import tools

_TRAD = "這個說時來對開發國學實體會過樣應點總經電"
_SIMP = "这个说时来对开发国学实体会过样应点总经电"
MIXED = _TRAD * 3 + _SIMP * 2          # 60 trad / 40 simp -> minority 0.40


@pytest.fixture
def conn(temp_db, monkeypatch):
    # The detector is under test, not the converter: with the zh extra
    # installed a mixed transcript would be converted before it is stored.
    monkeypatch.setattr(config, "ZH_CONVERT", "off")
    c = sqlite3.connect(temp_db)
    c.row_factory = sqlite3.Row
    db.init_db(c)
    try:
        yield c
    finally:
        c.close()


def _save(c, pid, text, analyzed=False):
    vid = db.upsert_video(c, platform="youtube", platform_id=pid, url="u-" + pid, title="t")
    db.save_transcript(c, vid, "zh", text, "[]", "w", 1.0)
    if analyzed:
        db.save_analysis(c, vid, "summary", "[]", "[]", "{}", "{}", "{}")
        c.commit()
    return vid


# ------------------------------------------------------------------ storage

def test_mixed_transcript_stores_the_counts(conn):
    vid = _save(conn, "m", MIXED)
    row = db.get_transcript(conn, vid)
    assert json.loads(row["script_mix"]) == {"trad": 60, "simp": 40, "minority": 0.4}
    assert db.parse_script_mix(row) == {"trad": 60, "simp": 40, "minority": 0.4}


@pytest.mark.parametrize("text", [_TRAD * 3, _SIMP * 3, "hello world", ""])
def test_single_script_non_chinese_and_empty_store_null(conn, text):
    vid = _save(conn, "p", text)
    assert db.get_transcript(conn, vid)["script_mix"] is None


def test_resaving_clean_text_clears_the_flag(conn):
    vid = _save(conn, "m", MIXED)
    db.save_transcript(conn, vid, "zh", _TRAD, "[]", "w", 1.0)
    assert db.get_transcript(conn, vid)["script_mix"] is None


def test_v21_database_upgrades_and_backfills(temp_db):
    c = sqlite3.connect(temp_db)
    c.row_factory = sqlite3.Row
    c.executescript("""
        ALTER TABLE transcripts RENAME TO transcripts_v22;
        CREATE TABLE transcripts (
            video_id TEXT PRIMARY KEY REFERENCES videos(id), language TEXT,
            text_full TEXT, segments_json TEXT, whisper_model TEXT,
            duration_sec REAL, created_at TEXT DEFAULT (datetime('now')),
            text_full_original TEXT, segments_json_original TEXT, zh_conversion TEXT);
        UPDATE schema_version SET version = 21;
    """)
    c.executemany(
        "INSERT INTO transcripts (video_id, language, text_full, segments_json, whisper_model, "
        "duration_sec) VALUES (?, 'zh', ?, '[]', 'w', 1.0)",
        [("mixed", MIXED), ("pure", _TRAD), ("empty", None)])
    c.commit()
    db.init_db(c)
    assert c.execute("SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION >= 22
    rows = {r["video_id"]: r for r in c.execute("SELECT * FROM transcripts")}
    assert db.parse_script_mix(rows["mixed"]) == {"trad": 60, "simp": 40, "minority": 0.4}
    assert rows["pure"]["script_mix"] is None and rows["empty"]["script_mix"] is None
    # Detect, do not convert: the backfill only writes the new column.
    assert rows["mixed"]["text_full"] == MIXED
    db.init_db(c)  # idempotent
    c.close()


def test_restore_originals_recomputes_the_flag(conn, monkeypatch, need_opencc):
    monkeypatch.setattr(config, "ZH_CONVERT", "s2twp")
    monkeypatch.setattr(config, "ZH_HOTWORDS", "")
    vid = _save(conn, "c", _TRAD + _SIMP)
    assert db.get_transcript(conn, vid)["zh_conversion"]          # converted ...
    assert db.get_transcript(conn, vid)["script_mix"] is None      # ... so not mixed
    assert db.restore_transcript_originals(conn, vid) == 1
    assert db.parse_script_mix(db.get_transcript(conn, vid))["simp"] > 0


def test_parse_script_mix_tolerates_missing_column_and_bad_json():
    assert db.parse_script_mix(None) is None
    assert db.parse_script_mix({}) is None
    assert db.parse_script_mix({"script_mix": "not json"}) is None
    assert db.script_mix_warning(None) is None


# ------------------------------------------------------------------ consumers

def _show_video(vid):
    res = tools._tool_show_video({"video_id": vid})
    return json.loads(res["content"][0]["text"])


def test_show_video_carries_the_warning(conn):
    mixed = _save(conn, "m", MIXED)
    pure = _save(conn, "p", _TRAD)
    t = _show_video(mixed)["transcript"]
    assert t["script_mix"] == {"trad": 60, "simp": 40, "minority": 0.4}
    assert "silently miss" in t["warning"] and "40%" in t["warning"]
    t = _show_video(pure)["transcript"]
    assert t["script_mix"] is None and "warning" not in t


def test_cli_show_and_export_carry_it(conn, capsys, tmp_path):
    vid = _save(conn, "m", MIXED, analyzed=True)
    capsys.readouterr()
    cli._cmd_show(types.SimpleNamespace(video_id=vid))
    assert "mixes traditional and simplified" in capsys.readouterr().out
    out = str(tmp_path / "json")
    assert export_json(conn, out, video_id=vid) == 1
    with open(os.path.join(out, vid + ".json"), encoding="utf-8") as f:
        assert json.load(f)["script_mix"] == {"trad": 60, "simp": 40, "minority": 0.4}


def test_with_detection_off_no_consumer_sees_a_warning(conn, capsys, tmp_path, monkeypatch):
    # Reverse test: if the consumers showed a warning without the stored value,
    # the tests above would not prove the signal is wired through the column.
    monkeypatch.setattr(db, "transcript_script_mix", lambda text: None)
    vid = _save(conn, "m", MIXED, analyzed=True)
    assert db.get_transcript(conn, vid)["script_mix"] is None
    t = _show_video(vid)["transcript"]
    assert t["script_mix"] is None and "warning" not in t
    capsys.readouterr()
    cli._cmd_show(types.SimpleNamespace(video_id=vid))
    assert "mixes traditional" not in capsys.readouterr().out
    out = str(tmp_path / "json")
    export_json(conn, out, video_id=vid)
    with open(os.path.join(out, vid + ".json"), encoding="utf-8") as f:
        assert json.load(f)["script_mix"] is None
