"""Interactive single-clip inspector.

Where the read-only `viewer` renders a *static* page per video (a flat keyframe
wall + a plain transcript block), the inspector is a *focused, interactive* view
of ONE reel: the transcript is split into its Whisper segments and time-synced to
the keyframes, and a timeline scrubber shows where every frame and spoken segment
sits across the clip. Clicking a transcript segment highlights the nearest
keyframe (and scrolls to it); clicking a keyframe highlights the segment being
spoken over it; clicking the timeline jumps to whatever is nearest that instant.

Like the viewer it is deliberately READ-ONLY and self-contained — keyframes are
base64-embedded and all CSS/JS is inline, so the output is a single .html file
that opens offline in any browser with zero install. It is a lens on the decoded
craft, not a player and not an editor; craft scores are labelled a reference, not
an authority, per the project's honesty line.
"""
from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Optional

from . import config, db
from .viewer import build_video_view, keyframe_data_uri

# Craft score dimensions, in display order. Mirrors viewer._SCORE_DIMS but the
# inspector renders them as a horizontal strip of meters rather than a table.
_SCORE_DIMS = [
    ("overall", "Overall"),
    ("hook_strength", "Hook"),
    ("visual_storytelling", "Visual"),
    ("pacing", "Pacing"),
    ("structure", "Structure"),
]


def _e(value: Any) -> str:
    """HTML-escape any value (None -> empty)."""
    return html.escape("" if value is None else str(value))


def _fmt_ts(sec: Any) -> str:
    """Seconds -> m:ss (tabular). None/negative -> 0:00."""
    try:
        s = int(round(float(sec)))
    except (TypeError, ValueError):
        s = 0
    if s < 0:
        s = 0
    return "%d:%02d" % (s // 60, s % 60)


def build_inspect_view(conn: db.sqlite3.Connection, video_id: str) -> Optional[Dict[str, Any]]:
    """Assemble one clip's inspector payload, or None if the video is unknown.

    Reuses viewer.build_video_view for the shared fields and augments it with the
    per-segment transcript (from transcripts.segments_json) and a resolved clip
    duration. duration_sec on the video row is often 0.0/None for IG (yt-dlp
    returns no duration), so we fall back to the largest timestamp we actually
    have — the last segment end or the last keyframe — so the timeline still
    scales correctly."""
    view = build_video_view(conn, video_id)
    if view is None:
        return None

    transcript = db.get_transcript(conn, video_id)
    segments: List[Dict[str, Any]] = []
    language = None
    if transcript is not None:
        language = transcript["language"]
        raw = transcript["segments_json"]
        if raw:
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = []
            for s in parsed:
                if not isinstance(s, dict):
                    continue
                try:
                    start = float(s.get("start", 0.0) or 0.0)
                    end = float(s.get("end", start) or start)
                except (TypeError, ValueError):
                    continue
                text = (s.get("text") or "").strip()
                if not text:
                    continue
                segments.append({"start": start, "end": end, "text": text})

    # Resolve a duration to scale the timeline against.
    candidates = [view.get("duration_sec") or 0.0]
    if segments:
        candidates.append(max(s["end"] for s in segments))
    for kf in view["keyframes"]:
        if kf.get("timestamp_sec") is not None:
            candidates.append(float(kf["timestamp_sec"]))
    duration = max(candidates) if candidates else 0.0

    view["segments"] = segments
    view["language"] = language
    view["duration"] = duration
    return view


# --- Rendering ---

def _render_scores(view: Dict[str, Any]) -> str:
    score = view.get("score")
    if not score:
        return ""
    meters: List[str] = []
    for key, label in _SCORE_DIMS:
        val = score.get(key)
        if val is None:
            continue
        pct = max(0.0, min(100.0, float(val) * 10.0))
        meters.append(
            '<div class="meter"><div class="mlabel">%s</div>'
            '<div class="mbar"><span style="width:%.1f%%"></span></div>'
            '<div class="mval">%.1f</div></div>' % (_e(label), pct, float(val)))
    if not meters:
        return ""
    reasoning = score.get("reasoning")
    note = ('<p class="reasoning">%s</p>' % _e(reasoning)) if reasoning else ""
    return (
        '<section class="scores"><h3>Craft scores '
        '<small>(reference, not authority &mdash; human judgment leads)</small></h3>'
        '<div class="meters">%s</div>%s</section>' % ("".join(meters), note))


def _render_structure(view: Dict[str, Any]) -> str:
    hook = view.get("hook") or {}
    style = view.get("style") or {}
    rows = [
        ("Structure", view.get("content_structure")),
        ("Content type", view.get("content_type")),
        ("Format", style.get("format")),
        ("Pacing", style.get("pacing")),
        ("Hook type", hook.get("opening_type")),
        ("Hook text", hook.get("opening_text")),
        ("CTA type", hook.get("cta_type")),
        ("CTA text", hook.get("cta_text")),
    ]
    cells = ['<tr><th>%s</th><td>%s</td></tr>' % (_e(k), _e(v)) for k, v in rows if v]
    if not cells:
        return ""
    return ('<section class="structure"><h3>Decoded structure</h3>'
            '<table class="kv">%s</table></section>' % "".join(cells))


def _render_timeline(view: Dict[str, Any]) -> str:
    """A horizontal scrubber: keyframe ticks + spoken-segment spans across the
    clip, positioned by time. Purely presentational markup; the inline script
    wires the click/jump behaviour."""
    dur = view.get("duration") or 0.0
    if dur <= 0:
        return ""
    ticks: List[str] = []
    for j, kf in enumerate(view["keyframes"]):
        ts = kf.get("timestamp_sec")
        if ts is None:
            continue
        left = max(0.0, min(100.0, float(ts) / dur * 100.0))
        ticks.append('<button class="tick" data-frame="%d" style="left:%.3f%%" '
                     'title="%s" aria-label="keyframe at %s"></button>'
                     % (j, left, _e(_fmt_ts(ts)), _e(_fmt_ts(ts))))
    spans: List[str] = []
    for i, seg in enumerate(view.get("segments", [])):
        left = max(0.0, min(100.0, seg["start"] / dur * 100.0))
        width = max(0.4, min(100.0 - left, (seg["end"] - seg["start"]) / dur * 100.0))
        spans.append('<button class="span" data-seg="%d" style="left:%.3f%%;width:%.3f%%" '
                     'title="%s"></button>' % (i, left, width, _e(seg["text"][:80])))
    return (
        '<section class="timeline"><h3>Timeline <small>%s</small></h3>'
        '<div class="scrub" id="scrub" role="slider" aria-label="clip timeline">'
        '<div class="track">%s</div><div class="spans">%s</div>'
        '<div class="playhead" id="playhead"></div></div>'
        '<div class="axis"><span>0:00</span><span>%s</span></div></section>'
        % (_e(_fmt_ts(dur)), "".join(ticks), "".join(spans), _e(_fmt_ts(dur))))


def _render_keyframes(view: Dict[str, Any]) -> str:
    if not view["keyframes"]:
        return '<section class="frames-wrap"><h3>Keyframes</h3><p class="empty">No keyframes.</p></section>'
    figs: List[str] = []
    for j, kf in enumerate(view["keyframes"]):
        ts = kf.get("timestamp_sec")
        src = keyframe_data_uri(kf.get("file_path")) or ""
        img = ('<img src="%s" alt="keyframe at %s" loading="lazy">' % (_e(src), _e(_fmt_ts(ts)))
               if src else '<div class="noimg">image unavailable</div>')
        desc = kf.get("description") or ""
        text = kf.get("text_in_frame") or ""
        onscreen = ('<span class="onscreen">on-screen: %s</span>' % _e(text)) if text else ""
        figs.append(
            '<figure class="kf" id="kf-%d" data-frame="%d" data-ts="%.3f" tabindex="0">'
            '<div class="kfimg">%s<span class="kfts">%s</span></div>'
            '<figcaption>%s%s</figcaption></figure>'
            % (j, j, float(ts) if ts is not None else 0.0, img, _e(_fmt_ts(ts)),
               _e(desc), onscreen))
    return ('<section class="frames-wrap"><h3>Keyframes <small>%d</small></h3>'
            '<div class="frames">%s</div></section>' % (len(figs), "".join(figs)))


def _render_transcript(view: Dict[str, Any]) -> str:
    segments = view.get("segments") or []
    if not segments:
        # No per-segment timing; fall back to the flat transcript if present.
        full = view.get("transcript") or ""
        if not full:
            return ('<aside class="transcript-wrap"><h3>Transcript</h3>'
                    '<p class="empty">No transcript.</p></aside>')
        return ('<aside class="transcript-wrap"><h3>Transcript</h3>'
                '<div class="transcript-flat">%s</div></aside>' % _e(full))
    rows: List[str] = []
    for i, seg in enumerate(segments):
        rows.append(
            '<button class="seg" id="seg-%d" data-seg="%d" '
            'data-start="%.3f" data-end="%.3f">'
            '<span class="segts">%s</span><span class="segtext">%s</span></button>'
            % (i, i, seg["start"], seg["end"], _e(_fmt_ts(seg["start"])), _e(seg["text"])))
    return ('<aside class="transcript-wrap"><h3>Transcript '
            '<small>click to sync</small></h3>'
            '<div class="segments">%s</div></aside>' % "".join(rows))


def render_inspector(view: Dict[str, Any]) -> str:
    """Full self-contained inspector HTML for one clip."""
    dur = view.get("duration") or 0.0
    meta_bits = [_e(view["platform"])]
    if view.get("uploader"):
        meta_bits.append("@%s" % _e(view["uploader"]))
    if view.get("language"):
        meta_bits.append(_e(view["language"]))
    meta_bits.append(_fmt_ts(dur))
    meta = " &middot; ".join(meta_bits)
    summary = ('<p class="summary">%s</p>' % _e(view["summary"])) if view.get("summary") else ""
    topics = ('<p class="topics">Topics: %s</p>' % _e(", ".join(view["topics"]))) if view.get("topics") else ""

    body = (
        '<header class="top">'
        '<div class="crumb">reel-scout inspect &middot; %s</div>'
        '<h1>%s</h1>'
        '<p class="meta">%s &middot; <a href="%s" rel="noopener">source &#8599;</a></p>'
        '%s%s</header>'
        '%s%s%s'
        '<div class="split">%s%s</div>'
        % (_e(view["video_id"]), _e(view["title"]), meta, _e(view["url"]),
           summary, topics,
           _render_scores(view), _render_structure(view), _render_timeline(view),
           _render_keyframes(view), _render_transcript(view)))

    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s &mdash; reel-scout inspect</title>'
        '<style>%s</style></head><body><main>%s</main><script>%s</script>'
        '</body></html>' % (_e(view["title"]), _STYLE, body, _SCRIPT))


_STYLE = """
:root{color-scheme:light dark;--fg:#1a1a1a;--bg:#fafafa;--mut:#8a8a8a;--line:#8884;
  --accent:#e0553d;--card:#fff;--activebg:#e0553d1a}
@media(prefers-color-scheme:dark){:root{--fg:#eaeaea;--bg:#111;--mut:#9a9a9a;
  --card:#1b1b1b;--activebg:#e0553d33}}
*{box-sizing:border-box}
body{font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans TC",sans-serif;
  margin:0;background:var(--bg);color:var(--fg)}
main{max-width:1100px;margin:0 auto;padding:0 1.5rem 4rem}
a{color:var(--accent)}
header.top{padding:1.6rem 0 1rem;border-bottom:1px solid var(--line)}
.crumb{font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--mut);
  font-variant-numeric:tabular-nums}
header.top h1{margin:.35rem 0 .3rem;font-size:1.5rem;line-height:1.2}
.meta{margin:.1rem 0 .6rem;color:var(--mut);font-size:.85rem}
.summary{font-size:1.02rem;margin:.6rem 0}
.topics{font-size:.82rem;color:var(--mut);margin:.2rem 0}
h3{margin:1.5rem 0 .5rem;font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}
h3 small{text-transform:none;letter-spacing:0;font-weight:400;opacity:.8}
.empty{color:var(--mut);font-size:.9rem}
/* scores */
.meters{display:flex;flex-wrap:wrap;gap:.5rem 1.4rem}
.meter{display:flex;align-items:center;gap:.5rem;min-width:170px}
.mlabel{font-size:.8rem;color:var(--mut);width:4.2rem}
.mbar{flex:1;height:.5rem;background:var(--line);border-radius:99px;overflow:hidden}
.mbar span{display:block;height:100%;background:var(--accent);border-radius:99px}
.mval{font-variant-numeric:tabular-nums;font-weight:600;font-size:.85rem;width:2rem;text-align:right}
.reasoning{font-size:.85rem;color:var(--mut);margin:.6rem 0 0;max-width:70ch}
/* structure */
table.kv{border-collapse:collapse;font-size:.88rem}
table.kv th{text-align:left;padding:.15rem 1rem .15rem 0;font-weight:600;color:var(--mut);
  vertical-align:top;white-space:nowrap}
table.kv td{padding:.15rem 0}
/* timeline */
.scrub{position:relative;height:34px;margin:.3rem 0 .2rem;cursor:pointer;
  background:var(--line);border-radius:6px;user-select:none}
.track,.spans{position:absolute;left:0;right:0}
.track{top:0;height:20px}
.spans{bottom:0;height:12px}
.tick{position:absolute;top:2px;width:3px;height:16px;padding:0;border:0;border-radius:2px;
  background:var(--fg);opacity:.55;transform:translateX(-1px);cursor:pointer}
.tick:hover,.tick.active{opacity:1;background:var(--accent);width:5px}
.span{position:absolute;bottom:0;height:10px;padding:0;border:0;border-radius:2px;
  background:var(--accent);opacity:.28;cursor:pointer}
.span:hover,.span.active{opacity:.85}
.playhead{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--fg);
  left:0;opacity:0;pointer-events:none;transition:left .08s linear}
.playhead.on{opacity:.9}
.axis{display:flex;justify-content:space-between;font-size:.72rem;color:var(--mut);
  font-variant-numeric:tabular-nums}
/* split layout */
.split{display:grid;grid-template-columns:1fr 20rem;gap:1.5rem;align-items:start}
@media(max-width:760px){.split{grid-template-columns:1fr}}
.frames{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:.9rem}
figure.kf{margin:0;border-radius:6px;padding:.35rem;background:var(--card);
  border:1px solid transparent;transition:border-color .12s,box-shadow .12s;cursor:pointer}
figure.kf.active{border-color:var(--accent);box-shadow:0 0 0 2px var(--activebg)}
figure.kf:focus{outline:2px solid var(--accent);outline-offset:1px}
.kfimg{position:relative}
.kfimg img,.noimg{width:100%;border-radius:4px;display:block}
.noimg{aspect-ratio:9/16;background:var(--line);display:grid;place-items:center;
  font-size:.75rem;color:var(--mut)}
.kfts{position:absolute;left:.3rem;bottom:.3rem;background:#000a;color:#fff;
  font-size:.7rem;padding:.05rem .3rem;border-radius:3px;font-variant-numeric:tabular-nums}
figcaption{font-size:.76rem;color:var(--mut);margin-top:.35rem;line-height:1.35}
.onscreen{display:block;margin-top:.2rem;color:var(--fg);opacity:.8}
/* transcript */
.transcript-wrap{position:sticky;top:1rem}
.segments{max-height:70vh;overflow:auto;border:1px solid var(--line);border-radius:6px}
.seg{display:flex;gap:.5rem;width:100%;text-align:left;padding:.4rem .6rem;border:0;
  background:transparent;color:inherit;font:inherit;font-size:.85rem;cursor:pointer;
  border-bottom:1px solid var(--line)}
.seg:last-child{border-bottom:0}
.seg:hover{background:var(--activebg)}
.seg.active{background:var(--activebg);box-shadow:inset 3px 0 0 var(--accent)}
.segts{color:var(--mut);font-variant-numeric:tabular-nums;flex:0 0 2.6rem}
.transcript-flat{white-space:pre-wrap;font-size:.85rem;color:var(--fg);opacity:.85;
  max-height:70vh;overflow:auto;padding:.6rem;border:1px solid var(--line);border-radius:6px}
"""

# Vanilla JS, no dependencies. Wires the three-way sync between the timeline
# scrubber, keyframes, and transcript segments. All timing data lives in data-*
# attributes so there is no separate JSON blob to keep in step.
_SCRIPT = r"""
(function(){
  var frames=[].slice.call(document.querySelectorAll('figure.kf'));
  var segs=[].slice.call(document.querySelectorAll('.seg'));
  var ticks=[].slice.call(document.querySelectorAll('.tick'));
  var spans=[].slice.call(document.querySelectorAll('.span'));
  var scrub=document.getElementById('scrub');
  var playhead=document.getElementById('playhead');
  var dur=0;
  frames.forEach(function(f){dur=Math.max(dur,parseFloat(f.dataset.ts)||0);});
  segs.forEach(function(s){dur=Math.max(dur,parseFloat(s.dataset.end)||0);});

  function clearActive(list){list.forEach(function(el){el.classList.remove('active');});}
  function frameTs(f){return parseFloat(f.dataset.ts)||0;}

  function nearestFrame(t){
    var best=null,bd=Infinity;
    frames.forEach(function(f){var d=Math.abs(frameTs(f)-t);if(d<bd){bd=d;best=f;}});
    return best;
  }
  function segAt(t){
    // segment covering t, else nearest by midpoint
    var cover=null,best=null,bd=Infinity;
    segs.forEach(function(s){
      var a=parseFloat(s.dataset.start)||0,b=parseFloat(s.dataset.end)||0;
      if(t>=a&&t<=b){cover=s;}
      var mid=(a+b)/2,d=Math.abs(mid-t);if(d<bd){bd=d;best=s;}
    });
    return cover||best;
  }
  function movePlayhead(t){
    if(!playhead||dur<=0)return;
    playhead.style.left=Math.max(0,Math.min(100,t/dur*100))+'%';
    playhead.classList.add('on');
  }
  function highlightFrame(f,scroll){
    if(!f)return;
    clearActive(frames);clearActive(ticks);
    f.classList.add('active');
    var i=frames.indexOf(f);
    if(ticks[i])ticks[i].classList.add('active');
    if(scroll)f.scrollIntoView({behavior:'smooth',block:'nearest'});
  }
  function highlightSeg(s,scroll){
    if(!s)return;
    clearActive(segs);clearActive(spans);
    s.classList.add('active');
    var i=segs.indexOf(s);
    if(spans[i])spans[i].classList.add('active');
    if(scroll)s.scrollIntoView({behavior:'smooth',block:'nearest'});
  }
  function syncTo(t){
    movePlayhead(t);
    highlightFrame(nearestFrame(t),true);
    highlightSeg(segAt(t),true);
  }

  segs.forEach(function(s){s.addEventListener('click',function(){
    var t=parseFloat(s.dataset.start)||0;
    movePlayhead(t);highlightSeg(s,false);highlightFrame(nearestFrame(t),true);
  });});
  frames.forEach(function(f){
    function go(){var t=frameTs(f);movePlayhead(t);highlightFrame(f,false);highlightSeg(segAt(t),true);}
    f.addEventListener('click',go);
    f.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();go();}});
  });
  ticks.forEach(function(t){t.addEventListener('click',function(e){
    e.stopPropagation();var f=frames[parseInt(t.dataset.frame,10)];if(f)f.click();
  });});
  spans.forEach(function(sp){sp.addEventListener('click',function(e){
    e.stopPropagation();var s=segs[parseInt(sp.dataset.seg,10)];if(s)s.click();
  });});
  if(scrub){scrub.addEventListener('click',function(e){
    var r=scrub.getBoundingClientRect();
    var t=dur*Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));
    syncTo(t);
  });}
})();
"""
