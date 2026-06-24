from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from . import tools

SERVER_INFO = {
    "name": "reel-scout",
    "version": "0.1.0",
}

CAPABILITIES = {
    "tools": {},
}

# Wire framing. Two stdio framings exist in the wild:
#   - "content-length": LSP-style headers (the original MCP stdio framing)
#   - "ndjson": one JSON-RPC message per line (what current MCP clients,
#     including Claude Code, actually send)
# read_message() auto-detects per message; main() echoes responses back in the
# same framing the client used. Default stays content-length for backward compat
# (and so write_message() called directly keeps its historical output shape).
FRAMING_CONTENT_LENGTH = "content-length"
FRAMING_NDJSON = "ndjson"
_detected_framing = FRAMING_CONTENT_LENGTH


def _readline(stream: Any) -> Any:
    if hasattr(stream, "buffer"):
        return stream.buffer.readline()
    return stream.readline()


def _read_exact(stream: Any, length: int) -> Any:
    if hasattr(stream, "buffer"):
        return stream.buffer.read(length)
    return stream.read(length)


def _write(stream: Any, data: bytes) -> None:
    if hasattr(stream, "buffer"):
        stream.buffer.write(data)
    else:
        stream.write(data.decode("utf-8"))


def read_message(stream: Any = None) -> Optional[Dict[str, Any]]:
    global _detected_framing
    if stream is None:
        stream = sys.stdin

    line = _readline(stream)
    if line in (b"", ""):
        return None
    decoded = line.decode("utf-8") if isinstance(line, bytes) else line

    # NDJSON framing: the line itself is a complete JSON-RPC message.
    if decoded.lstrip().startswith("{"):
        _detected_framing = FRAMING_NDJSON
        stripped = decoded.strip()
        if not stripped:
            return None
        return json.loads(stripped)

    # LSP-style Content-Length framing: parse headers (first header already read).
    _detected_framing = FRAMING_CONTENT_LENGTH
    content_length = None
    while True:
        if decoded in ("\r\n", "\n", ""):
            break
        name, separator, value = decoded.partition(":")
        if separator and name.lower().strip() == "content-length":
            content_length = int(value.strip())
        line = _readline(stream)
        if line in (b"", ""):
            return None
        decoded = line.decode("utf-8") if isinstance(line, bytes) else line

    if content_length is None:
        raise ValueError("Missing Content-Length header")

    body = _read_exact(stream, content_length)
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    if not body:
        return None
    return json.loads(body)


def write_message(message: Dict[str, Any], stream: Any = None, framing: Optional[str] = None) -> None:
    if stream is None:
        stream = sys.stdout
    if framing is None:
        framing = FRAMING_CONTENT_LENGTH

    if framing == FRAMING_NDJSON:
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        _write(stream, data)
    else:
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        header = ("Content-Length: %d\r\n\r\n" % len(body)).encode("utf-8")
        _write(stream, header + body)
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
    # The loop is intentionally defensive. Processing is serial (one stdio
    # request at a time) and a `tools/call analyze` can block for minutes; if a
    # client gives up and closes the pipe during that wait, the next write would
    # raise BrokenPipeError. Previously any such error (or a malformed frame)
    # propagated out of main() and killed the whole process — taking down ALL
    # tools for the session, not just the one slow request. Now a dead client or
    # a bad frame is contained: we exit cleanly on a closed pipe and skip bad
    # frames instead of crashing. (True concurrency would need a worker thread;
    # this only makes the server survive disconnects — it does not parallelize.)
    while True:
        try:
            message = read_message()
        except Exception as exc:  # malformed / partial frame
            print("reel-scout: skipping unreadable message: %s" % exc, file=sys.stderr)
            continue
        if message is None:
            break
        try:
            response = handle_request(message)
        except Exception as exc:  # belt-and-suspenders; handle_request already guards
            print("reel-scout: handler error: %s" % exc, file=sys.stderr)
            continue
        if response is not None:
            try:
                write_message(response, framing=_detected_framing)
            except (BrokenPipeError, ConnectionResetError):
                # Client closed the pipe (e.g. timed out on a long analyze).
                # Nothing left to write to — stop cleanly instead of crashing.
                break
            except Exception as exc:
                print("reel-scout: failed to write response: %s" % exc, file=sys.stderr)
                continue


if __name__ == "__main__":
    main()
