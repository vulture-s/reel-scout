"""Provider-agnostic temporal-vision interface (DESIGN.md §2).

reel-scout's existing `BaseVLM.describe_frame(image_path)` is single-frame: each frame
is captioned in isolation, so motion / progression / "what changed" is lost and the
merge step only ever sees disconnected sentences. That is the core weakness this layer
fixes.

`BaseTemporalVision.describe_clip(ClipPayload)` instead hands a backend the whole clip
(an ordered set of frames + their timestamps, optional audio markers, transcript, and —
for backends that can ingest video natively — the video path). Every backend consumes
the *same* ClipPayload; they differ only in how they render it to their model:

  - contact-sheet backends (local Qwen2.5-VL / minicpm / llava, or Claude / Codex via
    proxy) stitch the frames into a timestamped grid image (see contact_sheet.py) and
    send that — one call, temporally coherent.
  - native-video backends (Gemini) upload `video_path` and reason over it directly.

This is what keeps the pipeline local-first (default = local contact-sheet, no network)
while staying swappable to any cloud model without changing callers.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Frame:
    """One selected keyframe: where it is on disk and when it occurs in the clip."""
    path: str
    timestamp_sec: float
    index: int = 0


@dataclass
class AudioMarker:
    """An audio event aligned to the timeline (from PANNs), for audio-visual fusion."""
    event_type: str          # music | speech | silence | applause | sound_effect
    label: str
    start_sec: float
    end_sec: float


@dataclass
class ClipPayload:
    """Everything a temporal-vision backend needs to reason about one clip.

    `frames` is already selected upstream (smart-select); backends do not re-sample.
    `video_path` is only consumed by native-video backends; contact-sheet backends
    ignore it and render `frames`.
    """
    frames: List[Frame]
    duration_sec: float
    audio_markers: Optional[List[AudioMarker]] = None
    transcript_text: Optional[str] = None
    video_path: Optional[str] = None
    hints: Dict[str, object] = field(default_factory=dict)


@dataclass
class SceneSegment:
    start_sec: float
    end_sec: float
    description: str
    objects: List[str] = field(default_factory=list)
    text_in_frame: str = ""


@dataclass
class SceneAnalysis:
    """Temporal description of a clip — segments over time plus a one-line summary.

    Unlike a list of independent frame captions, this is allowed to reference motion and
    progression across frames ("the UI columns slide left as a new scene is inserted").
    """
    segments: List[SceneSegment] = field(default_factory=list)
    summary: str = ""
    backend: str = ""


class BaseTemporalVision(abc.ABC):
    @abc.abstractmethod
    def describe_clip(self, clip: ClipPayload) -> SceneAnalysis:
        """Produce a temporal description of the whole clip."""
        ...
