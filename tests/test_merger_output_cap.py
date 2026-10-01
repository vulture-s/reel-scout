"""The merge call's output ceiling must fit a talk-heavy clip.

At a literal 800 tokens, a 14-minute interview's analysis JSON (1038 tokens)
was cut off mid-string, and every retry failed the same way. The ceiling now
comes from config; this pins that it is used and that the default clears the
largest real case measured.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from reel_scout import config
from reel_scout.analyze import merger
from tests.test_merger_transcript_evidence import _LLM_REPLY, _seed, _temp_db


def test_merge_uses_the_configured_output_ceiling() -> None:
    conn, path = _temp_db()
    try:
        vid = _seed(conn, "capcase", text_full="hello")
        mock_llm = MagicMock()
        mock_llm.complete.return_value = _LLM_REPLY
        with patch("reel_scout.analyze.merger.get_llm", return_value=mock_llm), \
                patch.object(config, "MERGE_MAX_TOKENS", 1234):
            merger.merge_analysis(conn, vid)
        assert mock_llm.complete.call_args.kwargs["max_tokens"] == 1234
    finally:
        conn.close()
        os.remove(path)


def test_default_ceiling_clears_the_measured_interview() -> None:
    # 1038 = eval_count of the clip that kept failing at 800.
    assert config.MERGE_MAX_TOKENS >= 1038
