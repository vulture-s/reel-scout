"""A local file whose content changed at the same path is a new clip.

Local sources are keyed by a content hash so the same file at two paths dedups.
But Step 1 looked the row up by URL (= absolute path) first, so re-exporting an
edit to the same filename hit the old row, skipped every stage as "already
done", and served the new cut next to the old cut's transcript, frames,
analysis and score.
"""
import pytest

from reel_scout import db
from reel_scout.analyze import pipeline


class _Reached(Exception):
    pass


def _step1(conn, monkeypatch, path):
    """Run _process_single up to the first post-download stage; return its id."""
    def stop(_conn, video_id, *a, **k):
        raise _Reached(video_id)

    monkeypatch.setattr(db, "get_keyframes", stop)
    opts = pipeline.PipelineOptions(skip_transcribe=True)
    with pytest.raises(_Reached) as hit:
        pipeline._process_single(conn, pipeline._normalize_source(path), opts)
    return hit.value.args[0]


def test_recut_at_same_path_is_analyzed_as_a_new_clip(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_probe_duration", lambda p: 10.0)
    f = tmp_path / "my_reel.mp4"
    f.write_bytes(b"draft one")
    conn = db.get_connection()
    first = _step1(conn, monkeypatch, str(f))

    f.write_bytes(b"draft two -- recut")
    second = _step1(conn, monkeypatch, str(f))

    assert second != first
    assert db.get_video(conn, second)["platform_id"] == pipeline._hash_file(str(f))


def test_unchanged_local_file_still_reuses_its_row(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_probe_duration", lambda p: 10.0)
    f = tmp_path / "same.mp4"
    f.write_bytes(b"identical bytes")
    conn = db.get_connection()
    assert _step1(conn, monkeypatch, str(f)) == _step1(conn, monkeypatch, str(f))
