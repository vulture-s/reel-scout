# Reel Scout — Command & Integration Reference

Concise reference for the CLI, MCP tools, LLM/VLM backends, and config flags.
For the design rationale see [`roadmap.md`](./roadmap.md); for the signal model
see [`../prompts/signal-reliability-cheatsheet.md`](../prompts/signal-reliability-cheatsheet.md).

## CLI

| Command | What it does |
|---|---|
| `browse <profile_url>` | List a channel/profile's videos (metadata only). `--json` / `--urls-only`. |
| `crawl <url…>` | Download videos. `--channel <url> --limit N`, `--playlist <url>`, `--file -` (stdin). |
| `analyze <url\|path…>` | Full pipeline: download/register → transcribe → keyframes+VLM → shot/audio metrics (§4E) → on-screen text (§4F) → merge → optional score. Accepts a local file path (platform-outage insurance). `--score`. |
| `transcribe <path>` / `vision <path>` | Individual stages against a local file. |
| `list` / `show <id>` | List analyzed videos / show one analysis. |
| `export --format json\|csv\|html\|bundle` | Export analyses. `html` = one self-contained file; **`bundle`** = one self-contained file *per reel* + an index (the course take-home). |
| `view` | Local read-only web server for the library. |
| `inspect <id>` | Interactive single-clip viewer (transcript↔keyframe time-sync). |
| `score <id>` | Craft score (hook / visual / **pacing (evidence-based, §4E)** / structure). |
| `compare <id…>` | Side-by-side comparison table. |
| `stats [--channel] [--csv]` | Corpus tag distributions + score aggregates. |
| `patterns --channel <c>` | Per-channel patterns: length, hook/CTA/structure mix, high-vs-low contrast, cadence. |
| `inspire --based-on <ref> [--angle]` | Generate a fresh variant (titles/hook/structure/length) from a high scorer. |
| `track --my-video <ref> --views --likes [--comments --notes]` | Record real performance + structural iteration hints vs the top corpus. |
| `research --niche <n> --channels <url…> [--depth --out --no-analyze]` | Competitor research report. |
| `db {stats,reset,migrate}` / `config {show,check}` | DB / config utilities. |

Refs (`<ref>`, `<id>`) accept a full 16-hex video id or a unique prefix; `track --my-video` also accepts a URL already in the DB.

## MCP tools (`reel-scout-mcp`, stdio)

8 tools: `crawl`, `analyze`, `list_videos`, `show_video`, `export`, `patterns`,
`inspire`, `research`. LLM/network tools (`analyze`, `inspire`, `research`) route
stdout to stderr so they don't corrupt the JSON-RPC stream. `research` reads the
existing DB by default; pass `analyze: true` to crawl+analyze first (slow).

## Backends

- **VLM** (`VLM_BACKEND`): `omlx` (default) / `ollama`. Model via `VLM_MODEL`
  (default `qwen2.5vl:7b`), fallback `VLM_FALLBACK_MODEL`.
- **LLM** (merger/scorer/inspire/research, `LLM_BACKEND`): `omlx` / `ollama` /
  `openclaw` (proxy to a subscription, no local GPU).
- **Whisper** (`WHISPER_BACKEND`): `faster-whisper` (default) / whisper.cpp;
  subtitle-first when a native subtitle is present. `WHISPER_MULTILINGUAL=1` for
  code-switching interviews.

All inference defaults to localhost — no cloud API keys required.

## Notable config flags

| Flag | Default | Effect |
|---|---|---|
| `REEL_SCOUT_DATA` | `./data` | Data dir (DB, videos, keyframes). |
| `KEYFRAME_STRATEGY` / `KEYFRAME_MAX` / `KEYFRAME_RESOLUTION` | `scene` / `8` / `0` | Keyframe extraction. |
| `SHOT_METRICS_ENABLED` / `SHOT_SCENE_THRESHOLD` | `true` / `0.3` | §4E measured pacing (cuts/min + energy/BPM). |
| `OCR_ENABLED` / `OCR_ENGINE` | `true` / `vlm` | §4F on-screen text; `tesseract` opt-in (needs the `ocr` extra). |
| `IG_COOKIES_FILE` | — | Instagram cookies for gated content. |
| `LLM_BACKEND` / `VLM_BACKEND` / `WHISPER_BACKEND` | `omlx`/`omlx`/`faster-whisper` | Inference backends. |

`reel-scout config show` prints the resolved config; `config check` probes backend reachability.

## Optional extras (`pip install reel-scout[<extra>]`)

`whisper`, `audio` (onnxruntime+numpy — PANNs events + BPM), `diarize`,
`instagram` (instaloader browse fallback), `ocr` (pytesseract+Pillow), `vector`.

## Take-home bundle

```bash
reel-scout export --format bundle -o ./course-reels \
  --cjk-font /path/to/NotoSansTC.ttf   # optional: embeds Chinese glyphs
```

Each reel becomes ONE html file with the video, keyframes, waveform peaks, fonts
and a per-file CJK subset inlined — no server, no sibling files, nothing to lose
when it is moved or emailed. Sized for short-form: reels land around 2–25 MB, and
anything over `--max-mb` (default 25) is skipped with a reason rather than
producing a file nobody can open. Without `--cjk-font`, Chinese falls back to the
reader's system face; Latin always uses the bundled brand faces.
