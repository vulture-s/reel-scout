# Changelog

## Unreleased

### Added
- **One app instead of two.** The library index and the interactive inspector now
  share a single server and port — a row in the list opens straight into the
  player/waveform view. `view` lands on the library, `inspect <id>` opens one clip.
- **vulture.s shell.** `theme.py` carries the brand tokens (warm paper, warm-black
  ink, three-step rules, mono uppercase chrome) from the brand SSOT. Deviations are
  narrated in-file: a wider tool column, and no cyan (canon caps it at the tv./
  wordmark, which reel-scout doesn't carry).
- **Bundled brand fonts.** Archivo Black / Inter / JetBrains Mono ship with the
  package (78 KB total, OFL). Served as `/font/<file>` live, inlined as base64 in
  exports. CJK is subset per-export from that export's own text.
- **`export --format bundle`** — the take-home: one *self-contained* HTML per reel
  (video, keyframes, waveform peaks, fonts and a CJK subset all inlined) plus an
  index. Move it, rename it, email it — nothing to lose and no server to run.
  Verified: a bundled page issues exactly one network request, for itself.
  Reels over `--max-mb` (default 25) are skipped with a reason.

### Fixed
- `view` served requests single-threaded, so one idle browser keep-alive could
  stall the whole viewer. Now `ThreadingHTTPServer`.

## 1.2.0 — 2026-07-19

> ⚠️ **Craft scores are not comparable across this boundary.** §4E changes how
> `pacing` is scored — it now reasons on measured cut rhythm instead of pure LLM
> judgment, so the same video can score differently than it did on 1.1.0. Re-score
> a video before comparing it with anything scored on an older version.

### Added
- **§4E evidence-based pacing** — `shots.py` measures cut rhythm (cuts/min, shot
  count, avg shot length) via a dedicated full-clip ffmpeg scene pass; `audio/rhythm.py`
  adds RMS energy + best-effort BPM (numpy-gated, no librosa). Stored in the new
  `shot_metrics` table and folded into the analysis so the `pacing` craft score
  rests on measured evidence, not LLM vibes. Config `SHOT_METRICS_ENABLED`.
- **§4F on-screen text (L3.5)** — `ocr.py` collects burned-in captions with
  timestamps: `OCR_ENGINE=vlm` (default) reuses the VLM's `text_in_frame`;
  `tesseract` is an opt-in engine (`ocr` extra, guarded). Stored in `ocr_captions`,
  fed into merge as an L3.5 signal layer; new L3.5 tier in the reliability cheatsheet.
- **`patterns --channel`** — per-channel pattern analysis: length, hook/CTA/structure
  mix, top-vs-bottom-half structural contrast, posting cadence. (3B)
- **`inspire --based-on [--angle]`** — generate a fresh content variant (titles,
  hook script, structure outline, length) from a high-scoring video. (4B)
- **`track --my-video --views --likes`** — record real performance and get
  deterministic structural iteration suggestions vs the top-scored corpus. (4D)
- **IG browse instaloader fallback** when yt-dlp's Instagram extractor breaks. (3A)
- **MCP tools** `patterns`, `inspire`, `research` (5 → 8 tools). (4C)

### Changed
- DB schema v6 → v9 (added `shot_metrics`, `ocr_captions`, `performance` tables).

## 1.1.0 — 2026-07-17

### Added
- **Read-only viewer** for decoded analyses — two surfaces sharing one renderer:
  - **`export --format html`** — a self-contained single-file HTML (keyframes
    base64-embedded, all CSS inline, zero external assets) that opens in any
    browser, works offline, and survives being moved. Built as a take-home
    artifact for people who don't install reel-scout. `--video <id|prefix>`
    exports one video; otherwise all analyzed videos.
  - **`reel-scout view`** — a local read-only HTTP server rendering the library
    live (index → per-video pages, keyframes served by URL). `--host/--port/
    --no-open`.
  Both show each video's decoded structure (hook/beats/CTA), keyframes + what
  the VLM saw, craft scores, and transcript. Deliberately read-only — no action
  surfaces; scores are labelled a reference, not an authority.
- `db.get_keyframes_with_descriptions` (keyframes ⟕ vision_descriptions).

## 1.0.0 — 2026-07-17

First stable release. Completes the Batch Intelligence, Content Strategy (4A),
and Tool Hygiene milestones — the tool is now installable, CI-covered, and
feature-complete for cross-video/-channel analysis.

### Added
- **`stats`** — corpus statistics: tag distributions (content_type,
  content_structure, format, pacing, hook/cta type, emotion) + craft-score
  aggregates (avg/min/max), with `--channel` scoping, `--json`, and `--csv`
  (roadmap 3D).
- **`research --niche --channels --depth`** — cross-channel competitor research:
  lists each channel → analyzes → aggregates per channel and niche-wide → `--out`
  renders an LLM markdown report (common patterns / differentiation / strategy),
  falling back to a deterministic data-only report when no LLM is reachable
  (roadmap 4A). `--json` emits the aggregate; `--no-analyze` reuses the DB.
- **content-structure classification** — hook-body-cta / problem-solution /
  listicle / story-arc / raw-moment, emitted by the merger (roadmap 3C).
- **normalized analysis tags** — content_type / opening_type / cta_type / style
  format+pacing / emotion / content_structure mirrored from full_json into
  indexed columns for filtering and stats; migrations backfill existing rows
  (roadmap 3C, DB schema v4→v6).
- **GitHub Actions CI** — pytest across Python 3.9–3.13 (roadmap 5B).
- **MIT LICENSE** file + full PyPI packaging metadata (urls, classifiers,
  dynamic version); `pip install`-ready (roadmap 5A).

### Changed
- **`config check`** now covers all *configured* backends: yt-dlp via the
  resolved binary, LLM reachability keyed off `LLM_BACKEND`, and the optional
  audio/diarize/instagram groups when enabled (roadmap 5B).
- Version is single-sourced from `reel_scout/__init__.py` via hatchling dynamic
  version (fixes the prior 0.2.0/0.3.0 drift).

## 0.3.0 — 2026-07-17

### Added
- `analyze <local-path>` — the `analyze` pipeline now accepts a local video file,
  not just a URL. Registers a `platform="local"` row (`url == file_path == abspath`,
  `platform_id` = content hash, so identical content at two paths dedups) and runs
  transcribe / vision / merge unchanged. This is the platform-lockout insurance:
  when a yt-dlp extractor breaks, the core pipeline still runs on files you already
  have. Duration is probed independently and stays `None` on probe failure (no
  fabricated fallback written to the DB); a missing path raises a clear
  `FileNotFoundError` instead of the crawler's opaque "Unsupported platform".
- `compare <id1> <id2> ...` — cross-video comparison table (duration, format,
  pacing, hook/CTA type, content type, and the craft scores). Transposed table
  plus `--json`; accepts an exact id or a unique prefix; missing analysis/score
  renders as an em dash rather than a fabricated value. Pure DB read path — no
  crawler, no LLM — so it also survives a platform lockout.
- `YTDLP_BIN` config (mirrors the `FFMPEG_BIN` convention).

### Changed
- yt-dlp is now invoked via the copy pinned in this environment
  (`python -m yt_dlp`) instead of whatever `yt-dlp` is first on PATH — a stale
  PATH build silently produced baffling extractor errors. Override with
  `YTDLP_BIN`. All three crawlers (youtube / tiktok / instagram) routed through
  the new `crawl/ytdlp.py` helper.
- yt-dlp error messages surface the real failure: `ERROR:` lines are kept first
  (instead of a blind `stderr[:500]` that buried them under leading warnings),
  with a fallback to the stderr tail and an update hint when the failure looks
  like a broken extractor.

## 0.2.0 — 2026-07-14

### Added
- Opt-in Whisper language controls for bilingual / code-switching audio
  (中英對照 interviews): `WHISPER_LANGUAGE`, `WHISPER_TASK`,
  `WHISPER_MULTILINGUAL`, `WHISPER_CHUNK_LENGTH`.
  - Working recipe for a ZH-host / EN-guest interview:
    `WHISPER_MULTILINGUAL=1 WHISPER_CHUNK_LENGTH=15`.
  - Fixes long-form language-lock drift where whisper `large-v3` "translates"
    the guest's English into garbled Chinese. Verified on a 40-min interview:
    latin-char recovery 56% -> 90%.
  - Defaults reproduce prior single-pass behavior; leave OFF for single-language
    short-form.
- `config check` now surfaces the new `WHISPER_*` values.
- `tests/test_transcribe.py` pins the config -> transcribe() kwargs mapping.

### Changed
- `faster-whisper` floor raised `>=0.10.0` -> `>=1.1.0` (the `multilingual`
  transcribe arg the fix relies on was added in 1.1).
