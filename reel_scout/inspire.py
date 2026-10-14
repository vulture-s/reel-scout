"""Content inspiration generator (roadmap 4B).

Takes a video that already scored well and proposes a fresh *variant* — title
options, a hook script, a beat-by-beat structure outline, and a recommended
length — optionally twisted toward a new angle. This is the "from analysis to
action" step: the reverse-decoded structure of a proven video becomes a
scaffold for the next one, not a copy.

Read + one LLM call. Reuses compare.resolve_ref (id or unique prefix) and the
shared LLM backend.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from . import compare, config, db, name_guard, zh_convert
from .llm import get_llm
from .utils.stderr import warn

_INSPIRE_PROMPT = """You are a short-form video strategist. Below is the structured analysis of a video that already performs well. Propose ONE fresh variant that reuses its winning structure — do not copy its exact content.

## Proven video analysis
{analysis_json}

## Requested angle / twist
{angle}
{language_rule}{entity_rule}
## Output Format (JSON only, no markdown)
{{
  "titles": ["title option 1", "title option 2", "title option 3"],
  "hook_script": "the first 1-3 seconds, spoken/written verbatim",
  "structure_outline": ["beat 1: ...", "beat 2: ...", "beat 3: ..."],
  "recommended_length_sec": 30,
  "rationale": "1-2 sentences on why this reuses the proven structure"
}}

Return ONLY valid JSON."""


_OUTPUT_LANGUAGE_RULE = (
    "\n## Output language (mandatory)\n"
    "Write every human-readable value (titles, hook_script, structure_outline, rationale) "
    "in Traditional Chinese as used in Taiwan (zh-TW, 繁體中文). This applies no matter "
    "what language the requested angle or the proven video analysis above is written in.\n"
    "- NEVER use Simplified Chinese characters (简体字). Use Taiwan-standard forms, e.g. "
    "「影片」not「视频」,「內容」not「内容」,「結構」not「结构」,「這」not「这」.\n"
    "- Bilingual gloss for English domain terms: when a professional term, technique or "
    "concept comes from English, write the Traditional Chinese term followed by the English "
    "original in full-width parentheses on its first use, e.g. 「動態範圍（Dynamic Range）」, "
    "「跳切（Jump Cut）」. Gloss only individual terms of a few words — never append an "
    "English translation to a whole title, sentence or beat.\n"
    "- Keep brand names, product model numbers and proper nouns in their original form "
    "(e.g. Sony FX3, DaVinci Resolve) — do not translate or transliterate them.\n"
    "- Keep the JSON keys in English exactly as shown.\n"
)


_ENTITY_RULE = (
    "\n## Real names stay real (mandatory)\n"
    "The analysis above is the source of truth about which real things appear in the video. "
    "Every tool, app, website, brand, product model, person's name and channel name it mentions "
    "MUST be written exactly as it appears there — do not rename it, do not invent a substitute "
    "or fictional name, and do not transliterate it. \"Fresh variant\" means changing the "
    "structure, angle and copy — never swapping out a real entity for a made-up one.\n"
)


def _get_converter(mode: Optional[str] = None, hotwords_path: Optional[str] = None) -> Any:
    """The source converter (OpenCC per mode, then hotwords) -- see zh_convert."""
    return zh_convert.build_converter(mode, hotwords_path)


def _to_traditional(value: Any, convert: Any) -> Any:
    """Convert every string *value* in a JSON tree; keys are left untouched."""
    if isinstance(value, str):
        return convert(value)
    if isinstance(value, list):
        return [_to_traditional(v, convert) for v in value]
    if isinstance(value, dict):
        return {k: _to_traditional(v, convert) for k, v in value.items()}
    return value


def _analysis_for_prompt(full_json: str, zh_mode: Optional[str] = None,
                         zh_hotwords: Optional[str] = None) -> str:
    """The analysis JSON as fed to the prompt, with values in zh-TW Traditional.

    2026-10-14 Hevin's decision (b): a Simplified-Chinese analysis pulled
    qwen2.5:14b into echoing Simplified sentences (~3/23 runs) despite the
    output-language rule. Fix it at the source: the copy that goes into the
    prompt is already Traditional. Only this in-memory copy changes -- the DB
    row is never written back -- and the model's *output* is not converted.
    s2twp leaves Latin letters alone, so brands / model numbers survive.

    Mode (s2twp / s2tw / off) and the hotword table come from the arguments,
    else REEL_SCOUT_ZH_CONVERT / REEL_SCOUT_ZH_HOTWORDS. Hotwords run after
    OpenCC, so they also apply when OpenCC is missing or turned off.
    """
    converter = _get_converter(zh_mode, zh_hotwords)
    if converter.opencc_missing:
        warn("inspire: opencc not installed — analysis sent to the LLM unconverted "
             "(Simplified text in it may leak into the output). %s" % zh_convert.INSTALL_HINT)
    if converter.opencc is None and not converter.table:
        return full_json
    try:
        tree = json.loads(full_json)
    except (TypeError, ValueError):
        # Not JSON: convert the text as a whole. s2twp touches only Han
        # characters, so any English keys in it are unaffected.
        return converter(full_json)
    return json.dumps(_to_traditional(tree, converter), ensure_ascii=False)


def _language_rule(angle: str = "") -> str:
    """Prompt block that pins the output language — always zh-TW + bilingual gloss.

    History: the English template + an English analysis JSON pulled a Chinese
    angle into English titles (2026-07-29); #208 then made the output follow
    the angle's language, but qwen2.5:14b ignored "same language" and answered
    an English angle on a Chinese-analysed video in *Simplified* Chinese.
    2026-10-14 Hevin's decision: inspire output is ALWAYS Traditional Chinese
    (zh-TW), never Simplified, with English domain terms glossed bilingually
    and brands / model numbers kept verbatim — regardless of the angle's or
    the analysis's language. ``angle`` is accepted only for call-site
    compatibility; it no longer changes the rule.
    """
    return _OUTPUT_LANGUAGE_RULE


_RETRY_BLOCK = (
    "\n## Your previous answer was rejected (real names)\n"
    "Previous answer:\n{previous}\n\n"
    "Problems found by comparing it with the analysis above:\n{problems}\n"
    "Write the variant again. Keep every real name exactly as the analysis spells it, "
    "and do not introduce any tool, app, website, brand, model or person name that the "
    "analysis does not contain. Return ONLY valid JSON in the format above."
)


def _retry_prompt(prompt: str, previous: str, missing: List[str], invented: List[str]) -> str:
    problems = []
    if missing:
        problems.append("- Real names from the analysis that are missing or were replaced "
                        "(each must appear, spelled exactly): " + ", ".join(missing))
    if invented:
        problems.append("- Names that do not exist in the analysis (invented or substituted "
                        "-- remove them): " + ", ".join(invented))
    return prompt + _RETRY_BLOCK.format(previous=previous.strip()[:2000], problems="\n".join(problems))


def _parse_reply(text: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {"raw": text}
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                data = {"raw": text}  # braced text that still isn't valid JSON
    if not isinstance(data, dict):
        data = {"raw": text}
    return data


def generate_inspiration(
    conn: db.sqlite3.Connection,
    ref: str,
    angle: str = "",
    llm_backend: Optional[str] = None,
    name_retries: Optional[int] = None,
    zh_mode: Optional[str] = None,
    zh_hotwords: Optional[str] = None,
) -> Dict[str, Any]:
    """One variant, checked against the analysis for real names.

    After the model answers, ``name_guard.check`` compares its real names with
    the analysis. On a miss (a name dropped / replaced, or a name the analysis
    never mentions) the model is re-asked with the list of what was wrong, at
    most ``name_retries`` times (default ``INSPIRE_NAME_RETRIES``, 2). The
    result always carries ``name_check``: ``status`` is ``passed`` or
    ``failed`` -- a failed check is reported, never passed off as success; the
    answer returned is the attempt with the fewest problems (latest on a tie),
    and ``warning`` says in words what is still wrong.
    """
    video_id, matches = compare.resolve_ref(conn, ref)
    if video_id is None:
        if matches:
            raise ValueError("Ambiguous video ref '%s' matches: %s" % (ref, ", ".join(matches)))
        raise ValueError("No video found for ref: %s" % ref)

    analysis = db.get_analysis(conn, video_id)
    if not analysis or not analysis["full_json"]:
        raise ValueError("No analysis found for video: %s (run analyze first)" % video_id)

    retries = config.INSPIRE_NAME_RETRIES if name_retries is None else int(name_retries)
    if retries < 0:
        raise ValueError("name_retries must be >= 0")

    sent_analysis = _analysis_for_prompt(analysis["full_json"], zh_mode, zh_hotwords)
    prompt = _INSPIRE_PROMPT.format(
        analysis_json=sent_analysis,
        angle=angle.strip() if angle and angle.strip() else "(keep the same niche and audience)",
        language_rule=_language_rule(angle),
        entity_rule=_ENTITY_RULE,
    )
    try:
        entities = name_guard.extract_entities(json.loads(sent_analysis))
    except (TypeError, ValueError):
        entities = name_guard.extract_entities(sent_analysis)
    known_text = "\n".join((sent_analysis, analysis["full_json"], angle or ""))

    llm = get_llm(llm_backend)
    history: List[Dict[str, Any]] = []
    best: Optional[Dict[str, Any]] = None
    best_problems = None
    best_found: Dict[str, List[str]] = {"missing": [], "invented": []}
    ask = prompt
    for attempt in range(1, retries + 2):
        text = llm.complete(ask, max_tokens=600, temperature=0.7)
        data = _parse_reply(text)
        found = name_guard.check(entities, known_text, data)
        history.append({"attempt": attempt, "missing": found["missing"], "invented": found["invented"]})
        problems = len(found["missing"]) + len(found["invented"])
        if best_problems is None or problems <= best_problems:
            best, best_problems = data, problems
            best_found = found
        if problems == 0:
            break
        ask = _retry_prompt(prompt, text, found["missing"], found["invented"])

    data = best if best is not None else {}
    passed = best_problems == 0
    data["name_check"] = {
        "status": "passed" if passed else "failed",
        "attempts": len(history),
        "max_retries": retries,
        "entities": entities,
        "missing": best_found["missing"],
        "invented": best_found["invented"],
        "history": history,
    }
    if not passed:
        bits = []
        if best_found["missing"]:
            bits.append("missing/replaced: " + ", ".join(best_found["missing"]))
        if best_found["invented"]:
            bits.append("not in the analysis: " + ", ".join(best_found["invented"]))
        data["warning"] = ("real-name check FAILED after %d attempt(s) — %s"
                           % (len(history), "; ".join(bits)))
    data["based_on"] = video_id
    data["angle"] = angle or ""
    return data


def format_inspiration(data: Dict[str, Any]) -> str:
    lines = []
    lines.append("Inspiration based on %s" % data.get("based_on", "?"))
    if data.get("angle"):
        lines.append("Angle: %s" % data["angle"])
    lines.append("=" * 44)
    titles = data.get("titles") or []
    if titles:
        lines.append("Titles:")
        for t in titles:
            lines.append("  - %s" % t)
    if data.get("hook_script"):
        lines.append("\nHook: %s" % data["hook_script"])
    outline = data.get("structure_outline") or []
    if outline:
        lines.append("\nStructure:")
        for i, beat in enumerate(outline, 1):
            lines.append("  %d. %s" % (i, beat))
    if data.get("recommended_length_sec"):
        lines.append("\nRecommended length: %ss" % data["recommended_length_sec"])
    if data.get("rationale"):
        lines.append("Why: %s" % data["rationale"])
    if data.get("raw"):
        lines.append("\n(LLM did not return JSON)\n%s" % data["raw"])
    check = data.get("name_check") or {}
    if check.get("status") == "failed":
        lines.append("\n!! %s" % data.get("warning", "real-name check FAILED"))
    elif check.get("status") == "passed" and check.get("attempts", 1) > 1:
        lines.append("\n(real-name check passed on attempt %d)" % check["attempts"])
    return "\n".join(lines)
