"""Agent-produced analysis written back into the DB (the no-local-model path).

The interesting failures here are all silent ones: a score that drifts off the
scorer's scale, a row that loses track of which model produced it, or a clamped
out-of-range value that renders as a legitimate 10. Each gets a test.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from reel_scout import db, ingest, scorer


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _seed(conn, *, frames=3):
    vid = db.upsert_video(
        conn, platform="youtube", platform_id="abc123",
        url="https://youtube.com/shorts/abc123",
        title="Test", duration_sec=20.0,
    )
    db.save_keyframes(conn, vid, [
        {"frame_index": i, "timestamp_sec": float(i * 2),
         "file_path": "/kf/%s/%s_int_%03d.jpg" % (vid, vid, i), "strategy": "interval"}
        for i in range(frames)
    ])
    return vid


# --- the scale must stay shared with the real scorer -------------------------

def test_weights_match_the_scorer_prompt():
    """If scorer's documented formula moves, this must move with it.

    ingest duplicates the weights (scorer keeps them inline, not as a constant),
    so the only thing standing between the two paths and a silent divergence is
    this assertion.
    """
    for dim, weight in ingest._WEIGHTS.items():
        assert "%s*%s" % (dim, weight) in scorer._SCORE_PROMPT, (
            "scorer no longer documents %s*%s — ingest.compute_overall is now "
            "on a different scale than score_video" % (dim, weight))


def test_overall_is_recomputed_and_agent_supplied_value_ignored():
    conn, _ = _temp_db()
    vid = _seed(conn)
    score = ingest.ingest_score(conn, vid, {
        "hook_strength": 8, "visual_storytelling": 6,
        "pacing": 7, "structure": 5,
        "overall": 9.9,                      # deliberately wrong
    }, model="claude")
    # 8*.3 + 6*.25 + 7*.2 + 5*.25 = 2.4 + 1.5 + 1.4 + 1.25 = 6.55
    assert score.overall == 6.55
    assert db.get_score(conn, vid)["overall"] == 6.55


# --- provenance --------------------------------------------------------------

def test_rows_are_stamped_agent_prefixed():
    conn, _ = _temp_db()
    vid = _seed(conn)
    ingest.ingest_score(conn, vid, {
        "hook_strength": 5, "visual_storytelling": 5, "pacing": 5, "structure": 5,
    }, model="claude-opus-4-8")
    assert db.get_score(conn, vid)["model_used"] == "agent:claude-opus-4-8"


def test_provenance_is_not_double_prefixed():
    assert ingest.provenance("agent:x") == "agent:x"


def test_missing_model_is_rejected():
    conn, _ = _temp_db()
    vid = _seed(conn)
    with pytest.raises(ValueError, match="model name"):
        ingest.ingest_score(conn, vid, {
            "hook_strength": 5, "visual_storytelling": 5, "pacing": 5, "structure": 5,
        })


def test_vision_rows_record_backend_and_model():
    conn, _ = _temp_db()
    vid = _seed(conn)
    written, warnings = ingest.ingest_vision(conn, vid, {
        "frames": [{"frame_index": 0, "description": "a hand enters frame"}],
    }, model="claude")
    assert (written, warnings) == (1, [])
    row = conn.execute(
        "SELECT vlm_backend, vlm_model FROM vision_descriptions").fetchone()
    assert row["vlm_backend"] == "agent"
    assert row["vlm_model"] == "agent:claude"


# --- strictness rather than silent coercion ----------------------------------

@pytest.mark.parametrize("bad", [47, -1, "high", None, float("nan")])
def test_out_of_range_scores_raise_instead_of_clamping(bad):
    conn, _ = _temp_db()
    vid = _seed(conn)
    with pytest.raises(ValueError):
        ingest.ingest_score(conn, vid, {
            "hook_strength": bad, "visual_storytelling": 5,
            "pacing": 5, "structure": 5,
        }, model="claude")


def test_missing_dimension_names_what_is_missing():
    conn, _ = _temp_db()
    vid = _seed(conn)
    with pytest.raises(ValueError, match="pacing"):
        ingest.ingest_score(conn, vid, {
            "hook_strength": 5, "visual_storytelling": 5, "structure": 5,
        }, model="claude")


# --- frame addressing --------------------------------------------------------

def test_frames_resolve_by_id_index_basename_and_full_path():
    conn, _ = _temp_db()
    vid = _seed(conn)
    rows = db.get_keyframes(conn, vid)
    full = rows[2]["file_path"]
    specs = [
        {"keyframe_id": rows[0]["id"], "description": "by id"},
        {"frame_index": 1, "description": "by index"},
        {"file": os.path.basename(full), "description": "by basename"},
    ]
    written, warnings = ingest.ingest_vision(conn, vid, {"frames": specs}, model="m")
    assert (written, warnings) == (3, [])

    # and the full path resolves too (overwrites frame 2, still 1 write)
    written, warnings = ingest.ingest_vision(
        conn, vid, {"frames": [{"file": full, "description": "by full path"}]}, model="m")
    assert (written, warnings) == (1, [])


def test_unresolvable_frame_warns_but_batch_continues():
    conn, _ = _temp_db()
    vid = _seed(conn)
    written, warnings = ingest.ingest_vision(conn, vid, {"frames": [
        {"frame_index": 0, "description": "good"},
        {"frame_index": 99, "description": "no such frame"},
        {"description": "no locator at all"},
        {"frame_index": 1, "description": ""},          # empty -> skipped
        {"frame_index": 2, "description": "also good"},
    ]}, model="m")
    assert written == 2
    assert len(warnings) == 3
    assert any("99" in w for w in warnings)


def test_keyframe_id_from_another_video_is_refused():
    conn, _ = _temp_db()
    vid = _seed(conn)
    other = db.upsert_video(
        conn, platform="youtube", platform_id="zzz",
        url="https://youtube.com/shorts/zzz", title="Other", duration_sec=5.0)
    stray = db.save_keyframes(conn, other, [
        {"frame_index": 0, "timestamp_sec": 0.0, "file_path": "/kf/zzz.jpg",
         "strategy": "interval"}])[0]
    written, warnings = ingest.ingest_vision(
        conn, vid, {"frames": [{"keyframe_id": stray, "description": "x"}]}, model="m")
    assert written == 0
    assert "does not belong" in warnings[0]


def test_no_keyframes_points_at_the_fix():
    conn, _ = _temp_db()
    vid = db.upsert_video(
        conn, platform="youtube", platform_id="bare",
        url="https://youtube.com/shorts/bare", title="Bare", duration_sec=5.0)
    with pytest.raises(ValueError, match="skip-vision"):
        ingest.ingest_vision(conn, vid, {"frames": [{"frame_index": 0, "description": "x"}]},
                             model="m")


def test_empty_frames_list_is_rejected():
    conn, _ = _temp_db()
    vid = _seed(conn)
    with pytest.raises(ValueError, match="frames"):
        ingest.ingest_vision(conn, vid, {"frames": []}, model="m")


# --- CLI seam ----------------------------------------------------------------

def test_cli_ingest_score_reads_a_file(temp_db, capsys):
    from reel_scout import cli

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    vid = _seed(conn)
    conn.close()

    payload = {"hook_strength": 9, "visual_storytelling": 8,
               "pacing": 7, "structure": 6, "reasoning": "strong open"}
    path = os.path.join(os.path.dirname(temp_db), "score.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)

    cli.main(["ingest", "score", vid, "--from-json", path, "--model", "claude"])
    out = capsys.readouterr().out
    assert "agent:claude" in out
    # 9*.3 + 8*.25 + 7*.2 + 6*.25 = 2.7 + 2.0 + 1.4 + 1.5 = 7.6
    assert "7.6" in out


def test_show_surfaces_keyframe_ids_and_agent_provenance(temp_db, capsys):
    """`show` is where an agent learns the keyframe ids it must address.

    SKILL.md Step 2b tells the agent to read them from here, so if this output
    loses the ids or the `agent:` stamp, the documented L1 flow breaks.
    """
    from reel_scout import cli

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    vid = _seed(conn, frames=2)
    ids = [r["id"] for r in db.get_keyframes(conn, vid)]
    conn.close()

    cli.main(["show", vid])
    out = capsys.readouterr().out
    assert "Keyframes" in out
    for kf_id in ids:
        assert "id %5d" % kf_id in out
    assert "* = no description yet" in out       # nothing ingested yet
