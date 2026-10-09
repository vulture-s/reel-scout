"""No analysis is merged from a visual layer that never arrived (2026-10-09).

When the VLM is unreachable (oMLX not running is the usual case) every frame
fails, the pipeline printed "left empty for a later vision retry" -- and then
merged and scored anyway, with "(no vision data)" in the prompt. The retry it
promised does backfill the descriptions, but merge and score are skipped as
"already done" on every later run, so `visual_storytelling` stays a number
produced from no visuals, indistinguishable from a real one.

Now: if vision was attempted and not one frame was described, the run stops
before merge, and the item fails loudly. A re-run with the VLM up merges then.
Partial success still merges -- a partial visual layer is evidence.
"""
from __future__ import annotations

import os
import sqlite3
from unittest.mock import MagicMock

import pytest

from reel_scout import db
from reel_scout.analyze import pipeline
from reel_scout.vision.base import FrameDescription
from reel_scout.vision.keyframe import KeyframeInfo


def _harness(tmp_path, monkeypatch):
    d = str(tmp_path)
    monkeypatch.setattr(pipeline.config, "DATA_DIR", d)
    monkeypatch.setattr(pipeline.config, "KEYFRAMES_DIR", os.path.join(d, "kf"))
    monkeypatch.setattr(pipeline.config, "VIDEOS_DIR", os.path.join(d, "videos"))
    monkeypatch.setattr(pipeline.config, "SHOT_METRICS_ENABLED", False)
    monkeypatch.setattr(pipeline.config, "OCR_ENABLED", False)
    media = os.path.join(d, "clip.mp4")
    with open(media, "wb") as f:
        f.write(b"\x00")
    conn = sqlite3.connect(os.path.join(d, "t.db"))
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    url = "https://www.youtube.com/watch?v=visiondown"
    vid = db.upsert_video(conn, platform="youtube", platform_id="visiondown", url=url,
                          title="t", duration_sec=20.0, file_path=media,
                          file_size_bytes=1)

    def fake_extract(video_path, out_dir, video_id, **kw):
        os.makedirs(out_dir, exist_ok=True)
        frames = []
        for i in range(3):
            p = os.path.join(out_dir, "f%d.jpg" % i)
            with open(p, "wb") as f:
                f.write(b"\xff\xd8\xff")
            frames.append(KeyframeInfo(frame_index=i, timestamp_sec=i * 5.0,
                                       file_path=p, strategy="interval"))
        return frames

    monkeypatch.setattr(pipeline, "extract_keyframes", fake_extract)
    monkeypatch.setattr(pipeline, "fallback_blocked_because",
                        lambda *a, **k: "no fallback in this test")
    return conn, url, vid


def _vlm(results):
    vlm = MagicMock()
    vlm.describe_frame.side_effect = list(results)
    return vlm


def _opts():
    return pipeline.PipelineOptions(skip_transcribe=True, score=True)


def test_every_frame_failing_stops_before_merge(tmp_path, monkeypatch):
    conn, url, vid = _harness(tmp_path, monkeypatch)
    down = ConnectionRefusedError("VLM down")
    monkeypatch.setattr(pipeline, "get_vlm", lambda *a, **k: _vlm([down] * 3))
    monkeypatch.setattr(pipeline, "merge_analysis",
                        lambda *a, **k: pytest.fail("merged with no visual layer"))
    try:
        with pytest.raises(RuntimeError, match="no keyframe"):
            pipeline._process_single(conn, url, _opts())
        assert db.get_analysis(conn, vid) is None
        assert db.get_score(conn, vid) is None
    finally:
        conn.close()


def test_a_partial_visual_layer_still_merges(tmp_path, monkeypatch):
    conn, url, vid = _harness(tmp_path, monkeypatch)
    ok = FrameDescription(description="a red card", objects=[], text_in_frame="")
    monkeypatch.setattr(pipeline, "get_vlm",
                        lambda *a, **k: _vlm([ConnectionRefusedError("x"), ok, ok]))
    merged = []
    monkeypatch.setattr(pipeline, "merge_analysis", lambda c, v: merged.append(v))
    monkeypatch.setattr(pipeline.config, "SHOT_METRICS_ENABLED", False)
    try:
        opts = _opts()
        opts.score = False
        pipeline._process_single(conn, url, opts)
        assert merged == [vid]
    finally:
        conn.close()


def test_skip_vision_is_not_a_failure(tmp_path, monkeypatch):
    """--skip-vision is a choice (the agent-ingest path), not an outage."""
    conn, url, vid = _harness(tmp_path, monkeypatch)
    monkeypatch.setattr(pipeline, "get_vlm",
                        lambda *a, **k: pytest.fail("VLM called under --skip-vision"))
    merged = []
    monkeypatch.setattr(pipeline, "merge_analysis", lambda c, v: merged.append(v))
    try:
        opts = pipeline.PipelineOptions(skip_transcribe=True, skip_vision=True)
        pipeline._process_single(conn, url, opts)
        assert merged == [vid]
    finally:
        conn.close()
