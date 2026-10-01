"""merge_analysis retries once when the model's JSON is malformed."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from reel_scout import db
from reel_scout.analyze import merger

_BROKEN = '{"summary": "a "quoted" word", "topics": []}'
_GOOD = json.dumps({"summary": "s", "topics": ["t"]})


def _video():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    vid = db.upsert_video(conn, platform="youtube", platform_id="jr",
                          url="https://youtube.com/shorts/jr", title="T", duration_sec=30.0)
    return conn, path, vid


def _merge(replies):
    conn, path, vid = _video()
    llm = MagicMock()
    llm.complete.side_effect = list(replies)
    try:
        with patch("reel_scout.analyze.merger.get_llm", return_value=llm):
            merger.merge_analysis(conn, vid)
        return llm, db.get_analysis(conn, vid)
    finally:
        conn.close()
        os.unlink(path)


def test_one_malformed_reply_is_retried_and_the_clip_is_kept(capsys):
    llm, analysis = _merge([_BROKEN, _GOOD])
    assert llm.complete.call_count == 2
    assert json.loads(analysis["full_json"])["topics"] == ["t"]
    assert "attempt 1/2" in capsys.readouterr().out


def test_two_malformed_replies_still_fail_loudly():
    with pytest.raises(json.JSONDecodeError):
        _merge([_BROKEN, _BROKEN])


def test_a_good_reply_is_not_called_twice():
    llm, _ = _merge([_GOOD])
    assert llm.complete.call_count == 1


def test_prose_around_the_object_still_parses_first_time():
    llm, analysis = _merge(["Here you go:\n" + _GOOD + "\nThanks"])
    assert llm.complete.call_count == 1
    assert json.loads(analysis["full_json"])["summary"] == "s"
