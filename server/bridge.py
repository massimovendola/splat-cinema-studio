"""Local bridge: viewer posts guide-pass frames, this encodes them, runs the LTX IC-LoRA
workflow on Comfy Cloud through comfy-cli, and serves the result back.

    python server/bridge.py          # then open http://localhost:8787
Needs: comfy-cli signed in (comfy cloud login) or COMFY_CLOUD_API_KEY set, plus imageio[ffmpeg].
"""
import json
import os
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / ".tmp_frames"
WORKFLOW = ROOT / "workflows" / "video_ltx2_3_ic_lora.json"
RUN_WF = ROOT / "workflows" / ".run.json"
RUN_API = ROOT / "workflows" / ".run_api.json"
ENV = {**os.environ, "GIT_PYTHON_REFRESH": "quiet", "PYTHONIOENCODING": "utf-8"}
PORT = 8787
FPS = 24

# widget addresses inside the template's subgraph (see workflows/README.md)
SLOT_VIDEO, SLOT_IMAGE, SLOT_PROMPT, SLOT_ENHANCE = "199.file", "200.image", "129.text", "129.value_4"


def comfy(*args: str) -> dict:
    p = subprocess.run(["comfy", "--json", *args], cwd=ROOT, env=ENV, capture_output=True, text=True, encoding="utf-8")
    try:
        env = json.loads(next(l for l in reversed(p.stdout.splitlines()) if l.startswith("{")))
    except Exception:
        raise RuntimeError(f"comfy {' '.join(args[:2])} gave no JSON: {p.stdout[-300:]} {p.stderr[-300:]}")
    if not env.get("ok"):
        raise RuntimeError(f"comfy {' '.join(args[:2])}: {env.get('error', {}).get('message')}")
    return env["data"]


def cloud_names() -> dict:
    comfy("assets", "push")
    lock = json.loads((ROOT / ".comfy" / "assets.lock.json").read_text(encoding="utf-8"))
    return {name: a["cloud_name"] for name, a in lock["assets"].items()}


SLOT_IMG_STRENGTH = "129/198.strength"   # LTXVImgToVideoInplace: how hard the first frame is pinned


def generate(prompt: str, name: str = "latest", keep_look: float = 0.5) -> str:
    depth = [FRAMES / f"depth_{i:03d}.png" for i in range(len(list(FRAMES.glob("depth_*.png"))))]
    if not depth:
        raise RuntimeError("no depth frames received")
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    # fill pinholes between sprites: grey max filter (near is bright) then a light blur
    grey = np.stack([np.asarray(Image.open(f).convert("L").filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1.2)))
                     for f in depth]).astype(np.float32)
    # stretch contrast over the whole clip (2nd to 98th percentile of non-empty pixels) so the control keeps surface structure
    lo, hi = np.percentile(grey[grey > 8], (2, 98))
    grey = np.clip((grey - lo) / max(hi - lo, 1.0), 0, 1) * 255
    # empty space (no splats) is pure black = "infinitely far" with no structure, which LTX fills with artifacts.
    # Give it a smooth, deliberate distant backdrop instead: a gentle vertical ramp that reads as sky and haze.
    h, w = grey.shape[1:]
    ramp = (10 + 22 * (np.arange(h, dtype=np.float32) / h))[None, :, None]
    empty = np.stack([np.asarray(Image.fromarray(((g < 4) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0 for g in grey])
    soft = np.stack([np.asarray(Image.fromarray(m.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(3)), dtype=np.float32) / 255 for m in empty])
    grey = grey * (1 - soft) + ramp * soft
    clean = [np.repeat(g.astype(np.uint8)[..., None], 3, axis=-1) for g in grey]
    imageio.mimwrite(assets / "run_depth.mp4", clean, fps=FPS,
                     codec="libx264", quality=8, macro_block_size=1)
    # same treatment for the first RGB frame: replace the black void with a soft sky gradient
    first = np.asarray(Image.open(FRAMES / "first_000.png").convert("RGB")).astype(np.float32)
    void = Image.fromarray(((first.max(axis=-1) < 14) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(3))
    m = (np.asarray(void, dtype=np.float32) / 255)[..., None]
    t = (np.arange(first.shape[0], dtype=np.float32) / first.shape[0])[:, None, None]
    sky = (1 - t) * np.array([150, 178, 215], np.float32) + t * np.array([214, 222, 232], np.float32)
    Image.fromarray((first * (1 - m) + sky * m).astype(np.uint8)).save(assets / "run_first.png")
    names = cloud_names()
    shutil.copy(WORKFLOW, RUN_WF)
    comfy("workflow", "set-slot", str(RUN_WF),
          f"{SLOT_VIDEO}={names['run_depth.mp4']}", f"{SLOT_IMAGE}={names['run_first.png']}",
          f"{SLOT_PROMPT}={prompt}", f"{SLOT_ENHANCE}=false", f"{SLOT_IMG_STRENGTH}={keep_look}")
    # The prompt enhancer ignores the user's text and invents a scene from the image (it wrote a cafe with a
    # barista for a castle), so it is bypassed. The frontend graph wires the raw prompt into the switch's
    # on_false, but the CLI's conversion to API format drops that link, so restore it as a literal here.
    api = comfy("run", "--workflow", str(RUN_WF), "--where", "cloud", "--print-prompt")["prompt"]
    api["129:211"]["inputs"]["on_false"] = prompt
    api["129:212"]["inputs"]["value"] = False
    RUN_API.write_text(json.dumps(api), encoding="utf-8")
    run = comfy("run", "--workflow", str(RUN_API), "--where", "cloud", "--wait", "--timeout", "900")
    out = comfy("download", run["prompt_id"])
    # node 68 is the SaveVideo node; node 199 is the echoed control video
    result = next(f["path"] for f in out["files"] if str(f.get("node_id")) == "68")
    shutil.copy(result, ROOT / "outputs" / f"{name}.mp4")
    return f"/outputs/{name}.mp4"


class H(BaseHTTPRequestHandler):
    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204)

    def do_GET(self):
        path = self.path.split("?")[0]
        f = ROOT / "viewer" / "index.html" if path == "/" else ROOT / path.lstrip("/")
        if f.is_file() and ROOT in f.resolve().parents and f.suffix in {".html", ".mp4", ".png"}:
            self._send(200, f.read_bytes(), {".html": "text/html", ".mp4": "video/mp4", ".png": "image/png"}[f.suffix])
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        parts = self.path.strip("/").split("/")
        try:
            if parts[0] == "reset":
                shutil.rmtree(FRAMES, ignore_errors=True)
                FRAMES.mkdir()
                self._send(200, b"{}")
            elif parts[0] == "frame":
                kind, i = parts[1], int(parts[2])
                (FRAMES / f"{kind}_{i:03d}.png").write_bytes(body)
                self._send(200, b"{}")
            elif parts[0] == "generate":
                req = json.loads(body)
                video = generate(req["prompt"], "".join(c for c in req.get("name", "latest") if c.isalnum() or c in "_-"),
                                 min(1.0, max(0.0, float(req.get("keep_look", 0.5)))))
                self._send(200, json.dumps({"video": video}).encode())
            else:
                self._send(404, b"{}")
        except Exception as e:
            print("error:", e, file=sys.stderr)
            self._send(500, json.dumps({"error": str(e)}).encode())

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Splat Cinema Studio on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()   # local only: this endpoint spends cloud credits
