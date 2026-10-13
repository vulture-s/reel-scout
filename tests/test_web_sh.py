"""scripts/web.sh host selection — Tailscale readiness + loud loopback fallback.

Drives the real script under bash with fake `tailscale` / `ifconfig` /
`reel-scout` on PATH (no network, no real Tailscale). The script is copied
into a temp "repo" so it can't pick up a real `.venv/bin/reel-scout`, and
REEL_SCOUT_TAILSCALE_APP points at a nonexistent path so the macOS app-bundle
CLI on a dev machine is never consulted.
"""
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

WEB_SH = Path(__file__).resolve().parent.parent / "scripts" / "web.sh"
TS_IP = "100.64.0.7"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="web.sh is a bash script",
)


def _exe(path, body):
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run(tmp_path, *, tailscale=None, ifconfig_has_ip=True, env_extra=None):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(WEB_SH, repo / "scripts" / "web.sh")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # fake reel-scout: just report the host it was asked to bind
    _exe(bin_dir / "reel-scout", 'echo "BIND $*"\n')
    if tailscale is not None:
        _exe(bin_dir / "tailscale", tailscale)
    inet = ("\tinet %s --> %s netmask 0xffffffff\n" % (TS_IP, TS_IP)) if ifconfig_has_ip else ""
    _exe(
        bin_dir / "ifconfig",
        "cat <<'X'\nlo0: flags=8049<UP,LOOPBACK>\n\tinet 127.0.0.1 netmask 0xff000000\n"
        "utun4: flags=8051<UP,POINTOPOINT>\n" + inet + "X\n",
    )
    env = {
        "PATH": "%s:/usr/bin:/bin" % bin_dir,
        "HOME": str(tmp_path),
        "REEL_SCOUT_TAILSCALE_APP": str(tmp_path / "no-such-app"),
    }
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", str(repo / "scripts" / "web.sh"), "view"],
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


TS_UP = 'case "$1" in ip) echo %s;; esac\n' % TS_IP


def test_connected_binds_tailnet_ip_without_warning(tmp_path):
    r = _run(tmp_path, tailscale=TS_UP, ifconfig_has_ip=True)
    assert r.returncode == 0, r.stderr
    assert "--host %s " % TS_IP in r.stdout
    assert "WARNING" not in r.stderr


def test_ip_claimed_but_not_bound_waits_then_warns_and_falls_back(tmp_path):
    # The real-world bug: `tailscale ip -4` answers while the tunnel is down.
    r = _run(
        tmp_path, tailscale=TS_UP, ifconfig_has_ip=False,
        env_extra={"REEL_SCOUT_WEB_WAIT": "1", "REEL_SCOUT_WEB_WAIT_SECS": "1"},
    )
    assert r.returncode == 0, r.stderr  # must not exit: KeepAlive would restart-loop
    assert "--host 127.0.0.1 " in r.stdout
    assert "WARNING" in r.stderr
    assert "not configured on any interface" in r.stderr
    assert "after waiting 1s" in r.stderr


def test_ip_claimed_but_not_bound_without_wait_also_warns(tmp_path):
    r = _run(tmp_path, tailscale=TS_UP, ifconfig_has_ip=False)
    assert "--host 127.0.0.1 " in r.stdout
    assert "not configured on any interface" in r.stderr


def test_no_ip_at_all_times_out_with_warning(tmp_path):
    r = _run(
        tmp_path, tailscale="exit 1\n", ifconfig_has_ip=False,
        env_extra={"REEL_SCOUT_WEB_WAIT": "1", "REEL_SCOUT_WEB_WAIT_SECS": "1"},
    )
    assert r.returncode == 0, r.stderr
    assert "--host 127.0.0.1 " in r.stdout
    assert "reports no IPv4" in r.stderr


def test_tailscale_missing_warns_and_does_not_wait(tmp_path):
    r = _run(
        tmp_path, tailscale=None,
        env_extra={"REEL_SCOUT_WEB_WAIT": "1", "REEL_SCOUT_WEB_WAIT_SECS": "60"},
    )
    assert r.returncode == 0, r.stderr  # (timeout=30 in _run proves no 60s wait)
    assert "--host 127.0.0.1 " in r.stdout
    assert "tailscale CLI not found" in r.stderr


def test_explicit_host_skips_probe(tmp_path):
    r = _run(tmp_path, tailscale=None, env_extra={"REEL_SCOUT_WEB_HOST": "10.1.2.3"})
    assert "--host 10.1.2.3 " in r.stdout
    assert "WARNING" not in r.stderr
