from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import List

from . import __version__, config


def main(argv: List[str] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="reel-scout",
        description="Short-form video analysis tool",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    # --- browse ---
    p_browse = sub.add_parser("browse", help="List videos from a profile/channel page")
    p_browse.add_argument("url", help="Profile/channel URL (e.g. instagram.com/user/reels/)")
    p_browse.add_argument("--limit", "-n", type=int, default=30, help="Max videos to list (default: 30)")
    p_browse.add_argument("--cookies", help="Path to cookies file (for IG)")
    p_browse.add_argument("--json", dest="output_json", action="store_true", help="Output as JSON")
    p_browse.add_argument("--urls-only", action="store_true", help="Output only URLs (pipe to crawl --file)")

    # --- crawl ---
    p_crawl = sub.add_parser("crawl", help="Download videos")
    p_crawl.add_argument("urls", nargs="*", help="Video URLs")
    p_crawl.add_argument("--file", "-f", help="File with URLs (one per line; '-' for stdin)")
    p_crawl.add_argument("--channel", metavar="URL",
                         help="Channel/profile page: list its videos and download them")
    p_crawl.add_argument("--playlist", metavar="URL",
                         help="Playlist page: list its videos and download them")
    p_crawl.add_argument("--limit", "-n", type=int, default=30,
                         help="Max videos to take from --channel/--playlist (default: 30)")
    p_crawl.add_argument("--cookies", help="Path to cookies file (for IG)")

    # --- analyze ---
    p_analyze = sub.add_parser("analyze", help="Full pipeline: crawl + transcribe + vision + merge")
    p_analyze.add_argument("urls", nargs="*", help="Video URLs or local file paths")
    p_analyze.add_argument("--file", "-f", help="File with URLs (one per line)")
    p_analyze.add_argument("--resume", action="store_true", help="Resume interrupted batch")
    p_analyze.add_argument("--skip-vision", action="store_true", help="Skip VLM analysis")
    p_analyze.add_argument("--skip-transcribe", action="store_true", help="Skip transcription")
    p_analyze.add_argument("--whisper-backend", help="Whisper backend (faster-whisper, whisper-cpp)")
    p_analyze.add_argument("--vlm-backend", help="VLM backend (omlx, ollama)")
    p_analyze.add_argument("--vlm-model", help="VLM model name")
    p_analyze.add_argument("--keyframe-strategy", help="Keyframe strategy (scene, interval, hybrid)")
    p_analyze.add_argument("--keyframe-max", type=int, help="Max keyframes per video (overrides auto duration budget)")
    p_analyze.add_argument("--resolution", type=int, default=0, help="Upscale keyframes to this long-edge px so the VLM can read small on-screen text (0 = native)")
    p_analyze.add_argument("--start", type=float, default=0.0, help="Focus window start (sec); only extract keyframes from [start,end]")
    p_analyze.add_argument("--end", type=float, default=0.0, help="Focus window end (sec); 0 = clip end")
    p_analyze.add_argument("--llm-backend", help="LLM backend (omlx, ollama, openclaw)")
    p_analyze.add_argument("--score", action="store_true", help="Score video after analysis")
    p_analyze.add_argument("--skip-audio", action="store_true", default=True, help="Skip audio analysis (default: skip)")
    p_analyze.add_argument("--no-skip-audio", dest="skip_audio", action="store_false", help="Enable audio analysis")
    p_analyze.add_argument("--skip-diarize", action="store_true", default=True, help="Skip diarization (default: skip)")
    p_analyze.add_argument("--no-skip-diarize", dest="skip_diarize", action="store_false", help="Enable diarization")

    # --- transcribe ---
    p_transcribe = sub.add_parser("transcribe", help="Transcribe a local video/audio")
    p_transcribe.add_argument("path", nargs="?", help="Path to video/audio file")
    p_transcribe.add_argument("--pending", action="store_true", help="Transcribe all pending videos")
    p_transcribe.add_argument("--backend", help="Whisper backend")

    # --- vision ---
    p_vision = sub.add_parser("vision", help="Extract keyframes and describe with VLM")
    p_vision.add_argument("path", help="Path to video file")
    p_vision.add_argument("--backend", help="VLM backend (omlx, ollama)")
    p_vision.add_argument("--model", help="VLM model name")

    # --- list ---
    p_list = sub.add_parser("list", help="List analyzed videos")
    p_list.add_argument("--status", help="Filter by status")
    p_list.add_argument("--platform", help="Filter by platform")
    p_list.add_argument("--limit", type=int, default=50)

    # --- show ---
    p_show = sub.add_parser("show", help="Show full analysis for a video")
    p_show.add_argument("video_id", help="Video ID")

    # --- view ---
    p_view = sub.add_parser("view", help="Serve a read-only local viewer of analyzed videos")
    p_view.add_argument("--host", default="127.0.0.1")
    p_view.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    p_view.add_argument("--no-open", dest="open_browser", action="store_false",
                        help="Don't auto-open the browser")

    # --- inspect ---
    p_inspect = sub.add_parser(
        "inspect",
        help="Interactive single-clip inspector (self-contained HTML, time-synced)")
    p_inspect.add_argument("video", help="Video id (exact or unique prefix)")
    p_inspect.add_argument(
        "--output", "-o", default=None,
        help="HTML file to write (default: <data>/inspect-<id>.html)")
    p_inspect.add_argument(
        "--open", dest="open_browser", action="store_true",
        help="Open the written file in the default browser")

    # --- export ---
    p_export = sub.add_parser("export", help="Export analyses")
    p_export.add_argument("--format", choices=["json", "csv", "html"], default="json")
    p_export.add_argument("--output", "-o", default="./export")
    p_export.add_argument("--video", help="Single video id (html: exact or unique prefix)")

    # --- score ---
    p_score = sub.add_parser("score", help="Score a video using LLM analysis")
    p_score.add_argument("video_id", help="Video ID to score")
    p_score.add_argument("--backend", help="LLM backend (omlx, ollama, openclaw)")

    # --- compare ---
    p_compare = sub.add_parser("compare", help="Compare analyzed videos side by side")
    p_compare.add_argument("video_ids", nargs="+", help="Video IDs (exact or unique prefix)")
    p_compare.add_argument("--json", action="store_true", help="Emit JSON instead of a table")

    # --- research ---
    p_research = sub.add_parser("research", help="Competitor research across channels → aggregate")
    p_research.add_argument("--niche", required=True, help="Niche label for the report")
    p_research.add_argument("--channels", nargs="+", required=True, help="Channel/profile URLs")
    p_research.add_argument("--depth", type=int, default=20, help="Videos per channel (default 20)")
    p_research.add_argument("--llm-backend", help="LLM backend (omlx, ollama, openclaw)")
    p_research.add_argument("--no-analyze", dest="analyze", action="store_false",
                            help="Skip crawl+analyze; aggregate only what's already in the DB")
    p_research.add_argument("--json", action="store_true", help="Emit the aggregate as JSON")
    p_research.add_argument("--out", help="Write a synthesized markdown report to this path")

    # --- stats ---
    p_stats = sub.add_parser("stats", help="Corpus statistics (tag distributions + score aggregates)")
    p_stats.add_argument("--channel", help="Scope to one channel (matches videos.uploader substring)")
    p_stats.add_argument("--json", action="store_true", help="Emit JSON instead of a table")
    p_stats.add_argument("--csv", help="Write long-format CSV to this path")

    # --- db ---
    p_db = sub.add_parser("db", help="Database operations")
    p_db_sub = p_db.add_subparsers(dest="db_command")
    p_db_sub.add_parser("stats", help="Show database stats")
    p_db_sub.add_parser("reset", help="Reset database (destructive)")
    p_db_sub.add_parser("migrate", help="Run pending migrations")

    # --- config ---
    p_config = sub.add_parser("config", help="Configuration")
    p_cfg_sub = p_config.add_subparsers(dest="config_command")
    p_cfg_sub.add_parser("show", help="Show resolved config")
    p_cfg_sub.add_parser("check", help="Check external tools")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    handlers = {
        "browse": _cmd_browse,
        "crawl": _cmd_crawl,
        "analyze": _cmd_analyze,
        "transcribe": _cmd_transcribe,
        "vision": _cmd_vision,
        "list": _cmd_list,
        "show": _cmd_show,
        "export": _cmd_export,
        "inspect": _cmd_inspect,
        "view": _cmd_view,
        "score": _cmd_score,
        "compare": _cmd_compare,
        "stats": _cmd_stats,
        "research": _cmd_research,
        "db": _cmd_db,
        "config": _cmd_config,
    }
    handlers[args.command](args)


def _read_url_lines(path: str) -> List[str]:
    """Read URL lines from a file, or from stdin when path is '-'.

    The `browse --urls-only | crawl --file -` pipe advertised in browse's output
    needs the '-' case; plain open('-') raises FileNotFoundError.
    """
    if path == "-":
        return sys.stdin.read().splitlines()
    with open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines()


def _collect_urls(args) -> List[str]:
    urls = list(args.urls) if args.urls else []
    path = getattr(args, "file", None)
    if path:
        for line in _read_url_lines(path):
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def _expand_listing(url: str, limit: int, require_profile: bool) -> List[str]:
    """Expand a channel/playlist URL into the video URLs it lists.

    Raises ValueError with a user-facing message; the caller prints it. The
    profile check runs after get_crawler so an unsupported *platform* reports as
    such, and browse's NotImplementedError surfaces for platforms that have no
    listing support (TikTok) rather than being masked as "not a profile URL".
    """
    from .crawl import get_crawler, is_profile_url

    crawler = get_crawler(url)  # ValueError for unsupported platforms
    if require_profile and not is_profile_url(url):
        raise ValueError(
            "not a channel/profile URL: {}\n"
            "  Use --playlist for playlists, or pass video URLs directly.".format(url)
        )
    try:
        entries = crawler.browse(url, limit=limit)
    except NotImplementedError as e:
        raise ValueError(str(e))
    # v1 forwards URLs only. browse already carries title/uploader/duration, so
    # download() re-fetches them via yt-dlp --dump-json; threading VideoMeta
    # through download()'s URL-shaped signature is a refactor, not a freebie.
    return [e.url for e in entries if e.url]


def _cmd_browse(args) -> None:
    from .crawl import get_crawler

    if args.cookies:
        os.environ["IG_COOKIES_FILE"] = args.cookies

    try:
        crawler = get_crawler(args.url)
        entries = crawler.browse(args.url, limit=args.limit)
    except NotImplementedError as e:
        print(f"Error: {e}")
        return
    except Exception as e:
        print(f"Error browsing: {e}")
        return

    if not entries:
        print("No videos found.")
        return

    if args.urls_only:
        for e in entries:
            print(e.url)
        return

    if args.output_json:
        import dataclasses
        data = [dataclasses.asdict(e) for e in entries]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    print(f"Found {len(entries)} videos from @{entries[0].uploader or '?'}:\n")
    for i, e in enumerate(entries, 1):
        title = (e.title or "(untitled)")[:60]
        dur = f"{e.duration_sec:.0f}s" if e.duration_sec else "?"
        date = e.upload_date or "?"
        print(f"  {i:3d}. [{dur:>5s}] {title}")
        print(f"       {e.url}")
    print(f"\nTip: pipe URLs to crawl with: reel-scout browse {args.url} --urls-only | reel-scout crawl --file -")


def _cmd_crawl(args) -> None:
    from . import db
    from .crawl import get_crawler

    if args.channel and args.playlist:
        print("Error: use --channel or --playlist, not both.")
        return

    if args.cookies:
        os.environ["IG_COOKIES_FILE"] = args.cookies

    urls = _collect_urls(args)

    listing = args.channel or args.playlist
    if listing:
        try:
            found = _expand_listing(
                listing, args.limit, require_profile=bool(args.channel)
            )
        except ValueError as e:
            print("Error: {}".format(e))
            return
        except Exception as e:
            print("Error listing {}: {}".format(listing, e))
            return
        if not found:
            print("No videos found at {}".format(listing))
            return
        print("Found {} videos at {}".format(len(found), listing))
        urls.extend(found)

    if not urls:
        print(
            "No URLs provided. Use: reel-scout crawl <url>, --file urls.txt, "
            "--channel <url>, or --playlist <url>"
        )
        return

    config.ensure_dirs()
    conn = db.init_db()

    for i, url in enumerate(urls):
        print(f"[{i+1}/{len(urls)}] {url}")
        try:
            crawler = get_crawler(url)
            meta = crawler.download(url, config.VIDEOS_DIR)
            vid = db.upsert_video(
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
            print(f"  OK: {meta.title[:60]} ({meta.duration_sec:.0f}s) -> {vid}")
        except Exception as e:
            print(f"  Error: {e}")

    conn.close()


def _cmd_analyze(args) -> None:
    from .analyze.pipeline import PipelineOptions, run

    urls = _collect_urls(args)
    if not urls and not args.resume:
        print("No URLs provided. Use: reel-scout analyze <url> or --file urls.txt")
        return

    options = PipelineOptions(
        skip_vision=args.skip_vision,
        skip_transcribe=args.skip_transcribe,
        skip_audio=args.skip_audio,
        skip_diarize=args.skip_diarize,
        score=args.score,
        resume=args.resume,
        whisper_backend=args.whisper_backend,
        vlm_backend=args.vlm_backend,
        vlm_model=args.vlm_model,
        keyframe_strategy=args.keyframe_strategy,
        keyframe_max=args.keyframe_max,
        resolution=args.resolution,
        start_sec=args.start,
        end_sec=args.end,
    )
    run(urls, options)


def _cmd_transcribe(args) -> None:
    from . import db
    from .transcribe import get_transcriber

    if args.pending:
        config.ensure_dirs()
        conn = db.init_db()
        videos = db.list_videos(conn, status="downloaded", limit=9999)
        if not videos:
            print("No pending videos to transcribe.")
            return
        transcriber = get_transcriber(args.backend)
        for v in videos:
            print(f"Transcribing: {v['title'] or v['id']}")
            result = transcriber.transcribe(v["file_path"])
            segments_data = [
                {"start": s.start, "end": s.end, "text": s.text,
                 "confidence": s.confidence}
                for s in result.segments
            ]
            db.save_transcript(
                conn, v["id"],
                language=result.language,
                text_full=result.text_full,
                segments_json=json.dumps(segments_data, ensure_ascii=False),
                whisper_model=result.model,
                duration_sec=result.duration_sec,
            )
            print(f"  Language: {result.language}, Duration: {result.duration_sec:.1f}s")
        conn.close()
    elif args.path:
        transcriber = get_transcriber(args.backend)
        result = transcriber.transcribe(args.path)
        print(f"Language: {result.language}")
        print(f"Duration: {result.duration_sec:.1f}s")
        print(f"---")
        print(result.text_full)
    else:
        print("Provide a file path or use --pending")


def _cmd_vision(args) -> None:
    from .vision import get_vlm
    from .vision.keyframe import extract_keyframes

    import tempfile
    kf_dir = tempfile.mkdtemp(prefix="reel_scout_kf_")
    print(f"Extracting keyframes from: {args.path}")
    keyframes = extract_keyframes(args.path, kf_dir, "temp")
    print(f"  Extracted {len(keyframes)} keyframes")

    vlm = get_vlm(args.backend)
    for kf in keyframes:
        desc = vlm.describe_frame(kf.file_path)
        print(f"\n[{kf.timestamp_sec:.1f}s] {desc.description}")


def _cmd_list(args) -> None:
    from . import db

    config.ensure_dirs()
    conn = db.init_db()
    videos = db.list_videos(conn, status=args.status, platform=args.platform, limit=args.limit)
    if not videos:
        print("No videos found.")
        return

    for v in videos:
        title = (v["title"] or "(untitled)")[:50]
        print(f"  {v['id']}  {v['platform']:10s}  {v['status']:12s}  {title}")

    print(f"\nTotal: {len(videos)}")
    conn.close()


def _cmd_show(args) -> None:
    from . import db

    config.ensure_dirs()
    conn = db.init_db()
    video = db.get_video(conn, args.video_id)
    if not video:
        print(f"Video not found: {args.video_id}")
        return

    analysis = db.get_analysis(conn, args.video_id)
    transcript = db.get_transcript(conn, args.video_id)

    print(f"Video: {video['title'] or '(untitled)'}")
    print(f"Platform: {video['platform']}")
    print(f"URL: {video['url']}")
    print(f"Duration: {video['duration_sec']}s")
    print(f"Status: {video['status']}")

    if transcript:
        print(f"\n--- Transcript ({transcript['language']}) ---")
        print(transcript["text_full"][:500])

    if analysis:
        print(f"\n--- Analysis ---")
        full = json.loads(analysis["full_json"]) if analysis["full_json"] else {}
        print(json.dumps(full, ensure_ascii=False, indent=2))

    conn.close()


def _cmd_inspect(args) -> None:
    import os

    from . import db, inspector
    from .compare import resolve_ref

    conn = db.init_db()
    video_id, matches = resolve_ref(conn, args.video)
    if video_id is None:
        if matches:
            print("Ambiguous '%s' — matches %d videos: %s"
                  % (args.video, len(matches), ", ".join(matches[:8])))
        else:
            print("No video matches '%s'." % args.video)
        conn.close()
        sys.exit(1)

    view = inspector.build_inspect_view(conn, video_id)
    conn.close()
    if view is None:
        print("No video matches '%s'." % args.video)
        sys.exit(1)

    output = args.output or os.path.join(config.DATA_DIR, "inspect-%s.html" % video_id)
    parent = os.path.dirname(output)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(inspector.render_inspector(view))
    print("Wrote inspector for %s to %s" % (view["title"], output))

    if getattr(args, "open_browser", False):
        try:
            import webbrowser
            webbrowser.open("file://" + os.path.abspath(output))
        except Exception:  # noqa: BLE001 - headless / no browser is fine
            pass


def _cmd_view(args) -> None:
    from . import db, viewer

    config.ensure_dirs()
    db.init_db().close()  # ensure schema/migrations, then serve per-request conns
    viewer.serve(host=args.host, port=args.port, open_browser=args.open_browser)


def _cmd_export(args) -> None:
    from . import db
    from .export.json_export import export_csv, export_html, export_json

    config.ensure_dirs()
    conn = db.init_db()

    if args.format == "json":
        count = export_json(conn, args.output)
        print(f"Exported {count} analyses to {args.output}/")
    elif args.format == "csv":
        count = export_csv(conn, args.output)
        print(f"Exported {count} rows to {args.output}")
    elif args.format == "html":
        video_id = None
        if getattr(args, "video", None):
            from .compare import resolve_ref
            video_id, _ = resolve_ref(conn, args.video)
            if video_id is None:
                print(f"Video not found: {args.video}")
                conn.close()
                return
        path = export_html(conn, args.output, video_id=video_id)
        print(f"Wrote self-contained viewer to {path}")

    conn.close()


def _cmd_score(args) -> None:
    from . import db
    from .scorer import score_video

    config.ensure_dirs()
    conn = db.init_db()

    video = db.get_video(conn, args.video_id)
    if not video:
        print(f"Video not found: {args.video_id}")
        conn.close()
        return

    existing = db.get_score(conn, args.video_id)
    if existing:
        print("Score already exists for this video:")
        print(f"  Overall:    {existing['overall']:.1f}")
        print(f"  Hook:       {existing['hook_strength']:.1f}")
        print(f"  Visual:     {existing['visual_storytelling']:.1f}")
        print(f"  Pacing:     {existing['pacing']:.1f}")
        print(f"  Structure:  {existing['structure']:.1f}")
        print(f"  Reasoning:  {existing['reasoning']}")
        conn.close()
        return

    try:
        score = score_video(conn, args.video_id, llm_backend=args.backend)
        print(f"Score for: {video['title'] or '(untitled)'}")
        print(f"  Overall:    {score.overall:.1f}")
        print(f"  Hook:       {score.hook_strength:.1f}")
        print(f"  Visual:     {score.visual_storytelling:.1f}")
        print(f"  Pacing:     {score.pacing:.1f}")
        print(f"  Structure:  {score.structure:.1f}")
        print(f"  Reasoning:  {score.reasoning}")
    except ValueError as e:
        print(f"Error: {e}")

    conn.close()


def _cmd_compare(args) -> None:
    from . import db
    from .compare import build_comparison, format_table

    config.ensure_dirs()
    conn = db.init_db()
    try:
        comparison = build_comparison(conn, args.video_ids)
        if args.json:
            print(json.dumps(comparison, ensure_ascii=False, indent=2))
        else:
            print(format_table(comparison))
    finally:
        conn.close()


def _cmd_research(args) -> None:
    from . import db, research

    config.ensure_dirs()
    conn = db.init_db()
    try:
        report = research.run_research(
            conn, niche=args.niche, channel_urls=args.channels,
            depth=args.depth, llm_backend=args.llm_backend,
            do_analyze=args.analyze,
        )
        if args.out:
            md = research.render_report(report, llm_backend=args.llm_backend)
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(md)
            print("Wrote research report to %s (%d chars)" % (args.out, len(md)))
        elif args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(_format_research_summary(report))
    finally:
        conn.close()


def _format_research_summary(report) -> str:
    lines = ["Research: %s" % report["niche"],
             "=" * 40,
             "Channels: %d | niche videos: %d (analyzed %d)" % (
                 report["channel_count"],
                 report["niche_wide"]["video_count"],
                 report["niche_wide"]["analyzed_count"])]
    for ch in report["channels"]:
        lines.append("\n- %s (%s)" % (ch.get("uploader") or "?", ch["channel_url"]))
        lines.append("  videos=%d analyzed=%d modal_format=%s modal_pacing=%s avg_overall=%s" % (
            ch["video_count"], ch["analyzed_count"],
            ch["modal_format"], ch["modal_pacing"], ch["avg_overall"]))
    nw = report["niche_wide"]
    lines.append("\n-- niche-wide --")
    lines.append("modal_format=%s modal_structure=%s avg_overall=%s" % (
        nw["modal_format"], nw["modal_structure"], nw["avg_overall"]))
    return "\n".join(lines)


def _cmd_stats(args) -> None:
    from . import db, stats as stats_mod

    config.ensure_dirs()
    conn = db.init_db()
    try:
        result = stats_mod.compute_stats(conn, channel=args.channel)
        if args.csv:
            n = stats_mod.write_csv(result, args.csv)
            print("Wrote %d stat rows to %s" % (n, args.csv))
        elif args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(stats_mod.format_stats(result))
    finally:
        conn.close()


def _cmd_db(args) -> None:
    from . import db

    if args.db_command == "stats":
        config.ensure_dirs()
        conn = db.init_db()
        stats = db.db_stats(conn)
        print("Database Statistics")
        print("=" * 40)
        for table, count in stats.items():
            if isinstance(count, dict):
                print(f"  {table}:")
                for k, v in count.items():
                    print(f"    {k}: {v}")
            else:
                print(f"  {table}: {count}")
        conn.close()

    elif args.db_command == "reset":
        answer = input("This will DELETE all data. Type 'yes' to confirm: ")
        if answer.strip().lower() == "yes":
            if os.path.exists(config.DB_PATH):
                os.remove(config.DB_PATH)
                print("Database reset.")
            else:
                print("No database file found.")
        else:
            print("Cancelled.")

    elif args.db_command == "migrate":
        config.ensure_dirs()
        conn = db.init_db()
        print("Migrations complete.")
        conn.close()

    else:
        print("Use: reel-scout db {stats|reset|migrate}")


def _probe_cmd(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            first = (r.stdout.strip().split("\n") or [""])[0]
            return True, first or "ok"
        return False, "exit %d" % r.returncode
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def _probe_http(url, timeout=3):
    import urllib.request
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True, "%s (reachable)" % url
    except Exception as e:  # noqa: BLE001
        return False, "%s (NOT reachable: %s)" % (url, e)


def _probe_import(module):
    import importlib.util
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:  # noqa: BLE001 - a broken parent package shouldn't crash the check
        return False


def _run_config_checks():
    """Return [(name, ok, detail)] for every backend the current config selects.

    Only the *configured* backends are probed (VLM/LLM keyed off their backend
    setting; the optional audio/diarize/instagram groups only when enabled), and
    yt-dlp is resolved the same way the runtime resolves it (crawl/ytdlp)."""
    from .crawl import ytdlp
    checks = []

    checks.append(("ffmpeg", *_probe_cmd([config.FFMPEG_BIN, "-version"])))
    # yt-dlp: probe the SAME binary the crawlers use, not a hardcoded "yt-dlp".
    checks.append(("yt-dlp", *_probe_cmd(list(ytdlp.base_cmd()) + ["--version"])))

    if config.WHISPER_BACKEND == "faster-whisper":
        ok = _probe_import("faster_whisper")
        checks.append(("whisper", ok, "faster-whisper %s" % ("installed" if ok else "NOT installed")))
    else:
        ok, _ = _probe_cmd(["whisper", "--help"])
        checks.append(("whisper", ok, "whisper.cpp %s" % ("found" if ok else "NOT found")))

    vlm_url = config.OMLX_BASE_URL if config.VLM_BACKEND == "omlx" else config.OLLAMA_BASE_URL
    checks.append(("VLM (%s)" % config.VLM_BACKEND, *_probe_http(vlm_url)))

    # LLM reachability keyed off LLM_BACKEND (previously never checked as such).
    llm_url = {
        "omlx": config.OMLX_BASE_URL,
        "ollama": config.OLLAMA_BASE_URL,
        "openclaw": config.OPENCLAW_BASE_URL,
    }.get(config.LLM_BACKEND)
    if llm_url:
        checks.append(("LLM (%s)" % config.LLM_BACKEND, *_probe_http(llm_url)))
    else:
        checks.append(("LLM (%s)" % config.LLM_BACKEND, False, "unknown backend"))

    # Optional backends — only probed when configured/enabled.
    if config.PANNS_MODEL_PATH:
        ok = _probe_import("onnxruntime")
        checks.append(("audio/PANNs", ok, "onnxruntime %s" % ("installed" if ok else "NOT installed")))
    if config.DIARIZE_ENABLED:
        ok = _probe_import("pyannote.audio")
        tok = "token set" if config.PYANNOTE_AUTH_TOKEN else "TOKEN MISSING"
        checks.append(("diarize", ok and bool(config.PYANNOTE_AUTH_TOKEN),
                       "pyannote.audio %s, %s" % ("installed" if ok else "NOT installed", tok)))
    if config.IG_COOKIES_FILE:
        ok = _probe_import("instaloader")
        cookies_ok = os.path.exists(config.IG_COOKIES_FILE)
        checks.append(("instagram", ok and cookies_ok,
                       "instaloader %s, cookies %s" % (
                           "installed" if ok else "NOT installed",
                           "found" if cookies_ok else "NOT found")))
    return checks


def _cmd_config(args) -> None:
    if args.config_command == "show":
        print(config.show())

    elif args.config_command == "check":
        print("Checking configured backends...\n")
        for name, ok, detail in _run_config_checks():
            print("  %s %-14s %s" % ("OK" if ok else "!!", name + ":", detail))

    else:
        print("Use: reel-scout config {show|check}")


if __name__ == "__main__":
    main()
