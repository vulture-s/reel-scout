# Changelog

## 0.2.0 — 2026-07-14

### Added
- Opt-in Whisper language controls for bilingual / code-switching audio
  (中英對照 interviews): `WHISPER_LANGUAGE`, `WHISPER_TASK`,
  `WHISPER_MULTILINGUAL`, `WHISPER_CHUNK_LENGTH`.
  - Working recipe for a ZH-host / EN-guest interview:
    `WHISPER_MULTILINGUAL=1 WHISPER_CHUNK_LENGTH=15`.
  - Fixes long-form language-lock drift where whisper `large-v3` "translates"
    the guest's English into garbled Chinese. Verified on a 40-min interview:
    latin-char recovery 56% -> 90%.
  - Defaults reproduce prior single-pass behavior; leave OFF for single-language
    short-form.
- `config check` now surfaces the new `WHISPER_*` values.
- `tests/test_transcribe.py` pins the config -> transcribe() kwargs mapping.

### Changed
- `faster-whisper` floor raised `>=0.10.0` -> `>=1.1.0` (the `multilingual`
  transcribe arg the fix relies on was added in 1.1).
