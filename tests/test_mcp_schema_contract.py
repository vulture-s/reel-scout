"""Contract between the MCP schema the model reads and the values the code
actually stores. An enum that drifts from the data makes a filter silently
return nothing; these tests fail first."""
from __future__ import annotations

import ast
import json
import os
import re
import sqlite3

from reel_scout import crawl, db, validity
from reel_scout.analyze import pipeline
from reel_scout.mcp import server, tools

_PKG = os.path.dirname(db.__file__)


def _schema(name):
    return next(t for t in tools.list_tools() if t["name"] == name)["inputSchema"]


def _written_video_statuses():
    """Every status literal the package writes to `videos.status`."""
    found = set()
    sql_re = re.compile(r"UPDATE videos SET status\s*=\s*'([a-z_]+)'")
    for root, _dirs, files in os.walk(_PKG):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            src = open(os.path.join(root, fname), encoding="utf-8").read()
            found.update(sql_re.findall(src))
            for node in ast.walk(ast.parse(src)):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "attr", getattr(node.func, "id", None)) == "update_video_status"
                        and len(node.args) >= 3):
                    arg = node.args[2]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        found.add(arg.value)
                    elif isinstance(arg, ast.Name) and arg.id == "INVALID_STATUS":
                        found.add(validity.INVALID_STATUS)
                    else:
                        raise AssertionError("non-literal status in %s: %s" % (fname, ast.unparse(arg)))
    return found


def test_status_enum_covers_every_written_status():
    written = _written_video_statuses()
    assert written, "scanner found no status writes -- it is broken, not clean"
    assert written <= set(db.VIDEO_STATUSES)


def test_status_enum_includes_schema_default():
    m = re.search(r"status\s+TEXT DEFAULT '([a-z_]+)'", open(db.__file__, encoding="utf-8").read())
    assert m and m.group(1) in db.VIDEO_STATUSES


def test_platform_enum_matches_crawl_and_local():
    want = {name for _pat, name in crawl._PLATFORM_PATTERNS} | {pipeline.LOCAL_PLATFORM}
    assert set(tools._PLATFORMS) == want


def test_list_videos_schema_publishes_the_enums():
    props = _schema("list_videos")["properties"]
    assert props["status"]["enum"] == list(db.VIDEO_STATUSES)
    assert props["platform"]["enum"] == list(tools._PLATFORMS)
    assert _schema("list_videos")["additionalProperties"] is False


def test_list_videos_rejects_unknown_filter(temp_db):
    for args in ({"status": "Analyzed"}, {"platform": "ig"}):
        result = tools.call_tool("list_videos", args)
        assert result.get("isError"), args
        assert "expected one of" in result["content"][0]["text"]


def test_list_videos_valid_filter_still_filters(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    vid = db.upsert_video(conn, platform="youtube", platform_id="sc1",
                          url="https://youtube.com/shorts/sc1", title="t")
    db.update_video_status(conn, vid, "analyzed")
    conn.close()
    got = json.loads(tools.call_tool("list_videos", {"status": "analyzed"})["content"][0]["text"])
    assert [v["video_id"] for v in got] == [vid]
    assert json.loads(tools.call_tool("list_videos", {"status": "invalid"})["content"][0]["text"]) == []


def test_initialize_sends_instructions():
    result = server.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})["result"]
    text = result["instructions"]
    assert "native-subtitles" in text and "measured" in text
