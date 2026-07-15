# Reel Scout — Agent Instructions

## Project Overview
Short-form video analysis CLI tool. Crawls YT Shorts / IG Reels / TikTok via yt-dlp, transcribes with Whisper, analyzes visuals with VLM, and outputs structured JSON.

## Constraints
- **Python 3.9 strict** — no match/case, no walrus in complex expr, no 3.10+ syntax
- All files must have `from __future__ import annotations`
- Use `typing.Optional`, `typing.List`, `typing.Dict` (not `list[str]`, `dict[str, X]`)
- HTTP calls use `urllib.request`, not `requests`
- No hardcoded IPs, API keys, or passwords
- Tests use `pytest`; run `pytest -v` to verify

## Before you build
Grep for the thing first — several subsystems already exist and are easy to
miss. `browse` (channel listing), `is_profile_url()`, and the `openclaw` LLM
backend all shipped before anything referenced them.

## Where things are
- `docs/roadmap.md` — what's built vs. planned, and the reasoning behind the
  non-goals. Verified line-by-line against the code (2026-07-15), so trust it
  over your assumptions — but re-verify before citing it as evidence.
- `docs/video-analyzer-research.md` — comparison against byjlw/video-analyzer;
  design rationale for the frame-sampling and output-schema choices.
- `prompts/` — the creative-analysis prompt pack (SKILL.md reads these).
  Public-facing: **no client names, no real engagements** in examples.
- `README.md` / `README.zh.md` — user-facing docs.

## Scope
Public repo. Internal task-tracking, handover notes, and review verdicts do
**not** live here.
