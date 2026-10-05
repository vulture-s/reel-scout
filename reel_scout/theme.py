"""vulture.s design tokens — the shared shell for every reel-scout surface.

Ported from the brand SSOT (apps/brand-studio/skills/vulture-design/tokens.css).
The viewer, the inspector and the take-home export all pull their chrome from
here so the three can't drift apart.

Canon this shell is held to (see that skill's canon.md):

  * 外殼安靜，內容大聲 — the chrome stands outside and lets the frames, the
    waveform and the video be the loud part. Anything that wants to be the
    star gets cut.
  * chrome voice = mono, uppercase, functional only. Content voice stays prose.
  * Rules are a three-step system: 2px main / 1px section hairline /
    1px --rule-soft row divider. Hairlines and whitespace, not boxes.
  * REJECT gradient / glow / shimmer / stacked shadows / centred everything.
  * Functional status colours are a data layer, never brand — so the craft
    score bars stay mono ink rather than going red/green.

Two deliberate, narrated deviations from the brand defaults:

  1. TOOL WIDTH. The brand column is 760px editorial. An inspection tool needs
     room for a player, a waveform and a keyframe strip, so this variant runs
     wider (--col-tool). Everything else — palette, type, rules — is unchanged.
  2. NO CYAN. Canon caps cyan at "one touch per view, on the tv. mark or the
     wordmark's .s". reel-scout carries neither mark (the tv. bracket is a
     master-only motif and extending it here would need a parent+1 narration),
     so this shell is mono throughout rather than spending the accent somewhere
     canon doesn't sanction. --accent is defined for anything that later earns it.
"""
from __future__ import annotations

# Brand tokens, verbatim values from the SSOT.
TOKENS = """
:root{
  --bg:#f1efe9; --surface:#f7f5ef; --surface-2:#ebe8df;
  --ink:#231916; --ink-2:#4a3d35;
  --rule:#231916; --rule-soft:#cdc9bd; --quiet:#6a6861; --frame:#010102;
  --cyan-raw:#26B6DA; --cyan-ink:#1C71A5; --cyan-pale:#A3D9E8; --accent:#1C71A5;
  --display:"Archivo Black",system-ui,sans-serif;
  --sans:"Inter","Noto Sans TC",system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --col:760px; --col-wide:1080px;
  /* tool variant: wide enough for player + waveform + keyframe strip.
     Fluid above 1180: a fixed 1180 used 61% of a 1920 screen and squeezed
     library titles onto two lines beside empty margins. Never narrower than
     before (the floor is the old value), never wider than the ceiling so a line of
     text stays readable on very wide screens. 1600 was still too tight on a
     wider-than-2560 desktop (Hevin 2026-10-02): the library is a table, not
     prose, so the ceiling went to 2400. */
  --col-tool:clamp(1180px,94vw,2400px);

  /* Paper. Added 2026-10-05, shared with the site (site/src/styles/paper.css),
     which pins these values back to this file in tests/test_site_tokens.py.

     This is a deliberate reading of the canon rather than a break from it:
     "the chrome is quiet so the content is loud" is about what competes for
     attention, and a 5% fibre is not competing with a keyframe strip. The
     rule that keeps it honest is the masking below -- anything that carries
     content (images, video, pre, tables) paints its own surface over the
     texture, so the texture only ever shows in the margins.

     --paper-col is the one value that differs by surface: the tool is wide
     (--col-tool), the site is editorial (--col-wide). It is a token rather
     than two copies of the rule so the rule itself stays identical. */
  --paper-fiber-opacity:.05;
  --paper-rule-step:26px;
  --paper-rule-ink:rgba(35,25,22,.08);
  --paper-col:var(--col-tool);
}
/* Background-aware accent: on any ink surface cyan does not appear, it steps
   to paper white. Kept even though this shell is mono, so an ink panel added
   later can't accidentally put cyan on ink. */
.on-ink,[data-surface="ink"]{--accent:var(--bg)}
"""

# Base shell: reset, type, the rule system, chrome voice.
BASE = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.6 var(--sans);
  font-synthesis-weight:none}
a{color:inherit}
main{max-width:var(--col-tool);margin:0 auto;padding:0 24px 96px}

/* chrome voice — mono, uppercase, functional only */
.mono,.eyebrow,.lbl,figcaption .ts,.kicker{font-family:var(--mono)}
.eyebrow,.lbl,.kicker{font-size:11px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--quiet)}

/* masthead: 2px main rule */
header.top{border-bottom:2px solid var(--rule);margin-bottom:32px}
header.top .inner{max-width:var(--col-tool);margin:0 auto;padding:28px 24px 18px}
header.top h1{margin:0;font-family:var(--display);font-weight:400;
  font-size:clamp(26px,3.4vw,38px);letter-spacing:-.02em;line-height:1.05}
header.top .sub{margin-top:6px;font-family:var(--mono);font-size:11px;
  letter-spacing:.16em;text-transform:uppercase;color:var(--quiet)}

/* section head formula: mono eyebrow + display title + right mono EN label */
.shead{display:flex;align-items:baseline;justify-content:space-between;gap:16px;
  border-bottom:1px solid var(--rule);padding-bottom:6px;margin:36px 0 14px}
.shead h2{margin:0;font-family:var(--display);font-weight:400;font-size:19px;
  letter-spacing:-.01em}
.shead .en{font-family:var(--mono);font-size:11px;letter-spacing:.16em;
  text-transform:uppercase;color:var(--quiet)}

/* row divider — the soft third step */
.row{border-bottom:1px solid var(--rule-soft)}
hr{border:0;border-top:2px solid var(--rule);margin:32px 0}

/* --- Paper ------------------------------------------------------------
   Two fixed layers behind everything. Fixed rather than on `body` so the
   sheet stays still while the content scrolls -- a page on a desk, not a
   conveyor belt.

   pointer-events:none is not optional. Without it the overlay eats every
   click on the page and nothing works. */
body::before,body::after{content:"";position:fixed;z-index:0;pointer-events:none}
/* fibre. baseFrequency 0.9 is fine grain (reads as paper weave); lower values
   drift into blotches. multiply because an additive overlay washes the paper
   colour out instead of sitting in it. */
body::before{inset:0;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='f'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23f)'/%3E%3C/svg%3E");
  opacity:var(--paper-fiber-opacity);mix-blend-mode:multiply}
/* ruled lines, inside the content column only -- full bleed would draw lines
   through margins that are meant to be empty. Text is deliberately not aligned
   to them: aligning would mean locking line-height to a multiple of the step,
   and at this ink level they read as weave rather than as writing guides. */
body::after{top:0;bottom:0;left:50%;transform:translateX(-50%);
  width:min(var(--paper-col),100%);
  background-image:repeating-linear-gradient(to bottom,
    transparent 0,transparent calc(var(--paper-rule-step) - 1px),
    var(--paper-rule-ink) calc(var(--paper-rule-step) - 1px),
    var(--paper-rule-ink) var(--paper-rule-step))}
/* Content sits above the sheet. position:relative is load-bearing -- z-index
   does nothing on a static element, and without it the whole page renders
   under the texture. */
body > *{position:relative;z-index:1}
/* Masking. Anything carrying content paints its own surface, so the texture
   only ever shows in the margins and the gaps.

   🔴 Tables are deliberately NOT in this list, and that was a reversal. The
   first version masked them on the theory that row dividers and ruled lines
   are the same visual language and would read as two sets of horizontal rules.
   Rendered, the opposite was true: the library view *is* one full-width table,
   so masking it meant the whole screen had no texture at all -- the feature
   existed and could not be seen. Measured on paper (#f1efe9), a ruled line at
   8% lands 17/255 away from the sheet while --rule-soft lands 36/255 away, so
   the dividers stay unambiguously the louder of the two. */
figure,img,video,canvas{background:var(--bg)}
pre{background:var(--surface-2)}

/* Range inputs: the craft-score re-weighting sliders were being painted in the
   browser's own accent, which on a default macOS install is a bright blue --
   the loudest thing on an otherwise mono page, and the one colour this shell
   says it does not spend. The tokens were right; nothing had told the control
   about them. */
input[type=range]{accent-color:var(--ink)}
"""


# --- Fonts -------------------------------------------------------------
# The brand faces can't be assumed present on any machine (they aren't on the
# author's), so they ship with the package. Latin faces are static and tiny, so
# they're committed; CJK is not — see cjk_subset().

import base64 as _b64
import os as _os

FONT_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "assets", "fonts")

# (css family, filename, weight)
_FACES = [
    ("Archivo Black", "archivo-black-400.woff2", 400),
    ("Inter", "inter-400.woff2", 400),
    ("JetBrains Mono", "jetbrains-mono-400.woff2", 400),
]


def font_path(name: str) -> str:
    """Absolute path to a bundled font file, guarded against traversal."""
    safe = _os.path.basename(name)
    return _os.path.join(FONT_DIR, safe)


def font_face_css(embed: bool = False, cjk_woff2: bytes = b"") -> str:
    """@font-face rules for the bundled faces.

    embed=False (server): reference /font/<file>, so a page render stays small.
    embed=True  (export):  inline base64 data URIs, so the file works offline
                           and survives being moved — the same dual-source trick
                           the keyframes already use.
    `cjk_woff2` is an optional per-export Noto Sans TC subset (always inlined;
    there is no static CJK file to serve).
    """
    out = []
    for family, filename, weight in _FACES:
        path = _os.path.join(FONT_DIR, filename)
        if embed:
            try:
                with open(path, "rb") as f:
                    src = "url(data:font/woff2;base64,%s) format('woff2')" % (
                        _b64.b64encode(f.read()).decode("ascii"))
            except OSError:
                continue
        else:
            if not _os.path.exists(path):
                continue
            src = "url(/font/%s) format('woff2')" % filename
        out.append(
            "@font-face{font-family:'%s';font-style:normal;font-weight:%d;"
            "font-display:swap;src:%s}" % (family, weight, src))
    if cjk_woff2:
        out.append(
            "@font-face{font-family:'Noto Sans TC';font-style:normal;font-weight:400;"
            "font-display:swap;src:url(data:font/woff2;base64,%s) format('woff2')}"
            % _b64.b64encode(cjk_woff2).decode("ascii"))
    return "\n".join(out)


def cjk_subset(text: str, source_ttf: str = "") -> bytes:
    """Subset a CJK face down to exactly the glyphs `text` uses, as woff2.

    A full Noto Sans TC is ~11 MB, but any single export only ever shows a
    few hundred to a couple thousand ideographs, so the subset lands around a
    couple hundred KB. Returns b"" when the tooling (fontTools + brotli) or the
    source font isn't available — callers then fall back to the reader's system
    CJK face rather than failing the export.
    """
    chars = {ch for ch in text if ord(ch) > 0x2E7F}
    if not chars:
        return b""
    src = source_ttf or _os.environ.get("REEL_SCOUT_CJK_TTF", "")
    if not src or not _os.path.exists(src):
        return b""
    try:
        import io
        from fontTools import subset as _subset  # noqa: F401
        from fontTools.ttLib import TTFont
    except ImportError:
        return b""
    try:
        font = TTFont(src, lazy=True)
        opts = _subset.Options()
        opts.layout_features = []
        opts.hinting = False
        opts.desubroutinize = True
        opts.flavor = "woff2"
        subsetter = _subset.Subsetter(options=opts)
        subsetter.populate(unicodes=[ord(c) for c in chars] + list(range(0x20, 0x7F)))
        subsetter.subset(font)
        buf = io.BytesIO()
        font.flavor = "woff2"
        font.save(buf)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — a font problem must not fail an export
        return b""


def stylesheet(extra: str = "", embed_fonts: bool = False,
               cjk_woff2: bytes = b"") -> str:
    """Font faces + tokens + base shell, plus a surface's own component rules."""
    return font_face_css(embed_fonts, cjk_woff2) + TOKENS + BASE + extra
