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

from reel_scout import config, db, ingest, scorer


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
    """The prompt must still tell the model the formula the code actually uses.

    This used to guard against two hand-maintained copies of the weights
    drifting apart. There is now one copy (config.SCORE_WEIGHTS) and scorer
    renders its prompt sentence from it, so that drift class is gone by
    construction. What remains worth pinning is the other half: the sentence
    the model reads must still name every dimension with its live weight — a
    prompt that silently lost the formula would leave the LLM guessing at a
    blend the code then overrides.
    """
    rendered = scorer.weight_formula()
    for dim, weight in ingest._WEIGHTS.items():
        assert "%s*%g" % (dim, weight) in rendered, (
            "the scoring prompt no longer states %s's weight — the model is "
            "being asked to blend on a formula the code does not use" % dim)
    # and the sentence must survive into the prompt the model is actually sent
    assert "{weight_formula}" in scorer._SCORE_PROMPT
    assert rendered in scorer._SCORE_PROMPT.format(
        analysis_json="{}", measured_metrics="", weight_formula=rendered)


def test_ingest_and_scorer_share_one_weight_definition():
    """The single-source invariant itself: no module may hold a private copy."""
    assert ingest._WEIGHTS is config.SCORE_WEIGHTS
    assert ingest._DIMENSIONS is config.SCORE_DIMENSIONS


def test_custom_weights_are_normalised_and_do_not_leave_the_scale():
    """Re-weighting is a read-side view, so it must stay on the stored 0-10 axis.

    Without rescaling, dragging every slider to the top would push `overall`
    past 10 and quietly change what the number means — the "yours vs default"
    comparison the inspector shows would stop being apples-to-apples.
    """
    dims = {"hook_strength": 8.0, "visual_storytelling": 6.0,
            "pacing": 7.0, "structure": 5.0}
    default = ingest.compute_overall(dims)
    assert default == pytest.approx(6.55)

    # all-equal weights => plain mean, still inside 0-10
    assert ingest.compute_overall(dims, {k: 10 for k in dims}) == pytest.approx(6.5)
    # a single dimension carrying all the weight => that dimension's own value
    assert ingest.compute_overall(
        dims, {"hook_strength": 1, "visual_storytelling": 0,
               "pacing": 0, "structure": 0}) == pytest.approx(8.0)
    # degenerate and hostile inputs fall back rather than divide by zero / go negative
    assert ingest.compute_overall(dims, {k: 0 for k in dims}) == pytest.approx(default)
    assert ingest.compute_overall(dims, None) == pytest.approx(default)
    assert ingest.compute_overall(dims, {"hook_strength": "abc"}) == pytest.approx(default)
    assert ingest.compute_overall(
        dims, {"hook_strength": -5, "visual_storytelling": 1,
               "pacing": 0, "structure": 0}) == pytest.approx(6.0)

    # every combination stays on the axis
    for probe in ({"hook_strength": 99}, {"structure": 1000},
                  {"pacing": 0.001, "structure": 0.001}):
        assert 0.0 <= ingest.compute_overall(dims, probe) <= 10.0


def test_custom_weights_never_write_back():
    """Slider exploration must not mutate the shared default."""
    before = dict(config.SCORE_WEIGHTS)
    ingest.compute_overall(
        {"hook_strength": 9.0, "visual_storytelling": 1.0,
         "pacing": 1.0, "structure": 1.0},
        {"hook_strength": 100, "visual_storytelling": 0, "pacing": 0, "structure": 0})
    assert dict(config.SCORE_WEIGHTS) == before


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


# --- structured analysis -----------------------------------------------------

GOOD_ANALYSIS = {
    "summary": "A screen-recording tease for an audio plugin.",
    "topics": ["audio", "plugin"],
    "timeline": [{"timestamp": "0-3s", "event": "question card over a face close-up"}],
    "hook": {"opening_type": "question", "opening_text": "Ready for a big upgrade?",
             "cta_type": "none", "cta_text": ""},
    "style": {"format": "montage", "pacing": "fast", "has_captions": True,
              "has_background_music": True, "text_overlay_count": 2},
    "engagement_signals": {"face_visible": True, "face_count": 1,
                           "emotion": "enthusiastic", "spoken_language": "",
                           "subtitle_language": ""},
    "content_type": "promotional",
    "content_structure": "hook-body-cta",
}


def test_analysis_lands_and_normalized_columns_are_derived():
    """`merge_analysis` needs an LLM; without one this row is simply never written,
    so the 4-beat structure, hook type and CTA type — most of the point — go missing."""
    conn, _ = _temp_db()
    vid = _seed(conn)
    ingest.ingest_analysis(conn, vid, dict(GOOD_ANALYSIS), model="claude")
    row = db.get_analysis(conn, vid)
    assert row["summary"].startswith("A screen-recording tease")
    assert row["opening_type"] == "question"
    assert row["cta_type"] == "none"
    assert row["content_type"] == "promotional"
    assert row["content_structure"] == "hook-body-cta"


def test_analysis_provenance_rides_inside_full_json():
    conn, _ = _temp_db()
    vid = _seed(conn)
    ingest.ingest_analysis(conn, vid, dict(GOOD_ANALYSIS), model="claude-opus-4-8")
    full = json.loads(db.get_analysis(conn, vid)["full_json"])
    assert full["_source"] == "agent:claude-opus-4-8"


def test_analysis_requires_a_summary():
    conn, _ = _temp_db()
    vid = _seed(conn)
    bad = dict(GOOD_ANALYSIS)
    bad["summary"] = "  "
    with pytest.raises(ValueError, match="summary"):
        ingest.ingest_analysis(conn, vid, bad, model="claude")


@pytest.mark.parametrize("section,field,bad", [
    ("hook", "opening_type", "amazing"),
    ("hook", "cta_type", "subscribe"),
    ("style", "format", "cinematic"),
    ("style", "pacing", "medium-fast"),
    ("engagement_signals", "emotion", "excited"),
])
def test_invented_enum_values_are_rejected(section, field, bad):
    """These become normalized columns that `stats`/`patterns` group on — one
    invented value silently adds a one-member category to every aggregate."""
    conn, _ = _temp_db()
    vid = _seed(conn)
    payload = {k: (dict(v) if isinstance(v, dict) else v)
               for k, v in GOOD_ANALYSIS.items()}
    payload[section][field] = bad
    with pytest.raises(ValueError, match="not one of"):
        ingest.ingest_analysis(conn, vid, payload, model="claude")


@pytest.mark.parametrize("field,bad", [
    ("content_type", "vlog"),            # valid for style.format, not content_type
    ("content_structure", "hook-cta"),
])
def test_invented_top_level_enum_values_are_rejected(field, bad):
    conn, _ = _temp_db()
    vid = _seed(conn)
    payload = dict(GOOD_ANALYSIS)
    payload[field] = bad
    with pytest.raises(ValueError, match="not one of"):
        ingest.ingest_analysis(conn, vid, payload, model="claude")


def test_omitted_optional_enums_are_allowed():
    """Partial knowledge is fine; inventing a category is not."""
    conn, _ = _temp_db()
    vid = _seed(conn)
    ingest.ingest_analysis(
        conn, vid, {"summary": "minimal but honest"}, model="claude")
    assert db.get_analysis(conn, vid)["summary"] == "minimal but honest"


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
