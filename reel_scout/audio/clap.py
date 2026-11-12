"""Text-to-sound embeddings: LAION CLAP (laion/larger_clap_general) as ONNX, no torch.

What this module is for: "find the reel with a door slam in it". CLAP puts audio
and English text in one 512-d space, so a sound is found by describing it. The
audio of each clip is cut into 10 s windows (5 s hop), each window gets one
embedding, and `clap_search` ranks windows by cosine against the query text.

## Why ONNX and not transformers

The model was exported once (``scripts/export_clap_onnx.py``, which is the only
place torch + transformers are needed) into two graphs -- audio and text -- plus
the slaney mel matrix. Inference here is onnxruntime + numpy + tokenizers. The
export was checked against the HF torch model on 48 real clips x 50 texts:
audio / text cosine >= 0.9999999, retrieval top-1 and top-10 identical, 0.074 s
per window on an M2 Max (fp32). The int8 audio graph is optional: 3.6x smaller,
2x faster, but its retrieval top-1 agrees with fp32 for only 84% of queries
(top-10 overlap 92%) -- so fp32 is the default.

## Front end (mirrors ClapFeatureExtractor, inference path only)

48 kHz mono; a window of at most 10 s; shorter windows are *repeat-padded*
(``np.tile(x, int(N / len(x)))`` then zero-padded to 480000 -- the inference
half of ``rand_trunc`` / ``repeatpad``; the random crop never runs because
windows are cut here and are never longer than 10 s). Periodic Hann, reflect pad
512, n_fft 1024, hop 480, power spectrum x slaney mel (513 x 64),
``10 * log10(max(1e-10, .))`` -> (1001, 64).

## The tokenizer trap

``tokenizer.json`` carries its own padding config. Without ``tok.no_padding()``
every encoding in a batch is padded to the longest one, ``len(e.ids)`` is the
padded length, the attention mask is all ones, and a short query's embedding
drifts to cosine ~0.45 against the right answer -- silently, with plausible
looking results. ``tokenize`` turns padding off and takes the mask from each
encoding. ``tests/test_clap.py`` holds the regression test.

## Model files are not in the repo

They live in ``config.CLAP_MODEL_DIR`` (``REEL_SCOUT_CLAP_DIR``; default
``<REEL_SCOUT_DATA>/models/clap/larger_clap_general@16c8cc3/``) and are checked
against the sha256 values below on load, so a half-copied file or a different
export is refused instead of producing quietly different vectors.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from .. import config

MODEL_ID = "laion/larger_clap_general"
MODEL_REVISION = "16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db"
MODEL_TAG = "larger_clap_general@16c8cc3"

SR = 48000
WINDOW_S = 10.0
HOP_S = 5.0
N = int(WINDOW_S * SR)        # 480000 samples
HOP_N = int(HOP_S * SR)
N_FFT = 1024
STFT_HOP = 480
N_MELS = 64
N_FRAMES = 1 + N // STFT_HOP  # 1001
DIM = 512

#: sha256 of every file the runtime reads, measured on the M2 Max export
#: (2026-11-12). A mismatch is refused, not warned about.
SHA256 = {
    "clap_audio.onnx": "0c90f379fc000b25bff2cba0e72eb9126056a66b0a01209b938fdb9dc92ad14f",
    "clap_audio.int8.onnx": "9f8fad4e5000a42266b36934c10df3db0a0741afb0e4dfe36d10a91a86a14ec7",
    "clap_text.onnx": "a6ef9d2ea3e3761212d1b2c3735355579de771454cf8f1bb6173214297513210",
    "mel_slaney_513x64.npy": "ca2e08b79fee81395be082d59d85ff5c23a4a2bb3f69120a0237281fe915fe90",
    "tokenizer.json": "dc239041d98de27ffc3975473a1a23e3db4c937b23c138c38bbc66588bd247e5",
}

AUDIO_FILES = {"fp32": "clap_audio.onnx", "int8": "clap_audio.int8.onnx"}
TEXT_FILE = "clap_text.onnx"
MEL_FILE = "mel_slaney_513x64.npy"
TOKENIZER_FILE = "tokenizer.json"

INSTALL_HINT = 'pip install "reel-scout[clap]"'


class ClapUnavailable(RuntimeError):
    """CLAP cannot run here: an optional dependency or a model file is missing.

    Always carries a message that says what to install or where to put what.
    """


class NoAudio(Exception):
    """The input has no audio stream to embed."""


# --- dependencies ------------------------------------------------------------

def _require_numpy():
    try:
        import numpy as np  # noqa: F401
    except ImportError:
        raise ClapUnavailable("CLAP needs numpy: %s" % INSTALL_HINT)
    return np


def require_deps() -> Tuple[Any, Any, Any]:
    """(numpy, onnxruntime, tokenizers.Tokenizer) or ClapUnavailable naming the extra."""
    missing = []
    try:
        import numpy as np
    except ImportError:
        np = None
        missing.append("numpy")
    try:
        import onnxruntime as ort
    except ImportError:
        ort = None
        missing.append("onnxruntime")
    try:
        from tokenizers import Tokenizer
    except ImportError:
        Tokenizer = None
        missing.append("tokenizers")
    if missing:
        raise ClapUnavailable(
            "CLAP sound search needs %s, which %s not installed: %s"
            % (", ".join(missing), "is" if len(missing) == 1 else "are", INSTALL_HINT))
    return np, ort, Tokenizer


# --- model files -------------------------------------------------------------

def model_dir() -> str:
    return getattr(config, "CLAP_MODEL_DIR", "") or os.path.join(
        config.DATA_DIR, "models", "clap", MODEL_TAG)


def audio_variant() -> str:
    v = (getattr(config, "CLAP_AUDIO_VARIANT", "") or "fp32").strip().lower()
    if v not in AUDIO_FILES:
        raise ClapUnavailable("CLAP_AUDIO_VARIANT must be fp32 or int8, got %r" % v)
    return v


def _missing_message(d: str, missing: List[str]) -> str:
    return (
        "CLAP model files missing in %s: %s\n"
        "  Put the ONNX export of %s (revision %s) there, or point REEL_SCOUT_CLAP_DIR at it.\n"
        "  To make it yourself (once, needs torch + transformers, not reel-scout's runtime):\n"
        "    huggingface-cli download %s --revision %s --local-dir <snapshot>\n"
        "    python scripts/export_clap_onnx.py <snapshot> %s\n"
        "  The export also writes tokenizer.json; copy it from <snapshot> if absent."
        % (d, ", ".join(missing), MODEL_ID, MODEL_REVISION, MODEL_ID, MODEL_REVISION, d))


_HASH_OK: Dict[Tuple[str, int, float], bool] = {}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_model_dir(d: Optional[str] = None, variant: Optional[str] = None,
                    verify_hash: bool = True) -> Dict[str, str]:
    """Paths of the files this variant needs; ClapUnavailable if any is absent or wrong."""
    d = d or model_dir()
    variant = variant or audio_variant()
    needed = [AUDIO_FILES[variant], TEXT_FILE, MEL_FILE, TOKENIZER_FILE]
    missing = [f for f in needed if not os.path.isfile(os.path.join(d, f))]
    if missing:
        raise ClapUnavailable(_missing_message(d, missing))
    paths = {f: os.path.join(d, f) for f in needed}
    if verify_hash:
        for f, p in paths.items():
            st = os.stat(p)
            key = (os.path.abspath(p), st.st_size, st.st_mtime)
            if _HASH_OK.get(key):
                continue
            got = sha256_file(p)
            if got != SHA256[f]:
                raise ClapUnavailable(
                    "CLAP model file %s has sha256 %s, expected %s (%s @ %s).\n"
                    "  A partial copy or a different export -- re-copy it or re-run "
                    "scripts/export_clap_onnx.py." % (p, got, SHA256[f], MODEL_ID, MODEL_REVISION[:7]))
            _HASH_OK[key] = True
    return {"audio": paths[AUDIO_FILES[variant]], "text": paths[TEXT_FILE],
            "mel": paths[MEL_FILE], "tokenizer": paths[TOKENIZER_FILE]}


def availability() -> Optional[str]:
    """None when CLAP can run here, else the one-line reason it cannot (no hashing)."""
    try:
        require_deps()
        check_model_dir(verify_hash=False)
    except ClapUnavailable as e:
        return str(e).split("\n")[0]
    return None


# --- front end (numpy) -------------------------------------------------------

def hann_periodic(n: int):
    np = _require_numpy()
    return 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)


def pad_repeat(x):
    """<= 10 s mono window -> exactly N samples, the way ClapFeatureExtractor repeatpads."""
    np = _require_numpy()
    x = np.asarray(x, np.float32)
    if len(x) == 0:
        raise ValueError("empty window")
    if len(x) > N:
        raise ValueError("window longer than 10 s: split it first")
    if len(x) < N:
        x = np.tile(x, int(N / len(x)))
        x = np.pad(x, (0, N - len(x)))
    return x


def log_mel(x, mel):
    """(480000,) -> (1001, 64) float32 log-mel, as ClapFeatureExtractor._np_extract_fbank_features."""
    np = _require_numpy()
    x = np.asarray(x, np.float64)
    x = np.pad(x, (N_FFT // 2, N_FFT // 2), mode="reflect")
    n_frames = 1 + (len(x) - N_FFT) // STFT_HOP
    idx = np.arange(N_FFT)[None, :] + STFT_HOP * np.arange(n_frames)[:, None]
    frames = x[idx] * hann_periodic(N_FFT)
    spec = np.abs(np.fft.rfft(frames, n=N_FFT, axis=1)) ** 2          # (frames, 513)
    m = np.maximum(1e-10, spec @ mel)                                  # (frames, 64)
    return (10.0 * np.log10(m)).astype(np.float32)


def features(windows: Sequence[Any], mel):
    """list of <=10 s mono 48 kHz arrays -> (B, 1, 1001, 64) float32."""
    np = _require_numpy()
    return np.stack([log_mel(pad_repeat(w), mel)[None] for w in windows]).astype(np.float32)


def tokenize(tok, texts: Sequence[str]):
    """tokenizers.Tokenizer -> (input_ids, attention_mask) int64, right-padded with <pad>.

    Padding is switched off first and the mask comes from each encoding, never
    from ``len(ids)`` -- see the module docstring for what goes wrong otherwise.
    """
    np = _require_numpy()
    tok.no_padding()
    enc = tok.encode_batch(list(texts))
    L = max(len(e.ids) for e in enc)
    pad = tok.token_to_id("<pad>")
    if pad is None:
        pad = 1
    ids = np.full((len(enc), L), pad, np.int64)
    mask = np.zeros((len(enc), L), np.int64)
    for i, e in enumerate(enc):
        ids[i, :len(e.ids)] = e.ids
        mask[i, :len(e.ids)] = e.attention_mask
    return ids, mask


def l2norm(e):
    np = _require_numpy()
    e = np.asarray(e, np.float32)
    if e.ndim == 1:
        return e / (np.linalg.norm(e) + 1e-12)
    return e / (np.linalg.norm(e, axis=1, keepdims=True) + 1e-12)


# --- windowing ---------------------------------------------------------------

def window_starts(n_samples: int) -> List[int]:
    """Start offsets (samples) of the 10 s / 5 s-hop windows over a clip.

    A clip of 10 s or less is one window. After that a window starts every 5 s
    while it still brings audio the previous window did not cover, so the last
    window may be 5-10 s long (it is repeat-padded like any short clip) and a
    tail already inside the previous window is not embedded twice.
    """
    if n_samples <= 0:
        return []
    if n_samples <= N:
        return [0]
    return [s for s in range(0, n_samples, HOP_N) if s == 0 or s + (N - HOP_N) < n_samples]


def iter_windows(samples) -> Iterator[Tuple[int, float, float, Any]]:
    """(idx, start_s, end_s, window) over an in-memory 48 kHz mono array."""
    n = len(samples)
    for i, s in enumerate(window_starts(n)):
        w = samples[s:s + N]
        yield i, s / float(SR), (s + len(w)) / float(SR), w


def _ffmpeg_cmd(path: str) -> List[str]:
    return [config.FFMPEG_BIN, "-nostdin", "-hide_banner", "-v", "error",
            "-i", path, "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(SR),
            "-f", "f32le", "-"]


def stream_windows(path: str, timeout: int = 3600) -> Iterator[Tuple[int, float, float, Any]]:
    """Decode a media file's first audio stream at 48 kHz and yield its windows.

    Streams ffmpeg's stdout so a multi-hour file is never held in memory whole
    (3 h at 48 kHz float32 is 2 GB): only the current 10 s window is buffered.
    Raises NoAudio for a file with no audio stream.
    """
    np = _require_numpy()
    proc = subprocess.Popen(_ffmpeg_cmd(path), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    buf = np.zeros(0, np.float32)
    pos = 0          # absolute sample offset of buf[0]
    idx = 0
    next_start = 0
    total = 0
    leftover = b""
    try:
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read(HOP_N * 4)
            eof = not chunk
            if chunk:
                chunk = leftover + chunk
                cut = len(chunk) - (len(chunk) % 4)
                leftover = chunk[cut:]
                arr = np.frombuffer(chunk[:cut], np.float32)
                buf = np.concatenate([buf, arr])
                total += len(arr)
            # emit every full window that is ready
            while next_start + N <= pos + len(buf):
                off = next_start - pos
                w = buf[off:off + N].copy()
                yield idx, next_start / float(SR), (next_start + N) / float(SR), w
                idx += 1
                next_start += HOP_N
                drop = next_start - pos
                if drop > 0:
                    buf = buf[drop:]
                    pos = next_start
            if eof:
                break
        proc.wait(timeout=timeout)
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        if proc.returncode != 0:
            if "matches no streams" in err or "does not contain any stream" in err:
                raise NoAudio("no audio stream in %s" % path)
            raise RuntimeError("ffmpeg audio decode failed: %s" % err.strip()[-300:])
        if total == 0:
            raise NoAudio("no audio samples in %s" % path)
        # the tail: a final short window, under the same rule as window_starts
        if total <= N and idx == 0:
            yield 0, 0.0, total / float(SR), buf[:total].copy()
        elif next_start < total and next_start + (N - HOP_N) < total:
            off = next_start - pos
            w = buf[off:].copy()
            yield idx, next_start / float(SR), total / float(SR), w
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


# --- the model ---------------------------------------------------------------

class ClapOnnx:
    """The two ONNX graphs + front end. Construct via :func:`load`."""

    def __init__(self, audio_sess: Any, text_sess: Any, tokenizer: Any, mel: Any,
                 variant: str = "fp32", batch: int = 8) -> None:
        self.audio_sess = audio_sess
        self.text_sess = text_sess
        self.tokenizer = tokenizer
        self.mel = mel
        self.variant = variant
        self.batch = batch

    def embed_windows(self, windows: Sequence[Any]):
        """list of <=10 s windows -> (B, 512) L2-normalised float32."""
        np = _require_numpy()
        out = []
        for i in range(0, len(windows), self.batch):
            feats = features(windows[i:i + self.batch], self.mel)
            e = self.audio_sess.run(None, {"input_features": feats})[0]
            out.append(np.asarray(e, np.float32))
        if not out:
            return np.zeros((0, DIM), np.float32)
        return l2norm(np.concatenate(out))

    def embed_text(self, texts: Sequence[str]):
        """list of English strings -> (B, 512) L2-normalised float32."""
        ids, mask = tokenize(self.tokenizer, texts)
        e = self.text_sess.run(None, {"input_ids": ids, "attention_mask": mask})[0]
        return l2norm(e)

    def embed_file(self, path: str) -> List[Tuple[int, float, float, Any]]:
        """(idx, start_s, end_s, emb) for every window of a media file."""
        rows: List[Tuple[int, float, float, Any]] = []
        pending: List[Tuple[int, float, float, Any]] = []

        def flush() -> None:
            if not pending:
                return
            embs = self.embed_windows([p[3] for p in pending])
            for (i, s, e, _), v in zip(pending, embs):
                rows.append((i, s, e, v))
            del pending[:]

        for item in stream_windows(path):
            pending.append(item)
            if len(pending) >= self.batch:
                flush()
        flush()
        return rows


_LOADED: Dict[Tuple[str, str], ClapOnnx] = {}


def load(d: Optional[str] = None, variant: Optional[str] = None) -> ClapOnnx:
    """Load (once per process) and return the model, or raise ClapUnavailable."""
    np, ort, Tokenizer = require_deps()
    d = d or model_dir()
    variant = variant or audio_variant()
    key = (os.path.abspath(d), variant)
    if key in _LOADED:
        return _LOADED[key]
    paths = check_model_dir(d, variant)
    so = ort.SessionOptions()
    providers = ["CPUExecutionProvider"]
    audio = ort.InferenceSession(paths["audio"], so, providers=providers)
    text = ort.InferenceSession(paths["text"], so, providers=providers)
    tok = Tokenizer.from_file(paths["tokenizer"])
    mel = np.load(paths["mel"])
    m = ClapOnnx(audio, text, tok, mel, variant=variant)
    _LOADED[key] = m
    return m


def emb_to_blob(v) -> bytes:
    np = _require_numpy()
    return np.asarray(v, np.float32).tobytes()


def blob_to_emb(b: bytes):
    np = _require_numpy()
    return np.frombuffer(b, np.float32)


def index_video(conn: Any, video_id: str, path: str,
                model: Optional[ClapOnnx] = None) -> Dict[str, Any]:
    """Embed one clip's audio and store it (replacing any earlier index).

    Returns {"windows": n, "seconds": wall time, "duration_s": audio length}.
    Raises NoAudio / ClapUnavailable.
    """
    import time

    from .. import db

    np = _require_numpy()
    m = model or load()
    t0 = time.time()
    rows = m.embed_file(path)
    if not rows:
        raise NoAudio("no audio samples in %s" % path)
    mean = l2norm(np.mean(np.stack([r[3] for r in rows]), axis=0))
    duration = rows[-1][2]
    db.save_audio_clap(
        conn, video_id,
        windows=[(i, s, e, emb_to_blob(v)) for i, s, e, v in rows],
        mean_emb=emb_to_blob(mean), model=MODEL_ID, revision=MODEL_REVISION,
        variant=m.variant, dim=DIM, window_s=WINDOW_S, hop_s=HOP_S,
        duration_s=duration)
    return {"windows": len(rows), "seconds": time.time() - t0, "duration_s": duration}
