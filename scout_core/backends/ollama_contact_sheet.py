"""Local-first temporal-vision backend: contact-sheet -> Ollama VLM (DESIGN.md §2).

Renders a clip's selected frames into a timestamped contact sheet (one image) and
sends that to an Ollama vision model (e.g. minicpm-v on the mini, qwen3-vl:8b on the
M2 Max). One call per sheet — the model sees the whole sequence and can describe how
the video PROGRESSES, instead of captioning frames in isolation.

No new deps: mirrors reel_scout.vision.ollama (urllib + base64 -> /api/generate).
The exact same contact-sheet image is what a Claude/Codex backend would send; only
the HTTP call differs, which is the point — local-first, provider-swappable.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.request
from typing import List

from ..temporal_vision import (
    BaseTemporalVision,
    ClipPayload,
    SceneAnalysis,
    SceneSegment,
)
from ..contact_sheet import build_contact_sheets, ContactSheet


_PROMPT = """You are shown a CONTACT SHEET: a grid of still frames sampled from ONE \
video, in time order (left-to-right, top-to-bottom). Each frame is labelled in its \
top-left corner with an index and timestamp, e.g. "#0  0:00", "#3  0:29".

Read the frames as a SEQUENCE. Describe how the video progresses over time — the \
setting, the action, what changes from frame to frame — not each frame in isolation.

Return ONLY valid JSON, no markdown:
{
  "summary": "1-2 sentences: what the video is and how it unfolds",
  "segments": [
    {"start_sec": 0.0, "end_sec": 4.0, "description": "what happens here",
     "objects": ["key", "objects"], "text_in_frame": "any on-screen text or empty"}
  ]
}
Use the timestamps printed on the frames for start_sec / end_sec. Return only JSON."""


class OllamaContactSheetVision(BaseTemporalVision):
    def __init__(self, base_url: str, model: str, sheet_dir: str,
                 max_cells_per_sheet: int = 12, timeout: int = 300) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._sheet_dir = sheet_dir
        self._max_cells = max_cells_per_sheet
        self._timeout = timeout

    def describe_clip(self, clip: ClipPayload) -> SceneAnalysis:
        frames = [(f.path, f.timestamp_sec) for f in clip.frames]
        sheets = build_contact_sheets(
            frames, self._sheet_dir, prefix="clip",
            max_cells_per_sheet=self._max_cells,
        )
        if not sheets:
            return SceneAnalysis(summary="(no frames)", backend=self._backend_id())

        all_segments: List[SceneSegment] = []
        summaries: List[str] = []
        for sheet in sheets:
            raw = self._ask(sheet)
            parsed = _parse_json(raw)
            summaries.append(parsed.get("summary", ""))
            for seg in parsed.get("segments", []) or []:
                all_segments.append(SceneSegment(
                    start_sec=_f(seg.get("start_sec")),
                    end_sec=_f(seg.get("end_sec")),
                    description=str(seg.get("description", "")),
                    objects=list(seg.get("objects", []) or []),
                    text_in_frame=str(seg.get("text_in_frame", "")),
                ))

        all_segments.sort(key=lambda s: s.start_sec)
        return SceneAnalysis(
            segments=all_segments,
            summary=" ".join(s for s in summaries if s).strip(),
            backend=self._backend_id(),
        )

    # --- internals ---------------------------------------------------------
    def _backend_id(self) -> str:
        return "ollama-contact-sheet:%s" % self._model

    def _ask(self, sheet: ContactSheet) -> str:
        with open(sheet.image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")
        payload = {
            "model": self._model,
            "prompt": _PROMPT,
            "images": [img_b64],
            "stream": False,
            "options": {"temperature": 0.1},
        }
        req = urllib.request.Request(
            "%s/api/generate" % self._base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode("utf-8")).get("response", "")


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return {"summary": text.strip()[:300], "segments": []}
