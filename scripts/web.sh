#!/usr/bin/env bash
# reel-scout web launcher — serve the read-only viewer (list) or the
# single-clip inspector on this machine's Tailscale IP so other devices on the
# tailnet can reach it. Falls back to loopback when Tailscale is unavailable.
#
#   scripts/web.sh view              # read-only list of all analyzed clips
#   scripts/web.sh inspect <video>   # interactive single-clip inspector
#
# Env overrides:
#   REEL_SCOUT_WEB_HOST    force bind host (skip auto-detect)
#   REEL_SCOUT_WEB_PORT    view port    (default 8700)
#   REEL_SCOUT_INSPECT_PORT inspect port (default 8710)
#   REEL_SCOUT_WEB_WAIT=1   wait for Tailscale to come up (for launchd services
#                           that may start before the tailnet is ready)
#   REEL_SCOUT_WEB_WAIT_SECS  how long REEL_SCOUT_WEB_WAIT waits (default 60)
#   REEL_SCOUT_TAILSCALE_APP  macOS app-bundle CLI path probed before PATH
#                           (default /Applications/Tailscale.app/Contents/MacOS/Tailscale)
#
# "Tailscale is up" means the tailnet IPv4 is actually configured on a local
# interface (what bind() needs) — NOT merely that `tailscale ip -4` prints an
# address: that answers from node config even while the tunnel is down, so a
# non-empty IP string is the wrong readiness signal (bind then fails with
# EADDRNOTAVAIL). When Tailscale is not up we still fall back to 127.0.0.1 —
# exiting would put a KeepAlive launchd job into a restart loop — but we say
# so loudly on stderr instead of degrading silently.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RS="$REPO/.venv/bin/reel-scout"
[ -x "$RS" ] || RS="reel-scout"   # fall back to PATH

_tailscale_bin() {
  local bin="${REEL_SCOUT_TAILSCALE_APP:-/Applications/Tailscale.app/Contents/MacOS/Tailscale}"
  [ -x "$bin" ] || bin="$(command -v tailscale || true)"
  echo "$bin"
}

_ifconfig_bin() {
  command -v ifconfig 2>/dev/null && return 0
  local c
  for c in /sbin/ifconfig /usr/sbin/ifconfig; do
    [ -x "$c" ] && { echo "$c"; return 0; }
  done
  return 0
}

_warn() { echo "web.sh: WARNING: $*" >&2; }

TS_BIN="$(_tailscale_bin)"
IFCONFIG_BIN="$(_ifconfig_bin)"
# Probe once. Sets TS_IP to the tailnet IPv4 only if it is really up
# (configured on a local interface); otherwise TS_IP="" and TS_REASON says why.
# Runs in the current shell (not $(...)) so TS_REASON survives.
_probe_tailscale() {
  TS_IP=""; TS_REASON=""
  if [ -z "$TS_BIN" ]; then
    TS_REASON="tailscale CLI not found"; return 0
  fi
  local ip
  ip="$("$TS_BIN" ip -4 2>/dev/null | head -1 || true)"
  if [ -z "$ip" ]; then
    TS_REASON="tailscale reports no IPv4 (daemon down / logged out?)"; return 0
  fi
  if [ -z "$IFCONFIG_BIN" ]; then
    # Can't verify the interface; keep the old behaviour but don't hide it.
    _warn "ifconfig not found — cannot verify $ip is bound; using it unverified"
    TS_IP="$ip"; return 0
  fi
  if "$IFCONFIG_BIN" 2>/dev/null | grep -q "inet ${ip} "; then
    TS_IP="$ip"; return 0
  fi
  TS_REASON="tailscale claims $ip but it is not configured on any interface (tunnel not up)"
}

HOST="${REEL_SCOUT_WEB_HOST:-}"
if [ -z "$HOST" ]; then
  _probe_tailscale
  if [ -z "$TS_IP" ] && [ -n "$TS_BIN" ] && [ "${REEL_SCOUT_WEB_WAIT:-0}" = "1" ]; then
    wait_secs="${REEL_SCOUT_WEB_WAIT_SECS:-60}"
    deadline=$(( SECONDS + wait_secs ))
    while [ -z "$TS_IP" ] && [ "$SECONDS" -lt "$deadline" ]; do
      sleep 2
      _probe_tailscale
    done
    [ -n "$TS_IP" ] || TS_REASON="after waiting ${wait_secs}s: $TS_REASON"
  fi
  HOST="$TS_IP"
  if [ -z "$HOST" ]; then
    _warn "Tailscale not up ($TS_REASON) — falling back to 127.0.0.1; NOT reachable from the tailnet"
    HOST="127.0.0.1"   # kept so KeepAlive launchd jobs don't restart-loop
  fi
fi

cmd="${1:-view}"; shift || true
case "$cmd" in
  view)
    PORT="${REEL_SCOUT_WEB_PORT:-8700}"
    echo "reel-scout view → http://$HOST:$PORT/"
    [ "$HOST" = "127.0.0.1" ] || echo "  (連不上時：本機 macOS App Firewall 可能靜默丟 Tailscale/utun 封包 → 關防火牆或加 ACL)"
    exec "$RS" view --host "$HOST" --port "$PORT" --no-open
    ;;
  inspect)
    [ $# -ge 1 ] || { echo "usage: web.sh inspect <video_id>" >&2; exit 2; }
    PORT="${REEL_SCOUT_INSPECT_PORT:-8710}"
    echo "reel-scout inspect $1 → http://$HOST:$PORT/"
    [ "$HOST" = "127.0.0.1" ] || echo "  (連不上時：本機 macOS App Firewall 可能靜默丟 Tailscale/utun 封包 → 關防火牆或加 ACL)"
    exec "$RS" inspect "$1" --host "$HOST" --port "$PORT" --no-open
    ;;
  *)
    echo "usage: web.sh {view | inspect <video_id>}" >&2
    exit 2
    ;;
esac
