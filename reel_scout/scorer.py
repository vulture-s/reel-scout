from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from . import config, db
from .llm import get_llm

_SCORE_PROMPT = """You are a short-form video content analyst. Based on the analysis below, score this video on 4 dimensions (0-10 scale, decimals ok).

## Video Analysis
{analysis_json}

## Scoring Criteria
- hook_strength (0-10): How compelling is the opening? Does it grab attention in the first 1-2 seconds? (signal: hook.opening_type, timeline 0-3s)
- visual_storytelling (0-10): Do the visuals carry the story on their own — shot variety, framing, visual information — readable even with the sound off? (signal: keyframe visual descriptions, style.format, faces)
- pacing (0-10): Does the rhythm hold attention — cut frequency, beat changes, on-screen text density, no dead air? (signal: style.pacing, text_overlay_count, number of timeline segments)
- structure (0-10): Is there a complete arc (setup -> build -> payoff) that lands its ending? A clear call-to-action at the close is a plus. (signal: timeline narrative arc, hook.cta_type/cta_text)

## Output Format (JSON only)
{{
  "hook_strength": 0.0,
  "visual_storytelling": 0.0,
  "pacing": 0.0,
  "structure": 0.0,
  "overall": 0.0,
  "reasoning": "1-2 sentence explanation"
}}

The overall score is the weighted average: hook_strength*0.3 + visual_storytelling*0.25 + pacing*0.2 + structure*0.25

Return ONLY valid JSON."""


@dataclass
class VideoScore:
    hook_strength: float = 0.0
    visual_storytelling: float = 0.0
    pacing: float = 0.0
    structure: float = 0.0
    overall: float = 0.0
    reasoning: str = ""
    model_used: str = ""


def score_video(
    conn: db.sqlite3.Connection,
    video_id: str,
    llm_backend: Optional[str] = None,
) -> VideoScore:
    """Score a video using LLM analysis."""
    analysis = db.get_analysis(conn, video_id)
    if not analysis:
        raise ValueError("No analysis found for video: %s" % video_id)

    analysis_json = analysis["full_json"] or "{}"
    prompt = _SCORE_PROMPT.format(analysis_json=analysis_json)

    llm = get_llm(llm_backend)
    result_text = llm.complete(prompt, max_tokens=300, temperature=0.2)

    # Parse JSON response
    try:
        data = json.loads(result_text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", result_text)
        if m:
            data = json.loads(m.group())
        else:
            data = {}

    hook = float(data.get("hook_strength", 0))
    visual = float(data.get("visual_storytelling", 0))
    pacing = float(data.get("pacing", 0))
    structure = float(data.get("structure", 0))
    # overall is COMPUTED from the dimensions (weights must match _SCORE_PROMPT).
    # The LLM's self-reported "overall" drifts ~0.1 from the formula, so we ignore it
    # and recompute — keeps tool output self-consistent with the four dimensions.
    overall = round(hook * 0.3 + visual * 0.25 + pacing * 0.2 + structure * 0.25, 2)
    score = VideoScore(
        hook_strength=hook,
        visual_storytelling=visual,
        pacing=pacing,
        structure=structure,
        overall=overall,
        reasoning=str(data.get("reasoning", "")),
        model_used=llm_backend or config.LLM_BACKEND,
    )

    # Save to DB
    db.save_score(conn, video_id, score)
    return score
