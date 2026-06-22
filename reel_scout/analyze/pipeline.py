from __future__ import annotations

import json
import os
import signal
import sys
from dataclasses import dataclass
from typing import List, Optional

from .. import config, db
from ..crawl import get_crawler
from ..transcribe import get_transcriber
from ..transcribe.base import TranscriptResult
from ..vision import get_vlm
from ..vision.keyframe import extract_keyframes
from .merger import merge_analysis


@dataclass
class PipelineOptions:
    skip_vision: bool = False
    skip_transcribe: bool = False
    skip_audio: bool = True
    skip_diarize: bool = True
    score: bool = False
    resume: bool = False
    whisper_backend: Optional[str] = None
    vlm_backend: Optional[str] = None
    vlm_model: Optional[str] = None
    keyframe_strategy: Optional[str] = None
    keyframe_max: Optional[int] = None


def run(urls: List[str], options: Optional[PipelineOptions] = None) -> None:
    if options is None:
        options = PipelineOptions()

    config.ensure_dirs()
    conn = db.init_db()

    # Resume or create batch
    if options.resume:
        batch = db.get_latest_interrupted_batch(conn)
        if batch is None:
            print("No interrupted batch found.")
            return
        batch_id = batch["id"]
        print(f"Resuming batch {batch_id}")
    else:
        batch_id = db.create_batch(conn, urls)
        print(f"Created batch {batch_id} with {len(urls)} URLs")

    # Handle SIGINT for graceful interruption
    interrupted = [False]

    def _on_interrupt(sig, frame):
        if interrupted[0]:
            sys.exit(1)
        interrupted[0] = True
        print("\nInterrupted. Saving progress...")
        db.mark_batch_interrupted(conn, batch_id)

    original_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _on_interrupt)

    try:
        pending = db.get_pending_batch_items(conn, batch_id)
        total = len(pending)
        print(f"Processing {total} pending items...")

        for i, item in enumerate(pending):
            if interrupted[0]:
                break

            url = item["url"]
            print(f"\n[{i+1}/{total}] {url}")

            try:
                video_id = _process_single(conn, url, options)
                db.update_batch_item(conn, batch_id, url, "done", video_id=video_id)
                print(f"  Done: {video_id}")
            except Exception as e:
                db.update_batch_item(conn, batch_id, url, "error", error=str(e))
                print(f"  Error: {e}")

        if not interrupted[0]:
            db.mark_batch_completed(conn, batch_id)
            print(f"\nBatch {batch_id} completed.")
    finally:
        signal.signal(signal.SIGINT, original_handler)
        conn.close()


def _process_single(
    conn: db.sqlite3.Connection,
    url: str,
    options: PipelineOptions,
) -> str:
    # Step 1: Download (skip if already exists)
    existing = db.get_video_by_url(conn, url)
    if existing and existing["file_path"] and os.path.exists(existing["file_path"]):
        video_id = existing["id"]
        print("  Skipping download (already exists)")
    else:
        print("  Downloading...")
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

    video = db.get_video(conn, video_id)
    file_path = video["file_path"]

    # Step 2: Transcribe
    if not options.skip_transcribe:
        existing_transcript = db.get_transcript(conn, video_id)
        if existing_transcript:
            print("  Skipping transcribe (already done)")
        else:
            print("  Transcribing...")
            transcriber = get_transcriber(options.whisper_backend)
            result = transcriber.transcribe(file_path)
            segments_data = [
                {"start": s.start, "end": s.end, "text": s.text,
                 "confidence": s.confidence}
                for s in result.segments
            ]
            db.save_transcript(
                conn, video_id,
                language=result.language,
                text_full=result.text_full,
                segments_json=json.dumps(segments_data, ensure_ascii=False),
                whisper_model=result.model,
                duration_sec=result.duration_sec,
            )

    # Step 2.5: Audio analysis
    if not options.skip_audio:
        try:
            from ..audio import get_audio_analyzer
            from ..audio.extract import extract_wav
            existing_audio = db.get_audio_events(conn, video_id)
            if existing_audio:
                print("  Skipping audio analysis (already done)")
            else:
                print("  Analyzing audio events...")
                import tempfile
                wav_path = tempfile.mktemp(suffix=".wav")
                try:
                    extract_wav(file_path, wav_path)
                    analyzer = get_audio_analyzer()
                    timeline = analyzer.analyze(wav_path)
                    events_data = [
                        {"event_type": e.event_type, "label": e.label,
                         "start_sec": e.start_sec, "end_sec": e.end_sec,
                         "confidence": e.confidence}
                        for e in timeline.events
                    ]
                    db.save_audio_events(conn, video_id, events_data)
                finally:
                    import os as _os
                    if _os.path.exists(wav_path):
                        _os.unlink(wav_path)
        except (ImportError, FileNotFoundError) as e:
            print("  Skipping audio analysis: %s" % e, file=sys.stderr)

    # Step 2.7: Speaker diarization
    if not options.skip_diarize and config.DIARIZE_ENABLED:
        try:
            from ..diarize import get_diarizer
            from ..diarize.align import align_speakers_to_transcript
            from ..audio.extract import extract_wav
            transcript = db.get_transcript(conn, video_id)
            if transcript and transcript["segments_json"]:
                segments_json = transcript["segments_json"]
                # Check if already has speaker labels
                import json as _json
                segs = _json.loads(segments_json)
                if segs and "speaker" not in segs[0]:
                    print("  Running speaker diarization...")
                    import tempfile
                    wav_path = tempfile.mktemp(suffix=".wav")
                    try:
                        extract_wav(file_path, wav_path)
                        diarizer = get_diarizer()
                        result = diarizer.diarize(wav_path)
                        updated_json = align_speakers_to_transcript(
                            result.segments, segments_json)
                        conn.execute(
                            "UPDATE transcripts SET segments_json=? WHERE video_id=?",
                            (updated_json, video_id))
                        conn.commit()
                        print("  Diarization: %d speakers detected" % result.num_speakers)
                    finally:
                        import os as _os2
                        if _os2.path.exists(wav_path):
                            _os2.unlink(wav_path)
                else:
                    print("  Skipping diarization (already done)")
        except (ImportError, ValueError) as e:
            print("  Skipping diarization: %s" % e, file=sys.stderr)

    # Step 3: Vision analysis
    # Decoupled from keyframe extraction: vision descriptions are (re)generated for
    # any keyframe that lacks one, whether or not keyframes were extracted this run.
    # This lets a failed/partial VLM pass be backfilled by simply re-running analyze
    # — previously the describe+save loop lived inside the "keyframes didn't exist"
    # branch, so once keyframes were saved a failed vision pass could never recover.
    if not options.skip_vision:
        existing_kf = db.get_keyframes(conn, video_id)
        if existing_kf:
            print("  Keyframes already extracted")
            frames = [(kf["id"], kf["file_path"]) for kf in existing_kf]
        else:
            print("  Extracting keyframes...")
            kf_dir = os.path.join(config.KEYFRAMES_DIR, video_id)
            kf_infos = extract_keyframes(
                file_path, kf_dir, video_id,
                strategy=options.keyframe_strategy or "",
                max_frames=options.keyframe_max or 0,
            )
            kf_data = [
                {"frame_index": kf.frame_index, "timestamp_sec": kf.timestamp_sec,
                 "file_path": kf.file_path, "strategy": kf.strategy}
                for kf in kf_infos
            ]
            kf_ids = db.save_keyframes(conn, video_id, kf_data)
            frames = list(zip(kf_ids, [kf.file_path for kf in kf_infos]))

        backend = options.vlm_backend or config.VLM_BACKEND
        primary_model = options.vlm_model or config.VLM_MODEL

        # only describe keyframes that don't already have a description (backfill)
        described = db.get_described_keyframe_ids(conn, video_id)
        todo = [(kf_id, path) for kf_id, path in frames if kf_id not in described]

        if not todo:
            print("  Vision descriptions already present")
        else:
            def _persist(kf_id, desc, model):
                db.save_vision_description(
                    conn, kf_id,
                    description=desc.description,
                    objects_json=json.dumps(desc.objects, ensure_ascii=False),
                    text_in_frame=desc.text_in_frame,
                    vlm_backend=backend,
                    vlm_model=model,
                )

            print(f"  Describing {len(todo)} keyframe(s) with VLM ({primary_model})...")
            vlm = get_vlm(backend)
            failed = []  # (kf_id, path) — empty/errored on the primary model
            for kf_id, path in todo:
                # per-frame resilience: one bad frame must not abort the batch
                try:
                    desc = vlm.describe_frame(path)
                except Exception as e:  # noqa: BLE001
                    print(f"    frame {kf_id} failed: {e}", file=sys.stderr)
                    desc = None
                if desc and desc.description:
                    _persist(kf_id, desc, primary_model)
                else:
                    failed.append((kf_id, path))

            # graceful fallback (arkiv #83): retry failed frames with the fallback
            # model, but only if it's a different model that's actually installed —
            # otherwise leave frames empty for a later retry instead of 404ing.
            if failed:
                fb = config.VLM_FALLBACK_MODEL
                from ..vision.ollama import model_available, OllamaVLM
                use_fb = (
                    backend == "ollama" and fb and fb != primary_model
                    and model_available(config.OLLAMA_BASE_URL, fb)
                )
                if use_fb:
                    print(f"  {len(failed)} frame(s) failed; retrying with fallback {fb}...")
                    fb_vlm = OllamaVLM(base_url=config.OLLAMA_BASE_URL, model=fb)
                    for kf_id, path in failed:
                        try:
                            desc = fb_vlm.describe_frame(path)
                        except Exception as e:  # noqa: BLE001
                            print(f"    fallback frame {kf_id} failed: {e}", file=sys.stderr)
                            desc = None
                        if desc and desc.description:
                            _persist(kf_id, desc, fb)
                else:
                    print(
                        f"  {len(failed)} frame(s) failed; fallback "
                        f"'{fb or '(none)'}' unavailable — left empty for a later vision retry",
                        file=sys.stderr,
                    )

    # Step 4: Merge analysis
    existing_analysis = db.get_analysis(conn, video_id)
    if existing_analysis:
        print("  Skipping analysis (already done)")
    else:
        print("  Merging analysis...")
        merge_analysis(conn, video_id)

    # Step 5: Scoring (optional)
    if getattr(options, 'score', False):
        existing_score = db.get_score(conn, video_id)
        if existing_score:
            print("  Skipping scoring (already done)")
        else:
            print("  Scoring...")
            from ..scorer import score_video
            score = score_video(conn, video_id)
            print("  Score: %.1f (hook=%.1f visual=%.1f pacing=%.1f structure=%.1f)" % (
                score.overall, score.hook_strength, score.visual_storytelling,
                score.pacing, score.structure))

    return video_id
