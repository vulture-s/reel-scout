"""Register the MCP server with the clients that will launch it.

`pip install reel-scout` gives you a CLI and a `reel-scout-mcp` entry point. It
does not tell Claude Desktop or Claude Code that either exists, and the only
documented alternative is hand-editing a JSON file -- which is the step that
loses the non-technical half of a class.

The unobvious part is not the registration, it is `REEL_SCOUT_DATA`. It defaults
to "./data", relative to the *current working directory*, and an MCP client
launches the server from a directory of its own choosing. Without an absolute
path pinned at install time the server quietly opens a different, empty
database, and the symptom the user reports is "my videos are gone". config.py
already calls this the "reel-scout MCP cwd footgun"; this module is the antidote.

Deliberately mirrors skill_install: same refusal-unless-force semantics, same
"return what happened so the CLI can print it" shape.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from . import config

#: The key we own inside "mcpServers". Everything else in the file is untouched.
DEFAULT_SERVER_NAME = "reel-scout"

CLAUDE_DESKTOP = "claude-desktop"
CLAUDE_CODE = "claude-code"
CLIENTS = (CLAUDE_DESKTOP, CLAUDE_CODE)


def client_paths() -> Dict[str, str]:
    """Where each client keeps its MCP config on this platform."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        desktop = os.path.join(appdata, "Claude", "claude_desktop_config.json")
    elif sys.platform == "darwin":
        desktop = os.path.join(
            home, "Library", "Application Support", "Claude", "claude_desktop_config.json"
        )
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        desktop = os.path.join(xdg, "Claude", "claude_desktop_config.json")
    return {
        CLAUDE_DESKTOP: desktop,
        CLAUDE_CODE: os.path.join(home, ".claude.json"),
    }


def resolve_command() -> Tuple[str, List[str], str]:
    """(command, args, how). Always an absolute command.

    The console script *next to the running interpreter* wins over one found on
    PATH: `which` answers for the shell the installer happens to be in, which on
    a machine with two virtualenvs is a coin flip. The interpreter executing this
    code is the one the user just installed into, so it is the ground truth.

    Clients launch the command without a shell, so a bare name would not resolve.
    """
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    name = "reel-scout-mcp.exe" if sys.platform == "win32" else "reel-scout-mcp"
    # A venv puts python and the scripts together; a base Windows install splits
    # them into the root and Scripts/.
    for candidate in (os.path.join(exe_dir, name), os.path.join(exe_dir, "Scripts", name)):
        if os.path.isfile(candidate):
            return candidate, [], "console-script"

    found = shutil.which("reel-scout-mcp")
    if found:
        return os.path.abspath(found), [], "path"

    return os.path.abspath(sys.executable), ["-m", "reel_scout.mcp.server"], "module"


def resolve_data_dir(override: str = "") -> str:
    """The data dir to pin, always absolute.

    Resolved against the cwd of *this* command on purpose: "the library I am
    standing in right now" is what the user means, and making it absolute here
    is the whole point of the exercise.
    """
    return os.path.abspath(os.path.expanduser(override or config.DATA_DIR))


def server_entry(data_dir: str, command: Optional[str] = None,
                 args: Optional[List[str]] = None) -> Dict[str, Any]:
    if command is None:
        command, args, _ = resolve_command()
    return {
        "command": command,
        "args": list(args or []),
        # Only REEL_SCOUT_DATA. Backend settings live in .env, which config
        # finds relative to the package rather than the cwd, so copying them
        # here would create a second source of truth that outlives it.
        "env": {"REEL_SCOUT_DATA": data_dir},
    }


def read_config(path: str) -> Dict[str, Any]:
    """Parsed config, or {} when there is nothing there yet.

    Raises on malformed JSON rather than starting fresh: the file holds other
    people's servers, and "recovering" from a parse error means deleting them.
    """
    if not os.path.isfile(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        text = handle.read().strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise RuntimeError(
            "%s is not valid JSON (%s) — fix or move it; refusing to overwrite it"
            % (path, exc)
        )
    if not isinstance(data, dict):
        raise RuntimeError("%s does not contain a JSON object; refusing to overwrite it" % path)
    return data


def _write_config(path: str, data: Dict[str, Any]) -> Optional[str]:
    """Atomically replace `path`. Returns the backup path, if one was made.

    Same directory for the temp file: os.replace is only atomic within a
    filesystem. A crash between truncate and write would otherwise cost the user
    every other MCP server they had configured.
    """
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)

    backup = None
    if os.path.isfile(path):
        backup = path + ".reel-scout.bak"
        shutil.copy2(path, backup)

    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".reel-scout-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        if os.path.exists(tmp):
            os.unlink(tmp)
        if sys.platform == "win32" and getattr(exc, "winerror", None) in (5, 32):
            raise RuntimeError(
                "could not write %s — it is locked, which usually means the client "
                "is running. Fully quit it and try again." % path
            )
        raise
    return backup


def _claude_code_cli_add(entry: Dict[str, Any], name: str) -> bool:
    """Let Claude Code write its own config, if its CLI is around.

    ~/.claude.json is large, holds per-project state, and is rewritten by a
    running Claude Code process — a merge from outside can be clobbered by the
    client's next flush. Handing the write to the client avoids that race.
    """
    claude = shutil.which("claude")
    if not claude:
        return False
    try:
        subprocess.run(
            [claude, "mcp", "add-json", name, json.dumps(entry), "--scope", "user"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def install(client: str, *, data_dir: str = "", name: str = DEFAULT_SERVER_NAME,
            force: bool = False, path: str = "") -> Dict[str, Any]:
    """Register the server for `client`. Returns what happened, for printing."""
    if not path and client not in CLIENTS:
        raise RuntimeError("unknown client %r — one of: %s" % (client, ", ".join(CLIENTS)))

    resolved_data = resolve_data_dir(data_dir)
    command, args, how = resolve_command()
    entry = server_entry(resolved_data, command, args)

    if client == CLAUDE_CODE and not path and _claude_code_cli_add(entry, name):
        return {"client": client, "path": "(via `claude mcp add-json`)", "action": "installed",
                "command": command, "args": args, "how": how,
                "data_dir": resolved_data, "backup": None, "via_cli": True}

    target = os.path.abspath(os.path.expanduser(path)) if path else client_paths()[client]
    data = read_config(target)
    servers = data.setdefault("mcpServers", {})
    existed = name in servers
    if existed and not force:
        raise RuntimeError(
            "'%s' is already configured in %s (command: %s) — pass --force to "
            "overwrite it" % (name, target, servers[name].get("command", "?"))
        )
    servers[name] = entry
    backup = _write_config(target, data)
    return {"client": client, "path": target,
            "action": "replaced" if existed else "installed",
            "command": command, "args": args, "how": how,
            "data_dir": resolved_data, "backup": backup, "via_cli": False}


def _video_count(data_dir: str) -> Optional[int]:
    """How many videos that data dir actually holds, or None if there is no DB.

    The number is the point: "configured" and "pointing at your library" are
    different things, and only this distinguishes them.
    """
    db_path = os.path.join(data_dir, "reel_scout.db")
    if not os.path.isfile(db_path):
        return None
    import sqlite3

    try:
        conn = sqlite3.connect(db_path)
        try:
            return conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def status(name: str = DEFAULT_SERVER_NAME) -> List[Dict[str, Any]]:
    """Per-client diagnosis. Never writes anything."""
    would_command, would_args, would_how = resolve_command()
    here = resolve_data_dir()
    out = []
    for client, path in client_paths().items():
        row: Dict[str, Any] = {
            "client": client, "path": path, "exists": os.path.isfile(path),
            "configured": False, "command": None, "data_dir": None,
            "other_servers": 0, "command_matches": None, "data_dir_matches": None,
            "configured_videos": None, "error": None,
        }
        try:
            data = read_config(path)
        except RuntimeError as exc:
            row["error"] = str(exc)
            out.append(row)
            continue
        servers = data.get("mcpServers") or {}
        row["other_servers"] = len([k for k in servers if k != name])
        entry = servers.get(name)
        if entry:
            configured_data = (entry.get("env") or {}).get("REEL_SCOUT_DATA")
            row.update(
                configured=True,
                command=entry.get("command"),
                args=entry.get("args") or [],
                data_dir=configured_data,
                command_matches=os.path.normcase(str(entry.get("command") or ""))
                == os.path.normcase(would_command),
                data_dir_matches=(
                    None if not configured_data
                    else os.path.normcase(os.path.abspath(configured_data))
                    == os.path.normcase(here)
                ),
                configured_videos=_video_count(configured_data) if configured_data else None,
            )
        out.append(row)
    return out


def status_summary() -> Dict[str, Any]:
    """`status()` plus what this directory resolves to, for the CLI to print."""
    command, args, how = resolve_command()
    here = resolve_data_dir()
    return {
        "clients": status(),
        "would_command": command,
        "would_args": args,
        "would_how": how,
        "here_data_dir": here,
        "here_videos": _video_count(here),
    }
