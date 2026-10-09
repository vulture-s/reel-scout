"""Cross-site writes to the inspector/viewer server (audit E6, 2026-10-09).

The repro: with `reel-scout view` open, any page in the same browser could
`fetch('http://127.0.0.1:8700/api/groups/1', {method:'POST', mode:'no-cors',
body:'{"delete":true}'})`. text/plain is a simple request -- no preflight --
and the handler parsed the body as JSON regardless: group deleted, note
cleared, no history to restore from.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import urllib.error
import urllib.request

import pytest

from reel_scout import annotate, db, inspector
from reel_scout.inspector import write_refusal


@pytest.fixture
def server(temp_db):
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    vid = db.upsert_video(conn, "instagram", "AAAAAAAAAAA",
                          "https://www.instagram.com/reel/AAAAAAAAAAA/")
    group = annotate.add_group(conn, "client A")
    annotate.set_annotation(conn, vid, note="three weeks of notes", group=None, starred=True)
    conn.close()
    httpd = inspector.make_inspect_server(port=0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield {"port": port, "vid": vid, "gid": group["id"], "db": temp_db}
    finally:
        httpd.shutdown()
        httpd.server_close()


def _post(port, path, body, headers):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                                 data=json.dumps(body).encode(), method="POST",
                                 headers=headers)
    try:
        return urllib.request.urlopen(req, timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


def _state(path, vid):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return annotate.get(conn, vid)["note"], len(annotate.list_groups(conn))
    finally:
        conn.close()


def test_the_audit_repro_is_refused(server):
    evil = {"Content-Type": "text/plain", "Origin": "https://evil.example"}
    assert _post(server["port"], "/api/groups/%d" % server["gid"], {"delete": True}, evil) == 403
    assert _post(server["port"], "/api/annotate/" + server["vid"], {"note": ""}, evil) == 403
    assert _state(server["db"], server["vid"]) == ("three weeks of notes", 1)


def test_cross_site_json_is_refused_too(server):
    # A real browser would preflight this and get nothing back; a non-browser
    # sender forging the Origin is still told no.
    h = {"Content-Type": "application/json", "Origin": "https://evil.example"}
    assert _post(server["port"], "/api/annotate/" + server["vid"], {"note": ""}, h) == 403
    assert _state(server["db"], server["vid"])[0] == "three weeks of notes"


def test_text_plain_without_any_origin_is_refused(server):
    h = {"Content-Type": "text/plain"}
    assert _post(server["port"], "/api/annotate/" + server["vid"], {"note": ""}, h) == 415
    assert _state(server["db"], server["vid"])[0] == "three weeks of notes"


def test_sec_fetch_site_cross_site_is_refused(server):
    h = {"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"}
    assert _post(server["port"], "/api/annotate/" + server["vid"], {"note": ""}, h) == 403


def test_sec_fetch_site_same_site_is_refused(server):
    """same-site != same-origin: another local server on 127.0.0.1 (a dev
    server on a different port) is same-site with us and must not write."""
    h = {"Content-Type": "application/json", "Sec-Fetch-Site": "same-site"}
    assert _post(server["port"], "/api/annotate/" + server["vid"], {"note": ""}, h) == 403
    assert _state(server["db"], server["vid"])[0] == "three weeks of notes"


def test_dns_rebinding_is_refused(server):
    """A rebound page is same-origin with us by its own name -- Origin matches
    Host. The Host is the tell: it is not an address we answer to."""
    p = server["port"]
    h = {"Content-Type": "application/json", "Host": "evil.example:%d" % p,
         "Origin": "http://evil.example:%d" % p}
    assert _post(p, "/api/annotate/" + server["vid"], {"note": ""}, h) == 403
    assert _state(server["db"], server["vid"])[0] == "three weeks of notes"


def test_same_origin_writes_still_work(server):
    p = server["port"]
    h = {"Content-Type": "application/json", "Origin": "http://127.0.0.1:%d" % p}
    assert _post(p, "/api/annotate/" + server["vid"], {"note": "edited"}, h) == 200
    assert _state(server["db"], server["vid"])[0] == "edited"
    assert _post(p, "/api/groups/%d" % server["gid"], {"delete": True}, h) == 200
    assert _state(server["db"], server["vid"])[1] == 0


def test_non_browser_json_client_still_works(server):
    """curl / scripts send no Origin; JSON is the proof a browser page could
    not have sent it cross-site without a preflight."""
    h = {"Content-Type": "application/json; charset=utf-8"}
    assert _post(server["port"], "/api/annotate/" + server["vid"], {"note": "cli"}, h) == 200


def test_request_analysis_is_guarded(server):
    evil = {"Content-Type": "text/plain", "Origin": "https://evil.example"}
    assert _post(server["port"], "/api/request-analysis/x/1", {}, evil) == 403


def test_inspector_page_sends_json_for_request_analysis():
    # The button's fetch must satisfy the guard it now meets.
    src = open(inspector.__file__, encoding="utf-8").read()
    i = src.index("/api/request-analysis/'+b.dataset.post")
    assert "'Content-Type':'application/json'" in src[i:i + 200]


@pytest.mark.parametrize("host,ok", [
    ("127.0.0.1:8700", True), ("localhost:8700", True), ("100.64.0.5:8710", True),
    ("[::1]:8700", True), ("evil.example:8700", False), ("", False),
])
def test_host_rules(host, ok):
    headers = {"Host": host, "Content-Type": "application/json"}
    assert (write_refusal(headers) is None) is ok


def test_allowed_hosts_env(monkeypatch):
    h = {"Host": "m2max.tail1234.ts.net:8700", "Content-Type": "application/json"}
    assert write_refusal(h)[0] == 403
    monkeypatch.setenv("REEL_SCOUT_ALLOWED_HOSTS", "m2max.tail1234.ts.net")
    assert write_refusal(h) is None


def test_null_origin_is_refused():
    h = {"Host": "127.0.0.1:8700", "Origin": "null", "Content-Type": "application/json"}
    assert write_refusal(h)[0] == 403
