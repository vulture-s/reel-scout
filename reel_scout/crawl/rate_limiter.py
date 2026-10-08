"""Per-platform request pacing that holds across processes.

Why this is not an in-memory counter: `reel-scout batch` (and MCP
`batch_start`) runs every entry as a fresh `reel-scout analyze` subprocess, so
a limiter that lives in one process starts at zero for every video -- batch,
the bulk path, was effectively unthrottled, and two batches running at once
doubled it. The pacing state therefore lives in a small SQLite file next to the
library (`<DATA_DIR>/ratelimit.db`), which every process on the machine that
shares that data dir sees.

How it paces: each caller *reserves* the next free slot for its platform inside
one `BEGIN IMMEDIATE` transaction (`slot = max(now, last_slot + interval)`),
commits, and only then sleeps until its slot. The lock is held for a read and a
write, never across the sleep, so N callers arriving together get slots
`t, t+i, t+2i, ...` instead of all waking at once. SQLite rather than fcntl
because reel-scout also runs on Windows.

Rate per platform = min(platform default, RATE_LIMIT_PER_MINUTE). The env knob
can only make pacing *slower* than the per-platform default, never faster: the
defaults (e.g. instagram 5/min) are what protect the user's logged-in account.
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Optional

from ..utils.stderr import warn

# Per-platform default rates (requests per minute).
PLATFORM_RATES = {
    "youtube": 10,
    "instagram": 5,
    "tiktok": 8,
    "threads": 5,
}

_DEFAULT_RATE = 10
_STATE_FILE = "ratelimit.db"


def effective_rate(platform: str) -> int:
    """Requests/minute for *platform*, read at call time (not import time)."""
    base = PLATFORM_RATES.get(platform, _DEFAULT_RATE)
    raw = os.getenv("RATE_LIMIT_PER_MINUTE", "").strip()
    if not raw:
        return base
    try:
        cap = int(raw)
    except ValueError:
        warn(f"[rate-limit] ignoring non-integer RATE_LIMIT_PER_MINUTE={raw!r}")
        return base
    return max(1, min(base, cap))


def state_path() -> str:
    from .. import config
    return os.path.join(config.DATA_DIR, _STATE_FILE)


def _reserve_slot(path: str, platform: str, interval: float) -> float:
    """Atomically claim the next slot for *platform*; return its epoch time."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS rate_slots ("
            " platform TEXT PRIMARY KEY, last_slot REAL NOT NULL)"
        )
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT last_slot FROM rate_slots WHERE platform = ?", (platform,)
            ).fetchone()
            now = time.time()
            slot = now if row is None else max(now, float(row[0]) + interval)
            conn.execute(
                "INSERT INTO rate_slots(platform, last_slot) VALUES (?, ?) "
                "ON CONFLICT(platform) DO UPDATE SET last_slot = excluded.last_slot",
                (platform, slot),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return slot
    finally:
        conn.close()


class RateLimiter:
    """Cross-process pacer for one platform."""

    def __init__(self, platform: str, rate_per_minute: Optional[int] = None,
                 path: Optional[str] = None) -> None:
        self.platform = platform
        self._rate = rate_per_minute
        self._path = path
        self._last_local = 0.0  # fallback when the shared state is unusable

    @property
    def interval(self) -> float:
        rate = self._rate if self._rate is not None else effective_rate(self.platform)
        return 60.0 / max(rate, 1)

    def wait(self) -> float:
        """Block until this caller's slot; return seconds slept."""
        interval = self.interval
        path = self._path or state_path()
        try:
            slot = _reserve_slot(path, self.platform, interval)
        except (sqlite3.Error, OSError) as e:
            # Loud, but don't refuse to work: an unwritable data dir should not
            # turn every crawl into an error. Pacing degrades to per-process.
            warn(f"[rate-limit] shared state unavailable ({path}: {e}); "
                 f"pacing {self.platform} within this process only")
            slot = max(time.time(), self._last_local + interval)
            self._last_local = slot
        delay = slot - time.time()
        if delay > 0:
            time.sleep(delay)
            return delay
        return 0.0


def get_limiter(platform: str) -> RateLimiter:
    # A fresh object each time is fine: all state is in the shared file, and
    # the rate is re-read so a changed RATE_LIMIT_PER_MINUTE takes effect.
    return RateLimiter(platform)
