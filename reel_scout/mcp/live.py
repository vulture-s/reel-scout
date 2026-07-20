"""Long-lived resources owned by the MCP process — currently just the inspector.

Kept out of tools.py deliberately. That module has no mutable state at all,
which is what lets every handler be tested in isolation, and a listening socket
is exactly the kind of thing that quietly ends that property. Having it here
also gives tests one obvious place to reset.

Lifetime is the MCP process's: the thread is a daemon, so when the client goes
away the server dies and takes the inspector with it. A URL handed out earlier
simply stops loading. That is the honest behaviour for a local review surface,
but it does mean the URL is worth re-requesting rather than bookmarking.
"""

from __future__ import annotations

import contextlib
import sys
import threading
from typing import Any, Dict, Optional

from .. import config, db

_STATE: Dict[str, Any] = {"httpd": None, "thread": None, "host": None, "port": None}


def is_running() -> bool:
    """Whether the inspector is up *and* still serving.

    Checks the thread, not just the object: serve_forever can die on an
    unhandled error and leave a non-None httpd behind, and a stale handle would
    otherwise keep handing out a URL that no longer answers.
    """
    thread = _STATE["thread"]
    return _STATE["httpd"] is not None and thread is not None and thread.is_alive()


def base_url() -> Optional[str]:
    if not is_running():
        return None
    return "http://%s:%d" % (_STATE["host"], _STATE["port"])


def ensure_inspector(host: str = "127.0.0.1", port: int = 0) -> str:
    """Start the inspector if it is not up, and return its base URL.

    `host` is not plumbed through to the caller anywhere: none of the inspector's
    routes carry any authentication, and /api/stream/ will serve any video in the
    database, so a tool that let an agent set 0.0.0.0 would be one call away from
    publishing the user's library to their LAN.
    """
    if is_running():
        return base_url()

    from .. import inspector

    config.ensure_dirs()
    # make_inspect_server only connects; it never creates the schema or runs
    # migrations, and the request handler calls get_connection directly. Against
    # a database that does not exist yet that is a page of 500s, which is why
    # both `inspect` and `view` do this first.
    db.init_db().close()

    # Nothing in here prints today, but the route handlers defer their imports
    # and stdout is the JSON-RPC channel: a module-level print appearing in any
    # of them would kill the session with no other symptom.
    with contextlib.redirect_stdout(sys.stderr):
        httpd = inspector.make_inspect_server(host=host, port=port, default_id=None)

    # Hold the reference before starting the thread: this dict is the only thing
    # keeping the socket from being garbage collected.
    _STATE["httpd"] = httpd
    _STATE["host"] = host
    _STATE["port"] = httpd.server_address[1]
    thread = threading.Thread(
        target=httpd.serve_forever, daemon=True, name="reel-scout-inspector")
    _STATE["thread"] = thread
    thread.start()
    return base_url()


def stop_inspector() -> bool:
    """Shut it down. True if something was actually running."""
    httpd = _STATE["httpd"]
    if httpd is None:
        return False
    try:
        httpd.shutdown()
    except Exception:  # noqa: BLE001 - already dead is a fine outcome here
        pass
    with contextlib.suppress(Exception):
        httpd.server_close()
    thread = _STATE["thread"]
    if thread is not None:
        thread.join(timeout=5)
    _STATE.update(httpd=None, thread=None, host=None, port=None)
    return True
