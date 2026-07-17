"""On-screen (burned-in) text collection — the §4F "L3.5" signal layer.

Short-form videos often carry their message as burned-in captions / big on-screen
text rather than (or in addition to) spoken dialogue. That text is:
  - stronger than the L2 platform caption (it's IN the video, not authored for reach)
  - timestamp-alignable like the L3 transcript
  - the only textual signal for low-dialogue / pure-visual reels (the documented L3
    gap in prompts/signal-reliability-cheatsheet.md)

so it slots between L3 and L4 as "L3.5". Two engines:

  * "vlm" (default, zero new deps): reuse what the vision model already read into
    `vision_descriptions.text_in_frame`.
  * "tesseract" (opt-in, guarded): OCR the keyframe JPEGs directly — stronger CJK,
    but a heavy dependency, so off by default and falls back to vlm if unavailable.

Borrowed from crv Pro's `--ocr`; implementation our own.
"""
from __future__ import annotations

import importlib.util
from typing import Dict, List, Optional

from . import config, db


def _tesseract_available() -> bool:
    return (
        importlib.util.find_spec("pytesseract") is not None
        and importlib.util.find_spec("PIL") is not None
    )


def _ocr_image(image_path: str) -> str:
    """Dedicated-engine OCR of one keyframe. Best-effort: returns '' if pytesseract
    / Pillow / the tesseract binary are missing or the call errors."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    try:
        return pytesseract.image_to_string(Image.open(image_path)).strip()
    except Exception:  # noqa: BLE001 — OCR is best-effort, never fatal
        return ""


def collect_captions(
    conn: db.sqlite3.Connection,
    video_id: str,
    engine: Optional[str] = None,
) -> List[Dict]:
    """Gather timestamped on-screen text for a video as the L3.5 layer.

    Default engine reuses the VLM's text_in_frame (no new deps). When engine is
    'tesseract' and it's actually installed, each keyframe JPEG is OCR'd instead,
    falling back to the VLM text for any frame the engine reads as empty.
    """
    engine = engine or config.OCR_ENGINE
    use_tess = engine == "tesseract" and _tesseract_available()

    captions = []  # type: List[Dict]
    for r in db.get_keyframes_with_descriptions(conn, video_id):
        text = ""
        src = "vlm"
        if use_tess and r["file_path"]:
            text = _ocr_image(r["file_path"])
            if text:
                src = "tesseract"
        if not text:
            # vlm default, or tesseract-found-nothing fallback
            text = (r["text_in_frame"] or "").strip()
            src = "vlm"
        if text:
            captions.append(
                {"timestamp_sec": r["timestamp_sec"], "text": text, "engine": src}
            )
    return captions
