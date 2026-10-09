"""An invalid mark must survive every write path, not just the pipeline's.

`validity.mark_invalid` flags a clip whose media never really processed, and
`scorer.score_video` refuses to score it. But `save_analysis` used to set
`status='analyzed'` (and clear `error_message`) unconditionally, so an agent
writing through `ingest analysis` silently un-invalidated the clip, erased the
reason, and `ingest score` then put a number for it back into the aggregates.
"""
import pytest

from reel_scout import db, ingest, validity


def _invalid_clip(conn):
    vid = db.upsert_video(conn, "youtube", "abc", "https://youtu.be/abc", title="t")
    validity.mark_invalid(conn, vid, "zero frames contradiction")
    return vid


def test_ingest_analysis_refuses_invalid_clip_and_keeps_reason(temp_db):
    conn = db.get_connection()
    vid = _invalid_clip(conn)
    with pytest.raises(ValueError, match="invalid"):
        ingest.ingest_analysis(conn, vid, {"summary": "s", "model": "claude"})
    row = db.get_video(conn, vid)
    assert row["status"] == validity.INVALID_STATUS
    assert row["error_message"] == "zero frames contradiction"
    assert db.get_analysis(conn, vid) is None


def test_ingest_score_refuses_invalid_clip(temp_db):
    conn = db.get_connection()
    vid = _invalid_clip(conn)
    with pytest.raises(ValueError, match="invalid"):
        ingest.ingest_score(conn, vid, {"hook_strength": 1, "visual_storytelling": 1,
                                        "pacing": 1, "structure": 1, "model": "claude"})
    assert db.get_score(conn, vid) is None


def test_save_analysis_does_not_clear_invalid_mark(temp_db):
    """The storage primitive itself must not be the route around the mark."""
    conn = db.get_connection()
    vid = _invalid_clip(conn)
    db.save_analysis(conn, vid, summary="s", topics_json="[]", hooks_json="{}",
                     style_json="{}", engagement_signals_json="{}", full_json="{}")
    assert validity.is_invalid(conn, vid)
    assert db.get_video(conn, vid)["error_message"] == "zero frames contradiction"


def test_save_analysis_still_marks_ordinary_clip_analyzed(temp_db):
    conn = db.get_connection()
    vid = db.upsert_video(conn, "youtube", "def", "https://youtu.be/def")
    db.save_analysis(conn, vid, summary="s", topics_json="[]", hooks_json="{}",
                     style_json="{}", engagement_signals_json="{}", full_json="{}")
    assert db.get_video(conn, vid)["status"] == "analyzed"
