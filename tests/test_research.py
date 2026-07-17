"""Cross-channel research aggregation (roadmap 4A, PR-D)."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

from reel_scout import db, research


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _seed(conn, pid, uploader, full, score):
    vid = db.upsert_video(conn, platform="youtube", platform_id=pid,
                          url="https://y/%s" % pid, title=pid, uploader=uploader)
    db.save_analysis(conn, vid, summary="", topics_json="[]",
                     hooks_json=json.dumps(full.get("hook", {})),
                     style_json=json.dumps(full.get("style", {})),
                     engagement_signals_json="{}", full_json=json.dumps(full))
    conn.execute(
        "INSERT INTO scores (video_id, hook_strength, visual_storytelling, "
        "pacing, structure, overall) VALUES (?,?,?,?,?,?)", (vid, *score))
    conn.commit()
    return vid


def _two_channel_corpus(conn):
    a1 = _seed(conn, "a1", "Alpha",
               {"content_type": "educational", "content_structure": "listicle",
                "style": {"format": "talking_head", "pacing": "fast"},
                "hook": {"opening_type": "question", "cta_type": "follow"}},
               (8.0, 7.0, 8.0, 7.0, 8.0))
    a2 = _seed(conn, "a2", "Alpha",
               {"content_type": "educational", "content_structure": "listicle",
                "style": {"format": "talking_head", "pacing": "medium"},
                "hook": {"opening_type": "statement", "cta_type": "follow"}},
               (6.0, 6.0, 6.0, 6.0, 6.0))
    b1 = _seed(conn, "b1", "Beta",
               {"content_type": "story", "content_structure": "story-arc",
                "style": {"format": "vlog", "pacing": "slow"},
                "hook": {"opening_type": "visual", "cta_type": "visit"}},
               (5.0, 9.0, 5.0, 8.0, 6.0))
    return {"https://chan/alpha": [a1, a2], "https://chan/beta": [b1]}


def test_aggregate_per_channel_and_niche_wide():
    conn, path = _fresh_db()
    try:
        mapping = _two_channel_corpus(conn)
        report = research.aggregate(conn, mapping, niche="test-niche")
        assert report["niche"] == "test-niche"
        assert report["channel_count"] == 2

        alpha = next(c for c in report["channels"] if c["channel_url"].endswith("alpha"))
        assert alpha["video_count"] == 2
        assert alpha["uploader"] == "Alpha"
        assert alpha["modal_format"] == "talking_head"
        assert alpha["modal_structure"] == "listicle"
        assert alpha["avg_overall"] == 7.0  # (8+6)/2
        assert alpha["distributions"]["cta_type"] == {"follow": 2}

        nw = report["niche_wide"]
        assert nw["video_count"] == 3
        assert nw["modal_format"] == "talking_head"  # 2 of 3
        assert nw["distributions"]["content_type"] == {"educational": 2, "story": 1}
        assert nw["avg_overall"] == round((8 + 6 + 6) / 3, 2)
    finally:
        conn.close()
        os.unlink(path)


def test_aggregate_empty_channel_does_not_crash():
    conn, path = _fresh_db()
    try:
        report = research.aggregate(conn, {"https://chan/empty": []}, niche="x")
        ch = report["channels"][0]
        assert ch["video_count"] == 0
        assert ch["modal_format"] is None
        assert ch["avg_overall"] is None
        assert report["niche_wide"]["video_count"] == 0
    finally:
        conn.close()
        os.unlink(path)


def test_run_research_no_analyze_aggregates_existing_db():
    # do_analyze=False must skip crawl/pipeline entirely and aggregate what is
    # already in the DB, resolving channel URLs → video_ids by videos.url.
    conn, path = _fresh_db()
    try:
        _seed(conn, "x", "Solo",
              {"content_type": "review", "content_structure": "hook-body-cta",
               "style": {"format": "reaction", "pacing": "fast"},
               "hook": {"opening_type": "question", "cta_type": "like"}},
              (7.0, 7.0, 7.0, 7.0, 7.0))
        # expand_channels will try to browse the fake channel URL and fail →
        # empty mapping, so no video resolves. Instead we test aggregate path by
        # monkeypatching expand to return the known video URL.
        orig = research.expand_channels
        research.expand_channels = lambda urls, depth: {"https://chan/solo": ["https://y/x"]}
        try:
            report = research.run_research(
                conn, niche="n", channel_urls=["https://chan/solo"],
                depth=5, do_analyze=False)
        finally:
            research.expand_channels = orig
        ch = report["channels"][0]
        assert ch["video_count"] == 1
        assert ch["uploader"] == "Solo"
        assert ch["modal_format"] == "reaction"
    finally:
        conn.close()
        os.unlink(path)
