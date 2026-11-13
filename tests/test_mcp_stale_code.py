"""The MCP server refuses to run once its own source changed on disk.

2026-11-13: the server had been up since before a `git pull`; `analyze` then
imported the new pipeline.py against the db module already in memory and died
with "no attribute 'get_audio_loudness'" -- a function that exists in the source.
"""
from __future__ import annotations

from reel_scout.mcp import tools


def _calls(monkeypatch):
    seen = []
    monkeypatch.setitem(tools._HANDLERS, "list_videos", lambda args: seen.append(args) or tools._text_result([]))
    return seen


def test_unchanged_source_runs_the_handler(monkeypatch):
    seen = _calls(monkeypatch)
    monkeypatch.setattr(tools, "_STARTUP_FINGERPRINT", tools._source_fingerprint())
    result = tools.call_tool("list_videos", {})
    assert not result.get("isError"), result
    assert seen == [{}]


def test_changed_source_refuses_and_names_the_file(monkeypatch):
    seen = _calls(monkeypatch)
    now = tools._source_fingerprint()
    path, mtime, size = now[0]
    monkeypatch.setattr(tools, "_STARTUP_FINGERPRINT", ((path, mtime - 1, size),) + now[1:])
    result = tools.call_tool("list_videos", {})
    assert result.get("isError")
    text = result["content"][0]["text"]
    assert "Restart" in text and path in text
    assert seen == []                     # nothing ran on mixed code


def test_new_file_after_startup_counts_as_changed(monkeypatch):
    seen = _calls(monkeypatch)
    now = tools._source_fingerprint()
    monkeypatch.setattr(tools, "_STARTUP_FINGERPRINT", now[1:])   # pretend now[0] did not exist at startup
    assert tools.call_tool("list_videos", {}).get("isError")
    assert seen == []


def test_fingerprint_covers_lazily_imported_modules():
    paths = {p for p, _, _ in tools._source_fingerprint()}
    assert "db.py" in paths
    assert any(p.startswith("analyze") and p.endswith("pipeline.py") for p in paths)
    assert not any("__pycache__" in p for p in paths)
