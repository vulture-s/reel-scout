"""Re-saving a transcript must not hide an analysed clip.

`save_transcript` used to set `videos.status = 'transcribed'` unconditionally.
Every listing that feeds an export -- json, csv, skeleton, storyboard, bundle,
the viewer -- filters on `status = 'analyzed'`, and the only thing that sets it
back is `save_analysis`, which the pipeline skips once an analysis exists. So a
clip whose transcript was re-saved once dropped out of every export for good,
with its analysis still sitting there. Found 2026-10-09 on a real library row
(`696ba50c3c6c4ea1`: analysed 08-10, transcript re-saved 08-15).
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile

from reel_scout import db, validity
from reel_scout.export.json_export import export_json


def _conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _transcript(conn, vid):
    db.save_transcript(conn, vid, language="en", text_full="hi",
                       segments_json="[]", whisper_model="m", duration_sec=1.0)


def _video(conn, pid="a"):
    return db.upsert_video(conn, platform="youtube", platform_id=pid,
                           url="https://y/%s" % pid, title=pid)


def test_a_fresh_clip_still_becomes_transcribed():
    conn, path = _conn()
    try:
        vid = _video(conn)
        _transcript(conn, vid)
        assert db.get_video(conn, vid)["status"] == "transcribed"
    finally:
        conn.close()
        os.unlink(path)


def test_an_analysed_clip_stays_analysed_and_exported():
    conn, path = _conn()
    try:
        vid = _video(conn)
        _transcript(conn, vid)
        db.save_analysis(conn, vid, summary="s", topics_json="[]",
                         hooks_json="{}", style_json="{}",
                         engagement_signals_json="{}",
                         full_json=json.dumps({"summary": "s"}))
        _transcript(conn, vid)  # e.g. a re-transcription after a language fix
        assert db.get_video(conn, vid)["status"] == "analyzed"
        assert export_json(conn, tempfile.mkdtemp()) == 1
    finally:
        conn.close()
        os.unlink(path)


def test_an_invalid_mark_is_not_undone_by_a_transcript():
    conn, path = _conn()
    try:
        vid = _video(conn)
        validity.mark_invalid(conn, vid, "0 keyframes")
        _transcript(conn, vid)
        assert db.get_video(conn, vid)["status"] == validity.INVALID_STATUS
    finally:
        conn.close()
        os.unlink(path)
