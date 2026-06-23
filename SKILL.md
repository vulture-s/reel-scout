---
name: reel-scout
description: Reverse-decode a short-form video (Instagram Reel / TikTok / YouTube Short). Use when the user pastes a short-form video URL and wants to know WHY it works and extract a transferable structure — not just a summary. Downloads + transcribes + visually analyzes the clip with the local reel-scout pipeline, then applies the reverse-decode prompt pack to produce a 4-beat skeleton (Hook → contrast → CTA → resonance) and a transferable骨架.
allowed-tools: Bash, Read
homepage: https://github.com/vulture-s/reel-scout
license: MIT
user-invocable: true
---

# reel-scout — reverse-decode a short-form video

The user hands you a viral short-form video (IG Reel, TikTok, YouTube Short). This
skill turns that URL into **structured evidence** (download → transcript → keyframes
→ VLM visual analysis → SQLite record) using the local `reel-scout` CLI, then points
the **reverse-decode prompt pack** at that evidence to answer the real question:
*why does this clip work, and what骨架 can I transfer to my own topic?*

Two halves, one contract:
1. **reel-scout (the eyes)** — gets clean, grounded input into a model: the actual
   on-screen visuals (via a local VLM) and the actual transcript, not just the caption.
2. **prompts/ (the brain)** — the 4-beat reverse-decode framework that forces the
   model to separate observation from inference, cite timestamps, and emit a
   *transferable* structure instead of a one-line recap.

## Step 0 — Setup preflight (every invocation, silent on success)

The full pipeline shells out to `ffmpeg`/`ffprobe`/`yt-dlp` and needs the
`reel-scout` package installed. Verify first:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/setup.py" --check
```

**Windows note:** use `python` (not `python3` — that's the Microsoft Store stub).
On macOS/Linux either works.

On exit `0` the script emits **nothing** — proceed to Step 1 without comment. **Do
NOT announce "setup is complete."** The only acceptable user-visible output here is
remediation when something is missing.

On non-zero exit, follow the table (run the same script without `--check` for the
exact remediation strings, then act):

| Exit | Meaning | Action |
|------|---------|--------|
| `2` | Missing `ffmpeg` / `ffprobe` / `yt-dlp` | macOS: `brew install ffmpeg` + `pip install -U yt-dlp`. Linux/Windows: tell the user the install commands the script printed. |
| `3` | `reel-scout` not installed | From the repo root: `pip install -e .` (add `pip install -e ".[whisper]"` for transcription). |
| `4` | Both | Do both of the above. |

Within one session you can skip Step 0 on follow-up runs — once `--check` returned
0 nothing about the environment changes between turns.

`python "${CLAUDE_SKILL_DIR}/scripts/setup.py" --json` emits
`{status, missing_binaries, reel_scout_installed, repo_root, platform}` where
`status` is one of `ready | needs_deps | needs_install | needs_install_and_deps` —
use it when you need to branch on specifics.

## Surface limits — read this honestly

The full pipeline needs **local shell + local binaries + a local VLM backend**
(`oMLX` or `ollama`) and (for transcripts) a local Whisper backend. That means:

- **Claude Code / Codex (have a shell): full pipeline runs** — provided the user's
  machine has ffmpeg/yt-dlp/python installed and a local VLM endpoint reachable
  (Step 0 + `reel-scout config check` confirm this).
- **claude.ai (web): the download/VLM/transcribe pipeline does NOT run** — the web
  sandbox has no ffmpeg/yt-dlp and no local VLM. On the web surface you can still
  apply the **prompt pack** to a clip the user describes or screen-records and
  uploads (that is exactly what `prompts/hook-reverse-structure.md` **Prompt B** is
  for — the screen-recording variant with anti-hallucination guardrails). Do **not**
  pretend the automated extraction works on the web; route to Prompt B instead.

If you are unsure which surface you're on, run Step 0 — a non-zero exit with missing
binaries on every attempt is the tell that you lack the local pipeline.

## Step 1 — parse the input

Separate the video source (URL) from any question the user asked. reel-scout
ingests Instagram Reels, TikTok, and YouTube Shorts directly. IG profile *browsing*
needs cookies (see CLAUDE.md); a single Reel URL usually downloads without them.

## Step 2 — run the pipeline

Run the full analyze pipeline on the URL. **Pass the source verbatim, quoted.**

```bash
reel-scout analyze "<url>"
```

Real flags (verbatim from `reel_scout/cli.py`, `analyze` subparser — do **not**
invent flags beyond these):

- `--file PATH` / `-f PATH` — read URLs from a file (one per line) instead of args
- `--resume` — resume an interrupted batch
- `--skip-vision` — skip the VLM visual analysis (transcript-only; faster, no local VLM needed)
- `--skip-transcribe` — skip transcription (visuals-only)
- `--whisper-backend NAME` — Whisper backend (`faster-whisper`, `whisper-cpp`)
- `--vlm-backend NAME` — VLM backend (`omlx`, `ollama`)
- `--vlm-model NAME` — VLM model name
- `--keyframe-strategy NAME` — keyframe strategy (`scene`, `interval`, `hybrid`)
- `--keyframe-max N` — max keyframes per video (overrides the auto duration budget)
- `--resolution N` — upscale keyframes to this long-edge **px** so the VLM can read
  small on-screen text (`0` = native; this is **pixels, not a timestamp**)
- `--start SEC` — focus-window start in **seconds** (float); only extract keyframes from `[start, end]`
- `--end SEC` — focus-window end in **seconds** (float); `0` = clip end
- `--llm-backend NAME` — LLM backend for scoring (`omlx`, `ollama`, `openclaw`)
- `--score` — score the video (hook / visual / pacing / structure) after analysis
- `--skip-audio` / `--no-skip-audio` — audio analysis (default: **skipped**; pass `--no-skip-audio` to enable)
- `--skip-diarize` / `--no-skip-diarize` — diarization (default: **skipped**; pass `--no-skip-diarize` to enable)

> `--start`/`--end` are **seconds as floats** and `--resolution` is **pixels** —
> this differs from claude-video's timestamp strings. Don't pass `MM:SS` here.

Common patterns:

```bash
# Full default analysis (download + transcribe + VLM)
reel-scout analyze "https://www.instagram.com/reel/XXXXXXXX/"

# No local VLM available -> transcript + structured fields only
reel-scout analyze "<url>" --skip-vision

# Focus the VLM on the 0-8s hook, upscale for on-screen text, and score it
reel-scout analyze "<url>" --start 0 --end 8 --resolution 1024 --score
```

If `analyze` fails on the VLM step (no local `omlx`/`ollama` endpoint), re-run with
`--skip-vision` and tell the user the visual layer was skipped — the transcript-based
4-beat is still useful, just weaker on the visual beats.

## Step 3 — read the structured output

`analyze` prints the new `video_id`(s). Pull the full record:

```bash
reel-scout show <video_id>
```

`show` prints title / platform / URL / duration / status, the transcript, and the
analysis JSON. To list recent ids: `reel-scout list`. To dump everything for
external use: `reel-scout export --format json -o ./export` (or `--format csv`).
If you ran `--score`, `reel-scout score <video_id>` re-prints the hook/visual/
pacing/structure breakdown.

## Step 4 — apply the reverse-decode prompt pack (the analysis layer)

This is the point of the skill. You now have grounded evidence (transcript + VLM
visual descriptions + structured fields). **Read the prompt pack and apply its
framework — don't free-style a summary.**

```
Read "${CLAUDE_SKILL_DIR}/prompts/hook-reverse-structure.md"
```

Apply the **Liquid Death 4-beat 通用骨架** from that file to the reel-scout output:

1. **Hook (pattern-interrupt)** — what the first few seconds do to make the brain
   keep watching; rate intensity 1-5.
2. **反差介紹 (contrast intro)** — how this clip enters its topic vs. the genre norm;
   what memory anchor the contrast creates.
3. **CTA** — the next action it asks for; rate clarity 1-5 and alignment to the topic.
4. **結尾餘韻 (closing resonance)** — what the last 2-3 seconds leave behind.

Then produce the **transferable骨架** for the user's own topic (their Hook / 反差 /
CTA / 餘韻 by the *same logic*, not by copying lines).

Discipline the prompt pack enforces — keep it:
- **Separate observation from inference.** State what the VLM/transcript actually
  showed vs. what you're guessing. Cite the timestamp for claims.
- **Don't copy金句 or visuals — copy the structural logic.**
- If a beat doesn't transfer to the user's topic, say so and offer an alternative
  structure (per the prompt's audit rules).
- **Pacing and audio are the hallucination-prone beats** — when those matter,
  flag what you're inferring vs. what's grounded in the actual transcript/keyframes
  (see Prompt B's舉證 guardrails in the same file).

Related prompts in `prompts/` for follow-up stages (read on demand):
- `script-breakdown.md` — translate the extracted structure into the user's own shots/pacing
- `focus-audit.md` — gate the user's plan against the one thing they're selling
- `storyboard-visualize.md` — turn the approved plan into generatable storyboard prompts
- `signal-reliability-cheatsheet.md` — the 4-layer signal-reliability model (why caption-only misleads)

## Step 5 — cleanup

reel-scout keeps downloaded videos in its data dir. Per CLAUDE.md, after analysis
**ask the user whether to keep or delete the downloaded videos** rather than deleting
automatically. List paths if they want to remove them by hand.

## Security & Permissions

**What this skill does:**
- Runs `yt-dlp` locally to download the video and pull native captions (public data;
  the request goes to whatever host the URL points at)
- Runs `ffmpeg`/`ffprobe` locally to extract keyframes and audio
- Runs a **local** VLM backend (`omlx`/`ollama`) and a **local** Whisper backend —
  frames and audio stay on the machine; nothing is uploaded to a cloud transcription/
  vision API by default
- Writes a SQLite record + downloaded media to reel-scout's data dir

**What this skill does NOT do:**
- Does not log into any platform account or post anything (a single public Reel URL
  needs no cookies; IG profile *browsing* uses a user-supplied `cookies.txt`)
- Does not introduce new Python dependencies — it only wraps the existing
  `reel-scout` CLI and the `prompts/` pack
- Does not delete downloaded media automatically (Step 5)

**Bundled additions by this skill layer:** `scripts/setup.py` (preflight),
`commands/scout.md` (slash command), plugin manifests. The pipeline itself lives in
`reel_scout/` and the analysis brain in `prompts/` — both unchanged.

Review scripts before first use to verify behavior.
