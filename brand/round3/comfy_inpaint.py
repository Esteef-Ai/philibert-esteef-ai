"""Remove the controller cable and the fake signature from emulator_0.72_303.png with Flux
inpainting (only the masked areas are repainted). -> painted/emulator_final_<seed>.png"""
import json, sys, time, uuid, urllib.request, urllib.parse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
API = "http://127.0.0.1:8188"
SRC = HERE / "painted" / "emulator_0.72_303.png"
# areas to repaint (full-size pixel boxes): the cable + plug on top of the pad, the signature
BOXES = [(686, 660, 796, 744), (1130, 985, 1232, 1024)]
PROMPT = ("cel-shaded comic book illustration, thick black ink outlines. An empty, plain, smooth dark navy blue "
          "background, and below it the smooth curved top edge of a light grey game pad between its two dark grey "
          "shoulder buttons. Simple, clean, empty.")

def call(path, data=None, ctype="application/json"):
    req = urllib.request.Request(API + path, data=data, headers={"Content-Type": ctype} if data else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")

def upload(png: Path):
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{png.name}\"\r\nContent-Type: image/png\r\n\r\n").encode() \
        + png.read_bytes() + f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n".encode()
    return call("/upload/image", body, f"multipart/form-data; boundary={b}")["name"]

# the image with the areas to repaint made transparent: ComfyUI's LoadImage turns alpha into a mask
img = Image.open(SRC).convert("RGBA")
mask = Image.new("L", img.size, 0)
d = ImageDraw.Draw(mask)
for b in BOXES:
    d.rectangle(b, fill=255)
mask = mask.filter(ImageFilter.GaussianBlur(3))
img.putalpha(Image.eval(mask, lambda v: 255 - v))
masked = HERE / "painted" / "inpaint_src.png"
img.save(masked)
name = upload(masked)

def graph(seed):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux1-dev.safetensors", "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp8_e4m3fn.safetensors", "type": "flux"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": name}},
        "5": {"class_type": "VAEEncode", "inputs": {"pixels": ["4", 0], "vae": ["3", 0]}},
        "12": {"class_type": "GrowMask", "inputs": {"mask": ["4", 1], "expand": 6, "tapered_corners": True}},
        "13": {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["5", 0], "mask": ["12", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPT, "clip": ["2", 0]}},
        "7": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["6", 0], "guidance": 3.5}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "9": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["7", 0], "negative": ["8", 0],
              "latent_image": ["13", 0], "seed": seed, "steps": 28, "cfg": 1.0, "sampler_name": "euler",
              "scheduler": "simple", "denoise": 0.95}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": f"emulator_inpaint_{seed}"}},
    }

for seed in [int(s) for s in sys.argv[1:]] or [1]:
    pid = call("/prompt", json.dumps({"prompt": graph(seed), "client_id": "philibert-brand"}).encode())["prompt_id"]
    t0 = time.time()
    while True:
        h = call(f"/history/{pid}")
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                raise SystemExit(json.dumps(st)[:800])
            im = next(i for n in h[pid]["outputs"].values() for i in n.get("images", []))
            q = f"/view?filename={urllib.parse.quote(im['filename'])}&subfolder={urllib.parse.quote(im['subfolder'])}&type={im['type']}"
            raw = urllib.request.urlopen(API + q, timeout=60).read()
            gen = HERE / "painted" / f"_gen_{seed}.png"
            gen.write_bytes(raw)
            # paste ONLY the repainted areas back onto the untouched original (VAE round-trips soften the rest)
            orig = Image.open(SRC).convert("RGB")
            out = Image.composite(Image.open(gen).convert("RGB"), orig, mask)
            dest = HERE / "painted" / f"emulator_final_{seed}.png"
            out.save(dest)
            print(dest.name, f"({time.time() - t0:.0f} s)")
            break
        time.sleep(2)
