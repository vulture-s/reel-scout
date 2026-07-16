"""Local-file entry to the analyze pipeline (roadmap 5B).

The platform-lockout insurance path: `analyze <local-path>` must register a
video row from a file on disk so Steps 2-5 run unchanged, without fabricating a
duration when ffprobe can't read the file.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

from reel_scout import db
from reel_scout.analyze import pipeline


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _temp_file(content: bytes = b"not a real video") -> str:
    fd, path = tempfile.mkstemp(suffix=".mp4")
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return path


def test_is_local_source_distinguishes_paths_from_urls():
    path = _temp_file()
    try:
        assert pipeline._is_local_source(path) is True
        assert pipeline._is_local_source("https://youtube.com/shorts/abc") is False
        assert pipeline._is_local_source("/nope/does/not/exist.mp4") is False
    finally:
        os.unlink(path)


def test_normalize_source_absolutizes_local_and_passes_urls():
    path = _temp_file()
    try:
        rel = os.path.relpath(path)
        assert pipeline._normalize_source(rel) == os.path.abspath(path)
        url = "https://tiktok.com/@x/video/1"
        assert pipeline._normalize_source(url) == url
    finally:
        os.unlink(path)


def test_probe_duration_returns_none_not_fabricated_fallback():
    # A non-media file must probe to None — never a 60.0 lie written to the DB.
    path = _temp_file()
    try:
        assert pipeline._probe_duration(path) is None
    finally:
        os.unlink(path)


def test_register_local_video_shapes_row_like_a_download():
    conn, db_path = _temp_db()
    path = _temp_file(b"some bytes here")
    try:
        vid = pipeline._register_local_video(conn, path)
        row = db.get_video(conn, vid)
        abspath = os.path.abspath(path)
        assert row["platform"] == "local"
        assert row["url"] == abspath
        assert row["file_path"] == abspath
        assert row["duration_sec"] is None          # no fabricated duration
        assert row["file_size_bytes"] == len(b"some bytes here")
        assert row["title"] == os.path.splitext(os.path.basename(path))[0]
        # url is the seam the pipeline keys on for skip-download
        assert db.get_video_by_url(conn, abspath)["id"] == vid
    finally:
        conn.close()
        os.unlink(db_path)
        os.unlink(path)


def test_register_local_video_is_content_addressed():
    # Same content at two paths → same video_id (dedup); different content → not.
    conn, db_path = _temp_db()
    a = _temp_file(b"identical content")
    b = _temp_file(b"identical content")
    c = _temp_file(b"different content")
    try:
        id_a = pipeline._register_local_video(conn, a)
        id_b = pipeline._register_local_video(conn, b)
        id_c = pipeline._register_local_video(conn, c)
        assert id_a == id_b
        assert id_a != id_c
    finally:
        conn.close()
        os.unlink(db_path)
        for p in (a, b, c):
            os.unlink(p)


def test_process_single_missing_local_file_raises_clear_error():
    conn, db_path = _temp_db()
    try:
        # A path-looking source that doesn't exist should say so plainly rather
        # than fall through to the crawler's opaque "Unsupported platform".
        try:
            pipeline._process_single(conn, "/no/such/file.mp4", pipeline.PipelineOptions())
            assert False, "expected FileNotFoundError"
        except FileNotFoundError as e:
            assert "Local file not found" in str(e)
    finally:
        conn.close()
        os.unlink(db_path)
