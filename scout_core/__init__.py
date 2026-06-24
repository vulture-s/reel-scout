"""scout-core — shared substrate for reel-scout (short-form) and Longshot (long-form).

This is the package both tools depend on (design decision A, DESIGN.md §3). It holds
the provider-agnostic temporal-vision interface and the contact-sheet encoder that make
"local-first" and "Claude/Codex/Gemini swappable" the same thing.

NOTE: during the split, crawl / transcribe / audio / db will also move here. The
contact-sheet + temporal-vision pieces land first because they are the load-bearing
innovation and are verifiable in isolation (no behaviour change to reel-scout).
"""

from .temporal_vision import (
    Frame,
    AudioMarker,
    ClipPayload,
    SceneAnalysis,
    BaseTemporalVision,
)
from .contact_sheet import build_contact_sheets, ContactSheet

__all__ = [
    "Frame",
    "AudioMarker",
    "ClipPayload",
    "SceneAnalysis",
    "BaseTemporalVision",
    "build_contact_sheets",
    "ContactSheet",
]
