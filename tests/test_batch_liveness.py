"""Audit E6 (2026-10-09) MED #2/#3 follow-ups: a live worker must not read as
dead, a fresh one must hold the gate, and `analyze` must say which row it made."""
from __future__ import annotations

import json
import sqlite3
import time

from reel_scout import config, db
from reel_scout.mcp import batch_worker, tools


def _parse(result):
    return json.loads(result["content"][0]["text"])


def _conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _no_spawn(monkeypatch):
    monkeypatch.setattr(tools, "_spawn_worker", lambda batch_id, log: 4242)


# --- heartbeat is independent of progress ------------------------------------

def test_worker_beats_while_one_long_step_emits_nothing(temp_db, monkeypatch):
    """The failure: one analyze child silent for >15 min -> 'stalled'. Here a
    run_batch that emits no events at all must still keep the heartbeat going."""
    monkeypatch.setattr(config, "BATCH_HEARTBEAT_SEC", 0.05)
    conn = _conn(temp_db)
    bid = db.create_batch(conn, ["https://www.youtube.com/shorts/aaaaaaaaaaa"],
                          source=batch_worker.BATCH_SOURCE)
    conn.close()

    beats = []
    real_touch = db.touch_batch_heartbeat

    def counting_touch(c, b):
        beats.append(time.monotonic())
        return real_touch(c, b)

    monkeypatch.setattr(db, "touch_batch_heartbeat", counting_touch)

    def silent_run_batch(entries, out_root, mode, verbose=False, on_progress=None):
        time.sleep(0.6)  # one long step, no events
        return {"mode": mode, "done": [], "failed": [], "pending_completion": []}

    monkeypatch.setattr(batch_worker.batch_mod, "run_batch", silent_run_batch)
    assert batch_worker.run(bid) == 0
    # 1 initial touch + several from the thread during the silent 0.6s
    assert len(beats) >= 4, beats


def test_heartbeat_thread_stops_with_the_worker(temp_db, monkeypatch):
    monkeypatch.setattr(config, "BATCH_HEARTBEAT_SEC", 0.05)
    conn = _conn(temp_db)
    bid = db.create_batch(conn, ["https://www.youtube.com/shorts/aaaaaaaaaaa"],
                          source=batch_worker.BATCH_SOURCE)
    conn.close()
    hb = batch_worker.Heartbeat(bid, 0.05).start()
    hb.stop()
    assert not hb._thread.is_alive()


def test_heartbeat_survives_a_failed_touch(temp_db, monkeypatch):
    calls = []

    def flaky(c, b):
        calls.append(1)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db, "touch_batch_heartbeat", flaky)
    hb = batch_worker.Heartbeat("nope", 0.05).start()
    time.sleep(0.3)
    alive = hb._thread.is_alive()
    hb.stop()
    assert alive and len(calls) >= 2


# --- batch_start gate --------------------------------------------------------

def test_a_second_start_while_the_first_is_still_starting_is_refused(temp_db, monkeypatch):
    """Two quick batch_start calls used to spawn two workers: the first had no
    heartbeat yet, and only state == 'running' was treated as busy."""
    _no_spawn(monkeypatch)
    first = _parse(tools.call_tool("batch_start", {
        "urls": ["https://www.youtube.com/shorts/aaaaaaaaaaa"], "mode": "agent"}))
    assert first["status"] == "started"
    second = tools.call_tool("batch_start", {
        "urls": ["https://www.youtube.com/shorts/bbbbbbbbbbb"], "mode": "agent"})
    assert second.get("isError") is True
    assert "starting" in second["content"][0]["text"]


def test_a_spawn_that_never_came_up_does_not_hold_the_gate_forever(temp_db, monkeypatch):
    _no_spawn(monkeypatch)
    first = _parse(tools.call_tool("batch_start", {
        "urls": ["https://www.youtube.com/shorts/aaaaaaaaaaa"], "mode": "agent"}))
    conn = _conn(temp_db)
    conn.execute("UPDATE batches SET created_at = datetime('now', '-30 minutes') "
                 "WHERE id = ?", (first["batch_id"],))
    conn.commit()
    conn.close()
    assert _parse(tools.call_tool("batch_status", {}))["state"] == "stalled"
    second = _parse(tools.call_tool("batch_start", {
        "urls": ["https://www.youtube.com/shorts/bbbbbbbbbbb"], "mode": "agent"}))
    assert second["status"] == "started"


def test_a_fresh_heartbeat_holds_the_gate_and_force_overrides(temp_db, monkeypatch):
    _no_spawn(monkeypatch)
    first = _parse(tools.call_tool("batch_start", {
        "urls": ["https://www.youtube.com/shorts/aaaaaaaaaaa"], "mode": "agent"}))
    conn = _conn(temp_db)
    db.touch_batch_heartbeat(conn, first["batch_id"])
    conn.close()
    refused = tools.call_tool("batch_start", {
        "urls": ["https://www.youtube.com/shorts/bbbbbbbbbbb"], "mode": "agent"})
    assert refused.get("isError") is True
    forced = _parse(tools.call_tool("batch_start", {
        "urls": ["https://www.youtube.com/shorts/bbbbbbbbbbb"], "mode": "agent",
        "force": True}))
    assert forced["status"] == "started"


# --- analyze reports the row it produced -------------------------------------

def test_pipeline_writes_the_report_batch_reads(temp_db, tmp_path, monkeypatch):
    from reel_scout import batch
    from reel_scout.analyze import pipeline

    made = []

    def fake_single(conn, url, opts):
        made.append(db.upsert_video(conn, "instagram", "AAAAAAAAAAA", url))
        return made[-1]

    monkeypatch.setattr(pipeline, "_process_single", fake_single)
    report = str(tmp_path / "ids.json")
    errors = pipeline.run(["https://www.instagram.com/reel/AAAAAAAAAAA/"],
                          pipeline.PipelineOptions(), report_path=report)
    assert errors == 0
    assert batch.reported_video_id(report) == made[0]


def test_pipeline_report_is_empty_when_the_item_failed(temp_db, tmp_path, monkeypatch):
    from reel_scout import batch
    from reel_scout.analyze import pipeline

    def boom(conn, url, opts):
        raise RuntimeError("nope")

    monkeypatch.setattr(pipeline, "_process_single", boom)
    report = str(tmp_path / "ids.json")
    pipeline.run(["https://www.instagram.com/reel/AAAAAAAAAAA/"],
                 pipeline.PipelineOptions(), report_path=report)
    assert batch.reported_video_id(report) is None


def test_cli_analyze_passes_report_ids_through(monkeypatch, tmp_path):
    from reel_scout import cli
    from reel_scout.analyze import pipeline

    seen = {}

    def fake_run(urls, options, report_path=None):
        seen["report_path"] = report_path
        return 0

    monkeypatch.setattr(pipeline, "run", fake_run)
    report = str(tmp_path / "r.json")
    cli.main(["analyze", "--report-ids", report, "https://www.instagram.com/reel/AAAAAAAAAAA/"])
    assert seen["report_path"] == report


def test_batch_command_line_carries_the_report_flag(tmp_path):
    from reel_scout import batch
    p = batch._report_path(str(tmp_path), 3)
    cmd = batch.self_cmd("analyze", "u", "--report-ids", p)
    assert cmd[cmd.index("--report-ids") + 1] == p
