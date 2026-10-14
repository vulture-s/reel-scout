"""Real-name check for inspire output (the analysis is the source of truth).

The prompt rule "real names stay real" (#210) cut qwen2.5:14b's habit of
renaming the tool in a video from 6/10 to 2/10 runs -- but a prompt cannot get
it to 0. This module checks the answer instead:

* **entities** -- the real names in the analysis: name-shaped Latin words
  (``What'Sub``, ``DaVinci``, ``FX3``, ``GEV``) and titles in 書名號
  (``《我的世界》``).
* **missing** -- an entity that does not appear in the output.
* **invented** -- a name-shaped word / 書名號 title in the output that appears
  nowhere in the analysis or the requested angle (``SubEase``, ``Let'Sub``).

Which of the two fails an answer depends on the mode (``mode_for``): with no
angle both do (``strict``); with an angle only *invented* does (``angle``) --
an angle asks for a different video, so the source's names may drop out.

"Name-shaped" is deliberately a *shape*, not a dictionary: CamelCase inside a
word, an apostrophe between letters, letters mixed with digits, or ALL-CAPS of
3+ letters. Plain Title-case words (``Sony``, ``Jump Cut``) are not counted:
the zh-TW output rule asks for English glosses like 「跳切（Jump Cut）」, and a
shape that flagged those would fail every answer. The cost is stated, not
hidden: a fabricated Title-case-only name (``Subly``) or a Chinese person's
name is not detected.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Set

#: Analysis keys whose values are machine enums / measurements, not prose.
SKIP_KEYS = frozenset({
    "timestamp", "opening_type", "cta_type", "format", "pacing", "emotion",
    "spoken_language", "subtitle_language", "content_type", "content_structure",
    "measured",
})

#: Output keys that carry human-readable text.
OUTPUT_KEYS = ("titles", "hook_script", "structure_outline", "rationale", "raw")

#: Generic short-form jargon that is ALL-CAPS but is not anyone's name.
GENERIC_CAPS = frozenset({
    "CTA", "POV", "DIY", "FAQ", "ASMR", "VLOG", "SEO", "API", "APP", "KOL", "KPI",
    "ROI", "CEO", "HDR", "LOG", "RAW", "USB", "LED", "LUT", "FPS", "BGM", "SFX",
    "TTS", "OCR", "GPU", "CPU", "PDF", "MP4", "MOV", "NEW", "TOP", "WOW", "OMG",
    "LOL", "AND", "THE", "FOR", "YOU", "HOW", "WHY", "NOT", "ALL",
})

_WORD = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*")
_TITLE = re.compile(r"[《〈]([^《》〈〉]{1,40})[》〉]")
_UNIT = re.compile(r"^\d+(?:k|p|fps|s|sec|mm|hz|x|m|min|gb|mb|tb|bit|th|st|nd|rd)$", re.I)


def is_name_like(word: str) -> bool:
    """True for a Latin word shaped like a proper name (see module doc)."""
    if _UNIT.match(word) or word.isdigit():
        return False
    letters = re.sub(r"[^A-Za-z]", "", word)
    if not letters:
        return False
    if re.search(r"[A-Za-z]['’][A-Za-z]", word):
        return True                                    # What'Sub, Let'Sub
    if re.search(r"[a-z][A-Z]", word):
        return True                                    # DaVinci, iPhone, SubEase
    if re.search(r"\d", word) and re.search(r"[A-Za-z]", word):
        return True                                    # FX3, A7S3
    if word.isupper() and len(letters) >= 3 and word.upper() not in GENERIC_CAPS:
        return True                                    # GEV, ASTRA
    return False


def norm(text: str) -> str:
    """Comparison key: NFKC, lower-case, keep only letters/digits/Han."""
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(ch for ch in text if ch.isalnum())


def _strings(value: Any, skip: bool = False) -> Iterable[str]:
    if isinstance(value, str):
        if not skip:
            yield value
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v, skip)
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, skip or k in SKIP_KEYS)


def names_in_text(text: str) -> List[str]:
    """Name-shaped Latin words and 書名號 titles, in first-seen order."""
    found: List[str] = []
    seen: Set[str] = set()
    for m in _TITLE.finditer(text):
        key = norm(m.group(1))
        if key and key not in seen:
            seen.add(key)
            found.append("《%s》" % m.group(1))
    for m in _WORD.finditer(text):
        w = m.group(0)
        if is_name_like(w) and norm(w) not in seen:
            seen.add(norm(w))
            found.append(w)
    return found


def extract_entities(analysis: Any) -> List[str]:
    """Real names in an analysis tree (or plain text). Keys are never scanned."""
    text = "\n".join(_strings(analysis)) if not isinstance(analysis, str) else analysis
    return names_in_text(text)


def output_text(data: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in OUTPUT_KEYS:
        parts.extend(_strings(data.get(key)))
    return "\n".join(parts)


def _key(name: str) -> str:
    return norm(name.strip("《》〈〉"))


#: Check modes. ``strict`` (no angle): a dropped real name and a name the
#: analysis never mentions both fail the answer. ``angle``: the angle asks for a
#: *different* video, so a real name from the source may legitimately go away
#: (a variant for photographers need not mention the subtitle tool) -- only a
#: name that comes from nowhere (not in the analysis, not in the angle) fails.
MODE_STRICT = "strict"
MODE_ANGLE = "angle"


def mode_for(angle: str) -> str:
    """``angle`` when an angle was given (non-blank), else ``strict``."""
    return MODE_ANGLE if angle and angle.strip() else MODE_STRICT


def check(entities: List[str], known_text: str, data: Dict[str, Any],
          mode: str = MODE_STRICT) -> Dict[str, List[str]]:
    """``{"missing": [...], "invented": [...]}`` for one model answer.

    *known_text* is everything a name may legitimately come from (the analysis
    as sent, the raw analysis, the angle). Empty lists mean the answer passes.

    In ``angle`` mode a dropped real name is not a problem: ``missing`` is
    always empty and the dropped names are reported, for information only,
    under ``dropped``.
    """
    if mode not in (MODE_STRICT, MODE_ANGLE):
        raise ValueError("unknown name-check mode: %r" % (mode,))
    out = norm(output_text(data))
    known = norm(known_text)
    missing = [e for e in entities if _key(e) and _key(e) not in out]
    invented = [n for n in names_in_text(output_text(data)) if _key(n) not in known]
    if mode == MODE_ANGLE:
        return {"missing": [], "invented": invented, "dropped": missing}
    return {"missing": missing, "invented": invented}
