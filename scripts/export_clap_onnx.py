"""Export laion/larger_clap_general (pinned revision) to the ONNX files `search-sound` reads.

🔴 Run this ONCE, in a throwaway venv. It needs torch + transformers, which
reel-scout itself never imports -- the runtime (reel_scout/audio/clap.py) is
onnxruntime + numpy + tokenizers only.

    python -m venv /tmp/clap-export && . /tmp/clap-export/bin/activate
    pip install torch transformers onnx numpy huggingface_hub
    huggingface-cli download laion/larger_clap_general \\
        --revision 16c8cc3159a3c8a31e8ff5ef1f66b0d9ab3667db --local-dir <snapshot>
    python scripts/export_clap_onnx.py <snapshot> <out_dir>

<out_dir> is then REEL_SCOUT_CLAP_DIR (default
<REEL_SCOUT_DATA>/models/clap/larger_clap_general@16c8cc3/). It receives
clap_audio.onnx, clap_text.onnx, mel_slaney_513x64.npy, frontend_config.json
and a copy of the snapshot's tokenizer.json.

The runtime checks every file against the sha256 values in
reel_scout/audio/clap.py. Those were measured on an M2 Max export (torch legacy
exporter, opset 17); a different torch / transformers version can produce a
numerically equivalent graph with different bytes. If so, validate it (audio
and text cosine against the torch model) before updating the constants.

The optional int8 audio graph (clap_audio.int8.onnx, CLAP_AUDIO_VARIANT=int8) is
not produced by this script. The pinned one (sha256 in clap.py) agreed with
fp32 on retrieval top-1 for 84% of queries (top-10 overlap 92%); an int8 graph you
quantise yourself will hash differently and must be validated the same way
before its hash goes into clap.py.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

import numpy as np
import torch
from transformers import ClapFeatureExtractor, ClapModel


class Audio(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, input_features):
        e = self.m.get_audio_features(input_features=input_features)
        return getattr(e, "pooler_output", e)


class Text(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, input_ids, attention_mask):
        e = self.m.get_text_features(input_ids=input_ids, attention_mask=attention_mask)
        return getattr(e, "pooler_output", e)


def export(mod, args, names, dyn, path):
    kw = dict(input_names=names, output_names=["embeds"], dynamic_axes=dyn, opset_version=17)
    try:
        torch.onnx.export(mod, args, path, dynamo=False, **kw)
        return "legacy"
    except TypeError:
        torch.onnx.export(mod, args, path, **kw)
        return "default"


def main(snap, out):
    os.makedirs(out, exist_ok=True)
    model = ClapModel.from_pretrained(snap, torch_dtype=torch.float32).eval()
    fe = ClapFeatureExtractor.from_pretrained(snap)

    with torch.inference_mode():
        feats = torch.from_numpy(
            fe(np.zeros(480000, np.float32), sampling_rate=48000, return_tensors="np")["input_features"])
        print("audio input shape", tuple(feats.shape))
        how = export(Audio(model), (feats,), ["input_features"],
                     {"input_features": {0: "batch"}, "embeds": {0: "batch"}},
                     os.path.join(out, "clap_audio.onnx"))
        print("audio exported via", how)

        ids = torch.tensor([[0, 713, 16, 10, 1296, 2]], dtype=torch.long)
        mask = torch.ones_like(ids)
        how = export(Text(model), (ids, mask), ["input_ids", "attention_mask"],
                     {"input_ids": {0: "batch", 1: "seq"}, "attention_mask": {0: "batch", 1: "seq"},
                      "embeds": {0: "batch"}},
                     os.path.join(out, "clap_text.onnx"))
        print("text exported via", how)

    np.save(os.path.join(out, "mel_slaney_513x64.npy"), np.asarray(fe.mel_filters_slaney, np.float64))
    with open(os.path.join(out, "frontend_config.json"), "w") as fh:
        json.dump({k: v for k, v in fe.to_dict().items() if not k.startswith("mel_filters")},
                  fh, indent=2, default=str)
    tok = os.path.join(snap, "tokenizer.json")
    if os.path.exists(tok):
        shutil.copyfile(tok, os.path.join(out, "tokenizer.json"))
    for f in sorted(os.listdir(out)):
        print(f, round(os.path.getsize(os.path.join(out, f)) / 1e6, 1), "MB")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python scripts/export_clap_onnx.py <snapshot_dir> <out_dir>")
    main(sys.argv[1], sys.argv[2])
