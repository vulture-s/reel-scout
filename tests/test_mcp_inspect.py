from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from typing import Any

import pytest

from reel_scout import db
from reel_scout.mcp import live, tools


def _parse(result: Any) -> Any:
    """The JSON block — for inspect that is the second one, after the link."""
    blocks = [b for b in result["content"] if b["type"] == "text"]
    return json.loads(blocks[-1]["text"])


@pytest.fixture(autouse=True)
def _stop_inspector():
    """A leaked serve_forever thread outlives the test that made it and takes
    the port with it."""
    yield
    live.stop_inspector()


def _seed_video(db_path, title="Fried Chicken"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        vid = db.upsert_video(
            conn, platform="youtube", platform_id="insp1",
            url="https://youtube.com/shorts/insp1", title=title, duration_sec=12.0)
        conn.commit()
        return vid
    finally:
        conn.close()


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, response.read()


def test_inspect_starts_a_server_and_the_url_actually_answers(temp_db):
    vid = _seed_video(temp_db)
    result = tools.call_tool("inspect", {"video_id": vid})

    assert "isError" not in result
    payload = _parse(result)
    status, body = _get(payload["url"])
    assert status == 200
    assert b"Fried Chicken" in body


def test_the_bare_url_is_in_a_block_of_its_own(temp_db):
    """A URL buried in a JSON blob does not reliably become clickable, and
    clicking it is the entire point of the tool."""
    vid = _seed_video(temp_db)
    result = tools.call_tool("inspect", {"video_id": vid})
    headline = result["content"][0]["text"]
    assert headline.count("http://127.0.0.1:") == 1
    assert not headline.lstrip().startswith("{")


def test_repeat_calls_reuse_one_server(temp_db):
    """One server serves every clip: /inspect/<id> resolves any video, so a
    second call should hand back a different path on the same port rather than
    leaking another socket and thread."""
    first_id = _seed_video(temp_db)
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    try:
        second_id = db.upsert_video(
            conn, platform="youtube", platform_id="insp2",
            url="https://youtube.com/shorts/insp2", title="Second", duration_sec=9.0)
        conn.commit()
    finally:
        conn.close()

    first = _parse(tools.call_tool("inspect", {"video_id": first_id}))
    second = _parse(tools.call_tool("inspect", {"video_id": second_id}))

    assert first["base_url"] == second["base_url"]
    assert first["reused"] is False and second["reused"] is True
    assert first["url"] != second["url"]
    assert _get(first["url"])[0] == 200
    assert _get(second["url"])[0] == 200


def test_inspect_works_against_a_database_that_does_not_exist_yet(temp_db, monkeypatch, tmp_path):
    """make_inspect_server only connects — it never creates the schema or runs
    migrations, and the request handler calls get_connection directly. Without
    an init_db first this is a page of 500s."""
    from reel_scout import config

    fresh = tmp_path / "fresh"
    monkeypatch.setattr(config, "DATA_DIR", str(fresh))
    monkeypatch.setattr(config, "DB_PATH", str(fresh / "reel_scout.db"))
    monkeypatch.setattr(config, "VIDEOS_DIR", str(fresh / "videos"))
    monkeypatch.setattr(config, "KEYFRAMES_DIR", str(fresh / "keyframes"))
    monkeypatch.setattr(config, "ANALYSIS_DIR", str(fresh / "analysis"))

    payload = _parse(tools.call_tool("inspect", {}))
    assert _get(payload["url"])[0] == 200


def test_inspect_without_a_video_lands_on_the_library(temp_db):
    _seed_video(temp_db)
    payload = _parse(tools.call_tool("inspect", {}))
    assert payload["video_id"] is None
    assert payload["url"].endswith("/")
    assert _get(payload["url"])[0] == 200


def test_inspect_binds_only_loopback(temp_db):
    """No route carries any authentication and /api/stream/ will serve any video
    in the database, so `host` must never be reachable from the schema."""
    _seed_video(temp_db)
    payload = _parse(tools.call_tool("inspect", {}))
    assert payload["base_url"].startswith("http://127.0.0.1:")

    schema = next(t for t in tools.list_tools() if t["name"] == "inspect")["inputSchema"]
    assert "host" not in schema["properties"]
    assert "port" not in schema["properties"]


def test_unknown_video_is_a_clean_error_and_starts_nothing(temp_db):
    result = tools.call_tool("inspect", {"video_id": "nope"})
    assert result["isError"] is True
    assert live.is_running() is False


def test_ambiguous_prefix_lists_the_matches(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    try:
        for i in (1, 2):
            db.upsert_video(conn, platform="youtube", platform_id="amb%d" % i,
                            url="https://youtube.com/shorts/amb%d" % i, title="A%d" % i)
        conn.commit()
        ids = [r[0] for r in conn.execute("SELECT id FROM videos").fetchall()]
    finally:
        conn.close()

    shared = os.path.commonprefix(ids)
    if len(shared) < 1:
        pytest.skip("generated ids share no prefix in this run")
    result = tools.call_tool("inspect", {"video_id": shared})
    assert result["isError"] is True
    assert "mbiguous" in result["content"][0]["text"]


def test_status_before_start_reports_not_running_and_starts_nothing(temp_db):
    payload = _parse(tools.call_tool("inspect", {"action": "status"}))
    assert payload["running"] is False
    assert payload["base_url"] is None
    assert live.is_running() is False


def test_stop_shuts_the_port_down(temp_db):
    _seed_video(temp_db)
    payload = _parse(tools.call_tool("inspect", {}))
    url = payload["url"]
    assert _get(url)[0] == 200

    stopped = _parse(tools.call_tool("inspect", {"action": "stop"}))
    assert stopped["stopped"] is True
    assert live.is_running() is False
    with pytest.raises((urllib.error.URLError, OSError)):
        _get(url)


def test_stop_when_nothing_is_running_is_not_an_error(temp_db):
    assert _parse(tools.call_tool("inspect", {"action": "stop"}))["stopped"] is False


def test_a_dead_serve_thread_is_not_reported_as_running(temp_db):
    """serve_forever can die on an unhandled error and leave the httpd object
    behind; a handle alone would keep handing out a URL that no longer answers."""
    _seed_video(temp_db)
    tools.call_tool("inspect", {})
    assert live.is_running() is True

    live._STATE["thread"].join(0)
    live._STATE["httpd"].shutdown()
    live._STATE["thread"].join(timeout=5)

    assert live.is_running() is False
    assert live.base_url() is None


def test_an_unknown_action_is_refused(temp_db):
    assert tools.call_tool("inspect", {"action": "restart"}).get("isError")


def test_inspect_never_writes_to_stdout(temp_db, capsys):
    _seed_video(temp_db)
    tools.call_tool("inspect", {})
    tools.call_tool("inspect", {"action": "status"})
    tools.call_tool("inspect", {"action": "stop"})
    assert capsys.readouterr().out == ""


def test_the_score_shows_which_model_produced_it(temp_db):
    """The same clip scores 7.43 under one VLM and 5.5 under another, and `stats`
    averages agent-scored and locally-scored rows together — a number with no
    origin cannot be compared with anything. Shared with the exported bundle,
    which renders through the same function."""
    vid = _seed_video(temp_db)
    tools.call_tool("ingest_score", {
        "video_id": vid, "model": "test-model",
        "hook_strength": 6, "visual_storytelling": 4, "pacing": 6, "structure": 5,
        "reasoning": "why"})

    payload = _parse(tools.call_tool("inspect", {"video_id": vid}))
    body = _get(payload["url"])[1].decode("utf-8", "replace")
    assert "Craft scores" in body
    assert "agent:test-model" in body
