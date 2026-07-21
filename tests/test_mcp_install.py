from __future__ import annotations

import json
import os
import sys

import pytest

from reel_scout import config, mcp_install


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# --- where each client keeps its config -------------------------------------

def test_client_paths_follow_the_platform(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setattr(sys, "platform", "win32")
    assert mcp_install.client_paths()[mcp_install.CLAUDE_DESKTOP].endswith(
        os.path.join("Roaming", "Claude", "claude_desktop_config.json"))

    monkeypatch.setattr(sys, "platform", "darwin")
    assert "Application Support" in mcp_install.client_paths()[mcp_install.CLAUDE_DESKTOP]

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert mcp_install.client_paths()[mcp_install.CLAUDE_DESKTOP].startswith(str(tmp_path / "cfg"))


# --- the cwd footgun, which is the whole reason this module exists -----------

def test_data_dir_is_pinned_absolute(monkeypatch, tmp_path):
    """REEL_SCOUT_DATA defaults to './data'. A client launches the server from a
    directory of its own choosing, so a relative path silently opens a different,
    empty database -- and the user reports it as 'my videos are gone'."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", "./data")
    target = tmp_path / "cfg.json"

    mcp_install.install(mcp_install.CLAUDE_DESKTOP, path=str(target))

    written = _read(str(target))["mcpServers"]["reel-scout"]["env"]["REEL_SCOUT_DATA"]
    assert os.path.isabs(written)
    assert os.path.normcase(written) == os.path.normcase(str(tmp_path / "data"))


def test_env_carries_only_the_data_dir(monkeypatch, tmp_path):
    """Backend settings live in .env, which config resolves relative to the
    package rather than the cwd. Copying them here would create a second source
    of truth that outlives it."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "cfg.json"
    mcp_install.install(mcp_install.CLAUDE_DESKTOP, path=str(target))
    assert list(_read(str(target))["mcpServers"]["reel-scout"]["env"]) == ["REEL_SCOUT_DATA"]


# --- the file belongs to other people too ------------------------------------

def test_merge_preserves_every_other_server(tmp_path):
    """The headline risk: this file is where all of the user's MCP servers live."""
    target = tmp_path / "cfg.json"
    target.write_text(json.dumps({
        "mcpServers": {
            "filesystem": {"command": "fs-server"},
            "github": {"command": "gh-server", "args": ["--x"]},
        },
        "somethingElse": {"keep": True},
    }), encoding="utf-8")

    mcp_install.install(mcp_install.CLAUDE_DESKTOP, path=str(target))

    data = _read(str(target))
    assert data["mcpServers"]["filesystem"] == {"command": "fs-server"}
    assert data["mcpServers"]["github"] == {"command": "gh-server", "args": ["--x"]}
    assert data["somethingElse"] == {"keep": True}
    assert "reel-scout" in data["mcpServers"]


def test_existing_entry_is_refused_and_left_intact(tmp_path):
    target = tmp_path / "cfg.json"
    original = {"mcpServers": {"reel-scout": {"command": "old-one"}}}
    target.write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(RuntimeError) as excinfo:
        mcp_install.install(mcp_install.CLAUDE_DESKTOP, path=str(target))

    assert "--force" in str(excinfo.value)
    assert _read(str(target)) == original


def test_force_overwrites(tmp_path):
    target = tmp_path / "cfg.json"
    target.write_text(json.dumps(
        {"mcpServers": {"reel-scout": {"command": "old-one"}}}), encoding="utf-8")

    row = mcp_install.install(mcp_install.CLAUDE_DESKTOP, path=str(target), force=True)

    assert row["action"] == "replaced"
    assert _read(str(target))["mcpServers"]["reel-scout"]["command"] != "old-one"


def test_malformed_config_is_refused_not_overwritten(tmp_path):
    """'Recovering' from a parse error means deleting every server in the file."""
    target = tmp_path / "cfg.json"
    target.write_text("{not json", encoding="utf-8")
    before = target.read_bytes()

    with pytest.raises(RuntimeError):
        mcp_install.install(mcp_install.CLAUDE_DESKTOP, path=str(target))

    assert target.read_bytes() == before


def test_a_backup_is_written_before_overwriting(tmp_path):
    target = tmp_path / "cfg.json"
    target.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
    row = mcp_install.install(mcp_install.CLAUDE_DESKTOP, path=str(target))
    assert row["backup"] and os.path.isfile(row["backup"])
    assert _read(row["backup"])["mcpServers"] == {"other": {"command": "x"}}


def test_missing_config_is_created_with_parents(tmp_path):
    target = tmp_path / "deep" / "nested" / "cfg.json"
    mcp_install.install(mcp_install.CLAUDE_DESKTOP, path=str(target))
    assert "reel-scout" in _read(str(target))["mcpServers"]


# --- which command gets written ----------------------------------------------

def test_console_script_beside_the_interpreter_wins_over_path(monkeypatch, tmp_path):
    """`which` answers for the installer's shell, which on a machine with two
    virtualenvs is a coin flip. The interpreter running this code is the one the
    user just installed into."""
    venv = tmp_path / "venv" / ("Scripts" if sys.platform == "win32" else "bin")
    venv.mkdir(parents=True)
    name = "reel-scout-mcp.exe" if sys.platform == "win32" else "reel-scout-mcp"
    (venv / name).write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(venv / "python"))
    monkeypatch.setattr(mcp_install.shutil, "which", lambda _n: str(tmp_path / "decoy"))

    command, args, how = mcp_install.resolve_command()

    assert how == "console-script"
    assert command == str(venv / name)
    assert args == []


def test_falls_back_to_module_invocation(monkeypatch, tmp_path):
    empty = tmp_path / "nowhere"
    empty.mkdir()
    monkeypatch.setattr(sys, "executable", str(empty / "python"))
    monkeypatch.setattr(mcp_install.shutil, "which", lambda _n: None)

    command, args, how = mcp_install.resolve_command()

    assert how == "module"
    assert args == ["-m", "reel_scout.mcp.server"]
    assert os.path.isabs(command)


def test_the_written_command_is_absolute(monkeypatch, tmp_path):
    """Clients launch it without a shell, so a bare name would not resolve."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "cfg.json"
    mcp_install.install(mcp_install.CLAUDE_DESKTOP, path=str(target))
    assert os.path.isabs(_read(str(target))["mcpServers"]["reel-scout"]["command"])


def test_a_path_with_spaces_survives(monkeypatch, tmp_path):
    spaced = tmp_path / "My Videos" / "reel scout"
    spaced.mkdir(parents=True)
    monkeypatch.chdir(spaced)
    target = tmp_path / "cfg.json"
    mcp_install.install(mcp_install.CLAUDE_DESKTOP, path=str(target))
    written = _read(str(target))["mcpServers"]["reel-scout"]["env"]["REEL_SCOUT_DATA"]
    assert " " in written and os.path.isabs(written)


# --- claude-code takes the client's own CLI when it can ----------------------

def test_claude_code_prefers_the_clients_own_cli(monkeypatch, tmp_path):
    """~/.claude.json is rewritten by a running Claude Code, so an outside merge
    can be clobbered by its next flush."""
    calls = []
    monkeypatch.setattr(mcp_install.shutil, "which",
                        lambda n: "/usr/bin/claude" if n == "claude" else None)
    monkeypatch.setattr(mcp_install.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or None)
    monkeypatch.chdir(tmp_path)

    row = mcp_install.install(mcp_install.CLAUDE_CODE)

    assert row["via_cli"] is True
    assert calls and calls[0][1:4] == ["mcp", "add-json", "reel-scout"]


def test_claude_code_falls_back_to_a_merge_when_the_cli_is_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_install.shutil, "which", lambda _n: None)
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "dot-claude.json"

    row = mcp_install.install(mcp_install.CLAUDE_CODE, path=str(target))

    assert row["via_cli"] is False
    assert "reel-scout" in _read(str(target))["mcpServers"]


# --- diagnosis ----------------------------------------------------------------

def test_status_flags_a_data_dir_mismatch(monkeypatch, tmp_path):
    """The direct readout for 'the client is reading a different library'."""
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "cfg.json"
    monkeypatch.setattr(mcp_install, "client_paths",
                        lambda: {mcp_install.CLAUDE_DESKTOP: str(cfg),
                                 mcp_install.CLAUDE_CODE: str(tmp_path / "none.json")})
    cfg.write_text(json.dumps({"mcpServers": {"reel-scout": {
        "command": "somewhere-else",
        "env": {"REEL_SCOUT_DATA": str(tmp_path / "other-library")}}}}), encoding="utf-8")

    row = [r for r in mcp_install.status() if r["client"] == mcp_install.CLAUDE_DESKTOP][0]

    assert row["configured"] is True
    assert row["data_dir_matches"] is False
    assert row["command_matches"] is False


def test_status_counts_other_servers_without_dumping_them(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg.json"
    monkeypatch.setattr(mcp_install, "client_paths",
                        lambda: {mcp_install.CLAUDE_DESKTOP: str(cfg),
                                 mcp_install.CLAUDE_CODE: str(tmp_path / "none.json")})
    cfg.write_text(json.dumps({"mcpServers": {"a": {}, "b": {}}}), encoding="utf-8")

    row = [r for r in mcp_install.status() if r["client"] == mcp_install.CLAUDE_DESKTOP][0]

    assert row["configured"] is False
    assert row["other_servers"] == 2


def test_status_never_writes(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg.json"
    monkeypatch.setattr(mcp_install, "client_paths",
                        lambda: {mcp_install.CLAUDE_DESKTOP: str(cfg),
                                 mcp_install.CLAUDE_CODE: str(tmp_path / "none.json")})
    mcp_install.status()
    assert not cfg.exists()


# --- CLI seam -----------------------------------------------------------------

def _args(**kw):
    import argparse
    base = dict(mcp_command="install", client=mcp_install.CLAUDE_DESKTOP, data="",
                name="reel-scout", path="", force=False, dry_run=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_cli_tells_the_user_to_fully_quit(monkeypatch, tmp_path, capsys):
    """Both clients only re-read config on a real relaunch; 'I ran it and nothing
    happened' is otherwise the first support question."""
    from reel_scout import cli

    monkeypatch.chdir(tmp_path)
    cli._cmd_mcp(_args(path=str(tmp_path / "cfg.json")))
    out = capsys.readouterr().out
    assert "quit" in out.lower()
    assert "REEL_SCOUT_DATA" in out


def test_cli_surfaces_the_refusal(monkeypatch, tmp_path, capsys):
    from reel_scout import cli

    target = tmp_path / "cfg.json"
    target.write_text(json.dumps(
        {"mcpServers": {"reel-scout": {"command": "old"}}}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cli._cmd_mcp(_args(path=str(target)))

    assert "--force" in capsys.readouterr().out


def test_cli_dry_run_writes_nothing(monkeypatch, tmp_path, capsys):
    from reel_scout import cli

    monkeypatch.chdir(tmp_path)
    target = tmp_path / "cfg.json"
    cli._cmd_mcp(_args(path=str(target), dry_run=True))
    out = capsys.readouterr().out
    assert "mcpServers" in out
    assert not target.exists()
