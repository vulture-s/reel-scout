---
description: Reverse-decode a short-form video (IG Reel / TikTok / YouTube Short). Downloads + transcribes + visually analyzes it with the local reel-scout pipeline, then applies the reverse-decode prompt pack to extract the 4-beat skeleton and a transferable structure.
argument-hint: <video-url> [my-topic / question]
allowed-tools: [Bash, Read]
---

Invoke the `reel-scout` skill (defined in SKILL.md) with the user's arguments: $ARGUMENTS

Follow the skill's full pipeline: Step 0 preflight (`scripts/setup.py --check`) → `reel-scout analyze "<url>"` → `reel-scout show <video_id>` → Read `prompts/hook-reverse-structure.md` and apply the 4-beat reverse-decode framework to the grounded transcript + VLM output → produce the transferable骨架 for the user's topic.

Honor the surface limit: the download/VLM/transcribe pipeline only runs where there's a local shell + ffmpeg/yt-dlp/python + a local VLM backend (Claude Code / Codex). On claude.ai web, route to Prompt B (screen-recording variant) in `prompts/hook-reverse-structure.md` instead of pretending the automated extraction works.

If the user provided no URL, ask them for a short-form video URL before proceeding.
