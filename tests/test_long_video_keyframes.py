"""Exclusion tests: the budget / spread functions are not why a 4.2h clip got 0 frames.

`RwyLahUuGcc` (video_id 6706e700a348e52e, 15035s) ended its keyframe stage with
zero frames on 2026-08-06. The question left open afterwards was whether
`frame_cap`, `auto_frame_budget`, `select_spread` or `_extract_interval` misbehave
at that duration. They do not, and these tests pin that at the exact duration
of the clip, so a later change that does break them at 4h is caught here rather
than by another silent zero.

The actual cause was the scene-detection pass of that era (fixed in #61):
`-frames:v` never fired on a cut-less livestream, the hardcoded 120s timeout
raised `TimeoutExpired`, nothing caught it, and the run died after ffmpeg had
written exactly one image (`6706e700a348e52e_scene_001.jpg`, still on disk,
mtime one minute after the transcript row). That path is pinned by
`test_scene_detect_timeout_falls_back_to_interval_instead_of_zero_frames` in
test_keyframe.py; nothing here duplicates it.

All synthetic: no ffmpeg, no media, no model.
"""
from __future__ import annotations

import io
import subprocess

from reel_scout import config
from reel_scout.vision import keyframe
from reel_scout.vision.keyframe import (
    KeyframeInfo,
    auto_frame_budget,
    frame_cap,
    select_spread,
)

RWY_DURATION = 15035.0  # videos.duration_sec for RwyLahUuGcc
ZDI_DURATION = 13170.0  # zdiEwriSZCM, the other >3.5h clip marked invalid


def _max_gap(values):
    return max(b - a for a, b in zip(values, values[1:]))


def test_the_budget_for_a_four_hour_clip_is_never_zero():
    for d in (RWY_DURATION, ZDI_DURATION, 24 * 3600.0):
        budget = min(auto_frame_budget(d, focused=False), frame_cap(d))
        assert budget == config.KEYFRAME_MAX_LONG > 0, d


def test_select_spread_with_almost_no_cuts_keeps_every_cut():
    """A talking-head livestream: three cuts in four hours, budget 40."""
    stamps = [12.0, 7200.0, 15020.0]
    assert select_spread(stamps, 40) == [0, 1, 2]
    assert select_spread([3600.0], 40) == [0]
    assert select_spread([], 40) == []


def test_select_spread_over_a_dense_four_hour_cut_list_covers_the_whole_clip():
    """20k cuts, three quarters of them packed into the first 10 minutes."""
    dense_open = [i * 0.04 for i in range(15000)]  # 600s of rapid cuts
    sparse_tail = [600.0 + i * (RWY_DURATION - 601.0) / 5000 for i in range(1, 5001)]
    stamps = dense_open + sparse_tail
    n = config.KEYFRAME_MAX_LONG

    picked = select_spread(stamps, n)
    chosen = [stamps[i] for i in picked]

    assert len(picked) == n
    assert len(set(picked)) == n
    assert picked == sorted(picked)
    assert picked[0] == 0 and picked[-1] == len(stamps) - 1
    span = stamps[-1] - stamps[0]
    assert _max_gap(chosen) <= 1.6 * span / (n - 1)


def test_interval_sampling_spans_four_hours_without_running_out(tmp_path, monkeypatch):
    calls = []

    def _fake_run(cmd, **kw):
        calls.append(cmd)
        out = cmd[-1]
        open(out, "wb").close()
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(keyframe.subprocess, "run", _fake_run)
    monkeypatch.setattr(keyframe, "_get_duration", lambda p: RWY_DURATION)

    frames = keyframe._extract_interval(
        "x.mp4", str(tmp_path), "vid", config.KEYFRAME_MAX_LONG)

    ts = [f.timestamp_sec for f in frames]
    assert len(frames) == config.KEYFRAME_MAX_LONG
    assert len(set(ts)) == len(ts)
    assert 0 < ts[0] < 400 and RWY_DURATION - 400 < ts[-1] < RWY_DURATION


def test_scene_strategy_end_to_end_on_a_cutless_four_hour_clip(tmp_path, monkeypatch):
    """Detection finds nothing (no timeout), fallback must still deliver frames.

    The #61 test covers the timeout branch; this one covers the other way
    detection can come back empty on a livestream -- it finishes and reports no
    cuts -- through the real `_extract_interval`, `_ensure_first_last` and
    `select_spread`, with only ffmpeg stubbed.
    """
    class _NoCutsPopen:
        """Detection pass (streamed via Popen): finishes, reports zero cuts."""
        def __init__(self, cmd, **kw):
            assert "-f" in cmd and "null" in cmd, cmd
            self.stderr = io.StringIO("frame=1 fps=0.0\n")
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

    monkeypatch.setattr(keyframe.subprocess, "Popen", _NoCutsPopen)
    monkeypatch.setattr(keyframe.subprocess, "run", _fake_run)
    monkeypatch.setattr(keyframe, "_get_duration", lambda p: RWY_DURATION)
    monkeypatch.setattr(config, "KEYFRAME_DEDUPE", False)

    frames = keyframe.extract_keyframes(
        "x.mp4", str(tmp_path), "vid", strategy="scene")

    assert len(frames) == config.KEYFRAME_MAX_LONG
    ts = [f.timestamp_sec for f in frames]
    assert ts[0] < 1.0, "first frame guaranteed"
    assert ts[-1] > RWY_DURATION - 1.0, "last frame guaranteed"
    assert _max_gap(ts) < 2 * RWY_DURATION / (config.KEYFRAME_MAX_LONG - 1)
    assert all(isinstance(f, KeyframeInfo) for f in frames)
