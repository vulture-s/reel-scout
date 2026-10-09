"""The post around a clip (schema v20): storage, the viewer's "queue analysis"
button, and `reel-scout pending`.

The rule these pin, end to end: the first video is analyzed, photos are
stored, other videos are listed -- and the viewer may *ask* for one of those
to be analyzed but never runs the pipeline itself.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from reel_scout import cli, config, db, inspector
from reel_scout.crawl.base import VideoMeta

POST_URL = "https://www.threads.com/@someone/post/DaAaAaAaAaA"


def _conn(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _items(photo_path):
    return [
        {"idx": 1, "kind": "image", "url": "https://cdn.example/p1.jpg",
         "width": 1080, "height": 1350, "file_path": photo_path},
        {"idx": 2, "kind": "video", "url": "https://cdn.example/v2.mp4",
         "width": 720, "height": 1280, "file_path": "/v/th_DaAaAaAaAaA_m2.mp4"},
        {"idx": 3, "kind": "video", "url": "https://cdn.example/v3.mp4",
         "width": 720, "height": 1280},
    ]


def _post_meta(photo_path="", likes="323"):
    return VideoMeta(
        platform="threads", platform_id="DaAaAaAaAaA", url=POST_URL,
        title="caption", uploader="someone",
        extra={"post_code": "DaAaAaAaAaA", "caption": "full caption\nline 2",
               "self_thread": json.dumps(["part 2"]), "like_count": likes,
               "reply_count": "13", "repost_count": "37", "quote_count": "1",
               "media_type": "8", "resolved_url": POST_URL, "analyzed_idx": "2",
               "post_media_json": json.dumps(_items(photo_path))})


def _store_post(conn, meta=None):
    meta = meta or _post_meta()
    vid = db.upsert_video(conn, platform="threads", platform_id="DaAaAaAaAaA",
                          url=POST_URL, title="caption", uploader="someone")
    db.save_crawl_extras(conn, vid, meta)
    return vid


def _store_item(conn, idx):
    url = POST_URL + "?media=%d" % idx
    vid = db.upsert_video(conn, platform="threads", platform_id="DaAaAaAaAaA#%d" % idx,
                          url=url, title="caption", uploader="someone")
    db.save_crawl_extras(conn, vid, VideoMeta(
        platform="threads", platform_id="DaAaAaAaAaA#%d" % idx, url=url,
        extra={"post_code": "DaAaAaAaAaA", "media_index": str(idx)}))
    return vid


# --- storage ---------------------------------------------------------------

def test_post_text_counts_and_media_are_stored(temp_db):
    conn = _conn(temp_db)
    vid = _store_post(conn)
    post = db.get_post(conn, vid)
    assert post["caption"] == "full caption\nline 2"
    assert post["self_thread"] == ["part 2"]
    assert (post["like_count"], post["reply_count"]) == (323, 13)
    assert post["fetched_at"]
    assert [(m["idx"], m["kind"]) for m in post["media"]] == [
        (1, "image"), (2, "video"), (3, "video")]
    assert post["media"][1]["analyzed_video_id"] == vid     # the first video
    assert post["media"][2]["analyzed_video_id"] is None


def test_recrawl_refreshes_counts_but_keeps_item_analyses(temp_db):
    conn = _conn(temp_db)
    vid = _store_post(conn)
    item = _store_item(conn, 3)
    _store_post(conn, _post_meta(likes="999"))
    post = db.get_post(conn, vid)
    assert post["like_count"] == 999
    assert post["media"][2]["analyzed_video_id"] == item


def test_item_row_resolves_to_its_parent_post(temp_db):
    conn = _conn(temp_db)
    vid = _store_post(conn)
    item = _store_item(conn, 3)
    assert db.get_post(conn, item)["video_id"] == vid


def test_crawler_without_post_data_is_a_no_op(temp_db):
    conn = _conn(temp_db)
    vid = db.upsert_video(conn, platform="instagram", platform_id="X", url="https://i/x")
    db.save_crawl_extras(conn, vid, VideoMeta(platform="instagram"))
    assert db.get_post(conn, vid) is None


def test_fresh_and_migrated_databases_both_have_the_tables(temp_db):
    conn = _conn(temp_db)
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION == 20
    conn.execute("UPDATE schema_version SET version = 19")
    conn.execute("DROP TABLE post_meta")
    conn.commit()
    db.init_db(conn)
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 20
    conn.execute("SELECT * FROM post_meta")


# --- requests --------------------------------------------------------------

def test_request_is_idempotent_and_refuses_what_it_cannot_analyze(temp_db):
    conn = _conn(temp_db)
    vid = _store_post(conn)
    assert db.request_analysis(conn, vid, 3)["status"] == "pending"
    db.request_analysis(conn, vid, 3)
    assert len(db.list_analysis_requests(conn)) == 1
    with pytest.raises(db.PostRequestError, match="image"):
        db.request_analysis(conn, vid, 1)
    with pytest.raises(db.PostRequestError) as exc:
        db.request_analysis(conn, vid, 2)                  # already analyzed
    assert exc.value.status == 409
    with pytest.raises(db.PostRequestError) as exc:
        db.request_analysis(conn, vid, 9)
    assert exc.value.status == 404


def test_failed_request_is_rearmed(temp_db):
    conn = _conn(temp_db)
    vid = _store_post(conn)
    req = db.request_analysis(conn, vid, 3)
    db.set_analysis_request(conn, req["id"], "failed", "boom")
    assert db.request_analysis(conn, vid, 3)["status"] == "pending"


def _pending_args(**kw):
    base = dict(run=False, all=False, no_score=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_pending_run_marks_done_only_when_the_db_says_analyzed(temp_db):
    conn = _conn(temp_db)
    vid = _store_post(conn)
    db.request_analysis(conn, vid, 3)
    conn.close()

    calls = []

    def fake_run(urls, options):
        calls.append((urls, options.score))
        c = _conn(temp_db)
        item = _store_item(c, 3)
        db.update_video_status(c, item, "analyzed")
        c.close()
        return 0

    with patch("reel_scout.analyze.pipeline.run", side_effect=fake_run):
        assert cli._cmd_pending(_pending_args(run=True)) is None
    assert calls == [([POST_URL + "?media=3"], True)]
    conn = _conn(temp_db)
    assert db.list_analysis_requests(conn, status="done")[0]["media_idx"] == 3


def test_pending_run_records_failure_when_no_analyzed_row(temp_db):
    conn = _conn(temp_db)
    vid = _store_post(conn)
    db.request_analysis(conn, vid, 3)
    conn.close()
    with patch("reel_scout.analyze.pipeline.run", return_value=1):
        assert cli._cmd_pending(_pending_args(run=True)) == 1
    conn = _conn(temp_db)
    assert db.list_analysis_requests(conn, status="failed")[0]["error"]


def test_pending_without_run_only_lists(temp_db):
    conn = _conn(temp_db)
    vid = _store_post(conn)
    db.request_analysis(conn, vid, 3)
    conn.close()
    with patch("reel_scout.analyze.pipeline.run") as run:
        cli._cmd_pending(_pending_args())
    run.assert_not_called()


# --- viewer ----------------------------------------------------------------

def test_export_shows_the_post_text_but_offers_no_button(temp_db):
    conn = _conn(temp_db)
    vid = _store_post(conn)
    page = inspector.render_inspector(inspector.build_inspect_view(conn, vid))
    assert "full caption<br>line 2" in page
    assert "part 2" in page
    assert "reqan" not in page and "/api/post-media/" not in page


def test_live_page_button_queues_and_never_runs_the_pipeline(temp_db):
    photo = os.path.join(config.DATA_DIR, "p1.jpg")
    with open(photo, "wb") as f:
        f.write(b"\xff\xd8\xff\xe0jpeg")
    conn = _conn(temp_db)
    vid = _store_post(conn, _post_meta(photo_path=photo))
    conn.close()

    httpd = inspector.make_inspect_server(port=0)
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        page = urllib.request.urlopen(base + "/inspect/%s" % vid, timeout=5).read().decode()
        assert 'data-idx="3"' in page          # the unanalyzed video gets a button
        assert 'data-idx="2"' not in page      # the analyzed one does not
        media_id = _conn(temp_db).execute(
            "SELECT id FROM post_media WHERE idx = 1").fetchone()[0]
        img = urllib.request.urlopen(base + "/api/post-media/%s" % media_id, timeout=5)
        assert img.read().startswith(b"\xff\xd8")

        with patch("reel_scout.analyze.pipeline.run") as run:
            req = urllib.request.Request(base + "/api/request-analysis/%s/3" % vid,
                                         data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json"})
            body = json.loads(urllib.request.urlopen(req, timeout=5).read())
            run.assert_not_called()
        assert body == {"status": "pending", "media_idx": 3}

        bad = urllib.request.Request(base + "/api/request-analysis/%s/1" % vid,
                                     data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(bad, timeout=5)
        assert exc.value.code == 400

        again = urllib.request.urlopen(base + "/inspect/%s" % vid, timeout=5).read().decode()
        assert 'data-idx="3"' not in again     # now shows "queued" instead
    finally:
        httpd.shutdown()
        httpd.server_close()
