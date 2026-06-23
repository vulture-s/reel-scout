from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from reel_scout.vision.keyframe import (
    KeyframeInfo,
    _ensure_first_last,
    _scale_vf,
    _seek_args,
    auto_frame_budget,
)
from reel_scout import config


class TestKeyframeInfoHasScore:
    def test_keyframe_info_has_score(self) -> None:
        kf = KeyframeInfo(
            frame_index=0,
            timestamp_sec=1.0,
            file_path="/tmp/frame.jpg",
            strategy="scene",
        )
        assert hasattr(kf, "score")
        assert kf.score == 0.0

    def test_keyframe_info_custom_score(self) -> None:
        kf = KeyframeInfo(
            frame_index=0,
            timestamp_sec=1.0,
            file_path="/tmp/frame.jpg",
            strategy="scene",
            score=0.85,
        )
        assert kf.score == 0.85


class TestEnsureFirstLast:
    @patch("reel_scout.vision.keyframe.subprocess.run")
    @patch("reel_scout.vision.keyframe.os.path.exists", return_value=True)
    def test_ensure_first_last_adds_first(
        self, mock_exists: MagicMock, mock_run: MagicMock,
    ) -> None:
        frames = [
            KeyframeInfo(0, 5.0, "/tmp/f1.jpg", "scene", 0.5),
            KeyframeInfo(1, 10.0, "/tmp/f2.jpg", "scene", 0.8),
        ]
        result = _ensure_first_last(
            "/tmp/video.mp4", "/tmp/out", "vid1", frames, 10, 15.0,
        )
        # First frame should be prepended (timestamp 0.1)
        assert result[0].timestamp_sec == 0.1
        assert result[0].strategy == "first"
        # Last frame should be appended (timestamp 14.5)
        assert result[-1].timestamp_sec == 14.5
        assert result[-1].strategy == "last"
        assert len(result) == 4

    @patch("reel_scout.vision.keyframe.subprocess.run")
    def test_ensure_first_last_no_change(self, mock_run: MagicMock) -> None:
        frames = [
            KeyframeInfo(0, 0.2, "/tmp/f0.jpg", "scene", 0.5),
            KeyframeInfo(1, 5.0, "/tmp/f1.jpg", "scene", 0.8),
            KeyframeInfo(2, 9.5, "/tmp/f2.jpg", "scene", 0.6),
        ]
        result = _ensure_first_last(
            "/tmp/video.mp4", "/tmp/out", "vid1", frames, 10, 10.0,
        )
        # No change expected: 0.2 < 0.5 and 9.5 > (10.0 - 1.0)
        assert len(result) == 3
        mock_run.assert_not_called()

    @patch("reel_scout.vision.keyframe.subprocess.run")
    @patch("reel_scout.vision.keyframe.os.path.exists", return_value=True)
    def test_ensure_first_last_trims_middle(
        self, mock_exists: MagicMock, mock_run: MagicMock,
    ) -> None:
        frames = [
            KeyframeInfo(0, 3.0, "/tmp/f0.jpg", "scene", 0.2),
            KeyframeInfo(1, 5.0, "/tmp/f1.jpg", "scene", 0.9),
            KeyframeInfo(2, 7.0, "/tmp/f2.jpg", "scene", 0.1),
        ]
        # max_frames=4: after adding first+last we get 5, trim to 4
        result = _ensure_first_last(
            "/tmp/video.mp4", "/tmp/out", "vid1", frames, 4, 20.0,
        )
        assert len(result) == 4
        # The frame with lowest score (0.1 at 7.0) should be removed
        timestamps = [f.timestamp_sec for f in result]
        assert 7.0 not in timestamps


class TestAutoFrameBudget:
    def test_full_scan_curve(self) -> None:
        # claude-video full-scan table (pre-fps-cap on long clips)
        assert auto_frame_budget(20) == 30
        assert auto_frame_budget(45) == 40
        assert auto_frame_budget(120) == 60
        assert auto_frame_budget(300) == 80
        assert auto_frame_budget(900) == 100

    def test_focused_curve_is_denser(self) -> None:
        assert auto_frame_budget(45, focused=True) == 80
        assert auto_frame_budget(45, focused=False) == 40

    def test_hard_ceiling_100(self) -> None:
        assert auto_frame_budget(99999) == 100
        assert auto_frame_budget(99999, focused=True) == 100

    def test_fps_cap_short_clip(self) -> None:
        # <=2 fps: a 2s clip can supply at most 4 frames
        assert auto_frame_budget(2) == 4
        # 3s focused window: table says 10 but fps cap is 6
        assert auto_frame_budget(3, focused=True) == 6

    def test_unknown_duration(self) -> None:
        assert auto_frame_budget(0) == 30
        assert auto_frame_budget(-5) == 30

    @patch("reel_scout.vision.keyframe._get_duration", return_value=900.0)
    @patch("reel_scout.vision.keyframe._extract_scene", return_value=[])
    @patch("reel_scout.vision.keyframe._ensure_first_last", side_effect=lambda *a, **k: a[3])
    @patch("reel_scout.vision.keyframe.os.makedirs")
    def test_auto_budget_clamped_to_keyframe_max(
        self,
        mock_makedirs: MagicMock,
        mock_ensure: MagicMock,
        mock_scene: MagicMock,
        mock_duration: MagicMock,
    ) -> None:
        # COST RED LINE: even a 15-min clip (raw budget 100) must clamp to KEYFRAME_MAX
        from reel_scout.vision.keyframe import extract_keyframes

        extract_keyframes("/tmp/v.mp4", "/tmp/out", "vid1", strategy="scene", max_frames=0)
        # _extract_scene called with the clamped budget, not 100
        called_max = mock_scene.call_args[0][3]
        assert called_max == config.KEYFRAME_MAX


class TestScaleAndSeekHelpers:
    def test_scale_vf(self) -> None:
        assert _scale_vf(0) == ""
        assert _scale_vf(1024) == "scale=1024:-2"

    def test_seek_args(self) -> None:
        assert _seek_args(0, 0) == []
        assert _seek_args(5, 0) == ["-ss", "5"]
        assert _seek_args(5, 10) == ["-ss", "5", "-to", "10"]
        assert _seek_args(0, 10) == ["-to", "10"]

    @patch("reel_scout.vision.keyframe._get_duration", return_value=30.0)
    @patch("reel_scout.vision.keyframe.os.path.exists", return_value=True)
    @patch("reel_scout.vision.keyframe.os.makedirs")
    @patch("reel_scout.vision.keyframe.subprocess.run")
    def test_resolution_appended_to_scene_vf(
        self,
        mock_run: MagicMock,
        mock_makedirs: MagicMock,
        mock_exists: MagicMock,
        mock_duration: MagicMock,
    ) -> None:
        from reel_scout.vision.keyframe import extract_keyframes

        mock_result = MagicMock()
        mock_result.stderr = ""
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        extract_keyframes(
            "/tmp/v.mp4", "/tmp/out", "vid1",
            strategy="scene", max_frames=4, resolution=1024,
        )
        cmd = mock_run.call_args_list[0][0][0]
        vf = cmd[cmd.index("-vf") + 1]
        assert "scale=1024:-2" in vf
        assert "showinfo" in vf

    @patch("reel_scout.vision.keyframe._get_duration", return_value=30.0)
    @patch("reel_scout.vision.keyframe.os.path.exists", return_value=True)
    @patch("reel_scout.vision.keyframe.os.makedirs")
    @patch("reel_scout.vision.keyframe.subprocess.run")
    def test_focus_window_adds_seek_args(
        self,
        mock_run: MagicMock,
        mock_makedirs: MagicMock,
        mock_exists: MagicMock,
        mock_duration: MagicMock,
    ) -> None:
        from reel_scout.vision.keyframe import extract_keyframes

        mock_result = MagicMock()
        mock_result.stderr = ""
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        extract_keyframes(
            "/tmp/v.mp4", "/tmp/out", "vid1",
            strategy="scene", max_frames=4, start_sec=5.0, end_sec=10.0,
        )
        cmd = mock_run.call_args_list[0][0][0]
        assert "-ss" in cmd and "5.0" in cmd
        assert "-to" in cmd and "10.0" in cmd


class TestMotionStrategy:
    def test_motion_strategy_name(self) -> None:
        kf = KeyframeInfo(
            frame_index=0,
            timestamp_sec=2.0,
            file_path="/tmp/motion.jpg",
            strategy="motion",
            score=1.0,
        )
        assert kf.strategy == "motion"

    @patch("reel_scout.vision.keyframe._get_duration", return_value=30.0)
    @patch("reel_scout.vision.keyframe.os.path.exists", return_value=True)
    @patch("reel_scout.vision.keyframe.os.makedirs")
    @patch("reel_scout.vision.keyframe.subprocess.run")
    def test_extract_keyframes_motion(
        self,
        mock_run: MagicMock,
        mock_makedirs: MagicMock,
        mock_exists: MagicMock,
        mock_duration: MagicMock,
    ) -> None:
        from reel_scout.vision.keyframe import extract_keyframes

        # Simulate ffmpeg showinfo output with pts_time
        mock_result = MagicMock()
        mock_result.stderr = (
            "[Parsed_showinfo] n:0 pts:0 pts_time:1.5\n"
            "[Parsed_showinfo] n:1 pts:90000 pts_time:3.0\n"
        )
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        frames = extract_keyframes(
            "/tmp/video.mp4", "/tmp/out", "vid1",
            strategy="motion", max_frames=8,
        )
        # Should have called ffmpeg with mpdecimate
        first_call_args = mock_run.call_args_list[0]
        cmd = first_call_args[0][0]
        vf_arg = cmd[cmd.index("-vf") + 1]
        assert "mpdecimate" in vf_arg
