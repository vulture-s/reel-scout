"""mlx-whisper backend —— Apple Silicon 上唯一的 Metal 轉錄路徑（issue #113）。

`faster-whisper` 在 macOS 是 CPU-only（CTranslate2 沒有 Metal 後端）。同一台 M2 Max、
同一支 3:39:30 的片：faster-whisper large-v3 RTF 1.22（4h28m），mlx-whisper
large-v3 RTF 0.242（~53 分），large-v3-turbo RTF 0.040（~9 分）。

**預設（`WHISPER_BACKEND=auto`）**：能跑就走這條（Apple Silicon ＋ `mlx` extra），否則 faster-whisper。
2026-10-20 A/B（5 支有人工中文字幕的片）：large-v3 平均字錯率 9.5%，faster-whisper 9.4%，
差距在各片起伏之內；RTF 0.11–0.37 對 1.17–1.79。明寫 `WHISPER_BACKEND=mlx` 仍可強制。

跟 faster-whisper 的差異（別當成等價產物）：
  - **沒有 beam search**：mlx-whisper 0.4.3 `decoding.py` 對 beam_size 明確
    `raise NotImplementedError` → 走 greedy + temperature fallback。
  - **沒有 vad_filter**：以 `hallucination_silence_threshold` 近似（它要
    `word_timestamps=True` 才生效）。
  - `WHISPER_MULTILINGUAL` / `WHISPER_CHUNK_LENGTH` 沒有對應（mlx-whisper 沒有
    per-chunk 語言重偵測）→ 設了會出聲說明被忽略，不靜默。

一樣的地方（這些是契約，有測試釘住）：
  - 輸出形狀 = `TranscriptResult`（language / text_full / segments / duration_sec / model），
    下游 `db.save_transcript` 的繁轉（s2twp、`text_full_original`，schema v21）照常生效。
  - 逐段機率（no_speech_prob / avg_logprob / compression_ratio）照樣餵給 whisper-guard。
  - 繁體種子規則（`ZhSeedMixin`）與 faster-whisper 共用同一份。
"""
from __future__ import annotations

from typing import Optional

from .base import BaseTranscriber, Segment, TranscriptResult
from .zh_seed import ZhSeedMixin

#: `WHISPER_MODEL` 的短名 → HF repo。含 "/" 的值視為 repo 原樣使用。
#: 只列實測過或 mlx-community 官方維護的；未知短名直接報錯，不猜 repo 名
#: （猜錯會在 HF 下載階段才失敗，而且錯誤訊息不會指回這裡）。
MLX_MODEL_REPOS = {
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}

#: 與 faster-whisper 預設行為對齊的解碼參數（beam_size 不可用，見檔頭）。
_DECODE_KWARGS = dict(
    temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
    compression_ratio_threshold=2.4,
    logprob_threshold=-1.0,
    no_speech_threshold=0.6,
    condition_on_previous_text=True,
    # vad_filter 的近似；它要 word_timestamps 才生效。
    word_timestamps=True,
    hallucination_silence_threshold=2.0,
)


def resolve_mlx_repo(model: str) -> str:
    """`WHISPER_MODEL` → mlx-community HF repo。"""
    if "/" in model:
        return model
    try:
        return MLX_MODEL_REPOS[model]
    except KeyError:
        raise ValueError(
            "WHISPER_MODEL=%r has no known mlx repo (known: %s); "
            "set WHISPER_MODEL to an HF repo id like mlx-community/whisper-large-v3-turbo"
            % (model, ", ".join(sorted(MLX_MODEL_REPOS))))


class MlxWhisperTranscriber(ZhSeedMixin, BaseTranscriber):
    def __init__(self, model: str = "large-v3") -> None:
        self._model_name = model
        self._repo = resolve_mlx_repo(model)
        self._mlx = None

    def _ensure_model(self):
        # 模型本身由 mlx_whisper 的 ModelHolder 依 repo 快取，第一次 transcribe 才下載／載入；
        # 這裡只確保套件在。
        if self._mlx is None:
            try:
                import mlx_whisper
            except ImportError:
                raise ImportError(
                    "mlx-whisper not installed. "
                    "Install with: pip install 'reel-scout[mlx]'")
            self._mlx = mlx_whisper

    def _detect_language(self, audio):
        """`ZhSeedMixin` 的掛勾：對開頭 30 秒跑一次不帶語言的轉錄，取它判定的語言。

        mlx-whisper 沒有公開的 detect_language API（只在 `decoding` 內部），
        用公開的 `transcribe` 換穩定性；turbo 上這段 ~1-2 秒，且模型會被
        ModelHolder 快取給正式那一輪重用。
        """
        self._ensure_model()
        res = self._mlx.transcribe(
            audio, path_or_hf_repo=self._repo, temperature=0.0,
            condition_on_previous_text=False, verbose=None)
        return res.get("language")

    def _decode_kwargs(self) -> dict:
        from .. import config
        from ..utils.stderr import warn

        kwargs = dict(_DECODE_KWARGS)
        if config.WHISPER_LANGUAGE:
            kwargs["language"] = config.WHISPER_LANGUAGE
        if config.WHISPER_TASK and config.WHISPER_TASK != "transcribe":
            kwargs["task"] = config.WHISPER_TASK
        if config.WHISPER_MULTILINGUAL and not config.WHISPER_LANGUAGE:
            warn("  note: WHISPER_MULTILINGUAL has no mlx-whisper equivalent "
                 "(no per-chunk language re-detection) — ignored on the mlx backend")
        return kwargs

    def transcribe(self, audio_path: str) -> TranscriptResult:
        self._ensure_model()
        from ..ffprobe import probe_duration
        from .faster_whisper import _apply_guard

        kwargs = self._decode_kwargs()
        zh_prompt = self._zh_prompt_for(audio_path, kwargs.get("language"))
        if zh_prompt:
            kwargs["initial_prompt"] = zh_prompt
            # 同 faster-whisper：強制 zh 才能讓種子穩定生效。mlx 沒有 multilingual
            # 模式，所以不必像那邊留例外。
            kwargs["language"] = "zh"

        res = self._mlx.transcribe(audio_path, path_or_hf_repo=self._repo,
                                   verbose=None, **kwargs)

        raw = [
            {
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
                "text": (seg.get("text") or "").strip(),
                "no_speech_prob": seg.get("no_speech_prob", 0.0),
                "avg_logprob": seg.get("avg_logprob", 0.0),
                "compression_ratio": seg.get("compression_ratio", 1.0),
            }
            for seg in res.get("segments") or []
        ]
        kept = _apply_guard(raw)
        segments = [
            Segment(start=r["start"], end=r["end"], text=r["text"],
                    confidence=r["avg_logprob"])
            for r in kept
        ]
        duration: Optional[float] = probe_duration(audio_path)
        return TranscriptResult(
            language=res.get("language") or "",
            text_full=" ".join(r["text"] for r in kept),
            segments=segments,
            # mlx-whisper 不回報音訊長度；量不到就 0.0（同 whisper-cpp），不拿最後一段的
            # end 冒充 —— 那會少算尾端靜音。
            duration_sec=duration or 0.0,
            # 帶 backend 前綴：coverage 的 source 欄就是讀這個，A/B 時才分得出哪一線產的。
            model="mlx:" + self._repo,
        )
