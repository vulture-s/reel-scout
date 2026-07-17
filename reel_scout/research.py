"""Competitor research across channels (roadmap 4A).

Orchestration: for each channel → list its videos → run the full analyze
pipeline (dedup/resume come free from the batch tables) → aggregate the
normalized tags + scores per channel and niche-wide. PR-E adds the LLM markdown
report on top of the structured aggregate this module produces.

Channel grouping is tracked in memory (channel_url → [video_ids]) at
orchestration time, because there is no channel table — the only DB handle is
the free-text `videos.uploader`, which is too fragile to reconstruct grouping
from after the fact.
"""
from __future__ import annotations

import json as _json
from collections import Counter
from typing import Any, Dict, List, Optional

from . import compare, db
from .llm import get_llm

# Tag fields aggregated per channel / niche (from compare.collect_video + the
# normalized content_structure column).
_TAG_FIELDS = ["content_type", "content_structure", "format", "pacing",
               "opening_type", "cta_type"]
_SCORE_FIELDS = ["overall", "hook_strength", "visual_storytelling", "pacing_score", "structure"]


def expand_channels(channel_urls: List[str], depth: int) -> Dict[str, List[str]]:
    """channel_url → list of video URLs it lists (best effort per channel).

    A channel that can't be listed (unsupported platform, browse failure) maps
    to an empty list rather than aborting the whole run.
    """
    from .crawl import get_crawler, is_profile_url

    mapping: Dict[str, List[str]] = {}
    for url in channel_urls:
        try:
            crawler = get_crawler(url)
            if not is_profile_url(url):
                raise ValueError("not a channel/profile URL: %s" % url)
            entries = crawler.browse(url, limit=depth)
            mapping[url] = [e.url for e in entries if e.url]
        except Exception as e:  # noqa: BLE001 - per-channel resilience
            print("  ! skipping %s: %s" % (url, e))
            mapping[url] = []
    return mapping


def _collect_row(conn: db.sqlite3.Connection, video_id: str) -> Dict[str, Any]:
    """Per-video fields for aggregation: compare.collect_video + content_structure."""
    row = compare.collect_video(conn, video_id)
    analysis = db.get_analysis(conn, video_id)
    row["content_structure"] = analysis["content_structure"] if analysis else None
    return row


def _distribution(rows: List[Dict[str, Any]], field: str) -> Dict[str, int]:
    c = Counter(r[field] for r in rows if r.get(field) is not None)
    return dict(c.most_common())


def _modal(dist: Dict[str, int]) -> Optional[str]:
    return next(iter(dist), None) if dist else None


def _mean(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    analyzed = [r for r in rows if r.get("content_type") or r.get("format")]
    dists = {f: _distribution(rows, f) for f in _TAG_FIELDS}
    scores = {
        f: _mean([r.get(f) for r in rows]) for f in _SCORE_FIELDS
    }
    return {
        "video_count": len(rows),
        "analyzed_count": len(analyzed),
        "modal_format": _modal(dists["format"]),
        "modal_pacing": _modal(dists["pacing"]),
        "modal_structure": _modal(dists["content_structure"]),
        "avg_overall": scores["overall"],
        "distributions": dists,
        "avg_scores": scores,
    }


def aggregate(
    conn: db.sqlite3.Connection,
    channel_to_video_ids: Dict[str, List[str]],
    niche: str,
) -> Dict[str, Any]:
    """Pure aggregation: given channel → [video_ids], build the per-channel and
    niche-wide summary. No network, no LLM — unit-testable."""
    channels: List[Dict[str, Any]] = []
    all_rows: List[Dict[str, Any]] = []
    for channel_url, video_ids in channel_to_video_ids.items():
        rows = [_collect_row(conn, vid) for vid in video_ids]
        all_rows.extend(rows)
        summary = _summarize(rows)
        summary["channel_url"] = channel_url
        # A representative uploader label (most common non-null title-of-channel
        # proxy: the uploader on the videos).
        uploaders = _distribution(
            [{"uploader": db.get_video(conn, v)["uploader"]} for v in video_ids],
            "uploader")
        summary["uploader"] = _modal(uploaders)
        channels.append(summary)

    niche_wide = _summarize(all_rows)
    niche_wide.pop("channel_url", None)
    return {
        "niche": niche,
        "channel_count": len(channel_to_video_ids),
        "channels": channels,
        "niche_wide": niche_wide,
    }


def run_research(
    conn: db.sqlite3.Connection,
    niche: str,
    channel_urls: List[str],
    depth: int,
    llm_backend: Optional[str] = None,
    do_analyze: bool = True,
) -> Dict[str, Any]:
    """Full flow: expand channels → analyze → aggregate. Returns the structured
    aggregate (PR-E renders the markdown report from it)."""
    from .analyze.pipeline import PipelineOptions, run as run_pipeline

    mapping = expand_channels(channel_urls, depth)

    if do_analyze:
        all_urls = [u for urls in mapping.values() for u in urls]
        if all_urls:
            run_pipeline(all_urls, PipelineOptions(score=True))

    # Resolve each channel's URLs to video_ids that actually landed in the DB.
    channel_to_ids: Dict[str, List[str]] = {}
    for channel_url, urls in mapping.items():
        ids: List[str] = []
        for u in urls:
            video = db.get_video_by_url(conn, u)
            if video is not None:
                ids.append(video["id"])
        channel_to_ids[channel_url] = ids

    return aggregate(conn, channel_to_ids, niche)


# --- Markdown report synthesis (PR-E) ---

_REPORT_PROMPT = """You are a short-form video content strategist. Using ONLY the \
aggregated competitor-analysis data below, write a concise markdown report for the \
niche "{niche}".

## Aggregated data (per channel + niche-wide)
{data}

Write markdown with exactly these sections:
# {niche} — Competitor Research
## Common patterns
Which formats, pacing, hook types, content structures and CTAs recur across the \
niche — cite the distributions.
## Differentiation opportunities
Under-used angles and gaps; where high performers (higher avg_overall) differ from \
the rest.
## Content strategy recommendations
3-5 concrete, actionable recommendations, each grounded in the numbers above.

Ground every claim in the data. Output ONLY the markdown report, no preamble."""


def _build_report_prompt(report: Dict[str, Any]) -> str:
    return _REPORT_PROMPT.format(
        niche=report["niche"],
        data=_json.dumps(report, ensure_ascii=False, indent=2),
    )


def _fallback_report(report: Dict[str, Any]) -> str:
    """Deterministic data-only report, used when no LLM is reachable so the
    command still yields something useful instead of erroring."""
    nw = report["niche_wide"]
    lines = ["# %s — Competitor Research" % report["niche"], ""]
    lines.append("_LLM synthesis unavailable — data-only report._\n")
    lines.append("## Niche-wide")
    lines.append("- Channels: %d | videos: %d (analyzed %d)" % (
        report["channel_count"], nw["video_count"], nw["analyzed_count"]))
    lines.append("- Modal format: %s | modal structure: %s | avg overall: %s" % (
        nw["modal_format"], nw["modal_structure"], nw["avg_overall"]))
    for field, dist in nw["distributions"].items():
        if dist:
            lines.append("- %s: %s" % (
                field, ", ".join("%s=%d" % (k, v) for k, v in dist.items())))
    lines.append("\n## Per channel")
    for ch in report["channels"]:
        lines.append("- **%s** (%s): %d videos, modal_format=%s, avg_overall=%s" % (
            ch.get("uploader") or "?", ch["channel_url"],
            ch["video_count"], ch["modal_format"], ch["avg_overall"]))
    return "\n".join(lines)


def render_report(
    report: Dict[str, Any],
    llm_backend: Optional[str] = None,
    max_tokens: int = 2000,
) -> str:
    """Synthesize a markdown report from the structured aggregate. Falls back to
    a deterministic data-only report if the LLM is unreachable/empty.

    Note: a multi-channel report can be large; max_tokens defaults high (2000)
    and omlx/openclaw impose a 120s urllib timeout — feed the aggregate (compact
    structured data), never raw transcripts.
    """
    prompt = _build_report_prompt(report)
    try:
        md = get_llm(llm_backend).complete(prompt, max_tokens=max_tokens, temperature=0.3).strip()
    except Exception as e:  # noqa: BLE001 - any backend failure → data-only report
        print("  ! LLM report synthesis failed (%s); writing data-only report" % e)
        md = ""
    return md or _fallback_report(report)
