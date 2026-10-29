"""Paint the EMUlator with Flux dev in ComfyUI (img2img from the vector design).
python comfy_mascot.py <denoise> <seed> [<seed> ...]   -> round3/painted/emulator_<denoise>_<seed>.png"""
import json, sys, time, urllib.request, uuid, mimetypes
from pathlib import Path

HERE = Path(__file__).parent
API = "http://127.0.0.1:8188"
OUT = HERE / "painted"; OUT.mkdir(exist_ok=True)
PROMPT = (
    "cel-shaded comic book illustration in the style of Borderlands, thick black ink outlines, bold hand-drawn "
    "hatching and crosshatched shadows, flat saturated colors with hard-edged shadows, mascot character art. "
    "A crazy cyborg emu shown in side profile facing right, breathing a huge blast of orange and yellow fire out of "
    "its open beak. Real shaggy brown emu feathers, droopy and hair-like, a wild messy feathery crest on its head. "
    "The FRONT of its head is real bluish-grey emu skin and feathers; only the BACK of its skull is torn open, revealing a riveted chrome robot skull, and a small glowing red robot eye under the real eye, an angry steel "
    "brow plate frowning over a huge bulging bloodshot orange googly eye with a tiny pupil, a long flat grey emu beak with a jagged steel "
    "lower jaw, a floppy pink tongue hanging out, drool. Exposed metal neck vertebrae with a pink cable. A torn, "
    "burnt red cloth rag knotted around its neck, frayed ends flapping. A chrome robot hand gripping a retro "
    "SNES-style game controller with colorful buttons. Menacing and goofy at the same time. Dark navy background.")

def call(path, data=None, ctype="application/json"):
    req = urllib.request.Request(API + path, data=data, headers={"Content-Type": ctype} if data else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")

def upload(png: Path) -> str:
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{png.name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + png.read_bytes() + \
           f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n".encode()
    return call("/upload/image", body, f"multipart/form-data; boundary={b}")["name"]

def graph(img, denoise, seed):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev.safetensors", "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp8_e4m3fn.safetensors", "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": img}},
        "5": {"class_type": "VAEEncode", "inputs": {"pixels": ["4", 0], "vae": ["3", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT, "clip": ["2", 0]}},
        "7": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["6", 0], "guidance": 3.5}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "9": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["7", 0], "negative": ["8", 0],
              "latent_image": ["5", 0], "seed": seed, "steps": 26, "cfg": 1.0, "sampler_name": "euler",
              "scheduler": "simple", "denoise": denoise}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": f"emulator_{denoise}_{seed}"}},
    }

def run(img, denoise, seed):
    pid = call("/prompt", json.dumps({"prompt": graph(img, denoise, seed), "client_id": "philibert-brand"}).encode())["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 900:
        h = call(f"/history/{pid}")
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                raise SystemExit(f"ComfyUI error: {json.dumps(st)[:800]}")
            for node in h[pid]["outputs"].values():
                for im in node.get("images", []):
                    q = f"/view?filename={urllib.parse.quote(im['filename'])}&subfolder={urllib.parse.quote(im['subfolder'])}&type={im['type']}"
                    with urllib.request.urlopen(API + q, timeout=60) as r:
                        out = OUT / f"emulator_{denoise}_{seed}.png"
                        out.write_bytes(r.read())
                        print(f"{out.name}  ({time.time() - t0:.0f} s)", flush=True)
                        return
        time.sleep(2)
    raise SystemExit("timed out")

import urllib.parse   # noqa: E402
img = upload(HERE / "mascot-init.png")
denoise = float(sys.argv[1])
for s in sys.argv[2:]:
    run(img, denoise, int(s))
