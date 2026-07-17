from __future__ import annotations

from unittest.mock import MagicMock, patch

from reel_scout import shots
from reel_scout.shots import compute_shot_metrics, metrics_from_cuts, parse_cut_count


def test_parse_cut_count():
    stderr = (
        "[Parsed_showinfo] n:0 pts_time:1.5 ...\n"
        "[Parsed_showinfo] n:1 pts_time:3.2 ...\n"
        "[Parsed_showinfo] n:2 pts_time:9.9 ...\n"
    )
    assert parse_cut_count(stderr) == 3
    assert parse_cut_count("no scene changes here") == 0


def test_metrics_from_cuts_static_clip():
    # A single-shot clip: 0 cuts -> 1 shot spanning the whole duration.
    m = metrics_from_cuts(0, 30.0)
    assert m.shot_count == 1
    assert m.cuts_per_minute == 0.0
    assert m.avg_shot_sec == 30.0
    assert m.duration_sec == 30.0


def test_metrics_from_cuts_multi():
    # 9 cuts in 30s -> 18 cuts/min, 10 shots, 3.0s avg shot.
    m = metrics_from_cuts(9, 30.0)
    assert m.shot_count == 10
    assert m.cuts_per_minute == 18.0
    assert m.avg_shot_sec == 3.0


def test_compute_shot_metrics_mocked():
    fake = MagicMock()
    fake.stderr = "pts_time:1.0\npts_time:2.0\npts_time:3.0\n"
    with patch("reel_scout.shots.subprocess.run", return_value=fake), \
         patch("reel_scout.shots._probe_duration", return_value=60.0):
        m = compute_shot_metrics("/fake.mp4")
    assert m is not None
    assert m.shot_count == 4        # 3 cuts + 1
    assert m.cuts_per_minute == 3.0  # 3 cuts in 1 minute
    assert m.duration_sec == 60.0


def test_compute_shot_metrics_uses_passed_duration():
    fake = MagicMock()
    fake.stderr = "pts_time:1.0\n"
    with patch("reel_scout.shots.subprocess.run", return_value=fake) as run, \
         patch("reel_scout.shots._probe_duration") as probe:
        m = compute_shot_metrics("/fake.mp4", duration_sec=120.0)
    probe.assert_not_called()  # no re-probe when duration is supplied
    assert m.cuts_per_minute == 0.5  # 1 cut in 2 minutes
    assert run.called


def test_compute_shot_metrics_no_duration_returns_none():
    with patch("reel_scout.shots._probe_duration", return_value=None):
        assert compute_shot_metrics("/fake.mp4") is None


def test_compute_shot_metrics_ffmpeg_failure_returns_none():
    with patch("reel_scout.shots._probe_duration", return_value=30.0), \
         patch("reel_scout.shots.subprocess.run", side_effect=OSError("no ffmpeg")):
        assert compute_shot_metrics("/fake.mp4") is None
