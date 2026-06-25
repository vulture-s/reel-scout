"""Convert PANNs Cnn14 (.pth) -> ONNX for reel-scout (input: raw 32k waveform window, output: (1,527))."""
import os
from pathlib import Path
import torch
import torch.nn as nn
from panns_inference.models import Cnn14
from panns_inference.config import labels

HOME = str(Path.home())
CKPT = f"{HOME}/panns_data/Cnn14_mAP=0.431.pth"
OUT_DIR = os.path.join(HOME, "Projects", "reel-scout", "data", "panns")
os.makedirs(OUT_DIR, exist_ok=True)
ONNX_PATH = os.path.join(OUT_DIR, "cnn14.onnx")
LABELS_PATH = os.path.join(OUT_DIR, "class_labels.txt")

assert len(labels) == 527, f"expected 527 labels, got {len(labels)}"

model = Cnn14(sample_rate=32000, window_size=1024, hop_size=320,
              mel_bins=64, fmin=50, fmax=14000, classes_num=527)
ckpt = torch.load(CKPT, map_location="cpu")
model.load_state_dict(ckpt["model"])
model.eval()


class ClipwiseWrapper(nn.Module):
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, x):
        return self.m(x)["clipwise_output"]


wrapped = ClipwiseWrapper(model).eval()
dummy = torch.randn(1, 64000)  # 2.0s @ 32kHz

with torch.no_grad():
    torch.onnx.export(
        wrapped, dummy, ONNX_PATH,
        input_names=["waveform"], output_names=["clipwise_output"],
        dynamic_axes={"waveform": {0: "batch", 1: "time"},
                      "clipwise_output": {0: "batch"}},
        opset_version=17, do_constant_folding=True,
    )
print("exported:", ONNX_PATH, os.path.getsize(ONNX_PATH) // (1024 * 1024), "MB")

with open(LABELS_PATH, "w", encoding="utf-8") as f:
    for l in labels:
        f.write(l + "\n")
print("labels:", LABELS_PATH, len(labels))

# Sanity: run ONNX vs torch on same input, compare top class
import numpy as np
import onnxruntime
sess = onnxruntime.InferenceSession(ONNX_PATH)
onnx_out = sess.run(None, {"waveform": dummy.numpy().astype(np.float32)})[0]
with torch.no_grad():
    torch_out = wrapped(dummy).numpy()
print("onnx shape:", onnx_out.shape, "torch shape:", torch_out.shape)
print("max abs diff:", float(np.abs(onnx_out - torch_out).max()))
print("onnx top class:", labels[int(onnx_out[0].argmax())], "torch top class:", labels[int(torch_out[0].argmax())])
print("OK")
