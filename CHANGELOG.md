# Changelog

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
