"""Simplified -> Traditional conversion at the source, plus user hotwords.

Used in two places, both at the source and never on a model's output:
``inspire``'s in-memory analysis copy for the LLM (never written back), and
``db.save_transcript`` for Simplified transcripts / subtitles (stored
converted, the received text kept in ``transcripts.*_original``). Two
user-facing knobs:

* **mode** -- ``s2twp`` (default: Traditional with Taiwan phrasing, e.g.
  视频 -> 影片, 软件 -> 軟體), ``s2tw`` (character-by-character, no phrase
  swaps) or ``off``. Set via ``REEL_SCOUT_ZH_CONVERT`` / ``--zh-convert``.
* **hotwords** -- a YAML or JSON file of ``source: replacement`` pairs applied
  *after* OpenCC, longest match first, to fix the phrase swaps ``s2twp`` gets
  wrong for this domain (``类型 -> 型別`` when you wanted 類型). Set via
  ``REEL_SCOUT_ZH_HOTWORDS`` / ``--zh-hotwords``.

A key may be written in its Simplified *source* form (``类型``) or in the form
OpenCC produced (``型別``): each key is also run through the same OpenCC
config, so both spellings hit. That is the point of "after OpenCC" -- a
Simplified key alone would never match text OpenCC has already rewritten.

OpenCC is the optional ``zh`` extra (``pip install "reel-scout[zh]"``). Without
it, conversion is skipped with a stderr warning -- never silently.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, Optional

from . import config

#: The values ``mode`` may take after normalisation.
MODES = ("s2twp", "s2tw", "off")
_OFF_SPELLINGS = ("off", "none", "no", "false", "0", "")

INSTALL_HINT = 'pip install "reel-scout[zh]"'

_opencc_cache: Dict[str, Any] = {}


def normalize_mode(mode: Optional[str]) -> str:
    """``s2twp`` / ``s2tw`` / ``off``; unknown values raise ValueError."""
    m = (mode if mode is not None else "s2twp").strip().lower()
    if m in _OFF_SPELLINGS:
        return "off"
    if m.endswith(".json"):
        m = m[:-5]
    if m in ("s2twp", "s2tw"):
        return m
    raise ValueError("unknown zh conversion mode %r (use s2twp, s2tw or off)" % mode)


def _opencc_for(mode: str) -> Optional[Callable[[str], str]]:
    """Cached OpenCC ``convert`` for *mode*, or None if OpenCC is not installed.

    Two packages install as ``import opencc``: the pure-python
    ``opencc-python-reimplemented`` (the ``zh`` extra; takes ``"s2twp"``) and
    the official binding (older releases want ``"s2twp.json"``). Try both.
    """
    if mode in _opencc_cache:
        return _opencc_cache[mode]
    try:
        import opencc  # type: ignore
    except ImportError:
        return None
    try:
        conv = opencc.OpenCC(mode)
    except Exception:  # official binding < 1.1.x only accepts the .json name
        conv = opencc.OpenCC(mode + ".json")
    _opencc_cache[mode] = conv.convert
    return conv.convert


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    return s


def parse_hotwords(text: str, source: str = "<hotwords>") -> Dict[str, str]:
    """Parse a hotword table: a JSON object, or flat YAML ``key: value`` lines.

    Only the flat mapping form is accepted -- no nesting, no lists -- so no
    YAML library is needed. ``#`` starts a comment line. A malformed line is a
    ValueError naming the line, not a silently skipped entry.
    """
    stripped = text.lstrip("﻿").strip()
    if not stripped:
        return {}
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except ValueError as exc:
            raise ValueError("%s: invalid JSON: %s" % (source, exc))
        if not isinstance(data, dict):
            raise ValueError("%s: hotwords must be an object of source: replacement" % source)
        out = {}
        for k, v in data.items():
            if not isinstance(k, str) or not isinstance(v, str) or not k:
                raise ValueError("%s: hotword %r -> %r must be two strings" % (source, k, v))
            out[k] = v
        return out
    out = {}
    for lineno, raw in enumerate(stripped.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # ": " (or a trailing ":") separates; full-width "：" is accepted too
        # because a Chinese IME types it without anyone noticing.
        m = re.match(r"^(\"[^\"]*\"|'[^']*'|[^:：]+?)\s*[:：]\s*(.*)$", line)
        if not m:
            raise ValueError("%s line %d: expected 'source: replacement', got %r" % (source, lineno, raw))
        key, value = _unquote(m.group(1)), _unquote(m.group(2))
        if not key:
            raise ValueError("%s line %d: empty source word" % (source, lineno))
        out[key] = value
    return out


def load_hotwords(path: str) -> Dict[str, str]:
    with open(path, encoding="utf-8") as fh:
        return parse_hotwords(fh.read(), source=path)


class Converter:
    """Callable: OpenCC (per *mode*) then hotwords, longest match first."""

    def __init__(self, mode: str = "s2twp", hotwords: Optional[Dict[str, str]] = None) -> None:
        self.mode = normalize_mode(mode)
        self.opencc: Optional[Callable[[str], str]] = None
        self.opencc_missing = False
        if self.mode != "off":
            self.opencc = _opencc_for(self.mode)
            self.opencc_missing = self.opencc is None
        self.table: Dict[str, str] = {}
        for src, dst in (hotwords or {}).items():
            # Both spellings: as written, and as OpenCC rewrites it -- the
            # latter is what is actually in the text by the time we look.
            self.table[src] = dst
            if self.opencc is not None:
                self.table.setdefault(self.opencc(src), dst)
        self._pattern = None
        if self.table:
            keys = sorted(self.table, key=len, reverse=True)
            self._pattern = re.compile("|".join(re.escape(k) for k in keys))

    def apply_hotwords(self, text: str) -> str:
        if self._pattern is None:
            return text
        return self._pattern.sub(lambda m: self.table[m.group(0)], text)

    def __call__(self, text: str) -> str:
        if self.opencc is not None:
            text = self.opencc(text)
        return self.apply_hotwords(text)


def build_converter(mode: Optional[str] = None, hotwords_path: Optional[str] = None) -> Converter:
    """Converter from explicit args, falling back to config / env.

    Check ``.opencc_missing`` on the result: the caller owns the warning,
    because only it knows what the unconverted text will be used for.
    """
    mode = config.ZH_CONVERT if mode is None else mode
    path = config.ZH_HOTWORDS if hotwords_path is None else hotwords_path
    hotwords = load_hotwords(path) if path else {}
    return Converter(mode, hotwords)
