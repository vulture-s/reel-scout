from __future__ import annotations

import os
import shutil
import sqlite3

import pytest

from reel_scout import config, db


TMP_ROOT = os.path.join(os.path.dirname(__file__), "_tmp")


@pytest.fixture
def temp_db(monkeypatch, request):
    """Point every config path at a throwaway dir and hand back the db path.

    Patches config rather than passing a connection around, because the CLI
    handlers take only `args` and call db.init_db() themselves — they resolve
    the database through config.DB_PATH, so that is the only seam.
    """
    os.makedirs(TMP_ROOT, exist_ok=True)
    data_dir = os.path.join(TMP_ROOT, request.node.name[:60])
    shutil.rmtree(data_dir, ignore_errors=True)
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "reel_scout.db")
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "VIDEOS_DIR", os.path.join(data_dir, "videos"))
    monkeypatch.setattr(config, "KEYFRAMES_DIR", os.path.join(data_dir, "keyframes"))
    monkeypatch.setattr(config, "ANALYSIS_DIR", os.path.join(data_dir, "analysis"))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    conn.close()
    try:
        yield db_path
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
