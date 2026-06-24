"""Convert PANNs Cnn14_16k checkpoint -> ONNX matching reel-scout's analyzer
contract: input (1, N) float32 raw 16kHz waveform -> output (1, 527) probs.
Also writes class_labels.txt (527 AudioSet display names, index order) beside it.
"""
import os
import sys
import torch
import numpy as np
from panns_inference.models import Cnn14
from panns_inference.config import labels

DATA = os.path.expanduser("~/panns_data")
CKPT = os.path.join(DATA, "Cnn14_16k_mAP=0.438.pth")
ONNX = os.path.join(DATA, "cnn14_16k.onnx")
LABELS_TXT = os.path.join(DATA, "class_labels.txt")

# 1. Build model + load weights (16kHz config, per panns Cnn14_16k)
# Cnn14_16k == Cnn14 backbone with the 16kHz spectrogram params used to train
# the Cnn14_16k_mAP=0.438 checkpoint.
model = Cnn14(sample_rate=16000, window_size=512, hop_size=160,
              mel_bins=64, fmin=50, fmax=8000, classes_num=527)
ck = torch.load(CKPT, map_location="cpu", weights_only=False)  # trusted official PANNs ckpt
model.load_state_dict(ck["model"])
model.eval()


class ClipwiseWrap(torch.nn.Module):
    """Cnn14 forward returns a dict; ONNX needs a tensor. Expose clipwise_output."""
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, x):
        return self.m(x)["clipwise_output"]


wrap = ClipwiseWrap(model).eval()

# 2. Export. 2s @ 16kHz = 32000 samples; sample dim dynamic so any window works.
dummy = torch.zeros(1, 32000, dtype=torch.float32)
with torch.no_grad():
    torch.onnx.export(
        wrap, dummy, ONNX,
        input_names=["waveform"], output_names=["clipwise"],
        dynamic_axes={"waveform": {1: "samples"}, "clipwise": {0: "batch"}},
        opset_version=17,
    )
print("exported:", ONNX, os.path.getsize(ONNX) // 1024, "KB")

# 3. Labels file (index order) beside the model
with open(LABELS_TXT, "w", encoding="utf-8") as f:
    for lbl in labels:
        f.write(lbl + "\n")
print("labels written:", LABELS_TXT, len(labels))

# 4. Sanity: run onnxruntime, compare to torch on a noise input
import onnxruntime as ort
sess = ort.InferenceSession(ONNX, providers=["CPUExecutionProvider"])
x = np.random.randn(1, 32000).astype(np.float32) * 0.1
onnx_out = sess.run(None, {"waveform": x})[0]
with torch.no_grad():
    torch_out = wrap(torch.from_numpy(x)).numpy()
print("onnx out shape:", onnx_out.shape, "| torch shape:", torch_out.shape)
print("max abs diff onnx-vs-torch:", float(np.max(np.abs(onnx_out - torch_out))))
top = int(np.argmax(onnx_out[0]))
print("sanity top class on noise:", labels[top], round(float(onnx_out[0][top]), 3))
print("OK" if onnx_out.shape == (1, 527) else "BAD SHAPE")
