"""Read-only viewer for decoded analyses.

Renders a video's reverse-decoded structure (hook / beats / CTA), keyframes,
craft scores, and transcript as HTML. Two surfaces share this one renderer:

  * a self-contained single-file HTML export (keyframes base64-embedded, zero
    external assets) that opens in any browser with no install — the take-home
    artifact for course students; and
  * a local `reel-scout view` server (keyframes served from disk).

Deliberately READ-ONLY: it shows the decoded craft, it never offers an action
(no edit / re-analyze / run buttons). Scores are labelled a reference, not an
authority, per the project's honesty line.
"""
from __future__ import annotations

import base64
import html
import json
import os
from typing import Any, Callable, Dict, List, Optional

from . import config, db

# A keyframe-src strategy maps a keyframe row → the string that goes in <img src>.
# Export uses a base64 data URI (self-contained); the server uses a URL.
KeyframeSrc = Callable[[Dict[str, Any]], str]

_SCORE_DIMS = [
    ("overall", "Overall"),
    ("hook_strength", "Hook"),
    ("visual_storytelling", "Visual"),
    ("pacing", "Pacing"),
    ("structure", "Structure"),
]


def keyframe_data_uri(file_path: Optional[str]) -> Optional[str]:
    """Base64 data URI for a keyframe image (JPEG), or None if unreadable.

    file_path is stored cwd-relative by default; resolve it, and fall back to
    KEYFRAMES_DIR by basename if the recorded path has moved. A missing frame
    degrades to None (the caller shows a placeholder) rather than erroring."""
    if not file_path:
        return None
    candidates = [os.path.abspath(file_path)]
    base = os.path.basename(file_path)
    parent = os.path.basename(os.path.dirname(file_path))
    candidates.append(os.path.join(config.KEYFRAMES_DIR, parent, base))
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                return "data:image/jpeg;base64,%s" % b64
            except OSError:
                return None
    return None


def build_video_view(conn: db.sqlite3.Connection, video_id: str) -> Optional[Dict[str, Any]]:
    """Assemble the full read-only record for one video, or None if not found."""
    video = db.get_video(conn, video_id)
    if video is None:
        return None
    analysis = db.get_analysis(conn, video_id)
    score = db.get_score(conn, video_id)
    transcript = db.get_transcript(conn, video_id)
    keyframes = db.get_keyframes_with_descriptions(conn, video_id)

    full = {}
    if analysis is not None and analysis["full_json"]:
        try:
            full = json.loads(analysis["full_json"])
        except (ValueError, TypeError):
            full = {}

    return {
        "video_id": video_id,
        "title": video["title"] or "(untitled)",
        "platform": video["platform"],
        "url": video["url"],
        "uploader": video["uploader"],
        "duration_sec": video["duration_sec"],
        "summary": full.get("summary", ""),
        "topics": full.get("topics", []) or [],
        "content_type": full.get("content_type"),
        "content_structure": full.get("content_structure"),
        "hook": full.get("hook", {}) or {},
        "style": full.get("style", {}) or {},
        "timeline": full.get("timeline", []) or [],
        "score": dict(score) if score is not None else None,
        "transcript": transcript["text_full"] if transcript is not None else "",
        "keyframes": [dict(k) for k in keyframes],
    }


def _e(value: Any) -> str:
    """HTML-escape any value (None → empty)."""
    return html.escape("" if value is None else str(value))


def _fmt_dur(sec: Any) -> str:
    if sec is None:
        return "—"
    return "%ds" % int(sec)


def render_video_section(view: Dict[str, Any], keyframe_src: KeyframeSrc) -> str:
    parts: List[str] = []
    parts.append('<section class="video" id="v-%s">' % _e(view["video_id"]))
    parts.append('<h2>%s</h2>' % _e(view["title"]))
    parts.append(
        '<p class="meta">%s · %s · <a href="%s">source</a></p>' % (
            _e(view["platform"]), _fmt_dur(view["duration_sec"]), _e(view["url"])))

    if view["summary"]:
        parts.append('<p class="summary">%s</p>' % _e(view["summary"]))

    # Decoded structure — the craft payload.
    hook = view["hook"]
    style = view["style"]
    rows = [
        ("Structure", view["content_structure"]),
        ("Content type", view["content_type"]),
        ("Format", style.get("format")),
        ("Pacing", style.get("pacing")),
        ("Hook type", hook.get("opening_type")),
        ("Hook text", hook.get("opening_text")),
        ("CTA type", hook.get("cta_type")),
        ("CTA text", hook.get("cta_text")),
    ]
    parts.append('<h3>Decoded structure</h3><table class="kv">')
    for label, val in rows:
        if val:
            parts.append('<tr><th>%s</th><td>%s</td></tr>' % (_e(label), _e(val)))
    parts.append('</table>')

    if view["topics"]:
        parts.append('<p class="topics">Topics: %s</p>' % _e(", ".join(view["topics"])))

    # Timeline / narrative arc.
    if view["timeline"]:
        parts.append('<h3>Timeline</h3><ul class="timeline">')
        for item in view["timeline"]:
            if isinstance(item, dict):
                parts.append('<li><span class="ts">%s</span> %s</li>' % (
                    _e(item.get("timestamp", "")), _e(item.get("event", ""))))
        parts.append('</ul>')

    # Scores — reference, not authority.
    if view["score"]:
        parts.append('<h3>Craft scores <small>(reference, not authority — '
                     'human judgment leads)</small></h3><table class="scores">')
        for key, label in _SCORE_DIMS:
            val = view["score"].get(key)
            if val is not None:
                parts.append('<tr><th>%s</th><td>%.1f</td></tr>' % (_e(label), val))
        parts.append('</table>')

    # Keyframes.
    if view["keyframes"]:
        parts.append('<h3>Keyframes</h3><div class="frames">')
        for kf in view["keyframes"]:
            src = keyframe_src(kf)
            img = ('<img src="%s" alt="keyframe" loading="lazy">' % _e(src)
                   if src else '<div class="noimg">image unavailable</div>')
            desc = kf.get("description") or ""
            text = kf.get("text_in_frame") or ""
            parts.append('<figure>%s<figcaption>'
                         '<span class="ts">%ss</span> %s%s</figcaption></figure>' % (
                             img, _e(int(kf["timestamp_sec"]) if kf["timestamp_sec"] is not None else 0),
                             _e(desc),
                             (' <em>on-screen: %s</em>' % _e(text)) if text else ''))
        parts.append('</div>')

    # Transcript.
    if view["transcript"]:
        parts.append('<h3>Transcript</h3><div class="transcript">%s</div>'
                     % _e(view["transcript"]))

    parts.append('</section>')
    return "\n".join(parts)


_STYLE = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans TC",sans-serif;
  margin:0;padding:0;background:#fafafa;color:#1a1a1a}
@media(prefers-color-scheme:dark){body{background:#111;color:#eaeaea}}
header.top{padding:1.5rem 2rem;border-bottom:1px solid #8884}
header.top h1{margin:0;font-size:1.3rem;letter-spacing:.02em}
header.top .sub{opacity:.6;font-size:.85rem}
main{max-width:900px;margin:0 auto;padding:0 1.5rem 4rem}
nav.index{padding:1rem 0;border-bottom:1px solid #8884;margin-bottom:1rem}
nav.index a{display:block;padding:.2rem 0;text-decoration:none;color:inherit}
nav.index a:hover{text-decoration:underline}
nav.index .sc{opacity:.55;font-size:.8rem}
section.video{padding:2rem 0;border-bottom:1px solid #8884}
section.video h2{margin:.2rem 0}
.meta{opacity:.6;font-size:.85rem;margin:.2rem 0 1rem}
.meta a{color:inherit}
.summary{font-size:1.05rem}
h3{margin:1.4rem 0 .4rem;font-size:.95rem;text-transform:uppercase;letter-spacing:.05em;opacity:.75}
h3 small{text-transform:none;letter-spacing:0;opacity:.7;font-weight:400}
table.kv,table.scores{border-collapse:collapse;font-size:.9rem}
table.kv th,table.scores th{text-align:left;padding:.15rem 1rem .15rem 0;font-weight:600;opacity:.7;vertical-align:top;white-space:nowrap}
table.kv td,table.scores td{padding:.15rem 0}
ul.timeline{margin:.2rem 0;padding-left:1.2rem}
.ts{font-variant-numeric:tabular-nums;opacity:.55;font-size:.8rem;margin-right:.4rem}
.frames{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:1rem}
.frames figure{margin:0}
.frames img{width:100%;height:auto;border-radius:4px;display:block;background:#8882}
.frames .noimg{aspect-ratio:16/9;display:grid;place-items:center;background:#8882;border-radius:4px;font-size:.8rem;opacity:.5}
figcaption{font-size:.8rem;opacity:.75;margin-top:.3rem}
figcaption em{opacity:.9}
.transcript{font-size:.9rem;opacity:.85;white-space:pre-wrap;max-height:16rem;overflow:auto;
  padding:.6rem .8rem;background:#8881;border-radius:4px}
.topics{font-size:.85rem;opacity:.7}
"""


def render_page(sections: List[str], index_html: str, title: str) -> str:
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title><style>%s</style></head><body>'
        '<header class="top"><h1>%s</h1>'
        '<div class="sub">reel-scout — decoded structure viewer (read-only)</div></header>'
        '<main>%s%s</main></body></html>' % (
            _e(title), _STYLE, _e(title), index_html, "\n".join(sections))
    )


def render_index(views: List[Dict[str, Any]], href: Callable[[str], str]) -> str:
    if len(views) <= 1:
        return ""
    items = ['<nav class="index">']
    for v in views:
        overall = ""
        if v["score"] and v["score"].get("overall") is not None:
            overall = '<span class="sc"> · %.1f</span>' % v["score"]["overall"]
        struct = '<span class="sc"> · %s</span>' % _e(v["content_structure"]) if v["content_structure"] else ""
        items.append('<a href="%s">%s%s%s</a>' % (
            _e(href(v["video_id"])), _e(v["title"]), struct, overall))
    items.append('</nav>')
    return "\n".join(items)


def render_bundle(conn: db.sqlite3.Connection, video_id: Optional[str] = None,
                  title: str = "reel-scout") -> str:
    """Self-contained HTML for one or all analyzed videos (keyframes base64
    embedded). This is the take-home export string."""
    if video_id:
        ids = [video_id]
    else:
        ids = [v["id"] for v in db.list_videos(conn, status="analyzed", limit=9999)]
    views = [v for v in (build_video_view(conn, vid) for vid in ids) if v]

    def src(kf: Dict[str, Any]) -> str:
        return keyframe_data_uri(kf.get("file_path")) or ""

    sections = [render_video_section(v, src) for v in views]
    index = render_index(views, href=lambda vid: "#v-%s" % vid)
    if not views:
        sections = ['<section class="video"><p>No analyzed videos to show.</p></section>']
    return render_page(sections, index, title)


# --- Live server surface (reel-scout view) ---
# Same renderer as the bundle, but keyframes are served from disk by URL instead
# of base64-embedded, and each video is its own page.

def render_index_page(conn: db.sqlite3.Connection, title: str = "reel-scout") -> str:
    views = [v for v in (build_video_view(conn, r["id"])
                         for r in db.list_videos(conn, status="analyzed", limit=9999)) if v]
    if not views:
        body = '<section class="video"><p>No analyzed videos yet.</p></section>'
        return render_page([body], "", title)
    nav = render_index(views, href=lambda vid: "/video/%s" % vid)
    # render_index returns "" for a single video; always show the list on the server.
    if not nav:
        nav = ('<nav class="index"><a href="/video/%s">%s</a></nav>'
               % (_e(views[0]["video_id"]), _e(views[0]["title"])))
    return render_page([], nav, title)


def render_video_page(conn: db.sqlite3.Connection, video_id: str) -> Optional[str]:
    view = build_video_view(conn, video_id)
    if view is None:
        return None
    section = render_video_section(view, keyframe_src=lambda kf: "/keyframe/%s" % kf["id"])
    back = '<nav class="index"><a href="/">&larr; all videos</a></nav>'
    return render_page([section], back, view["title"])


def _keyframe_path(conn: db.sqlite3.Connection, keyframe_id: str) -> Optional[str]:
    row = conn.execute("SELECT file_path FROM keyframes WHERE id = ?", (keyframe_id,)).fetchone()
    if row is None or not row[0]:
        return None
    for path in (os.path.abspath(row[0]),
                 os.path.join(config.KEYFRAMES_DIR,
                              os.path.basename(os.path.dirname(row[0])),
                              os.path.basename(row[0]))):
        if os.path.exists(path):
            return path
    return None


def make_server(host: str = "127.0.0.1", port: int = 0):
    """Build (but don't start) the read-only HTTP server. Each request opens its
    own short-lived connection (via db.get_connection → config.DB_PATH), so the
    handler is thread-safe regardless of which thread serve_forever runs on.
    Split from serve() so tests can drive it over a real socket."""
    import http.server

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the console quiet
            pass

        def _send(self, code, body, content_type="text/html; charset=utf-8"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            conn = db.get_connection()
            try:
                if path == "/":
                    self._send(200, render_index_page(conn))
                elif path.startswith("/video/"):
                    page = render_video_page(conn, path[len("/video/"):])
                    self._send(200, page) if page else self._send(404, "not found")
                elif path.startswith("/keyframe/"):
                    fp = _keyframe_path(conn, path[len("/keyframe/"):])
                    if fp:
                        with open(fp, "rb") as f:
                            self._send(200, f.read(), "image/jpeg")
                    else:
                        self._send(404, "not found")
                else:
                    self._send(404, "not found")
            finally:
                conn.close()

    # Threading, not the plain HTTPServer: a video page pulls its keyframes over
    # separate requests, so a single-threaded server serialized them and ANY held
    # -open connection (a browser keep-alive is enough) blocked every other
    # request until it timed out. The handler is per-request thread-safe as noted
    # above, so threading is free. ThreadingHTTPServer sets daemon_threads.
    return http.server.ThreadingHTTPServer((host, port), _Handler)


def serve(host: str = "127.0.0.1", port: int = 0, open_browser: bool = True) -> None:
    """Start the read-only local viewer server. Blocks until interrupted."""
    httpd = make_server(host=host, port=port)
    url = "http://%s:%d/" % (host, httpd.server_address[1])
    print("reel-scout view (read-only) serving at %s  — Ctrl-C to stop" % url)
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - headless / no browser is fine
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
