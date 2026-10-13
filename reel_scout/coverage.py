"""How much of each clip the transcript and the keyframes actually cover.

Two readings per clip, each with a **max gap** next to the percentage:

- transcript: share of the clip inside some subtitle/Whisper segment, and the
  longest stretch with no segment at all (head and tail included);
- keyframes: how far the sampled frames reach, and the longest stretch between
  two consecutive frames the VLM saw (head and tail included).

The percentage alone hid the failure it was meant to catch. A 2026-10-02 audit
of 12 clips read 69-100% keyframe coverage -- healthy-looking -- while the
largest gap between frames was 10-77 s on clips sampled with only 12-22
frames. "Where is the last frame" answers whether sampling collapsed onto the
opening; it says nothing about a hole in the middle. The max gap does.

Unknown duration is reported as unmeasured (None), never as 0 or 100: without
it the tail gap cannot be computed, and a number that silently drops the tail
looks exactly like a good one.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import db

Span = Tuple[float, float]


def _clip(spans: Iterable[Span], duration: float) -> List[Span]:
    out = []  # type: List[Span]
    for start, end in spans:
        try:
            s = max(0.0, float(start))
            e = min(float(duration), float(end))
        except (TypeError, ValueError):
            continue
        if e < s:
            continue
        out.append((s, e))
    out.sort()
    return out


def span_coverage(spans: Iterable[Span], duration: Optional[float]) -> Dict[str, Any]:
    """Coverage of [0, duration] by a set of (start, end) spans.

    Returns ``covered_pct`` (union of the spans / duration), ``max_gap_sec``
    (longest uncovered stretch, head before the first span and tail after the
    last included) and ``max_gap_at`` (where that stretch starts). A point --
    a keyframe -- is a zero-width span. No spans at all: the whole clip is one
    gap. Unknown or non-positive duration: every field is None (unmeasured).
    """
    if not duration or duration <= 0:
        return {"covered_pct": None, "max_gap_sec": None, "max_gap_at": None}
    merged = []  # type: List[List[float]]
    for s, e in _clip(spans, duration):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    covered = sum(e - s for s, e in merged)
    best_gap = 0.0
    best_at = None  # type: Optional[float]
    cursor = 0.0
    for s, e in merged:
        if s - cursor > best_gap:
            best_gap, best_at = s - cursor, cursor
        cursor = max(cursor, e)
    if duration - cursor > best_gap:
        best_gap, best_at = duration - cursor, cursor
    return {
        "covered_pct": round(100.0 * covered / duration, 1),
        "max_gap_sec": round(best_gap, 2),
        "max_gap_at": None if best_at is None else round(best_at, 2),
    }


def point_coverage(points: Sequence[float], duration: Optional[float]) -> Dict[str, Any]:
    """Keyframe reading: how far the frames reach, and the largest hole."""
    pts = []  # type: List[float]
    for p in points:
        try:
            pts.append(float(p))
        except (TypeError, ValueError):
            continue
    res = span_coverage([(p, p) for p in pts], duration)
    reach = None
    if res["covered_pct"] is not None and pts:
        reach = round(100.0 * min(max(pts), float(duration)) / float(duration), 1)
    elif res["covered_pct"] is not None:
        reach = 0.0
    return {
        "frames": len(pts),
        "reach_pct": reach,
        "max_gap_sec": res["max_gap_sec"],
        "max_gap_at": res["max_gap_at"],
    }


def _segments(row) -> List[Span]:
    try:
        data = json.loads(row["segments_json"] or "[]")
    except (TypeError, ValueError):
        return []
    out = []  # type: List[Span]
    for seg in data if isinstance(data, list) else []:
        if isinstance(seg, dict) and "start" in seg and "end" in seg:
            out.append((seg["start"], seg["end"]))
    return out


def compute(conn, channel: Optional[str] = None,
            limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """One row per video: transcript and keyframe coverage with max gaps.

    Sorted worst-first by the larger of the two max gaps, so the clip with the
    biggest blind stretch is the first line, whichever layer it is in.
    """
    sql = ("SELECT v.id, v.uploader, v.title, v.duration_sec, "
           "t.video_id AS t_vid, t.segments_json, t.whisper_model, "
           "t.duration_sec AS t_duration "
           "FROM videos v LEFT JOIN transcripts t ON t.video_id = v.id")
    params = []  # type: List[Any]
    if channel:
        sql += " WHERE v.uploader LIKE ?"
        params.append("%" + channel + "%")
    rows = []  # type: List[Dict[str, Any]]
    for r in conn.execute(sql, params).fetchall():
        duration = r["duration_sec"] or r["t_duration"]
        frames = [k["timestamp_sec"] for k in db.get_keyframes(conn, r["id"])]
        transcript = None
        if r["t_vid"] is not None:
            transcript = span_coverage(_segments(r), duration)
            transcript["source"] = r["whisper_model"]
        keyframes = point_coverage(frames, duration) if frames else None
        if transcript is None and keyframes is None:
            continue
        rows.append({
            "video_id": r["id"],
            "uploader": r["uploader"],
            "title": r["title"],
            "duration_sec": duration,
            "transcript": transcript,
            "keyframes": keyframes,
        })

    def worst(row: Dict[str, Any]) -> float:
        gaps = [x["max_gap_sec"] for x in (row["transcript"], row["keyframes"])
                if x and x["max_gap_sec"] is not None]
        return max(gaps) if gaps else -1.0

    rows.sort(key=lambda r: (-worst(r), r["video_id"]))
    return rows[:limit] if limit else rows


def _fmt(v: Optional[float], unit: str = "") -> str:
    return "—" if v is None else ("%.1f%s" % (v, unit))


def format_rows(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "No videos with a transcript or keyframes in scope."
    head = "%-22s %8s | %7s %9s | %6s %7s %9s" % (
        "video", "dur", "sub%", "sub_gap", "frames", "reach%", "kf_gap")
    lines = [head, "-" * len(head)]
    for r in rows:
        t = r["transcript"] or {}
        k = r["keyframes"] or {}
        lines.append("%-22s %8s | %7s %9s | %6s %7s %9s" % (
            str(r["video_id"])[:22], _fmt(r["duration_sec"], "s"),
            _fmt(t.get("covered_pct")), _fmt(t.get("max_gap_sec"), "s"),
            k.get("frames", "—"), _fmt(k.get("reach_pct")),
            _fmt(k.get("max_gap_sec"), "s")))
    lines.append("")
    lines.append("sub_gap / kf_gap = longest stretch with no subtitle segment / "
                 "no sampled frame, head and tail included. — = not measured.")
    return "\n".join(lines)
