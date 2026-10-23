"""Image Generation: Philibert's ComfyUI add-on, kept entirely on the drive.

  runtime/<plat>/comfyui/python      its own Python (torch is 3 GB; it never mixes with the app's)
  runtime/<plat>/comfyui/ComfyUI     the pinned ComfyUI release
  models/image/checkpoints           the models, shared by every computer the drive runs on
  data/images                        what it makes (data/images/.trash for deleted ones)
  data/comfyui                       ComfyUI's own settings and saved workflows

It is set up per computer, because torch differs by chip: NVIDIA on Windows
(CUDA 13.0, or 12.8 for an older driver), the processor elsewhere on Windows,
Metal on a Mac with an Apple chip. A Mac with an Intel chip is not offered.
Setup can do it (--install), and so can the Image Generation page on any
computer the drive is plugged into later.

ComfyUI runs on 127.0.0.1:8199 - not its usual 8188, so a ComfyUI the person
already has on this computer is left alone - with no window and no browser.

Entry points: handle(body, root, ...) for /api/images; tool(args, root, ...)
for the chat's generate_image; python nd_imagegen.py --install <drive root>.
"""
import atexit
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

PORT = 8199
URL = f"http://127.0.0.1:{PORT}"
IS_WIN = os.name == "nt"
_NO_WINDOW = 0x08000000 if IS_WIN else 0
SIZES = {"square": (1024, 1024), "poster": (832, 1216), "banner": (1344, 768), "story": (768, 1344)}
_proc = None
_lock = threading.Lock()
_job = {"state": "idle", "line": "", "progress": 0.0, "error": ""}     # the install, for the page


def plat():
    if IS_WIN:
        return "win-x64"
    return "mac-arm64" if platform.machine() in ("arm64", "aarch64") else "mac-x64"


def paths(root):
    root = Path(root)
    c = root / "runtime" / plat() / "comfyui"
    return {"root": root, "comfy": c, "app": c / "ComfyUI",
            "py": c / "python" / ("python.exe" if IS_WIN else "bin/python3"),
            "ready": c / ".philibert-ready", "models": root / "models" / "image",
            "out": root / "data" / "images", "user": root / "data" / "comfyui",
            "log": root / "data" / "logs" / "comfyui.log", "pins": root / "setup" / "pins.json"}


def pins(root):
    return json.loads(paths(root)["pins"].read_text(encoding="utf-8"))["imagegen"]


def installed(root):
    p = paths(root)
    return p["ready"].is_file() and (p["app"] / "main.py").is_file() and p["py"].is_file()


def checkpoints(root):
    d = paths(root)["models"] / "checkpoints"
    return sorted(f.name for f in d.glob("*.safetensors")) if d.is_dir() else []


# --- what this computer can do -----------------------------------------------------
def _nvidia():
    """(driver major, VRAM GB) of the first NVIDIA card, or None."""
    exe = shutil.which("nvidia-smi") or (r"C:\Windows\System32\nvidia-smi.exe" if IS_WIN else "")
    if not exe or not Path(exe).exists():
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=driver_version,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW).stdout
        drv, mem = out.strip().splitlines()[0].split(",")
        return int(drv.strip().split(".")[0]), round(int(mem.strip()) / 1024)
    except Exception:
        return None


def _ram_gb():
    try:
        import psutil
        return round(psutil.virtual_memory().total / 2**30)
    except Exception:
        return 0


def rating():
    """green / yellow / red for this computer, the torch build to use, and why - in plain words."""
    p = plat()
    if p == "mac-x64":
        return {"rating": "red", "backend": None, "why": "A Mac with an Intel chip can only draw with its processor: "
                "minutes for each picture. Image Generation needs a Mac with an Apple chip."}
    if p == "mac-arm64":
        ram = _ram_gb()
        if ram and ram < 16:
            return {"rating": "red", "backend": "mps", "why": f"This Mac has {ram} GB of memory; pictures need 16 GB or more."}
        return {"rating": "yellow", "backend": "mps", "why": "Works on the Apple chip - several times slower than a "
                "recent NVIDIA card (about a minute a picture)."}
    nv = _nvidia()
    if not nv:
        return {"rating": "red", "backend": "cpu", "why": "No NVIDIA graphics card: pictures are drawn by the "
                "processor and take several minutes each."}
    drv, vram = nv
    backend = "cu130" if drv >= 580 else "cu128" if drv >= 570 else None
    if backend is None:
        return {"rating": "red", "backend": None, "why": f"The NVIDIA driver here is version {drv}; it needs 570 "
                "or newer. Update it from nvidia.com, then set up again."}
    if vram < 6:
        return {"rating": "red", "backend": backend, "why": f"The graphics card has {vram} GB; pictures need 8 GB."}
    if vram < 8:
        return {"rating": "yellow", "backend": backend, "why": f"The graphics card has {vram} GB: it works, slowly."}
    return {"rating": "green", "backend": backend, "why": f"NVIDIA card with {vram} GB: about 10-30 seconds a picture."}


# --- setting it up on this computer --------------------------------------------------
def _get(url, dst, say, label, size=None):
    """Download with resume; say(line, fraction) reports progress."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": "Philibert-Setup", **({"Range": f"bytes={have}-"} if have else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:
            have = 0                                      # the server started over
        total = have + int(r.headers.get("Content-Length") or 0) or size or 0
        with open(part, "ab" if have else "wb") as f:
            got, last = have, 0.0
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                got += len(b)
                if time.time() - last > 1:
                    last = time.time()
                    say(f"{label}: {got / 2**30:.1f} of {total / 2**30:.1f} GB" if total > 2**30
                        else f"{label}: {got // 2**20} MB", got / total if total else -1)
    part.replace(dst)
    return dst


def _run(cmd, say, env, base, span):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                         encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    n = 0
    for line in p.stdout:
        line = line.strip()
        if line.startswith(("Collecting", "Downloading", "Installing collected")):
            n += 1
            say(line[:90], base + span * min(0.95, n / 60))
    return p.wait()


def install(root, say=lambda line, frac=-1: print(line, flush=True), model=True):
    """Everything Image Generation needs on this computer; safe to run again (it resumes)."""
    p, pin = paths(root), pins(root)
    r = rating()
    if not r["backend"]:
        raise RuntimeError(r["why"])
    dl = p["root"] / "runtime" / "_download" / plat()
    # 1. its own Python - the same pinned build as the app's
    if not p["py"].is_file():
        py_pins = json.loads(p["pins"].read_text(encoding="utf-8"))["python"]
        arc = dl / "python.tar.gz"
        if not arc.is_file():
            _get(py_pins[plat()], arc, say, "Python")
        say("Unpacking Python", 0.04)
        with tarfile.open(arc) as t:
            t.extractall(p["comfy"], filter="data")
    # 2. ComfyUI
    stamp = p["comfy"] / ".comfyui-version"
    if not (stamp.is_file() and stamp.read_text(encoding="ascii").strip() == pin["comfyui"]["version"]):
        z = _get(pin["comfyui"]["url"], dl / f"comfyui-{pin['comfyui']['version']}.zip", say, "ComfyUI")
        say("Unpacking ComfyUI", 0.08)
        tmp = p["comfy"] / "_unpack"
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(tmp)
        top = next(x for x in tmp.iterdir() if x.is_dir())
        if p["app"].exists():
            shutil.rmtree(p["app"])                   # an older ComfyUI: the drive keeps no edits in it
        top.replace(p["app"])
        shutil.rmtree(tmp, ignore_errors=True)
        stamp.write_text(pin["comfyui"]["version"], encoding="ascii")
    # 3. torch for this chip, then ComfyUI's own packages
    tb = pin["torch"][r["backend"]]
    want = f"{r['backend']} " + " ".join(tb["packages"]) + f" comfyui {pin['comfyui']['version']}"
    pstamp = p["comfy"] / ".philibert-packages"
    if not (pstamp.is_file() and pstamp.read_text(encoding="ascii").strip() == want):
        tmpd = dl / "tmp"
        tmpd.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PYTHONNOUSERSITE": "1", "TEMP": str(tmpd), "TMP": str(tmpd), "TMPDIR": str(tmpd),
               "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
        pip = [str(p["py"]), "-m", "pip", "install", "--no-cache-dir", "--no-warn-script-location", "--progress-bar", "off"]
        say("Getting the picture engine (about 3 GB)", 0.1)
        if _run(pip + tb["packages"] + (["--index-url", tb["index"]] if tb.get("index") else []), say, env, 0.1, 0.35):
            raise RuntimeError("The picture engine (torch) did not install. Check the Internet connection and try again.")
        say("Getting ComfyUI's building blocks", 0.45)
        if _run(pip + ["-r", str(p["app"] / "requirements.txt")], say, env, 0.45, 0.1):
            raise RuntimeError("ComfyUI's building blocks did not install. Check the Internet connection and try again.")
        pstamp.write_text(want, encoding="ascii")
    # 4. a model to draw with, unless one is already on the drive: Z-Image Turbo where it
    #    fits the graphics card, SDXL otherwise; the app's Models page has the rest
    if model and not default_model(root):
        download_model(root, recommended_id(root), lambda line, f: say(line, 0.55 + 0.44 * max(f, 0)))
    p["ready"].write_text(json.dumps({"comfyui": pin["comfyui"]["version"], "backend": r["backend"],
                                      "when": time.strftime("%Y-%m-%d %H:%M")}), encoding="utf-8")
    say("Image Generation is ready.", 1.0)


def install_async(root, internet=True):
    """For the page: set it up in the background; status() reports how far it got."""
    if not internet:
        return {"ok": False, "msg": "Setting up Image Generation downloads about 10 GB: turn the INTERNET switch on first."}
    with _lock:
        if _job["state"] == "running":
            return {"ok": True, "msg": "Already setting up."}
        _job.update(state="running", line="Starting", progress=0.0, error="")

    def say(line, frac=-1):
        _job["line"] = line
        if frac >= 0:
            _job["progress"] = frac

    def go():
        try:
            install(root, say)
            _job["state"] = "done"
        except Exception as e:
            _job.update(state="error", error=str(e))
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


# --- running ComfyUI -----------------------------------------------------------------
def running():
    try:
        urllib.request.urlopen(URL + "/system_stats", timeout=2).close()
        return True
    except Exception:
        return False


def start(root, free_gpu=None, timeout=240):
    global _proc
    if running():
        return True
    if not installed(root):
        raise RuntimeError("Image Generation is not set up on this computer yet.")
    p = paths(root)
    for d in (p["out"] / "input", p["user"], p["models"] / "checkpoints", p["models"] / "loras", p["models"] / "vae",
              p["log"].parent):
        d.mkdir(parents=True, exist_ok=True)
    yml = p["comfy"] / "philibert_models.yaml"
    yml.write_text("philibert:\n    base_path: " + json.dumps(str(p["models"])) + "\n" + "".join(
        f"    {k}: {k}\n" for k in ("checkpoints", "loras", "vae", "upscale_models", "embeddings", "controlnet",
                                    "clip", "unet", "diffusion_models", "text_encoders")), encoding="utf-8")
    if free_gpu:
        free_gpu()                                 # a chat model and a picture model don't both fit on most cards
    env = {**os.environ, "PYTHONNOUSERSITE": "1", "DO_NOT_TRACK": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
           "PYTORCH_ENABLE_MPS_FALLBACK": "1"}
    with _lock:
        log = open(p["log"], "a", encoding="utf-8", errors="replace")
        _proc = subprocess.Popen(
            [str(p["py"]), "main.py", "--listen", "127.0.0.1", "--port", str(PORT), "--disable-auto-launch",
             "--output-directory", str(p["out"]), "--input-directory", str(p["out"] / "input"),
             "--user-directory", str(p["user"]), "--temp-directory", str(p["comfy"] / "temp"),
             "--extra-model-paths-config", str(yml), "--preview-method", "none"],
            cwd=str(p["app"]), env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=_NO_WINDOW)
    if not getattr(start, "_atexit", False):     # nothing of Philibert's keeps running after it closes
        atexit.register(stop)
        start._atexit = True
    t0 = time.time()
    while time.time() - t0 < timeout:
        if running():
            return True
        if _proc.poll() is not None:
            raise RuntimeError("ComfyUI stopped while starting - see data\\logs\\comfyui.log on the drive.")
        time.sleep(1)
    raise RuntimeError("ComfyUI did not start in time - see data\\logs\\comfyui.log on the drive.")


def stop():
    global _proc
    with _lock:
        if _proc and _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(10)
            except Exception:
                _proc.kill()
        _proc = None


def _call(path, payload=None):
    req = urllib.request.Request(URL + path, data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# --- the models: a catalogue (setup/pins.json), downloaded on request ---------------------
_mjob = {"state": "idle", "id": "", "line": "", "progress": 0.0, "error": ""}   # one model download at a time

# Style presets: what makes a good picture for a musician, in words the models answer to.
# Lessons kept (ND's image work, ImageForgery): Z-Image is distilled - 8 steps, guidance 1,
# so it ignores a "leave out" list and wants the picture described in full sentences, with
# any lettering in "quotes". SDXL wants comma tags, a "leave out" list, 25-30 steps and
# guidance 5-7, at its own sizes (1024x1024, 832x1216, 1344x768...).
STYLES = [
    {"id": "none", "name": "As written", "add": "", "neg": ""},
    {"id": "cover", "name": "Album cover", "add": "square album cover art, bold central composition, striking colour palette, "
     "professional graphic design, high detail", "neg": "border, frame, mockup"},
    {"id": "poster", "name": "Gig poster", "add": "vintage screen-printed gig poster, limited colour palette, halftone texture, "
     "bold typography, retro concert poster design", "neg": "photo, blurry"},
    {"id": "photo", "name": "Band photo", "add": "35mm film photograph, natural light, shallow depth of field, candid, "
     "film grain, realistic", "neg": "illustration, cartoon, painting, deformed hands"},
    {"id": "logo", "name": "Logo", "add": "clean vector logo emblem, flat design, simple shapes, centred on a plain "
     "background, high contrast", "neg": "photo, clutter, gradient noise"},
    {"id": "neon", "name": "Neon night", "add": "neon-lit night scene, synthwave colours, glowing signs, wet reflections, "
     "cinematic lighting", "neg": "daylight, washed out"},
    {"id": "paint", "name": "Painted", "add": "expressive oil painting, visible brush strokes, rich texture, gallery "
     "quality", "neg": "photo, 3d render"},
]
NEG_BASE = "blurry, low quality, jpeg artifacts, watermark, signature, distorted, extra fingers"
DEFAULTS = {"zimage": {"steps": 8, "cfg": 1.0, "sampler": "res_multistep", "scheduler": "simple"},
            "sdxl": {"steps": 28, "cfg": 6.0, "sampler": "dpmpp_2m", "scheduler": "karras"}}


def catalog(root):
    try:
        return pins(root).get("models") or []
    except (OSError, ValueError, KeyError):
        return []


def _mfile(root, f):
    return paths(root)["models"] / f["dir"] / f["file"]


def model_installed(root, m):
    return all(_mfile(root, f).is_file() for f in m["files"])


def _vram_fit(m):
    """green / yellow / red for this model on this computer's graphics memory."""
    if plat() == "mac-arm64":
        gb = _ram_gb() * 0.6                    # unified memory: the system keeps part of it
    else:
        nv = _nvidia()
        gb = nv[1] if nv else 0
    if gb >= m.get("vram_ok", 8):
        return "green"
    return "yellow" if gb >= m.get("vram_min", 6) else "red"


def models(root):
    """The catalogue with what is on the drive, plus any checkpoint the person added themselves."""
    out, known = [], set()
    for m in catalog(root):
        known.update(f["file"] for f in m["files"])
        out.append({k: m.get(k) for k in ("id", "name", "kind", "about", "licence", "source", "recommended", "settings")}
                   | {"installed": model_installed(root, m), "size": sum(f["size"] for f in m["files"]),
                      "fit": _vram_fit(m)})
    for c in checkpoints(root):
        if c not in known:
            out.append({"id": "own:" + c, "name": c.rsplit(".", 1)[0], "kind": "sdxl", "installed": True, "own": True,
                        "about": "Your own model (in models\\image\\checkpoints).", "size": 0, "fit": "green"})
    return out


def default_model(root):
    """The model a quick picture uses: the recommended one if it is here, else any picture model."""
    ms = [m for m in models(root) if m["installed"] and m["kind"] in ("zimage", "sdxl")]
    rec = [m for m in ms if m.get("recommended")]
    return (rec or ms or [None])[0]


def recommended_id(root):
    """What Setup fetches by itself: Z-Image Turbo where it fits, otherwise SDXL."""
    cat = {m["id"]: m for m in catalog(root)}
    z = cat.get("zimage-turbo")
    return "zimage-turbo" if z and _vram_fit(z) == "green" else "sdxl-base"


def download_model(root, mid, say=lambda line, frac=-1: None):
    m = next((m for m in catalog(root) if m["id"] == mid), None)
    if not m:
        raise ValueError("no such model")
    total = sum(f["size"] for f in m["files"]) or 1
    done = 0
    for f in m["files"]:
        dst = _mfile(root, f)
        if not dst.is_file():
            base = done
            url = (m.get("mirror") or {}).get(f["file"]) if isinstance(m.get("mirror"), dict) else None
            _get(url or f["url"], dst, lambda line, fr, base=base, sz=f["size"]:
                 say(f"{m['name']}: {line.split(': ', 1)[-1]}", (base + max(fr, 0) * sz) / total), f["file"], f["size"])
        done += f["size"]
    say(f"{m['name']} is ready.", 1.0)


def download_model_async(root, mid, internet=True):
    if not internet:
        return {"ok": False, "msg": "Downloading a model needs the INTERNET switch on."}
    if not any(m["id"] == mid for m in catalog(root)):
        return {"ok": False, "msg": "no such model"}
    with _lock:
        if _mjob["state"] == "running":
            return {"ok": False, "msg": "Another model is downloading - one at a time."}
        _mjob.update(state="running", id=mid, line="Starting", progress=0.0, error="")

    def say(line, frac=-1):
        _mjob["line"] = line
        if frac >= 0:
            _mjob["progress"] = frac

    def go():
        try:
            download_model(root, mid, say)
            _mjob["state"] = "done"
        except Exception as e:
            _mjob.update(state="error", error=str(e)[:300])
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


def remove_model(root, mid):
    """Delete a downloaded model's files - but not a file another installed model still uses."""
    cat = catalog(root)
    m = next((x for x in cat if x["id"] == mid), None)
    if not m:
        return {"ok": False, "msg": "no such model"}
    shared = {f["file"] for x in cat if x["id"] != mid and model_installed(root, x) for f in x["files"]}
    freed = 0
    for f in m["files"]:
        p = _mfile(root, f)
        if f["file"] not in shared and p.is_file():
            freed += p.stat().st_size
            p.unlink()
    return {"ok": True, "freed": freed}


# --- workflows ------------------------------------------------------------------------
def wf_sdxl(prompt, negative, w, h, steps, cfg, sampler, scheduler, seed, ckpt, count):
    """Checkpoint -> prompts -> sampler -> pictures (count of them, one seed each)."""
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": count}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": steps, "cfg": cfg, "sampler_name": sampler,
                                                   "scheduler": scheduler, "denoise": 1.0, "model": ["4", 0],
                                                   "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "Philibert", "images": ["8", 0]}},
    }


def wf_zimage(prompt, w, h, steps, seed, files, count):
    """Z-Image Turbo (Lumina 2): its own loaders, AuraFlow sampling (shift 3), 8 steps, guidance 1."""
    by = {f["dir"]: f["file"] for f in files}
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": by["diffusion_models"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": by["text_encoders"], "type": "lumina2"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": by["vae"]}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"shift": 3, "model": ["1", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "7": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": count}},
        "8": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "res_multistep",
                                                   "scheduler": "simple", "denoise": 1.0, "model": ["4", 0],
                                                   "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0]}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": "Philibert", "images": ["9", 0]}},
    }


def wf_upscale(image_name, model_file):
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": model_file}},
        "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "SaveImage", "inputs": {"filename_prefix": "Philibert_4x", "images": ["3", 0]}},
    }


def _run_prompt(wf, timeout):
    pid = _call("/prompt", {"prompt": wf, "client_id": "philibert-" + uuid.uuid4().hex[:8]})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        hist = _call(f"/history/{pid}").get(pid)
        if hist:
            st = hist.get("status") or {}
            if st.get("status_str") == "error":
                msgs = [m[1].get("exception_message", "") for m in st.get("messages", []) if m[0] == "execution_error"]
                raise RuntimeError("ComfyUI said: " + ("; ".join(msgs) or "it failed")[:300])
            imgs = [im for out in (hist.get("outputs") or {}).values() for im in (out.get("images") or [])]
            if imgs or st.get("completed"):
                return imgs
        time.sleep(0.7)
    raise RuntimeError("The picture took too long.")


def generate(root, prompt, negative="", size="square", width=None, height=None, steps=None, cfg=None, seed=None,
             ckpt=None, free_gpu=None, timeout=1200, model=None, count=1, style="none"):
    """Make count pictures (variations: one seed each, from seed up). Returns a list."""
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("say what to draw")
    w, h = SIZES.get(size, SIZES["square"])
    if width and height:
        w, h = max(512, min(2048, int(width) // 64 * 64)), max(512, min(2048, int(height) // 64 * 64))
    ms = {m["id"]: m for m in models(root) if m["installed"]}
    if ckpt and not model:                                  # the older call: a checkpoint by file name
        model = next((i for i, m in ms.items() if i == "own:" + ckpt), None) or \
                next((m["id"] for m in catalog(root) if any(f["file"] == ckpt for f in m["files"]) and m["id"] in ms), None)
    m = ms.get(model) or default_model(root)
    if not m or m["kind"] not in ("zimage", "sdxl"):
        raise RuntimeError("No picture model is on the drive yet - open Models and download one.")
    count = max(1, min(int(count or 1), 4))
    seed = int(seed) if seed not in (None, "") else random.randint(1, 2**31)
    st_ = next((s for s in STYLES if s["id"] == style), STYLES[0])
    d = {**DEFAULTS[m["kind"]], **(m.get("settings") or {})}
    steps = max(1, min(int(steps or d["steps"]), 60))
    if not st_["add"]:
        full = prompt
    elif m["kind"] == "zimage":         # a sentence of its own: no stray punctuation next to quoted lettering
        full = prompt.rstrip() + ("" if prompt.rstrip()[-1:] in ".!?" else ".") + " Style: " + st_["add"] + "."
    else:
        full = prompt.rstrip().rstrip(",") + ", " + st_["add"]
    start(root, free_gpu)
    if m["kind"] == "zimage":
        files = next(x for x in catalog(root) if x["id"] == m["id"])["files"]
        steps = min(steps, 12)
        wf = wf_zimage(full, w, h, steps, seed, files, count)
        neg_used, cfg = "", 1.0
    else:
        ck = m["id"][4:] if m.get("own") else next(x for x in catalog(root) if x["id"] == m["id"])["files"][0]["file"]
        cfg = float(cfg or d["cfg"])
        neg_used = ", ".join(x for x in (negative.strip(), st_["neg"], NEG_BASE) if x)
        wf = wf_sdxl(full, neg_used, w, h, steps, cfg, d["sampler"], d["scheduler"], seed, ck, count)
    imgs = _run_prompt(wf, timeout)
    out = []
    for i, im in enumerate(imgs):
        f = paths(root)["out"] / im.get("subfolder", "") / im["filename"]
        meta = {"prompt": prompt, "style": st_["id"], "negative": negative, "w": w, "h": h, "seed": seed + i,
                "model": m["name"], "model_id": m["id"], "steps": steps, "cfg": cfg, "batch": i + 1, "of": len(imgs)}
        f.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        out.append({"name": f.name, "path": str(f), **meta})
    if not out:
        raise RuntimeError("ComfyUI finished but gave back no picture.")
    return out


def upscale(root, name, free_gpu=None):
    f = image_file(root, name)
    if not f:
        raise ValueError("no such picture")
    up = next((m for m in catalog(root) if m["kind"] == "upscale" and model_installed(root, m)), None)
    if not up:
        raise RuntimeError("Download the 4x upscaler in Models first.")
    inp = paths(root)["out"] / "input"
    inp.mkdir(parents=True, exist_ok=True)
    shutil.copy2(f, inp / f.name)
    start(root, free_gpu)
    imgs = _run_prompt(wf_upscale(f.name, up["files"][0]["file"]), 600)
    if not imgs:
        raise RuntimeError("The upscale gave back no picture.")
    g = paths(root)["out"] / imgs[0].get("subfolder", "") / imgs[0]["filename"]
    try:
        meta = json.loads(f.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    meta.update(upscaled_from=f.name, w=(meta.get("w") or 0) * 4, h=(meta.get("h") or 0) * 4)
    g.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return {"name": g.name, **meta}


def images(root):
    out = paths(root)["out"]
    if not out.is_dir():
        return []
    res = []
    for f in sorted(out.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)[:600]:
        meta = {}
        try:
            meta = json.loads(f.with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        res.append({"name": f.name, "when": f.stat().st_mtime, **{k: meta.get(k) for k in (
            "prompt", "seed", "w", "h", "model", "model_id", "style", "negative", "steps", "cfg", "upscaled_from")}})
    return res


def image_file(root, name):
    """The file for a gallery name, or None: names only, never a path from outside."""
    out = paths(root)["out"].resolve()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    f = out / name
    return f if f.suffix.lower() == ".png" and f.is_file() else None


def trash(root, name):
    f = image_file(root, name)
    if not f:
        return False
    t = f.parent / ".trash"
    t.mkdir(exist_ok=True)
    for g in (f, f.with_suffix(".json")):
        if g.exists():
            g.replace(t / g.name)
    return True


def status(root):
    r = rating()
    dm = default_model(root)
    return {"ok": True, "installed": installed(root), "running": running(), "checkpoints": checkpoints(root),
            "rating": r["rating"], "why": r["why"], "platform": plat(), "setup": dict(_job),
            "models": models(root), "default_model": dm["id"] if dm else None, "download": dict(_mjob),
            "styles": [{"id": s["id"], "name": s["name"]} for s in STYLES], "defaults": DEFAULTS,
            "editor": URL + "/", "sizes": {k: list(v) for k, v in SIZES.items()}}


# --- the page and the chat -----------------------------------------------------------
def handle(body, root, internet=True, free_gpu=None):
    body = body or {}
    op = body.get("op", "")
    try:
        if op == "status":
            return status(root)
        if op == "install":
            return install_async(root, internet)
        if op == "start":
            start(root, free_gpu)
            return {"ok": True, "editor": URL + "/"}
        if op == "generate":
            r = generate(root, body.get("prompt"), body.get("negative") or "", body.get("size") or "square",
                         steps=body.get("steps"), cfg=body.get("cfg"), seed=body.get("seed"),
                         model=body.get("model"), count=body.get("count") or 1, style=body.get("style") or "none",
                         free_gpu=free_gpu)
            return {"ok": True, "images": r, **r[0]}
        if op == "upscale":
            return {"ok": True, **upscale(root, str(body.get("name") or ""), free_gpu)}
        if op == "list":
            return {"ok": True, "images": images(root)}
        if op == "delete":
            return {"ok": trash(root, str(body.get("name") or ""))}
        if op == "model_download":
            return download_model_async(root, str(body.get("id") or ""), internet)
        if op == "model_remove":
            return remove_model(root, str(body.get("id") or ""))
        return {"ok": False, "msg": f"unknown op {op!r}"}
    except (RuntimeError, ValueError, urllib.error.URLError, OSError) as e:
        return {"ok": False, "msg": str(e)}


def tool(a, root, free_gpu=None):
    """The chat's generate_image. Returns (text for the model, the PNG bytes or None)."""
    if not installed(root):
        return ("[NOT SET UP] Image Generation is not set up on this computer. Tell the user they can set it up "
                "from the Image Generation icon on the desktop (it downloads the picture engine and a model). "
                "Do not try anything else."), None
    try:
        r = generate(root, a.get("prompt"), str(a.get("negative") or ""), "square",
                     a.get("width"), a.get("height"), a.get("steps"), a.get("cfg"), free_gpu=free_gpu)[0]
    except (RuntimeError, ValueError, urllib.error.URLError, OSError) as e:
        return f"[ERROR generate_image: {e}]", None
    return r, Path(r["path"]).read_bytes()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--install":
        try:
            install(sys.argv[2], lambda line, frac=-1: print(f"imagegen: {line}", flush=True),
                    model="--no-model" not in sys.argv)
        except Exception as e:
            print(f"imagegen: FAILED {e}", flush=True)
            sys.exit(1)
    elif len(sys.argv) >= 2 and sys.argv[1] == "--rating":
        print(json.dumps(rating()))
    else:
        sys.exit(__doc__)
