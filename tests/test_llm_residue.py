"""What is left after #185, and how the rest of the tool treats it (2026-10-14).

#185 stopped `merge_analysis` and `score_video` from writing a failed LLM reply
as data (tests/test_llm_reply_honesty.py). Three things were still open:

* the agent-ingest path (`ingest.ingest_analysis`, CLI `ingest-analysis`, MCP
  `ingest_analysis`) still accepted the old carcass verbatim -- it has a
  non-empty `summary`, so the one required-field check passed;
* `reel-scout show` raised TypeError on any score row with a NULL column,
  which is what the old scorer wrote for a NaN reply;
* corpora that ran before #185 still hold the rows it would now refuse, and
  nothing could list them without writing to the database.

The aggregate tests pin the other half of the contract: a NULL is skipped,
never averaged in as 0.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import types

import pytest

from reel_scout import cli, config, db, ingest, patterns, stats, validity

CARCASS = {"summary": "{\n", "topics": [], "error": "failed to parse JSON"}


def _conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _video(conn, pid, uploader="C"):
    return db.upsert_video(conn, platform="youtube", platform_id=pid,
                           url="https://y/%s" % pid, title="title-%s" % pid,
                           uploader=uploader)


def _analysis(conn, vid, full):
    db.save_analysis(conn, vid, summary=str(full.get("summary", "")),
                     topics_json="[]", hooks_json="{}", style_json="{}",
                     engagement_signals_json="{}", full_json=json.dumps(full))


def _score(conn, vid, dims, overall, model="m"):
    conn.execute(
        "INSERT INTO scores (video_id, hook_strength, visual_storytelling, "
        "pacing, structure, overall, model_used) VALUES (?,?,?,?,?,?,?)",
        (vid,) + tuple(dims) + (overall, model))
    conn.commit()


# --- ingest refuses the carcass ---------------------------------------------

def test_ingest_analysis_refuses_the_parse_failure_carcass(temp_db):
    conn = _conn(temp_db)
    try:
        vid = _video(conn, "carcass")
        with pytest.raises(ValueError, match="error="):
            ingest.ingest_analysis(conn, vid, dict(CARCASS), model="agent")
        assert db.get_analysis(conn, vid) is None
    finally:
        conn.close()


def test_ingest_analysis_still_stores_a_real_payload(temp_db):
    # The guard keys on a truthy `error`, so an explicit empty one is harmless.
    conn = _conn(temp_db)
    try:
        vid = _video(conn, "real")
        ingest.ingest_analysis(conn, vid, {"summary": "a real summary",
                                           "topics": ["x"], "error": None},
                               model="agent")
        row = db.get_analysis(conn, vid)
        assert row is not None and row["summary"] == "a real summary"
    finally:
        conn.close()


# --- show does not crash on NULL --------------------------------------------

def test_show_prints_dash_for_null_score_columns(temp_db, capsys):
    conn = _conn(temp_db)
    vid = _video(conn, "nul")
    _score(conn, vid, (None, 7.0, None, None), None)
    conn.close()

    cli._cmd_show(types.SimpleNamespace(video_id=vid))
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if "Overall:" in l][0]
    assert "Overall: —" in line
    assert "Visual: 7.0" in line
    # Missing is shown as missing, not as a zero.
    assert "0.0" not in line.replace("7.0", "")


# --- aggregates skip NULL, never average it as 0 ----------------------------

def _null_and_real(path, other_overall):
    conn = _conn(path)
    try:
        for pid, overall in (("real", 8.0), ("other", other_overall)):
            vid = _video(conn, pid)
            _analysis(conn, vid, {"summary": "s"})
            dims = (8.0,) * 4 if pid == "real" else (other_overall,) * 4
            _score(conn, vid, dims, overall)
        return stats.compute_stats(conn), patterns.compute_patterns(conn, "C")
    finally:
        conn.close()


def test_stats_and_patterns_skip_null_instead_of_counting_it_as_zero(temp_db):
    s, p = _null_and_real(temp_db, None)
    agg = s["score_aggregates"]
    for col in ("overall", "hook_strength", "pacing"):
        assert agg[col]["avg"] == 8.0
        assert agg[col]["count"] == 1
    # The NULL row is not on either side of the median split.
    assert p["high_vs_low"]["scored"] == 1


def test_the_null_assertion_above_can_fail(temp_db):
    # Same fixture with a 0.0 where the NULL was: the average halves. If this
    # ever reads 8.0 the test above has stopped measuring anything.
    s, p = _null_and_real(temp_db, 0.0)
    assert s["score_aggregates"]["overall"]["avg"] == 4.0
    assert s["score_aggregates"]["overall"]["count"] == 2
    assert p["high_vs_low"]["scored"] == 2


# --- the read-only residue audit --------------------------------------------

def _seed_residue(path):
    conn = _conn(path)
    try:
        bad = _video(conn, "bad")
        _analysis(conn, bad, CARCASS)
        _score(conn, bad, (0.0,) * 4, 0.0)

        nul = _video(conn, "nul")
        _analysis(conn, nul, {"summary": "fine"})
        _score(conn, nul, (6.0, None, 6.0, 6.0), None)

        ok = _video(conn, "ok")
        _analysis(conn, ok, {"summary": "fine"})
        _score(conn, ok, (7.0,) * 4, 7.0)

        # A real dimension at 0.0 next to non-zero ones is not the signature.
        low = _video(conn, "low")
        _analysis(conn, low, {"summary": "fine"})
        _score(conn, low, (0.0, 3.0, 2.0, 1.0), 1.5)

        return {"bad": bad, "nul": nul, "ok": ok, "low": low}
    finally:
        conn.close()


def test_scan_llm_residue_buckets(temp_db):
    ids = _seed_residue(temp_db)
    conn = _conn(temp_db)
    try:
        r = validity.scan_llm_residue(conn)
    finally:
        conn.close()

    assert [h["id"] for h in r["bad_analyses"]] == [ids["bad"]]
    assert "failed to parse JSON" in r["bad_analyses"][0]["reason"]
    assert r["bad_analyses"][0]["scored"] is True

    assert [h["id"] for h in r["null_scores"]] == [ids["nul"]]
    assert r["null_scores"][0]["missing"] == ["visual_storytelling", "overall"]

    assert [h["id"] for h in r["all_zero_scores"]] == [ids["bad"]]


@pytest.mark.parametrize("blob,expect", [
    ('{"summary": "s"}', None),
    ('{"summary": "s", "error": ""}', None),
    ('{"summary": "s", "error": "boom"}', "error="),
    ("[1, 2]", "not an object"),
    ("{not json", "not valid JSON"),
    ("", "empty"),
    (None, "empty"),
])
def test_analysis_defect_classification(blob, expect):
    got = validity._analysis_defect(blob)
    if expect is None:
        assert got is None
    else:
        assert got is not None and expect in got


def _digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def test_check_llm_residue_cli_reports_and_writes_nothing(temp_db, capsys):
    ids = _seed_residue(temp_db)
    before = _digest(temp_db)
    mtime = os.stat(temp_db).st_mtime_ns

    cli._cmd_db(types.SimpleNamespace(db_command="check-llm-residue"))
    out = capsys.readouterr().out

    assert "opened read-only" in out
    assert "[1] analyses stored from an unusable merge reply: 1" in out
    assert "[2] scores with a NULL dimension: 1" in out
    assert "[3] scores with all four dimensions exactly 0.0" in out
    assert ids["bad"] in out and ids["nul"] in out
    assert ids["ok"] not in out and ids["low"] not in out
    assert "nothing was written" in out

    assert _digest(temp_db) == before
    assert os.stat(temp_db).st_mtime_ns == mtime


def test_check_llm_residue_cli_does_not_create_a_missing_db(temp_db, monkeypatch,
                                                            capsys):
    missing = os.path.join(os.path.dirname(temp_db), "nope.db")
    monkeypatch.setattr(config, "DB_PATH", missing)
    with pytest.raises(SystemExit) as exc:
        cli._cmd_db(types.SimpleNamespace(db_command="check-llm-residue"))
    assert exc.value.code == 2
    assert not os.path.exists(missing)
