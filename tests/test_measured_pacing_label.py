"""A measured clip's `style.pacing` comes from its cut rate, not the merge LLM.

`9uqk-3P96V0` (36.7 cuts/min, top quartile of the corpus) was stored as
"medium"; across 220 clips the LLM's label did not track the cut rate (clips it
called "slow" averaged 56.7 cuts/min). The label is mirrored into the
`style_pacing` column that `patterns` / `track` / `stats` aggregate on.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from reel_scout import config, db, scorer
from reel_scout.analyze import merger


@pytest.fixture
def conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    db.init_db(c)
    yield c
    c.close()
    os.unlink(path)


def _video(conn, pid):
    return db.upsert_video(
        conn, platform="youtube", platform_id=pid,
        url="https://youtube.com/shorts/%s" % pid, title="T", duration_sec=36.0)


@pytest.mark.parametrize("cpm,label", [
    (0.0, "slow"), (7.9, "slow"), (8.0, "medium"), (24.9, "medium"),
    (25.0, "fast"), (36.7, "fast"), (None, None),
])
def test_pacing_label_bands(cpm, label):
    assert merger.pacing_label(cpm) == label


def test_merge_overrides_the_llm_label_and_keeps_it_aside(conn):
    vid = _video(conn, "kompan")
    db.save_shot_metrics(conn, vid, shot_count=23, cuts_per_minute=36.67,
                         avg_shot_sec=1.57)
    llm = MagicMock()
    llm.complete.return_value = json.dumps(
        {"summary": "s", "topics": [], "style": {"format": "montage", "pacing": "medium"}})
    with patch("reel_scout.analyze.merger.get_llm", return_value=llm):
        merger.merge_analysis(conn, vid)

    row = db.get_analysis(conn, vid)
    style = json.loads(row["full_json"])["style"]
    assert style["pacing"] == "fast"
    assert style["pacing_llm"] == "medium"
    assert style["pacing_source"] == "measured"
    assert style["format"] == "montage"
    assert row["style_pacing"] == "fast"            # the column the aggregators read
    assert json.loads(row["style_json"])["pacing"] == "fast"


def test_unmeasured_clip_keeps_the_llm_label(conn):
    vid = _video(conn, "nometrics")
    llm = MagicMock()
    llm.complete.return_value = json.dumps(
        {"summary": "s", "topics": [], "style": {"pacing": "slow"}})
    with patch("reel_scout.analyze.merger.get_llm", return_value=llm):
        merger.merge_analysis(conn, vid)

    row = db.get_analysis(conn, vid)
    style = json.loads(row["full_json"])["style"]
    assert style == {"pacing": "slow"}
    assert row["style_pacing"] == "slow"


def test_agreeing_llm_label_is_not_duplicated(conn):
    data = {"measured": {"cuts_per_minute": 30.0}, "style": {"pacing": "fast"}}
    assert merger.apply_measured_pacing(data) is True
    assert "pacing_llm" not in data["style"]


def test_backfill_relabels_an_existing_analysis_once(conn):
    vid = _video(conn, "backfill")
    db.save_analysis(
        conn, vid, summary="s", topics_json="[]", hooks_json="{}",
        style_json=json.dumps({"format": "montage", "pacing": "medium"}),
        engagement_signals_json="{}",
        full_json=json.dumps({"summary": "s",
                              "style": {"format": "montage", "pacing": "medium"}}),
    )
    db.save_shot_metrics(conn, vid, shot_count=23, cuts_per_minute=36.67,
                         avg_shot_sec=1.57)

    merger.backfill_measured(conn, vid)
    row = db.get_analysis(conn, vid)
    assert row["style_pacing"] == "fast"
    first = row["full_json"]
    assert json.loads(first)["style"]["pacing_llm"] == "medium"

    merger.backfill_measured(conn, vid)            # idempotent
    assert db.get_analysis(conn, vid)["full_json"] == first


def test_backfill_seeds_style_from_its_column_when_the_blob_has_none(conn):
    vid = _video(conn, "oldshape")
    db.save_analysis(
        conn, vid, summary="s", topics_json="[]", hooks_json="{}",
        style_json=json.dumps({"format": "talking_head", "pacing": "fast"}),
        engagement_signals_json="{}", full_json=json.dumps({"summary": "s"}),
    )
    db.save_shot_metrics(conn, vid, shot_count=2, cuts_per_minute=3.0,
                         avg_shot_sec=20.0)

    merger.backfill_measured(conn, vid)
    style = json.loads(db.get_analysis(conn, vid)["style_json"])
    assert style["format"] == "talking_head"
    assert style["pacing"] == "slow" and style["pacing_llm"] == "fast"


def test_score_prompt_carries_the_band_and_its_scale():
    block = scorer._measured_block(json.dumps({"measured": {"cuts_per_minute": 36.7}}))
    assert "cut_rhythm_band: fast" in block
    assert "slow < %g" % config.PACING_SLOW_BELOW_CPM in block
    assert scorer._measured_block(json.dumps({"summary": "s"})) == ""
