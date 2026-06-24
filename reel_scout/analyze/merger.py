from __future__ import annotations

import json
import sqlite3
from typing import Optional

from .. import config, db
from ..audio.panns import _MUSIC_LABELS
from ..llm import get_llm

# Minimum PANNs confidence for a music label to count as "background music present".
# A real bed (e.g. 2 windows at 0.84) clears this easily; incidental ambient leakage
# below it doesn't flip the flag.
MUSIC_CONF_THRESHOLD = 0.30

_MERGE_PROMPT_TEMPLATE = """You are analyzing a short-form video. Based on the transcript and visual descriptions below, produce a structured JSON analysis.

## Video Metadata
- Title: {title}
- Platform: {platform}
- Duration: {duration_sec}s
- Uploader: {uploader}

## Transcript
{transcript}

## Visual Descriptions (keyframes)
{vision_descriptions}

## Audio Events
{audio_events}

## Output Format (JSON only, no markdown)
{{
  "summary": "1-2 sentence summary of the video content",
  "topics": ["topic1", "topic2"],
  "timeline": [
    {{"timestamp": "0-3s", "event": "hook/opening description"}},
    {{"timestamp": "3-15s", "event": "main content description"}},
    {{"timestamp": "15-20s", "event": "CTA or closing"}}
  ],
  "hook": {{
    "opening_type": "question|statement|visual|music|none",
    "opening_text": "first few words or description",
    "cta_type": "follow|like|comment|link|visit|none",
    "cta_text": "CTA text if any"
  }},
  "style": {{
    "format": "talking_head|montage|tutorial|reaction|skit|vlog|slideshow",
    "pacing": "fast|medium|slow",
    "has_captions": true/false,
    "has_background_music": true/false,
    "text_overlay_count": 0
  }},
  "engagement_signals": {{
    "face_visible": true/false,
    "face_count": 0,
    "emotion": "enthusiastic|calm|serious|humorous|neutral",
    "spoken_language": "language code",
    "subtitle_language": "language code or empty"
  }},
  "content_type": "educational|entertainment|promotional|review|story|news"
}}

IMPORTANT — cta_type: read the LAST transcript segments and final frames before deciding. If the video closes by urging a real-world action — visit a shop, go try/eat somewhere, go check it out (e.g. "快去試試看", "大家快去吃", "就在XX路上") — set "cta_type": "visit" and copy the phrase into cta_text. follow/like/comment/link are ONLY for on-platform engagement. Use "none" ONLY when there is genuinely no closing call to action at all. Do not default to "none" for offline/visit CTAs.

The timeline should capture the narrative arc: how the video progresses from hook to main content to conclusion/CTA. Use approximate time ranges.

Return ONLY valid JSON, no explanation."""


def merge_analysis(
    conn: sqlite3.Connection,
    video_id: str,
) -> None:
    video = db.get_video(conn, video_id)
    transcript = db.get_transcript(conn, video_id)
    keyframes = db.get_keyframes(conn, video_id)

    # Gather vision descriptions
    vision_texts = []
    for kf in keyframes:
        cur = conn.execute(
            "SELECT * FROM vision_descriptions WHERE keyframe_id = ?",
            (kf["id"],),
        )
        vd = cur.fetchone()
        if vd:
            vision_texts.append(
                f"[{kf['timestamp_sec']:.1f}s] {vd['description']}"
            )

    # Build transcript with speaker labels if available
    if transcript:
        import json as _json
        segs = _json.loads(transcript["segments_json"] or "[]")
        if segs and segs[0].get("speaker"):
            transcript_text = "\n".join(
                "[%s] %s" % (s.get("speaker", ""), s.get("text", ""))
                for s in segs
            )
        else:
            transcript_text = transcript["text_full"]
    else:
        transcript_text = "(no transcript)"
    vision_text = "\n".join(vision_texts) if vision_texts else "(no vision data)"

    # Gather audio events
    audio_events = db.get_audio_events(conn, video_id)
    audio_text = "(no audio analysis)"
    if audio_events:
        audio_lines = []
        for ae in audio_events:
            audio_lines.append("[%.1fs-%.1fs] %s: %s (%.0f%%)" % (
                ae["start_sec"], ae["end_sec"], ae["event_type"],
                ae["label"], ae["confidence"] * 100))
        audio_text = "\n".join(audio_lines)

    prompt = _MERGE_PROMPT_TEMPLATE.format(
        title=video["title"] or "(untitled)",
        platform=video["platform"],
        duration_sec=video["duration_sec"] or 0,
        uploader=video["uploader"] or "(unknown)",
        transcript=transcript_text,
        vision_descriptions=vision_text,
        audio_events=audio_text,
    )

    llm = get_llm()
    result_json = llm.complete(prompt, max_tokens=800, temperature=0.1)

    try:
        data = json.loads(result_json)
    except json.JSONDecodeError:
        # Try to extract JSON from response
        import re
        m = re.search(r"\{[\s\S]*\}", result_json)
        if m:
            data = json.loads(m.group())
        else:
            data = {"summary": result_json, "topics": [], "error": "failed to parse JSON"}

    # has_background_music is a measured fact, not a guess. The PANNs audio stage
    # detects music with a confidence score; the merge LLM tends to ignore a music
    # bed under heavy voiceover and emit false (e.g. 17 Speech vs 2 Music windows ->
    # LLM says false even though Music was detected at 0.84). The merge layer must
    # not overwrite a signal an upstream stage actually measured, so the detector
    # decides this one field — the LLM's value is discarded.
    #   - audio ran (events present): True iff any music label clears the threshold.
    #   - audio skipped (no events, the default path): the LLM has no audio signal
    #     either, so mark unknown (None) rather than keep a fabricated bool.
    if audio_events:
        data.setdefault("style", {})["has_background_music"] = any(
            ae["label"] in _MUSIC_LABELS
            and ae["confidence"] >= MUSIC_CONF_THRESHOLD
            for ae in audio_events
        )
    else:
        data.setdefault("style", {})["has_background_music"] = None

    db.save_analysis(
        conn, video_id,
        summary=data.get("summary", ""),
        topics_json=json.dumps(data.get("topics", []), ensure_ascii=False),
        hooks_json=json.dumps(data.get("hook", {}), ensure_ascii=False),
        style_json=json.dumps(data.get("style", {}), ensure_ascii=False),
        engagement_signals_json=json.dumps(
            data.get("engagement_signals", {}), ensure_ascii=False
        ),
        full_json=json.dumps(data, ensure_ascii=False),
    )
