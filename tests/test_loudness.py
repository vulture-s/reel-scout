from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess

import pytest

from reel_scout import db
from reel_scout.audio import loudness

# Real ffmpeg 7 output (tail), trimmed: the per-frame lines above the summary
# carry the same "I:" / "LRA:" labels and must not be read.
SUMMARY = """\
[Parsed_ebur128_0 @ 0x6000] t: 111.0  TARGET:-23 LUFS    M: -12.0 S: -13.1     I: -14.0 LUFS       LRA:   7.0 LU  SPK:  -0.9  -0.8 dBFS  TPK:  -0.8  -0.7 dBTP
[Parsed_ebur128_0 @ 0x6000] Summary:

  Integrated loudness:
    I:         -14.3 LUFS
    Threshold: -25.0 LUFS

  Loudness range:
    LRA:         7.9 LU
    Threshold: -35.0 LUFS
    LRA low:   -19.8 LUFS
    LRA high:  -11.9 LUFS

  Sample peak:
    Peak:       -0.9 dBFS

  True peak:
    Peak:       -0.7 dBFS
"""


def test_parse_reads_the_summary_not_the_progress_line():
    r = loudness.parse_summary(SUMMARY)
    assert r == {"integrated_lufs": -14.3, "lra_lu": 7.9,
                 "sample_peak_dbfs": -0.9, "true_peak_dbtp": -0.7}


def test_parse_silence_and_inf_peak():
    s = SUMMARY.replace("-14.3 LUFS", "-70.0 LUFS").replace("Peak:       -0.9 dBFS", "Peak:       -inf dBFS")
    r = loudness.parse_summary(s)
    assert r["integrated_lufs"] == loudness.SILENCE_LUFS
    assert r["sample_peak_dbfs"] is None   # -inf is "no signal", not a number to average


def test_parse_without_summary_is_an_error():
    with pytest.raises(ValueError):
        loudness.parse_summary("[Parsed_ebur128_0] t: 1.0 I: -14.0 LUFS")


def test_schema_has_audio_loudness_and_roundtrips():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    conn.execute("INSERT INTO videos (id, platform, platform_id, url) VALUES ('v1','local','v1','x')")
    db.save_audio_loudness(conn, "v1", integrated_lufs=-14.3, lra_lu=7.9,
                           sample_peak_dbfs=-0.9, true_peak_dbtp=-0.7)
    row = db.get_audio_loudness(conn, "v1")
    assert row["integrated_lufs"] == -14.3 and row["true_peak_dbtp"] == -0.7
    db.save_audio_loudness(conn, "v1", integrated_lufs=-16.0, lra_lu=5.0,
                           sample_peak_dbfs=-2.0, true_peak_dbtp=-1.5)
    assert db.get_audio_loudness(conn, "v1")["integrated_lufs"] == -16.0   # replace, not append
    assert db.db_stats(conn)["audio_loudness"] == 1


def test_migration_from_v22_adds_the_table():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    conn.execute("DROP TABLE audio_loudness")
    conn.execute("UPDATE schema_version SET version = 22")
    conn.commit()
    db.init_db(conn)
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION
    conn.execute("SELECT * FROM audio_loudness")


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@needs_ffmpeg
def test_measure_reference_tone(tmp_path):
    # BS.1770 reference: a 997 Hz sine at -20 dBFS peak, mono, reads -23.0 LUFS
    # (K-weighting gain at 1 kHz cancels the -0.691 offset). Sample peak -20.
    # aevalsrc, not lavfi `sine`: `sine` has a fixed 1/8 amplitude (-18 dBFS),
    # so `sine` + volume=-20dB is a -38 dBFS tone and reads -41 LUFS.
    p = str(tmp_path / "tone.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "aevalsrc=0.1*sin(2*PI*997*t):s=48000:d=10",
                    "-ac", "1", "-c:a", "pcm_f32le", p], check=True)
    r = loudness.measure(p)
    assert r["integrated_lufs"] == pytest.approx(-23.0, abs=0.3)
    assert r["sample_peak_dbfs"] == pytest.approx(-20.0, abs=0.2)
    assert r["lra_lu"] == pytest.approx(0.0, abs=0.5)


@needs_ffmpeg
def test_measure_no_audio_stream(tmp_path):
    p = str(tmp_path / "video_only.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
                    "-pix_fmt", "yuv420p", p], check=True)
    with pytest.raises(loudness.NoAudio):
        loudness.measure(p)
