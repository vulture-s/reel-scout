"""The indexed tag columns must only ever hold the closed vocabulary.

`ingest` rejects an off-enum value because stats/patterns/compare GROUP BY
these columns and one stray spelling becomes a one-member category in every
aggregate. The local-LLM merge path wrote the model's spelling straight in:
"Question", "talking head", "Educational" each became their own bucket.
"""
import json

from reel_scout import db
from reel_scout.analyze import merger


class _FakeLLM:
    model = "m"

    def __init__(self, reply):
        self.reply = reply

    def complete(self, *a, **k):
        return self.reply


def _merge(conn, monkeypatch, payload):
    vid = db.upsert_video(conn, "youtube", "abc", "https://youtu.be/abc")
    monkeypatch.setattr(merger, "get_llm", lambda *a, **k: _FakeLLM(json.dumps(payload)))
    merger.merge_analysis(conn, vid)
    return db.get_analysis(conn, vid)


def test_case_and_spacing_variants_land_in_the_canonical_bucket(temp_db, monkeypatch):
    conn = db.get_connection()
    row = _merge(conn, monkeypatch, {
        "summary": "x",
        "hook": {"opening_type": "Question", "cta_type": " Follow "},
        "style": {"format": "talking head", "pacing": "FAST"},
        "engagement_signals": {"emotion": "Calm"},
        "content_type": "Educational",
        "content_structure": "Hook Body CTA",
    })
    assert row["opening_type"] == "question"
    assert row["cta_type"] == "follow"
    assert row["style_format"] == "talking_head"
    assert row["style_pacing"] == "fast"
    assert row["emotion"] == "calm"
    assert row["content_type"] == "educational"
    assert row["content_structure"] == "hook-body-cta"


def test_off_vocabulary_value_is_not_indexed_but_full_json_keeps_it(temp_db, monkeypatch):
    conn = db.get_connection()
    row = _merge(conn, monkeypatch, {"summary": "x", "style": {"format": "documentary"}})
    assert row["style_format"] is None
    assert json.loads(row["full_json"])["style"]["format"] == "documentary"
