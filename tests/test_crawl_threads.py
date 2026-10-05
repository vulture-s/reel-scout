"""ThreadsCrawler contract.

The fixtures are synthetic but shaped like the real server-rendered pages
measured 2026-10-05 (five queued posts, three media layouts). Real captions
and usernames stay out of the repo; the *nesting* is what these tests pin --
the root post at ``result.data.media`` under ``require``/``__bbox`` arrays,
with replies and the author's follow-ups nested inside it.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from reel_scout.crawl import detect_platform, get_crawler
from reel_scout.crawl.threads import (
    ThreadsCrawler, parse_post, pick_videos, post_texts,
)

POST_URL = "https://www.threads.com/@someone/post/DaAaAaAaAaA"
SHARE_URL = "https://www.threads.com/share/_xYz123/"


def _vv(name):
    return [{"type": 101, "url": "https://cdn.example/%s.mp4?sig=1" % name}]


def _node(code, user, text, **kw):
    node = {"code": code, "user": {"username": user},
            "caption": {"text": text}, "text_post_app_info": {}}
    node.update(kw)
    return node


def _wrap(media):
    return {"require": [["x", "y", None, [{"__bbox": {"require": [
        ["a", "b", None, [None, {"__bbox": {"result": {"data": {"media": media}}}}]]
    ]}}]]]}


def _page(post):
    """Lay ``post`` out the way Threads does: one post streamed as several
    script blocks sharing an ``id`` -- core fields (with ``code``) first, then
    a separate fragment carrying the replies and the author's follow-ups."""
    post = dict(post)
    tpi = dict(post.get("text_post_app_info") or {})
    late = {k: tpi.pop(k) for k in ("self_thread", "direct_replies") if k in tpi}
    post["text_post_app_info"] = tpi
    blocks = [
        {"other": "blob"},
        _wrap({"id": post["id"], "text_post_app_info": {"impression_count": 9}}),
        _wrap(post),
        _wrap({"id": "someone_elses_post", "text_post_app_info": {
            "self_thread": {"posts": {"edges": [{"node": _node(
                "DOther00001", "other", "not ours")}]}}}}),
        _wrap({"id": post["id"], "text_post_app_info": late}),
    ]
    return "<html><body>%s</body></html>" % "".join(
        '<script type="application/json" data-sjs>%s</script>' % json.dumps(b)
        for b in blocks)


def _root(**kw):
    reply = _node("DReply00001", "stranger", "nice", video_versions=_vv("reply"))
    follow = _node("DFollow0001", "someone", "part 2 of the thread")
    tpi = {
        "direct_reply_count": 13, "repost_count": 37, "quote_count": 1,
        "direct_replies": {"edges": [{"node": {"posts": {"edges": [{"node": reply}]}}}]},
        "self_thread": {"posts": {"edges": [{"node": follow}]}},
    }
    base = dict(media_type=2, video_versions=_vv("root"), like_count=323,
                taken_at=1786003273, text_post_app_info=tpi)
    base.update(kw)
    post = _node("DaAaAaAaAaA", "someone", "the caption, in full",
                 id="3957_6304", **base)
    post["text_post_app_info"] = tpi
    return post


# --- routing ---------------------------------------------------------------

@pytest.mark.parametrize("url", [
    POST_URL, SHARE_URL, "https://www.threads.net/@someone/post/DaAaAaAaAaA",
])
def test_threads_urls_route_to_threads_crawler(url):
    assert detect_platform(url) == "threads"
    assert isinstance(get_crawler(url), ThreadsCrawler)


def test_extract_id_post_and_share():
    c = ThreadsCrawler()
    assert c.extract_id(POST_URL) == "DaAaAaAaAaA"
    assert c.extract_id(SHARE_URL) == "_xYz123"
    with pytest.raises(ValueError):
        c.extract_id("https://www.threads.com/@someone")


# --- parsing ---------------------------------------------------------------

def test_parse_post_returns_root_not_a_reply():
    """Replies carry ``code``/``caption``/``video_versions`` too. Picking one
    would analyze a stranger's clip under the author's URL."""
    post = parse_post(_page(_root()))
    assert post["code"] == "DaAaAaAaAaA"
    assert pick_videos(post)[0]["video_versions"][0]["url"].endswith("root.mp4?sig=1")


def test_login_wall_shell_fails_loud():
    """What browsers and plain curl get: a page with JSON blobs but no post.
    Must raise -- an empty meta would flow on as a 'successful' crawl."""
    shell = '<html><script type="application/json">{"login": true}</script></html>'
    with pytest.raises(RuntimeError, match="THREADS_USER_AGENT"):
        parse_post(shell)


@pytest.mark.parametrize("layout,expect", [
    ("single", ["root"]),
    ("carousel", ["c1", "c3"]),
    ("inline", ["inline"]),
    ("text_only", []),
])
def test_pick_videos_covers_the_three_observed_layouts(layout, expect):
    if layout == "single":
        post = _root()
    elif layout == "carousel":  # media_type 8; image items have no video
        post = _root(media_type=8, video_versions=None, carousel_media=[
            {"video_versions": _vv("c1")}, {"image_versions2": {}},
            {"video_versions": _vv("c3")}])
    elif layout == "inline":    # media_type 19: text post + linked inline video
        post = _root(media_type=19, video_versions=None)
        post["text_post_app_info"]["linked_inline_media"] = {"video_versions": _vv("inline")}
    else:
        post = _root(media_type=19, video_versions=None)
    got = [v["video_versions"][0]["url"].split("/")[-1].split(".")[0]
           for v in pick_videos(post)]
    assert got == expect


def test_follow_ups_streamed_in_a_later_fragment_are_merged_back():
    """Live pages put ``self_thread`` in a separate block from the caption.
    Reading only the block with ``code`` returned 0 follow-ups for a post that
    had one -- and nothing failed. Fragments of *other* posts must not leak in."""
    caption, follow = post_texts(parse_post(_page(_root())))
    assert caption == "the caption, in full"
    assert follow == ["part 2 of the thread"]  # the stranger's reply is not here


# --- download --------------------------------------------------------------

def _download(post, tmp_path):
    page = _page(post).encode("utf-8")

    def fake_fetch(url, ua, timeout=60):
        if "cdn.example" in url:
            return url, b"\x00\x00\x00\x18ftypmp42"
        assert ua == "UA-under-test"
        return "https://www.threads.com/@someone/post/DaAaAaAaAaA?xmt=1", page

    with patch("reel_scout.crawl.threads._fetch", side_effect=fake_fetch), \
         patch("reel_scout.crawl.threads.get_limiter"), \
         patch("reel_scout.crawl.threads.config.THREADS_USER_AGENT", "UA-under-test"), \
         patch("reel_scout.crawl.threads.ffprobe.probe_duration", return_value=68.3), \
         patch("reel_scout.crawl.threads.ffprobe.warn_if_not_apple_playable"):
        return ThreadsCrawler().download(SHARE_URL, output_dir=str(tmp_path))


def test_download_resolves_share_link_to_post_code_and_keeps_the_post(tmp_path):
    meta = _download(_root(), tmp_path)
    assert meta.platform == "threads"
    assert meta.platform_id == "DaAaAaAaAaA"        # not the share token
    assert meta.url == SHARE_URL
    assert meta.uploader == "someone"
    assert meta.title == "the caption, in full"
    assert meta.upload_date == "20260806"
    assert meta.duration_sec == 68.3
    assert meta.file_path.endswith("th_DaAaAaAaAaA.mp4")
    assert meta.file_size_bytes > 0
    assert meta.extra["caption"] == "the caption, in full"
    assert json.loads(meta.extra["self_thread"]) == ["part 2 of the thread"]
    assert (meta.extra["like_count"], meta.extra["reply_count"],
            meta.extra["repost_count"]) == ("323", "13", "37")


def test_download_text_only_post_raises(tmp_path):
    with pytest.raises(RuntimeError, match="has no video"):
        _download(_root(media_type=19, video_versions=None), tmp_path)
