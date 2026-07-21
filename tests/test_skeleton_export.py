"""R-skel — beat/rhythm skeleton export (reel-scout → smart-edit hand-off)."""
from __future__ import annotations

import json
import os

from reel_scout import db
from reel_scout.export.skeleton import build_skeleton, export_skeleton


def _video(**over):
    base = {"id": "v1", "platform": "youtube", "url": "http://x/1",
            "title": "Ref", "duration_sec": 30.0}
    base.update(over)
    return base


def _transcript(segments, **over):
    base = {"segments_json": json.dumps(segments, ensure_ascii=False),
            "duration_sec": 30.0, "language": "zh"}
    base.update(over)
    return base


def _metrics(**over):
    base = {"shot_count": 12, "cuts_per_minute": 24.0, "avg_shot_sec": 2.5,
            "audio_bpm": 120.0, "audio_energy": 0.7}
    base.update(over)
    return base


# --- build_skeleton (pure) --------------------------------------------------

def test_build_skeleton_full_shape():
    segs = [{"start": 0.0, "end": 2.5, "text": "hook line"},
            {"start": 2.5, "end": 6.0, "text": "body line"}]
    sk = build_skeleton(_video(), _transcript(segs), _metrics())
    assert sk["video_id"] == "v1"
    assert sk["duration_sec"] == 30.0
    assert sk["language"] == "zh"
    assert sk["beat_count"] == 2
    assert sk["rhythm"] == {
        "shot_count": 12, "cuts_per_minute": 24.0, "avg_shot_sec": 2.5,
        "audio_bpm": 120.0, "audio_energy": 0.7,
    }
    assert sk["beats"][0] == {"index": 0, "start": 0.0, "end": 2.5,
                              "dur_sec": 2.5, "text": "hook line"}
    assert sk["beats"][1]["dur_sec"] == 3.5
    assert sk["speaker_turns"] is None   # no speaker field → unknown, not 0


def test_build_skeleton_counts_speaker_turns():
    segs = [
        {"start": 0.0, "end": 1.0, "text": "a", "speaker": "A"},
        {"start": 1.0, "end": 2.0, "text": "b", "speaker": "A"},   # no change
        {"start": 2.0, "end": 3.0, "text": "c", "speaker": "B"},   # A→B
        {"start": 3.0, "end": 4.0, "text": "d", "speaker": "A"},   # B→A
    ]
    sk = build_skeleton(_video(), _transcript(segs), _metrics())
    assert sk["speaker_turns"] == 2
    assert sk["beats"][0]["speaker"] == "A"


def test_build_skeleton_no_transcript_or_metrics_degrades():
    sk = build_skeleton(_video(duration_sec=None), None, None)
    assert sk["beats"] == []
    assert sk["beat_count"] == 0
    assert sk["rhythm"] is None
    assert sk["language"] is None
    assert sk["speaker_turns"] is None
    assert sk["duration_sec"] is None


def test_build_skeleton_duration_falls_back_to_transcript():
    sk = build_skeleton(_video(duration_sec=None), _transcript([], duration_sec=18.0), None)
    assert sk["duration_sec"] == 18.0


def test_build_skeleton_tolerates_corrupt_segments_and_skips_incomplete():
    # corrupt JSON → no beats, no crash
    corrupt = _transcript([])
    corrupt["segments_json"] = "{bad"
    assert build_skeleton(_video(), corrupt, None)["beats"] == []
    # a segment missing start/end is skipped; indices stay contiguous
    segs = [{"start": 0.0, "end": 1.0, "text": "keep"},
            {"text": "no timing"},
            {"start": 1.0, "end": 2.0, "text": "keep2"}]
    beats = build_skeleton(_video(), _transcript(segs), None)["beats"]
    assert [b["index"] for b in beats] == [0, 1]
    assert [b["text"] for b in beats] == ["keep", "keep2"]


# --- export_skeleton (end-to-end via temp DB) -------------------------------

def test_export_skeleton_writes_file(temp_db, tmp_path):
    conn = db.init_db()
    conn.execute(
        "INSERT INTO videos (id, platform, platform_id, url, title, duration_sec, status) "
        "VALUES (?,?,?,?,?,?,?)",
        ("v1", "youtube", "pid1", "http://x/1", "Ref", 30.0, "analyzed"),
    )
    db.save_transcript(
        conn, "v1", "zh", "hi there",
        json.dumps([{"start": 0, "end": 2, "text": "hi", "speaker": "A"},
                    {"start": 2, "end": 5, "text": "there", "speaker": "B"}],
                   ensure_ascii=False),
        "large-v3", 30.0,
    )
    conn.execute(
        "INSERT INTO shot_metrics (video_id, shot_count, cuts_per_minute, avg_shot_sec, "
        "audio_bpm, audio_energy) VALUES (?,?,?,?,?,?)",
        ("v1", 10, 20.0, 3.0, 110.0, 0.5),
    )
    conn.commit()

    out = str(tmp_path / "skel")
    count = export_skeleton(conn, out, video_id="v1")
    conn.close()

    assert count == 1
    fpath = os.path.join(out, "v1.skeleton.json")
    assert os.path.exists(fpath)
    with open(fpath, encoding="utf-8") as f:
        sk = json.load(f)
    assert sk["video_id"] == "v1"
    assert sk["beat_count"] == 2
    assert sk["speaker_turns"] == 1
    assert sk["rhythm"]["audio_bpm"] == 110.0
