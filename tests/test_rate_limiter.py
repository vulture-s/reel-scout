"""Pacing must hold across processes -- batch runs each video as a subprocess."""
from __future__ import annotations

import os
import subprocess
import sys

from reel_scout.crawl import rate_limiter
from reel_scout.crawl.rate_limiter import RateLimiter, effective_rate

_CHILD = r"""
import sys, time
from reel_scout.crawl.rate_limiter import RateLimiter
lim = RateLimiter("instagram", rate_per_minute=60, path=sys.argv[1])
slept = lim.wait()
print("%f %f" % (time.time(), slept))
"""


def test_three_independent_processes_are_paced(tmp_path):
    """The audit repro: three fresh processes each waited 0.00s. Now they
    share one state file, so the second and third wait for their slots.
    (An explicit 60/min rate keeps the test fast; the real instagram default
    is 5/min = 12s apart.)"""
    path = str(tmp_path / "ratelimit.db")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PYTHONPATH=root)  # the children import *this* checkout
    procs = [subprocess.Popen([sys.executable, "-c", _CHILD, path], cwd=root, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(3)]
    results = []
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
        done, slept = (float(x) for x in out.split())
        results.append((done, slept))
    results.sort()
    finishes = [r[0] for r in results]
    # 60/min -> 1s apart. Allow a little scheduler slack below the interval.
    assert finishes[1] - finishes[0] >= 0.9
    assert finishes[2] - finishes[1] >= 0.9
    # The third one in line had to actually wait.
    assert max(r[1] for r in results) >= 1.5


def test_sequential_calls_in_one_process_still_paced(tmp_path):
    path = str(tmp_path / "rl.db")
    a = RateLimiter("tiktok", rate_per_minute=120, path=path)
    b = RateLimiter("tiktok", rate_per_minute=120, path=path)  # a different object
    assert a.wait() == 0.0
    assert b.wait() > 0.3  # 0.5s interval, shared through the file


def test_platforms_do_not_share_a_slot(tmp_path):
    path = str(tmp_path / "rl.db")
    RateLimiter("instagram", rate_per_minute=1, path=path).wait()
    assert RateLimiter("youtube", rate_per_minute=1, path=path).wait() == 0.0


def test_rate_limit_env_is_read_and_only_slows(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    assert effective_rate("instagram") == 5
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    assert effective_rate("instagram") == 2
    assert effective_rate("youtube") == 2
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "100")
    assert effective_rate("instagram") == 5  # cannot loosen the account-safety default
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "junk")
    assert effective_rate("instagram") == 5


def test_default_state_lives_in_data_dir(monkeypatch, tmp_path):
    from reel_scout import config
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    assert rate_limiter.state_path() == os.path.join(str(tmp_path), "ratelimit.db")


def test_unwritable_state_degrades_loudly(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    bad = str(blocker / "sub" / "rl.db")
    rate_limiter._LOCAL_LAST.clear()
    # Fresh objects per call, exactly like get_limiter(): the fallback must not
    # live on the instance, or it would never pace anything.
    first = RateLimiter("instagram", rate_per_minute=120, path=bad).wait()
    second = RateLimiter("instagram", rate_per_minute=120, path=bad).wait()
    # The first call in a degraded process cannot see siblings, so it waits a
    # full interval (0.5s) instead of firing immediately.
    assert first > 0.3
    assert second > 0.3  # still paced within the process
    assert "shared state unavailable" in capsys.readouterr().err
    rate_limiter._LOCAL_LAST.clear()


def test_non_integer_rate_env_does_not_break_startup():
    """effective_rate() ignores a bad value, but config read it at import
    with a bare int() first -- so `RATE_LIMIT_PER_MINUTE=bogus` crashed every
    command before the limiter's own handling could run."""
    env = dict(os.environ, RATE_LIMIT_PER_MINUTE="bogus")
    r = subprocess.run([sys.executable, "-c", "import reel_scout.config as c; print(c.RATE_LIMIT_PER_MINUTE)"],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "10"
