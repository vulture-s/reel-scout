---
description: Reverse-decode a short-form video (IG Reel / TikTok / YouTube Short). Downloads + transcribes + visually analyzes it with the local reel-scout pipeline, then applies the reverse-decode prompt pack to extract the 4-beat skeleton and a transferable structure.
argument-hint: <video-url> [my-topic / question]
allowed-tools: [Bash, Read]
---

Invoke the `reel-scout` skill (defined in SKILL.md) with the user's arguments: $ARGUMENTS

Follow the skill's full pipeline: Step 0 preflight (`scripts/setup.py --check`) → `reel-scout analyze "<url>"` → `reel-scout show <video_id>` → Read `prompts/hook-reverse-structure.md` and apply the 4-beat reverse-decode framework to the grounded transcript + VLM output → produce the transferable骨架 for the user's topic.

Honor the surface tiers (SKILL.md "Surface limits"), and say which one you used:

- **L2** — local shell + ffmpeg/yt-dlp/python + a reachable VLM backend: run the pipeline as above.
- **L1** — shell and binaries present but **no local VLM**: re-run with `--skip-vision`, then follow SKILL.md **Step 2b** — read the keyframes off disk yourself, and write your descriptions and rubric score back with `reel-scout ingest vision|score ... --model <you>`. Do **not** drop to Prompt B here and do **not** hand back a transcript-only result as if it were the whole analysis.
- **L0** — claude.ai web (no shell, no binaries): route to Prompt B (screen-recording variant) in `prompts/hook-reverse-structure.md` instead of pretending the automated extraction works.

If the user provided no URL, ask them for a short-form video URL before proceeding.
