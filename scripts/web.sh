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
#   REEL_SCOUT_WEB_WAIT=1   wait up to 60s for Tailscale to come up (for launchd
#                           services that may start before the tailnet is ready)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RS="$REPO/.venv/bin/reel-scout"
[ -x "$RS" ] || RS="reel-scout"   # fall back to PATH

_tailscale_ip() {
  local bin="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
  [ -x "$bin" ] || bin="$(command -v tailscale || true)"
  [ -n "$bin" ] || return 0
  "$bin" ip -4 2>/dev/null | head -1
}

HOST="${REEL_SCOUT_WEB_HOST:-}"
if [ -z "$HOST" ]; then
  HOST="$(_tailscale_ip || true)"
  if [ -z "$HOST" ] && [ "${REEL_SCOUT_WEB_WAIT:-0}" = "1" ]; then
    for _ in $(seq 1 30); do
      sleep 2
      HOST="$(_tailscale_ip || true)"
      [ -n "$HOST" ] && break
    done
  fi
  [ -n "$HOST" ] || HOST="127.0.0.1"   # loopback fallback
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
