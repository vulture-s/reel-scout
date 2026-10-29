"""Short clips earn one keyframe per shot, up to KEYFRAME_SHOT_CAP.

`9uqk-3P96V0` (KOMPAN x Porsche, 36.0s, 23 shots) got the flat short-form cap of
12 frames on 2026-10-29: the VLM saw every other shot, and Sydney, Rio, Tokyo and
Brooklyn -- four of the six locations in the montage -- never reached it. The
cut list below is that clip's stored shot table.

These pin both directions: a fast-cut short clip grows to one frame per shot,
and everything else -- slow clips, long-form, an explicit --keyframe-max, the
setting turned off -- spends exactly what it spent before.

All synthetic: no ffmpeg, no media, no model.
"""
from __future__ import annotations

import io
import subprocess

import pytest

from reel_scout import config
from reel_scout.vision import keyframe

KOMPAN_DURATION = 36.0
KOMPAN_CUTS = [
    2.36, 3.8, 5.08, 7.2, 7.96, 9.36, 11.08, 12.52, 14.28, 17.6, 20.04,
    20.96, 22.88, 24.52, 24.68, 24.76, 24.84, 24.92, 25.28, 27.08, 28.48,
    30.64,
]


def _stub_ffmpeg(monkeypatch, cuts, duration):
    class _CutsPopen:
        """Detection pass: reports `cuts` as showinfo pts_time lines."""
        def __init__(self, cmd, **kw):
            assert "-f" in cmd and "null" in cmd, cmd
            self.stderr = io.StringIO(
                "".join("n:%d pts_time:%g\n" % (i, t) for i, t in enumerate(cuts)))
            self.returncode = None

        def poll(self):
            return self.returncode

        def kill(self):
            pass

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    def _fake_run(cmd, **kw):
        open(cmd[-1], "wb").close()     # per-frame grab
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(keyframe.subprocess, "Popen", _CutsPopen)
    monkeypatch.setattr(keyframe.subprocess, "run", _fake_run)
    monkeypatch.setattr(keyframe, "_get_duration", lambda p: duration)
    monkeypatch.setattr(config, "KEYFRAME_DEDUPE", False)
    monkeypatch.setattr(config, "KEYFRAME_MAX", 12)
    monkeypatch.setattr(config, "KEYFRAME_SHOT_CAP", 30)


def _shots(cuts, duration):
    edges = [0.0] + list(cuts) + [duration]
    return list(zip(edges, edges[1:]))


def _ts(frames):
    return [f.timestamp_sec for f in frames]


@pytest.mark.parametrize("strategy", ["scene", "hybrid"])
def test_fast_cut_short_clip_gets_a_frame_in_every_shot(tmp_path, monkeypatch, strategy):
    _stub_ffmpeg(monkeypatch, KOMPAN_CUTS, KOMPAN_DURATION)

    frames = keyframe.extract_keyframes(
        "x.mp4", str(tmp_path), "vid", strategy=strategy)

    shots = _shots(KOMPAN_CUTS, KOMPAN_DURATION)
    assert len(shots) == 23
    # One per cut plus the guaranteed first and last frames.
    assert len(frames) == len(KOMPAN_CUTS) + 2 == 24
    ts = _ts(frames)
    for start, end in shots:
        assert any(start <= t < end for t in ts), (start, end, ts)


def test_hybrid_does_not_pad_a_grown_budget_with_interval_frames(tmp_path, monkeypatch):
    _stub_ffmpeg(monkeypatch, KOMPAN_CUTS, KOMPAN_DURATION)

    frames = keyframe.extract_keyframes(
        "x.mp4", str(tmp_path), "vid", strategy="hybrid")

    assert not [f for f in frames if f.strategy == "interval"]


def test_shot_cap_bounds_a_very_fast_clip(tmp_path, monkeypatch):
    cuts = [0.5 * i for i in range(1, 120)]           # 120 shots in 60s
    _stub_ffmpeg(monkeypatch, cuts, 60.0)

    frames = keyframe.extract_keyframes(
        "x.mp4", str(tmp_path), "vid", strategy="scene")

    assert len(frames) == config.KEYFRAME_SHOT_CAP
    ts = _ts(frames)
    assert ts[0] < 0.5 and ts[-1] > 59.0, "still spread end to end"


def _run(tmp_path, monkeypatch, cuts, duration, shot_cap, **kw):
    _stub_ffmpeg(monkeypatch, cuts, duration)
    monkeypatch.setattr(config, "KEYFRAME_SHOT_CAP", shot_cap)
    out = tmp_path / ("cap%d" % shot_cap)
    return _ts(keyframe.extract_keyframes("x.mp4", str(out), "vid", **kw))


@pytest.mark.parametrize("cuts,duration,kw", [
    # Slow short clip: fewer cuts than KEYFRAME_MAX.
    ([4.0, 9.0, 15.0, 22.0], 30.0, {"strategy": "scene"}),
    ([4.0, 9.0, 15.0, 22.0], 30.0, {"strategy": "hybrid"}),
    # Long-form keeps its per-minute curve.
    ([3.0 * i for i in range(1, 200)], 600.0, {"strategy": "scene"}),
    # An explicit count is respected as-is.
    (KOMPAN_CUTS, KOMPAN_DURATION, {"strategy": "scene", "max_frames": 12}),
    # A focus window has its own denser table.
    (KOMPAN_CUTS, KOMPAN_DURATION,
     {"strategy": "scene", "start_sec": 5.0, "end_sec": 30.0}),
])
def test_everything_else_spends_exactly_what_it_did_before(
        tmp_path, monkeypatch, cuts, duration, kw):
    before = _run(tmp_path, monkeypatch, cuts, duration, 0, **kw)
    after = _run(tmp_path, monkeypatch, cuts, duration, 30, **kw)
    assert after == before


def test_off_restores_the_flat_cap_on_a_fast_clip(tmp_path, monkeypatch):
    ts = _run(tmp_path, monkeypatch, KOMPAN_CUTS, KOMPAN_DURATION, 0,
              strategy="scene")
    assert len(ts) == 12


def test_grown_budget_never_shrinks_and_never_passes_the_cap():
    assert keyframe.grown_budget(12, 5, 30) == 12
    assert keyframe.grown_budget(12, 22, 30) == 24
    assert keyframe.grown_budget(12, 40, 30) == 30
    assert keyframe.grown_budget(12, 40, 0) == 12
