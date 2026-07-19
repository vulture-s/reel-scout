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
  /* tool variant: wide enough for player + waveform + keyframe strip */
  --col-tool:1180px;
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
"""


def stylesheet(extra: str = "") -> str:
    """Tokens + base shell, plus a surface's own component rules."""
    return TOKENS + BASE + extra
