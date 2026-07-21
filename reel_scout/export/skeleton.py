"""Skeleton JSON export — the reel-scout → smart-edit hand-off (three-piece §4.4).

reel-scout deconstructs a reference clip; the skeleton is that deconstruction as a
plain data file: beat structure (transcript segments with per-segment seconds),
measured rhythm (cuts/min, avg shot length, BPM/energy), and speaker-turn count.
smart-edit consumes it as the edit target — a rhythm-and-structure spec — instead
of a one-line intent. The interface is a data format, not a function call: neither
side imports the other.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .. import db


def _segments_to_beats(segments_json: Optional[str]) -> List[Dict[str, Any]]:
    """Parse transcript segments into beats carrying per-segment seconds. Never
    raises — a corrupt / missing column degrades to []."""
    if not segments_json:
        return []
    try:
        rows = json.loads(segments_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(rows, list):
        return []
    beats: List[Dict[str, Any]] = []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        start, end = r.get("start"), r.get("end")
        if start is None or end is None:
            continue
        beat = {
            "index": len(beats),
            "start": round(float(start), 3),
            "end": round(float(end), 3),
            "dur_sec": round(float(end) - float(start), 3),
            "text": (r.get("text") or "").strip(),
        }
        # speaker is only present when diarization ran; omit it otherwise so the
        # skeleton doesn't imply speaker data it doesn't have.
        if r.get("speaker") is not None:
            beat["speaker"] = r["speaker"]
        beats.append(beat)
    return beats


def _speaker_turns(beats: List[Dict[str, Any]]) -> Optional[int]:
    """Count speaker changes across beats — the downstream cut signal (high = a
    conversation that should cross-cut, low = a monologue that should hold on
    b-roll). None when no beat carries a speaker (diarization wasn't run), so a
    zero-turn monologue is distinguishable from "unknown"."""
    speakers = [b["speaker"] for b in beats if "speaker" in b]
    if not speakers:
        return None
    return sum(1 for a, b in zip(speakers, speakers[1:]) if a != b)


def build_skeleton(video, transcript, shot_metrics) -> Dict[str, Any]:
    """Assemble the beat/rhythm skeleton of one reference clip.

    Pure: takes already-fetched rows (sqlite3.Row or dict), touches no DB. Any of
    `transcript` / `shot_metrics` may be None (not every clip has them) — the
    skeleton degrades field-by-field rather than failing.
    """
    beats = _segments_to_beats(transcript["segments_json"] if transcript is not None else None)

    rhythm = None
    if shot_metrics is not None:
        rhythm = {
            "shot_count": shot_metrics["shot_count"],
            "cuts_per_minute": shot_metrics["cuts_per_minute"],
            "avg_shot_sec": shot_metrics["avg_shot_sec"],
            "audio_bpm": shot_metrics["audio_bpm"],
            "audio_energy": shot_metrics["audio_energy"],
        }

    duration = None
    if video is not None and video["duration_sec"] is not None:
        duration = video["duration_sec"]
    elif transcript is not None and transcript["duration_sec"] is not None:
        duration = transcript["duration_sec"]

    return {
        "video_id": video["id"] if video is not None else None,
        "platform": video["platform"] if video is not None else None,
        "url": video["url"] if video is not None else None,
        "title": video["title"] if video is not None else None,
        "duration_sec": duration,
        "language": transcript["language"] if transcript is not None else None,
        "rhythm": rhythm,
        "beat_count": len(beats),
        "speaker_turns": _speaker_turns(beats),
        "beats": beats,
    }


def export_skeleton(conn, output_dir: str, video_id: Optional[str] = None) -> int:
    """Write one `<video_id>.skeleton.json` per video (or just the given one) into
    output_dir. Returns the count written."""
    os.makedirs(output_dir, exist_ok=True)

    if video_id:
        videos = [v for v in [db.get_video(conn, video_id)] if v is not None]
    else:
        videos = db.list_videos(conn, status="analyzed", limit=9999)

    count = 0
    for video in videos:
        vid = video["id"]
        skeleton = build_skeleton(
            video,
            db.get_transcript(conn, vid),
            db.get_shot_metrics(conn, vid),
        )
        fpath = os.path.join(output_dir, "%s.skeleton.json" % vid)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(skeleton, f, ensure_ascii=False, indent=2)
        count += 1

    return count
