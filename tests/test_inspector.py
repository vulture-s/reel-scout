"""Interactive single-clip inspector (self-contained, time-synced HTML)."""
from __future__ import annotations

import json
import os
import sqlite3

from reel_scout import config, db, inspector


def _tiny_jpeg(path: str) -> None:
    data = bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300"
        + "08060607060508070707090909"
    ) + b"\xff\xd9"
    with open(path, "wb") as f:
        f.write(data)


_SEGMENTS = [
    {"start": 0.0, "end": 2.4, "text": "Hungry right now?", "confidence": 0.9},
    {"start": 2.4, "end": 6.0, "text": "Watch this.", "confidence": 0.9},
    {"start": 6.0, "end": 8.4, "text": "Come try it.", "confidence": 0.9},
]

_FULL = {
    "summary": "A punchy fried-chicken reel.",
    "topics": ["food"],
    "content_structure": "hook-body-cta",
    "hook": {"opening_type": "question", "opening_text": "Hungry?",
             "cta_type": "visit", "cta_text": "come try it"},
    "style": {"format": "montage", "pacing": "fast"},
}


def _seed(conn, kf_path=None, duration_sec=8.4, segments=None, with_score=True,
          text_full="Hungry right now? Watch this. Come try it."):
    vid = db.upsert_video(conn, platform="instagram", platform_id="xyz",
                          url="https://www.instagram.com/reel/xyz/", title="Fried Chicken",
                          uploader="waffle", duration_sec=duration_sec)
    db.save_transcript(
        conn, vid, language="en", text_full=text_full,
        segments_json=json.dumps(_SEGMENTS if segments is None else segments),
        whisper_model="x", duration_sec=duration_sec or 0.0)
    if with_score:
        conn.execute("INSERT INTO scores (video_id, hook_strength, visual_storytelling, "
                     "pacing, structure, overall, reasoning) VALUES (?,?,?,?,?,?,?)",
                     (vid, 8.0, 7.0, 9.0, 6.5, 7.6, "strong open, weak close"))
    if kf_path:
        db.save_keyframes(conn, vid, [
            {"frame_index": 0, "timestamp_sec": 0.5, "file_path": kf_path, "strategy": "scene"},
            {"frame_index": 1, "timestamp_sec": 7.9, "file_path": kf_path, "strategy": "scene"},
        ])
        first = db.get_keyframes(conn, vid)[0]
        conn.execute("INSERT INTO vision_descriptions (keyframe_id, description, "
                     "text_in_frame, objects_json, vlm_backend, vlm_model) VALUES (?,?,?,?,?,?)",
                     (first["id"], "close-up of fried chicken", "SO GOOD", "[]", "ollama", "x"))
    db.save_analysis(conn, vid, summary=_FULL["summary"], topics_json=json.dumps(_FULL["topics"]),
                     hooks_json=json.dumps(_FULL["hook"]), style_json=json.dumps(_FULL["style"]),
                     engagement_signals_json="{}", full_json=json.dumps(_FULL))
    conn.commit()
    return vid


def _conn(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    return conn


def test_build_inspect_view_parses_segments(temp_db):
    conn = _conn(temp_db)
    try:
        vid = _seed(conn)
        view = inspector.build_inspect_view(conn, vid)
        assert view is not None
        assert len(view["segments"]) == 3
        assert view["segments"][0]["text"] == "Hungry right now?"
        assert view["segments"][0]["start"] == 0.0
        assert view["language"] == "en"
    finally:
        conn.close()


def test_build_inspect_view_unknown_video(temp_db):
    conn = _conn(temp_db)
    try:
        assert inspector.build_inspect_view(conn, "deadbeef") is None
    finally:
        conn.close()


def test_duration_falls_back_when_video_duration_missing(temp_db):
    """IG videos often have duration_sec None/0 (yt-dlp gives no duration); the
    timeline must still scale off the last segment/keyframe timestamp."""
    kf = os.path.join(config.KEYFRAMES_DIR, "kf.jpg")
    os.makedirs(config.KEYFRAMES_DIR, exist_ok=True)
    _tiny_jpeg(kf)
    conn = _conn(temp_db)
    try:
        vid = _seed(conn, kf_path=kf, duration_sec=None)
        view = inspector.build_inspect_view(conn, vid)
        # last keyframe at 7.9, last segment ends 8.4 -> duration 8.4
        assert abs(view["duration"] - 8.4) < 1e-6
    finally:
        conn.close()


def test_render_has_time_synced_data_attributes(temp_db):
    kf = os.path.join(config.KEYFRAMES_DIR, "kf.jpg")
    os.makedirs(config.KEYFRAMES_DIR, exist_ok=True)
    _tiny_jpeg(kf)
    conn = _conn(temp_db)
    try:
        vid = _seed(conn, kf_path=kf)
        html = inspector.render_inspector(inspector.build_inspect_view(conn, vid))
        # segments carry start/end for the JS sync
        assert 'class="seg"' in html and 'data-start="0.000"' in html
        # keyframes carry a timestamp; timeline carries ticks + spans
        assert 'figure class="kf"' in html and 'data-ts=' in html
        assert 'class="tick"' in html and 'class="span"' in html
        # self-contained: base64 keyframe embedded, inline script present
        assert "data:image/jpeg;base64," in html
        assert "getElementById('scrub')" in html
        # honesty line preserved from the viewer
        assert "reference, not authority" in html
        # single well-formed document
        assert html.count("<html") == 1 and html.count("</html>") == 1
    finally:
        conn.close()


def test_render_flat_transcript_when_no_segment_timing(temp_db):
    """Segments absent but full text present -> flat transcript, not 'No transcript.'"""
    conn = _conn(temp_db)
    try:
        vid = _seed(conn, kf_path=None, segments=[], with_score=False)
        html = inspector.render_inspector(inspector.build_inspect_view(conn, vid))
        assert "transcript-flat" in html
        assert "Watch this." in html
        assert "class=\"seg\"" not in html  # no per-segment rows
    finally:
        conn.close()


def test_render_degrades_without_transcript_or_keyframes(temp_db):
    conn = _conn(temp_db)
    try:
        vid = _seed(conn, kf_path=None, segments=[], with_score=False, text_full="")
        view = inspector.build_inspect_view(conn, vid)
        html = inspector.render_inspector(view)
        assert "No keyframes." in html
        assert "No transcript." in html
        # no score section, no crash
        assert "Craft scores" not in html
        assert html.startswith("<!doctype html>")
    finally:
        conn.close()


def test_cmd_inspect_writes_file_by_prefix(temp_db, capsys, tmp_path):
    conn = _conn(temp_db)
    vid = _seed(conn)
    conn.close()

    out = str(tmp_path / "insp.html")

    class Args:
        video = vid[:6]  # unique prefix
        output = out
        open_browser = False

    from reel_scout.cli import _cmd_inspect
    _cmd_inspect(Args())
    assert os.path.exists(out)
    with open(out, encoding="utf-8") as f:
        assert "reel-scout inspect" in f.read()
    assert "Wrote inspector" in capsys.readouterr().out


def test_cmd_inspect_unknown_ref_exits(temp_db, capsys):
    class Args:
        video = "nomatch"
        output = None
        open_browser = False

    from reel_scout.cli import _cmd_inspect
    import pytest
    with pytest.raises(SystemExit):
        _cmd_inspect(Args())
    assert "No video matches" in capsys.readouterr().out
