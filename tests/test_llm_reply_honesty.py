"""A model reply that is not the answer must not be stored as one (2026-10-09).

Two producers turned an unusable LLM reply into a real-looking row:

* `scorer.score_video` took `float(data.get(dim, 0))` for every dimension, so a
  refusal or a truncated reply became 0.0 x4 and a reply on the wrong scale
  (47, -3, 85, NaN) went straight into `scores` -- `overall` 16.95, 77.75 or
  NULL. The agent-ingest path has rejected all of these since `ingest._as_score`
  existed; the local-model path never went through the same gate.
* `merger.merge_analysis` stored a reply with no JSON object in it as
  `{"summary": <raw text>, "error": ...}`. The commonest way to get one is the
  reply being cut off at MERGE_MAX_TOKENS, which is exactly the case the retry
  exists for -- and it was never retried. Once stored, the pipeline skips the
  merge on every later run ("already done"), so the poison row is permanent.

Both now raise, and write nothing. A NULL is visibly missing; a 0.0 is averaged.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from reel_scout import db
from reel_scout.analyze import merger
from reel_scout.scorer import score_video


def _conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    vid = db.upsert_video(conn, platform="youtube", platform_id="honest",
                          url="https://youtube.com/shorts/honest", title="T",
                          duration_sec=30.0)
    return conn, path, vid


def _score(reply):
    conn, path, vid = _conn()
    db.save_analysis(conn, vid, summary="s", topics_json="[]", hooks_json="{}",
                     style_json="{}", engagement_signals_json="{}",
                     full_json='{"summary": "s"}')
    llm = MagicMock()
    llm.complete.return_value = reply
    llm.model = "m"
    try:
        with patch("reel_scout.scorer.get_llm", return_value=llm):
            try:
                return score_video(conn, vid), db.get_score(conn, vid)
            except ValueError as exc:
                return exc, db.get_score(conn, vid)
    finally:
        conn.close()
        os.unlink(path)


_FULL = {"hook_strength": 7, "visual_storytelling": 6, "pacing": 5, "structure": 8}


@pytest.mark.parametrize("reply", [
    "I cannot score this video.",                               # refusal
    '{"hook_strength": 7.5, "visual_storytelling": 6',          # truncated
    json.dumps({k: v for k, v in _FULL.items() if k != "structure"}),  # missing
    json.dumps(dict(_FULL, hook_strength=47)),                  # above 10
    json.dumps(dict(_FULL, visual_storytelling=-3)),            # below 0
    json.dumps({"hook_strength": 85, "visual_storytelling": 70,
                "pacing": 80, "structure": 75}),                # 100-point scale
    '{"hook_strength": NaN, "visual_storytelling": 6, "pacing": 5, "structure": 8}',
    json.dumps(dict(_FULL, pacing="fast")),                     # not a number
    "[1, 2, 3]",                                                # not an object
])
def test_an_unusable_score_reply_raises_and_writes_nothing(reply):
    result, row = _score(reply)
    assert isinstance(result, ValueError), result
    assert row is None, "a score row was written from %r" % reply


def test_a_good_score_reply_still_scores():
    result, row = _score(json.dumps(dict(_FULL, overall=9.9, reasoning="ok")))
    assert not isinstance(result, Exception)
    assert row["hook_strength"] == 7.0
    assert row["overall"] == pytest.approx(6.6)
    assert not math.isnan(row["overall"])


def test_numeric_strings_in_range_are_accepted():
    result, row = _score(json.dumps({k: str(v) for k, v in _FULL.items()}))
    assert not isinstance(result, Exception)
    assert row["structure"] == 8.0


def _merge(replies):
    conn, path, vid = _conn()
    llm = MagicMock()
    llm.complete.side_effect = list(replies)
    try:
        with patch("reel_scout.analyze.merger.get_llm", return_value=llm):
            try:
                merger.merge_analysis(conn, vid)
                err = None
            except ValueError as exc:     # JSONDecodeError is a ValueError
                err = exc
        return llm, err, db.get_analysis(conn, vid)
    finally:
        conn.close()
        os.unlink(path)


_TRUNCATED = '{"summary": "s", "topics": ["a"], "hook": {"opening_type": "question"'
_GOOD = json.dumps({"summary": "s", "topics": ["t"]})


@pytest.mark.parametrize("bad", [
    _TRUNCATED,
    "I'm sorry, I cannot analyze this video.",
    '[{"summary": "s"}]',
])
def test_a_merge_reply_with_no_usable_object_is_retried(bad):
    llm, err, analysis = _merge([bad, _GOOD])
    assert err is None
    assert llm.complete.call_count == 2
    assert json.loads(analysis["full_json"])["topics"] == ["t"]


@pytest.mark.parametrize("bad", [
    _TRUNCATED,
    "I'm sorry, I cannot analyze this video.",
    '[{"summary": "s"}]',
])
def test_two_unusable_merge_replies_store_no_analysis(bad):
    llm, err, analysis = _merge([bad, bad])
    assert isinstance(err, ValueError)
    assert analysis is None, "a carcass analysis was stored"
