"""urllib HTTPS must not depend on the OS CA store.

python.org's macOS Python has no CA store until "Install Certificates.command" runs,
so every urllib HTTPS fetch failed with CERTIFICATE_VERIFY_FAILED on the maintainer's
M2 Max -- the Threads crawler had never worked there (earlier live tests ran on a
Windows machine). These pin: certifi's bundle is used, a user's SSL_CERT_FILE wins,
a missing certifi falls back instead of crashing, and BOTH internet-facing call sites
actually go through the helper.
"""
from __future__ import annotations

import builtins
import ssl
from unittest.mock import MagicMock, patch

import pytest

from reel_scout.utils import https


def test_uses_certifi_bundle(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    import certifi
    with patch("reel_scout.utils.https.ssl.create_default_context") as cdc:
        https.ssl_context()
    cdc.assert_called_once_with(cafile=certifi.where())


def test_ssl_cert_file_from_the_user_wins(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/custom/ca.pem")
    assert https.ssl_context() is None                # default context honours the env


def test_missing_certifi_falls_back_instead_of_crashing(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    real_import = builtins.__import__

    def no_certifi(name, *a, **k):
        if name == "certifi":
            raise ImportError("no certifi")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_certifi)
    assert https.ssl_context() is None


@pytest.mark.parametrize("call", ["threads", "batch"])
def test_internet_facing_fetches_pass_the_context(call, monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = b"x"
    resp.geturl.return_value = "https://example"
    with patch("reel_scout.utils.https.urllib.request.urlopen", return_value=resp) as uo:
        if call == "threads":
            from reel_scout.crawl.threads import _fetch
            _fetch("https://www.threads.com/@a/post/X", "UA")
        else:
            from reel_scout import batch
            batch.fetch("https://example.com/list.txt")
    ctx = uo.call_args.kwargs.get("context")
    assert isinstance(ctx, ssl.SSLContext)
