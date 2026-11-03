# Splat Cinema Studio

An open-source take on cinema studio tools. Load a real gaussian splat or lidar scan as a virtual set, design a camera move inside it, then generate a stylized cinematic shot with LTX 2.3 that follows the real geometry.

Built at the Comfy "Open Source Higgsfield" build night, on the Comfy Developer Platform (Comfy Cloud API via comfy-cli).

## How it works

1. The viewer (three.js) loads a `.ply` splat or point cloud.
2. You pick a camera move (orbit or push-in) and a style prompt.
3. The viewer renders a depth pass along the camera path (97 frames, 768x512) plus the first RGB frame.
4. The local bridge encodes the depth clip, uploads it to Comfy Cloud, and runs the **LTX 2.3 IC-LoRA Union Control** workflow (`workflows/video_ltx2_3_ic_lora.json`, the stock Comfy template).
5. The stylized shot comes back and plays in the viewer.

Same scan, same camera move, any style: change the prompt and render again.

## Run it

Requirements: Python 3.10+, a Comfy Cloud account with API access.

```bash
pip install -U comfy-cli imageio imageio-ffmpeg numpy pillow
comfy cloud login            # or set COMFY_CLOUD_API_KEY
python server/bridge.py
```

Open http://localhost:8787, load a `.ply` (or click the procedural sample), choose a move and style, then press **Render depth and send to LTX**. A render takes about 2 to 3 minutes (frame upload plus about a minute of LTX).

No local GPU or ComfyUI install is needed; generation runs on Comfy Cloud.

## Scenes

Binary little-endian PLY, either a gaussian splat (`f_dc_*` colors, low-opacity splats are dropped) or a colored point cloud. Splat centers are rendered as point sprites for the guide passes, so very sparse scans need a larger point size.

## Layout

- `viewer/index.html`: three.js viewer, camera presets, depth and RGB passes
- `server/bridge.py`: frame intake, encoding, Comfy Cloud job, result serving
- `workflows/video_ltx2_3_ic_lora.json`: unmodified Comfy template used for generation
- `tools/make_test_depth.py`: synthetic depth clip for testing the workflow without a scan

## Notes on the workflow

- Control input is node `199` (video) and first frame is node `200` (image). Prompt is `129.text`.
- Prompt enhance (`129.value_4`) is switched off. The enhancer ignores the user's prompt and invents a scene from the first frame. With it off, comfy-cli's conversion to API format drops the If/Else switch's `on_false` link (the raw prompt), so the encoder receives `None`. `server/bridge.py` restores it by patching node `129:211` in the converted prompt.
- First-frame strength (`129/198.strength`) is exposed as "Keep original look" in the viewer. Lower values give the style prompt more influence.
- Depth convention: near is bright, far is dark, log-scaled between the fitted near and far distances.

## License

MIT
