"""Find sounds by describing them: text -> CLAP text embedding -> cosine over every window.

``search(conn, "door slam")`` ranks the stored 10 s windows (``audio_clap_windows``)
by cosine similarity to the query and returns the best ones with their clip and
seconds. ``per_video=True`` keeps one hit per clip and widens it over the
neighbouring windows that score nearly as well (so "the typing runs 0:20-0:45"
comes back as one span, not five overlapping windows).

## Chinese (and any CJK) queries are translated first, visibly

CLAP's text tower only learned English. A Chinese query encoded as-is does not
fail -- it returns a ranking, confidently, that has nothing to do with the
words. So a query containing CJK is first translated to English by the repo's
own LLM backend (``LLM_BACKEND`` / ``LLM_MODEL``, the same client the merger
uses), and the English that was actually searched is returned beside the
results. If translation fails, or no LLM is reachable, the search fails with
that reason: it never falls back to embedding the original text.

Scores are raw cosines. They rank within one query; they are not
probabilities and are not comparable across queries.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from . import clap

#: Neighbouring windows scoring within this much of a clip's best window are
#: folded into its span when ``per_video`` is on.
MERGE_MARGIN = 0.03

_CJK = re.compile(u"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")

TRANSLATE_PROMPT = (
    "Translate this description of a sound into a short English phrase for an "
    "audio search engine, in the style 'a door slamming' or 'keyboard typing'. "
    "Output ONLY the English phrase -- no quotes, no notes, no alternatives.\n\n%s"
)


class TranslationFailed(RuntimeError):
    """A CJK query could not be turned into English, so it was not searched."""


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


def _clean_translation(reply: str) -> str:
    lines = [ln.strip() for ln in (reply or "").strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    out = lines[0]
    out = re.sub(r"^(english|translation)\s*[:：]\s*", "", out, flags=re.I)
    return out.strip().strip("\"'`“”‘’「」").strip().rstrip(".")


def translate_query(query: str, llm: Any = None) -> str:
    """English for a CJK sound query, via the configured LLM. Raises TranslationFailed."""
    from .. import config

    if llm is None:
        try:
            from ..llm import get_llm

            llm = get_llm()
        except Exception as e:  # noqa: BLE001 — any backend error is the same outcome
            raise TranslationFailed(
                "query %r is not English and CLAP only reads English; no LLM to "
                "translate it (LLM_BACKEND=%s): %s" % (query, config.LLM_BACKEND, e))
    try:
        reply = llm.complete(TRANSLATE_PROMPT % query, max_tokens=60, temperature=0.0)
    except Exception as e:  # noqa: BLE001
        raise TranslationFailed(
            "query %r is not English and CLAP only reads English; translating it "
            "with LLM_BACKEND=%s failed: %s" % (query, config.LLM_BACKEND, e))
    out = _clean_translation(reply)
    if not out or has_cjk(out):
        raise TranslationFailed(
            "query %r: the LLM's translation was unusable (%r); not searching the "
            "untranslated text" % (query, (reply or "")[:120]))
    return out


def _load_index(conn: Any, revision: str):
    np = clap._require_numpy()
    rows = conn.execute(
        "SELECT w.video_id, w.idx, w.start_s, w.end_s, w.emb FROM audio_clap_windows w "
        "JOIN audio_clap c ON c.video_id = w.video_id "
        "WHERE c.revision = ? ORDER BY w.video_id, w.idx", (revision,)).fetchall()
    if not rows:
        return [], np.zeros((0, clap.DIM), np.float32)
    meta = [(r[0], int(r[1]), float(r[2]), float(r[3])) for r in rows]
    mat = np.stack([clap.blob_to_emb(r[4]) for r in rows]).astype(np.float32)
    return meta, mat


def rank(meta: List[Any], mat: Any, qv: Any, top: int = 10,
         per_video: bool = False) -> List[Dict[str, Any]]:
    """Top hits for one L2-normalised query vector over (meta, window matrix)."""
    np = clap._require_numpy()
    if not meta:
        return []
    scores = mat @ np.asarray(qv, np.float32).reshape(-1)
    order = np.argsort(-scores, kind="stable")
    if not per_video:
        return [{"video_id": meta[i][0], "window": meta[i][1], "start_s": meta[i][2],
                 "end_s": meta[i][3], "score": round(float(scores[i]), 4)}
                for i in order[:top]]
    # one hit per clip: its best window, widened over adjacent near-equal windows
    by_pos = {(m[0], m[1]): j for j, m in enumerate(meta)}
    seen = set()
    out: List[Dict[str, Any]] = []
    for i in order:
        vid = meta[i][0]
        if vid in seen:
            continue
        seen.add(vid)
        best = float(scores[i])
        lo = hi = meta[i][1]
        while (vid, lo - 1) in by_pos and float(scores[by_pos[(vid, lo - 1)]]) >= best - MERGE_MARGIN:
            lo -= 1
        while (vid, hi + 1) in by_pos and float(scores[by_pos[(vid, hi + 1)]]) >= best - MERGE_MARGIN:
            hi += 1
        out.append({"video_id": vid, "window": meta[i][1],
                    "start_s": meta[by_pos[(vid, lo)]][2], "end_s": meta[by_pos[(vid, hi)]][3],
                    "windows_merged": hi - lo + 1, "score": round(best, 4)})
        if len(out) >= top:
            break
    return out


def search(conn: Any, query: str, top: int = 10, per_video: bool = False,
           model: Any = None, llm: Any = None,
           translator: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
    """Rank indexed windows against a text query.

    Returns {"query", "query_en", "translated", "results", "indexed_windows",
    "indexed_videos"}; ``query_en`` is what CLAP actually read.
    """
    query = (query or "").strip()
    if not query:
        raise ValueError("empty query")
    translated = False
    query_en = query
    if has_cjk(query):
        query_en = translator(query) if translator else translate_query(query, llm=llm)
        translated = True
    meta, mat = _load_index(conn, clap.MODEL_REVISION)
    out: Dict[str, Any] = {
        "query": query, "query_en": query_en, "translated": translated,
        "indexed_windows": len(meta),
        "indexed_videos": len({m[0] for m in meta}),
        "results": [],
    }
    if not meta:
        return out
    m = model or clap.load()
    qv = m.embed_text([query_en])[0]
    results = rank(meta, mat, qv, top=top, per_video=per_video)
    if results:
        ids = sorted({r["video_id"] for r in results})
        titles = {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT id, title, url FROM videos WHERE id IN (%s)" % ",".join("?" * len(ids)),
            ids).fetchall()}
        for r in results:
            t = titles.get(r["video_id"])
            r["title"] = t[0] if t else None
            r["url"] = t[1] if t else None
    out["results"] = results
    return out
