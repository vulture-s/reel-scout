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
from typing import Any, Dict, Optional

from . import compare, db
from .llm import get_llm

_INSPIRE_PROMPT = """You are a short-form video strategist. Below is the structured analysis of a video that already performs well. Propose ONE fresh variant that reuses its winning structure — do not copy its exact content.

## Proven video analysis
{analysis_json}

## Requested angle / twist
{angle}

## Output Format (JSON only, no markdown)
{{
  "titles": ["title option 1", "title option 2", "title option 3"],
  "hook_script": "the first 1-3 seconds, spoken/written verbatim",
  "structure_outline": ["beat 1: ...", "beat 2: ...", "beat 3: ..."],
  "recommended_length_sec": 30,
  "rationale": "1-2 sentences on why this reuses the proven structure"
}}

Return ONLY valid JSON."""


def generate_inspiration(
    conn: db.sqlite3.Connection,
    ref: str,
    angle: str = "",
    llm_backend: Optional[str] = None,
) -> Dict[str, Any]:
    video_id, matches = compare.resolve_ref(conn, ref)
    if video_id is None:
        if matches:
            raise ValueError("Ambiguous video ref '%s' matches: %s" % (ref, ", ".join(matches)))
        raise ValueError("No video found for ref: %s" % ref)

    analysis = db.get_analysis(conn, video_id)
    if not analysis or not analysis["full_json"]:
        raise ValueError("No analysis found for video: %s (run analyze first)" % video_id)

    prompt = _INSPIRE_PROMPT.format(
        analysis_json=analysis["full_json"],
        angle=angle.strip() if angle and angle.strip() else "(keep the same niche and audience)",
    )
    llm = get_llm(llm_backend)
    text = llm.complete(prompt, max_tokens=600, temperature=0.7)

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
    return "\n".join(lines)
