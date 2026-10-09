"""Side-by-side Traditional Chinese for the free text (roadmap §7E).

The decoded enums became translatable at the display layer, because the model
only ever picks from a closed list and showing the picked one in Chinese changes
nothing about the claim. Free text is not like that. A summary, a frame
description, a line of transcript, a scoring rationale — those words are the
model's own, and a translation is **a second artifact placed beside the first**,
never a replacement for it.

That distinction decides everything else here:

* the original is always kept and always displayed;
* the translation carries the engine and model that produced it, the way
  `scores` and `shot_labels` learned to;
* and it carries a fingerprint of the source it was made from.

🔴 **The fingerprint is the part that matters.** Descriptions get re-run when a
VLM changes; transcripts get re-cut when a language track is fixed. A
translation stored without one goes on being shown beside text it no longer
matches, silently, looking exactly like a current one. `is_stale()` is the whole
reason the column exists.

## What is not translated

Text that is already Chinese. Running a translator over it produces a worse
version of what was already there, and the corpus is roughly a quarter Chinese
already. `needs_translation()` is a ratio test, not a language-detector call:
mixed-script subtitles are common and a hard classifier gets them wrong in both
directions.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import config, db

LANG = "zh"
ENGINE_OLLAMA = "ollama"

#: Kinds, and what `ref` addresses inside the clip.
KIND_DESCRIPTION = "description"          # ref = keyframe id
KIND_SEGMENT = "transcript_segment"       # ref = segment index
KIND_SUMMARY = "summary"                  # ref = ''
KIND_TIMELINE = "timeline"                # ref = timeline index
KIND_REASONING = "reasoning"              # ref = ''
KIND_OPENING = "opening_text"             # ref = ''  (hook.opening_text)
KIND_CTA = "cta_text"                     # ref = ''  (hook.cta_text)

#: Above this share of CJK the text is already Chinese and translating it would
#: only degrade it. Deliberately a ratio rather than a language classifier:
#: subtitles mix scripts constantly and a hard classifier is wrong both ways.
CJK_ALREADY = 0.15

#: Taiwan wording is specified, not just the script. Asking only for
#: "Traditional Chinese" gets Traditional characters carrying mainland
#: vocabulary — the first run came back with 「該視頻」 where Taiwan says
#: 「這支影片」. Both are zh-Hant; only one is the house style.
PROMPT = ("Translate the following into Traditional Chinese as used in Taiwan "
          "(zh-TW). Use Taiwanese vocabulary and phrasing, not mainland terms "
          "(影片 not 視頻, 品質 not 質量, 網路 not 網絡, 程式 not 程序). "
          "Keep proper nouns, brand names and on-screen text in the original. "
          "Output ONLY the translation — no preamble, no notes, no romanisation."
          "\n\n%s")


def cjk_ratio(text: Optional[str]) -> float:
    if not text:
        return 0.0
    n = sum(1 for ch in text if "一" <= ch <= "鿿")
    return n / max(1, len(text))


#: Kana share (of kanji + kana) at which text is Japanese, not Chinese. Kanji
#: alone cannot tell the two apart -- ordinary Japanese runs 18-45% kanji, well
#: over :data:`CJK_ALREADY` -- so before this every Japanese line was taken for
#: Chinese and skipped. Kana is the evidence that can: Chinese text carries none,
#: bar the odd decorative の in Taiwan copy, which this share is set above.
KANA_JAPANESE = 0.25


def kana_count(text: Optional[str]) -> int:
    """Hiragana + katakana characters (U+3040-U+30FF)."""
    if not text:
        return 0
    return sum(1 for ch in text if "\u3040" <= ch <= "\u30ff")


def needs_translation(text: Optional[str]) -> bool:
    """False for empty text and for text that is already mostly Chinese.

    Japanese is translated even when it is kanji-heavy: a kanji ratio says
    "CJK", not "Chinese", and the Chinese UI cannot show Japanese as if it
    were already translated.
    """
    if not text or not text.strip():
        return False
    kana = kana_count(text)
    if kana >= 2:
        kanji = sum(1 for ch in text if "一" <= ch <= "鿿")
        if kana / float(kana + kanji) >= KANA_JAPANESE:
            return True
    return cjk_ratio(text) <= CJK_ALREADY


def is_stale(row: Any, source_text: Optional[str]) -> bool:
    """True when the stored translation was made from different source text."""
    return db.source_fingerprint(source_text) != (row["source_hash"] or "")


def translate_text(text: str, model: str, base_url: Optional[str] = None) -> Optional[str]:
    """One passage. None on any failure — never a partial or a placeholder."""
    url = (base_url or getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
    body = json.dumps({"model": model, "prompt": PROMPT % text, "stream": False,
                       "think": False, "options": {"temperature": 0}}).encode("utf-8")
    req = urllib.request.Request(url + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    out = (payload.get("response") or "").strip()
    return out or None


def collect_units(conn, video_id: str) -> List[Tuple[str, str, str]]:
    """(kind, ref, source_text) for everything translatable in one clip.

    Transcript is taken per timed segment rather than whole: a four-hour clip is
    46,000 characters in one field, which no single request should carry, and
    the segments are the unit the player already seeks by.
    """
    units: List[Tuple[str, str, str]] = []

    for r in conn.execute(
            "SELECT k.id, d.description FROM vision_descriptions d "
            "JOIN keyframes k ON k.id = d.keyframe_id WHERE k.video_id = ? "
            "ORDER BY k.timestamp_sec", (video_id,)):
        if needs_translation(r["description"]):
            units.append((KIND_DESCRIPTION, str(r["id"]), r["description"]))

    t = db.get_transcript(conn, video_id)
    if t:
        try:
            segs = json.loads(t["segments_json"] or "[]") or []
        except ValueError:
            segs = []
        for i, seg in enumerate(segs):
            text = (seg or {}).get("text") or ""
            if needs_translation(text):
                units.append((KIND_SEGMENT, str(i), text))

    a = db.get_analysis(conn, video_id)
    if a:
        if needs_translation(a["summary"]):
            units.append((KIND_SUMMARY, "", a["summary"]))
        try:
            full = json.loads(a["full_json"] or "{}")
        except ValueError:
            full = {}
        for i, ev in enumerate(full.get("timeline") or []):
            text = (ev or {}).get("event") or ""
            if needs_translation(text):
                units.append((KIND_TIMELINE, str(i), text))
        # The decoded block's two free-text fields were never collected, so
        # they stayed English in the Chinese UI even on fully translated clips.
        hook = full.get("hook") or {}
        for kind, field in ((KIND_OPENING, "opening_text"), (KIND_CTA, "cta_text")):
            text = (hook.get(field) or "") if isinstance(hook, dict) else ""
            if needs_translation(text):
                units.append((kind, "", text))

    sc = db.get_score(conn, video_id)
    if sc and needs_translation(sc["reasoning"]):
        units.append((KIND_REASONING, "", sc["reasoning"]))
    return units


def translate_video(conn, video_id: str, model: str,
                    base_url: Optional[str] = None,
                    kinds: Optional[List[str]] = None,
                    limit: Optional[int] = None,
                    refresh_stale: bool = True) -> Dict[str, int]:
    """Translate what is missing (and, by default, what has gone stale)."""
    tally = {"translated": 0, "refreshed": 0, "skipped_existing": 0,
             "failed": 0, "candidates": 0, "pruned": 0}
    have = {(r["kind"], r["ref"]): r
            for r in db.get_translations(conn, video_id, lang=LANG)}
    units = [u for u in collect_units(conn, video_id)
             if not kinds or u[0] in kinds]
    tally["candidates"] = len(units)
    done = 0
    for kind, ref, source in units:
        if limit and done >= limit:
            break
        existing = have.get((kind, ref))
        stale = existing is not None and is_stale(existing, source)
        if existing is not None and not stale:
            tally["skipped_existing"] += 1
            continue
        if existing is not None and stale and not refresh_stale:
            tally["skipped_existing"] += 1
            continue
        out = translate_text(source, model, base_url)
        if out is None:
            tally["failed"] += 1
            continue
        db.save_translation(conn, video_id, kind, ref, LANG, source, out,
                            ENGINE_OLLAMA, model)
        tally["refreshed" if stale else "translated"] += 1
        done += 1
    if refresh_stale:
        # A translation whose source is gone is stale in the strongest sense,
        # and `is_stale()` never sees it: it is only asked about sources that
        # still exist. Re-cutting a transcript into fewer segments (the rolling-
        # cue dedupe fix took 66 segments to 64) left the tail rows addressing
        # indexes that no longer exist -- kept forever, matching nothing.
        # Same switch as refreshing: `--keep-stale` keeps these too.
        current = {(k, r) for k, r, _ in units}
        for (kind, ref) in list(have):
            if kinds and kind not in kinds:
                continue
            if (kind, ref) not in current:
                db.delete_translation(conn, video_id, kind, ref, LANG)
                tally["pruned"] += 1
    return tally
