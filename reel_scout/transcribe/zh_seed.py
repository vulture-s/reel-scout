"""繁體種子提示 —— faster-whisper 與 mlx-whisper 兩個 backend 共用。

原本整段寫在 `FasterWhisperTranscriber` 裡；mlx backend 加進來後抽成 mixin，
因為「先確認是中文、再給繁體種子」這條規則跟引擎無關，兩邊必須同一份 ——
各抄一份就會有一邊先漂掉。唯一跟引擎有關的是「怎麼從一段音訊判定語言」，
那一步留給子類別的 `_detect_language(audio) -> str`。
"""
from __future__ import annotations


class ZhSeedMixin:
    """需要子類別提供 `_detect_language(audio_float32_16k) -> 語言標籤`。"""

    #: 語言探測只看開頭這麼多秒。
    _ZH_PROBE_SECONDS = 30
    #: Whisper 會吐的中文標籤。`yue` 是粵語，在使用它的地方同樣寫繁體，所以吃同一個種子。
    _ZH_TAGS = ("zh", "yue")

    def _zh_prompt_for(self, audio_path, forced_language):
        """這支片要用的繁體種子提示，或 None。

        功能關閉、音訊不是中文、或**查不出來**時一律回 None —— 那三種情況下呼叫端
        的行為跟改動前一字不差。

        **為什麼要先確定語言**：`WHISPER_LANGUAGE` 預設是 ""（自動偵測），而把中文
        提示餵給日文音訊會把解碼器往中文偏。這個語料裡就有一支 `lang=ja`，所以那不是
        假想的風險。

        **為什麼探測只取開頭 30 秒**：`detect_language` 要吃音訊陣列，而 `decode_audio`
        沒有長度參數 —— 為了判斷語言就把整支解開，會讓語料裡那支 4 小時的片變成
        ~960MB 的 float32。ffmpeg 本來就是硬依賴，所以切開頭那一段只要 1.8MB、
        約 6 秒，而且**與片長無關**。

        失敗會出聲，不會被吞掉：靜默跳過等於交回一份簡體逐字稿，卻不說明這個設定
        為什麼沒作用。
        """
        from .. import config

        if (config.WHISPER_ZH_SCRIPT or "").lower() != "traditional":
            return None
        if not config.WHISPER_ZH_PROMPT:
            return None
        if forced_language:
            # 已經指定語言就不必探測 —— 也不該探測，那是使用者的宣告。
            return (config.WHISPER_ZH_PROMPT
                    if forced_language.lower() in self._ZH_TAGS else None)
        lang = self._probe_language(audio_path)
        if lang is None:
            return None
        return config.WHISPER_ZH_PROMPT if lang.lower() in self._ZH_TAGS else None

    def _probe_language(self, audio_path):
        """開頭那一段的 Whisper 語言標籤，讀不到回 None。

        取音訊（ffmpeg）這半是共用的；判定那半交給各 backend 的 `_detect_language`。
        """
        import subprocess

        from .. import config as cfg
        from ..utils.stderr import warn


        try:
            import numpy as np
        except ImportError:                                    # pragma: no cover
            warn("  note: 沒有 numpy — 略過繁簡種子的語言探測")
            return None
        try:
            proc = subprocess.run(
                [cfg.FFMPEG_BIN, "-v", "error", "-i", audio_path,
                 "-t", str(self._ZH_PROBE_SECONDS), "-ac", "1", "-ar", "16000",
                 "-f", "f32le", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            warn("  note: 語言探測失敗（%s）— 不加繁體種子直接轉錄" % exc)
            return None
        if proc.returncode != 0 or not proc.stdout:
            warn("  note: 語言探測取不到音訊 — 不加繁體種子直接轉錄")
            return None
        audio = np.frombuffer(proc.stdout, dtype=np.float32)
        if audio.size == 0:
            return None
        try:
            lang = self._detect_language(audio)
        except Exception as exc:                               # noqa: BLE001
            warn("  note: 語言判定失敗（%s）— 不加繁體種子直接轉錄" % exc)
            return None
        return lang

    def _detect_language(self, audio):                       # pragma: no cover
        raise NotImplementedError
