from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from . import tools
from ..utils.stderr import force_utf8_stdio

SERVER_INFO = {
    "name": "reel-scout",
    "version": "0.1.0",
}

CAPABILITIES = {
    "tools": {},
}

#: Sent in the initialize result; MCP clients show it to the model before any
#: tool description. It carries what no single tool can: where each kind of data
#: comes from and how far to trust it.
INSTRUCTIONS = (
    "reel-scout is the user's local library of analysed social videos (Instagram, "
    "YouTube, TikTok, Threads, plus local files). Lookups (list_videos, show_video, "
    "keyframes, patterns, search_sound, list_annotations) only read it; crawl, "
    "analyze, batch_*, ingest_*, annotate and mark write to it.\n"
    "Say where a claim comes from, because the layers differ in reliability:\n"
    "- Transcripts come from one of two sources, named in show_video's "
    "`transcript.whisper_model`: 'native-subtitles' is the platform's own caption "
    "track (uploaded or auto-generated); anything else is local Whisper "
    "speech-to-text. Either can misspell names and jargon, and Chinese may come "
    "out simplified or mixed; `transcript.script_mix` flags the mix.\n"
    "- Summaries, hooks, topics, style and keyframe descriptions are model-written "
    "interpretations, and scores are a model's rubric judgement; present them as "
    "assessments, not facts about the video.\n"
    "- Values under `analysis.full.measured` (e.g. cuts_per_minute) are computed "
    "from the file; prefer them over model-written labels when they disagree.\n"
    "- A missing field means it was not produced for that clip, not that the "
    "video lacks it (no music detected may only mean audio analysis was skipped)."
)


def read_message(stream: Any = None) -> Optional[Dict[str, Any]]:
    """Read one JSON-RPC message.

    MCP's stdio transport frames messages as newline-delimited JSON — one compact
    object per line, no embedded newlines. (The original implementation used
    LSP-style ``Content-Length`` headers, which MCP clients like Claude Code do
    not send, so the server never saw a request.)
    """
    if stream is None:
        stream = sys.stdin
    while True:
        line = stream.readline()
        if line in (b"", ""):
            return None  # EOF
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        line = line.strip()
        if line:
            return json.loads(line)


def write_message(message: Dict[str, Any], stream: Any = None) -> None:
    """Write one JSON-RPC message as a single newline-terminated line (UTF-8)."""
    if stream is None:
        stream = sys.stdout
    line = json.dumps(message, ensure_ascii=False) + "\n"
    if hasattr(stream, "buffer"):
        stream.buffer.write(line.encode("utf-8"))  # real stdout: bytes, keeps 中文
    else:
        stream.write(line)  # text stream (e.g. StringIO in tests)
    if hasattr(stream, "flush"):
        stream.flush()


def _rpc_result(req_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    try:
        if method == "initialize":
            return _rpc_result(
                req_id,
                {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": SERVER_INFO,
                    "capabilities": CAPABILITIES,
                    "instructions": INSTRUCTIONS,
                },
            )
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return _rpc_result(req_id, {"tools": tools.list_tools()})
        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            return _rpc_result(req_id, tools.call_tool(tool_name, arguments))
        return _rpc_error(req_id, -32601, "Method not found: %s" % method)
    except Exception as exc:
        return _rpc_error(req_id, -32603, "Internal error: %s" % exc)


def main() -> None:
    # The JSON-RPC replies below go out as raw UTF-8 bytes through
    # `stream.buffer`, so they were never at risk. Everything *else* the package
    # prints while serving a request is -- `tools.py` wraps the pipeline in
    # `redirect_stdout(sys.stderr)` to keep it off the protocol channel, and
    # that is exactly what lands it on the stream whose encoding nobody had
    # fixed. Protecting one channel moved the risk to the other.
    force_utf8_stdio()
    while True:
        message = read_message()
        if message is None:
            break
        response = handle_request(message)
        if response is not None:
            write_message(response)


if __name__ == "__main__":
    main()
