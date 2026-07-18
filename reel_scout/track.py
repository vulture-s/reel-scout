"""Performance tracking + iteration hints (roadmap 4D).

Record your own published video's real numbers (views/likes/comments), then
contrast its reverse-decoded structure with the high-scoring corpus to get
concrete, evidence-based iteration suggestions. The comparison is deterministic
(no LLM) so it's reproducible: it keys on the normalized structure/pacing tags
and the measured cuts/min from §4E.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import compare, db

# A video counts as part of the "what works" corpus at or above this overall score.
_HIGH_SCORE = 7.0


def resolve_my_video(conn: db.sqlite3.Connection, ref: str) -> str:
    """Resolve a --my-video reference: an exact URL already in the DB, or a video
    id / unique prefix. Errors clearly if it hasn't been analyzed yet."""
    v = db.get_video_by_url(conn, ref)
    if v is not None:
        return v["id"]
    video_id, matches = compare.resolve_ref(conn, ref)
    if video_id is None:
        if matches:
            raise ValueError("Ambiguous ref '%s' matches: %s" % (ref, ", ".join(matches)))
        raise ValueError(
            "No video found for '%s' — analyze it first (reel-scout analyze <url>)" % ref)
    return video_id


def record_performance(
    conn: db.sqlite3.Connection,
    ref: str,
    views: Optional[int] = None,
    likes: Optional[int] = None,
    comments: Optional[int] = None,
    notes: Optional[str] = None,
) -> str:
    video_id = resolve_my_video(conn, ref)
    db.save_performance(conn, video_id, views, likes, comments, notes)
    return video_id


def _mode(d: Dict[str, int]) -> Optional[str]:
    return max(d, key=lambda k: d[k]) if d else None


def _corpus_baseline(conn: db.sqlite3.Connection, exclude_id: str) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT a.content_structure AS structure, a.style_pacing AS pacing, "
        "sm.cuts_per_minute AS cpm FROM scores s "
        "JOIN analyses a ON a.video_id = s.video_id "
        "LEFT JOIN shot_metrics sm ON sm.video_id = s.video_id "
        "WHERE s.overall >= ? AND s.video_id != ?",
        (_HIGH_SCORE, exclude_id),
    ).fetchall()
    structures: Dict[str, int] = {}
    pacings: Dict[str, int] = {}
    cpms: List[float] = []
    for r in rows:
        if r["structure"]:
            structures[r["structure"]] = structures.get(r["structure"], 0) + 1
        if r["pacing"]:
            pacings[r["pacing"]] = pacings.get(r["pacing"], 0) + 1
        if r["cpm"] is not None:
            cpms.append(r["cpm"])
    return {
        "n": len(rows),
        "top_structure": _mode(structures),
        "top_pacing": _mode(pacings),
        "avg_cuts_per_minute": round(sum(cpms) / len(cpms), 2) if cpms else None,
    }


def compare_to_corpus(conn: db.sqlite3.Connection, video_id: str) -> Dict[str, Any]:
    analysis = db.get_analysis(conn, video_id)
    sm = db.get_shot_metrics(conn, video_id)
    mine = {
        "content_structure": analysis["content_structure"] if analysis else None,
        "style_pacing": analysis["style_pacing"] if analysis else None,
        "cuts_per_minute": sm["cuts_per_minute"] if sm else None,
    }
    base = _corpus_baseline(conn, video_id)
    suggestions: List[str] = []
    if base["n"] == 0:
        suggestions.append(
            "No high-scoring corpus yet (need videos scoring >= %.0f) — "
            "analyze more competitors first." % _HIGH_SCORE)
        return {"video_id": video_id, "mine": mine, "corpus": base, "suggestions": suggestions}

    if base["top_structure"] and mine["content_structure"] \
            and base["top_structure"] != mine["content_structure"]:
        suggestions.append(
            "Top performers mostly use '%s' structure; yours is '%s' — consider restructuring."
            % (base["top_structure"], mine["content_structure"]))
    if base["avg_cuts_per_minute"] is not None and mine["cuts_per_minute"] is not None:
        avg = base["avg_cuts_per_minute"]
        mine_cpm = mine["cuts_per_minute"]
        if mine_cpm < avg * 0.7:
            suggestions.append(
                "Top performers cut faster (~%.1f cuts/min vs your %.1f) — tighten the edit."
                % (avg, mine_cpm))
        elif mine_cpm > avg * 1.3:
            suggestions.append(
                "Your cut rate (%.1f/min) is well above the top-performer avg (%.1f) — "
                "may feel frenetic." % (mine_cpm, avg))
    if base["top_pacing"] and mine["style_pacing"] \
            and base["top_pacing"] != mine["style_pacing"]:
        suggestions.append(
            "Top performers pace '%s'; yours reads '%s'." % (base["top_pacing"], mine["style_pacing"]))
    if not suggestions:
        suggestions.append("Your structure/pacing already aligns with the top performers.")
    return {"video_id": video_id, "mine": mine, "corpus": base, "suggestions": suggestions}


def format_track(perf: Any, cmp: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("Tracked %s" % cmp["video_id"])
    lines.append("=" * 44)
    if perf is not None:
        lines.append("Performance: views=%s likes=%s comments=%s" % (
            perf["views"], perf["likes"], perf["comments"]))
        if perf["notes"]:
            lines.append("Notes: %s" % perf["notes"])
    base = cmp["corpus"]
    lines.append("\nvs high-scoring corpus (n=%d, overall>=%.0f):" % (base["n"], _HIGH_SCORE))
    lines.append("  top structure: %s   top pacing: %s   avg cuts/min: %s" % (
        base["top_structure"], base["top_pacing"], base["avg_cuts_per_minute"]))
    lines.append("\nIteration suggestions:")
    for s in cmp["suggestions"]:
        lines.append("  - %s" % s)
    return "\n".join(lines)
