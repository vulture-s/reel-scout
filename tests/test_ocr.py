"""§4F on-screen text (L3.5): caption collection + merge integration."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

from reel_scout import db, ocr


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn, path


def _kf_row(ts, text_in_frame, file_path="/frame.jpg"):
    return {"timestamp_sec": ts, "text_in_frame": text_in_frame, "file_path": file_path}


def test_collect_captions_vlm_default_drops_empty():
    conn, path = _temp_db()
    try:
        rows = [_kf_row(1.0, "SALE 50%"), _kf_row(2.0, ""), _kf_row(3.0, "Coffee Master")]
        with patch("reel_scout.ocr.db.get_keyframes_with_descriptions", return_value=rows):
            caps = ocr.collect_captions(conn, "v", engine="vlm")
        assert [c["text"] for c in caps] == ["SALE 50%", "Coffee Master"]
        assert all(c["engine"] == "vlm" for c in caps)
        assert caps[0]["timestamp_sec"] == 1.0
    finally:
        conn.close()
        os.unlink(path)


def test_collect_captions_tesseract_falls_back_when_unavailable():
    conn, path = _temp_db()
    try:
        rows = [_kf_row(1.0, "VLM TEXT")]
        with patch("reel_scout.ocr.db.get_keyframes_with_descriptions", return_value=rows), \
             patch("reel_scout.ocr._tesseract_available", return_value=False):
            caps = ocr.collect_captions(conn, "v", engine="tesseract")
        assert caps[0]["text"] == "VLM TEXT"
        assert caps[0]["engine"] == "vlm"  # fell back to VLM text
    finally:
        conn.close()
        os.unlink(path)


def test_collect_captions_tesseract_used_when_available():
    conn, path = _temp_db()
    try:
        rows = [_kf_row(1.0, "vlm fallback")]
        with patch("reel_scout.ocr.db.get_keyframes_with_descriptions", return_value=rows), \
             patch("reel_scout.ocr._tesseract_available", return_value=True), \
             patch("reel_scout.ocr._ocr_image", return_value="TESSERACT TEXT"):
            caps = ocr.collect_captions(conn, "v", engine="tesseract")
        assert caps[0]["text"] == "TESSERACT TEXT"
        assert caps[0]["engine"] == "tesseract"
    finally:
        conn.close()
        os.unlink(path)


def test_ocr_image_best_effort_returns_empty_on_failure():
    # No pytesseract installed OR unreadable path — either way "" (never raises).
    assert ocr._ocr_image("/nonexistent-frame-xyz.jpg") == ""


def test_merge_includes_onscreen_text():
    conn, path = _temp_db()
    try:
        vid = db.upsert_video(
            conn, platform="youtube", platform_id="ocr_merge",
            url="https://youtube.com/shorts/ocr_merge", title="T", duration_sec=20.0,
        )
        db.save_ocr_captions(conn, vid, [
            {"timestamp_sec": 1.0, "text": "50% OFF TODAY", "engine": "vlm"},
        ])
        from reel_scout.analyze import merger
        mock_llm = MagicMock()
        mock_llm.complete.return_value = json.dumps({"summary": "s"})
        with patch("reel_scout.analyze.merger.get_llm", return_value=mock_llm):
            merger.merge_analysis(conn, vid)
        prompt = mock_llm.complete.call_args[0][0]
        assert "On-screen Text" in prompt
        assert "50% OFF TODAY" in prompt
    finally:
        conn.close()
        os.unlink(path)
