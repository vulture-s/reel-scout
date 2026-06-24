"""Temporal-vision backends. Each renders a ClipPayload for one model family.

All contact-sheet backends (local Ollama VLM, Claude/Codex via proxy) share the
same substrate — scout_core.contact_sheet — and differ only in the HTTP/API call.
"""
