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
    # 4. a model to draw with, unless one is already on the drive
    if model and not checkpoints(root):
        m = pin["model"]
        _get(m["url"], p["models"] / "checkpoints" / m["file"], lambda line, f: say(line, 0.55 + 0.44 * max(f, 0)),
             m["name"], m["size"])
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


def workflow(prompt, negative, w, h, steps, cfg, seed, ckpt):
    """The plain SDXL graph: model -> prompts -> sampler -> picture."""
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "dpmpp_2m",
                                                   "scheduler": "karras", "denoise": 1.0, "model": ["4", 0],
                                                   "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "Philibert", "images": ["8", 0]}},
    }


def generate(root, prompt, negative="", size="square", width=None, height=None, steps=25, cfg=6.5, seed=None,
             ckpt=None, free_gpu=None, timeout=900):
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("say what to draw")
    w, h = SIZES.get(size, SIZES["square"])
    if width and height:
        w, h = max(512, min(2048, int(width) // 64 * 64)), max(512, min(2048, int(height) // 64 * 64))
    have = checkpoints(root)
    if not have:
        raise RuntimeError("There is no picture model in models\\image\\checkpoints on the drive.")
    ckpt = ckpt if ckpt in have else have[0]
    seed = int(seed) if seed not in (None, "") else random.randint(1, 2**31)
    start(root, free_gpu)
    neg = negative or "blurry, low quality, distorted, watermark, text artifacts"
    pid = _call("/prompt", {"prompt": workflow(prompt, neg, w, h, max(1, min(int(steps), 60)), float(cfg), seed, ckpt),
                            "client_id": "philibert-" + uuid.uuid4().hex[:8]})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        hist = _call(f"/history/{pid}").get(pid)
        if hist:
            st = hist.get("status") or {}
            if st.get("status_str") == "error":
                msgs = [m[1].get("exception_message", "") for m in st.get("messages", []) if m[0] == "execution_error"]
                raise RuntimeError("ComfyUI said: " + ("; ".join(msgs) or "it failed")[:300])
            for out in (hist.get("outputs") or {}).values():
                for im in out.get("images") or []:
                    f = paths(root)["out"] / im.get("subfolder", "") / im["filename"]
                    (f.with_suffix(".json")).write_text(json.dumps(
                        {"prompt": prompt, "negative": negative, "w": w, "h": h, "seed": seed, "model": ckpt,
                         "steps": steps, "cfg": cfg}, indent=1), encoding="utf-8")
                    return {"name": f.name, "path": str(f), "seed": seed, "w": w, "h": h, "model": ckpt}
        time.sleep(1)
    raise RuntimeError("The picture took too long.")


def images(root):
    out = paths(root)["out"]
    if not out.is_dir():
        return []
    res = []
    for f in sorted(out.glob("*.png"), key=lambda f: f.stat().st_mtime, reverse=True)[:400]:
        meta = {}
        try:
            meta = json.loads(f.with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        res.append({"name": f.name, "when": f.stat().st_mtime, "prompt": meta.get("prompt", ""), "seed": meta.get("seed"),
                    "w": meta.get("w"), "h": meta.get("h")})
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
    return {"ok": True, "installed": installed(root), "running": running(), "checkpoints": checkpoints(root),
            "rating": r["rating"], "why": r["why"], "platform": plat(), "setup": dict(_job),
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
                         seed=body.get("seed"), ckpt=body.get("model"), free_gpu=free_gpu)
            return {"ok": True, **r}
        if op == "list":
            return {"ok": True, "images": images(root)}
        if op == "delete":
            return {"ok": trash(root, str(body.get("name") or ""))}
        return {"ok": False, "msg": f"unknown op {op!r}"}
    except (RuntimeError, ValueError, urllib.error.URLError, OSError) as e:
        return {"ok": False, "msg": str(e)}


def tool(a, root, free_gpu=None):
    """The chat's generate_image. Returns (text for the model, the PNG bytes or None)."""
    if not installed(root):
        return ("[NOT SET UP] Image Generation is not set up on this computer. Tell the user they can set it up "
                "from the Image Generation icon on the desktop (it downloads about 10 GB). Do not try anything else."), None
    try:
        r = generate(root, a.get("prompt"), str(a.get("negative") or ""), "square",
                     a.get("width"), a.get("height"), a.get("steps") or 25, a.get("cfg") or 6.5,
                     free_gpu=free_gpu)
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
