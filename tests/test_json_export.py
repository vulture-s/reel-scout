"""R-seg — `export --format json` keeps timecoded segments, not just text_full."""
from __future__ import annotations

import json
import os

from reel_scout import db
from reel_scout.export.json_export import _parse_segments, export_json


# --- _parse_segments (pure) -------------------------------------------------

def test_parse_segments_projects_shape_and_strips_text():
    segs = _parse_segments(json.dumps([
        {"start": 0, "end": 1, "text": " hi ", "speaker": "A"},
        {"start": 1, "end": 2, "text": "there"},
    ]))
    assert segs == [
        {"start": 0, "end": 1, "text": "hi", "speaker": "A"},
        {"start": 1, "end": 2, "text": "there"},   # no speaker key when absent
    ]


def test_parse_segments_empty_and_corrupt_degrade_to_list():
    assert _parse_segments(None) == []
    assert _parse_segments("") == []
    assert _parse_segments("{not valid json") == []
    assert _parse_segments(json.dumps({"not": "a list"})) == []
    assert _parse_segments(json.dumps([1, 2, "x"])) == []   # non-dict rows skipped


# --- export_json (end-to-end via temp DB) -----------------------------------

def test_export_json_includes_segments(temp_db, tmp_path):
    conn = db.init_db()
    conn.execute(
        "INSERT INTO videos (id, platform, platform_id, url, title, duration_sec, status) "
        "VALUES (?,?,?,?,?,?,?)",
        ("v1", "youtube", "pid1", "http://x/1", "Ref", 30.0, "analyzed"),
    )
    db.save_transcript(
        conn, "v1", "zh", "hi there",
        json.dumps([{"start": 0, "end": 2, "text": "hi", "speaker": "A"},
                    {"start": 2, "end": 5, "text": "there"}], ensure_ascii=False),
        "large-v3", 30.0,
    )
    db.save_analysis(conn, "v1", "summary", "[]", "[]", "{}", "{}", "{}")
    conn.commit()

    out = str(tmp_path / "json")
    count = export_json(conn, out, video_id="v1")
    conn.close()

    assert count == 1
    with open(os.path.join(out, "v1.json"), encoding="utf-8") as f:
        rec = json.load(f)
    assert rec["transcript"] == "hi there"       # flat text_full still present
    assert rec["segments"] == [
        {"start": 0, "end": 2, "text": "hi", "speaker": "A"},
        {"start": 2, "end": 5, "text": "there"},
    ]
