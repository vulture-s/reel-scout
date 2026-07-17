"""Regression: .env discovery must be CWD-independent.

Guards the "reel-scout MCP cwd footgun": the MCP server (and any CLI launched
from a non-project CWD) used to miss the project's .env, silently falling back
to built-in backend defaults (dead omlx:8000) so every VLM/LLM call failed with
Connection refused.
"""
from __future__ import annotations

from pathlib import Path

from reel_scout import config


def test_env_candidates_include_project_root_from_foreign_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # a CWD with no .env of its own
    cands = [Path(p).resolve() for p in config._env_candidates()]

    project_root = Path(config.__file__).resolve().parent.parent
    assert (project_root / ".env").resolve() in cands, (
        "project-root .env must be a candidate regardless of CWD"
    )
    # back-compat: the CWD is still searched first
    assert cands[0] == (tmp_path / ".env").resolve()


def test_load_env_loads_project_root_env(monkeypatch, tmp_path):
    """From a foreign CWD, a project-root .env is parsed (via a stubbed root)."""
    fake_root_env = tmp_path / "root" / ".env"
    fake_root_env.parent.mkdir(parents=True)
    fake_root_env.write_text("FOO_FROM_ROOT=bar\n", encoding="utf-8")

    foreign_cwd = tmp_path / "elsewhere"
    foreign_cwd.mkdir()
    monkeypatch.chdir(foreign_cwd)

    monkeypatch.setattr(
        config, "_env_candidates", lambda env_path=".env": [Path(env_path), fake_root_env]
    )
    monkeypatch.delenv("FOO_FROM_ROOT", raising=False)
    config._load_env()

    import os

    assert os.environ.get("FOO_FROM_ROOT") == "bar"
