"""ffprobe is found next to ffmpeg by file name, not by string surgery (2026-10-09).

Every probe derived its binary as `config.FFMPEG_BIN.replace("ffmpeg",
"ffprobe")`. With the default bare `ffmpeg` that is fine; with a full path it
also rewrites every directory that happens to contain "ffmpeg":

    /opt/homebrew/Cellar/ffmpeg/7.1/bin/ffmpeg -> .../Cellar/ffprobe/7.1/bin/ffprobe
    C:\\ffmpeg\\bin\\ffmpeg.exe               -> C:\\ffprobe\\bin\\ffprobe.exe

`probe_duration` swallowed the resulting OSError and returned None, so every
duration, codec and audio-stream probe went quietly blank, and keyframe
extraction -- which did not catch it -- died with FileNotFoundError.
"""
from __future__ import annotations

import ntpath
import os
import posixpath

import pytest

from reel_scout import config, ffprobe
from reel_scout.vision import keyframe


@pytest.mark.parametrize("ffmpeg,expected", [
    ("ffmpeg", "ffprobe"),
    ("/opt/homebrew/bin/ffmpeg", "/opt/homebrew/bin/ffprobe"),
    ("/opt/homebrew/Cellar/ffmpeg/7.1/bin/ffmpeg",
     "/opt/homebrew/Cellar/ffmpeg/7.1/bin/ffprobe"),
    ("/x/ffmpeg-7.1-full_build/bin/ffmpeg", "/x/ffmpeg-7.1-full_build/bin/ffprobe"),
])
def test_only_the_file_name_changes_posix(monkeypatch, ffmpeg, expected):
    monkeypatch.setattr(config, "FFMPEG_BIN", ffmpeg)
    monkeypatch.delenv("FFPROBE_BIN", raising=False)
    assert ffprobe.ffprobe_bin(pathmod=posixpath) == expected


@pytest.mark.parametrize("ffmpeg,expected", [
    (r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffprobe.exe"),
    (r"C:\tools\ffmpeg-7.1-full_build\bin\FFMPEG.EXE",
     r"C:\tools\ffmpeg-7.1-full_build\bin\ffprobe.EXE"),
])
def test_only_the_file_name_changes_windows(monkeypatch, ffmpeg, expected):
    monkeypatch.setattr(config, "FFMPEG_BIN", ffmpeg)
    monkeypatch.delenv("FFPROBE_BIN", raising=False)
    assert ffprobe.ffprobe_bin(pathmod=ntpath) == expected


def test_an_explicit_ffprobe_bin_wins(monkeypatch):
    monkeypatch.setattr(config, "FFMPEG_BIN", "/a/ffmpeg/ffmpeg")
    monkeypatch.setenv("FFPROBE_BIN", "/b/ffprobe")
    assert ffprobe.ffprobe_bin() == "/b/ffprobe"


def test_every_probe_uses_the_helper(monkeypatch):
    seen = []

    def fake_run(cmd, *a, **k):
        seen.append(cmd[0])
        raise OSError("stop")

    monkeypatch.setattr(config, "FFMPEG_BIN", "/opt/homebrew/Cellar/ffmpeg/7.1/bin/ffmpeg")
    monkeypatch.delenv("FFPROBE_BIN", raising=False)
    monkeypatch.setattr(ffprobe.subprocess, "run", fake_run)
    monkeypatch.setattr(keyframe.subprocess, "run", fake_run)
    ffprobe.probe_duration("x.mp4")
    for name in ("probe_audio_stream_count", "probe_video_codec", "probe_dimensions"):
        try:
            getattr(ffprobe, name)("x.mp4")
        except OSError:
            pass
    try:
        keyframe._get_duration("x.mp4")
    except OSError:
        pass
    assert len(seen) == 5, seen
    assert all(c == "/opt/homebrew/Cellar/ffmpeg/7.1/bin/ffprobe" for c in seen), seen
