# Audio analysis (PANNs) setup

Audio event detection (music / speech / silence / sound-effect timelines) is an
**optional** feature, off by default. The pipeline runs it only when audio is
explicitly requested (`analyze --no-skip-audio`, or MCP `analyze` with
`skip_audio=false`), and it needs an ONNX model that the repo does **not** bundle.

If audio is requested but the model/deps are missing, the pipeline now **fails
loud** with install guidance (it used to silently continue and emit
`has_background_music=false`). This doc is how to make it actually work.

## Contract the analyzer expects

`reel_scout/audio/panns.py` feeds the ONNX model **raw 16 kHz waveform** windows
of shape `(1, N)` (default 2 s → `(1, 32000)`) and expects clipwise AudioSet
probabilities `(1, 527)`. A `class_labels.txt` (527 AudioSet display names, index
order) must sit **beside** the model — labels are looked up by
`os.path.dirname(PANNS_MODEL_PATH)`.

## Steps

```bash
# 1. deps (torch is only needed to convert the checkpoint, not at runtime)
pip install onnxruntime panns_inference torchlibrosa onnxscript torch

# 2. AudioSet labels CSV (panns_inference imports it at module load)
mkdir -p ~/panns_data
curl -sSL -o ~/panns_data/class_labels_indices.csv \
  https://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv

# 3. Cnn14 16 kHz checkpoint (matches the 16 kHz wav the pipeline extracts)
curl -sSL -o "~/panns_data/Cnn14_16k_mAP=0.438.pth" \
  "https://zenodo.org/record/3987831/files/Cnn14_16k_mAP%3D0.438.pth?download=1"

# 4. convert .pth -> ONNX + write class_labels.txt (see scripts/convert_panns_onnx.py)
PYTHONUTF8=1 python scripts/convert_panns_onnx.py

# 5. point reel-scout at it (the MCP launcher auto-sets this if the file exists)
export PANNS_MODEL_PATH=~/panns_data/cnn14_16k.onnx

# 6. verify end-to-end
reel-scout analyze <url> --no-skip-audio --skip-vision --skip-transcribe
```

## Gotchas (hit during 2026-06-24 setup on Windows)

- **`Cnn14`, not `Cnn14_16k`** — `panns_inference.models` only exposes the
  parameterized `Cnn14`; build it with the 16 kHz params
  (`sample_rate=16000, window_size=512, hop_size=160, mel_bins=64, fmin=50,
  fmax=8000`) and load the `Cnn14_16k` state dict into it.
- **`torch.load(..., weights_only=False)`** — torch ≥2.6 defaults to
  `weights_only=True`, which rejects the numpy globals in the official checkpoint
  (it is trusted: zenodo PANNs release).
- **`PYTHONUTF8=1` on Windows** — `torch.onnx.export` prints a ✅ that crashes on
  a cp950 console; UTF-8 I/O avoids the `UnicodeEncodeError`.
- **External weights** — the exporter writes `cnn14_16k.onnx` (small graph) +
  `cnn14_16k.onnx.data` (~310 MB weights). They must stay **together**;
  onnxruntime resolves `.onnx.data` relative to the model file.
- A non-fatal `version_converter ... No Adapter To Version 17 for Pad` may print
  during export — the model is still written and verified (onnx-vs-torch output
  diff ~2e-7).

## Window overlap note

Windows are 2 s with a 1 s hop, so per-type second-sums **double-count** the
overlap (a 330 s video can report ~540 s of "speech"). Use **shares** (one type
divided by the sum of all types), not raw seconds / duration, when reporting
proportions.
