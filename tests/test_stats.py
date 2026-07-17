"""Corpus statistics (roadmap 3D)."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

from reel_scout import db, stats


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _seed(conn, pid, uploader, full, score=None):
    vid = db.upsert_video(conn, platform="youtube", platform_id=pid,
                          url="https://y/%s" % pid, title=pid, uploader=uploader)
    db.save_analysis(conn, vid, summary="", topics_json="[]",
                     hooks_json=json.dumps(full.get("hook", {})),
                     style_json=json.dumps(full.get("style", {})),
                     engagement_signals_json="{}", full_json=json.dumps(full))
    if score is not None:
        conn.execute(
            "INSERT INTO scores (video_id, hook_strength, visual_storytelling, "
            "pacing, structure, overall) VALUES (?,?,?,?,?,?)", (vid, *score))
        conn.commit()
    return vid


def _corpus(conn):
    _seed(conn, "a", "Chan One",
          {"content_type": "educational", "content_structure": "listicle",
           "style": {"format": "talking_head", "pacing": "fast"},
           "hook": {"opening_type": "question", "cta_type": "follow"}},
          score=(8.0, 7.0, 8.0, 7.0, 7.5))
    _seed(conn, "b", "Chan One",
          {"content_type": "educational", "content_structure": "hook-body-cta",
           "style": {"format": "talking_head", "pacing": "medium"},
           "hook": {"opening_type": "statement", "cta_type": "follow"}},
          score=(6.0, 6.0, 6.0, 6.0, 6.0))
    _seed(conn, "c", "Chan Two",
          {"content_type": "story", "content_structure": "story-arc",
           "style": {"format": "vlog", "pacing": "slow"},
           "hook": {"opening_type": "visual", "cta_type": "visit"}},
          score=(4.0, 9.0, 5.0, 8.0, 6.5))


def test_global_distributions_and_score_aggregates():
    conn, path = _fresh_db()
    try:
        _corpus(conn)
        s = stats.compute_stats(conn)
        assert s["total_videos"] == 3
        assert s["analyzed_videos"] == 3
        assert s["tag_distributions"]["content_type"] == {"educational": 2, "story": 1}
        assert s["tag_distributions"]["style_format"]["talking_head"] == 2
        assert s["tag_distributions"]["content_structure"]["listicle"] == 1
        ov = s["score_aggregates"]["overall"]
        assert ov["count"] == 3
        assert ov["min"] == 6.0 and ov["max"] == 7.5
        assert abs(ov["avg"] - round((7.5 + 6.0 + 6.5) / 3, 2)) < 1e-9
    finally:
        conn.close()
        os.unlink(path)


def test_channel_scope_filters_by_uploader():
    conn, path = _fresh_db()
    try:
        _corpus(conn)
        s = stats.compute_stats(conn, channel="Chan One")
        assert s["total_videos"] == 2
        assert s["tag_distributions"]["content_type"] == {"educational": 2}
        assert s["score_aggregates"]["overall"]["count"] == 2
        assert s["score_aggregates"]["overall"]["max"] == 7.5
    finally:
        conn.close()
        os.unlink(path)


def test_empty_corpus_has_zero_counts_not_crash():
    conn, path = _fresh_db()
    try:
        s = stats.compute_stats(conn)
        assert s["total_videos"] == 0
        assert s["tag_distributions"]["content_type"] == {}
        assert s["score_aggregates"]["overall"]["avg"] is None
        assert s["score_aggregates"]["overall"]["count"] == 0
        # formatter must not crash on empty
        assert "Corpus stats" in stats.format_stats(s)
    finally:
        conn.close()
        os.unlink(path)


def test_csv_export_long_format():
    conn, path = _fresh_db()
    try:
        _corpus(conn)
        s = stats.compute_stats(conn)
        out = os.path.join(os.path.dirname(path), "stats_out.csv")
        n = stats.write_csv(s, out)
        with open(out) as f:
            content = f.read()
        assert content.startswith("metric,dimension,key,value")
        assert "tag,content_type,educational,2" in content
        assert "score,overall,count,3" in content
        assert n > 0
        os.unlink(out)
    finally:
        conn.close()
        os.unlink(path)
