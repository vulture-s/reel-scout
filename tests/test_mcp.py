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


def test_list_tools_count():
    tool_defs = tools.list_tools()
    assert len(tool_defs) == 8


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
    assert len(response["result"]["tools"]) == 8


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
