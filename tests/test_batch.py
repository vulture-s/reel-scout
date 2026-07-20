"""`reel-scout batch` — a doc full of links, one bundle each.

Two properties carry the weight here. First, a machine without a VLM must **stop
and ask** rather than quietly produce transcript-only bundles: silent degradation
is how the craft score goes missing without anyone noticing. Second, an entry is
only ever paired with a video it definitely produced — handing one person's
analysis to another is the worst outcome this command has.
"""
from __future__ import annotations

import pytest

from reel_scout import batch


# --- capability -> mode ------------------------------------------------------

def test_a_reachable_vlm_makes_full_unambiguous():
    """Nothing to choose when the machine can do everything."""
    assert batch.resolve_mode(None, {"vlm": True, "whisper": True}) == ("full", "")


def test_no_vlm_refuses_to_pick_for_the_user():
    mode, msg = batch.resolve_mode(None, {"vlm": False, "whisper": True})
    assert mode is None
    for expected in ("--mode agent", "--mode transcript", "--mode full"):
        assert expected in msg
    assert "not an error" in msg


def test_no_vlm_does_not_silently_fall_back_to_transcript():
    """The regression that matters: quietly dropping the visual layer + score."""
    mode, _ = batch.resolve_mode(None, {"vlm": False, "whisper": True})
    assert mode != "transcript"


def test_asking_for_full_without_a_vlm_is_refused_with_the_fix():
    mode, msg = batch.resolve_mode("full", {"vlm": False, "whisper": True})
    assert mode is None
    assert "ollama serve" in msg or "--mode agent" in msg


@pytest.mark.parametrize("mode", ["agent", "transcript"])
def test_explicit_modes_are_honoured_without_a_vlm(mode):
    assert batch.resolve_mode(mode, {"vlm": False, "whisper": False}) == (mode, "")


def test_unknown_mode_lists_the_valid_ones():
    mode, msg = batch.resolve_mode("turbo", {"vlm": True, "whisper": True})
    assert mode is None
    assert "agent" in msg and "transcript" in msg


# --- pairing safety ----------------------------------------------------------

class _Cur:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, ids, urlmap=None):
        self.ids, self.urlmap = ids, urlmap or {}

    def execute(self, sql, params=()):
        if "WHERE url" in sql:
            vid = self.urlmap.get(params[0])
            return _Cur({"id": vid} if vid else None)
        return [(i,) for i in self.ids]


def test_exactly_one_new_row_is_the_one_we_just_made():
    assert batch.resolve_video_id(_Conn({"a", "b"}), {"a"}, "u") == "b"


def test_two_new_rows_refuses_to_guess():
    assert batch.resolve_video_id(_Conn({"a", "b", "c"}), {"a"}, "u") is None


def test_already_analyzed_falls_back_to_an_exact_url_match():
    assert batch.resolve_video_id(_Conn({"a"}, {"u": "z"}), {"a"}, "u") == "z"


def test_tracking_parameters_that_break_url_equality_refuse_to_guess():
    assert batch.resolve_video_id(_Conn({"a"}), {"a"}, "u") is None


# --- parsing -----------------------------------------------------------------

FORM_CSV = (
    "時間戳記,姓名,連結,問題\n"
    "2026/08/01 9:15,陳小明,https://www.instagram.com/reel/AAA111/?igsh=track,開頭\n"
    "2026/08/01 9:22,Amy Wu,https://www.tiktok.com/@x/video/7401234567890123456,節奏\n"
    "2026/08/01 9:40,陳小明,https://www.instagram.com/reel/AAA111/?igsh=track,重複\n"
)

FREE_TEXT = """我想拆的片
王美麗 https://www.instagram.com/reel/BBB222/
張阿強 — https://vt.tiktok.com/ZSJqwerty/
(還沒填)
Kevin Chen：https://youtu.be/ccc333
"""


def test_csv_reads_the_label_column_not_the_form_timestamp():
    assert [n for n, _ in batch.parse_rows(FORM_CSV)] == ["陳小明", "Amy Wu"]


def test_the_same_link_twice_runs_once():
    assert len(batch.parse_rows(FORM_CSV)) == 2


def test_free_text_takes_whatever_precedes_the_link():
    assert [n for n, _ in batch.parse_rows(FREE_TEXT)] == ["王美麗", "張阿強", "Kevin Chen"]


def test_links_the_pipeline_cannot_ingest_are_left_alone():
    text = ("a https://drive.google.com/file/d/abc/view\n"
            "b https://www.youtube.com/watch?v=longform\n"
            "c https://www.instagram.com/reel/CCC444/\n")
    assert [u for _, u in batch.parse_rows(text)] == [
        "https://www.instagram.com/reel/CCC444/"]


def test_an_unlabelled_link_still_counts():
    assert batch.parse_rows("https://www.instagram.com/reel/DDD555/\n") == [
        ("", "https://www.instagram.com/reel/DDD555/")]


# --- google export endpoints -------------------------------------------------

@pytest.mark.parametrize("src,want", [
    ("https://docs.google.com/document/d/1AbC-dEf/edit?usp=sharing",
     "https://docs.google.com/document/d/1AbC-dEf/export?format=txt"),
    ("https://docs.google.com/spreadsheets/d/9XyZ_123/edit#gid=0",
     "https://docs.google.com/spreadsheets/d/9XyZ_123/export?format=csv"),
    ("https://example.com/list.txt", "https://example.com/list.txt"),
])
def test_an_ordinary_edit_link_becomes_a_no_auth_export_link(src, want):
    assert batch.export_url(src) == want


# --- output naming -----------------------------------------------------------

@pytest.mark.parametrize("label,idx,want", [
    ("陳小明", 1, "陳小明"),
    ("Amy Wu", 2, "Amy-Wu"),
    ("", 3, "clip-03"),
    ("林大華 (學員)", 4, "林大華-學員"),
    ("王/美/麗", 5, "王美麗"),
])
def test_slugify_keeps_cjk_and_drops_path_separators(label, idx, want):
    assert batch.slugify(label, idx) == want
