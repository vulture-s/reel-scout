"""Skill distribution (`reel-scout skill install`).

The gap this closes was measured, not theorised: a clean venv with
`pip install reel-scout` had a working CLI and none of SKILL.md, commands/,
prompts/ or scripts/setup.py — so an agent had nothing to load and `/scout` did
not exist. These tests hold the two source layouts (vendored wheel copy vs. a
clone) to the same destination tree.
"""
from __future__ import annotations

import os

import pytest

from reel_scout import skill_install


@pytest.fixture
def fake_bundle(tmp_path, monkeypatch):
    """A vendored-in-wheel layout: reel_scout/skill/ with the assets under it."""
    root = tmp_path / "pkg" / "skill"
    (root / "commands").mkdir(parents=True)
    (root / "prompts").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    (root / "SKILL.md").write_text("# skill", encoding="utf-8")
    (root / "commands" / "scout.md").write_text("scout", encoding="utf-8")
    (root / "prompts" / "hook-reverse-structure.md").write_text("p", encoding="utf-8")
    (root / "scripts" / "setup.py").write_text("print('x')", encoding="utf-8")
    monkeypatch.setattr(skill_install, "bundled_root", lambda: str(root))
    return str(root)


def test_bundled_source_wins_over_a_clone(fake_bundle, monkeypatch):
    """An installed package must not silently prefer some unrelated checkout."""
    monkeypatch.setattr(skill_install, "repo_root", lambda: "/somewhere/else")
    root, which = skill_install.source_root()
    assert (root, which) == (fake_bundle, "bundled")


def test_clone_is_the_fallback(monkeypatch):
    monkeypatch.setattr(skill_install, "bundled_root", lambda: None)
    monkeypatch.setattr(skill_install, "repo_root", lambda: "/repo")
    assert skill_install.source_root() == ("/repo", "clone")


def test_missing_everywhere_is_reported_not_guessed(monkeypatch):
    monkeypatch.setattr(skill_install, "bundled_root", lambda: None)
    monkeypatch.setattr(skill_install, "repo_root", lambda: None)
    assert skill_install.source_root() == (None, "missing")
    with pytest.raises(RuntimeError, match="not found"):
        skill_install.install("/tmp/whatever")


def test_install_lays_down_the_agent_facing_files(fake_bundle, tmp_path):
    dest = tmp_path / "skills" / "reel-scout"
    resolved, copied = skill_install.install(str(dest))
    assert set(copied) == {"SKILL.md", "commands", "prompts", "scripts"}
    for rel in ("SKILL.md", "commands/scout.md",
                "prompts/hook-reverse-structure.md", "scripts/setup.py"):
        assert os.path.isfile(os.path.join(resolved, rel)), rel


def test_non_empty_destination_is_refused_without_force(fake_bundle, tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "SKILL.md").write_text("my own edits", encoding="utf-8")
    with pytest.raises(RuntimeError, match="--force"):
        skill_install.install(str(dest))
    # and the user's file is untouched
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "my own edits"


def test_force_overwrites(fake_bundle, tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "SKILL.md").write_text("stale", encoding="utf-8")
    skill_install.install(str(dest), force=True)
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "# skill"


def test_a_clone_contributes_only_setup_py_from_scripts(tmp_path, monkeypatch):
    """A checkout's scripts/ carries more than the skill uses; don't ship the rest."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "commands").mkdir()
    (repo / "prompts").mkdir()
    (repo / "SKILL.md").write_text("# skill", encoding="utf-8")
    (repo / "scripts" / "setup.py").write_text("s", encoding="utf-8")
    (repo / "scripts" / "web.sh").write_text("not part of the skill", encoding="utf-8")
    monkeypatch.setattr(skill_install, "bundled_root", lambda: None)
    monkeypatch.setattr(skill_install, "repo_root", lambda: str(repo))

    dest, _ = skill_install.install(str(tmp_path / "dest"))
    assert os.path.isfile(os.path.join(dest, "scripts", "setup.py"))
    assert not os.path.exists(os.path.join(dest, "scripts", "web.sh"))


def test_dest_expands_a_tilde(fake_bundle, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    dest, _ = skill_install.install("~/.claude/skills/reel-scout")
    assert dest == str(tmp_path / ".claude" / "skills" / "reel-scout")


# --- CLI seam ---------------------------------------------------------------

def test_cli_skill_path_names_the_source(fake_bundle, capsys):
    from reel_scout import cli

    cli.main(["skill", "path"])
    out = capsys.readouterr().out
    assert "bundled" in out
    assert fake_bundle in out


def test_cli_skill_install_tells_the_user_what_to_do_next(fake_bundle, tmp_path, capsys):
    from reel_scout import cli

    cli.main(["skill", "install", "--dest", str(tmp_path / "d")])
    out = capsys.readouterr().out
    assert "Installed the reel-scout skill" in out
    assert "/scout" in out          # the payoff, not just a file count


def test_cli_skill_install_surfaces_the_refusal(fake_bundle, tmp_path, capsys):
    from reel_scout import cli

    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "x").write_text("y", encoding="utf-8")
    cli.main(["skill", "install", "--dest", str(dest)])
    assert "--force" in capsys.readouterr().out
