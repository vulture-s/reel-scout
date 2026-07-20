"""Keyframe extraction must not be gated on `--skip-vision`.

Found by running the thing end to end rather than by any of the 305 tests that
existed at the time: `analyze <url> --skip-vision` left **zero** keyframes on
disk and zero rows in the table, because extraction lived inside the
`if not options.skip_vision:` branch alongside the VLM calls.

That silently invalidated the entire no-local-model story. `ingest vision`,
SKILL.md Step 2b and `batch --mode agent` all rest on "the frames are ffmpeg, so
they exist before any model runs" — true of ffmpeg, false of the code. An agent
asked to describe the keyframes would have found an empty directory.

Extraction needs no model, and the case with no VLM is exactly the case where
something else needs those frames later. This test pins the structure so the two
cannot be re-coupled by accident.
"""
from __future__ import annotations

import ast
import os

PIPELINE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "reel_scout", "analyze", "pipeline.py")


def _mentions_skip_vision(node: ast.AST) -> bool:
    return any(getattr(n, "attr", None) == "skip_vision"
               or getattr(n, "id", None) == "skip_vision"
               for n in ast.walk(node))


def _guarded_calls(tree: ast.AST, func_name: str):
    """Names of calls to `func_name` that sit under an `if ... skip_vision ...`."""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not _mentions_skip_vision(node.test):
            continue
        # only the branch taken when vision IS being done — `if not skip_vision:`
        # bodies and `else:` of `if skip_vision:` both count as "vision runs here"
        for branch in (node.body, node.orelse):
            for sub in branch:
                for call in ast.walk(sub):
                    if (isinstance(call, ast.Call)
                            and getattr(call.func, "id", None) == func_name):
                        hits.append(call.lineno)
    return hits


def test_extract_keyframes_is_not_inside_a_skip_vision_branch():
    tree = ast.parse(open(PIPELINE, encoding="utf-8").read())
    guarded = _guarded_calls(tree, "extract_keyframes")
    assert not guarded, (
        "extract_keyframes() is gated on skip_vision at line(s) %s — with no VLM "
        "the pipeline will leave no frames on disk, and `ingest vision` / "
        "SKILL.md Step 2b / `batch --mode agent` all have nothing to read."
        % guarded)


def test_the_pipeline_still_calls_extract_keyframes_at_all():
    """Guard against the above passing because the call was simply deleted."""
    tree = ast.parse(open(PIPELINE, encoding="utf-8").read())
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "extract_keyframes"]
    assert calls, "pipeline no longer extracts keyframes at all"


def test_skip_vision_still_gates_the_vlm_itself():
    """The flag must keep doing what it says: no VLM calls."""
    tree = ast.parse(open(PIPELINE, encoding="utf-8").read())
    assert _guarded_calls(tree, "get_vlm"), (
        "get_vlm() is no longer gated on skip_vision — --skip-vision would try to "
        "reach a VLM that the user just told us not to use")
