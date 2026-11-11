"""Build the CLAP sound-search index for analyzed clips that have none yet.

`audio_clap` / `audio_clap_windows` are additive tables (schema v24); clips
analyzed before them, or analyzed on a machine without the `clap` extra or the
model files, carry no rows. Re-running `analyze` to get them would redo
transcription, vision and the merge. This pass touches nothing but those two
tables.

A clip indexed with a different model revision counts as missing (its vectors
are in another space).

Outcomes, kept apart on purpose (same shape as `backfill_loudness`):
  filled            embedded and stored
  skipped_no_media  this machine no longer has the file (not a failure)
  no_audio          the file has no audio stream (stores nothing)
  failed            decode or inference failed
"""
from __future__ import annotations

import sys
import time
from typing import Any, Dict, Optional

from .audio import clap
from .utils import paths as media_paths


def candidates(conn) -> list:
    return conn.execute(
        "SELECT v.id, v.file_path, v.title FROM videos v "
        "WHERE v.status = 'analyzed' "
        "AND NOT EXISTS (SELECT 1 FROM audio_clap c WHERE c.video_id = v.id "
        "                AND c.revision = ?) "
        "ORDER BY v.created_at", (clap.MODEL_REVISION,)
    ).fetchall()


def backfill(conn, dry_run: bool = False, limit: Optional[int] = None,
             progress: bool = False, model: Any = None) -> Dict[str, Any]:
    """Raises clap.ClapUnavailable (before touching anything) when CLAP cannot run."""
    rows = candidates(conn)
    total = len(rows)
    if limit:
        rows = rows[:limit]
    out: Dict[str, Any] = {"candidates": total, "filled": 0, "skipped_no_media": 0,
                           "no_audio": 0, "failed": 0, "windows": 0,
                           "seconds": 0.0, "audio_seconds": 0.0}
    if not dry_run and rows and model is None:
        model = clap.load()
    for i, r in enumerate(rows, 1):
        if not r["file_path"] or not media_paths.exists(r["file_path"]):
            out["skipped_no_media"] += 1
            continue
        if dry_run:
            out["filled"] += 1
            continue
        path = media_paths.resolve_media_path(r["file_path"])
        t0 = time.time()
        try:
            res = clap.index_video(conn, r["id"], path, model=model)
        except clap.NoAudio:
            out["no_audio"] += 1
            continue
        except Exception as e:  # noqa: BLE001 — one bad file must not stop the pass
            out["failed"] += 1
            if progress:
                print("  [%d/%d] %s: %s" % (i, len(rows), r["id"], e), file=sys.stderr)
            continue
        dt = time.time() - t0
        out["filled"] += 1
        out["windows"] += res["windows"]
        out["seconds"] += dt
        out["audio_seconds"] += res.get("duration_s") or 0.0
        if progress:
            print("  [%d/%d] %s  %d window(s), %.1fs audio in %.1fs"
                  % (i, len(rows), r["id"], res["windows"], res.get("duration_s") or 0.0, dt))
    return out
