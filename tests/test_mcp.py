from __future__ import annotations

import json
import os
import sqlite3
import shutil
from io import StringIO
from typing import Any

import pytest

from reel_scout import config, db
from reel_scout.mcp import server, tools

from .conftest import TMP_ROOT


def _parse_result(result: Any) -> Any:
    return json.loads(result["content"][0]["text"])


#: Every tool the server is supposed to expose. A set rather than a count so a
#: failure names the tool that went missing instead of just the arithmetic.
EXPECTED_TOOLS = {
    "crawl",
    "analyze",
    "list_videos",
    "show_video",
    "keyframes",
    "export",
    "patterns",
    "inspire",
    "research",
}


def test_list_tools_count():
    assert {t["name"] for t in tools.list_tools()} == EXPECTED_TOOLS


def test_every_listed_tool_has_a_handler():
    """`list_tools` and the handler table are separate structures that nothing
    keeps in agreement: a tool missing from the table answers "Unknown tool",
    one missing from the list is invisible but callable. Both directions."""
    assert {t["name"] for t in tools.list_tools()} == set(tools._HANDLERS)


def test_list_tools_schema():
    tool_defs = tools.list_tools()
    for tool_def in tool_defs:
        assert "name" in tool_def
        assert "description" in tool_def
        assert "inputSchema" in tool_def


def test_call_list_videos_empty(temp_db):
    result = tools.call_tool("list_videos", {})
    assert "isError" not in result
    assert _parse_result(result) == []


def test_call_patterns_requires_channel(temp_db):
    assert tools.call_tool("patterns", {}).get("isError")


def test_call_patterns_reads_channel(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    vid = db.upsert_video(conn, platform="youtube", platform_id="mp",
                          url="https://youtube.com/shorts/mp", uploader="Chan", duration_sec=20.0)
    db.save_analysis(conn, vid, summary="s", topics_json="[]", hooks_json="{}",
                     style_json="{}", engagement_signals_json="{}",
                     full_json=json.dumps({"content_structure": "listicle",
                                           "hook": {"opening_type": "question"}}))
    conn.commit()
    conn.close()
    result = tools.call_tool("patterns", {"channel": "Chan"})
    assert "isError" not in result
    assert _parse_result(result)["total_videos"] == 1


def test_call_inspire(temp_db):
    from unittest.mock import MagicMock, patch
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    vid = db.upsert_video(conn, platform="youtube", platform_id="mi",
                          url="https://youtube.com/shorts/mi", title="T")
    db.save_analysis(conn, vid, summary="s", topics_json="[]", hooks_json="{}",
                     style_json="{}", engagement_signals_json="{}",
                     full_json=json.dumps({"summary": "s"}))
    conn.commit()
    conn.close()
    mock_llm = MagicMock()
    mock_llm.complete.return_value = json.dumps({"titles": ["A"]})
    with patch("reel_scout.inspire.get_llm", return_value=mock_llm):
        result = tools.call_tool("inspire", {"based_on": vid})
    assert "isError" not in result
    assert _parse_result(result)["titles"] == ["A"]


def test_call_research_mocked(temp_db):
    from unittest.mock import patch
    with patch("reel_scout.research.run_research",
               return_value={"niche": "coffee", "channels": {}}) as rr:
        result = tools.call_tool(
            "research", {"niche": "coffee", "channels": ["https://y/c"], "analyze": False})
    rr.assert_called_once()
    assert "isError" not in result
    assert _parse_result(result)["niche"] == "coffee"


def test_call_research_rejects_non_array_channels(temp_db):
    # A string 'channels' would otherwise be iterated char-by-char downstream.
    result = tools.call_tool("research", {"niche": "x", "channels": "abc"})
    assert result.get("isError")


def test_call_show_video_not_found(temp_db):
    result = tools.call_tool("show_video", {"video_id": "missing"})
    assert result["isError"] is True
    assert "Video not found" in result["content"][0]["text"]


def test_call_unknown_tool():
    result = tools.call_tool("unknown", {})
    assert result["isError"] is True
    assert "Unknown tool" in result["content"][0]["text"]


def test_handle_initialize():
    response = server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    assert response["result"]["protocolVersion"] == "2024-11-05"
    assert response["result"]["serverInfo"]["name"] == "reel-scout"


def test_handle_tools_list():
    response = server.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    )
    assert {t["name"] for t in response["result"]["tools"]} == EXPECTED_TOOLS


def test_message_framing_round_trip():
    # MCP stdio framing = newline-delimited JSON (one compact object per line),
    # not LSP-style Content-Length headers.
    payload = {"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}}
    output = StringIO()
    server.write_message(payload, output)
    serialized = output.getvalue()
    assert serialized.endswith("\n")
    assert serialized.count("\n") == 1  # single line, no embedded newlines

    input_stream = StringIO(serialized)
    parsed = server.read_message(input_stream)
    assert parsed == payload


def test_call_export_json(temp_db):
    conn = db.get_connection()
    try:
        video_id = db.upsert_video(
            conn,
            platform="youtube",
            platform_id="abc123",
            url="https://youtube.com/shorts/abc123",
            title="測試影片",
            duration_sec=12.5,
        )
        db.save_transcript(
            conn,
            video_id,
            language="zh",
            text_full="這是逐字稿",
            segments_json="[]",
            whisper_model="mock-whisper",
            duration_sec=12.5,
        )
        db.save_analysis(
            conn,
            video_id,
            summary="重點摘要",
            topics_json='["測試"]',
            hooks_json='["開頭鉤子"]',
            style_json='{"format":"talking-head"}',
            engagement_signals_json='["caption"]',
            full_json='{"summary":"重點摘要"}',
        )
    finally:
        conn.close()

    output_dir = os.path.join(TMP_ROOT, "export_json")
    shutil.rmtree(output_dir, ignore_errors=True)
    os.makedirs(output_dir, exist_ok=True)
    result = tools.call_tool("export", {"format": "json", "output": output_dir})
    payload = _parse_result(result)
    try:
        assert payload["count"] == 1
        assert os.path.exists(os.path.join(output_dir, "%s.json" % video_id))
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


# --- keyframes: the only way an agent without a filesystem can see the frames ---
# `show_video` hands back file paths. In Claude Desktop there is nothing that can
# open them, so without this tool `ingest_vision` would be a write endpoint whose
# only possible input is invention.

def _seed_frames(db_path, tmpdir, *, frames=4):
    """A video plus real JPEG bytes on disk — the tool reads files, so the test
    has to put files there rather than mock the read away."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        vid = db.upsert_video(
            conn, platform="youtube", platform_id="kf123",
            url="https://youtube.com/shorts/kf123",
            title="Keyframe Test", duration_sec=20.0,
        )
        kf_dir = os.path.join(str(tmpdir), vid)
        os.makedirs(kf_dir, exist_ok=True)
        rows = []
        for i in range(frames):
            path = os.path.join(kf_dir, "%s_int_%03d.jpg" % (vid, i))
            # A JPEG SOI/EOI pair: enough that base64 round-trips real bytes.
            with open(path, "wb") as handle:
                handle.write(b"\xff\xd8\xff" + bytes([i]) * 64 + b"\xff\xd9")
            rows.append({"frame_index": i, "timestamp_sec": float(i * 2),
                         "file_path": path, "strategy": "interval"})
        db.save_keyframes(conn, vid, rows)
        conn.commit()
        return vid
    finally:
        conn.close()


def test_keyframes_returns_the_images_not_just_paths(temp_db, tmp_path):
    vid = _seed_frames(temp_db, tmp_path, frames=4)
    result = tools.call_tool("keyframes", {"video_id": vid})

    assert "isError" not in result
    kinds = [block["type"] for block in result["content"]]
    assert kinds == ["text", "image", "image", "image", "image"]
    assert all(b["mimeType"] == "image/jpeg" for b in result["content"][1:])

    payload = _parse_result(result)
    assert payload["returned"] == 4
    assert payload["keyframes_total"] == 4
    # The locator table is what ingest_vision needs to address frames by.
    assert [f["keyframe_id"] for f in payload["frames"]]
    assert [f["frame_index"] for f in payload["frames"]] == [0, 1, 2, 3]


def test_keyframes_decode_back_to_the_bytes_on_disk(temp_db, tmp_path):
    """Guards the base64 step: a mangled encode would still look like an image
    block to a shape assertion, and only show up as an unreadable frame."""
    import base64

    vid = _seed_frames(temp_db, tmp_path, frames=2)
    result = tools.call_tool("keyframes", {"video_id": vid})
    payload = _parse_result(result)

    for block, frame in zip(result["content"][1:], payload["frames"]):
        with open(frame["file_path"], "rb") as handle:
            assert base64.b64decode(block["data"]) == handle.read()


def test_keyframes_spreads_across_the_clip_rather_than_taking_the_first_n(temp_db, tmp_path):
    """The first N frames of a long clip are its first few seconds, which say
    nothing about how it resolves."""
    vid = _seed_frames(temp_db, tmp_path, frames=20)
    payload = _parse_result(tools.call_tool("keyframes", {"video_id": vid, "max_frames": 4}))

    indexes = [f["frame_index"] for f in payload["frames"]]
    assert len(indexes) == 4
    assert indexes[0] == 0 and indexes[-1] == 19


def test_keyframes_honours_explicit_frame_indexes(temp_db, tmp_path):
    vid = _seed_frames(temp_db, tmp_path, frames=8)
    payload = _parse_result(
        tools.call_tool("keyframes", {"video_id": vid, "frame_indexes": [1, 5]})
    )
    assert [f["frame_index"] for f in payload["frames"]] == [1, 5]


def test_keyframes_reports_a_missing_file_instead_of_aborting(temp_db, tmp_path):
    """One frame lost off disk should cost that frame, not the whole call —
    same partial-success philosophy as ingest_vision."""
    vid = _seed_frames(temp_db, tmp_path, frames=3)
    payload_before = _parse_result(tools.call_tool("keyframes", {"video_id": vid}))
    os.remove(payload_before["frames"][1]["file_path"])

    payload = _parse_result(tools.call_tool("keyframes", {"video_id": vid}))
    assert payload["returned"] == 2
    assert len(payload["warnings"]) == 1
    assert "not on disk" in payload["warnings"][0]


def test_keyframes_says_so_when_it_truncates(temp_db, tmp_path, monkeypatch):
    """Silent truncation reads as 'that was the whole clip'."""
    monkeypatch.setattr(tools, "_KEYFRAMES_MAX_BYTES", 100)
    vid = _seed_frames(temp_db, tmp_path, frames=6)
    payload = _parse_result(tools.call_tool("keyframes", {"video_id": vid}))
    assert "truncated" in payload
    assert payload["returned"] < 6


def test_keyframes_flags_frames_that_already_have_a_description(temp_db, tmp_path):
    vid = _seed_frames(temp_db, tmp_path, frames=3)
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = db.get_keyframes(conn, vid)
        db.save_vision_description(
            conn, rows[0]["id"], description="already seen",
            objects_json="[]", text_in_frame="", vlm_backend="agent",
            vlm_model="agent:test",
        )
        conn.commit()
    finally:
        conn.close()
    payload = _parse_result(tools.call_tool("keyframes", {"video_id": vid}))
    assert [f["already_described"] for f in payload["frames"]] == [True, False, False]


def test_keyframes_accepts_an_id_prefix(temp_db, tmp_path):
    vid = _seed_frames(temp_db, tmp_path, frames=2)
    payload = _parse_result(tools.call_tool("keyframes", {"video_id": vid[:8]}))
    assert payload["video_id"] == vid


def test_keyframes_on_an_unknown_video_is_a_clean_error(temp_db):
    result = tools.call_tool("keyframes", {"video_id": "nope"})
    assert result["isError"] is True
    assert "not found" in result["content"][0]["text"].lower()


def test_keyframes_without_any_frames_says_what_to_run(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    try:
        vid = db.upsert_video(
            conn, platform="youtube", platform_id="bare",
            url="https://youtube.com/shorts/bare", title="Bare", duration_sec=5.0,
        )
        conn.commit()
    finally:
        conn.close()
    result = tools.call_tool("keyframes", {"video_id": vid})
    assert result["isError"] is True
    assert "analyze" in result["content"][0]["text"]


def test_keyframes_never_writes_to_stdout(temp_db, tmp_path, capsys):
    """stdout is the NDJSON channel. A stray print corrupts the stream and kills
    the session with no other symptom, so every tool needs this assertion."""
    vid = _seed_frames(temp_db, tmp_path, frames=3)
    tools.call_tool("keyframes", {"video_id": vid})
    assert capsys.readouterr().out == ""
