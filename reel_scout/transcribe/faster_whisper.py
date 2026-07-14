from __future__ import annotations

from .base import BaseTranscriber, Segment, TranscriptResult


class FasterWhisperTranscriber(BaseTranscriber):
    def __init__(self, model: str = "large-v3") -> None:
        self._model_name = model
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise ImportError(
                    "faster-whisper not installed. "
                    "Install with: pip install faster-whisper"
                )
            self._model = WhisperModel(
                self._model_name,
                device="auto",
                compute_type="auto",
            )

    def transcribe(self, audio_path: str) -> TranscriptResult:
        self._ensure_model()

        from .. import config
        kwargs = {"beam_size": 5, "vad_filter": True}
        # language="" -> None so faster-whisper auto-detects
        if config.WHISPER_LANGUAGE:
            kwargs["language"] = config.WHISPER_LANGUAGE
        if config.WHISPER_TASK and config.WHISPER_TASK != "transcribe":
            kwargs["task"] = config.WHISPER_TASK
        # Per-chunk language detection for code-switching (中英對照) audio.
        # Only meaningful when language is NOT forced.
        if config.WHISPER_MULTILINGUAL and not config.WHISPER_LANGUAGE:
            kwargs["multilingual"] = True
            if config.WHISPER_CHUNK_LENGTH > 0:
                kwargs["chunk_length"] = config.WHISPER_CHUNK_LENGTH

        segments_iter, info = self._model.transcribe(audio_path, **kwargs)

        segments = []
        texts = []
        for seg in segments_iter:
            segments.append(Segment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                confidence=seg.avg_logprob,
            ))
            texts.append(seg.text.strip())

        return TranscriptResult(
            language=info.language,
            text_full=" ".join(texts),
            segments=segments,
            duration_sec=info.duration,
            model=self._model_name,
        )
