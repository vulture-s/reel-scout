# Reel Scout — Reverse-Decode Prompt Pack

The **default analysis layer**. Reel Scout's pipeline gets clean input into a model
(download → transcript → keyframes → structured fields); these prompts are the
*brain* you point at that input to reverse-engineer **why a short-form video works**
and extract a **transferable structure**, not just copy its lines.

Open (MIT). Authored by Hevin (vulture.s).

## The prompts

| File | Stage | Use |
|---|---|---|
| [`hook-reverse-structure.md`](./hook-reverse-structure.md) | Research | Pull the 4-beat skeleton (Hook → contrast → CTA → resonance) from a viral reel. Includes a screen-recording variant with anti-hallucination guardrails (observation vs. inference, cite-your-evidence). |
| [`script-breakdown.md`](./script-breakdown.md) | Plan | Translate the extracted structure into your own topic's shots / pacing / point-of-view. |
| [`focus-audit.md`](./focus-audit.md) | Gate | Check your own plan stays aligned to the one thing you're selling — before you shoot. |
| [`storyboard-visualize.md`](./storyboard-visualize.md) | Execute | Turn the approved plan into generatable storyboard prompts. |
| [`signal-reliability-cheatsheet.md`](./signal-reliability-cheatsheet.md) | Reference | The 4-layer signal-reliability model — why caption/handle alone misleads, and which evidence to trust. |

Order: **hook-reverse (research) → script-breakdown (plan) → focus-audit (gate) → storyboard-visualize (execute)**.

## Why this matters

A capable model reading raw frames + transcript still hallucinates structure when
asked open-ended. These prompts force it to separate what it *saw* from what it
*guessed*, cite timestamps, and produce a structure you can transfer — which is the
actual job, not a one-line summary.
