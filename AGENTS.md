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

## Bug classes that keep coming back (and the test that catches the next one)
Each of these has shipped more than once. Before you add a subcommand, a server
route, a subprocess call or a batch step, check the matching test still passes
-- most are structural (they enumerate the code), so new code is covered too.

1. **Failure exits 0.** A handler prints `Error:` / `Video not found` and returns
   None, and `batch` (which trusts rc alone) records it as done.
   `tests/test_cli_failure_exit_codes.py` walks the real argparse tree; a new
   subcommand must get a failing invocation or a written exemption. Known rc-0
   handlers are a shrink-only ratchet (`KNOWN_RC0`). Every `self_cmd(...)` step
   in `batch.py` must be outside it.
2. **Bad input treated as data.** Unusable LLM replies, an all-failed VLM layer,
   or `status=invalid` rows flowing into scores/averages/exports.
   `tests/test_llm_reply_honesty.py`, `tests/test_vision_down_no_merge.py`,
   `tests/test_research.py`, `tests/test_transcript_keeps_status.py`.
3. **Localhost writes without an Origin/Host check** (CSRF, DNS rebinding).
   `tests/test_http_write_guard_structural.py` requires every non-GET `do_X` in
   any `BaseHTTPRequestHandler` to call `inspector.write_refusal` first;
   behaviour per route: `tests/test_inspector_csrf.py`.
4. **URL becomes an option** in a child argv. Every URL in an argv must follow
   `"--"`: `tests/test_argv_url_double_dash_structural.py`,
   `tests/test_low_hardening.py`.
5. **Keying by something that is reused** (a "new" row another process added, a
   label/slug shared by two reels, a local path re-exported, a model label
   overriding a human one). `tests/test_batch_liveness.py`,
   `tests/test_storyboard_export.py` (slug and same-path cases: open #199, #200).
6. **Units and formats** -- sample rate (PANNs wants 32 kHz:
   `tests/test_panns_sample_rate.py`), path rewriting
   (`tests/test_ffprobe_bin.py`).

## Scope
Public repo. Internal task-tracking, handover notes, and review verdicts do
**not** live here.
