# Reel Scout

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

## Long-form video

Reel Scout is **built for short-form** (Shorts / Reels / TikTok) — that's where the
structured output (hook, CTA, pacing, retention-style timeline) is most meaningful,
and where it's fastest.

It is **not limited to short-form**, though. The engine has no hard duration cap:
download (yt-dlp), transcription (whisper), and audio analysis (PANNs) all scale to
long videos, and keyframe extraction is bounded by `max_frames` rather than blowing
up. A 1-hour video runs fine. Two things to do when you point it at long-form:

- **Raise `--keyframe-max`.** The default keyframe budget is tuned for short clips; on
  a long video it samples too sparsely (a 1-hour video can land ~1 frame per 15 min).
  Bump it so vision isn't starved.
- **Enable `--no-skip-audio`** to get the music / speech / silence / sound-effect
  breakdown — often the most useful signal on music or ambient pieces (see
  [`docs/audio-panns-setup.md`](docs/audio-panns-setup.md)).

Caveat: the structured **merge schema is short-form-shaped** (it expects a hook and a
3-segment `0-3s … CTA` timeline), so on long-form those particular fields get noisy or
meaningless. The transcript, audio breakdown, keyframe descriptions, and summary stay
useful; the reel-specific fields don't.

```bash
reel-scout analyze "<long-form-url>" --keyframe-max 24 --no-skip-audio
```

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
