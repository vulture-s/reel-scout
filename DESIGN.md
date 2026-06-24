# Design: Long-form native-video understanding (hard split from reel-scout)

> **Status**: APPROVED (2026-06-24) — all §8 decisions locked. Ready to build; awaiting go for P1. No code yet.
> **Decision taken**: hard split — long-form native-video becomes its **own repo/tool**, separate
> from reel-scout (which stays short-form and gets the "pro" pipeline). Both **local-first** and
> **provider-agnostic** (local VLM / Codex / Claude / Gemini swappable).
> **Name**: **Longshot** ✅ (Hevin, 2026-06-24) — film term (the long/establishing shot) + long-form pun.

---

## 1. Why split, and what each side owns

reel-scout is optimized for short-form (Shorts/Reels/TikTok): hook/CTA/retention schema, sparse
keyframes, one-clip-at-a-time. Bolting whole-video native ingestion into it muddies that design.
After the split:

| | reel-scout (existing) | Longshot (NEW repo) |
|---|---|---|
| Target | short-form ≤ ~3 min | long-form (talks, ambient, vlogs, lectures) |
| Vision | **pro pipeline** (T1+T2+T4, see §4) | native-video first, contact-sheet fallback |
| Output schema | hook / CTA / 0-3s timeline | chapters / segments / topic arc / A-V structure |
| Strength | virality/structure mining | content/segment understanding & retrieval |

Both keep: crawl, transcribe, audio (PANNs), DB, the **provider-agnostic backend interface**.

---

## 2. The core idea: one provider-agnostic "temporal vision" interface

reel-scout today only has a **single-frame** VLM contract (`BaseVLM.describe_frame(image_path)`).
Long-form (and the pro pipeline) need a **multi-frame / whole-clip** contract. Define a new ABC:

```python
class BaseTemporalVision(abc.ABC):
    @abc.abstractmethod
    def describe_clip(self, clip: ClipPayload) -> SceneAnalysis: ...

@dataclass
class ClipPayload:
    frames: list[Frame]          # (path, timestamp_sec), already selected upstream
    audio_events: list[AudioEvent] | None   # from PANNs, for A-V fusion
    transcript: Transcript | None
    video_path: str | None       # for backends that ingest video natively
    duration_sec: float
    hints: dict                  # preset knobs (granularity, max_sheets, ...)
```

**This is what makes "local-first" and "codex/claude/gemini 通用" the same thing**: every backend
consumes the *same* `ClipPayload`; they differ only in how they render it to their model.

### Backend matrix (all behind the one interface)

| backend | how it ingests | local? | auth | role |
|---|---|---|---|---|
| **local VLM, contact-sheet** (per-machine, see below) | contact-sheet grid image (timestamps burned in) → 1 call | **yes (default)** | none | local-first baseline |
| **gemini-native-video** | upload `video_path`, **native** temporal reasoning | no | API key (OAuth-first: Gemini=key) | best quality on long-form |
| **claude** | contact-sheet image(s) | no | **OpenClaw proxy** (subscription/OAuth, no Anthropic key) | swappable cloud, parity |
| **codex / gpt** | contact-sheet image(s) | no | OpenClaw proxy / Codex runtime | swappable cloud |

**Key distinction**: only **Gemini ingests a raw video file natively**. Claude / Codex / local VLMs
**cannot eat video** — they take **images**, so they run the **contact-sheet** path (frames → grid).
Same `ClipPayload`, different rendering. Native-video is an *optional enhanced* path for backends that
support it — never required, so **local-first always holds**.

### Local backend = per-machine, not one model (verified 2026-06-24)

| machine | RAM | default local VLM | note |
|---|---|---|---|
| **Mac mini M2 Pro** (24h relay hub) | **16 GB** | **minicpm-v** (5.5 GB, already installed) | safe on 16 GB; keep contact-sheets small (≤6–9 cells, modest res). `qwen3-vl:8b` is also installed but balloons to ~10.4 GB resident + can time out on text-dense sheets → too tight while it's also relaying. Light backend, not the workhorse. |
| **MacBook Pro M2 Max** | 32 GB+ | **qwen3-vl:8b** (already installed, newer than Qwen2.5-VL) | the local-first workhorse — full-size sheets, dense frames fine. |
| **PC RTX 4070** | 12 GB VRAM | minicpm-v / llava:7b | per reel-scout README; lean VLM only on 12 GB. |

We do **not** standardise on "Qwen2.5-VL". The mini already runs `minicpm-v` + `qwen3-vl:8b`; M2 Max
runs `qwen3-vl:8b` (supersedes 2.5-VL). Pick per machine; the contact-sheet payload is identical, so
the backend swaps without touching callers. Heavy/long-form local work → M2 Max or Gemini, not the mini.

---

## 3. Shared core vs duplication (the real hard-split cost)

Hard split means two repos but a lot of overlap (crawl/db/transcribe/backends/contact-sheet). Three ways:

- **(A) Extract `scout-core` package** both repos depend on — crawl, transcribe, audio, db, the
  backend interface + adapters, contact-sheet encoder. Cleanest long-term; ~1 day of extraction up front.
- **(B) Longshot copies what it needs** — fastest start, but drift between the two over time.
- **(C) Longshot depends on reel-scout as a library** — couples them; awkward if reel-scout
  internals change.

**Recommendation: (A) shared `scout-core`.** It's the only option where the pro-pipeline upgrades
(contact-sheet, A-V fusion) land *once* and both tools benefit, and a hard split doesn't mean
maintaining two diverging crawlers. (B) is acceptable only if we want a throwaway prototype first.

---

## 4. reel-scout "pro pipeline" (lands in shared core, used by both)

`smart keyframe select (T2) → contact-sheet encode (T1) → temporal-vision describe (local-first, swappable) → audio-visual merge (T4)`

- **T2 select**: PySceneDetect content-cuts + CLIP-embedding dedup → diverse, on-cut frames (replaces fixed-interval).
- **T1 contact-sheet**: stitch N frames (≤ ~12/sheet for legibility) into one timestamped grid → one VLM call (cheaper + temporally coherent vs per-frame siloed captions — fixes the current core weakness).
- **T4 A-V fusion**: align PANNs audio events with frame timeline at merge ("hook lands when beat drops @0:03"). Unlocked now that audio works.
- Short-form vs long-form = **presets** on the same pipeline (keyframe budget, sheets-per-clip, schema).

---

## 5. Longshot specifics (the new repo's differentiator)

- **Native-video backend first** (Gemini), contact-sheet fallback when no key / offline (local-first).
- **Long-form output schema**: chapters/segments (start–end + topic), topic arc, speaker turns
  (reuse pyannote diarize), A-V structure — NOT hook/CTA.
- **Chunking**: very long videos → segment by scene/topic, describe per chunk, then stitch a global arc.
- **Retrieval angle** (later): segment embeddings → "find the moment about X" across a library
  (aligns with the arkiv cross-project-search priority).

---

## 6. Phased plan

1. **P0 (this doc)** — approve direction + name + shared-core choice (A/B/C).
2. **P1 — extract `scout-core`** (if A): move crawl/transcribe/audio/db/backends out of reel-scout.
3. **P2 — temporal-vision interface + contact-sheet (local) backend** in scout-core. Wire into reel-scout = the pro pipeline T1. Verify on a short clip.
4. **P3 — T2 select + T4 A-V fusion** → reel-scout pro pipeline complete.
5. **P4 — Longshot repo**: native-video (Gemini) backend + long-form schema + chunking. Verify on the 1hr ambient + a talk.
6. **P5 — claude/codex adapters** for parity; retrieval later.

---

## 6b. P2 first-run findings (2026-06-24, mini)

First end-to-end run of the contact-sheet → local-VLM backend, on the halfof8 BTS
"I built an app" clip (10 keyframes, 330 s) against the mini's Ollama.

- ✅ **Pipeline works end-to-end**: `ClipPayload → build_contact_sheets → Ollama VLM →
  SceneAnalysis`, parsed cleanly. minicpm-v returned in ~28 s.
- ✅ **Contact-sheet artifact is excellent** (verified by eye): a 10-cell timestamped grid
  that clearly shows the whole video's progression — even surfaced the end-card credit
  *"Original soundtrack by Sasha DZA"* (independently confirms the attribution flag from
  the case study). The substrate is good.
- ⚠️ **minicpm-v reads a DENSE sheet weakly**: on 10 small, text-heavy cells it gave a
  generic "compilation of scenes" summary and parroted the prompt template. Likely the
  model downscales the sheet and loses the small text. Density is the suspected lever
  (fewer, larger cells) — test was cut off when the mini went down (below).
- 🔴 **qwen3-vl:8b is NOT viable on the 16 GB mini**: the request timed out (>400 s) AND
  left the mini unresponsive (SSH + Ollama both down — 16 GB exhausted, swap death).
  Confirms §2's per-machine call: **qwen3-vl → M2 Max only; mini = minicpm-v, light loads**.

**Conclusions / next**: plumbing proven; quality is a model+density question, not an
architecture one. To prove a *good* read: (a) sparse-sheet preset on minicpm-v (few cells),
(b) qwen3-vl on the M2 Max (where it fits), or (c) a cloud backend (Claude/Codex via proxy)
on the same sheet. Do NOT run heavy VLMs on the mini.

## 7. Law Phase

- **Acceptance**: (a) one `BaseTemporalVision` interface with ≥2 working backends (local contact-sheet
  + one cloud); (b) reel-scout short-form runs through the new pipeline with quality ≥ current per-frame;
  (c) Longshot produces a chaptered analysis of a 1hr video; (d) no network needed for the default path.
- **Red lines**: never break reel-scout's existing short-form output; local-first default (no mandatory
  cloud); API keys via env only (Gemini per OAuth-first: API key OK); no secrets in code.
- **Evidence**: side-by-side per-frame-vs-contact-sheet on the same short clip; 1hr long-form chaptered run;
  backend-swap test (same clip, local vs cloud) producing comparable structure.

---

## 8. Decisions

1. **Shared-core strategy**: **A — extract `scout-core`** ✅ (Hevin, 2026-06-24).
2. **New repo name**: **Longshot** ✅ (Hevin, 2026-06-24).
3. **Backends** ✅: local-first default = **per-machine** contact-sheet VLM (mini→minicpm-v / M2 Max→qwen3-vl:8b
   / 4070→minicpm-llava — verified 2026-06-24, see §2 table). Gemini = native-video enhanced path (API key).
   Claude / Codex = contact-sheet via OpenClaw proxy (no Anthropic key, no Gemini CLI). Native-video is
   Gemini-only for now; everything else = contact-sheet. Not standardising on Qwen2.5-VL.
