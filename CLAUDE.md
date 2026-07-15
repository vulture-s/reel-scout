# Reel Scout

Short-form video analysis CLI tool.

## Stack
- Python 3.9+ (strict: no match/case, no 3.10+ syntax)
- yt-dlp for video crawling
- faster-whisper / whisper.cpp for transcription
- oMLX / Ollama for VLM visual analysis
- SQLite for state tracking
- argparse for CLI (no click/typer)
- urllib for HTTP (no requests dependency)

## IG Cookies
- Browse/crawl IG requires cookies: `cookies.txt` (Netscape format) in project root
- Export from Chrome extension "Get cookies.txt LOCALLY" on instagram.com page
- yt-dlp IG user extractor is broken as of 2026.4. There is **no instaloader fallback** — `InstagramCrawler.browse` is pure yt-dlp and raises `RuntimeError` on failure. The `instagram` optional extra in pyproject.toml is unused (verified 2026-07-15).
- After analysis, ask user if downloaded videos should be kept or deleted

## Architecture
- `reel_scout/crawl/` — per-platform downloaders via yt-dlp (+ browse via --flat-playlist)
- `reel_scout/transcribe/` — whisper backends
- `reel_scout/vision/` — keyframe extraction + VLM
- `reel_scout/analyze/` — pipeline orchestrator + merger
- `reel_scout/export/` — JSON/CSV/vector DB output
- `reel_scout/db.py` — SQLite schema + CRUD
- `reel_scout/config.py` — env-based config

## Transcription — bilingual / long-form drift
- whisper `large-v3` locks language from the opening window; on long code-switching
  files (中英對照 interview: ZH host + EN guest) it "translates" the other language
  into the locked one → garbled output. NOT an audio problem (isolated slices are clean).
- Fix is opt-in env (defaults preserve prior single-pass behavior):
  `WHISPER_MULTILINGUAL=1 WHISPER_CHUNK_LENGTH=15` — per-chunk re-detection.
  `multilingual` alone is insufficient; the short `chunk_length` is what forces it.
- Also available: `WHISPER_LANGUAGE` (force one), `WHISPER_TASK=translate` (force EN out).
- Keep OFF for single-language short-form (per-chunk detect adds cost).

## Rules
- All HTTP calls use urllib.request, not requests
- Use `from __future__ import annotations` in all files
- Use `typing.Optional`, `typing.List`, `typing.Dict` (not built-in generics)
- SQLite WAL mode for safety
- Sequential processing (transcribe all, then VLM all) to avoid memory pressure
