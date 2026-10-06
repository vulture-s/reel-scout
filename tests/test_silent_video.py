"""A clip with no audio stream must not crash transcription.

Found 2026-10-05 on a real Threads carousel whose three videos were all
silent: faster-whisper decodes through PyAV, which asks for audio stream 0
unconditionally, and died with ``IndexError: tuple index out of range``. It
reproduced on a plain local file, so it was never a Threads problem -- it was
"no audio stream" being unhandled anywhere.

The rule pinned here: zero audio streams -> an empty transcript that names the
reason, Whisper is never called, and the pipeline carries on to the visual
steps. A probe that *fails* is not silence and must still reach Whisper.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from reel_scout import config, db, ffprobe
from reel_scout.analyze import pipeline
from reel_scout.transcribe.base import Segment, TranscriptResult


# --- the probe ---------------------------------------------------------------

def _run(stdout="", rc=0):
    return MagicMock(returncode=rc, stdout=stdout)


@pytest.mark.parametrize("result,expect", [
    (_run(""), 0),                 # video-only file: ffprobe succeeds, lists nothing
    (_run("1\n"), 1),
    (_run("1\n2\n"), 2),
    (_run("", rc=1), None),        # unreadable file: unknown, NOT silent
])
def test_probe_audio_stream_count(result, expect):
    with patch("reel_scout.ffprobe.subprocess.run", return_value=result):
        assert ffprobe.probe_audio_stream_count("x.mp4") == expect


def test_probe_that_cannot_run_is_unknown_not_silent():
    with patch("reel_scout.ffprobe.subprocess.run", side_effect=OSError("no ffprobe")):
        assert ffprobe.probe_audio_stream_count("x.mp4") is None


# --- the pipeline step -------------------------------------------------------

class _Stop(Exception):
    """Raised at the first call after transcription, so only that step runs."""


def _transcribe_step(temp_db, audio_streams):
    path = os.path.join(config.DATA_DIR, "clip.mp4")
    with open(path, "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42")
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    transcriber = MagicMock()
    transcriber.transcribe.return_value = TranscriptResult(
        language="zh", text_full="hello", segments=[Segment(0.0, 1.0, "hello")],
        model="large-v3")
    with patch.object(ffprobe, "probe_audio_stream_count", return_value=audio_streams), \
         patch.object(pipeline, "get_transcriber", return_value=transcriber), \
         patch.object(db, "get_keyframes", side_effect=_Stop):
        with pytest.raises(_Stop):
            pipeline._process_single(conn, path, pipeline.PipelineOptions(skip_vision=True))
    video_id = db.get_video_by_url(conn, os.path.abspath(path))["id"]
    return db.get_transcript(conn, video_id), transcriber


def test_no_audio_stream_skips_whisper_and_records_why(temp_db):
    transcript, transcriber = _transcribe_step(temp_db, audio_streams=0)
    transcriber.transcribe.assert_not_called()
    assert transcript is not None                    # stored, so not retried every run
    assert transcript["text_full"] == ""
    assert transcript["whisper_model"] == "none:no-audio-stream"


def test_clip_with_audio_still_goes_to_whisper(temp_db):
    transcript, transcriber = _transcribe_step(temp_db, audio_streams=1)
    transcriber.transcribe.assert_called_once()
    assert transcript["text_full"] == "hello"


def test_failed_probe_still_goes_to_whisper(temp_db):
    transcript, transcriber = _transcribe_step(temp_db, audio_streams=None)
    transcriber.transcribe.assert_called_once()


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                    reason="needs ffmpeg + ffprobe")
def test_probe_on_a_real_video_only_file(tmp_path):
    """The mocked cases above assume ffprobe prints nothing for a video-only
    file. Check that against a real one."""
    out = tmp_path / "silent.mp4"
    made = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        capture_output=True)
    if made.returncode != 0:
        pytest.skip("ffmpeg could not build a test clip")
    assert ffprobe.probe_audio_stream_count(str(out)) == 0
