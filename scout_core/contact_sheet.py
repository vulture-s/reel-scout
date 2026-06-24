"""Contact-sheet encoder — the universal substrate (DESIGN.md §2, §4 T1).

Stitches an ordered set of frames into a grid image with each cell labelled by its
index and timestamp. This single image is what lets one VLM call reason over a whole
sequence (motion, progression, structure) instead of captioning frames in isolation —
and because a grid-of-frames is *just an image*, the exact same artifact runs on a
local VLM, Claude, Codex, or any vision model. It is the thing that makes the pipeline
both local-first and provider-agnostic.

Design choices:
  - Cap cells per sheet (default 12) for legibility: too many frames and a VLM can't
    resolve detail. More frames than the cap -> multiple sheets, returned in order.
  - Burn the timestamp + index into each cell so the model (and audio-visual fusion
    downstream) can refer to "frame 3 @0:04" precisely.
  - No model dependency here — pure Pillow. Backends consume ContactSheet.image_path.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


@dataclass
class ContactSheet:
    image_path: str
    # Which frame indices/timestamps occupy each cell, in reading order — lets a caller
    # map the model's "cell N" references back to real timeline positions.
    cells: List[Tuple[int, float]] = field(default_factory=list)
    sheet_index: int = 0
    total_sheets: int = 1


def _fmt_ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return ("%d:%02d:%02d" % (h, m, s)) if h else ("%d:%02d" % (m, s))


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    # Try a few common faces; fall back to Pillow's bitmap default (always present).
    for name in ("arial.ttf", "DejaVuSans.ttf", "Helvetica.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def build_contact_sheets(
    frames: List[Tuple[str, float]],
    out_dir: str,
    prefix: str = "sheet",
    cell_w: int = 480,
    max_cells_per_sheet: int = 12,
    cols: Optional[int] = None,
    label_h: int = 22,
    pad: int = 6,
) -> List[ContactSheet]:
    """Render `frames` (list of (image_path, timestamp_sec)) into one or more grids.

    Returns ContactSheet objects in temporal order. Frames whose image is missing are
    skipped (degraded, not fatal) so one bad extraction can't kill the sheet.
    """
    usable = [(p, ts) for (p, ts) in frames if p and os.path.exists(p)]
    if not usable:
        return []

    os.makedirs(out_dir, exist_ok=True)
    sheets: List[ContactSheet] = []
    chunks = [
        usable[i : i + max_cells_per_sheet]
        for i in range(0, len(usable), max_cells_per_sheet)
    ]
    font = _load_font(15)

    for sheet_idx, chunk in enumerate(chunks):
        n = len(chunk)
        ncols = cols or min(4, max(1, math.ceil(math.sqrt(n))))
        nrows = math.ceil(n / ncols)

        # Derive a uniform cell height from the first image's aspect ratio.
        with Image.open(chunk[0][0]) as im0:
            ar = (im0.height / im0.width) if im0.width else 9 / 16
        cell_h = int(cell_w * ar)
        tile_w = cell_w + pad * 2
        tile_h = cell_h + label_h + pad * 2

        sheet = Image.new("RGB", (tile_w * ncols, tile_h * nrows), (18, 18, 18))
        draw = ImageDraw.Draw(sheet)
        cells_meta: List[Tuple[int, float]] = []

        for k, (path, ts) in enumerate(chunk):
            r, c = divmod(k, ncols)
            x0, y0 = c * tile_w + pad, r * tile_h + pad
            try:
                with Image.open(path) as im:
                    im = im.convert("RGB").resize((cell_w, cell_h))
                    sheet.paste(im, (x0, y0 + label_h))
            except Exception:
                draw.rectangle(
                    [x0, y0 + label_h, x0 + cell_w, y0 + label_h + cell_h],
                    fill=(40, 40, 40),
                )
            # Global frame index across all sheets (k offset by prior chunks).
            global_idx = sheet_idx * max_cells_per_sheet + k
            draw.text((x0, y0), "#%d  %s" % (global_idx, _fmt_ts(ts)),
                      fill=(255, 210, 90), font=font)
            cells_meta.append((global_idx, ts))

        out_path = os.path.join(out_dir, "%s_%02d.jpg" % (prefix, sheet_idx))
        sheet.save(out_path, "JPEG", quality=88)
        sheets.append(ContactSheet(
            image_path=out_path,
            cells=cells_meta,
            sheet_index=sheet_idx,
            total_sheets=len(chunks),
        ))

    return sheets
