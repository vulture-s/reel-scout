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
