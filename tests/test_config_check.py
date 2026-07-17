"""config check backend coverage (roadmap 5B)."""
from __future__ import annotations

from reel_scout import cli, config
from reel_scout.crawl import ytdlp


def _patch_probes(monkeypatch, http_ok=True, import_ok=True, cmd_ok=True):
    calls = {"cmds": [], "urls": [], "imports": []}

    def fake_cmd(cmd, timeout=5):
        calls["cmds"].append(cmd)
        return (cmd_ok, "1.2.3" if cmd_ok else "err")

    def fake_http(url, timeout=3):
        calls["urls"].append(url)
        return (http_ok, "%s (%s)" % (url, "reachable" if http_ok else "down"))

    def fake_import(module):
        calls["imports"].append(module)
        return import_ok

    monkeypatch.setattr(cli, "_probe_cmd", fake_cmd)
    monkeypatch.setattr(cli, "_probe_http", fake_http)
    monkeypatch.setattr(cli, "_probe_import", fake_import)
    return calls


def _names(checks):
    return [c[0] for c in checks]


def test_core_backends_always_checked(monkeypatch):
    _patch_probes(monkeypatch)
    monkeypatch.setattr(config, "VLM_BACKEND", "omlx")
    monkeypatch.setattr(config, "LLM_BACKEND", "openclaw")
    checks = cli._run_config_checks()
    names = _names(checks)
    assert "ffmpeg" in names
    assert "yt-dlp" in names
    assert "whisper" in names
    assert any(n.startswith("VLM") for n in names)
    assert any(n.startswith("LLM") for n in names)


def test_ytdlp_check_uses_resolved_binary_not_hardcoded(monkeypatch):
    calls = _patch_probes(monkeypatch)
    cli._run_config_checks()
    ytdlp.base_cmd.cache_clear()
    expected = list(ytdlp.base_cmd()) + ["--version"]
    assert expected in calls["cmds"], "yt-dlp check must use ytdlp.base_cmd(), not 'yt-dlp'"


def test_llm_reachability_keyed_off_llm_backend(monkeypatch):
    calls = _patch_probes(monkeypatch)
    monkeypatch.setattr(config, "LLM_BACKEND", "ollama")
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://ollama.test:11434")
    cli._run_config_checks()
    assert "http://ollama.test:11434" in calls["urls"]


def test_optional_backends_only_when_configured(monkeypatch):
    _patch_probes(monkeypatch)
    # None configured → no optional rows.
    monkeypatch.setattr(config, "PANNS_MODEL_PATH", "")
    monkeypatch.setattr(config, "DIARIZE_ENABLED", False)
    monkeypatch.setattr(config, "IG_COOKIES_FILE", "")
    names = _names(cli._run_config_checks())
    assert "audio/PANNs" not in names
    assert "diarize" not in names
    assert "instagram" not in names

    # Enable them → rows appear.
    monkeypatch.setattr(config, "PANNS_MODEL_PATH", "/models/panns.onnx")
    monkeypatch.setattr(config, "DIARIZE_ENABLED", True)
    monkeypatch.setattr(config, "PYANNOTE_AUTH_TOKEN", "tok")
    monkeypatch.setattr(config, "IG_COOKIES_FILE", __file__)  # an existing file
    names = _names(cli._run_config_checks())
    assert "audio/PANNs" in names
    assert "diarize" in names
    assert "instagram" in names


def test_diarize_flagged_not_ok_without_token(monkeypatch):
    _patch_probes(monkeypatch, import_ok=True)
    monkeypatch.setattr(config, "DIARIZE_ENABLED", True)
    monkeypatch.setattr(config, "PYANNOTE_AUTH_TOKEN", "")
    diarize = [c for c in cli._run_config_checks() if c[0] == "diarize"][0]
    assert diarize[1] is False  # not ok — token missing
    assert "TOKEN MISSING" in diarize[2]
