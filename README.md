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

## Prompt Pack (analysis layer)

Reel Scout's pipeline gets clean input into a model. The **reverse-decode prompt
pack** in [`prompts/`](./prompts/) is the analysis brain you point at that input —
to reverse-engineer *why* a short-form video works and extract a transferable
structure, with anti-hallucination guardrails (observation vs. inference, cite the
timestamp). Open (MIT). See [`prompts/README.md`](./prompts/README.md).

## Requirements

- Python 3.9+
- ffmpeg
- yt-dlp

## Attribution

Video extraction techniques (captions-first transcription, duration-aware frame
budgeting, time-range focus, on-screen-text resolution bump) are adapted from
[claude-video](https://github.com/bradautomates/claude-video) (MIT). See [`NOTICE`](./NOTICE).
