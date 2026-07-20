"""Write externally-produced judgment back into the DB — "the agent is the backend".

The pipeline's VLM and LLM stages both assume a local model endpoint (`oMLX` /
`ollama`). Someone without one is not actually stuck: keyframe extraction is
**ffmpeg, not a model**, so the frames exist on disk before the VLM stage ever
runs. An agent that can see images can describe those frames and apply the craft
rubric itself, and this module is how that result gets back into the database —
so it lands in `show`, `view`, `inspect` and the exported bundle like any other
analysis, instead of evaporating in a chat transcript.

Two rules here are load-bearing, not stylistic:

1. **Provenance is mandatory.** Craft scores are strongly model-dependent — the
   same clip scored 7.43 under qwen3-vl:8b and 5.5 under qwen2.5vl:7b. A row an
   agent produced must stay distinguishable from one a local VLM produced, or a
   classroom ends up comparing numbers that were never comparable. Every row
   written here is tagged `agent:<model>`.

2. **`overall` is recomputed, never accepted.** `scorer.py` deliberately discards
   the model's self-reported overall because it drifts from the weighted formula.
   We apply the identical weights, so an agent-scored video sits on the same
   scale as a locally-scored one on that axis at least.

Caveat worth knowing: `stats` aggregates scores without grouping by
`model_used`, so a corpus mixing agent-scored and locally-scored videos will
blend two scales in its averages. Per-video reads are unaffected.
"""

from typing import Any, Dict, List, Optional, Tuple

from . import db

# Weights duplicated from scorer._SCORE_PROMPT / scorer.score_video. If those
# ever change, this must change with them or the two paths silently diverge —
# tests/test_ingest.py pins them against the scorer module to catch that.
_WEIGHTS = {
    "hook_strength": 0.3,
    "visual_storytelling": 0.25,
    "pacing": 0.2,
    "structure": 0.25,
}

_DIMENSIONS = tuple(_WEIGHTS)

#: Backend label for anything an agent produced rather than a local VLM/LLM.
AGENT_BACKEND = "agent"


def provenance(model: str) -> str:
    """`agent:<model>` — the string stamped into `model_used` / `vlm_model`."""
    model = (model or "").strip()
    if not model:
        raise ValueError("a model name is required so the row's origin stays traceable")
    return model if model.startswith(AGENT_BACKEND + ":") else "%s:%s" % (AGENT_BACKEND, model)


def compute_overall(dims: Dict[str, float]) -> float:
    """Weighted overall, matching scorer.score_video exactly (2dp)."""
    return round(sum(dims[d] * _WEIGHTS[d] for d in _DIMENSIONS), 2)


def _as_score(value: Any, field: str) -> float:
    """A 0–10 number, or a hard error naming the field.

    Deliberately strict rather than clamping: a silently clamped 47 looks like a
    real 10 in the viewer, and the person who has to notice is a student.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number 0-10, got %r" % (field, value))
    if num != num or num < 0 or num > 10:      # num != num catches NaN
        raise ValueError("%s must be within 0-10, got %r" % (field, value))
    return num


def resolve_keyframe(rows: List[Any], spec: Dict[str, Any]) -> int:
    """Map one frame entry to a keyframe id.

    Accepts `keyframe_id`, `frame_index`, or `file` (full path or bare basename),
    in that order. The producer here is a language model reading files off disk,
    so a single rigid key would fail in exactly the situation this path exists to
    serve; matching on what it can actually see is worth the extra branch.
    """
    if spec.get("keyframe_id") is not None:
        want = int(spec["keyframe_id"])
        for r in rows:
            if r["id"] == want:
                return want
        raise ValueError("keyframe_id %d does not belong to this video" % want)

    if spec.get("frame_index") is not None:
        want = int(spec["frame_index"])
        for r in rows:
            if r["frame_index"] == want:
                return r["id"]
        raise ValueError("no keyframe with frame_index %d for this video" % want)

    ref = spec.get("file") or spec.get("file_path")
    if ref:
        ref = str(ref)
        tail = ref.replace("\\", "/").rsplit("/", 1)[-1]
        for r in rows:
            path = (r["file_path"] or "").replace("\\", "/")
            if path == ref or path.rsplit("/", 1)[-1] == tail:
                return r["id"]
        raise ValueError("no keyframe matching file %r for this video" % ref)

    raise ValueError("each frame needs one of: keyframe_id, frame_index, file")


def ingest_vision(
    conn: Any,
    video_id: str,
    payload: Dict[str, Any],
    model: str = "",
) -> Tuple[int, List[str]]:
    """Write agent-produced frame descriptions. Returns (written, warnings).

    `payload` is `{"model": ..., "frames": [{<locator>, "description", ...}]}`.
    Frames that fail to resolve are collected as warnings rather than aborting the
    batch — a partial visual layer beats none, and the caller reports what missed.
    """
    frames = payload.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("payload needs a non-empty 'frames' list")

    stamp = provenance(model or payload.get("model", ""))
    rows = db.get_keyframes(conn, video_id)
    if not rows:
        raise ValueError(
            "no keyframes stored for %s — run `analyze --skip-vision` first so the "
            "frames exist on disk" % video_id)

    written, warnings = 0, []
    for i, spec in enumerate(frames):
        if not isinstance(spec, dict):
            warnings.append("frame %d: expected an object, got %s" % (i, type(spec).__name__))
            continue
        try:
            kf_id = resolve_keyframe(rows, spec)
        except ValueError as exc:
            warnings.append("frame %d: %s" % (i, exc))
            continue

        description = str(spec.get("description") or "").strip()
        if not description:
            warnings.append("frame %d: empty description, skipped" % i)
            continue

        objects = spec.get("objects") or []
        if isinstance(objects, str):
            objects = [objects]
        import json as _json
        db.save_vision_description(
            conn,
            keyframe_id=kf_id,
            description=description,
            objects_json=_json.dumps(list(objects), ensure_ascii=False),
            text_in_frame=str(spec.get("text_in_frame") or ""),
            vlm_backend=AGENT_BACKEND,
            vlm_model=stamp,
        )
        written += 1

    return written, warnings


def ingest_score(
    conn: Any,
    video_id: str,
    payload: Dict[str, Any],
    model: str = "",
) -> Any:
    """Write an agent-produced craft score. Returns the stored VideoScore.

    Any `overall` in `payload` is ignored on purpose — see the module docstring.
    """
    from .scorer import VideoScore

    missing = [d for d in _DIMENSIONS if payload.get(d) is None]
    if missing:
        raise ValueError("missing required dimension(s): %s" % ", ".join(missing))

    dims = {d: _as_score(payload[d], d) for d in _DIMENSIONS}
    score = VideoScore(
        hook_strength=dims["hook_strength"],
        visual_storytelling=dims["visual_storytelling"],
        pacing=dims["pacing"],
        structure=dims["structure"],
        overall=compute_overall(dims),
        reasoning=str(payload.get("reasoning") or "").strip(),
        model_used=provenance(model or payload.get("model", "")),
    )
    db.save_score(conn, video_id, score)
    return score
