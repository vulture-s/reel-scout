"""`score` and `export --format bundle` must say "it did not happen" in their
exit code, because `batch` reads nothing else.

Both used to print the failure and exit 0. `batch`'s scoring pass then took a
scorer that had raised (unparseable reply, no analysis, invalid clip) as
scored -- no retry, `item_scored` emitted -- and its export step took a reel
skipped as too big as a finished bundle: a folder holding only an index that
says "Nothing bundled", recorded as done.
"""
import os

import pytest

from reel_scout import cli, db, scorer, validity


def _exit(argv):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
        raise SystemExit(0)
    return exc.value.code or 0


def _analyzed(conn, pid="abc", file_path=None):
    vid = db.upsert_video(conn, "youtube", pid, "https://youtu.be/" + pid,
                          title="t", file_path=file_path)
    db.save_analysis(conn, vid, summary="s", topics_json="[]", hooks_json="{}",
                     style_json="{}", engagement_signals_json="{}", full_json="{}")
    return vid


def test_score_unknown_video_exits_nonzero(temp_db):
    assert _exit(["score", "nosuchvideo"]) != 0


def test_score_without_analysis_exits_nonzero(temp_db):
    conn = db.get_connection()
    vid = db.upsert_video(conn, "youtube", "abc", "https://youtu.be/abc")
    assert _exit(["score", vid]) != 0


def test_score_invalid_clip_exits_nonzero(temp_db):
    conn = db.get_connection()
    vid = db.upsert_video(conn, "youtube", "abc", "https://youtu.be/abc")
    validity.mark_invalid(conn, vid, "zero frames")
    assert _exit(["score", vid]) != 0


def test_score_unparseable_reply_exits_nonzero(temp_db, monkeypatch):
    conn = db.get_connection()
    vid = _analyzed(conn)

    class _Broken:
        model = "m"

        def complete(self, *a, **k):
            return '{"hook_strength": 7 "pacing": 6}'

    monkeypatch.setattr(scorer, "get_llm", lambda *a, **k: _Broken())
    assert _exit(["score", vid]) != 0
    assert db.get_score(conn, vid) is None


def test_score_existing_score_still_exits_zero(temp_db):
    conn = db.get_connection()
    vid = _analyzed(conn)
    db.save_score(conn, vid, scorer.VideoScore(1, 1, 1, 1, 1, "r", "m"))
    assert _exit(["score", vid]) == 0


def test_bundle_export_of_a_skipped_reel_exits_nonzero(temp_db, tmp_path):
    conn = db.get_connection()
    media = tmp_path / "big.mp4"
    media.write_bytes(b"\0" * 300000)
    vid = _analyzed(conn, file_path=str(media))
    out = tmp_path / "student"
    assert _exit(["export", "--format", "bundle", "--video", vid,
                  "-o", str(out), "--max-mb", "0.1"]) != 0


def test_bundle_export_unknown_video_exits_nonzero(temp_db, tmp_path):
    assert _exit(["export", "--format", "bundle", "--video", "nosuchvideo",
                  "-o", str(tmp_path / "x")]) != 0


def test_bundle_export_that_writes_exits_zero(temp_db, tmp_path):
    conn = db.get_connection()
    vid = _analyzed(conn)
    out = tmp_path / "ok"
    assert _exit(["export", "--format", "bundle", "--video", vid, "-o", str(out)]) == 0
    assert any(n != "index.html" for n in os.listdir(str(out)))
