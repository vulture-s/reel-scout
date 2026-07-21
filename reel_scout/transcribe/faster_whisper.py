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

        # Collect raw segments WITH the per-segment probabilities the guard needs
        # (no_speech_prob / avg_logprob / compression_ratio). Reducing to Segment
        # first would drop these fields and neuter whisper-guard's probability layers.
        raw = [
            {
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "no_speech_prob": getattr(seg, "no_speech_prob", 0.0),
                "avg_logprob": getattr(seg, "avg_logprob", 0.0),
                "compression_ratio": getattr(seg, "compression_ratio", 1.0),
            }
            for seg in segments_iter
        ]

        kept = _apply_guard(raw)

        segments = [
            Segment(start=r["start"], end=r["end"], text=r["text"],
                    confidence=r["avg_logprob"])
            for r in kept
        ]

        return TranscriptResult(
            language=info.language,
            text_full=" ".join(r["text"] for r in kept),
            segments=segments,
            duration_sec=info.duration,
            model=self._model_name,
        )


def _apply_guard(segments):
    """Run whisper-guard's anti-hallucination filter over raw Whisper segments.

    Returns the kept segments (dicts with start/end/text + probabilities), dropping
    silence / low-logprob / high-compression / repetition / char-loop hallucinations
    — the same 4-layer guard arkiv and media-manager already run. No-op (returns the
    input) when WHISPER_GUARD_ENABLED is off, and degrades gracefully if whisper-guard
    isn't installed so transcription never hard-fails on a missing optional dep.
    """
    from .. import config
    if not config.WHISPER_GUARD_ENABLED:
        return segments
    try:
        from whisper_guard import filter_hallucinations
    except ImportError:
        # whisper-guard ships in the `whisper` extra; a partial install shouldn't
        # break transcription — just skip guarding.
        print("  [guard] whisper-guard not installed; skipping (pip install whisper-guard)")
        return segments
    return filter_hallucinations(segments)
