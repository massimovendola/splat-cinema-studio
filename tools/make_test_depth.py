"""Synthetic depth push-in through a boxy corridor, for testing the LTX control workflow
before the splat viewer exists. Writes assets/test_depth.mp4 and assets/test_first.png."""
import sys
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image

W, H, FRAMES, FPS = 768, 512, 97, 24
out = Path(sys.argv[1] if len(sys.argv) > 1 else "assets")
out.mkdir(parents=True, exist_ok=True)

ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
x = (xs - W / 2) / (H / 2)
y = (ys - H / 2) / (H / 2)


def depth_frame(t: float) -> np.ndarray:
    """Rectangular tunnel with pillars; camera pushes forward by t in [0, 1]."""
    cam_z = t * 6.0
    # distance along view ray to the tunnel walls (half-width 1.2, half-height 0.8)
    tx = np.where(np.abs(x) > 1e-4, 1.2 / np.abs(x), 1e4)
    ty = np.where(np.abs(y) > 1e-4, 0.8 / np.abs(y), 1e4)
    z = np.minimum(tx, ty)
    # pillars every 2 units, bright bands that move toward the camera
    pillar = ((z + cam_z) % 2.0) < 0.25
    z = np.where(pillar, z - 0.15, z)
    z = np.clip(z, 0.5, 12.0)
    d = 1.0 - (np.log(z) - np.log(0.5)) / (np.log(12.0) - np.log(0.5))  # near = bright
    return (np.clip(d, 0, 1) * 255).astype(np.uint8)


frames = [np.stack([depth_frame(i / (FRAMES - 1))] * 3, axis=-1) for i in range(FRAMES)]
imageio.mimwrite(out / "test_depth.mp4", frames, fps=FPS, codec="libx264", quality=8, macro_block_size=1)

first = frames[0].astype(np.float32) / 255
tint = np.array([1.0, 0.75, 0.5], dtype=np.float32)
Image.fromarray((first * tint * 255).astype(np.uint8)).save(out / "test_first.png")
print("wrote", out / "test_depth.mp4", out / "test_first.png")
