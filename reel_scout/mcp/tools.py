from __future__ import annotations

import contextlib
import json
import os
import sys
from typing import Any, Dict, List

from .. import config, db, ingest
from ..export.json_export import export_csv, export_json

# `ingest` is imported at module level, against the deferred-import convention the
# handlers below follow, because `_enum()` reads its whitelists while `list_tools()`
# is being built. It is cheap -- ingest imports only db, which is already here.
# Making it lazy would break the schema at list time.


def _enum(section, field) -> Dict[str, Any]:
    """A string property whose allowed values come from ingest's own validator.

    Retyping the seven whitelists here would create a second copy that drifts
    from the one that actually rejects payloads, and the schema is the only
    place the model learns them before a failed round-trip.
    """
    return {"type": "string", "enum": list(ingest._ENUMS[(section, field)])}


#: Frames returned by `keyframes` when the caller does not say.
_KEYFRAMES_DEFAULT_MAX = 8

#: Total base64 budget for one `keyframes` reply. Native frames are unbounded and
#: base64 inflates them by 4/3, so a long clip could otherwise return tens of MB
#: into a context window. Truncation is reported, never silent.
_KEYFRAMES_MAX_BYTES = 4 * 1024 * 1024


def list_tools() -> List[Dict[str, Any]]:
    return [
        {
            "name": "crawl",
            "description": "Download short-form videos from YouTube, Instagram, or TikTok",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "urls": {"type": "array", "items": {"type": "string"}},
                    "cookies": {"type": "string"},
                },
                "required": ["urls"],
            },
        },
        {
            "name": "analyze",
            "description": "Full pipeline: download + transcribe + vision analysis + structured merge",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "urls": {"type": "array", "items": {"type": "string"}},
                    "skip_vision": {"type": "boolean", "default": False},
                    "skip_transcribe": {"type": "boolean", "default": False},
                    "wait": {"type": "boolean", "default": True},
                },
                "required": ["urls"],
            },
        },
        {
            "name": "list_videos",
            "description": "List analyzed videos with optional filters",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "platform": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
        },
        {
            "name": "show_video",
            "description": "Show full analysis for a specific video",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "video_id": {"type": "string"},
                },
                "required": ["video_id"],
            },
        },
        {
            "name": "keyframes",
            "description": (
                "Return the extracted keyframe images themselves so you can look at "
                "them. `show_video` only gives you file paths, which are useless "
                "without filesystem access — this is how you actually see the frames. "
                "Call it before `ingest_vision`: describe what you saw, never what you "
                "assumed."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "Video id or a unique prefix.",
                    },
                    "frame_indexes": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "Specific frame_index values. Omit for an even spread "
                            "across the clip."
                        ),
                    },
                    "max_frames": {
                        "type": "integer",
                        "default": _KEYFRAMES_DEFAULT_MAX,
                        "description": "Cap on how many frames come back (default 8).",
                    },
                },
                "required": ["video_id"],
            },
        },
        {
            "name": "ingest_vision",
            "description": (
                "Write your own keyframe descriptions into the DB — this is how the "
                "visual layer gets produced when there is no local VLM (L1). Call "
                "`keyframes` first and describe what you actually saw. Address each "
                "frame by keyframe_id, frame_index, or file."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "Video id or a unique prefix."},
                    "model": {
                        "type": "string",
                        "description": (
                            "Your model name. Stamped as agent:<model> so the row's "
                            "origin stays traceable — craft scores vary a lot between "
                            "models."
                        ),
                    },
                    "frames": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "keyframe_id": {"type": "integer"},
                                "frame_index": {"type": "integer"},
                                "file": {"type": "string",
                                         "description": "Full path or bare basename."},
                                "description": {"type": "string"},
                                "objects": {"type": "array", "items": {"type": "string"}},
                                "text_in_frame": {"type": "string"},
                            },
                            "required": ["description"],
                        },
                    },
                },
                "required": ["video_id", "model", "frames"],
            },
        },
        {
            "name": "ingest_analysis",
            "description": (
                "Write the structured analysis (4-beat timeline, hook, style, "
                "content type) into the DB. The low-cardinality fields are validated "
                "enums that `stats` and `patterns` group on: omit any you cannot "
                "determine — never invent a value, since a coined one adds a "
                "one-member category to every aggregate."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "video_id": {"type": "string"},
                    "model": {"type": "string"},
                    "summary": {"type": "string"},
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "timeline": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "timestamp": {"type": "string", "description": "e.g. '0-3s'"},
                                "event": {"type": "string"},
                            },
                        },
                    },
                    "hook": {
                        "type": "object",
                        "properties": {
                            "opening_type": _enum("hook", "opening_type"),
                            "opening_text": {"type": "string"},
                            "cta_type": _enum("hook", "cta_type"),
                            "cta_text": {"type": "string"},
                        },
                    },
                    "style": {
                        "type": "object",
                        "properties": {
                            "format": _enum("style", "format"),
                            "pacing": _enum("style", "pacing"),
                            "has_captions": {"type": "boolean"},
                            "has_background_music": {"type": "boolean"},
                            "text_overlay_count": {"type": "integer"},
                        },
                    },
                    "engagement_signals": {
                        "type": "object",
                        "properties": {
                            "face_visible": {"type": "boolean"},
                            "face_count": {"type": "integer"},
                            "emotion": _enum("engagement_signals", "emotion"),
                            "spoken_language": {"type": "string"},
                            "subtitle_language": {"type": "string"},
                        },
                    },
                    "content_type": _enum(None, "content_type"),
                    "content_structure": _enum(None, "content_structure"),
                },
                # Only summary: every enum stays optional on purpose. Marking them
                # required would push the model to invent a value rather than omit
                # the field, which is exactly what the whitelist exists to prevent.
                "required": ["video_id", "model", "summary"],
            },
        },
        {
            "name": "ingest_score",
            "description": (
                "Write your rubric score (L1). Do NOT send `overall` — it is "
                "recomputed as hook*0.3 + visual*0.25 + pacing*0.2 + structure*0.25 "
                "and anything you send is discarded. Values outside 0-10 are "
                "rejected, not clamped. Read the prompt pack first so the four "
                "dimensions mean what they mean everywhere else."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "video_id": {"type": "string"},
                    "model": {"type": "string"},
                    "hook_strength": {"type": "number", "minimum": 0, "maximum": 10},
                    "visual_storytelling": {"type": "number", "minimum": 0, "maximum": 10},
                    "pacing": {"type": "number", "minimum": 0, "maximum": 10},
                    "structure": {"type": "number", "minimum": 0, "maximum": 10},
                    "reasoning": {"type": "string"},
                },
                "required": [
                    "video_id", "model",
                    "hook_strength", "visual_storytelling", "pacing", "structure",
                ],
            },
        },
        {
            "name": "export",
            "description": "Export analyses to JSON or CSV",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "format": {"type": "string", "enum": ["json", "csv"], "default": "json"},
                    "output": {"type": "string", "default": "./export"},
                },
            },
        },
        {
            "name": "patterns",
            "description": "Per-channel pattern analysis (length, hook/CTA/structure mix, high-vs-low, cadence). Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {"channel": {"type": "string"}},
                "required": ["channel"],
            },
        },
        {
            "name": "inspire",
            "description": "Generate a fresh content variant (titles/hook/structure) from a high-scoring video",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "based_on": {"type": "string"},
                    "angle": {"type": "string"},
                },
                "required": ["based_on"],
            },
        },
        {
            "name": "research",
            "description": "Competitor research: browse the given channels, aggregate niche patterns, return the report data. analyze=true also analyzes each video first (slow); analyze=false skips per-video analysis but still browses the channels (needs network), aggregating from the existing DB.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "niche": {"type": "string"},
                    "channels": {"type": "array", "items": {"type": "string"}},
                    "depth": {"type": "integer", "default": 20},
                    "analyze": {"type": "boolean", "default": False},
                },
                "required": ["niche", "channels"],
            },
        },
    ]


def call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    handler = _HANDLERS.get(name)
    if handler is None:
        return _error_result("Unknown tool: %s" % name)
    try:
        return handler(arguments)
    except Exception as exc:
        return _error_result("Error: %s" % exc)


def _text_result(payload: Any) -> Dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ]
    }


def _image_result(payload: Any, images: List[Dict[str, str]]) -> Dict[str, Any]:
    """A JSON block followed by one image block per frame.

    The text block first, deliberately: it carries the keyframe_id / frame_index
    locators, and a model that reads top-to-bottom should have them in hand
    before it starts describing what it sees.
    """
    content = [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]
    for image in images:
        content.append(
            {
                "type": "image",
                "data": image["data"],
                "mimeType": image.get("mime_type", "image/jpeg"),
            }
        )
    return {"content": content}


def _error_result(message: str) -> Dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def _tool_crawl(args: Dict[str, Any]) -> Dict[str, Any]:
    from ..crawl import get_crawler

    urls = args.get("urls") or []
    if not urls:
        return _error_result("urls is required")

    cookies = args.get("cookies")
    if cookies:
        os.environ["IG_COOKIES_FILE"] = cookies

    config.ensure_dirs()
    conn = db.init_db()
    results = []
    try:
        for url in urls:
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    crawler = get_crawler(url)
                    meta = crawler.download(url, config.VIDEOS_DIR)
                video_id = db.upsert_video(
                    conn,
                    platform=meta.platform,
                    platform_id=meta.platform_id,
                    url=url,
                    title=meta.title,
                    uploader=meta.uploader,
                    duration_sec=meta.duration_sec,
                    upload_date=meta.upload_date,
                    file_path=meta.file_path,
                    file_size_bytes=meta.file_size_bytes,
                )
                results.append(
                    {
                        "url": url,
                        "video_id": video_id,
                        "platform": meta.platform,
                        "title": meta.title,
                        "duration_sec": meta.duration_sec,
                        "status": "downloaded",
                    }
                )
            except Exception as exc:
                results.append({"url": url, "status": "error", "error": str(exc)})
    finally:
        conn.close()
    return _text_result(results)


def _tool_analyze(args: Dict[str, Any]) -> Dict[str, Any]:
    from ..analyze.pipeline import PipelineOptions, _process_single

    urls = args.get("urls") or []
    if not urls:
        return _error_result("urls is required")

    skip_vision = bool(args.get("skip_vision", False))
    skip_transcribe = bool(args.get("skip_transcribe", False))
    wait = bool(args.get("wait", True))

    config.ensure_dirs()
    conn = db.init_db()
    batch_id = db.create_batch(conn, urls, source="mcp")
    options = PipelineOptions(
        skip_vision=skip_vision,
        skip_transcribe=skip_transcribe,
    )
    if not wait:
        conn.close()
        return _text_result(
            {
                "batch_id": batch_id,
                "status": "queued",
                "warning": "wait=false stores the batch only; run analyze again with wait=true to process it.",
            }
        )

    processed = []
    try:
        for url in urls:
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    video_id = _process_single(conn, url, options)
                db.update_batch_item(conn, batch_id, url, "done", video_id=video_id)
                processed.append({"url": url, "video_id": video_id, "status": "done"})
            except Exception as exc:
                db.update_batch_item(conn, batch_id, url, "error", error=str(exc))
                processed.append({"url": url, "status": "error", "error": str(exc)})
        db.mark_batch_completed(conn, batch_id)
    finally:
        conn.close()
    return _text_result({"batch_id": batch_id, "items": processed})


def _tool_list_videos(args: Dict[str, Any]) -> Dict[str, Any]:
    config.ensure_dirs()
    conn = db.init_db()
    try:
        videos = db.list_videos(
            conn,
            status=args.get("status"),
            platform=args.get("platform"),
            limit=int(args.get("limit", 50)),
        )
        result = []
        for video in videos:
            result.append(
                {
                    "video_id": video["id"],
                    "platform": video["platform"],
                    "title": video["title"],
                    "status": video["status"],
                    "duration_sec": video["duration_sec"],
                    "url": video["url"],
                }
            )
        return _text_result(result)
    finally:
        conn.close()


def _tool_show_video(args: Dict[str, Any]) -> Dict[str, Any]:
    video_id = args.get("video_id", "")
    if not video_id:
        return _error_result("video_id is required")

    config.ensure_dirs()
    conn = db.init_db()
    try:
        video = db.get_video(conn, video_id)
        if video is None:
            return _error_result("Video not found: %s" % video_id)

        transcript = db.get_transcript(conn, video_id)
        analysis = db.get_analysis(conn, video_id)
        score = db.get_score(conn, video_id)
        keyframes = db.get_keyframes_with_descriptions(conn, video_id)
        payload = {
            "video": {
                "video_id": video["id"],
                "platform": video["platform"],
                "platform_id": video["platform_id"],
                "url": video["url"],
                "title": video["title"],
                "uploader": video["uploader"],
                "duration_sec": video["duration_sec"],
                "status": video["status"],
                "file_path": video["file_path"],
            },
            "transcript": None,
            "analysis": None,
            "score": None,
            "keyframes": [],
        }
        if score is not None:
            # model_used is the point: agent-scored and locally-scored rows are
            # averaged together by `stats`, so a score without its origin is
            # unattributable. Over MCP this is the only place it surfaces.
            payload["score"] = {
                "overall": score["overall"],
                "hook_strength": score["hook_strength"],
                "visual_storytelling": score["visual_storytelling"],
                "pacing": score["pacing"],
                "structure": score["structure"],
                "reasoning": score["reasoning"],
                "model_used": score["model_used"],
            }
        if transcript is not None:
            payload["transcript"] = {
                "language": transcript["language"],
                "text_full": transcript["text_full"],
                "segments": json.loads(transcript["segments_json"] or "[]"),
                "whisper_model": transcript["whisper_model"],
                "duration_sec": transcript["duration_sec"],
            }
        if analysis is not None:
            payload["analysis"] = {
                "summary": analysis["summary"],
                "topics": json.loads(analysis["topics_json"] or "[]"),
                "hooks": json.loads(analysis["hooks_json"] or "[]"),
                "style": json.loads(analysis["style_json"] or "{}"),
                "engagement_signals": json.loads(analysis["engagement_signals_json"] or "[]"),
                "full": json.loads(analysis["full_json"] or "{}"),
            }
        for keyframe in keyframes:
            payload["keyframes"].append(
                {
                    "id": keyframe["id"],
                    "frame_index": keyframe["frame_index"],
                    "timestamp_sec": keyframe["timestamp_sec"],
                    "file_path": keyframe["file_path"],
                    "strategy": keyframe["strategy"],
                    # Without these the agent can write a visual layer and then
                    # have no way to read it back: over MCP `show_video` is the
                    # only view it has.
                    "description": keyframe["description"],
                    "text_in_frame": keyframe["text_in_frame"],
                    "objects": json.loads(keyframe["objects_json"] or "[]"),
                }
            )
        return _text_result(payload)
    finally:
        conn.close()


def _tool_patterns(args: Dict[str, Any]) -> Dict[str, Any]:
    channel = args.get("channel", "")
    if not channel:
        return _error_result("channel is required")
    from .. import patterns as patterns_mod

    config.ensure_dirs()
    conn = db.init_db()
    try:
        return _text_result(patterns_mod.compute_patterns(conn, channel))
    finally:
        conn.close()


def _tool_inspire(args: Dict[str, Any]) -> Dict[str, Any]:
    based_on = args.get("based_on", "")
    if not based_on:
        return _error_result("based_on is required")
    from .. import inspire as inspire_mod

    config.ensure_dirs()
    conn = db.init_db()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            data = inspire_mod.generate_inspiration(conn, based_on, angle=args.get("angle", ""))
        return _text_result(data)
    finally:
        conn.close()


def _tool_research(args: Dict[str, Any]) -> Dict[str, Any]:
    niche = args.get("niche", "")
    channels = args.get("channels") or []
    if not niche or not channels:
        return _error_result("niche and channels are required")
    if not isinstance(channels, list):
        return _error_result("channels must be an array of URLs")
    from .. import research as research_mod

    config.ensure_dirs()
    conn = db.init_db()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            agg = research_mod.run_research(
                conn, niche, channels,
                depth=int(args.get("depth", 20)),
                do_analyze=bool(args.get("analyze", False)),
            )
        return _text_result(agg)
    finally:
        conn.close()


def _pick_frames(rows: List[Any], wanted: Any, max_frames: int) -> List[Any]:
    """Which keyframe rows to return: the ones asked for, or an even spread.

    An even spread rather than the first N — the first N of a 40-frame clip is
    the first few seconds, which tells you nothing about how the clip resolves.
    """
    if wanted:
        want = {int(w) for w in wanted}
        return [r for r in rows if r["frame_index"] in want][:max_frames]
    if len(rows) <= max_frames:
        return list(rows)
    step = (len(rows) - 1) / float(max_frames - 1) if max_frames > 1 else 0
    return [rows[int(round(i * step))] for i in range(max_frames)]


def _tool_keyframes(args: Dict[str, Any]) -> Dict[str, Any]:
    import base64

    from ..compare import resolve_ref
    from ..viewer import _keyframe_path

    video_ref = args.get("video_id") or ""
    if not video_ref:
        return _error_result("video_id is required")
    max_frames = int(args.get("max_frames", _KEYFRAMES_DEFAULT_MAX))
    if max_frames < 1:
        return _error_result("max_frames must be at least 1")

    config.ensure_dirs()
    conn = db.init_db()
    try:
        video_id, matches = resolve_ref(conn, video_ref)
        if video_id is None:
            if len(matches) > 1:
                return _error_result(
                    "Ambiguous video id %r — matches: %s" % (video_ref, ", ".join(matches))
                )
            return _error_result("Video not found: %s" % video_ref)

        rows = db.get_keyframes(conn, video_id)
        if not rows:
            return _error_result(
                "No keyframes stored for %s — run `analyze --skip-vision` first so the "
                "frames exist on disk." % video_id
            )

        selected = _pick_frames(rows, args.get("frame_indexes"), max_frames)
        described = set(db.get_described_keyframe_ids(conn, video_id))

        frames, images, warnings = [], [], []
        budget = _KEYFRAMES_MAX_BYTES
        truncated = False
        for row in selected:
            path = _keyframe_path(conn, str(row["id"]))
            if not path:
                warnings.append(
                    "keyframe %s: %s is not on disk" % (row["id"], row["file_path"])
                )
                continue
            with open(path, "rb") as handle:
                raw = handle.read()
            encoded = base64.b64encode(raw).decode("ascii")
            if len(encoded) > budget:
                truncated = True
                break
            budget -= len(encoded)
            frames.append(
                {
                    "keyframe_id": row["id"],
                    "frame_index": row["frame_index"],
                    "timestamp_sec": row["timestamp_sec"],
                    "file_path": row["file_path"],
                    "already_described": row["id"] in described,
                }
            )
            images.append({"data": encoded, "mime_type": "image/jpeg"})

        payload = {
            "video_id": video_id,
            "keyframes_total": len(rows),
            "returned": len(frames),
            "frames": frames,
            "next_step": (
                "Look at the images below, then call ingest_vision with one entry per "
                "frame, addressed by keyframe_id."
            ),
        }
        if warnings:
            payload["warnings"] = warnings
        if truncated:
            payload["truncated"] = (
                "Stopped at %d frame(s) to stay inside the reply size budget. Ask for "
                "specific frame_indexes to see the rest." % len(frames)
            )
        return _image_result(payload, images)
    finally:
        conn.close()


def _resolve_video(conn: Any, ref: str):
    """(video_id, error_result). Exactly one of the two is None.

    ingest.py has no existence check of its own, and without one a bad id reaches
    save_analysis / save_score as a foreign-key violation -- sqlite3.IntegrityError,
    not ValueError, so it would sail past the handler's error mapping and surface
    as "FOREIGN KEY constraint failed".
    """
    from ..compare import resolve_ref

    video_id, matches = resolve_ref(conn, ref)
    if video_id is not None:
        return video_id, None
    if len(matches) > 1:
        return None, _error_result(
            "Ambiguous video id %r — matches: %s" % (ref, ", ".join(matches))
        )
    return None, _error_result("Video not found: %s" % ref)


def _ingest_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    """Everything except the two routing keys.

    `video_id` in particular has to go: ingest_analysis stores whatever it is
    handed inside full_json, and it only pops `model` itself.
    """
    return {k: v for k, v in args.items() if k not in ("video_id", "model")}


def _tool_ingest_vision(args: Dict[str, Any]) -> Dict[str, Any]:
    video_ref = args.get("video_id") or ""
    if not video_ref:
        return _error_result("video_id is required")
    frames = args.get("frames")
    if not isinstance(frames, list) or not frames:
        return _error_result("frames must be a non-empty list")

    config.ensure_dirs()
    conn = db.init_db()
    try:
        video_id, err = _resolve_video(conn, video_ref)
        if err is not None:
            return err
        try:
            written, warnings = ingest.ingest_vision(
                conn, video_id, _ingest_payload(args), model=args.get("model", "")
            )
        except ValueError as exc:
            return _error_result(str(exc))

        total = len(db.get_keyframes(conn, video_id))
        described = len(db.get_described_keyframe_ids(conn, video_id))
        payload = {
            "video_id": video_id,
            "written": written,
            "submitted": len(frames),
            "source": ingest.provenance(args.get("model", "")),
            "keyframes_total": total,
            "keyframes_described": described,
        }
        # Partial success is by design, so a bare count would let the caller
        # believe every frame landed.
        if warnings:
            payload["warnings"] = warnings
        if described < total:
            payload["still_undescribed"] = total - described
        return _text_result(payload)
    finally:
        conn.close()


def _tool_ingest_analysis(args: Dict[str, Any]) -> Dict[str, Any]:
    video_ref = args.get("video_id") or ""
    if not video_ref:
        return _error_result("video_id is required")

    config.ensure_dirs()
    conn = db.init_db()
    try:
        video_id, err = _resolve_video(conn, video_ref)
        if err is not None:
            return err
        payload_in = _ingest_payload(args)
        try:
            stored = ingest.ingest_analysis(
                conn, video_id, payload_in, model=args.get("model", "")
            )
        except ValueError as exc:
            return _error_result(str(exc))

        hook = stored.get("hook") or {}
        style = stored.get("style") or {}
        signals = stored.get("engagement_signals") or {}
        landed = {
            "content_type": stored.get("content_type"),
            "content_structure": stored.get("content_structure"),
            "opening_type": hook.get("opening_type"),
            "cta_type": hook.get("cta_type"),
            "style_format": style.get("format"),
            "style_pacing": style.get("pacing"),
            "emotion": signals.get("emotion"),
        }
        payload = {
            "video_id": video_id,
            "source": stored.get("_source"),
            "summary": (stored.get("summary") or "")[:200],
            "stored": landed,
        }
        # Omission is the documented right answer for an undeterminable enum, so
        # make it visible rather than silent.
        omitted = sorted(k for k, v in landed.items() if v in (None, ""))
        if omitted:
            payload["omitted"] = omitted
        return _text_result(payload)
    finally:
        conn.close()


def _tool_ingest_score(args: Dict[str, Any]) -> Dict[str, Any]:
    import dataclasses

    video_ref = args.get("video_id") or ""
    if not video_ref:
        return _error_result("video_id is required")

    config.ensure_dirs()
    conn = db.init_db()
    try:
        video_id, err = _resolve_video(conn, video_ref)
        if err is not None:
            return err
        try:
            score = ingest.ingest_score(
                conn, video_id, _ingest_payload(args), model=args.get("model", "")
            )
        except ValueError as exc:
            return _error_result(str(exc))

        payload = dataclasses.asdict(score)
        payload["video_id"] = video_id
        payload["note"] = (
            "overall was recomputed from the four dimensions; any value you sent "
            "was discarded. This is an L1 (agent-scored) row — it is not directly "
            "comparable with locally-scored videos in the same corpus."
        )
        return _text_result(payload)
    finally:
        conn.close()


def _tool_export(args: Dict[str, Any]) -> Dict[str, Any]:
    fmt = args.get("format", "json")
    output = args.get("output", "./export")

    config.ensure_dirs()
    conn = db.init_db()
    try:
        if fmt == "json":
            count = export_json(conn, output)
            return _text_result({"format": fmt, "count": count, "output": output})
        if fmt == "csv":
            csv_output = output
            _, ext = os.path.splitext(output)
            if not ext:
                os.makedirs(output, exist_ok=True)
                csv_output = os.path.join(output, "export.csv")
            count = export_csv(conn, csv_output)
            return _text_result({"format": fmt, "count": count, "output": csv_output})
        return _error_result("Unsupported export format: %s" % fmt)
    finally:
        conn.close()


#: Name -> handler. Defined here, after every handler exists, and kept module-level
#: so a test can assert it against `list_tools()`: the two are the only things that
#: decide whether a tool is callable and whether it is visible, and nothing about
#: the code makes them agree. A tool missing here answers "Unknown tool"; a tool
#: missing there is invisible but callable.
_HANDLERS = {
    "crawl": _tool_crawl,
    "analyze": _tool_analyze,
    "list_videos": _tool_list_videos,
    "show_video": _tool_show_video,
    "keyframes": _tool_keyframes,
    "ingest_vision": _tool_ingest_vision,
    "ingest_analysis": _tool_ingest_analysis,
    "ingest_score": _tool_ingest_score,
    "export": _tool_export,
    "patterns": _tool_patterns,
    "inspire": _tool_inspire,
    "research": _tool_research,
}
