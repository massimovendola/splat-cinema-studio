"""Demo helper: re-run the last rendered camera path (frames already on the bridge) with several
styles, then stack the results side by side. Usage: python tools/style_grid.py  (bridge must be running)."""
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
SCENE = "An aerial view of a castle with walls, towers and lawns"
TAIL = (f"{SCENE}, fully rendered in this style, with a natural sky and soft distant background. The camera performs a "
        "smooth slow orbit around the subject in one continuous shot, no cuts, no scene changes, the same location throughout.")
# (style prompt, keep_look): lower keep_look frees the model from the daylight first frame, needed for big changes like night
STYLES = {
    "candy": ("A castle made entirely of colourful candy: pink and mint frosting walls, red and yellow gumdrop towers, "
              "glossy sugar glaze, sprinkles, vivid saturated colours, green candy-floss lawns.", 0.15),
    "neon": ("Cyberpunk night scene: pitch dark night sky with stars, the castle walls glowing with bright magenta and cyan "
             "neon light strips, glowing neon windows, wet reflective ground, volumetric fog, high contrast, no daylight.", 0.0),
    "anime": ("Hand-painted anime film frame, watercolour storybook look: flat pastel colour, bold ink outlines, visible brush "
              "strokes, bright blue sky with big white clouds, rounded cartoon trees, bright flat colours, no photographic detail.", 0.0),
}
only = sys.argv[1:] or list(STYLES)          # e.g. `python tools/style_grid.py neon anime` to redo just those

for name, (style, keep) in STYLES.items():
    if name not in only:
        continue
    prompt = f"{style} {TAIL}"
    req = urllib.request.Request("http://localhost:8787/generate",
                                 json.dumps({"prompt": prompt, "name": name, "keep_look": keep}).encode(),
                                 {"Content-Type": "application/json"})
    print(name, json.load(urllib.request.urlopen(req, timeout=900)))

ins = [str(ROOT / "outputs" / f"{n}.mp4") for n in STYLES]
cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", *sum((["-i", i] for i in ins), []),
       "-filter_complex", "hstack=inputs=3", "-an", str(ROOT / "outputs" / "styles_side_by_side.mp4")]
subprocess.run(cmd, check=True, capture_output=True)
print("wrote outputs/styles_side_by_side.mp4")
