"""Interactive single-clip inspector web app (player + waveform + filmstrip)."""
from __future__ import annotations

import array
import json
import os
import sqlite3
import threading
import urllib.request

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
          text_full="Hungry right now? Watch this. Come try it.", video_file=None):
    vid = db.upsert_video(conn, platform="instagram", platform_id="xyz",
                          url="https://www.instagram.com/reel/xyz/", title="Fried Chicken",
                          uploader="waffle", duration_sec=duration_sec,
                          file_path=video_file)
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


def _make_video_file(name="clip.mp4", body=b"0123456789" * 1000):
    os.makedirs(config.VIDEOS_DIR, exist_ok=True)
    path = os.path.join(config.VIDEOS_DIR, name)
    with open(path, "wb") as f:
        f.write(body)
    return name, path, body


# --- data assembly ---

def test_build_inspect_view_parses_segments(temp_db):
    conn = _conn(temp_db)
    try:
        vid = _seed(conn)
        view = inspector.build_inspect_view(conn, vid)
        assert view is not None
        assert len(view["segments"]) == 3
        assert view["segments"][0]["text"] == "Hungry right now?"
        assert view["has_video"] is False  # no file_path
        assert view["language"] == "en"
    finally:
        conn.close()


def test_build_inspect_view_detects_video_file(temp_db):
    name, _, _ = _make_video_file()
    conn = _conn(temp_db)
    try:
        vid = _seed(conn, video_file=name)
        view = inspector.build_inspect_view(conn, vid)
        assert view["has_video"] is True
    finally:
        conn.close()


def test_build_inspect_view_unknown(temp_db):
    conn = _conn(temp_db)
    try:
        assert inspector.build_inspect_view(conn, "deadbeef") is None
    finally:
        conn.close()


def test_duration_falls_back_when_video_duration_missing(temp_db):
    kf = os.path.join(config.KEYFRAMES_DIR, "kf.jpg")
    os.makedirs(config.KEYFRAMES_DIR, exist_ok=True)
    _tiny_jpeg(kf)
    conn = _conn(temp_db)
    try:
        vid = _seed(conn, kf_path=kf, duration_sec=None)
        view = inspector.build_inspect_view(conn, vid)
        assert abs(view["duration"] - 8.4) < 1e-6  # last segment/keyframe
    finally:
        conn.close()


# --- waveform ---

def test_compute_waveform_peaks_normalized(temp_db, monkeypatch):
    pcm = array.array("h", [100, -200, 30000, -32768]).tobytes()

    class _R:
        returncode = 0
        stdout = pcm

    monkeypatch.setattr(inspector.subprocess, "run", lambda *a, **k: _R())
    peaks = inspector.compute_waveform("whatever.mp4", bins=2)
    assert len(peaks) == 2
    assert abs(peaks[0] - 200 / 32768.0) < 1e-6
    assert abs(peaks[1] - 1.0) < 1e-6


def test_compute_waveform_ffmpeg_failure_returns_none(temp_db, monkeypatch):
    class _R:
        returncode = 1
        stdout = b""

    monkeypatch.setattr(inspector.subprocess, "run", lambda *a, **k: _R())
    assert inspector.compute_waveform("x.mp4", bins=8) is None


def test_waveform_payload_flat_without_file(temp_db):
    conn = _conn(temp_db)
    try:
        vid = _seed(conn)  # no video file
        payload = inspector._waveform_payload(conn, vid, bins=16)
        assert payload["bins"] == 16
        assert payload["peaks"] == [0.0] * 16
    finally:
        conn.close()


# --- rendering ---

def test_render_has_player_waveform_filmstrip(temp_db):
    name, _, _ = _make_video_file()
    kf = os.path.join(config.KEYFRAMES_DIR, "kf.jpg")
    os.makedirs(config.KEYFRAMES_DIR, exist_ok=True)
    _tiny_jpeg(kf)
    conn = _conn(temp_db)
    try:
        vid = _seed(conn, kf_path=kf, video_file=name)
        page = inspector.render_inspector(inspector.build_inspect_view(conn, vid))
        assert '<video id="player"' in page and "/api/stream/%s" % vid in page
        assert 'id="wf"' in page and 'id="wfsvg"' in page          # waveform
        assert 'class="strip"' in page and 'class="cell"' in page  # filmstrip
        assert 'class="seg"' in page and 'data-start="0.000"' in page
        assert 'id="setin"' in page and 'id="srt"' in page         # in/out + export
        assert '"reference, not authority"' in page or "reference, not authority" in page
        assert '"hasVideo": true' in page or '"hasVideo":true' in page
        assert page.count("<html") == 1 and page.count("</html>") == 1
    finally:
        conn.close()


def test_render_no_video_shows_note(temp_db):
    conn = _conn(temp_db)
    try:
        vid = _seed(conn)  # no file
        page = inspector.render_inspector(inspector.build_inspect_view(conn, vid))
        assert "video file not on disk" in page
        assert '<video id="player"' not in page
    finally:
        conn.close()


# --- server ---

def test_server_serves_inspect_waveform_stream_keyframe(temp_db):
    name, _, body = _make_video_file()
    kf = os.path.join(config.KEYFRAMES_DIR, "kf.jpg")
    os.makedirs(config.KEYFRAMES_DIR, exist_ok=True)
    _tiny_jpeg(kf)
    conn = _conn(temp_db)
    vid = _seed(conn, kf_path=kf, video_file=name)
    kf_id = db.get_keyframes(conn, vid)[0]["id"]
    conn.close()

    httpd = inspector.make_inspect_server(port=0, default_id=vid)
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        # inspect page
        page = urllib.request.urlopen(base + "/inspect/%s" % vid, timeout=5).read().decode()
        assert '<video id="player"' in page
        # root serves the default clip
        root = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "reel-scout inspect" in root
        # waveform json (no ffmpeg needed: real tiny file may fail decode -> flat)
        wf = json.loads(urllib.request.urlopen(base + "/api/waveform/%s?bins=32" % vid, timeout=5).read())
        assert wf["bins"] == 32 and len(wf["peaks"]) == 32
        # keyframe image
        img = urllib.request.urlopen(base + "/keyframe/%s" % kf_id, timeout=5)
        assert img.headers["Content-Type"] == "image/jpeg"
        # unknown clip -> 404
        try:
            urllib.request.urlopen(base + "/inspect/nope", timeout=5)
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_stream_honors_range(temp_db):
    name, _, body = _make_video_file(body=b"ABCDEFGHIJ" * 500)  # 5000 bytes
    conn = _conn(temp_db)
    vid = _seed(conn, video_file=name)
    conn.close()

    httpd = inspector.make_inspect_server(port=0, default_id=vid)
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        # full request advertises range support
        full = urllib.request.urlopen(base + "/api/stream/%s" % vid, timeout=5)
        assert full.headers["Accept-Ranges"] == "bytes"
        assert len(full.read()) == len(body)
        # partial request
        req = urllib.request.Request(base + "/api/stream/%s" % vid,
                                     headers={"Range": "bytes=0-99"})
        resp = urllib.request.urlopen(req, timeout=5)
        assert resp.status == 206
        assert resp.headers["Content-Range"] == "bytes 0-99/%d" % len(body)
        chunk = resp.read()
        assert len(chunk) == 100 and chunk == body[:100]
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_parse_range_edge_cases():
    assert inspector._parse_range(None, 1000) is None
    assert inspector._parse_range("bytes=0-99", 1000) == (0, 99)
    assert inspector._parse_range("bytes=100-", 1000) == (100, 999)
    assert inspector._parse_range("bytes=-100", 1000) == (900, 999)  # suffix
    assert inspector._parse_range("bytes=500-4000", 1000) == (500, 999)  # clamp end
    assert inspector._parse_range("bytes=900-100", 1000) is None  # start>end


def test_cmd_inspect_unknown_ref_exits(temp_db, capsys):
    class Args:
        video = "nomatch"
        host = "127.0.0.1"
        port = 0
        open_browser = False

    import pytest
    from reel_scout.cli import _cmd_inspect
    with pytest.raises(SystemExit):
        _cmd_inspect(Args())
    assert "No video matches" in capsys.readouterr().out


def test_back_link_only_when_there_is_an_index(temp_db):
    """`view` mode: "/" is the library, so offer a way back. `inspect <id>` pins
    "/" to this very page, so a back link there would loop to itself."""
    import sqlite3 as _sq
    import threading
    import urllib.request

    conn = _sq.connect(temp_db)
    conn.row_factory = _sq.Row
    vid = _seed(conn)
    conn.close()

    for default_id, expect_back in ((None, True), (vid, False)):
        httpd = inspector.make_inspect_server(port=0, default_id=default_id)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            page = urllib.request.urlopen(
                "http://127.0.0.1:%d/inspect/%s" % (port, vid), timeout=5).read().decode()
            assert ('class="back"' in page) is expect_back, (
                "default_id=%r should%s render a back link" % (
                    default_id, "" if expect_back else " not"))
        finally:
            httpd.shutdown()
            httpd.server_close()
