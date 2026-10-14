"""inspire real-name guard: extract names from the analysis, check, re-ask, report.

2026-10-14 Hevin: renaming the tool in a variant must go to 0. The prompt rule
(#210) got E-group (h2e-Me48tHI, no angle) from 6/10 to 2/10; this checks the
answer and re-asks. A run that still fails is reported as failed -- never
returned as if it were clean.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from typing import List
from unittest.mock import patch

import pytest

from reel_scout import cli, db, inspire, name_guard

# Shape of the real h2e-Me48tHI analysis (the one qwen2.5:14b kept renaming).
_WHATSUB = {
    "summary": "一位創作者介紹了一個他花了半年時間開發的自動上字幕網站What'Sub，並詳細演示了該網站的功能和優點。",
    "topics": ["自動上字幕", "影片編輯", "創作者工具"],
    "timeline": [{"timestamp": "0.1-32s", "event": "介紹自己並展示開發的自動上字幕網站What'Sub"}],
    "hook": {"opening_type": "statement",
             "opening_text": "我花了半年 獨自一人 開發了一個 字幕網站 它的名字叫做... What'Sub",
             "cta_type": "visit", "cta_text": "快去試試看"},
    "style": {"format": "talking_head", "pacing": "medium"},
    "engagement_signals": {"spoken_language": "zh-Hant", "emotion": "enthusiastic"},
    "content_structure": "hook-body-cta",
    "measured": {"cuts_per_minute": 5.95},
}


def _good(name: str = "What'Sub") -> str:
    return json.dumps({
        "titles": ["半年做出 %s：自動上字幕" % name, "一個人開發字幕網站", "字幕不用再手打"],
        "hook_script": "我一個人做了 %s" % name,
        "structure_outline": ["beat 1: 痛點", "beat 2: 示範", "beat 3: CTA 快去試試"],
        "recommended_length_sec": 45,
        "rationale": "沿用 hook-body-cta；跳切（Jump Cut）節奏",
    }, ensure_ascii=False)


_RENAMED = _good("SubEase")


class FakeLLM:
    """Scripted replies; records every prompt it was sent."""

    def __init__(self, replies: List[str]) -> None:
        self.replies = list(replies)
        self.prompts: List[str] = []

    def complete(self, prompt, max_tokens=600, temperature=0.7):
        self.prompts.append(prompt)
        return self.replies[min(len(self.prompts), len(self.replies)) - 1]


@pytest.fixture
def whatsub_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    vid = db.upsert_video(conn, platform="youtube", platform_id="h2e",
                          url="https://youtube.com/watch?v=h2e", title="What'Sub", duration_sec=826.0)
    db.save_analysis(conn, vid, summary=_WHATSUB["summary"], topics_json="[]", hooks_json="{}",
                     style_json="{}", engagement_signals_json="{}",
                     full_json=json.dumps(_WHATSUB, ensure_ascii=False))
    try:
        yield conn, vid
    finally:
        conn.close()
        os.unlink(path)


def _run(conn, vid, replies, **kw):
    llm = FakeLLM(replies)
    with patch("reel_scout.inspire.get_llm", return_value=llm):
        data = inspire.generate_inspiration(conn, vid, **kw)
    return data, llm


# ---------------------------------------------------------------- extraction

def test_extracts_the_tool_name_and_not_the_enums():
    assert name_guard.extract_entities(_WHATSUB) == ["What'Sub"]


@pytest.mark.parametrize("word", ["What'Sub", "Let'Sub", "DaVinci", "iPhone", "SubEase",
                                  "FX3", "A7S3", "GEV", "ASTRA", "TikTok", "What’Sub"])
def test_name_shaped_words(word):
    assert name_guard.is_name_like(word)


@pytest.mark.parametrize("word", ["Sony", "Jump", "Cut", "Dynamic", "Range", "talking", "zh",
                                  "Hant", "CTA", "POV", "AI", "UI", "4K", "1080p", "60fps", "30s",
                                  "2026", "the"])
def test_not_name_shaped(word):
    assert not name_guard.is_name_like(word)


def test_extraction_covers_book_title_marks_and_latin_names_in_any_field():
    analysis = {
        "summary": "用 Sony FX3 拍《我的世界》實況，剪輯在 DaVinci Resolve 18",
        "topics": ["GEV外掛", "〈開箱〉"],
        "hook": {"opening_type": "ASTRA"},      # enum key: never scanned
        "engagement_signals": {"spoken_language": "zh-Hant"},
    }
    got = name_guard.extract_entities(analysis)
    assert got == ["《我的世界》", "《開箱》", "FX3", "DaVinci", "GEV"]
    # keys are never names
    assert name_guard.extract_entities({"WhatSub": "普通文字"}) == []


def test_check_finds_missing_and_invented():
    known = json.dumps(_WHATSUB, ensure_ascii=False)
    renamed = json.loads(_RENAMED)
    assert name_guard.check(["What'Sub"], known, renamed) == {"missing": ["What'Sub"], "invented": ["SubEase"]}
    assert name_guard.check(["What'Sub"], known, json.loads(_good())) == {"missing": [], "invented": []}
    # spelling variants of the real name are the same name
    assert name_guard.check(["What'Sub"], known, {"titles": ["WhatSub 上字幕", "what’sub"]})["missing"] == []
    # a gloss in the zh-TW style is not an invented name
    assert name_guard.check([], "", {"rationale": "動態範圍（Dynamic Range）"})["invented"] == []


def test_angle_may_introduce_names(whatsub_db):
    conn, vid = whatsub_db
    reply = _good().replace("CTA 快去試試", "CTA 改用 FX3 拍")
    data, llm = _run(conn, vid, [reply], angle="for Sony FX3 owners")
    assert data["name_check"]["status"] == "passed"
    assert data["name_check"]["mode"] == "angle"
    assert len(llm.prompts) == 1


# ---------------------------------------------------------------- retry loop

def test_passes_first_time_no_reask(whatsub_db):
    conn, vid = whatsub_db
    data, llm = _run(conn, vid, [_good()])
    assert len(llm.prompts) == 1
    check = data["name_check"]
    assert check["status"] == "passed" and check["attempts"] == 1
    assert check["entities"] == ["What'Sub"]
    assert "warning" not in data
    assert "What'Sub" in data["titles"][0]


def test_reask_then_pass(whatsub_db):
    conn, vid = whatsub_db
    data, llm = _run(conn, vid, [_RENAMED, _good()])
    assert len(llm.prompts) == 2
    # the re-ask names exactly what was wrong
    second = llm.prompts[1]
    assert second.startswith(llm.prompts[0])
    assert "## Your previous answer was rejected (real names)" in second
    tail = second[len(llm.prompts[0]):]
    assert "missing or were replaced" in tail and "What'Sub" in tail
    assert "do not exist in the analysis" in tail and "SubEase" in tail
    check = data["name_check"]
    assert check["status"] == "passed" and check["attempts"] == 2
    assert check["history"][0] == {"attempt": 1, "missing": ["What'Sub"], "invented": ["SubEase"]}
    assert "SubEase" not in json.dumps(data["titles"], ensure_ascii=False)
    assert "warning" not in data


def test_reask_still_failing_is_reported_not_hidden(whatsub_db):
    conn, vid = whatsub_db
    data, llm = _run(conn, vid, [_RENAMED, _RENAMED, _RENAMED, _good()])
    assert len(llm.prompts) == 3            # 1 + default 2 retries, then stop
    check = data["name_check"]
    assert check["status"] == "failed"
    assert check["attempts"] == 3 and check["max_retries"] == 2
    assert check["missing"] == ["What'Sub"] and check["invented"] == ["SubEase"]
    assert "FAILED" in data["warning"] and "SubEase" in data["warning"] and "What'Sub" in data["warning"]
    rendered = inspire.format_inspiration(data)
    assert "real-name check FAILED" in rendered


def test_best_attempt_is_returned_when_all_fail(whatsub_db):
    conn, vid = whatsub_db
    two_bad = _good("SubEase").replace("一個人開發字幕網站", "一個人開發 VidCaption")
    data, _llm = _run(conn, vid, [two_bad, _RENAMED, two_bad])
    # attempt 2 had fewer problems than 1 and 3
    assert data["name_check"]["status"] == "failed"
    assert data["name_check"]["invented"] == ["SubEase"]
    assert "VidCaption" not in json.dumps(data, ensure_ascii=False).split('"history"')[0]


def test_retry_count_is_configurable(whatsub_db, monkeypatch):
    conn, vid = whatsub_db
    _data, llm = _run(conn, vid, [_RENAMED], name_retries=0)
    assert len(llm.prompts) == 1
    monkeypatch.setattr(inspire.config, "INSPIRE_NAME_RETRIES", 4)
    data, llm = _run(conn, vid, [_RENAMED])
    assert len(llm.prompts) == 5 and data["name_check"]["max_retries"] == 4
    with pytest.raises(ValueError):
        _run(conn, vid, [_good()], name_retries=-1)


def test_non_json_reply_is_checked_too(whatsub_db):
    conn, vid = whatsub_db
    data, llm = _run(conn, vid, ["sorry, here: SubEase is great", "plain text about What'Sub"])
    assert len(llm.prompts) == 2
    assert data["name_check"]["status"] == "passed"
    assert data["raw"] == "plain text about What'Sub"


def test_cli_exit_code_and_stderr_on_failure(temp_db, capsys):
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    vid = db.upsert_video(conn, platform="youtube", platform_id="h2e",
                          url="https://youtube.com/watch?v=h2e", title="x", duration_sec=1.0)
    db.save_analysis(conn, vid, summary="s", topics_json="[]", hooks_json="{}", style_json="{}",
                     engagement_signals_json="{}", full_json=json.dumps(_WHATSUB, ensure_ascii=False))
    conn.close()
    with patch("reel_scout.inspire.get_llm", return_value=FakeLLM([_RENAMED])):
        with pytest.raises(SystemExit) as exc:
            cli.main(["inspire", "--based-on", vid[:8], "--name-retries", "1", "--json"])
    assert exc.value.code == 3
    out, err = capsys.readouterr()
    assert json.loads(out)["name_check"]["status"] == "failed"
    assert "real-name check FAILED" in err
    with patch("reel_scout.inspire.get_llm", return_value=FakeLLM([_good()])):
        rc = None
        try:
            cli.main(["inspire", "--based-on", vid[:8]])
        except SystemExit as e:  # main may exit 0 explicitly
            rc = e.code
    assert rc in (None, 0)


# ---------------------------------------------------------------- mode by angle
# Hevin 2026-10-14 (after #211's D group): with an angle the variant is a
# different video, so a source name may drop out -- only a name from nowhere
# fails. With no angle the check stays strict (missing + invented).

_NO_NAME = json.dumps({
    "titles": ["攝影師的字幕流程", "拍完就上字幕", "三步出片"],
    "hook_script": "拍完素材，字幕怎麼辦？",
    "structure_outline": ["beat 1: 痛點", "beat 2: 示範", "beat 3: CTA"],
    "recommended_length_sec": 45,
    "rationale": "跳切（Jump Cut）節奏",
}, ensure_ascii=False)


def test_mode_for():
    assert name_guard.mode_for("") == name_guard.MODE_STRICT
    assert name_guard.mode_for("   ") == name_guard.MODE_STRICT
    assert name_guard.mode_for("photography") == name_guard.MODE_ANGLE


def test_check_in_angle_mode_ignores_missing_but_reports_it():
    known = json.dumps(_WHATSUB, ensure_ascii=False)
    got = name_guard.check(["What'Sub"], known, json.loads(_NO_NAME), name_guard.MODE_ANGLE)
    assert got == {"missing": [], "invented": [], "dropped": ["What'Sub"]}
    got = name_guard.check(["What'Sub"], known, json.loads(_RENAMED), name_guard.MODE_ANGLE)
    assert got == {"missing": [], "invented": ["SubEase"], "dropped": ["What'Sub"]}
    # strict is the default and unchanged
    assert name_guard.check(["What'Sub"], known, json.loads(_NO_NAME))["missing"] == ["What'Sub"]
    with pytest.raises(ValueError):
        name_guard.check([], "", {}, "lenient")


def test_angle_missing_name_passes(whatsub_db):
    conn, vid = whatsub_db
    data, llm = _run(conn, vid, [_NO_NAME, _good()], angle="photography")
    assert len(llm.prompts) == 1                      # no re-ask for a dropped name
    check = data["name_check"]
    assert check["status"] == "passed"
    assert check["mode"] == "angle" and check["checks"] == ["invented"]
    assert check["missing"] == [] and check["dropped"] == ["What'Sub"]
    assert "warning" not in data


def test_angle_invented_name_is_reasked(whatsub_db):
    conn, vid = whatsub_db
    data, llm = _run(conn, vid, [_RENAMED, _NO_NAME], angle="photography")
    assert len(llm.prompts) == 2
    tail = llm.prompts[1][len(llm.prompts[0]):]
    assert "SubEase" in tail and "do not exist in the analysis" in tail
    assert "missing or were replaced" not in tail     # angle mode never asks for the dropped name
    check = data["name_check"]
    assert check["status"] == "passed" and check["mode"] == "angle" and check["attempts"] == 2
    assert check["history"][0]["invented"] == ["SubEase"]


def test_angle_invented_name_still_fails_when_never_fixed(whatsub_db):
    conn, vid = whatsub_db
    data, llm = _run(conn, vid, [_RENAMED], angle="photography")
    assert len(llm.prompts) == 3
    check = data["name_check"]
    assert check["status"] == "failed" and check["mode"] == "angle"
    assert check["invented"] == ["SubEase"] and check["missing"] == []
    assert "SubEase" in data["warning"] and "missing/replaced" not in data["warning"]


def test_no_angle_missing_name_is_reasked(whatsub_db):
    conn, vid = whatsub_db
    data, llm = _run(conn, vid, [_NO_NAME, _good()])
    assert len(llm.prompts) == 2
    tail = llm.prompts[1][len(llm.prompts[0]):]
    assert "missing or were replaced" in tail and "What'Sub" in tail
    check = data["name_check"]
    assert check["status"] == "passed" and check["attempts"] == 2
    assert check["mode"] == "strict" and check["checks"] == ["missing", "invented"]
    assert "dropped" not in check
    assert check["history"][0]["missing"] == ["What'Sub"]
