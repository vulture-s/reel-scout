"""HTTPS for the urllib call sites that fetch from the internet.

python.org's macOS installer ships Python WITHOUT access to the system CA store
until someone runs "Install Certificates.command". Every urllib HTTPS request then
fails with CERTIFICATE_VERIFY_FAILED -- found 2026-10-08 on the maintainer's M2 Max,
where the Threads crawler had never once succeeded (all earlier live tests ran on a
Windows machine whose Python reads the OS store). yt-dlp brings its own certificate
handling, which is why IG / TikTok / YouTube never showed it.

So: honour SSL_CERT_FILE if the user set one (that is a deliberate choice), else use
certifi's Mozilla bundle when it is installed (it is a dependency), else the
platform default.
"""
from __future__ import annotations

import os
import ssl
import urllib.request
from typing import Optional


def ssl_context() -> Optional[ssl.SSLContext]:
    if os.environ.get("SSL_CERT_FILE"):
        return None                                   # default context reads it
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def urlopen(req, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())
