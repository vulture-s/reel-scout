# Reel Scout

> English ｜ [繁體中文](README.zh.md)

Short-form video analysis CLI tool.

Crawl, transcribe, and visually analyze YouTube Shorts, Instagram Reels, and TikTok videos into structured data.

## Install

```bash
pip install -e .
pip install -e ".[whisper]"  # for faster-whisper transcription
```

## Usage

```bash
reel-scout crawl "https://youtube.com/shorts/xxxxx"
reel-scout analyze "https://youtube.com/shorts/xxxxx"
reel-scout analyze --file urls.txt --skip-vision
reel-scout list
reel-scout show <video_id>
reel-scout export --format json -o ./export
reel-scout config check
```

## Bilingual / code-switching audio (中英對照)

Whisper `large-v3` locks onto the language it detects in the opening window and, on
long files, "translates" later speech of the *other* language back into the locked
one — a code-switching interview (Chinese host + English guest) comes out with the
guest's English mangled into garbled Chinese. It is a long-form drift, not a bad
audio issue: the same passage transcribes perfectly when sliced out on its own.

Fix — force per-chunk language re-detection:

```bash
WHISPER_MULTILINGUAL=1 WHISPER_CHUNK_LENGTH=15 reel-scout analyze "<url>"
```

`multilingual` alone is not enough — it needs a short `chunk_length` (~15s) so each
chunk re-detects. Verified on a 40-min ZH-host/EN-guest interview: latin-char
recovery 56% → 90%. Leave OFF for single-language short-form (per-chunk detection
adds cost). Other levers: `WHISPER_LANGUAGE=en` (force one language),
`WHISPER_TASK=translate` (force English output).

## MCP Server

```bash
reel-scout-mcp  # stdio transport for Claude Code integration
```

## Requirements

- Python 3.9+
- ffmpeg, yt-dlp
- A local LLM/VLM backend (ollama or oMLX) for `merge` + `score`, or Claude/OpenClaw via proxy

### Hardware (local-model self-host)

Models are loaded **sequentially per stage**, not concurrently — peak footprint is the
text LLM, so VRAM / unified memory is the gate:

| stage | model | ~size |
|-------|-------|-------|
| transcribe | faster-whisper large-v3 | ~3 GB |
| keyframe VLM | minicpm-v (~5.5 GB) or llava:7b (~4.7 GB) | ~5 GB |
| merge + score LLM | qwen2.5:14b | ~9 GB |

_Reference run: one short-form reel (download → whisper large-v3 → keyframe → VLM → merge → score) takes **~9–10 min** on an RTX 4070 (12 GB); whisper + VLM dominate. Run pipelines **one at a time** — concurrent runs thrash the card and time the VLM out._

> **VLM choice on 12 GB:** prefer a lean VLM (`minicpm-v` / `llava:7b`). `qwen3-vl:8b` loads at **~10.4 GB** and times out describing text-dense frames on a 12 GB card — keep it for 16 GB+. A single frame timeout no longer kills the run: the pipeline skips that frame and merges what it got.

**Recommended** (full-quality models, smooth):
- NVIDIA: ≥12 GB VRAM (RTX 4070 / 3080-class) + 32 GB RAM + SSD
- Apple Silicon: M2 Pro / M3 Pro+, 32 GB unified memory

**Minimum** (smaller models / slower):
- NVIDIA: 8 GB VRAM (RTX 3060 / 4060) → use qwen2.5:7b + llava:7b/minicpm-v + whisper medium; 16 GB RAM
- Apple Silicon: M1 / M2, 16 GB unified memory
- CPU-only: works, but whisper + LLM are slow — batch/overnight only, not live

No GPU? The cloud backends (Claude / Gemini / OpenClaw proxy) need none of the above.
