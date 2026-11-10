"""Measure programme loudness for analyzed clips that have none yet.

`audio_loudness` is an additive table (schema v23); clips analyzed before it
exist carry no row, and re-running `analyze` to get one would redo transcription,
vision and the merge. This pass touches nothing but `audio_loudness`.

Cheap: ebur128 decodes audio only, ~200x realtime on an M2 Max.

Same three outcomes as `backfill_shots`, kept apart on purpose:
  filled            measured and stored
  skipped_no_media  this machine no longer has the file (not a failure)
  no_audio          the file has no audio stream (stored as nothing, not -70)
  failed            ffmpeg ran and could not measure
"""
from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from . import db
from .audio.loudness import NoAudio, measure
from .utils import paths as media_paths


def candidates(conn) -> list:
    return conn.execute(
        "SELECT v.id, v.file_path, v.title FROM videos v "
        "WHERE v.status = 'analyzed' "
        "AND NOT EXISTS (SELECT 1 FROM audio_loudness l WHERE l.video_id = v.id) "
        "ORDER BY v.created_at"
    ).fetchall()


def backfill(conn, dry_run: bool = False, limit: Optional[int] = None,
             progress: bool = False) -> Dict[str, Any]:
    rows = candidates(conn)
    total = len(rows)
    if limit:
        rows = rows[:limit]
    out = {"candidates": total, "filled": 0, "skipped_no_media": 0,
           "no_audio": 0, "failed": 0}
    for i, r in enumerate(rows, 1):
        if not r["file_path"] or not media_paths.exists(r["file_path"]):
            out["skipped_no_media"] += 1
            continue
        if dry_run:
            out["filled"] += 1
            continue
        path = media_paths.resolve_media_path(r["file_path"])
        try:
            m = measure(path)
        except NoAudio:
            out["no_audio"] += 1
            continue
        except Exception as e:  # noqa: BLE001 — one bad file must not stop the pass
            out["failed"] += 1
            if progress:
                print("  [%d/%d] %s: %s" % (i, len(rows), r["id"], e), file=sys.stderr)
            continue
        db.save_audio_loudness(conn, r["id"], **m)
        out["filled"] += 1
        if progress:
            print("  [%d/%d] %s  %.1f LUFS" % (i, len(rows), r["id"], m["integrated_lufs"]))
    return out
