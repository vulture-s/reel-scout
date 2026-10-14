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


def _opencc_importable() -> bool:
    try:
        import opencc  # noqa: F401  # type: ignore
    except ImportError:
        return False
    return True


@pytest.fixture
def need_opencc():
    """Skip when the optional `zh` extra is absent -- unless CI says it must be there.

    CI runs the suite twice: once without the extra (these tests skip, the
    no-opencc fallback is exercised for real) and once with
    REEL_SCOUT_REQUIRE_OPENCC=1, where a missing opencc is a failure rather
    than a quiet skip -- otherwise the "with zh" job could pass having tested
    nothing.
    """
    if not _opencc_importable():
        if os.environ.get("REEL_SCOUT_REQUIRE_OPENCC") == "1":
            pytest.fail("REEL_SCOUT_REQUIRE_OPENCC=1 but opencc is not importable")
        pytest.skip("optional zh extra (opencc) not installed")


@pytest.fixture
def no_opencc(monkeypatch):
    """Make `import opencc` fail, as on an install without the zh extra."""
    import sys

    from reel_scout import zh_convert

    monkeypatch.setitem(sys.modules, "opencc", None)
    monkeypatch.setattr(zh_convert, "_opencc_cache", {})
