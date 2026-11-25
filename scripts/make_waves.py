"""Procedural luminous silk-wave background (original asset), black with icy white glow."""
import sys
import numpy as np
from PIL import Image, ImageFilter

W, H = 1080, 2340
rng = np.random.default_rng(7)
y = np.arange(H, dtype=np.float32)[:, None]
x = np.arange(W, dtype=np.float32)[None, :]
acc = np.zeros((H, W), np.float32)

# a bundle of thin ribbons following a smooth wave, centred in the upper third
for i in range(46):
    t = i / 45.0
    base = H * 0.30 + (t - 0.5) * 260
    amp = 140 + 60 * np.sin(t * 3.1)
    ph = 0.6 * np.sin(t * 2.3)
    curve = base + amp * np.sin(x / W * 2.6 * np.pi + ph) + 70 * np.sin(x / W * 5.3 * np.pi + t * 4)
    d = np.abs(y - curve)
    width = 1.2 + 2.5 * (1 - abs(t - 0.5) * 2)
    bright = 0.35 + 0.65 * np.exp(-((t - 0.45) ** 2) / 0.05)
    acc += bright * np.exp(-(d / width) ** 2)

# second, softer bundle lower down
for i in range(30):
    t = i / 29.0
    base = H * 0.78 + (t - 0.5) * 180
    curve = base - 110 * np.sin(x / W * 2.1 * np.pi + 1.2 + t) + 40 * np.sin(x / W * 6 * np.pi + t * 3)
    d = np.abs(y - curve)
    acc += 0.35 * np.exp(-(d / 1.6) ** 2)

acc = acc / acc.max()
core = np.clip(acc * 1.8, 0, 1)
img = Image.fromarray((core * 255).astype(np.uint8))
glow1 = np.asarray(img.filter(ImageFilter.GaussianBlur(6)), np.float32) / 255
glow2 = np.asarray(img.filter(ImageFilter.GaussianBlur(28)), np.float32) / 255
lum = np.clip(core * 0.9 + glow1 * 1.2 + glow2 * 1.6, 0, 1)
# vignette so cards stay readable; overall dim
vy = (np.arange(H)[:, None] / H - 0.5) * 2
vx = (np.arange(W)[None, :] / W - 0.5) * 2
vig = np.clip(1 - 0.35 * (vx ** 2 + vy ** 2), 0, 1)
lum = lum * vig * 0.85
ice = np.array([0.86, 0.95, 1.0], np.float32)   # icy white-cyan tint
rgb = np.clip(lum[..., None] * ice[None, None, :] * 255 + 4, 0, 255).astype(np.uint8)
out = Image.fromarray(rgb, "RGB")
out.save(sys.argv[1], "JPEG", quality=86, optimize=True, progressive=True)
print(sys.argv[1], out.size)

