#!/usr/bin/env python3
"""
#######+#######+########+#######+#######+#######+     #####+ ##+
##+====?##+====?+==##+==?##+====?##+====?##+====?    ##+==##+##|
#####+  #######+   ##|   #####+  #####+  #####+      #######|##|
##+==?  +====##|   ##|   ##+==?  ##+==?  ##+==?      ##+==##|##|
#######+#######|   ##|   #######+#######+##|          ##|  ##|##|
+======?+======?   +=?   +======?+======?+=?          +=?  +=?+=?
         N E U R A L D O C K  --  P O W E R E D  B Y  E S T E E F . A I
"""

import sys, os, subprocess, threading, json, base64, tempfile, time, shutil, io, hashlib, secrets
import fnmatch
import ast, builtins
from datetime import datetime
import urllib.request, urllib.error, urllib.parse, uuid, re, string
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import webbrowser, socket

VERSION = "3.1.0"

BANNER = rf"""
  ______  _____ _______ ______ ______ ______          _____ 
 |  ____|/ ____|__   __|  ____|  ____|  ____|   /\   |_   _|
 | |__  | (___    | |  | |__  | |__  | |__     /  \    | |  
 |  __|  \___ \   | |  |  __| |  __| |  __|   / /\ \   | |  
 | |____ ____) |  | |  | |____| |____| |   _ / ____ \ _| |_ 
 |______|_____/   |_|  |______|______|_|  (_)_/    \_\_____|

  NEURALDOCK  //  POWERED BY ESTEEF.AI
  Local AI Studio  //  RTX Edition  //  v{VERSION}
"""

# ??? Config ???????????????????????????????????????????????????????????????????
# --- Version --- (defined above BANNER, which interpolates it)

HERETIC_DIR  = Path("C:/Heretic")
VENV_DIR     = HERETIC_DIR / "venv"
VENV_PY      = VENV_DIR / "Scripts" / "python.exe"
VENV_PIP     = VENV_DIR / "Scripts" / "pip.exe"
# 127.0.0.1, not "localhost": Ollama is now bound to the IPv4 loopback only, and
# "localhost" resolves to ::1 first on Windows - every call would eat a failed
# IPv6 connect before falling back. Same trap that cost 2s/request on port 7788.
OLLAMA_URL   = os.environ.get("ND_OLLAMA_URL") or "http://127.0.0.1:11434"

# Philibert by Esteef.Ai: the portable, offline-by-default build of ND that runs
# from an external drive (G:\\!Ai\\ND-Portable). Its launcher sets these; without
# them ND is unchanged.
PORTABLE = os.environ.get("ND_PORTABLE") == "1"
PRODUCT  = "Philibert" if PORTABLE else "NeuralDock"
# Not part of a pure assistant that travels between other people's computers.
PORTABLE_DROP_TOOLS = {"generate_image", "run_shell", "install_app", "gui_action",
                       "hidden_desktop", "screen_capture", "device_action", "list_devices",
                       "delegate", "list_specialists", "resolve_app"}
# What the Internet switch blocks while it is off.
NETWORK_TOOLS = {"web_search", "web_fetch", "browser_open"}
COMFYUI_URL  = "http://localhost:8188"

# ComfyUI launch flags tuned for this box (RTX 5070 Ti, Blackwell sm_120, 16 GB).
#   fp16_accumulation  - accumulate in fp16 instead of fp32; large win on Ada/Blackwell
#   fp8_matrix_mult    - native fp8 tensor-core matmul, which Blackwell has and Ampere does not
#   pytorch cross-attn - torch 2.11 sdpa already dispatches to flash attention
#   preview-method none- 'auto' VAE-decodes a preview EVERY sampler step; pure overhead
#                        for API-driven generation where nobody watches the preview
COMFY_PERF_ARGS = ("--fast fp16_accumulation fp8_matrix_mult "
                   "--use-pytorch-cross-attention --preview-method none")
PORT         = int(os.environ.get("ND_PORT") or 7788)
HTML_FILE    = Path(__file__).parent / "NeuralDock_ui.html"
# Elena's own agent-mode interface, served at /elena. Kept a separate file and a
# separate route rather than folded into the main UI: it is a different shell for
# the same server, and the whole point of its design is that it carries no chrome
# the main UI needs. Serving it from here rather than a side process also makes
# it same-origin, so it needs no CORS and works from a paired phone.
ELENA_FILE   = Path(__file__).parent / "elena_ui.html"

# Install base -- prefer T:\ if available, else ask user
DEFAULT_INSTALL_DRIVE = "T"

def get_install_base():
    # Prefer the user-configured install base
    cfg = _config.get("install_base","").strip() if isinstance(_config.get("install_base",""), str) else ""
    if cfg:
        p = Path(cfg)
        if p.exists():
            return p
    t = Path("T:/NeuralDock")
    if Path("T:/").exists():
        return t
    return None  # UI will ask user

def get_comfyui_dir():
    """Always prefer user-configured path from config."""
    cfg = _config.get("comfyui_dir","").strip()
    if cfg:
        p = Path(cfg)
        if p.exists(): return p
        # Path configured but doesn't exist yet — return it anyway so UI shows it
        return p
    # Only auto-detect if nothing configured
    for p in [Path("T:/ComfyUI"), Path.home()/"ComfyUI", Path("C:/ComfyUI")]:
        if p.exists(): return p
    return None

def get_gallery_dir():
    """Always prefer user-configured gallery path."""
    cfg = _config.get("gallery_dir","").strip()
    if cfg:
        p = Path(cfg)
        try: p.mkdir(parents=True, exist_ok=True)
        except: pass
        return p
    base = get_install_base()
    if base:
        p = base / "Gallery"
        try: p.mkdir(parents=True, exist_ok=True)
        except: pass
        return p
    return None


# ??? Persistent config ????????????????????????????????????????????????????????
# Config lives next to the launcher so it persists across locations
# Where ND WRITES. Portable builds keep data apart from the app so an update can
# replace app/ without touching it.
_CONFIG_DIR  = Path(os.environ["ND_DATA_DIR"]) if os.environ.get("ND_DATA_DIR") else Path(__file__).parent
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE  = _CONFIG_DIR / "neuraldock_config.json"
_BACKUP_FILE = HERETIC_DIR / "neuraldock_config.json"  # legacy location
_config = {}

def load_config():
    global _config
    # Try launcher directory first, then legacy C:\Heretic location
    for cfg_path in [CONFIG_FILE, _BACKUP_FILE]:
        if cfg_path.exists():
            try:
                _config = json.loads(cfg_path.read_text(encoding="utf-8"))
                log(f"Config loaded from {str(cfg_path)}", "info")
                _portable_defaults()
                # Migrate to new location if loaded from legacy
                if cfg_path == _BACKUP_FILE and not CONFIG_FILE.exists():
                    save_config()
                    log("Config migrated to launcher folder", "info")
                return
            except Exception as e:
                log(f"Config load error from {cfg_path}: {e}", "warn")
    _config = {}
    _portable_defaults()

def _portable_defaults():
    """Philibert: the vault lives on the drive, and the Internet starts OFF."""
    if not PORTABLE:
        return
    _config["obsidian_root"] = str(_CONFIG_DIR)
    _config["obsidian_vault"] = "vault"
    (_CONFIG_DIR / "vault").mkdir(parents=True, exist_ok=True)
    _config.setdefault("online", False)


def internet_on():
    """Full ND is always online; Philibert only when the user switched it on."""
    return (not PORTABLE) or bool(_config.get("online", False))


def network_refusal(name, a):
    """'' when the call may go ahead, else the message the model gets."""
    if name not in NETWORK_TOOLS or internet_on():
        return ""
    if name == "browser_open":
        u = str((a or {}).get("url") or "").strip().lower()
        if re.match(r"^(file:|https?://(localhost|127\.0\.0\.1)(:|/|$))", u):
            return ""
    return ("[OFFLINE] " + PRODUCT + " is offline - the Internet switch is OFF, so "
            f"{name} is not available. Tell the user what you would look up, and that "
            "they can turn the Internet switch on in the toolbar (INTERNET: OFF) to allow it.")


def save_config():
    """Save config next to launcher. Always write, never silently fail."""
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(_config, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"Config save failed: {e}", "error")
        # Fallback to C:\Heretic
        try:
            HERETIC_DIR.mkdir(parents=True, exist_ok=True)
            _BACKUP_FILE.write_text(json.dumps(_config, indent=2), encoding="utf-8")
            log("Config saved to fallback location", "warn")
        except Exception as e2:
            log(f"Config fallback save also failed: {e2}", "error")

# ??? Shared state ?????????????????????????????????????????????????????????????
_lock         = threading.Lock()
status_log    = []
setup_running = False
_pull_status  = {}
_scan_results = []   # [{path, size_mb, type, suggested_dest}]
_gen_jobs     = {}   # job_id -> {status, result, error}

_cache = {
    "python": False, "cuda": False, "ollama": False,
    "comfyui": False, "heretic": False, "whisper": False,
    "tts": False, "models": [], "comfyui_dir": None,
    "cogvideo": False,
    "install_base": None, "needs_drive_config": False,
}

def log(msg, level="info"):
    with _lock:
        status_log.append({"msg": msg, "level": level, "t": time.strftime("%H:%M:%S")})
    print(f"[{level.upper()}] {msg}", flush=True)

def set_cache(key, value):
    with _lock:
        _cache[key] = value

def get_cache():
    with _lock:
        return dict(_cache)

# ??? Run helpers ??????????????????????????????????????????????????????????????
def run(cmd, cwd=None, timeout=30):
    try:
        r = subprocess.run(cmd, shell=True, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           cwd=cwd, timeout=timeout)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "timeout"
    except Exception as e:
        return False, "", str(e)

def run_visible(cmd, cwd=None):
    try:
        proc = subprocess.Popen(cmd, shell=True, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                cwd=cwd)
        lines = []
        for line in proc.stdout:
            print(line, end="", flush=True)
            lines.append(line)
        proc.wait()
        return proc.returncode == 0, "".join(lines), ""
    except Exception as e:
        return False, "", str(e)

def run_capture(cmd, timeout=3600, cwd=None):
    """Run command silently and capture all output. Used for automated pipelines."""
    try:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout, cwd=cwd, env=env
        )
        log(f"[run_capture] rc={result.returncode} stdout={result.stdout[:200]}", "info")
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Timed out after {timeout}s"
    except Exception as e:
        return False, "", str(e)

# ??? Checks ???????????????????????????????????????????????????????????????????
def _check_python():
    ok, out, _ = run("python --version")
    if ok:
        try:
            parts = out.split()[-1].split(".")
            return int(parts[0]) >= 3 and int(parts[1]) >= 10
        except: return False
    return False

def _check_cuda():
    """True when torch has a working GPU accelerator - any vendor.

    The cache key stays "cuda" because the UI badge reads it, but the question
    is no longer "is this NVIDIA". A ROCm build answers through torch.cuda
    (HIP is mapped onto that namespace); Intel answers through torch.xpu. The
    old check returned False on both, and the caller responded by reinstalling
    a CUDA wheel on every boot, forever.
    """
    if not VENV_PY.exists(): return False
    ok, out, _ = run(
        f'"{VENV_PY}" -c "import torch;'
        f' x=getattr(torch,\'xpu\',None);'
        f' print(torch.cuda.is_available() or bool(x and x.is_available()))"')
    return ok and "True" in out

def _ensure_portable_ollama(timeout=40):
    """Philibert: the launcher starts the drive's Ollama. Wait for it; start it
    from ND_OLLAMA_EXE only if it is not up. Never the host's install."""
    if _check_ollama():
        return True
    exe = os.environ.get("ND_OLLAMA_EXE")
    if exe and Path(exe).is_file():
        try:
            env = dict(os.environ)
            env["OLLAMA_HOST"] = OLLAMA_URL.split("://", 1)[-1]
            subprocess.Popen([exe, "serve"], env=env,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            log(f"Could not start the drive's Ollama: {e}", "error")
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _check_ollama():
            return True
        time.sleep(1)
    return False


def ensure_ollama_running(timeout=40):
    if PORTABLE:
        return _ensure_portable_ollama(timeout)
    """Start Ollama if it is not answering.

    The .bat launcher checks this, but running NeuralDock_launcher.py directly
    skips it - and then the whole app is dead in the water with only an
    "OLLAMA OFFLINE" badge to explain why. ComfyUI already self-heals like
    this; Ollama should too, since nothing works without it.
    """
    if _check_ollama():
        return True
    log("Ollama is not responding - starting it...", "warn")
    app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
    try:
        if app.exists():
            subprocess.Popen([str(app)])          # tray app, restores user settings
        else:
            subprocess.Popen(["ollama", "serve"],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        log(f"Could not start Ollama: {e}", "error")
        return False
    for _ in range(timeout):
        time.sleep(1)
        if _check_ollama():
            log("Ollama is up", "ok")
            return True
    log("Ollama did not come up in time", "error")
    return False

def _check_ollama():
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2)
        return True
    except: return False

def _check_comfyui():
    try:
        urllib.request.urlopen(f"{COMFYUI_URL}/system_stats", timeout=2)
        return True
    except: return False

def _check_heretic():
    if not VENV_PY.exists(): return False
    ok, _, _ = run(f'"{VENV_PY}" -c "import heretic"')
    if ok: return True
    ok2, _, _ = run(f'"{VENV_PY}" -m heretic --help')
    return ok2

def _check_whisper():
    """Can THIS process transcribe?

    Two bugs met here. transcribe_audio() uses faster-whisper (CTranslate2), not
    openai-whisper, and the old check imported "whisper" -- which is installed,
    so it always said yes. And it shelled out to VENV_PY while the transcription
    runs in-process, so it was answering for a different interpreter entirely.
    ND launched under a bare python reported "whisper: True" while every slice
    came back "No module named 'faster_whisper'", which is why the wake word
    could never fire and nothing said why.
    """
    import importlib.util
    return importlib.util.find_spec("faster_whisper") is not None

def _check_tts():
    # Same two faults as _check_whisper: speak() imports piper, not pyttsx3, and
    # it does so in this process rather than in VENV_PY.
    import importlib.util
    return importlib.util.find_spec("piper") is not None

def _check_cogvideo():
    if not VENV_PY.exists(): return False
    ok, _, _ = run(f'"{VENV_PY}" -c "from diffusers import CogVideoXPipeline"')
    if ok: return True
    # Also check if package exists under alternate import
    ok2, _, _ = run(f'"{VENV_PY}" -c "import diffusers; print(diffusers.__version__)"')
    return ok2

def _get_models():
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
            data = json.loads(r.read())
            return [m["name"] for m in data.get("models", [])]
    except: return []

def refresh_status_cache():
    base = get_install_base()
    set_cache("python",  _check_python())
    set_cache("cuda",    _check_cuda())
    set_cache("ollama",  _check_ollama())
    set_cache("comfyui", _check_comfyui())
    set_cache("heretic", _check_heretic())
    set_cache("whisper", _check_whisper())
    set_cache("tts",     _check_tts())
    set_cache("models",  _get_models())
    set_cache("cogvideo",    _check_cogvideo())
    set_cache("install_base", str(base) if base else None)
    set_cache("needs_drive_config", base is None)
    cd = get_comfyui_dir()
    set_cache("comfyui_dir", str(cd) if cd else None)

def start_status_loop():
    def loop():
        while True:
            try: refresh_status_cache()
            except Exception as e: log(f"Status refresh error: {e}", "warn")
            time.sleep(10)
    threading.Thread(target=loop, daemon=True).start()

# ??? Venv + installers ????????????????????????????????????????????????????????
def ensure_venv():
    if VENV_PY.exists(): return True
    log("Creating C:\\Heretic venv...", "info")
    HERETIC_DIR.mkdir(parents=True, exist_ok=True)
    ok, o, e = run(f'python -m venv "{VENV_DIR}"')
    if ok:
        log("Venv created [OK]", "ok")
        run_visible(f'"{VENV_PIP}" install --upgrade pip')
        return True
    log(f"Venv failed: {e}", "error")
    return False

def venv_install(packages, label):
    if not ensure_venv(): return False
    log(f"Installing {label}...", "info")
    ok, o, e = run_visible(f'"{VENV_PIP}" install {packages}')
    if ok: log(f"{label} [OK]", "ok")
    else:  log(f"{label} FAILED", "error")
    threading.Thread(target=refresh_status_cache, daemon=True).start()
    return ok

def install_pytorch():
    # Wheel index follows the detected vendor: cu128 / rocm / xpu / cpu.
    try:
        import nd_gpu
        url, label = nd_gpu.torch_index_url(), nd_gpu.vendor().upper()
    except Exception:
        url, label = "https://download.pytorch.org/whl/cu128", "CUDA"
    return venv_install(f"torch torchvision torchaudio --index-url {url}",
                        f"{label} PyTorch")
def install_heretic():  return venv_install("-U heretic-llm", "Heretic LLM")
def install_whisper():  return venv_install("openai-whisper", "Whisper STT")
def install_tts():      return venv_install("pyttsx3", "pyttsx3 TTS")
def install_extras():   return venv_install("pillow opencv-python PyMuPDF huggingface_hub requests websocket-client tqdm", "extras")
def install_llamacpp():
    """Install llama-cpp-python for GGUF conversion of Heretic models."""
    log("Installing llama-cpp-python (GGUF converter)...", "info")
    # Try CUDA version first, fall back to CPU
    ok = venv_install(
        "llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu128",
        "llama-cpp-python (CUDA)"
    )
    if not ok:
        ok = venv_install("llama-cpp-python", "llama-cpp-python (CPU)")
    return ok

def convert_to_gguf(src_path, dest_path=None):
    """Convert a HuggingFace model to GGUF format for Ollama."""
    src = Path(src_path)
    if not src.exists():
        return False, f"Source path not found: {src_path}"
    if dest_path is None:
        dest_path = str(src.parent / (src.name + ".gguf"))
    dest = Path(dest_path)
    log(f"Converting {src.name} to GGUF format...", "info")
    # Try using llama.cpp convert script
    script = f"""
import sys
try:
    from llama_cpp import llama_cpp
    print("llama-cpp-python available")
except ImportError:
    print("llama-cpp-python not installed")
    sys.exit(1)
"""
    # Use huggingface hub to download convert script if needed
    convert_script = HERETIC_DIR / "convert_hf_to_gguf.py"
    if not convert_script.exists():
        log("Downloading llama.cpp conversion script...", "info")
        script_url = "https://raw.githubusercontent.com/ggerganov/llama.cpp/master/convert_hf_to_gguf.py"
        ok = download_file(script_url, convert_script, "GGUF converter script")
        if not ok:
            return False, "Could not download GGUF conversion script"

    log(f"Running GGUF conversion on {src_path}...", "info")
    # convert_hf_to_gguf.py accepts only f32, f16, bf16, q8_0, tq1_0, tq2_0 and
    # auto. It has never accepted q4_K_M, which this passed for a long time, so
    # every conversion through here failed on an argparse error. The k-quants
    # come from a separate step: ollama create -q q4_K_M does it at import time,
    # which is why this only has to produce a faithful 16-bit GGUF.
    ok, out, err = run_visible(
        f'"{VENV_PY}" "{convert_script}" "{src_path}" --outfile "{dest_path}" --outtype bf16',
        cwd=str(HERETIC_DIR)
    )
    if ok and dest.exists():
        log(f"GGUF conversion complete: {dest_path}", "ok")
        return True, dest_path
    return False, f"Conversion failed: {err[:300]}"
def install_hf_hub():   return venv_install("huggingface_hub", "HF Hub")
def install_cogvideo():
    log("Installing CogVideoX dependencies...", "info")
    ok = venv_install("diffusers transformers accelerate imageio imageio-ffmpeg sentencepiece", "CogVideoX")
    if ok:
        # Pre-download model to T:/NeuralDock/CogVideoX if T: available
        base = get_install_base()
        if base:
            cog_dir = base / "CogVideoX"
            cog_dir.mkdir(parents=True, exist_ok=True)
            log(f"CogVideoX will cache models to {cog_dir}", "info")
            # Set HF cache dir so model downloads to T: not C:
            _config["hf_cache_dir"] = str(cog_dir)
            save_config()
            log("CogVideoX configured to use T: drive for model storage [OK]", "ok")
    return ok

def run_full_setup():
    global setup_running
    if setup_running:
        log("Setup already running", "warn"); return
    setup_running = True
    try:
        log("=== ESTEEF.AI // NeuralDock Auto-Setup v3.0 ===", "info")
        # Ensure requests is available early -- needed for model downloads
        try:
            import requests
        except ImportError:
            log("Installing requests library...", "info")
            venv_install("requests", "requests")
        if not _check_python():
            log("Python 3.10+ not found", "error"); return
        if not ensure_venv(): return
        c = get_cache()
        if not c["cuda"]:    install_pytorch()
        else: log("PyTorch present", "info")
        if not c["heretic"]: install_heretic()
        else: log("Heretic present", "info")
        if not c["whisper"]: install_whisper()
        else: log("Whisper present", "info")
        if not c["tts"]:     install_tts()
        else: log("TTS present", "info")
        install_extras()
        # Install CogVideoX if not present
        if not _check_cogvideo():
            log("CogVideoX not found -- installing...", "info")
            install_cogvideo()
        else:
            log("CogVideoX present [OK]", "info")
        log("=== Setup Complete [OK] ===", "ok")
    finally:
        setup_running = False
        threading.Thread(target=refresh_status_cache, daemon=True).start()

# ??? ComfyUI management ???????????????????????????????????????????????????????
_comfyui_proc = None


# ??? ComfyUI installer ????????????????????????????????????????????????????????
def install_comfyui():
    """Clone ComfyUI to T:/ComfyUI (or configured dir), install its deps."""
    base = get_install_base()
    if not base:
        log("No install base configured -- set a drive in Setup first", "error")
        return False

    target = base.parent / "ComfyUI"  # e.g. T:/EsteefAi/../ComfyUI = T:/ComfyUI
    # If config has a specific comfyui_dir, use that instead
    cfg_dir = _config.get("comfyui_dir","").strip()
    if cfg_dir:
        target = Path(cfg_dir)
    _config["comfyui_dir"] = str(target)
    save_config()

    if (target / "main.py").exists():
        log(f"ComfyUI already exists at {target}", "info")
        return True

    log(f"Installing ComfyUI to {target}...", "info")
    target.parent.mkdir(parents=True, exist_ok=True)

    # Clone repo
    ok, o, e = run(f'git clone https://github.com/comfyanonymous/ComfyUI.git "{target}"', timeout=300)
    if not ok:
        log(f"ComfyUI clone failed: {e}", "error")
        return False
    log("ComfyUI cloned [OK]", "ok")

    # Install requirements using the Heretic venv (shared CUDA PyTorch)
    req = target / "requirements.txt"
    if req.exists():
        log("Installing ComfyUI Python requirements...", "info")
        ok2, o2, e2 = run_visible(f'"{VENV_PIP}" install -r "{req}"')
        if ok2:
            log("ComfyUI requirements installed [OK]", "ok")
        else:
            log(f"ComfyUI requirements warning: {e2}", "warn")

    # Create a launcher bat that uses the Heretic venv
    bat_content = (
        f'@echo off\r\n'
        f'title ESTEEF.AI // ComfyUI\r\n'
        f'call "{VENV_DIR}\\Scripts\\activate.bat"\r\n'
        f'cd /d "{target}"\r\n'
        f'python main.py --port 8188 {COMFY_PERF_ARGS}\r\n'
        f'pause\r\n'
    )
    bat_path = target / "run_neuraldock.bat"
    bat_path.write_text(bat_content)
    log(f"ComfyUI launcher created: {bat_path}", "ok")

    threading.Thread(target=refresh_status_cache, daemon=True).start()
    return True

def ensure_comfyui_running(timeout=90):
    """Start ComfyUI if not running. Auto-installs to T:/ComfyUI if not found. Returns True if ready."""
    global _comfyui_proc
    if _check_comfyui():
        return True

    comfyui_dir = get_comfyui_dir()

    # Auto-install if not found
    if not comfyui_dir or not (comfyui_dir / "main.py").exists():
        log("ComfyUI not found -- auto-installing to T:/ComfyUI...", "info")
        ok = install_comfyui()
        if not ok:
            log("ComfyUI auto-install failed -- check git is installed and T: drive is accessible", "error")
            return False
        comfyui_dir = get_comfyui_dir()
        if not comfyui_dir:
            log("ComfyUI dir still not found after install", "error")
            return False

    log(f"Starting ComfyUI from {comfyui_dir}...", "info")

    # Prefer our generated venv launcher, then the vendor bat, then CPU.
    # ComfyUI ships a different bat per backend (run_nvidia_gpu / run_amd_gpu /
    # run_intel_gpu), so ask nd_gpu which ones to look for instead of hardcoding
    # the NVIDIA one. run_cpu.bat is always the last resort.
    try:
        import nd_gpu
        _vendor_bats = nd_gpu.comfy_launchers()
    except Exception:
        _vendor_bats = ["run_nvidia_gpu.bat"]
    candidates = [comfyui_dir / "run_neuraldock.bat"]     # our generated bat
    candidates += [comfyui_dir / b for b in _vendor_bats]
    candidates.append(comfyui_dir / "run_cpu.bat")
    launched = False
    for bat in candidates:
        if bat.exists():
            _comfyui_proc = subprocess.Popen(
                [str(bat)], shell=True, cwd=str(comfyui_dir),
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name=="nt" else 0
            )
            log(f"ComfyUI started via {bat.name}", "info")
            launched = True
            break

    if not launched:
        # Fall back: run main.py directly with venv python
        main_py = comfyui_dir / "main.py"
        if not main_py.exists():
            log("ComfyUI main.py not found", "error")
            return False
        py = str(VENV_PY) if VENV_PY.exists() else "python"
        _comfyui_proc = subprocess.Popen(
            [py, str(main_py), "--port", "8188"] + COMFY_PERF_ARGS.split(),
            cwd=str(comfyui_dir),
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name=="nt" else 0
        )
        log(f"ComfyUI started via {py} main.py", "info")

    log(f"Waiting for ComfyUI to respond (up to {timeout}s)...", "info")
    for i in range(timeout):
        time.sleep(1)
        if _check_comfyui():
            log("ComfyUI ready [OK]", "ok")
            set_cache("comfyui", True)
            return True
        if i > 0 and i % 15 == 0:
            log(f"Still waiting for ComfyUI... ({i}s elapsed)", "info")

    log("ComfyUI did not respond in time after {}s -- check if it started correctly".format(timeout), "error")
    return False

def comfyui_post(endpoint, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{COMFYUI_URL}{endpoint}", data=data,
        headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise Exception(f"ComfyUI HTTP {e.code} on {endpoint}: {body[:300]}")

def comfyui_get(endpoint):
    with urllib.request.urlopen(f"{COMFYUI_URL}{endpoint}", timeout=10) as r:
        return json.loads(r.read())

# ??? ComfyUI model download ???????????????????????????????????????????????????
# Use ?download=true so HuggingFace serves the raw file, not an HTML redirect
SDXL_URL    = "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors?download=true"
SVD_URL     = "https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt/resolve/main/svd_xt.safetensors?download=true"
ANIMATEDIFF_URL = "https://huggingface.co/guoyww/animatediff/resolve/main/mm_sd_v15_v2.ckpt?download=true"

# Global download progress tracker — job_id -> progress info
_download_progress = {}

def download_file(url, dest_path, label, progress_key=None):
    """Download a file with streaming progress. Uses requests if available, falls back to urllib."""
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1024 * 1024:  # skip if >1MB already there
        log(f"{label} already exists ({dest.stat().st_size//1024//1024} MB), skipping", "info")
        return True

    log(f"Downloading {label}...", "info")
    log(f"  URL: {url}", "info")
    log(f"  Dest: {dest}", "info")

    tmp_path = dest.with_suffix('.tmp')

    # Try using requests library first (handles redirects + progress better)
    try:
        import requests
        headers = {"User-Agent": "NeuralDock/3.0"}
        # Add HF token if configured
        hf_token = _config.get("hf_token", "")
        if hf_token:
            headers["Authorization"] = f"Bearer {hf_token}"

        with requests.get(url, stream=True, headers=headers, timeout=30, allow_redirects=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            last_pct = -1
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):  # 8MB chunks
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = int(downloaded / total * 100)
                            if pct != last_pct and pct % 2 == 0:
                                mb_done  = downloaded // 1024 // 1024
                                mb_total = total // 1024 // 1024
                                log(f"{label}: {pct}% ({mb_done}/{mb_total} MB)", "info")
                                last_pct = pct
                                # Update global progress tracker
                                if progress_key:
                                    _download_progress[progress_key] = {
                                        "pct": pct,
                                        "mb_done": mb_done,
                                        "mb_total": mb_total,
                                        "label": label
                                    }
                        else:
                            mb = downloaded // 1024 // 1024
                            if mb % 100 == 0 and mb > 0:
                                log(f"{label}: {mb} MB downloaded...", "info")
                                if progress_key:
                                    _download_progress[progress_key] = {
                                        "pct": -1, "mb_done": mb,
                                        "mb_total": 0, "label": label
                                    }

        tmp_path.rename(dest)
        log(f"{label} downloaded [OK] ({dest.stat().st_size//1024//1024} MB)", "ok")
        return True

    except ImportError:
        log("requests not available, falling back to urllib", "warn")
    except Exception as e:
        log(f"{label} download failed (requests): {e}", "error")
        if tmp_path.exists():
            tmp_path.unlink()
        return False

    # Fallback: urllib with streaming
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NeuralDock/3.0"})
        hf_token = _config.get("hf_token", "")
        if hf_token:
            req.add_header("Authorization", f"Bearer {hf_token}")

        with urllib.request.urlopen(req, timeout=30) as response:
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            last_pct = -1
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = response.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = int(downloaded / total * 100)
                        if pct != last_pct and pct % 5 == 0:
                            mb_done = downloaded // 1024 // 1024
                            mb_total = total // 1024 // 1024
                            log(f"{label}: {pct}% ({mb_done}/{mb_total} MB)", "info")
                            last_pct = pct

        tmp_path.rename(dest)
        log(f"{label} downloaded [OK]", "ok")
        return True

    except Exception as e:
        log(f"{label} download failed: {e}", "error")
        if tmp_path.exists():
            tmp_path.unlink()
        return False

def ensure_sd_models():
    comfyui_dir = get_comfyui_dir()
    if not comfyui_dir:
        log("ComfyUI dir not set -- cannot download models", "error")
        return False
    ckpt_dir = comfyui_dir / "models" / "checkpoints"
    motion_dir = comfyui_dir / "custom_nodes" / "ComfyUI-AnimateDiff-Evolved" / "models"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    ok1 = download_file(SDXL_URL,    ckpt_dir / "sd_xl_base_1.0.safetensors",    "SDXL Base")
    ok2 = download_file(SVD_URL,     ckpt_dir / "svd_xt.safetensors",             "SVD-XT")
    return ok1

def install_animatediff_node():
    comfyui_dir = get_comfyui_dir()
    if not comfyui_dir:
        log("ComfyUI dir not found", "error"); return False
    nodes_dir = comfyui_dir / "custom_nodes"
    ad_dir    = nodes_dir / "ComfyUI-AnimateDiff-Evolved"
    if ad_dir.exists():
        log("AnimateDiff node already installed", "info"); return True
    log("Installing AnimateDiff-Evolved node...", "info")
    ok, o, e = run(f'git clone https://github.com/Kosinkadink/ComfyUI-AnimateDiff-Evolved.git "{ad_dir}"')
    if ok:
        log("AnimateDiff node installed [OK]", "ok")
        # Download motion module
        motion_dir = ad_dir / "models"
        motion_dir.mkdir(parents=True, exist_ok=True)
        download_file(ANIMATEDIFF_URL, motion_dir / "mm_sd_v15_v2.ckpt", "AnimateDiff motion module")
        return True
    log(f"AnimateDiff install failed: {e}", "error")
    return False

# ??? ComfyUI workflow builders ????????????????????????????????????????????????
def build_sdxl_workflow(prompt, negative="", width=1024, height=1024, steps=20, cfg=7.0, checkpoint=None, seed=-1,
                        lora=None, lora_strength=0.8, init_image=None, denoise=1.0):
    if seed == -1:
        import random
        seed = random.randint(0, 2**32-1)
    # Base refs; LoRA re-routes model+clip through the LoraLoader
    model_ref, clip_ref = ["4", 0], ["4", 1]
    wf = {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "euler", "scheduler": "karras",
            "denoise": (denoise if init_image else 1.0),
            "model": model_ref, "positive": ["6", 0],
            "negative": ["7", 0], "latent_image": ["5", 0]
        }},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": (checkpoint or "sd_xl_base_1.0.safetensors")}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": clip_ref}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative or "blurry, ugly, bad anatomy", "clip": clip_ref}},
        "8": {"class_type": "VAEDecode",    "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage",    "inputs": {"filename_prefix": "neuraldock_sd", "images": ["8", 0]}}
    }
    if lora:
        wf["10"] = {"class_type": "LoraLoader", "inputs": {
            "lora_name": lora, "strength_model": float(lora_strength), "strength_clip": float(lora_strength),
            "model": ["4", 0], "clip": ["4", 1]
        }}
        wf["3"]["inputs"]["model"] = ["10", 0]
        wf["6"]["inputs"]["clip"]  = ["10", 1]
        wf["7"]["inputs"]["clip"]  = ["10", 1]
    if init_image:
        # img2img: load inspiration image, scale to target size, encode to latent
        wf["11"] = {"class_type": "LoadImage",  "inputs": {"image": init_image}}
        wf["12"] = {"class_type": "ImageScale", "inputs": {
            "upscale_method": "lanczos", "width": width, "height": height,
            "crop": "center", "image": ["11", 0]
        }}
        wf["13"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["12", 0], "vae": ["4", 2]}}
        wf["3"]["inputs"]["latent_image"] = ["13", 0]
        del wf["5"]
    return wf

def is_flux_model(name):
    """Detect Flux-family models by filename."""
    return bool(name) and "flux" in Path(str(name)).name.lower()

def save_input_image(b64data):
    """Save a base64/dataURL image into ComfyUI's input folder; return the filename for LoadImage."""
    comfyui = get_comfyui_dir()
    if not comfyui:
        raise Exception("ComfyUI directory not configured")
    if "," in b64data[:100]:  # strip data:image/...;base64, prefix
        b64data = b64data.split(",", 1)[1]
    img_bytes = base64.b64decode(b64data)
    input_dir = comfyui / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    fname = f"nd_insp_{uuid.uuid4().hex[:10]}.png"
    (input_dir / fname).write_bytes(img_bytes)
    return fname

def _find_model_file(folder, keywords, label):
    """Find first model file in folder whose name contains any keyword. Raises with a helpful message."""
    if folder.exists():
        for f in sorted(os.listdir(str(folder))):
            fl = f.lower()
            if Path(f).suffix.lower() in {".safetensors",".sft",".ckpt",".pt"} and any(k in fl for k in keywords):
                return f
    raise Exception(f"Flux requires {label} in {folder} — file not found. "
                    f"Expected a file containing one of: {', '.join(keywords)}")

def build_flux_workflow(prompt, negative="", width=1024, height=1024, steps=20, cfg=3.5, checkpoint="flux1-dev.safetensors", seed=-1,
                        lora=None, lora_strength=0.8, init_image=None, denoise=1.0):
    """Flux workflow: UNETLoader + DualCLIPLoader + FluxGuidance. `negative` is ignored (Flux uses guidance, not CFG)."""
    if seed == -1:
        import random
        seed = random.randint(0, 2**32-1)
    comfyui = get_comfyui_dir()
    if not comfyui:
        raise Exception("ComfyUI directory not configured")
    clip_dir = comfyui / "models" / "clip"
    vae_dir  = comfyui / "models" / "vae"
    clip_l = _find_model_file(clip_dir, ["clip_l"], "the CLIP-L text encoder")
    t5     = _find_model_file(clip_dir, ["t5xxl","t5-xxl"], "the T5-XXL text encoder")
    vae    = _find_model_file(vae_dir,  ["ae.safetensors".lower(),"flux","ae."], "the Flux VAE (ae.safetensors)")
    # Flux guidance: sensible range ~1-5; if user left SDXL-style CFG, clamp it
    guidance = float(cfg)
    if guidance > 6: guidance = 3.5
    wf = {
        "1": {"class_type": "UNETLoader",     "inputs": {"unet_name": checkpoint, "weight_dtype": "default"}},
        "2": {"class_type": "DualCLIPLoader", "inputs": {"clip_name1": t5, "clip_name2": clip_l, "type": "flux"}},
        "3": {"class_type": "VAELoader",      "inputs": {"vae_name": vae}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "FluxGuidance",   "inputs": {"conditioning": ["4", 0], "guidance": guidance}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "7": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "denoise": (denoise if init_image else 1.0),
            "model": ["1", 0], "positive": ["5", 0],
            "negative": ["6", 0], "latent_image": ["7", 0]
        }},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": "neuraldock_flux", "images": ["9", 0]}}
    }
    if lora:
        wf["20"] = {"class_type": "LoraLoader", "inputs": {
            "lora_name": lora, "strength_model": float(lora_strength), "strength_clip": float(lora_strength),
            "model": ["1", 0], "clip": ["2", 0]
        }}
        wf["8"]["inputs"]["model"] = ["20", 0]
        wf["4"]["inputs"]["clip"]  = ["20", 1]
    if init_image:
        wf["21"] = {"class_type": "LoadImage",  "inputs": {"image": init_image}}
        wf["22"] = {"class_type": "ImageScale", "inputs": {
            "upscale_method": "lanczos", "width": width, "height": height,
            "crop": "center", "image": ["21", 0]
        }}
        wf["23"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["22", 0], "vae": ["3", 0]}}
        wf["8"]["inputs"]["latent_image"] = ["23", 0]
        del wf["7"]
    return wf

# Checkpoints that sit in models/checkpoints but cannot make a picture from a prompt:
# Stable Video Diffusion (image -> video), IC-Light (relighting an input photo),
# AnimateDiff motion modules. Both SVD and IC-Light were picked for box art on
# 2026-09-29 and failed inside ComfyUI.
NOT_TEXT2IMAGE = ("svd", "iclight", "ic_light", "ic-light", "mm_sd", "motion", "animatediff",
                  "controlnet", "control_", "upscale", "inpaint")


def is_text2image_model(name):
    n = Path(str(name)).name.lower()
    return not any(k in n for k in NOT_TEXT2IMAGE)


def default_image_model():
    """What a chat image uses when no model is named: Z-Image Turbo if installed
    (distilled, 8 steps, and far better at rendering words than SDXL), else None ->
    the SDXL base checkpoint."""
    comfy = get_comfyui_dir()
    if not comfy:
        return None
    for sub in ("diffusion_models", "unet"):
        d = comfy / "models" / sub
        if d.exists():
            for f in sorted(d.rglob("*.safetensors")):
                if is_zimage_model(f.name):
                    return f.relative_to(d).as_posix()
    return None


def is_zimage_model(name):
    n = Path(str(name)).name.lower()
    return "z_image" in n or "zimage" in n or "z-image" in n

def build_zimage_workflow(prompt, negative="", width=1024, height=1024, steps=8, cfg=1.0, checkpoint="z_image_turbo_bf16.safetensors", seed=-1,
                          lora=None, lora_strength=0.8, init_image=None, denoise=1.0):
    """Z-Image Turbo workflow (Lumina arch): UNETLoader + CLIPLoader(lumina2, Qwen3-4B) + ModelSamplingAuraFlow."""
    if seed == -1:
        import random
        seed = random.randint(0, 2**32-1)
    comfyui = get_comfyui_dir()
    if not comfyui:
        raise Exception("ComfyUI directory not configured")
    te_dir  = comfyui / "models" / "text_encoders"
    vae_dir = comfyui / "models" / "vae"
    qwen = _find_model_file(te_dir,  ["qwen_3","qwen3","qwen"], "the Qwen3-4B text encoder (qwen_3_4b.safetensors)")
    vae  = _find_model_file(vae_dir, ["ae.safetensors".lower(),"flux","ae."], "the VAE (ae.safetensors)")
    # Z-Image Turbo is distilled: 8 steps, cfg 1.0 regardless of UI values
    z_steps = min(int(steps), 12) if int(steps) > 0 else 8
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": checkpoint, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": qwen, "type": "lumina2"}},
        "3": {"class_type": "VAELoader",  "inputs": {"vae_name": vae}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"shift": 3, "model": ["1", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": negative or "", "clip": ["2", 0]}},
        "7": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": z_steps, "cfg": 1.0,
            "sampler_name": "res_multistep", "scheduler": "simple",
            "denoise": (denoise if init_image else 1.0),
            "model": ["4", 0], "positive": ["5", 0],
            "negative": ["6", 0], "latent_image": ["7", 0]
        }},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"filename_prefix": "neuraldock_zimage", "images": ["9", 0]}}
    }
    if lora:
        wf["20"] = {"class_type": "LoraLoader", "inputs": {
            "lora_name": lora, "strength_model": float(lora_strength), "strength_clip": float(lora_strength),
            "model": ["1", 0], "clip": ["2", 0]
        }}
        wf["4"]["inputs"]["model"] = ["20", 0]
        wf["5"]["inputs"]["clip"]  = ["20", 1]
        wf["6"]["inputs"]["clip"]  = ["20", 1]
    if init_image:
        wf["21"] = {"class_type": "LoadImage",  "inputs": {"image": init_image}}
        wf["22"] = {"class_type": "ImageScale", "inputs": {
            "upscale_method": "lanczos", "width": width, "height": height,
            "crop": "center", "image": ["21", 0]
        }}
        wf["23"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["22", 0], "vae": ["3", 0]}}
        wf["8"]["inputs"]["latent_image"] = ["23", 0]
        del wf["7"]
    return wf

def build_image_workflow(prompt, negative="", width=1024, height=1024, steps=20, cfg=7.0, checkpoint=None,
                         lora=None, lora_strength=0.8, init_image=None, denoise=1.0, model_kind=None):
    """Route to the right workflow builder based on the selected model family."""
    if checkpoint and not is_text2image_model(checkpoint):
        raise Exception(
            f"'{checkpoint}' is not a text-to-image model (it is a video, relighting or "
            "motion model) - pick Z-Image, FLUX or an SDXL / SD 1.5 checkpoint.")
    if checkpoint and is_flux_model(checkpoint):
        return build_flux_workflow(prompt, negative, width, height, steps, cfg, checkpoint,
                                   lora=lora, lora_strength=lora_strength, init_image=init_image, denoise=denoise)
    if checkpoint and is_zimage_model(checkpoint):
        return build_zimage_workflow(prompt, negative, width, height, steps, cfg, checkpoint,
                                     lora=lora, lora_strength=lora_strength, init_image=init_image, denoise=denoise)
    if model_kind == "diffusion":
        raise Exception(
            f"No workflow template for diffusion model '{checkpoint}' yet. "
            "Currently supported: FLUX and Z-Image diffusers, plus SDXL/SD checkpoints.")
    return build_sdxl_workflow(prompt, negative, width, height, steps, cfg, checkpoint,
                               lora=lora, lora_strength=lora_strength, init_image=init_image, denoise=denoise)

def build_animatediff_workflow(prompt, negative="", frames=16, steps=20, cfg=7.0, seed=-1,
                               width=512, height=512, fps=8, checkpoint=None, motion=None,
                               init_image=None, denoise=0.6):
    if seed == -1:
        import random
        seed = random.randint(0, 2**32-1)
    frames = max(4, min(int(frames), 64))
    wf = {
        "1":  {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": (checkpoint or "v1-5-pruned-emaonly-fp16.safetensors")}},
        "2":  {"class_type": "ADE_AnimateDiffLoaderWithContext", "inputs": {
            "model_name": (motion or "mm_sd_v15_v2.ckpt"), "beta_schedule": "autoselect",
            "model": ["1", 0]
        }},
        "3":  {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "4":  {"class_type": "CLIPTextEncode", "inputs": {"text": negative or "blurry, ugly", "clip": ["1", 1]}},
        "5":  {"class_type": "EmptyLatentImage","inputs": {"width": width, "height": height, "batch_size": frames}},
        "6":  {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "euler_ancestral", "scheduler": "normal",
            "denoise": 1.0,
            "model": ["2", 0], "positive": ["3", 0],
            "negative": ["4", 0], "latent_image": ["5", 0]
        }},
        "7":  {"class_type": "VAEDecode",    "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8":  {"class_type": "SaveAnimatedWEBP", "inputs": {
            "filename_prefix": "neuraldock_anim",
            "fps": fps, "lossless": False, "quality": 85, "method": "default",
            "images": ["7", 0]
        }}
    }
    if init_image:
        # vid2vid-ish: repeat the encoded source image across all frames, denoise controls drift
        wf["10"] = {"class_type": "LoadImage",  "inputs": {"image": init_image}}
        wf["11"] = {"class_type": "ImageScale", "inputs": {
            "upscale_method": "lanczos", "width": width, "height": height,
            "crop": "center", "image": ["10", 0]
        }}
        wf["12"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["11", 0], "vae": ["1", 2]}}
        wf["13"] = {"class_type": "RepeatLatentBatch", "inputs": {"samples": ["12", 0], "amount": frames}}
        wf["6"]["inputs"]["latent_image"] = ["13", 0]
        wf["6"]["inputs"]["denoise"] = float(denoise)
        del wf["5"]
    return wf

def build_svd_workflow(image_b64, steps=25, fps=6, seed=-1, width=1024, height=576, frames=25, checkpoint=None):
    if seed == -1:
        import random
        seed = random.randint(0, 2**32-1)
    frames = max(5, min(int(frames), 25))  # svd_xt is trained for up to 25 frames
    return {
        "1":  {"class_type": "ImageOnlyCheckpointLoader", "inputs": {"ckpt_name": (checkpoint or "svd_xt.safetensors")}},
        "2":  {"class_type": "LoadImage",                  "inputs": {"image": save_input_image(image_b64)}},
        "3":  {"class_type": "SVD_img2vid_Conditioning",   "inputs": {
            "width": width, "height": height, "video_frames": frames,
            "motion_bucket_id": 127, "fps": fps, "augmentation_level": 0.02,
            "clip_vision": ["1", 1], "init_image": ["2", 0], "vae": ["1", 2]
        }},
        "4":  {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": 2.5,
            "sampler_name": "euler", "scheduler": "karras", "denoise": 1.0,
            "model": ["1", 0], "positive": ["3", 0], "negative": ["3", 1],
            "latent_image": ["3", 2]
        }},
        "5":  {"class_type": "VAEDecodeTiled", "inputs": {"tile_size": 256, "overlap": 64, "temporal_size": 64, "temporal_overlap": 8, "samples": ["4", 0], "vae": ["1", 2]}},
        "6":  {"class_type": "SaveAnimatedWEBP", "inputs": {
            "filename_prefix": "neuraldock_svd",
            "fps": fps, "lossless": False, "quality": 85, "method": "default",
            "images": ["5", 0]
        }}
    }

# ??? Video post-processing (text overlay + format conversion) ????????????????
_FONT_MAP = {
    "arial":    "arial.ttf",
    "impact":   "impact.ttf",
    "courier":  "cour.ttf",
    "times":    "times.ttf",
    "comic":    "comic.ttf",
    "consolas": "consola.ttf",
    "georgia":  "georgia.ttf",
    "verdana":  "verdana.ttf",
}

def _load_overlay_font(name, size):
    from PIL import ImageFont
    fname = _FONT_MAP.get((name or "arial").lower(), "arial.ttf")
    for cand in [f"C:/Windows/Fonts/{fname}", fname, "C:/Windows/Fonts/arial.ttf"]:
        try:
            return ImageFont.truetype(cand, size)
        except Exception:
            continue
    from PIL import ImageFont as IF
    return IF.load_default()

def _overlay_frames(frames, overlay):
    from PIL import ImageDraw
    text = (overlay or {}).get("text", "")
    if not text:
        return frames
    color = overlay.get("color", "#ffffff")
    size  = int(overlay.get("size", 36))
    pos   = overlay.get("position", "bottom")
    font  = _load_overlay_font(overlay.get("font", "arial"), size)
    out = []
    for fr in frames:
        fr = fr.convert("RGB")
        d = ImageDraw.Draw(fr)
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
        x = max(4, (fr.width - tw)//2)
        if pos == "top":      y = 12
        elif pos == "middle": y = (fr.height - th)//2
        else:                 y = fr.height - th - 18
        # outline for readability
        for dx, dy in [(-2,0),(2,0),(0,-2),(0,2),(-1,-1),(1,1),(-1,1),(1,-1)]:
            d.text((x+dx, y+dy), text, font=font, fill="#000000")
        d.text((x, y), text, font=font, fill=color)
        out.append(fr)
    return out

def postprocess_video(data, fmt="webp", overlay=None, fps=8):
    """Decode an animated WebP from ComfyUI, optionally burn in a text overlay,
    and re-encode as webp / gif / mp4. Returns (bytes, ext, mime)."""
    import io, shutil
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    frames = []
    try:
        while True:
            frames.append(im.copy().convert("RGB"))
            im.seek(im.tell() + 1)
    except EOFError:
        pass
    if not frames:
        raise Exception("No frames decoded from video output")
    if overlay and overlay.get("text"):
        frames = _overlay_frames(frames, overlay)
    fps = max(1, int(fps or 8))
    dur = int(1000 / fps)
    if fmt == "gif":
        buf = io.BytesIO()
        frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                       duration=dur, loop=0, optimize=True)
        return buf.getvalue(), ".gif", "image/gif"
    if fmt == "mp4":
        ff = shutil.which("ffmpeg")
        if not ff:
            raise Exception("ffmpeg not found — cannot export MP4 (install ffmpeg or pick GIF/WebP)")
        tmpd = tempfile.mkdtemp()
        try:
            for i, f in enumerate(frames):
                f.save(os.path.join(tmpd, f"f_{i:05d}.png"))
            outp = os.path.join(tmpd, "out.mp4")
            r = subprocess.run([ff, "-y", "-framerate", str(fps), "-i",
                                os.path.join(tmpd, "f_%05d.png"),
                                "-c:v", "libx264", "-pix_fmt", "yuv420p", outp],
                               capture_output=True, timeout=120)
            if r.returncode != 0:
                raise Exception("ffmpeg failed: " + r.stderr.decode(errors="ignore")[-200:])
            return Path(outp).read_bytes(), ".mp4", "video/mp4"
        finally:
            try: shutil.rmtree(tmpd, ignore_errors=True)
            except Exception: pass
    # default: webp
    buf = io.BytesIO()
    frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:],
                   duration=dur, loop=0, quality=85)
    return buf.getvalue(), ".webp", "image/webp"

# ??? CogVideoX (diffusers) ????????????????????????????????????????????????????
COG_HF_HOME = Path("G:/EsteefAi/HFCache")

def list_cogvideo_models():
    """CogVideoX snapshots present in the local HF cache."""
    out = []
    hub = COG_HF_HOME / "hub"
    if hub.exists():
        for d in hub.iterdir():
            if d.is_dir() and "cogvideox" in d.name.lower() and d.name.startswith("models--"):
                repo = d.name[len("models--"):].replace("--", "/")
                snaps = d / "snapshots"
                if snaps.exists() and any(snaps.iterdir()):
                    size_gb = 0
                    try:
                        size_gb = round(sum(f.stat().st_size for f in d.rglob("*") if f.is_file())/1024**3, 1)
                    except Exception: pass
                    out.append({"name": repo, "size_gb": size_gb})
    return out

def run_cogvideo_job(job_id, params, post=None):
    """Run CogVideoX in the Heretic venv, assemble frames, post-process, save to gallery."""
    import io, shutil
    from PIL import Image
    gallery = get_gallery_dir()
    outdir = Path(tempfile.mkdtemp())
    pfile  = outdir / "params.json"
    params = dict(params)
    params["hf_home"] = str(COG_HF_HOME)
    params["outdir"]  = str(outdir / "frames")
    pfile.write_text(json.dumps(params), encoding="utf-8")
    script = Path(__file__).parent / "cogvideo_gen.py"
    try:
        with _lock:
            _gen_jobs[job_id] = {"status":"generating","result":None,"error":None,
                                 "_status_msg":"loading CogVideoX (first run takes a few minutes)"}
        proc = subprocess.Popen([str(VENV_PY), str(script), str(pfile)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        deadline = time.time() + 10800  # 3h hard cap (5b on 16GB VRAM runs with CPU offload and is slow)
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("COG_STATUS"):
                with _lock:
                    if job_id in _gen_jobs: _gen_jobs[job_id]["_status_msg"] = line[10:].strip()
            if line.startswith("COG_ERROR"):
                raise Exception(line[9:].strip() or "CogVideoX failed")
            if time.time() > deadline:
                proc.kill()
                raise Exception("CogVideoX timed out after 3 hours")
        proc.wait()
        frames_dir = Path(params["outdir"])
        frame_files = sorted(frames_dir.glob("frame_*.png"))
        if proc.returncode != 0 or not frame_files:
            raise Exception("CogVideoX produced no frames (see launcher console for details)")
        frames = [Image.open(str(f)).convert("RGB") for f in frame_files]
        fps = int((post or {}).get("fps", 8))
        buf = io.BytesIO()
        frames[0].save(buf, format="WEBP", save_all=True, append_images=frames[1:],
                       duration=int(1000/max(1,fps)), loop=0, quality=85)
        data = buf.getvalue(); ext=".webp"; mime="image/webp"
        if post:
            try:
                data, ext, mime = postprocess_video(data, post.get("format","webp"), post.get("overlay"), fps)
            except Exception as pe:
                log(f"Cog job {job_id}: post-process failed ({pe})", "warn")
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_name = f"{ts}_{job_id[:8]}{ext}"
        out_path = (gallery / out_name) if gallery else Path(tempfile.mktemp(suffix=ext))
        out_path.write_bytes(data)
        with _lock:
            _gen_jobs[job_id] = {"status":"done","result":base64.b64encode(data).decode(),
                                 "mime":mime,"filename":out_name,"path":str(out_path),"error":None}
        log(f"Cog job {job_id} complete [OK]", "ok")
    except Exception as e:
        log(f"Cog job {job_id} error: {e}", "error")
        with _lock:
            _gen_jobs[job_id] = {"status":"error","error":str(e),"result":None}
    finally:
        try: shutil.rmtree(outdir, ignore_errors=True)
        except Exception: pass

# ??? ComfyUI job runner ???????????????????????????????????????????????????????
def unload_all_models(reason="a manual request"):
    """Evict every resident Ollama model and report what was freed.

    Split out of free_vram_for_comfy so it can be called unconditionally. That
    function is gated on the free_vram_for_comfy config flag (a user who wants
    the chat model to stay warm turns it off), but an explicit "unload the GPU"
    from the UI or from Unload_GPU.bat must never be silently skipped by a flag
    the user set for a different purpose.
    """
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/ps", timeout=8) as r:
            loaded = json.loads(r.read()).get("models", []) or []
    except Exception as e:
        return {"ok": False, "msg": f"Ollama did not answer: {e}",
                "unloaded": [], "freed_gb": 0}
    if not loaded:
        return {"ok": True, "msg": "Nothing was loaded - the GPU is already free.",
                "unloaded": [], "freed_gb": 0}
    total = sum(m.get("size", 0) for m in loaded)
    log(f"Freeing {total/1e9:.1f} GB of VRAM from Ollama for {reason}", "info")
    done, failed = [], []
    for m in loaded:
        name = m.get("name") or m.get("model")
        if not name:
            continue
        try:
            # keep_alive 0 tells Ollama to drop the model as soon as this returns
            payload = json.dumps({"model": name, "keep_alive": 0}).encode()
            req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", data=payload,
                                         headers={"Content-Type": "application/json"},
                                         method="POST")
            urllib.request.urlopen(req, timeout=60).read()
            log(f"  unloaded {name} ({m.get('size',0)/1e9:.1f} GB)", "ok")
            done.append({"model": name, "gb": round(m.get("size", 0) / 1e9, 1)})
        except Exception as e:
            log(f"  could not unload {name}: {e}", "warn")
            failed.append(name)
    # give the driver a moment to actually release the allocation
    for _ in range(20):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(f"{OLLAMA_URL}/api/ps", timeout=5) as r:
                if not (json.loads(r.read()).get("models") or []):
                    break
        except Exception:
            break
    freed = round(sum(d["gb"] for d in done), 1)
    msg = (f"Freed {freed} GB from {len(done)} model(s)." if done
           else "Nothing could be unloaded.")
    if failed:
        msg += " Still resident: " + ", ".join(failed)
    return {"ok": not failed, "msg": msg, "unloaded": done, "freed_gb": freed}


def free_vram_for_comfy(reason="image generation"):
    """Evict resident Ollama models before handing the GPU to ComfyUI.

    One 16 GB card cannot hold a chat model and a diffusion model at once.
    Ollama keeps the last-used model resident for `keep_alive` (60m by default),
    so an LLM used an hour ago will still be squatting on 11-20 GB when you ask
    for an image - ComfyUI then spills to system RAM and a 30s render turns into
    many minutes. Unloading first costs a few seconds of model reload later and
    is worth it every time.
    """
    if not _config.get("free_vram_for_comfy", True):
        return
    unload_all_models(reason)


def run_comfyui_workflow(workflow, job_id, output_type="image", post=None):
    """Submit workflow, poll until done, save output, return file path."""
    gallery = get_gallery_dir()
    free_vram_for_comfy(output_type + " generation")

    # Ensure ComfyUI is running -- transparent to user
    # Try to start ComfyUI -- max 60s wait
    if not ensure_comfyui_running(timeout=60):
        with _lock:
            _gen_jobs[job_id] = {
                "status": "error",
                "error": (
                    "ComfyUI did not start in time.\n"
                    "If this is your first time: go to ? Setup -> click INSTALL COMFYUI TO DRIVE\n"
                    "then try again after it finishes installing."
                )
            }
        return

    # Check required models exist before sending workflow
    comfyui_dir = get_comfyui_dir()
    if comfyui_dir:
        ckpt_dir = comfyui_dir / "models" / "checkpoints"
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        if output_type == "image":
            sdxl = ckpt_dir / "sd_xl_base_1.0.safetensors"
            if not sdxl.exists():
                log(f"SDXL model not found -- downloading to {sdxl} (~7GB, please wait...)", "warn")
                with _lock:
                    _gen_jobs[job_id]["status"] = "generating"
                    _gen_jobs[job_id]["error"] = None
                # Update status so UI shows download progress
                def _update_job_status(msg):
                    with _lock:
                        if job_id in _gen_jobs:
                            _gen_jobs[job_id]["_status_msg"] = msg
                ok = download_file(SDXL_URL, sdxl, "SDXL Base model")
                if not ok or not sdxl.exists():
                    with _lock:
                        _gen_jobs[job_id] = {
                            "status": "error",
                            "error": (
                                "SDXL model download failed.\n"
                                "Try: go to ? Setup -> DOWNLOAD NOW\n"
                                f"Or manually place sd_xl_base_1.0.safetensors in:\n{ckpt_dir}"
                            )
                        }
                    return
                log("SDXL model ready [OK]", "ok")

    with _lock:
        # Update existing entry (created before thread start) or create it
        _gen_jobs[job_id] = {"status": "queued", "result": None, "error": None}

    client_id = str(uuid.uuid4())
    try:
        # Queue prompt
        resp = comfyui_post("/prompt", {"prompt": workflow, "client_id": client_id})
        prompt_id = resp.get("prompt_id")
        if not prompt_id:
            raise Exception("No prompt_id returned from ComfyUI")

        with _lock:
            _gen_jobs[job_id]["status"] = "generating"

        log(f"Job {job_id}: queued in ComfyUI as {prompt_id}", "info")

        # Poll history until done
        # First run with SDXL can take 10+ min (model load + generation)
        max_wait = 720  # 12 minutes
        for attempt in range(max_wait):
            time.sleep(1)
            if attempt % 15 == 0 and attempt > 0:
                log(f"Job {job_id}: still running ({attempt}s)...", "info")
                # Also check if ComfyUI queue shows it's still pending
                try:
                    q = comfyui_get("/queue")
                    running = len(q.get("queue_running", []))
                    pending = len(q.get("queue_pending", []))
                    if running == 0 and pending == 0 and attempt > 30:
                        # Queue empty but no output yet - check history one more time
                        log(f"Job {job_id}: queue empty, checking history...", "info")
                except: pass
            try:
                history = comfyui_get(f"/history/{prompt_id}")
            except:
                continue
            if prompt_id not in history:
                continue
            job_data = history[prompt_id]
            # A FAILED prompt is in the history too, with no outputs. Waiting for
            # outputs alone left every failed job polling "queue empty, checking
            # history..." for the full 12 minutes (2026-09-29: five box-art jobs sent
            # with svd_xt, a video model, as the image checkpoint).
            _st = job_data.get("status") or {}
            if _st.get("status_str") == "error":
                _msg, _node = "ComfyUI reported an error", ""
                for _m in _st.get("messages") or []:
                    if isinstance(_m, list) and len(_m) == 2 and _m[0] == "execution_error":
                        _msg = str(_m[1].get("exception_message") or _msg).strip()
                        _node = str(_m[1].get("node_type") or "")
                raise Exception(f"ComfyUI could not run it{' (' + _node + ')' if _node else ''}: "
                                f"{_msg.splitlines()[0][:300]}")
            if "outputs" not in job_data:
                continue

            outputs = job_data["outputs"]
            # Find image/video outputs
            for node_id, node_out in outputs.items():
                images = node_out.get("images", [])
                gifs   = node_out.get("gifs", [])
                items  = images + gifs
                if not items:
                    continue
                item = items[0]
                filename  = item["filename"]
                subfolder = item.get("subfolder", "")
                itype     = item.get("type", "output")

                # Fetch from ComfyUI output
                url = f"{COMFYUI_URL}/view?filename={urllib.parse.quote(filename)}&subfolder={urllib.parse.quote(subfolder)}&type={itype}"
                with urllib.request.urlopen(url, timeout=30) as r:
                    img_bytes = r.read()

                # Optional post-processing for video: text overlay + format conversion
                mime_override = None
                ext_override  = None
                if output_type == "video" and post:
                    try:
                        img_bytes, ext_override, mime_override = postprocess_video(
                            img_bytes, post.get("format","webp"), post.get("overlay"), post.get("fps",8))
                    except Exception as pe:
                        log(f"Job {job_id}: post-process failed ({pe}) — keeping original output", "warn")

                # Save to gallery
                ext = ext_override or Path(filename).suffix or (".gif" if output_type == "video" else ".png")
                ts  = time.strftime("%Y%m%d_%H%M%S")
                out_name = f"{ts}_{job_id[:8]}{ext}"
                if gallery:
                    out_path = gallery / out_name
                    out_path.write_bytes(img_bytes)
                    log(f"Saved to gallery: {out_path}", "ok")
                else:
                    tmp = tempfile.mktemp(suffix=ext)
                    Path(tmp).write_bytes(img_bytes)
                    out_path = Path(tmp)

                b64 = base64.b64encode(img_bytes).decode()
                mime = mime_override or ("image/gif" if ext == ".gif" else ("video/mp4" if ext == ".mp4" else ("image/webp" if ext == ".webp" else "image/png")))

                with _lock:
                    _gen_jobs[job_id] = {
                        "status": "done",
                        "result": b64,
                        "mime": mime,
                        "filename": out_name,
                        "path": str(out_path),
                        "error": None
                    }
                log(f"Job {job_id} complete [OK]", "ok")
                return

        raise Exception(
            f"Timeout waiting for ComfyUI output after {max_wait}s. "
            "This can happen on first run while SDXL loads into VRAM (~2-4 min). "
            "Try clicking Generate Image again - it will be faster now the model is cached."
        )

    except Exception as e:
        log(f"Job {job_id} error: {e}", "error")
        with _lock:
            _gen_jobs[job_id] = {"status": "error", "error": str(e), "result": None}

# ??? Gallery ??????????????????????????????????????????????????????????????????
def get_gallery_items(limit=50):
    gallery = get_gallery_dir()
    if not gallery or not gallery.exists():
        return []
    items = []
    exts  = {".png",".jpg",".jpeg",".gif",".webp",".mp4"}
    for f in sorted(gallery.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        if f.suffix.lower() in exts:
            try:
                b64 = base64.b64encode(f.read_bytes()).decode()
                ext = f.suffix.lower()
                mime = "image/gif" if ext==".gif" else \
                       "image/webp" if ext==".webp" else \
                       "video/mp4" if ext==".mp4" else "image/png"
                items.append({"filename": f.name, "b64": b64, "mime": mime,
                               "path": str(f), "mtime": f.stat().st_mtime})
            except: pass
    return items

# ??? Drive scanner ????????????????????????????????????????????????????????????
MODEL_EXTS   = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf"}
SKIP_DIRS    = {"Windows","Program Files","Program Files (x86)","$Recycle.Bin",
                "AppData","ProgramData","System Volume Information","node_modules",
                "__pycache__","site-packages",".git"}

# Map of known model types: (name_patterns, category, subfolder_in_comfyui)
MODEL_CATEGORIES = [
    (["svd","stable-video","img2vid"],      "SVD - Stable Video Diffusion",   "models/checkpoints"),
    (["animatediff","motion_module","mm_sd"],"AnimateDiff Motion Module",      "custom_nodes/ComfyUI-AnimateDiff-Evolved/models"),
    (["sdxl","sd_xl","xl_base","xl_refiner"],"SDXL Checkpoint",               "models/checkpoints"),
    (["controlnet","control_"],              "ControlNet",                     "models/controlnet"),
    (["lora","loha","locon"],                "LoRA",                           "models/loras"),
    (["vae"],                                "VAE",                            "models/vae"),
    (["upscale","esrgan","realesrgan"],      "Upscaler",                       "models/upscale_models"),
    (["clip","text_encoder"],                "CLIP / Text Encoder",            "models/clip"),
    (["stable-diffusion","sd-v","v1-5","v2-1","dreamshaper","realistic"],
                                             "SD 1.x/2.x Checkpoint",         "models/checkpoints"),
    (["heretic","abliterated","decensored"], "Heretic Optimized Model",        None),  # goes to ollama
    (["cogvideo","cogvideox"],               "CogVideoX Model",                None),  # diffusers cache
]

def categorize_model(fname):
    """Return (category_label, suggested_comfyui_subfolder) for a model file."""
    nl = fname.lower()
    for patterns, label, subfolder in MODEL_CATEGORIES:
        if any(p in nl for p in patterns):
            return label, subfolder
    return "AI Model", "models/checkpoints"

def get_all_drives():
    drives = []
    for letter in string.ascii_uppercase:
        p = Path(f"{letter}:/")
        if p.exists():
            drives.append(p)
    return drives

def get_ollama_cache_dirs():
    """Find where Ollama stores its model files."""
    candidates = [
        Path.home() / ".ollama" / "models",
        Path(os.environ.get("OLLAMA_MODELS", "")) if os.environ.get("OLLAMA_MODELS") else None,
        Path("C:/Users") / os.environ.get("USERNAME","") / ".ollama" / "models",
    ]
    return [p for p in candidates if p and p.exists()]

def scan_drives_for_models():
    global _scan_results
    _scan_results = []
    drives = get_all_drives()
    log(f"Scanning {len(drives)} drive(s) for NeuralDock-related model files...", "info")

    comfyui    = get_comfyui_dir()
    base       = get_install_base()
    install_b  = str(base).lower() if base else ""
    comfyui_s  = str(comfyui).lower() if comfyui else ""

    found = []

    # 1. Scan all drives for model files
    for drive in drives:
        log(f"Scanning {drive}...", "info")
        try:
            for root, dirs, files in os.walk(str(drive), topdown=True):
                root_lower = root.lower()
                # Skip irrelevant system dirs
                dirs[:] = [d for d in dirs
                           if d not in SKIP_DIRS
                           and not d.startswith(".")]
                for fname in files:
                    ext = Path(fname).suffix.lower()
                    if ext not in MODEL_EXTS:
                        continue
                    full = Path(root) / fname
                    try:
                        size_mb = full.stat().st_size / (1024 * 1024)
                        if size_mb < 1:  # skip tiny files
                            continue
                        category, subfolder = categorize_model(fname)
                        # Build suggested dest
                        if subfolder and comfyui:
                            dest = str(comfyui / subfolder)
                        elif subfolder and base:
                            dest = str(base / "ComfyUI" / subfolder)
                        elif base:
                            dest = str(base / "models")
                        else:
                            dest = str(full.parent)

                        # Flag if already in the right place
                        already_placed = (
                            (comfyui and str(full).lower().startswith(comfyui_s)) or
                            (base and str(full).lower().startswith(install_b))
                        )

                        found.append({
                            "path":          str(full),
                            "filename":      fname,
                            "size_mb":       round(size_mb, 1),
                            "type":          category,
                            "subfolder":     subfolder or "models",
                            "suggested_dest": dest,
                            "already_placed": already_placed,
                            "drive":         str(drive),
                        })
                    except: pass
        except PermissionError:
            pass

    # 2. Also scan Ollama model cache
    for ollama_dir in get_ollama_cache_dirs():
        log(f"Scanning Ollama cache: {ollama_dir}...", "info")
        try:
            for root, dirs, files in os.walk(str(ollama_dir)):
                for fname in files:
                    full = Path(root) / fname
                    try:
                        size_mb = full.stat().st_size / (1024*1024)
                        if size_mb < 1:
                            continue
                        # Ollama models are blobs - try to get model name from path
                        model_label = "Ollama Model Cache"
                        if base:
                            dest = str(base / "OllamaModels")
                        else:
                            dest = str(full.parent)
                        found.append({
                            "path":           str(full),
                            "filename":       fname,
                            "size_mb":        round(size_mb, 1),
                            "type":           model_label,
                            "subfolder":      "OllamaModels",
                            "suggested_dest": dest,
                            "already_placed": False,
                            "drive":          str(full.drive) + chr(92),
                        })
                    except: pass
        except PermissionError:
            pass

    _scan_results = found
    placed   = sum(1 for f in found if f["already_placed"])
    log(f"Scan complete -- found {len(found)} model file(s) ({placed} already in correct location)", "ok")
    return found

def move_model_file(src, dest_dir, action="move", subfolder=""):
    """Move/copy a model file, recreating the correct subfolder structure."""
    src_path = Path(src)
    # Build full destination with subfolder
    dest = Path(dest_dir)
    if subfolder:
        dest = dest / subfolder
    dest.mkdir(parents=True, exist_ok=True)
    dest_file = dest / src_path.name
    try:
        if action == "move":
            shutil.move(str(src_path), str(dest_file))
            log(f"Moved {src_path.name} -> {dest_file}", "ok")
        elif action == "copy":
            shutil.copy2(str(src_path), str(dest_file))
            log(f"Copied {src_path.name} -> {dest_file}", "ok")
        elif action == "delete":
            src_path.unlink()
            log(f"Deleted {src_path}", "ok")
            return True, str(src_path)
        return True, str(dest_file)
    except Exception as e:
        log(f"File operation failed: {e}", "error")
        return False, str(e)

# move_model_file defined in scanner section above

# ??? Ollama bridge ????????????????????????????????????????????????????????????
def clean_ai_response(text):
    """Strip <think> tags, HTML artifacts, and stray XML from model output."""
    if not text: return text
    import re as _re
    # Remove <think>...</think> reasoning blocks (Qwen3, DeepSeek, etc.)
    text = _re.sub(r'<think>.*?</think>', '', text, flags=_re.DOTALL|_re.IGNORECASE)
    # Remove stray HTML/XML tags
    text = _re.sub(r'</?[a-zA-Z][a-zA-Z0-9]*[^>]*>', '', text)
    # Clean up excess blank lines left behind
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def sanitize_model_name(name):
    """Strip Ollama-incompatible characters from model name."""
    import re as _re
    # Remove [custom], [local] etc suffixes added by UI
    name = _re.sub(r"\s*\[.*?\]", "", name).strip()
    # Ollama model names: alphanumeric, hyphens, colons, dots only
    return name

def model_vram_report(model=None):
    """Ask Ollama how the loaded model is ACTUALLY split between GPU and CPU.

    This is the single biggest determinant of speed on this box and it was
    completely invisible in the UI. Measured on the RTX 5070 Ti (16.3 GB):

        qwen3-coder:30b  20.6 GB loaded, 29% on CPU, 1418 tok/s prefill
        qwen3:14b        11.9 GB loaded,  0% on CPU, 2468 tok/s prefill

    The 30B's weights alone are ~18 GB, so no num_ctx setting can make it fit --
    dropping the context from 32768 to 8192 only moved it from 29% to 24%.
    A partially offloaded model is not "warming up"; it is permanently slower.
    """
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/ps", timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "msg": str(e)}
    want = str(model or "").split(":")[0].lower()
    for m in (data.get("models") or []):
        name = str(m.get("name") or m.get("model") or "")
        if want and name.split(":")[0].lower() != want:
            continue
        size = int(m.get("size") or 0)
        vram = int(m.get("size_vram") or 0)
        if not size:
            continue
        cpu_pct = max(0, round(100 * (size - vram) / size))
        return {"ok": True, "loaded": True, "model": name,
                "size_gb": round(size / 1e9, 1),
                "vram_gb": round(vram / 1e9, 1),
                "cpu_pct": cpu_pct,
                "ctx": m.get("context_length") or m.get("context") or 0}
    return {"ok": True, "loaded": False}


# ─── Usage: real tokens, real energy, and a clearly-labelled comparison ──────
USAGE_FILE = _CONFIG_DIR / "nd_usage.json"
_usage = None
_usage_dirty = False

# Defaults only. Edit these in neuraldock_config.json under "usage_rates" --
# they are not measurements and they go stale.
#
#   *_in / *_out   USD per MILLION tokens, from the vendor's published pricing.
#   kwh_per_ktok   estimated datacentre energy per 1,000 tokens generated.
#   l_per_kwh      estimated litres of water per kWh, on-site cooling plus the
#                  power station's own consumption.
#
# The last two are the soft ones. Public estimates for both span more than an
# order of magnitude depending on site, season and what you count, so treat any
# water number here as a sketch, not a measurement.
USAGE_RATES_DEFAULT = {
    "local_kwh_price": 0.17,       # USD per kWh, your electricity bill
    "cloud_kwh_per_ktok": 0.0003,  # est. kWh per 1k output tokens, cloud
    "cloud_l_per_kwh": 1.8,        # est. litres water per kWh, cloud
    "local_l_per_kwh": 0.0,        # an air-cooled desktop consumes no water
    "models": {
        "Claude Opus 5":  {"in": 15.00, "out": 75.00},
        "Claude Sonnet 5": {"in": 3.00, "out": 15.00},
        "GPT (flagship)": {"in": 10.00, "out": 30.00},
    },
    "_note": ("Prices are USD per million tokens and are NOT verified by ND. "
              "Check the vendor's current pricing page and correct them here. "
              "Energy and water figures are rough public estimates with very "
              "wide error bars."),
}


def usage_rates():
    r = dict(USAGE_RATES_DEFAULT)
    r.update(_config.get("usage_rates") or {})
    if not r.get("models"):
        r["models"] = USAGE_RATES_DEFAULT["models"]
    return r


def _usage_blank():
    return {"started": time.time(), "requests": 0, "tokens_in": 0, "tokens_out": 0,
            "gen_secs": 0.0, "gpu_wh": 0.0, "by_model": {}, "by_day": {}}


def load_usage():
    global _usage
    if _usage is not None:
        return _usage
    try:
        _usage = json.loads(USAGE_FILE.read_text(encoding="utf-8-sig"))
        for k, v in _usage_blank().items():
            _usage.setdefault(k, v)
    except Exception:
        _usage = _usage_blank()
    return _usage


def save_usage(force=False):
    global _usage_dirty
    if not (_usage_dirty or force):
        return
    try:
        USAGE_FILE.write_text(json.dumps(load_usage(), indent=1), encoding="utf-8")
        _usage_dirty = False
    except Exception as e:
        log(f"Could not save usage counters: {e}", "warn")


def note_usage(model, tokens_in, tokens_out, secs=0.0):
    """Record ONE completed Ollama request. Exact counts, straight from Ollama."""
    global _usage_dirty
    tin, tout = int(tokens_in or 0), int(tokens_out or 0)
    if not (tin or tout):
        return
    day = datetime.now().strftime("%Y-%m-%d")
    with _lock:
        u = load_usage()
        u["requests"] += 1
        u["tokens_in"] += tin
        u["tokens_out"] += tout
        u["gen_secs"] = round(u.get("gen_secs", 0.0) + max(0.0, secs), 1)
        m = u["by_model"].setdefault(str(model or "?"),
                                     {"requests": 0, "tokens_in": 0, "tokens_out": 0})
        m["requests"] += 1; m["tokens_in"] += tin; m["tokens_out"] += tout
        d = u["by_day"].setdefault(day, {"tokens_in": 0, "tokens_out": 0, "requests": 0})
        d["requests"] += 1; d["tokens_in"] += tin; d["tokens_out"] += tout
        _usage_dirty = True


def note_gpu_energy(watts, seconds, idle_watts):
    """Integrate GPU power into Wh, counting only draw ABOVE idle.

    Idle is subtracted on purpose: the card burns ~40 W with nothing running,
    and charging that to inference would make a long idle session look like
    heavy compute.
    """
    global _usage_dirty
    try:
        above = max(0.0, float(watts) - float(idle_watts))
    except Exception:
        return
    if above <= 0:
        return
    with _lock:
        u = load_usage()
        u["gpu_wh"] = round(u.get("gpu_wh", 0.0) + above * (seconds / 3600.0), 4)
        _usage_dirty = True


def usage_report():
    """Totals, plus what the same token count would have cost in the cloud.

    Every cloud number here is arithmetic on the configured rates. Nothing in
    this section is measured, and the caller is expected to say so.
    """
    u = dict(load_usage())
    r = usage_rates()
    tin, tout = u["tokens_in"], u["tokens_out"]
    kwh = u.get("gpu_wh", 0.0) / 1000.0
    local = {
        "tokens_in": tin, "tokens_out": tout, "tokens_total": tin + tout,
        "requests": u["requests"], "gen_secs": u.get("gen_secs", 0.0),
        "gpu_kwh": round(kwh, 4),
        "electricity_usd": round(kwh * float(r["local_kwh_price"]), 4),
        "water_litres": round(kwh * float(r.get("local_l_per_kwh", 0.0)), 3),
        "tok_per_sec": (round((tin + tout) / u["gen_secs"], 1)
                        if u.get("gen_secs") else 0),
    }
    cloud_kwh = (tout / 1000.0) * float(r["cloud_kwh_per_ktok"])
    cloud = []
    for name, p in (r.get("models") or {}).items():
        cloud.append({
            "model": name,
            "usd": round(tin / 1e6 * float(p.get("in", 0))
                         + tout / 1e6 * float(p.get("out", 0)), 2),
            "kwh": round(cloud_kwh, 4),
            "water_litres": round(cloud_kwh * float(r["cloud_l_per_kwh"]), 2),
        })
    cloud.sort(key=lambda x: -x["usd"])
    return {"local": local, "cloud": cloud, "rates": r,
            "since": u.get("started"),
            "by_model": u.get("by_model", {}), "by_day": u.get("by_day", {}),
            "disclaimer": ("Local tokens and GPU energy are MEASURED: token counts "
                           "come from Ollama's own prompt_eval_count/eval_count, "
                           "and energy is nvidia-smi power draw above idle, "
                           "integrated over time. Every cloud figure is arithmetic "
                           "on the editable rates above and is NOT a measurement. "
                           "The water numbers in particular are order-of-magnitude "
                           "sketches with very wide error bars.")}


# --- Live CPU / GPU meters --------------------------------------------------
# The banner already warns when a model spills to the CPU, but it says nothing
# about what the machine is doing right now -- so a run that is merely slow and
# a run that is wedged look identical from the UI. These are the two numbers
# that tell them apart. Sampled here rather than in the browser so the ~150 ms
# nvidia-smi call happens once per period no matter how many tabs are open.
SYSMON_PERIOD  = 2.0         # seconds between samples
SYSMON_HISTORY = 90          # samples kept = 3 minutes of sparkline
_sysmon = {"cpu": [], "gpu": [], "now": {}, "ts": 0.0}


def _nvidia_sample():
    """GPU utilisation %, temperature C and total VRAM, via nvidia-smi.

    Deliberately NOT memory.used or memory.free: measured on this box's driver
    both return 2**44-ish garbage (17592181866867 MiB) while memory.total is
    correct. The VRAM figure the UI shows comes from Ollama's own size_vram,
    which is also the number that actually decides speed here.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,temperature.gpu,memory.total,name,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return None
    lines = (out.stdout or "").strip().splitlines()
    if not lines:
        return None
    parts = [p.strip() for p in lines[0].split(",")]
    if len(parts) < 4:
        return None
    try:
        return {"pct": int(float(parts[0])), "temp": int(float(parts[1])),
                "total_gb": round(float(parts[2]) / 1024, 1), "name": parts[3],
                "watts": float(parts[4]) if len(parts) > 4 else 0.0}
    except Exception:
        return None


def _ollama_vram_gb():
    """How much VRAM Ollama's resident models are holding, in GB."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/ps", timeout=4) as r:
            models = json.loads(r.read()).get("models") or []
    except Exception:
        return None
    if not models:
        return 0.0
    return round(sum(int(m.get("size_vram") or 0) for m in models) / 1e9, 1)


def _cpu_temp_c():
    """CPU temperature in C from LibreHardwareMonitor's WMI namespace, or None.

    Windows has no CPU temperature API of its own: the ACPI thermal zone is
    "not supported" on this board (MSI X870, checked 2026-09-27) and psutil has
    no sensors on Windows. LibreHardwareMonitor (free, open source), while it is
    running, publishes every sensor under root\\LibreHardwareMonitor. Prefer the
    package / Tctl-Tdie reading on AMD, else the hottest CPU sensor."""
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        for ns in ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor"):
            try:
                svc = win32com.client.GetObject("winmgmts:" + ns)
                rows = svc.ExecQuery("SELECT Name, Value, Identifier FROM Sensor "
                                     "WHERE SensorType='Temperature'")
                cpu = [(str(r.Name), float(r.Value)) for r in rows
                       if "cpu" in str(r.Identifier).lower() and r.Value]
            except Exception:
                continue
            if not cpu:
                continue
            for want in ("tctl", "package", "tdie"):
                for name, v in cpu:
                    if want in name.lower():
                        return round(v, 1)
            return round(max(v for _, v in cpu), 1)
    except Exception:
        pass
    return None


def _sysmon_loop():
    try:
        import psutil
    except Exception:
        psutil = None
        log("psutil not available - the CPU meter will stay blank", "warn")
    if psutil:
        psutil.cpu_percent(None)      # prime: the first call always reads 0.0
    tick, vram_gb, cpu_temp = 0, None, None
    _idle_w = [0.0]            # lowest draw seen: the baseline to subtract
    _save_every = 0
    while True:
        try:
            cpu_pct = int(round(psutil.cpu_percent(None))) if psutil else 0
            ghz = 0.0
            if psutil:
                try:
                    f = psutil.cpu_freq()
                    ghz = round((f.current or 0) / 1000.0, 2) if f else 0.0
                except Exception:
                    ghz = 0.0
            g = _nvidia_sample()
            if g and g.get("watts"):
                # Idle baseline, learned from the lowest draw seen. Anything
                # above it is work; the card idles around 40 W doing nothing.
                _idle_w[0] = min(_idle_w[0], g["watts"]) if _idle_w[0] else g["watts"]
                note_gpu_energy(g["watts"], SYSMON_PERIOD, _idle_w[0])
            # /api/ps is cheap but pointless at 2 s resolution -- a model load
            # takes tens of seconds. Every 5th sample is plenty.
            tick += 1
            if tick % 5 == 1:
                vram_gb = _ollama_vram_gb()
                cpu_temp = _cpu_temp_c()
            ram_pct, ram_used, ram_total = 0, None, None
            if psutil:
                try:
                    vm = psutil.virtual_memory()
                    ram_pct = int(round(vm.percent))
                    ram_used = round((vm.total - vm.available) / 2**30, 1)
                    ram_total = round(vm.total / 2**30)
                except Exception:
                    pass
            with _lock:
                _sysmon["cpu"].append(cpu_pct)
                _sysmon["gpu"].append(g["pct"] if g else 0)
                _sysmon.setdefault("ram", []).append(ram_pct)
                del _sysmon["cpu"][:-SYSMON_HISTORY]
                del _sysmon["gpu"][:-SYSMON_HISTORY]
                del _sysmon["ram"][:-SYSMON_HISTORY]
                _sysmon["now"] = {
                    "cpu_pct": cpu_pct, "cpu_ghz": ghz,
                    "gpu_ok": bool(g),
                    "gpu_pct": (g or {}).get("pct", 0),
                    "gpu_temp": (g or {}).get("temp", 0),
                    "gpu_name": (g or {}).get("name", ""),
                    "vram_total_gb": (g or {}).get("total_gb", 0),
                    "vram_used_gb": vram_gb,
                    "cpu_temp": cpu_temp,           # C, None when no sensor source
                    "ram_pct": ram_pct,
                    "ram_used_gb": ram_used,
                    "ram_total_gb": ram_total,
                }
                _sysmon["ts"] = time.time()
            _save_every += 1
            if _save_every % 30 == 0:      # once a minute, not every sample
                save_usage()
        except Exception:
            pass      # a meter must never be able to take the server down
        time.sleep(SYSMON_PERIOD)


def sysmon_snapshot():
    with _lock:
        return {"now": dict(_sysmon["now"]), "ts": _sysmon["ts"],
                "period": SYSMON_PERIOD,
                "cpu": list(_sysmon["cpu"]), "gpu": list(_sysmon["gpu"]),
                "ram": list(_sysmon.get("ram", []))}


# ??? Per-model context profiles ????????????????????????????????????????????
# Not every model wants the same window. Measured on this box (RTX 5070 Ti, 16.3 GB):
#
#     2026-08  qwen3coder-q3xl @ 32768 -> 15.8 GB, 7% CPU,   63 tok/s pre,  16.1 gen
#     2026-08  qwen3coder-q3xl @ 16384 -> 14.6 GB, 0% CPU,   72 tok/s pre,  18.1 gen
#     2026-08  qwen3coder-q3xl @  8192 -> 14.1 GB, 0% CPU, 3060 tok/s pre, 120.5 gen
#     2026-09-04  UD-Q3_K_XL  @ 32768 -> 14.7 GB, 7% CPU, 3350 tok/s pre, 107.7 gen
#
# The August rows read as proof that a 32768 window costs a 48x prefill
# slowdown, and the small profiles below were built on that. The September row
# is the same weights at the same window with the same 7% spill, running 53x
# faster than the row directly above it -- the fast numbers at the slow row's
# settings. Both cannot describe num_ctx.
#
# The variable the August rows do not record is WHEN they were taken. This box
# generates at ~103 tok/s in the hours after a reboot and ~27 tok/s later, with
# free VRAM and no orphaned runners, and only a reboot has ever restored it. A
# sweep that walks 32768 -> 16384 -> 8192 over an afternoon measures that decay
# and hands it to whichever setting was tried last.
#
# So the profiles below are 32768 until a fixed-window soak says otherwise. A
# window the GPU cannot hold is still worth less than one it can -- that part
# holds -- but 7% on the CPU is not what 63 tok/s looks like.
#
# num_ctx is not a standalone dial either: the memory block, the transcript and
# every tool result all live inside it. Shrinking the window without shrinking
# those just means the transcript gets silently truncated instead. So a profile
# carries all four numbers together.
DEFAULT_PROFILE = {
    "num_ctx":             32768,
    "memory_budget_chars": 12000,   # matches obsidian_budget_chars default
    "read_page_chars":     10000,   # one page of a file
    "tool_result_chars":   14000,   # must stay above read_page_chars + framing
    "keep_verbatim":       2,
}

# Keys are matched against the model name case-insensitively, longest key first,
# so "qwen3coder-q3xl:latest" and the raw hf.co/... tag both land on the profile.
BUILTIN_PROFILES = {
    # Both keys name the same 13 GB Q3 weights: the local tag and the hf.co
    # one. At 32768 they measure 14.7 GB resident and 93% on the GPU, so the
    # window the rest of ND is built around fits. These now match
    # DEFAULT_PROFILE and are kept only so the substring match still lands on
    # a named profile rather than falling through silently.
    "qwen3coder-q3xl": {
        "num_ctx":             32768,
        "memory_budget_chars": 12000,
        "read_page_chars":     10000,
        "tool_result_chars":   14000,  # stays above read_page_chars + framing
        "keep_verbatim":       2,
    },
    "qwen3-coder-30b-a3b-instruct-gguf": {   # the hf.co tag for the same weights
        "num_ctx":             32768,
        "memory_budget_chars": 12000,
        "read_page_chars":     10000,
        "tool_result_chars":   14000,
        "keep_verbatim":       2,
    },
}

# The read-page budget is consumed deep inside fs_read_file, which has no model
# argument and no clean way to get one. Chat jobs each run on their own thread,
# so park the resolved profile in thread-local storage for the duration of the
# job rather than threading a parameter through every tool signature. Anything
# running outside a chat job falls back to the flat defaults.
_job_ctx = threading.local()

def set_active_profile(prof):
    _job_ctx.profile = prof

def active_profile():
    return getattr(_job_ctx, "profile", None) or DEFAULT_PROFILE


_overcommit_warned = set()


def _profile_fixed_chars(prof):
    """Chars a turn spends before any transcript exists: the system prompt, the
    memory block, and the tool results kept verbatim."""
    sysp = (len(SYSTEM_PROMPT_TOOLS) + len(SYSTEM_PROMPT_UI_RULES)
            + len(SYSTEM_PROMPT_CODE_RULES))
    return (sysp + prof["memory_budget_chars"]
            + prof["keep_verbatim"] * prof["tool_result_chars"])


def _warn_if_overcommitted(prof, name):
    """Say so when a profile's FIXED cost eats most of its own window.

    Such a profile overflows on the first real tool result, and Ollama answers
    overflow by silently dropping the OLDEST messages -- the system prompt, which
    is where the capability declaration and the task live. The visible symptom is
    a model that suddenly claims it cannot edit or access files. Measured: the
    'devstral' profile at num_ctx 8192 committed 80% of its window to fixed cost
    before a single transcript line. Warn once per profile rather than leaving
    this to be rediscovered from the outside.
    """
    key = prof.get("_profile") or name or "<default>"
    if key in _overcommit_warned:
        return
    window = max(prof["num_ctx"] * 4, 1)
    share = _profile_fixed_chars(prof) / window
    if share >= 0.55:
        _overcommit_warned.add(key)
        log(f"Context profile '{key}' is overcommitted: {share:.0%} of its "
            f"{prof['num_ctx']}-token window is fixed cost (system prompt + memory "
            f"+ kept tool results) before any transcript. Expect front-truncation, "
            f"which drops the system prompt. Lower memory_budget_chars / "
            f"tool_result_chars / keep_verbatim, or raise num_ctx.", "warn")


def model_profile(model=None):
    """Resolve the context profile for one model.

    Order: config["model_profiles"] (user override) -> BUILTIN_PROFILES ->
    flat legacy config keys -> DEFAULT_PROFILE. Partial profiles are fine;
    anything a profile omits falls through to the layer beneath it.
    """
    prof = dict(DEFAULT_PROFILE)
    # legacy flat keys stay authoritative for models with no profile of their own
    prof["num_ctx"]             = int(_config.get("num_ctx", prof["num_ctx"]))
    prof["memory_budget_chars"] = int(_config.get("obsidian_budget_chars", prof["memory_budget_chars"]))
    prof["read_page_chars"]     = int(_config.get("agent_read_page_chars", prof["read_page_chars"]))
    prof["tool_result_chars"]   = int(_config.get("agent_tool_result_chars", prof["tool_result_chars"]))
    prof["keep_verbatim"]       = int(_config.get("agent_keep_verbatim", prof["keep_verbatim"]))

    name = str(model or "").lower()
    if not name:
        return prof
    table = dict(BUILTIN_PROFILES)
    user = _config.get("model_profiles") or {}
    if isinstance(user, dict):
        for k, v in user.items():
            if isinstance(v, dict):
                table[str(k).lower()] = v
    # longest match wins, so a specific tag beats a family prefix
    for key in sorted(table, key=len, reverse=True):
        if key in name:
            for k, v in table[key].items():
                if k in prof:
                    try:
                        prof[k] = int(v)
                    except (TypeError, ValueError):
                        pass
            prof["_profile"] = key
            break
    _warn_if_overcommitted(prof, name)
    return prof


def reply_cap(model=None):
    """Most tokens one reply may generate. Half the model's window, 4096..16384.

    Was a flat 4096 until 2026-10-18, when every write_file of a whole new
    ~300-line file died as Ollama 500 "invalid tool call arguments: unexpected
    end of JSON input" -- the call was cut off mid-string at token 4096. Half
    the window leaves the other half for the prompt; an 8K model keeps 4096.
    Override with agent_num_predict in the config."""
    fixed = _config.get("agent_num_predict")
    if fixed:
        return int(fixed)
    return max(4096, min(16384, int(model_profile(model)["num_ctx"]) // 2))


def _ollama_options(model=None):
    opts = {
        "num_predict": reply_cap(model),              # response length cap
        "num_ctx": model_profile(model)["num_ctx"]    # per-model; Ollama's 4K default cripples file work
    }
    if model and on_cpu(model):
        opts["num_gpu"] = 0                           # GPU busy: no layers on the card
    return opts


# ── CPU fallback ─────────────────────────────────────────────────────────────
# A model that cannot START on the GPU is retried on the CPU instead of failing
# the turn. Measured on Philibert 2026-10-19: with another program holding 14.5
# of 16 GB, qwen3:14b died at load ("llama-server process has terminated: exit
# status 0xc0000409 ... CUDA error: shared object initialization failed") rather
# than spilling to system RAM, and the turn came back empty. After GPU_RETRY_S
# the GPU is tried again, since whatever held it may have let go.
GPU_RETRY_S = 600
_cpu_only = {}            # model -> when it last failed to start on the GPU
_GPU_FAIL = re.compile(r"CUDA error|cudaMalloc|CUBLAS|out of memory|unable to allocate|"
                       r"llama-server process has terminated|0xc0000409|"
                       r"failed to (load|initiali[sz]e)[^\n]*(CUDA|GPU|backend|device)", re.I)


def on_cpu(model):
    t = _cpu_only.get(sanitize_model_name(model or ""))
    return bool(t and time.time() - t < GPU_RETRY_S)


def cpu_fallback_models():
    return [m for m in list(_cpu_only) if on_cpu(m)]


def gpu_start_failed(model, detail):
    """True when Ollama could not start `model` on the GPU and it should be retried
    on the CPU. False if the error is something else, or it already failed on the
    CPU (so a real out-of-RAM cannot loop)."""
    if not (PORTABLE or _config.get("cpu_fallback")):
        return False          # ND proper: a benchmark must fail loudly, not slow down
    if not detail or not _GPU_FAIL.search(str(detail)):
        return False
    m = sanitize_model_name(model or "")
    if not m or on_cpu(m):
        return False
    _cpu_only[m] = time.time()
    log(f"{m} could not start on the GPU (another program is using it, or it is out of "
        f"memory) - running it on the CPU instead. Slower, but it answers; the GPU is "
        f"tried again in {GPU_RETRY_S // 60} min.", "warn")
    return True


def _http_detail(e):
    try:
        return e.read().decode("utf-8", "replace")[:600] if hasattr(e, "read") else str(e)
    except Exception:
        return str(e)

_think_caps = {}          # model -> does it declare the "thinking" capability


def _model_thinks(model):
    """Does this model have a thinking mode Ollama can switch off?

    Asked once per model and cached. /api/show reports it cleanly:
    qwen3.8:27b -> [completion, vision, tools, thinking]
    qwen3-coder:30b -> [completion, tools]

    A model without the capability must never be sent the `think` field at all,
    which is why this asks rather than always sending it.
    """
    m = sanitize_model_name(model or "")
    if not m:
        return False
    if m in _think_caps:
        return _think_caps[m]
    ok = False
    try:
        req = urllib.request.Request(
            OLLAMA_URL + "/api/show", data=json.dumps({"model": m}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            caps = (json.loads(r.read().decode("utf-8", "replace")) or {}).get("capabilities") or []
        ok = "thinking" in caps
    except Exception:
        ok = False        # unknown means do not send the field
    _think_caps[m] = ok
    return ok


def _think_kw(model):
    """The `think` field for a chat payload, or nothing at all.

    Default OFF, and that default is measured rather than assumed. qwen3.8:27b
    with thinking on spent 5 minutes in round one producing NOTHING, then 136
    characters in the 5 minutes after -- against 35-80s for the incumbent to
    finish the whole T1 task. On "reply with exactly: OK" it burned 39 tokens
    and 142 characters of reasoning to answer in two.
    
    An agent loop pays for that on every round of every turn, and the round
    budget is what it runs out of. Set agent_thinking true in the config to
    hand it back.
    """
    if not _model_thinks(model):
        return {}
    return {"think": bool(_config.get("agent_thinking", False))}


def _keep_alive():
    # Ollama unloads after 5 min by default; a 27B reload costs minutes mid-task
    return _config.get("ollama_keep_alive", "60m")

def ollama_chat(model, messages, timeout=1740, status_cb=None, clean=True, text_cb=None):  # 29 min — huge offloaded models can spend many minutes in prompt eval
    """Chat with Ollama (plain text). Streams; reports token progress via status_cb(n_tokens).
    clean=False returns RAW text (needed when the caller must parse tool-call XML,
    which clean_ai_response would strip)."""
    model = sanitize_model_name(model)
    payload = json.dumps({
        "model":    model,
        "messages": messages,
        "stream":   True,
        "keep_alive": _keep_alive(),
        "options":  _ollama_options(model),
        **_think_kw(model)
    }).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        chunks = []
        pend = []          # text generated but not yet handed to text_cb
        def _flush(force=False):
            # Batch before every callback: text_cb takes a lock, and one
            # acquisition per token buys nothing the eye can see. 24 chars is
            # well under a single poll interval of text.
            if not text_cb or not pend:
                return
            if force or sum(len(x) for x in pend) >= STREAM_FLUSH_CHARS:
                text_cb("".join(pend))
                del pend[:]
        with urllib.request.urlopen(req, timeout=timeout) as r:
            _cc = getattr(_job_ctx, "cancel_check", None)
            for line in r:
                if _cc is not None and _cc():
                    log("Cancelled mid-reply - stopped the stream", "warn")
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    token = obj.get("message", {}).get("content", "")
                    if token:
                        chunks.append(token)
                        pend.append(token)
                        _flush()
                        if status_cb and len(chunks) % 25 == 0:
                            status_cb(len(chunks))
                    if obj.get("done"):
                        note_usage(model, obj.get("prompt_eval_count"),
                                   obj.get("eval_count"),
                                   (obj.get("total_duration") or 0) / 1e9)
                        break
                except json.JSONDecodeError:
                    continue
        _flush(force=True)
        raw = "".join(chunks)
        if not raw:
            return "[No response]"
        return clean_ai_response(raw) if clean else raw
    except Exception as e:
        detail = _http_detail(e)
        if gpu_start_failed(model, detail):
            return ollama_chat(model, messages, timeout, status_cb, clean, text_cb)
        return f"[Ollama error: {e}] {detail if detail != str(e) else ''}".rstrip()

def ollama_chat_native(model, messages, tools, timeout=1740, status_cb=None, text_cb=None):
    """Chat with Ollama using NATIVE structured tool calling.
    Returns {"content": str, "tool_calls": [{"name":..., "arguments": {...}}], "native_ok": bool}.
    native_ok=False means the model/template rejected or ignored the tools param — caller should
    fall back to the legacy TOOL: text protocol."""
    model = sanitize_model_name(model)
    payload = json.dumps({
        "model":    model,
        "messages": messages,
        "tools":    tools,
        "stream":   True,
        "keep_alive": _keep_alive(),
        "options":  _ollama_options(model),
        **_think_kw(model)
    }).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        chunks, calls = [], []
        pend = []          # text generated but not yet handed to text_cb
        def _flush(force=False):
            if not text_cb or not pend:
                return
            if force or sum(len(x) for x in pend) >= STREAM_FLUSH_CHARS:
                text_cb("".join(pend))
                del pend[:]
        prompt_tokens = eval_tokens = 0
        with urllib.request.urlopen(req, timeout=timeout) as r:
            _cc = getattr(_job_ctx, "cancel_check", None)
            for line in r:
                if _cc is not None and _cc():
                    log("Cancelled mid-reply - stopped the stream", "warn")
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Ollama can report a failure INSIDE a 200 stream, as a line
                # carrying only {"error": ...}. It has no "message" and no
                # "done", so the reader below skips straight past it and the
                # call returns empty -- the failure never reaches a log.
                # Measured on OBSIDIAN-9B-Coder:
                #   llama-server returned invalid tool call arguments for
                #   "write_file": unexpected end of JSON input
                # i.e. the model's tool-call JSON was truncated mid-argument,
                # which is what happens when it tries to pass a whole 19 KB
                # page as a string. Say so, and let the caller retry as text.
                if obj.get("error"):
                    log(f"Ollama reported an error mid-stream for {model}: "
                        f"{str(obj['error'])[:200]}", "warn")
                    return {"content": "", "tool_calls": [], "native_ok": True,
                            "prompt_tokens": prompt_tokens, "eval_tokens": eval_tokens,
                            "stream_error": str(obj["error"])[:300]}
                msg = obj.get("message", {})
                token = msg.get("content", "")
                if token:
                    chunks.append(token)
                    pend.append(token)
                    _flush()
                    if status_cb and len(chunks) % 25 == 0:
                        status_cb(len(chunks))
                for tc in msg.get("tool_calls", []) or []:
                    fn = tc.get("function", {})
                    calls.append({"name": fn.get("name",""), "arguments": fn.get("arguments",{}) or {}})
                if obj.get("done"):
                    # Ollama reports the REAL prompt size here. Without it,
                    # context overflow is completely invisible: the server
                    # silently drops the oldest messages -- including the
                    # user's original instruction -- and the model starts
                    # improvising because the task is no longer in its window.
                    prompt_tokens = int(obj.get("prompt_eval_count") or 0)
                    eval_tokens = int(obj.get("eval_count") or 0)
                    note_usage(model, prompt_tokens, eval_tokens,
                               (obj.get("total_duration") or 0) / 1e9)
                    break
        _flush(force=True)
        return {"content": "".join(chunks), "tool_calls": calls, "native_ok": True,
                "prompt_tokens": prompt_tokens, "eval_tokens": eval_tokens}
    except urllib.error.HTTPError as e:
        # 4xx is a statement about the MODEL: its template cannot do tools, and
        # nothing will change that, so latch native off for the conversation.
        #
        # 5xx is a statement about the SERVER for this one request -- a grammar
        # that broke mid-argument, a request too large. Latching on that costs
        # the model native tool calling for every remaining round of the turn,
        # over one bad call. Measured 2026-09-01 on the LeninShop benchmark: a
        # single 500 on round 9 dropped the run to the text protocol, it parsed
        # nothing, and the turn ended with "[No response]" after 75s of real work.
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        if gpu_start_failed(model, detail):
            return ollama_chat_native(model, messages, tools, timeout, status_cb, text_cb)
        if 500 <= int(e.code) < 600:
            log(f"Ollama {e.code} on a native tool call to {model} — retrying this "
                f"round as text, keeping native for the rest. {detail}", "warn")
            return {"content": "", "tool_calls": [], "native_ok": True,
                    "server_error": f"HTTP {e.code}", "retry_as_text": True}
        log(f"Native tool calling unsupported by {model} ({e.code}) — falling back "
            f"to the text protocol for this conversation. {detail}", "warn")
        return {"content": "", "tool_calls": [], "native_ok": False}
    except Exception as e:
        return {"content": f"[Ollama error: {e}]", "tool_calls": [], "native_ok": True}

def get_ollama_models_dir():
    """Get the configured Ollama models directory."""
    return _config.get("ollama_models_dir", "")

def set_ollama_models_dir(path):
    """Set OLLAMA_MODELS and restart Ollama to use new path."""
    _config["ollama_models_dir"] = path
    save_config()
    # Create the directory
    Path(path).mkdir(parents=True, exist_ok=True)
    log(f"Ollama models dir set to: {path}", "ok")
    # Try to restart Ollama with new env
    run("taskkill /F /IM ollama.exe >nul 2>&1")
    import time as _t
    _t.sleep(1)
    env_str = f"set OLLAMA_MODELS={path} && ollama serve"
    subprocess.Popen(env_str, shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE if os.name=="nt" else 0)
    _t.sleep(3)
    if _check_ollama():
        log("Ollama restarted with new models dir [OK]", "ok")
        return True
    log("Ollama restart may take a moment...", "warn")
    return True

def ollama_pull(model_name):
    with _lock:
        _pull_status[model_name] = {"status": "starting", "pct": 0, "done": False, "ok": False}
    payload = json.dumps({"name": model_name, "stream": True}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/pull", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            for line in r:
                try: obj = json.loads(line.decode())
                except: continue
                status    = obj.get("status","")
                total     = obj.get("total", 0)
                completed = obj.get("completed", 0)
                pct       = int(completed/total*100) if total else 0
                if status == "success":
                    log(f"Pull {model_name}: success [OK]", "ok")
                    with _lock:
                        _pull_status[model_name] = {"status":"success","pct":100,"done":True,"ok":True}
                    threading.Thread(target=refresh_status_cache, daemon=True).start()
                    return
                elif status in ("writing manifest","verifying sha256 digest"):
                    with _lock: _pull_status[model_name]["status"] = status
                elif total and pct > 0:
                    log(f"Pull {model_name}: {pct}%", "info")
                    with _lock: _pull_status[model_name].update({"status":status,"pct":pct})
        models = _get_models()
        if any(model_name.split(":")[0] in m for m in models):
            with _lock:
                _pull_status[model_name] = {"status":"success","pct":100,"done":True,"ok":True}
            threading.Thread(target=refresh_status_cache, daemon=True).start()
    except Exception as e:
        log(f"Pull error: {e}", "error")
        with _lock:
            _pull_status[model_name] = {"status":f"error: {e}","pct":0,"done":True,"ok":False}

# ??? TTS / STT ????????????????????????????????????????????????????????????????
def tts_speak(text):
    if not VENV_PY.exists(): return
    script = f'import pyttsx3\ne=pyttsx3.init()\ne.say({repr(text)})\ne.runAndWait()\n'
    tmp = tempfile.mktemp(suffix=".py")
    with open(tmp,"w") as f: f.write(script)
    run(f'"{VENV_PY}" "{tmp}"')
    try: os.unlink(tmp)
    except: pass

# ─── Voice: Piper TTS (local, customizable) ───────────────────────────────────
VOICES_DIR = Path("G:/EsteefAi/Voices")
_piper_cache = {}     # voice name -> loaded PiperVoice (loading takes ~1s, so cache)

def list_voices():
    """Available TTS voices: Piper .onnx models + Windows SAPI fallbacks."""
    out = []
    try:
        if VOICES_DIR.exists():
            for f in sorted(VOICES_DIR.glob("*.onnx")):
                n = f.stem
                # en_US-amy-medium -> "Amy (en US, medium)"
                parts = n.split("-")
                who = parts[1].replace("_", " ").title() if len(parts) > 1 else n
                loc = parts[0].replace("_", "-") if parts else ""
                qual = parts[2] if len(parts) > 2 else ""
                out.append({"id": n, "engine": "piper",
                            "label": f"{who} ({loc}{', ' + qual if qual else ''})",
                            "size_mb": round(f.stat().st_size / 1024 / 1024, 1)})
    except Exception as e:
        log(f"voice scan failed: {e}", "warn")
    try:
        ok, sout, _ = run('powershell -NoProfile -Command "Add-Type -AssemblyName System.Speech; '
                          '(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() '
                          '| ForEach-Object { $_.VoiceInfo.Name }"')
        if ok:
            for line in (sout or "").splitlines():
                line = line.strip()
                if line:
                    out.append({"id": f"sapi:{line}", "engine": "sapi",
                                "label": f"{line} (Windows)", "size_mb": 0})
    except Exception:
        pass
    return out

def get_voice_settings():
    return {
        "voice":  _config.get("agent_voice", ""),
        "speed":  float(_config.get("agent_voice_speed", 1.0)),
        "volume": float(_config.get("agent_voice_volume", 1.0)),
    }

def tts_synthesize(text, voice=None, speed=None, volume=None):
    """Render speech to WAV bytes so the BROWSER can play it (allows barge-in,
    volume control, and works from another device). Returns (bytes, mime)."""
    import io, wave
    s = get_voice_settings()
    voice  = voice  or s["voice"]
    speed  = float(speed  if speed  is not None else s["speed"])
    volume = float(volume if volume is not None else s["volume"])
    text = (text or "").strip()
    if not text:
        return b"", "audio/wav"

    # Windows SAPI path
    if voice.startswith("sapi:"):
        name = voice.split(":", 1)[1]
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        rate = max(-10, min(10, int(round((speed - 1.0) * 10))))
        ps = ('Add-Type -AssemblyName System.Speech; '
              '$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; '
              f'$s.SelectVoice("{name}"); $s.Rate={rate}; '
              f'$s.SetOutputToWaveFile("{tmp}"); $s.Speak([Console]::In.ReadToEnd()); $s.Dispose()')
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           input=text, text=True, capture_output=True, timeout=120)
            data = tmp.read_bytes() if tmp.exists() else b""
            return data, "audio/wav"
        finally:
            try: tmp.unlink()
            except Exception: pass

    # Piper path (default)
    if not voice:
        avail = [v for v in list_voices() if v["engine"] == "piper"]
        if not avail:
            raise Exception("No Piper voices installed in " + str(VOICES_DIR))
        voice = avail[0]["id"]
    model = VOICES_DIR / f"{voice}.onnx"
    if not model.exists():
        raise Exception(f"Voice not found: {voice}")

    from piper import PiperVoice, SynthesisConfig
    pv = _piper_cache.get(voice)
    if pv is None:
        pv = PiperVoice.load(str(model))
        _piper_cache[voice] = pv
        log(f"Loaded voice: {voice}", "ok")
    # piper length_scale: higher = slower, so invert the speed multiplier
    cfg = SynthesisConfig(length_scale=(1.0 / max(0.3, min(speed, 3.0))),
                          volume=max(0.1, min(volume, 2.0)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        pv.synthesize_wav(text, w, syn_config=cfg)
    return buf.getvalue(), "audio/wav"

# ─── Speech to text ───────────────────────────────────────────────────────────
# The old path shelled out to openai-whisper "base" with fp16=False, i.e. the
# second-smallest model running on the CPU. That is where the bad transcripts
# came from. faster-whisper large-v3 on the GPU is both far more accurate and
# several times quicker, and it stays resident between utterances.
_fw_model = None
_fw_key   = None

# Words Whisper reliably gets wrong in this app's vocabulary. Seeding the decoder
# with them is the single cheapest accuracy win for domain speech.
STT_VOCAB = ("NeuralDock, Esteef, ComfyUI, Ollama, PowerShell, LoRA, checkpoint, "
             "diffuser, safetensors, GGUF, Qwen, Flux, SDXL, AnimateDiff, CogVideoX, "
             "Piper, Whisper, VRAM, CUDA, repo, prompt, agent mode, admin mode, "
             "screenshot, workflow, venv, Python, JSON, API, GPU, RTX.")

def _whisper_settings():
    return {
        "model":    _config.get("whisper_model", "large-v3"),
        "device":   _config.get("whisper_device", "auto"),
        "language": _config.get("whisper_language", "en"),
        "beam":     int(_config.get("whisper_beam", 5)),
        "vocab":    bool(_config.get("whisper_vocab_hint", True)),
    }

_fw_models = {}          # (name, device) -> model, so wake + request models coexist

def _get_whisper(name_override=None):
    """Load (and cache) a faster-whisper model. Falls back CUDA -> CPU."""
    global _fw_model, _fw_key
    s = _whisper_settings()
    if name_override:
        s = dict(s); s["model"] = name_override
    dev = s["device"]
    if dev == "auto":
        # faster-whisper is CTranslate2, which has CUDA and CPU backends only --
        # there is no ROCm or XPU build. So on AMD/Intel this must resolve to
        # "cpu" even when torch reports a working GPU, or the load throws.
        # nd_gpu.whisper_backend() names the accelerated alternative for those
        # vendors (whisper.cpp over Vulkan); wiring it is a separate job.
        try:
            import nd_gpu
            ct2_ok = nd_gpu.vendor() == nd_gpu.NVIDIA
        except Exception:
            ct2_ok = True
        try:
            import torch
            dev = "cuda" if (ct2_ok and torch.cuda.is_available()) else "cpu"
        except Exception:
            dev = "cpu"
    key = (s["model"], dev)
    if key in _fw_models:
        return _fw_models[key], dev
    from faster_whisper import WhisperModel
    compute = "float16" if dev == "cuda" else "int8"
    t0 = time.time()
    try:
        m = WhisperModel(s["model"], device=dev, compute_type=compute)
    except Exception as e:
        if dev == "cuda":
            log(f"Whisper CUDA load failed ({e}); falling back to CPU", "warn")
            dev, compute = "cpu", "int8"
            m = WhisperModel(s["model"], device=dev, compute_type=compute)
        else:
            raise
    _fw_models[(s["model"], dev)] = m
    log(f"Whisper '{s['model']}' loaded on {dev}/{compute} in {round(time.time()-t0,1)}s", "ok")
    return m, dev

def transcribe_audio(audio_path, model_override=None, quick=False):
    """Speech -> text. Handles webm/ogg straight from the browser MediaRecorder.

    quick=True is the always-listening path: it fires every few seconds just to
    check for the wake word, so it uses a small model and a beam of 1. Running
    large-v3 on that cadence would sit on the GPU permanently and starve the LLM.
    """
    audio_path = Path(audio_path)
    wav_path = audio_path.with_suffix(".stt.wav")
    made_wav = False
    # 16 kHz mono PCM is what Whisper wants; giving it anything else costs accuracy.
    ok, _, _ = run(f'ffmpeg -y -i "{audio_path}" -ar 16000 -ac 1 -c:a pcm_s16le '
                   f'-af "highpass=f=60,lowpass=f=7500,afftdn=nf=-22,dynaudnorm=f=200:g=5" '
                   f'"{wav_path}" 2>nul')
    if ok and wav_path.exists() and wav_path.stat().st_size > 200:
        made_wav = True
        src = wav_path
    else:
        log("ffmpeg convert failed - handing the raw audio to Whisper", "warn")
        src = audio_path
    try:
        s = _whisper_settings()
        use = model_override or (_config.get("whisper_wake_model", "base.en") if quick else None)
        model, dev = _get_whisper(use)
        t0 = time.time()
        segments, info = model.transcribe(
            str(src),
            language=(s["language"] or None),
            beam_size=(1 if quick else s["beam"]),
            temperature=[0.0, 0.2, 0.4],       # retry ladder if a segment looks broken
            vad_filter=True,                   # drop silence so it stops inventing words
            vad_parameters={"min_silence_duration_ms": 400, "speech_pad_ms": 200},
            condition_on_previous_text=False,  # stops one bad guess poisoning the rest
            initial_prompt=(STT_VOCAB if s["vocab"] else None),
            no_speech_threshold=0.5,
        )
        parts, lowconf = [], []
        for seg in segments:
            txt = (seg.text or "").strip()
            if not txt:
                continue
            parts.append(txt)
            if getattr(seg, "avg_logprob", 0) < -1.0:
                lowconf.append(txt)
        text = " ".join(parts).strip()
        dt = round(time.time() - t0, 2)
        if not quick:        # wake-word scans fire constantly; do not spam the log
            log(f"Whisper[{use or s['model']}/{dev}] {dt}s -> {text[:80]!r}"
                + (f"  ({len(lowconf)} low-confidence segs)" if lowconf else ""), "ok")
        return text or "[No speech detected - try speaking a little longer]"
    except Exception as e:
        log(f"Whisper failed: {e}", "error")
        return f"[Transcription error: {e}]"
    finally:
        if made_wav:
            try: wav_path.unlink()
            except Exception: pass

def _transcribe_audio_legacy(audio_path):
    """Old shell-out path, kept only as a reference."""
    if not VENV_PY.exists():
        return "[Whisper: venv not found - run Auto-Setup first]"

    audio_path = Path(audio_path)
    wav_path   = audio_path.with_suffix(".wav")

    # Try to convert to WAV using ffmpeg (handles webm/ogg from browser)
    converted = False
    if audio_path.suffix.lower() != ".wav" or True:  # always try convert
        ok, _, _ = run(f'ffmpeg -y -i "{audio_path}" -ar 16000 -ac 1 -c:a pcm_s16le "{wav_path}" 2>nul')
        if ok and wav_path.exists() and wav_path.stat().st_size > 100:
            converted = True
            log(f"Audio converted to WAV ({wav_path.stat().st_size} bytes)", "info")
        else:
            # ffmpeg failed or not installed - try using audio as-is
            wav_path = audio_path
            log("ffmpeg not found or failed - trying audio as-is", "warn")

    script = f'''
import whisper, sys
try:
    model = whisper.load_model("base")
    result = model.transcribe({repr(str(wav_path))}, fp16=False)
    text = result.get("text", "").strip()
    print(text if text else "[empty - no speech detected]")
except Exception as e:
    print(f"[Whisper error: {{e}}]", file=sys.stderr)
    sys.exit(1)
'''
    tmp = tempfile.mktemp(suffix=".py")
    with open(tmp, "w") as f:
        f.write(script)

    ok, out, err = run(f'"{VENV_PY}" "{tmp}"', timeout=120)
    try: os.unlink(tmp)
    except: pass
    try:
        if converted and wav_path != audio_path: os.unlink(wav_path)
    except: pass

    if ok and out and out.strip():
        return out.strip()
    elif err and err.strip():
        return f"[Transcription error: {err.strip()}]"
    else:
        return "[No speech detected - please speak clearly and try again]"

def analyze_image(model, image_path, prompt="Describe this image in detail."):
    with open(image_path,"rb") as f: b64 = base64.b64encode(f.read()).decode()
    # options is not optional here. Ollama's server is started by the desktop
    # app with OLLAMA_CONTEXT_LENGTH=131072, so a request that names no window
    # gets a 128k one -- and this call runs during design_review, on the same
    # card that is already holding the coder model.
    payload = json.dumps({"model":model,"messages":[{"role":"user","content":prompt,"images":[b64]}],
                          "stream":False,"options":_ollama_options(model),
                          **_think_kw(model)}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=payload,
                                 headers={"Content-Type":"application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())["message"]["content"]
    except Exception as e:
        return f"[Vision error: {e}]"

# ??? Heretic ??????????????????????????????????????????????????????????????????
def run_heretic_model(model_id):
    if not VENV_PY.exists():
        log("Venv not found", "error"); return
    bat = HERETIC_DIR / "_run_heretic.bat"
    bat.write_text(
        f'@echo off\r\ntitle ESTEEF.AI // Heretic -- {model_id}\r\n'
        f'call "{VENV_DIR}\\Scripts\\activate.bat"\r\n'
        f'heretic {model_id}\r\npause\r\n'
    )
    subprocess.Popen(['cmd','/C',f'start "Heretic" cmd /K "{bat}"'], shell=False, cwd=str(HERETIC_DIR))

# ??? Threaded HTTP server ?????????????????????????????????????????????????????


# â”€â”€â”€ Web / Search Tools â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def web_fetch(url, max_chars=8000):
    """Fetch a URL and return cleaned text content."""
    try:
        import urllib.request as _ur
        headers = {"User-Agent": "Mozilla/5.0 NeuralDock/3.1"}
        req = _ur.Request(url, headers=headers)
        with _ur.urlopen(req, timeout=15) as r:
            raw = r.read()
            encoding = r.headers.get_content_charset("utf-8")
            html = raw.decode(encoding, errors="replace")
        # Basic HTML stripping
        import re
        html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL|re.IGNORECASE)
        html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL|re.IGNORECASE)
        html = re.sub(r"<[^>]+>", " ", html)
        html = re.sub(r"&nbsp;", " ", html)
        html = re.sub(r"&amp;", "&", html)
        html = re.sub(r"&lt;", "<", html)
        html = re.sub(r"&gt;", ">", html)
        html = re.sub(r"&quot;", '"', html)
        text = re.sub(r"\s+", " ", html).strip()
        return text[:max_chars]
    except Exception as e:
        return f"[Web fetch error: {e}]"

def web_search(query, max_results=5):
    """Search DuckDuckGo and return result snippets (no API key needed)."""
    try:
        import urllib.parse as _up
        import urllib.request as _ur
        import re
        q = _up.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={q}"
        headers = {"User-Agent": "Mozilla/5.0 NeuralDock/3.1"}
        req = _ur.Request(url, headers=headers)
        with _ur.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
        # Extract result snippets
        results = []
        for m in re.finditer(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL):
            text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if text: results.append(text)
        for m in re.finditer(r'class="result__url"[^>]*>(.*?)</span>', html, re.DOTALL):
            if len(results) < max_results:
                url_text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if url_text and not any(url_text in r for r in results):
                    results.append(f"[URL: {url_text}]")
        return " | ".join(results[:max_results]) if results else "[No results found]"
    except Exception as e:
        return f"[Search error: {e}]"


# â”€â”€â”€ File System Tools â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
READ_PAGE_LINES = 1200  # default lines per read_file call (400 forced too many rounds)

# A LINE budget alone is not a size budget. retro-vault.html is 3595 lines but
# 194 KB -- averaging 55 chars a line, with some lines far longer. One 1200-line
# page of it is ~66 KB, roughly 16k tokens, dropped into a 32k context window in
# a single tool result. Two of those and the model has no room left to think,
# which is exactly how one request took 1914 seconds and produced no answer.
# So cap the page by CHARACTERS as well, and say plainly where to resume.
READ_PAGE_CHARS = 10000

# Structural outlines make a large file navigable without reading all of it.
_OUTLINE_PATTERNS = [
    (re.compile(r"^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)", re.I), "fn"),
    (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)"), "class"),
    (re.compile(r"^\s*def\s+([A-Za-z_][\w]*)"), "def"),
    (re.compile(r"^\s*<(script|style)\b", re.I), "block"),
    (re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()"), "fn"),
    (re.compile(r'^\s*<(?:div|section|main|header|nav)[^>]*id="([^"]+)"', re.I), "id"),
    (re.compile(r"^\s*#{1,3}\s+(.+)$"), "hdr"),
]


# How much of the window may be spent holding files verbatim through soft
# compaction, as a share of num_ctx.
#
# This started as a COUNT of six files and that was a mistake, measured: with
# tool_result_chars at 14,000 (~3,500 tokens), six files is ~21,000 tokens --
# 64% of a 32K window before the ~3,650-token preamble. Every round then carried
# a near-full prompt, prefill cost exploded, and a T3 run went from ~400s to
# over the 1,800s cap.
#
# A share, not a count, because the right number depends on the window and on
# tool_result_chars, and both vary per model. At 25% of 32K that is roughly two
# files -- enough for the pair a change usually spans, cheap enough to carry.
COMPACT_KEEP_SHARE = 0.25

# A tool result this small is never compacted except under genuine overflow. A
# directory listing or a script's exit line costs ~500 tokens and is usually
# still being acted on; compacting it only makes the model ask for it again.
SMALL_RESULT_KEEP = 2000

# Fit the prompt BEFORE sending, at this share of num_ctx. _check_context only
# reacts to the PREVIOUS round's reported prompt_tokens, so one 14k-char tool
# result can cross the window in a single round -- and Ollama does not error, it
# silently drops the OLDEST messages, i.e. the system prompt carrying the
# capability declaration and the task.
PRESEND_MAX_SHARE = 0.85

# Characters per token, LEARNED per model from Ollama's own prompt_eval_count.
# The fit used to assume 4. Measured 2026-09-24: a prompt the fit believed was
# under its 27,800-token limit was really ~31,400 tokens (96% of the window) --
# code, JSON and paths tokenize far denser than prose -- and the 30B, partly on
# the CPU, spent 29 minutes reading it and timed out having written nothing.
# Until a model has been measured, assume the conservative 3.0. The measured
# ratio includes the tool schemas Ollama adds outside `convo`, which makes it
# lower than the true text ratio -- a deliberate overestimate of the prompt.
CHARS_PER_TOKEN_DEFAULT = 3.0
CHARS_PER_TOKEN_RANGE = (2.0, 4.0)
_chars_per_token = {}          # model -> learned ratio


def chars_per_token(model):
    return _chars_per_token.get(str(model or ""), CHARS_PER_TOKEN_DEFAULT)


def learn_chars_per_token(model, chars_sent, prompt_tokens):
    """Fold one real measurement into the model's ratio. Returns the new ratio."""
    try:
        if not chars_sent or not prompt_tokens or prompt_tokens < 500:
            return chars_per_token(model)   # too small to say anything
        lo, hi = CHARS_PER_TOKEN_RANGE
        r = max(lo, min(hi, chars_sent / float(prompt_tokens)))
        old = _chars_per_token.get(str(model))
        # Lean toward the LOWER of old and new: overestimating a prompt costs a
        # little context; underestimating it cost a whole turn.
        _chars_per_token[str(model)] = r if old is None else min(r, 0.5 * (old + r))
        return _chars_per_token[str(model)]
    except Exception:
        return chars_per_token(model)

# Restated at the TAIL every round. The capability list sits at index 0, the
# first thing discarded on overflow, which is exactly why the model starts
# claiming it cannot edit files. ~40 tokens, and front-truncation cannot reach it.
CAPABILITY_REMINDER = (
    "[reminder] You have REAL access to this PC right now. read_file, list_dir, "
    "search_files, edit_file and write_file all work. To change a file: read it, "
    "then call edit_file. Never say you cannot access, open or edit files, and "
    "never ask the user to paste a file you can read yourself. Work ONLY on the "
    "latest user request: an earlier request in this chat is finished or dropped "
    "unless the latest message says to continue it.")


def _tool_result_file(content):
    """The file a paged read was ABOUT, or None.

    Recognises only the read_file header, which is the shape that matters:

        [FILE] [G:/proj/app/schemas.py - lines 2-4 of 431, 12KB total]

    Short results -- an edit confirmation, a run_script exit -- are never
    compacted anyway, so they need no identity.
    """
    if not content:
        return None
    first = content.split(chr(10), 1)[0]
    i = first.find(" lines ")
    if i < 0:
        return None
    head = first[:i].rstrip()
    for dash in (chr(8212), "-"):
        if head.endswith(dash):
            head = head[:-1].rstrip()
            break
    else:
        return None
    if head.startswith("[FILE] "):
        head = head[7:]
    head = head.lstrip("[").strip()
    return head or None


def clip_tool_result(text, limit):
    """Trim an oversized tool result, keeping BOTH ends.

    A plain text[:limit] silently amputates the tail, and the tail is where
    fs_read_file puts "resume with offset=N" and where errors usually appear.
    Losing that is how a model ends up re-reading page 1 forever.
    """
    text = str(text)
    if len(text) <= limit:
        return text
    head = int(limit * 0.75)
    tail = limit - head - 80
    return (text[:head]
            + f"\n\n[... {len(text) - head - tail} characters trimmed from the middle ...]\n\n"
            + text[-tail:])


def file_outline(lines, max_items=45):
    """A compact map of a file: what is defined, and on which line."""
    out = []
    for i, line in enumerate(lines, 1):
        if len(line) > 400:            # minified blob, nothing useful to name
            continue
        for rx, kind in _OUTLINE_PATTERNS:
            m = rx.match(line)
            if m:
                name = (m.group(1) if m.groups() else "").strip()[:60]
                if name:
                    out.append(f"  {i:>5}  {kind:<5} {name}")
                break
        if len(out) >= max_items:
            out.append("  ...  (outline truncated)")
            break
    return "\n".join(out)

# A tool that cannot do a thing must SAY so. A tool that tries anyway and reports
# the wreckage teaches the model something false, and the model believes it.
#
# Measured, and it cost three benchmark runs: run_script was handed run.ps1 and
# ran `python run.ps1`, so the model was told a PowerShell file had a Python
# SyntaxError. It concluded the file was broken and looped trying to fix it.
#
# A sweep of every file tool found the same shape five more times:
#
#   read_file  on a PNG        "lines 1-277 of 281"   -- success, returning noise
#   read_file  on a directory  "Permission denied"    -- a false cause
#   edit_file  on a PNG        "old_text appears 40 times"
#   edit_file  on a directory  "Permission denied"
#   list_dir   on a file       "WinError 267"         -- true, not actionable
#   write_file to a directory  allowed, then silently redirected
#
# None of these were broken code. All of them lied about WHY.
TEXT_SNIFF_BYTES = 8192


def _looks_binary(path):
    """Is this bytes rather than text? Cheap and deliberately conservative.

    A NUL byte in the first 8KB is the classic test and has almost no false
    positives on source files. Undecodable UTF-8 is the backstop.
    """
    try:
        chunk = Path(path).open("rb").read(TEXT_SNIFF_BYTES)
    except OSError:
        return False
    if not chunk:
        return False
    if bytes([0]) in chunk:
        return True
    try:
        chunk.decode("utf-8")
        return False
    except UnicodeDecodeError:
        # A truncated multi-byte char at the boundary is not binary.
        return len(chunk) == TEXT_SNIFF_BYTES and bytes([0]) in chunk[:64]


def path_problem(path, want="file"):
    """Why this path cannot be used, phrased so the model can act. '' if fine.

    `want` is "file" or "dir". Every message names the tool that WOULD work,
    because "this is wrong" without "do that instead" is how a model ends up
    retrying the same call.
    """
    raw = str(path or "").strip().strip('"').strip("'")
    if not raw:
        return "no path was given."
    p = Path(raw)
    try:
        exists = p.exists()
    except OSError:
        return f"{raw} is not a usable path."
    if not exists:
        return (f"{raw} does not exist. Check the path with list_dir on its "
                f"parent folder before trying again.")
    if want == "file" and p.is_dir():
        return (f"{raw} is a FOLDER, not a file. Use list_dir to see what is "
                f"inside it, then name one of those files.")
    if want == "dir" and p.is_file():
        return (f"{raw} is a FILE, not a folder. Use read_file to read it, or "
                f"list_dir on the folder that contains it.")
    if want == "file" and p.is_file() and _looks_binary(p):
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        return (f"{raw} is a BINARY file ({size:,} bytes), not text. It cannot "
                f"be read or edited as text and nothing is wrong with it. Do "
                f"not try again on this file.")
    return ""


def fs_read_file(path, offset=0, limit=None):
    """Read a file, PAGED. offset/limit are 1-based line numbers.
    Always reports the total line count so the model knows to page instead of
    assuming the file ended (the old version silently truncated large files)."""
    try:
        path = path.strip().strip('"').strip("'")
        # Say WHY before doing anything: a directory used to come back as
        # "Permission denied" and a PNG came back as 277 lines of noise
        # reported as success.
        why = path_problem(path, want="file")
        if why:
            return "[Cannot read] " + why
        p = Path(path)
        if not p.exists():
            if not os.path.exists(path):
                return f"[File not found: {path}]"
        stat = p.stat()
        if stat.st_size > 60 * 1024 * 1024:
            return f"[File too large: {stat.st_size//1024//1024}MB — use search_files to locate what you need]"
        try:    offset = max(0, int(offset or 0))
        except: offset = 0
        try:    limit = int(limit) if limit else READ_PAGE_LINES
        except: limit = READ_PAGE_LINES
        limit = max(1, min(limit, 4000))

        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(lines)
        start = offset if offset else 0
        if start >= total and total:
            return f"[offset {start} is past end of file — {path} has {total} lines]"
        chunk = lines[start:start+limit]

        # Enforce the character budget too, trimming at a line boundary so the
        # resume offset stays exact.
        page_chars = int(active_profile().get("read_page_chars", READ_PAGE_CHARS))
        used, kept = 0, []
        for ln in chunk:
            if used + len(ln) + 1 > page_chars and kept:
                break
            kept.append(ln)
            used += len(ln) + 1
        capped = len(kept) < len(chunk)
        chunk = kept
        end = start + len(chunk)
        body = "\n".join(chunk)

        header = f"[{path} — lines {start+1}-{end} of {total}, {stat.st_size//1024}KB total]\n"

        # On the first page of a big file, lead with a map. It is far cheaper
        # than paging through everything, and for "recreate this app" it is
        # usually all the model actually needs.
        if start == 0 and (stat.st_size > page_chars * 2 or total > limit):
            outline = file_outline(lines)
            if outline:
                header += ("\nSTRUCTURE MAP (jump straight to a line with "
                           "read_file offset=N, or use search_files):\n"
                           + outline + "\n\n--- content from line 1 ---\n")

        footer = ""
        if end < total:
            why = ("page character limit reached" if capped else "line limit reached")
            footer = (f"\n\n[...{total-end} MORE LINES NOT SHOWN ({why}). This file did NOT end here.\n"
                      f"Resume with read_file offset={end}. But do NOT page through a large file just to "
                      f"understand it — that fills the context window and leaves no room to think. "
                      f"Use the structure map above and search_files to read only the parts you need.]")
        return header + body + footer
    except Exception as e:
        return f"[Read error: {e}]"

def fs_list_dir(path):
    """List directory contents. Handles Windows paths with special chars."""
    why = path_problem(path, want="dir")
    if why:
        return "[Cannot list] " + why
    try:
        path = path.strip().strip('"').strip("'").strip()
        # Normalize backslashes
        import os as _os
        path = path.replace("/", _os.sep)
        p = Path(path)
        if not p.exists():
            # Try with os.path as fallback
            if not _os.path.exists(path):
                return f"[Directory not found: {path}]"
            p = Path(_os.path.abspath(path))
        items = []
        for item in sorted(p.iterdir()):
            kind = "DIR" if item.is_dir() else "FILE"
            try:
                size = "" if item.is_dir() else f" ({item.stat().st_size//1024}KB)"
            except:
                size = ""
            items.append(f"[{kind}] {item.name}{size}")
        total = len(items)
        result = "\n".join(items[:200])  # cap at 200 items
        if total > 200:
            result += f"\n... ({total-200} more items)"
        return result if result else "[Empty directory]"
    except Exception as e:
        return f"[List error: {e}]"

def fs_write_file(path, content, mode="w"):
    """Write content to a file, creating directories as needed."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, mode, encoding="utf-8") as f:
            f.write(content)
        return str(p)
    except Exception as e:
        return f"[Write error: {e}]"

# â”€â”€â”€ Backups + verification + surgical edit + search â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€─
_LAST_BACKUP = {}   # {"backup": path, "original": path}

def _backup_file(path):
    """Snapshot a file before modifying it. Returns backup path or None."""
    global _LAST_BACKUP
    try:
        p = Path(path)
        if not p.exists():
            return None
        bdir = p.parent / ".nd_backups"
        bdir.mkdir(exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        bpath = bdir / f"{p.name}.{ts}.bak"
        bpath.write_bytes(p.read_bytes())
        _LAST_BACKUP = {"backup": str(bpath), "original": str(p)}
        return str(bpath)
    except Exception as e:
        log(f"Backup failed for {path}: {e}", "warn")
        return None

def _project_root(p: Path):
    """Walk up out of the package the file sits in. Returns the folder that
    would be on sys.path, or None if the file is not inside a package."""
    d = p.parent
    root = None
    for _ in range(12):
        if (d / "__init__.py").is_file():
            root = d.parent
            d = d.parent
        else:
            break
    return root


def _unresolved_local_imports(p: Path):
    """Imports of the PROJECT'S OWN modules that point at nothing.

    Third-party names are deliberately ignored -- knowing whether `fastapi` is
    importable would mean importing it, and importing a file the model just
    wrote is not something to do on a whim. Local modules can be checked purely
    on disk, and that is where this class of mistake actually lives: the model
    invents a neighbour module that was never written.
    """
    import ast
    root = _project_root(p)
    if not root:
        return []
    try:
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []          # a syntax error is py_compile's job to report

    def exists(dotted: str) -> bool:
        parts = [x for x in dotted.split(".") if x]
        if not parts:
            return True
        base = root.joinpath(*parts)
        return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file() \
            or base.is_dir()

    def _defined_in(target):
        """Every top-level name a local module provides, or None if unknowable.

        None means do not judge: a star re-export, an unreadable file, anything
        where a confident answer would be a guess.
        """
        f = target.with_suffix(".py")
        if not f.is_file():
            f = target / "__init__.py"
            if not f.is_file():
                return None
        try:
            t = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return None
        names = set()
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                names.add(n.id)
            elif isinstance(n, ast.alias):
                names.add((n.asname or n.name).split(".")[0])
            elif isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names):
                return None
        if target.is_dir():
            for child in target.iterdir():
                if child.suffix == ".py":
                    names.add(child.stem)
                elif (child / "__init__.py").is_file():
                    names.add(child.name)
        return names

    def _missing_at(target, aliases):
        """Names imported from an already-resolved local module path.

        Conservative on purpose. If the target re-exports (`from x import *`) or
        cannot be read, nothing is reported -- a false IMPORT ERROR on a name
        that is really there would be far worse than missing one that is not.
        """
        f = target.with_suffix(".py")
        if not f.is_file():
            f = target / "__init__.py"
            if not f.is_file():
                return []
        try:
            t = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return []
        defined = set()
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(n.name)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                defined.add(n.id)
            elif isinstance(n, ast.alias):
                defined.add((n.asname or n.name).split(".")[0])
            elif isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names):
                return []          # star import: anything could be re-exported
        # `from .. import models` imports a SUBMODULE, which is not a name in the
        # package's __init__.py. Treat a file or folder of that name as defined,
        # or every package-relative import of a sibling gets a false IMPORT ERROR.
        pkg_dir = target if target.is_dir() else None

        def _is_submodule(nm):
            return bool(pkg_dir) and ((pkg_dir / f"{nm}.py").is_file()
                                      or (pkg_dir / nm / "__init__.py").is_file())

        return [a.name for a in aliases
                if a.name != "*" and a.name not in defined and not _is_submodule(a.name)]

    def _missing_names(root_dir, dotted, aliases):
        return _missing_at(root_dir.joinpath(*[x for x in dotted.split(".") if x]),
                           aliases)

    def _bad_attrs(tree_, here):
        """`schemas.WishlistItem` where schemas.py has no WishlistItem.

        Only follows bindings this file creates from LOCAL modules, and only
        module-level names, so there is nothing to guess about what the name
        refers to.
        """
        bound = {}
        for n in ast.walk(tree_):
            if isinstance(n, ast.ImportFrom) and n.level:
                pkg = here.parent
                for _ in range(n.level - 1):
                    pkg = pkg.parent
                base = pkg.joinpath(*(n.module or "").split(".")) if n.module else pkg
                for a in n.names:
                    if a.name == "*":
                        continue
                    cand = base / a.name
                    if cand.with_suffix(".py").is_file() or (cand / "__init__.py").is_file():
                        bound[a.asname or a.name] = cand
            elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
                # `from app import schemas` -- absolute, and the imported name is
                # a submodule rather than something the package defines.
                if not local(n.module.split(".")[0]):
                    continue
                base = root.joinpath(*n.module.split("."))
                for a in n.names:
                    if a.name == "*":
                        continue
                    cand = base / a.name
                    if cand.with_suffix(".py").is_file() or (cand / "__init__.py").is_file():
                        bound[a.asname or a.name] = cand
            elif isinstance(n, ast.Import):
                for a in n.names:
                    parts = a.name.split(".")
                    if not local(parts[0]):
                        continue
                    cand = root.joinpath(*parts)
                    if cand.with_suffix(".py").is_file() or (cand / "__init__.py").is_file():
                        bound[a.asname or parts[0]] = cand if a.asname else root / parts[0]
        if not bound:
            return []
        out = []
        for n in ast.walk(tree_):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id in bound):
                have = _defined_in(bound[n.value.id])
                if have is not None and n.attr not in have:
                    out.append(f"{n.value.id}.{n.attr}")
        return out

    def local(top: str) -> bool:
        # Only judge names that look like part of THIS project.
        return (root / top).is_dir() or (root / (top + ".py")).is_file()

    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:                      # from ..config import settings
                pkg = p.parent
                for _ in range(node.level - 1):
                    pkg = pkg.parent
                target = pkg.joinpath(*(node.module or "").split(".")) if node.module else pkg
                dots = "." * node.level
                if not (target.with_suffix(".py").is_file()
                        or (target / "__init__.py").is_file() or target.is_dir()):
                    bad.append(f"{dots}{node.module or ''}")
                else:
                    # Same name check as for absolute imports: the module being
                    # there says nothing about the name being in it.
                    for miss in _missing_at(target, node.names):
                        bad.append(f"{dots}{node.module or ''}.{miss}")
                continue
            mod = node.module or ""
            if mod and local(mod.split(".")[0]):
                if not exists(mod):
                    bad.append(mod)
                else:
                    # The module is there, but is the NAME? Measured on the
                    # benchmark: `from app.models import Request` -- app/models.py
                    # exists, so this passed, and the class is called ItemRequest.
                    # Hallucinated symbol names are a common failure and they are
                    # statically checkable against the file being imported from.
                    for miss in _missing_names(root, mod, node.names):
                        bad.append(f"{mod}.{miss}")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if local(a.name.split(".")[0]) and not exists(a.name):
                    bad.append(a.name)
    # Cross-file naming drift: the import is fine, the NAME on the other side
    # is not. This is the failure a multi-file build actually produces.
    try:
        bad.extend(_bad_attrs(tree, p))
    except Exception:
        pass
    seen, out = set(), []
    for b in bad:
        if b not in seen:
            seen.add(b); out.append(b)
    return out


# Names Python provides that no file has to define.
_ALWAYS_DEFINED = frozenset(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__debug__", "__path__", "__all__",
    "__class__", "__module__", "__qualname__", "__annotations__",
}
VERIFY_MAX_UNDEFINED = 4


def _bound_names(tree):
    """Every name this file binds ANYWHERE, by any means.

    Deliberately flat -- module scope, function locals, parameters and
    comprehension variables all land in one set. A real scope analysis would
    catch more, and would also report a local used in another function as
    undefined when the author knows better. This guard refuses writes, so it
    is built for precision: over-approximate what is defined, and only complain
    about a name that is bound nowhere at all.
    """
    out = set()

    def target(node):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for e in node.elts:
                target(e)
        elif isinstance(node, ast.Starred):
            target(node.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                out.add(a.asname or a.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.add(node.name)
            a = node.args
            for arg in list(a.args) + list(a.posonlyargs) + list(a.kwonlyargs):
                out.add(arg.arg)
            if a.vararg:
                out.add(a.vararg.arg)
            if a.kwarg:
                out.add(a.kwarg.arg)
        elif isinstance(node, ast.Lambda):
            a = node.args
            for arg in list(a.args) + list(a.posonlyargs) + list(a.kwonlyargs):
                out.add(arg.arg)
            if a.vararg:
                out.add(a.vararg.arg)
            if a.kwarg:
                out.add(a.kwarg.arg)
        elif isinstance(node, ast.ClassDef):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                target(t)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            target(node.target)
        elif isinstance(node, ast.NamedExpr):
            target(node.target)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            target(node.target)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    target(item.optional_vars)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                out.add(node.name)
        elif isinstance(node, ast.comprehension):
            target(node.target)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            out.update(node.names)
        elif node.__class__.__name__ == "MatchAs" and getattr(node, "name", None):
            out.add(node.name)
        elif node.__class__.__name__ == "MatchStar" and getattr(node, "name", None):
            out.add(node.name)
        elif node.__class__.__name__ == "MatchMapping" and getattr(node, "rest", None):
            out.add(node.rest)
    return out


def _undefined_names(path):
    """Names this file reads but never defines, imports or receives.

    The gap this closes, measured: a step copied a test setup out of
    smoke_test.py into test_public.py, which imports neither os nor tempfile.
    py_compile passed, the import check passed, ND said "Verified OK", and the
    file raised NameError the moment it ran -- taking 424 tests to zero.
    """
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    # A star import can supply anything, so nothing here can be proven missing.
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
            return []
    bound = _bound_names(tree) | _ALWAYS_DEFINED
    seen, out = set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in bound and node.id not in seen:
                seen.add(node.id)
                out.append((node.id, node.lineno))
    return out


def _verify_file(path):
    """Post-edit check. Returns '' if OK (or unchecked type), else the error text."""
    try:
        p = Path(path)
        ext = p.suffix.lower()
        if ext == ".py":
            import py_compile
            try:
                py_compile.compile(str(p), doraise=True)
            except py_compile.PyCompileError as e:
                return f"PYTHON SYNTAX ERROR: {e.msg[:400]}"
            # Parsing is not importing. `from app.dependencies import get_db`
            # compiles perfectly and takes the whole application down.
            missing = _unresolved_local_imports(p)
            if missing:
                return ("IMPORT ERROR: this file imports "
                        + ", ".join(missing[:4])
                        + " — no such module or name exists in this project. You "
                        "either invented it or renamed something. Use what is "
                        "actually there.")
            # Compiling proves the file parses, not that its names exist.
            undef = _undefined_names(p)
            if undef:
                where = ", ".join(f"{n} (line {ln})" for n, ln in undef[:VERIFY_MAX_UNDEFINED])
                return ("UNDEFINED NAME: this file uses " + where
                        + " — nothing in it defines, imports or receives "
                        + ("those names" if len(undef) > 1 else "that name")
                        + ". It will raise NameError as soon as that line runs. "
                        "Add the missing import at the top of the file, or use "
                        "something the file already has.")
            return ""
        if ext == ".json":
            try:
                json.loads(p.read_text(encoding="utf-8", errors="replace"))
                return ""
            except Exception as e:
                return f"JSON ERROR: {e}"
        return ""
    except Exception:
        return ""


_RUFF_OK = None


def _ruff_available():
    """Cache whether ruff is runnable, so a missing linter is not probed each edit."""
    global _RUFF_OK
    if _RUFF_OK is None:
        try:
            r = subprocess.run([sys.executable, "-m", "ruff", "--version"],
                               capture_output=True, timeout=15)
            _RUFF_OK = (r.returncode == 0)
        except Exception:
            _RUFF_OK = False
    return _RUFF_OK


def _py_diagnostics(path, workspace=""):
    """LSP-style post-edit diagnostics for a .py file: fast static analysis fed
    back INLINE so the model sees errors on the same turn, before it runs the
    suite. Informational only -- it never gates or triggers a retry (that stays
    _verify_file's job), so lint noise cannot loop the agent. Empty string when
    clean, disabled, or ruff is unavailable.

    ruff --select E9,F catches the errors that actually crash a run: E9 syntax /
    runtime-parse errors, and F pyflakes (undefined names F821, bad/unused
    imports F401/F811, undefined __all__ F822). Static, so it needs no project
    venv and runs in milliseconds. --isolated ignores project config so a
    repo's own `ignore` list cannot silence a real error mid-edit."""
    if not _config.get("agent_lint_diagnostics", True):
        return ""
    p = Path(path)
    try:
        if p.suffix.lower() != ".py" or not p.is_file():
            return ""
    except OSError:
        return ""
    type_rows = _type_diagnostics(p, workspace)
    if not _ruff_available():
        return _diag_report(p, [], type_rows)
    try:
        # F401 (unused import) is ignored on purpose. An unused import never
        # breaks a program, but "fixing" one can: `from tkinter import
        # filedialog` is what makes `tk.filedialog` exist, ruff cannot see that
        # and calls it unused, and this list is shown to the model after every
        # edit -- measured 2026-09-24, it flagged the exact line that had just
        # fixed a two-day-old crash.
        r = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--isolated",
             "--select", "E9,F", "--ignore", "F401",
             "--output-format", "json", "--no-cache", str(p)],
            cwd=str(workspace or p.parent), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30)
        items = json.loads(r.stdout or "[]")
    except Exception:
        items = []
    rows = []
    if isinstance(items, list):
        for it in items:
            loc = it.get("location") or {}
            rows.append(f"  line {loc.get('row', '?')}: {it.get('code') or ''} "
                        + (it.get("message") or "").strip())
    return _diag_report(p, rows, type_rows)


def _diag_report(p, lint_rows, type_rows):
    rows = list(lint_rows) + list(type_rows)
    if not rows:
        return ""
    extra = f"\n  (+{len(rows) - 12} more)" if len(rows) > 12 else ""
    return ("⚠ diagnostics for " + p.name + " — fix these before finishing; "
            "they crash imports/tests, or crash the moment that line runs:\n"
            + "\n".join(rows[:12]) + extra)


# ─── Type checking after every edit ──────────────────────────────────────────
# ruff is static and cannot see types. Measured 2026-09-24: place_lane.py called
# probe.change(folder / "01_start.png", ...) -- change() takes two PIL IMAGES --
# and nothing ND ran could see it: the bare run, the import check and a
# 47-minute "verify" turn all passed, because the bad line only runs with the
# game open. mypy, given the helper's annotations, names it on the spot:
#     Argument 1 to "change" has incompatible type "Path"; expected "Image"
# Only the high-signal codes are reported: a type checker on unannotated model
# code is otherwise noisy, and noise in this list gets "fixed" by deleting code.
_MYPY_OK = None
MYPY_CODES = {"arg-type", "attr-defined", "call-arg", "call-overload", "name-defined",
              "operator", "index", "return-value", "func-returns-value", "union-attr"}
MYPY_CACHE = _CONFIG_DIR / "temp" / "mypy_cache"   # never in the user's project
_MYPY_LINE_RE = re.compile(r"^(?P<f>.+?):(?P<line>\d+): error: (?P<msg>.*?)\s+\[(?P<code>[\w-]+)\]\s*$")


def _mypy_available():
    global _MYPY_OK
    if _MYPY_OK is None:
        try:
            r = subprocess.run([sys.executable, "-m", "mypy", "--version"],
                               capture_output=True, timeout=30)
            _MYPY_OK = (r.returncode == 0)
        except Exception:
            _MYPY_OK = False
    return _MYPY_OK


def _type_diagnostics(p, workspace=""):
    """High-signal type errors in ONE file, as diagnostic rows. [] if none/unavailable.

    Imported modules are read for their types (so `from probe import change`
    knows change() wants images) but their own errors are not reported: this is
    about the file just edited.
    """
    if not _config.get("agent_type_diagnostics", True) or not _mypy_available():
        return []
    try:
        MYPY_CACHE.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, MYPYPATH=str(p.parent))
        r = subprocess.run(
            [sys.executable, "-m", "mypy", "--check-untyped-defs",
             "--ignore-missing-imports", "--follow-imports=silent",
             "--no-error-summary", "--no-color-output", "--hide-error-context",
             "--cache-dir", str(MYPY_CACHE), p.name],
            cwd=str(p.parent), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60)
    except Exception:
        return []
    rows = []
    for ln in (r.stdout or "").splitlines():
        m = _MYPY_LINE_RE.match(ln.strip())
        if not m or m.group("code") not in MYPY_CODES:
            continue
        if Path(m.group("f")).name.lower() != p.name.lower():
            continue
        rows.append(f"  line {m.group('line')}: type: {m.group('msg')}")
    return rows


def _match_ignoring_line_ends(content, old_text):
    """(start, end) of the ONE place old_text matches if trailing whitespace on
    each line is ignored, else None."""
    old_lines = [ln.rstrip() for ln in (old_text or "").split("\n")]
    while old_lines and not old_lines[-1]:
        old_lines.pop()
    if not old_lines or not any(old_lines):
        return None
    lines = content.split("\n")
    k = len(old_lines)
    hits = [i for i in range(len(lines) - k + 1)
            if lines[i].rstrip() == old_lines[0]
            and [ln.rstrip() for ln in lines[i:i + k]] == old_lines]
    if len(hits) != 1:
        return None
    i = hits[0]
    start = sum(len(ln) + 1 for ln in lines[:i])
    end = start + sum(len(ln) + 1 for ln in lines[i:i + k]) - 1
    return start, end


def edit_near_miss(content, old_text, max_lines=24):
    """Where old_text ALMOST matches, and how it differs - so the next try can
    copy the real text instead of guessing again.

    Measured 2026-09-25: a one-file job spent 21 minutes and changed nothing. Its
    first edit_file rebuilt a block of the file from memory, missed by a little,
    and got back only "old_text not found". Every retry was a near-copy of the
    same wrong text, refused as a repeat, and the model spiralled into workarounds.
    """
    import difflib
    # A trailing newline is not an extra line to match.
    old_lines = (old_text or "").rstrip("\n").split("\n")
    lines = content.split("\n")
    k = max(1, len(old_lines))
    if not old_text.strip() or len(lines) > 6000 or k > 400:
        return " Read the file again and copy old_text EXACTLY (whitespace matters)."
    best, best_i = 0.0, -1
    stripped_old = [ln.strip() for ln in old_lines]
    for i in range(0, max(1, len(lines) - k + 1)):
        win = [ln.strip() for ln in lines[i:i + k]]
        sm = difflib.SequenceMatcher(None, stripped_old, win, autojunk=False)
        if sm.real_quick_ratio() <= best or sm.quick_ratio() <= best:
            continue
        r = sm.ratio()
        if r > best:
            best, best_i = r, i
    if best_i < 0 or best < 0.5:
        return (" No part of the file is close to it - it may be the wrong file, or "
                "text from an older version. Read the file and copy old_text from it.")
    real = lines[best_i:best_i + k]
    diff = list(difflib.unified_diff(old_lines, real, "your old_text", "the file", n=1,
                                     lineterm=""))[2:]
    shown = diff[:max_lines] + (["..."] if len(diff) > max_lines else [])
    return (f"\nThe closest text in the file is lines {best_i + 1}-{best_i + k} "
            f"({int(best * 100)}% similar). How your old_text differs from it "
            f"(- yours, + the file):\n" + "\n".join(shown) + "\n"
            "Copy old_text from those lines EXACTLY, or use a SHORTER old_text - a few "
            "lines that are unique in the file are enough.")


def fs_edit_file(path, old_text, new_text, workspace=""):
    """Surgical find/replace edit. Backs up first, verifies after."""
    try:
        # Same escaping failure as write_file, and here it is worse: old_text
        # full of literal \\n never matches anything, so the edit fails for a
        # reason the model cannot see, and new_text full of literal \\n writes a
        # file Python will not parse. Fix both before going near the disk.
        if looks_escaped(new_text):
            new_text = unescape_content(new_text)
            log("edit_file new_text arrived with literal \\n instead of newlines "
                "— unescaped it", "warn")
        if looks_escaped(old_text):
            old_text = unescape_content(old_text)
            log("edit_file old_text arrived with literal \\n instead of newlines "
                "— unescaped it", "warn")
        path = path.strip().strip('"').strip("'")
        why = path_problem(path, want="file")
        if why:
            return "[Cannot edit] " + why
        p = Path(path)
        if not p.exists():
            return f"[File not found: {path}]"
        content = p.read_text(encoding="utf-8", errors="replace")
        n = content.count(old_text)
        _loose_note = ""
        if n == 0:
            # Trailing spaces are invisible in every view the model gets of a
            # file, and a mismatch there is not a real difference. Indentation
            # IS real (Python), so only line ENDS are relaxed, and only when the
            # relaxed text is unique.
            _span = _match_ignoring_line_ends(content, old_text)
            if _span:
                old_text = content[_span[0]:_span[1]]
                n = 1
                _loose_note = " (old_text matched once trailing spaces were ignored)"
        if n == 0:
            return ("[EDIT FAILED] old_text not found in the file. Nothing was changed."
                    + edit_near_miss(content, old_text))
        if n > 1:
            return f"[EDIT FAILED] old_text appears {n} times — add more surrounding context so it is unique."
        # An edit that changes NOTHING is not progress. Measured 2026-09-27 (Golf It
        # find_names job): qwen3-coder:30b re-applied two changes from the PREVIOUS
        # request that were already in probe.py and set_location.py; both came back
        # "Edited ... Verified OK", were listed as files written, and the job's real
        # task was left half done. Say so plainly, and write nothing.
        _i = content.find(old_text)
        _j = content.find(new_text) if new_text else -1
        if new_text == old_text or (old_text in new_text and _j >= 0
                                    and _j <= _i < _j + len(new_text)):
            return (f"[NO CHANGE] {path} already contains that text - this change is "
                    "ALREADY DONE and nothing was written. Do not repeat it: move on to "
                    "the next part of the CURRENT request, or finish if nothing is left.")
        # A "surgical" edit that deletes most of the file is not surgical.
        # Measured on the LeninShop benchmark: asked to ADD one endpoint, the
        # model replaced app/routers/public.py with a 79-line file, deleting the
        # docstring, every import and nine working endpoints. It parsed, so the
        # syntax check passed and ND said "Verified OK".
        updated = content.replace(old_text, new_text, 1)
        before_lines = content.count("\n") + 1
        after_lines = updated.count("\n") + 1
        if before_lines >= EDIT_MIN_LINES and after_lines < before_lines * (1 - EDIT_MAX_SHRINK):
            lost = before_lines - after_lines
            return (f"[EDIT REFUSED] That edit would delete {lost} of {before_lines} lines "
                    f"({100 * lost // before_lines}% of the file), leaving {after_lines}. "
                    "edit_file is for surgical changes and nothing was written.\n\n"
                    "If you are ADDING something, make old_text a small unique anchor near "
                    "where it belongs and put the anchor back in new_text followed by your "
                    "addition. Do not paste a whole rewritten file into new_text.\n\n"
                    "If you really do mean to replace the file, say so and use write_file.")
        # Same question the write door asks: an edit that keeps the line count
        # can still delete the names other files import.
        try:
            if p.suffix.lower() == ".py":
                pm = placement_mod()
                if pm:
                    broken = pm.broken_dependents(str(p), content, updated, workspace)
                    if broken:
                        return pm.rewrite_refusal(str(p), broken)
        except Exception:
            pass
        bak = _backup_file(path)
        p.write_text(updated, encoding="utf-8")
        vr = _verify_file(path)
        msg = f"Edited {path} (1 replacement){_loose_note}. Backup: {bak or 'n/a'}."
        if vr:
            msg += f"\n⚠ VERIFY FAILED — {vr}\nFix this with another edit_file call."
        else:
            msg += " Verified OK."
        log(f"edit_file: {path}", "ok")
        return msg
    except Exception as e:
        return f"[Edit error: {e}]"

# How much of a file one edit_file call may remove before it is refused. A
# genuine surgical edit never approaches this; a model pasting a rewritten file
# into new_text always does.
EDIT_MAX_SHRINK = 0.6      # refuse an edit that deletes 60%+ of the lines
EDIT_MIN_LINES  = 40       # ...of a file big enough for that to mean anything

SEARCH_TIME_BUDGET  = 25       # seconds
SEARCH_FILE_BUDGET  = 20000    # files opened

def fs_search_files(root, pattern, max_hits=60):
    """Regex search across text files under root. Returns file:line: match lines.

    Hard-bounded on time and file count. Without this, pointing it at a drive
    root walks the whole filesystem and the agent just hangs mid-task.
    """
    import re as _re
    _t0 = time.time()
    try:
        root = root.strip().strip('"').strip("'")
        rp = Path(root)
        if not rp.exists():
            return f"[Not found: {root}]"
        # A drive root or a system folder is never the right place to grep.
        _norm = str(rp).rstrip("\\/").lower()
        if len(_norm) <= 2 or _norm in ("c:", "c:\\", "c:/windows", "c:\\windows",
                                        "c:\\program files", "c:\\program files (x86)",
                                        "c:\\users", "/", ""):
            return (f"[Refused: '{root}' is far too broad to search — it would take minutes and "
                    "return noise. Narrow it to the specific project folder you care about. "
                    "If you are trying to find an installed application, use "
                    "`Get-Command`, `Get-ChildItem` on a specific folder, or check the registry "
                    "via run_shell instead of searching the filesystem.]")
        try:
            rx = _re.compile(pattern, _re.IGNORECASE)
        except _re.error as e:
            return f"[Bad regex: {e}]"
        TEXT_EXT = {".py",".js",".ts",".html",".css",".json",".txt",".md",".bat",".ps1",".yaml",".yml",".xml",".ini",".cfg",".toml",".csv",".sql",".sh"}
        SKIP_DIRS2 = {".git","node_modules","__pycache__","venv",".nd_backups","site-packages"}
        hits = []
        files_scanned = 0
        timed_out = False
        for dirpath, dirs, files in os.walk(str(rp)):
            if time.time() - _t0 > SEARCH_TIME_BUDGET or files_scanned > SEARCH_FILE_BUDGET:
                timed_out = True
                break
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS2]
            for fn in files:
                if Path(fn).suffix.lower() not in TEXT_EXT:
                    continue
                if time.time() - _t0 > SEARCH_TIME_BUDGET:
                    timed_out = True
                    break
                fp = Path(dirpath) / fn
                try:
                    if fp.stat().st_size > 2*1024*1024:
                        continue
                    files_scanned += 1
                    for i, ln in enumerate(fp.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                        if rx.search(ln):
                            hits.append(f"{fp}:{i}: {ln.strip()[:160]}")
                            if len(hits) >= max_hits:
                                raise StopIteration
                except StopIteration:
                    raise
                except Exception:
                    continue
        note = (f"\n[stopped after {SEARCH_TIME_BUDGET}s / {files_scanned} files — results are partial. "
                "Narrow the root folder if you need more.]") if timed_out else ""
        if hits:
            return "\n".join(hits) + note
        if not files_scanned:
            # Nothing was even opened. Saying "in 0 files" here reads as "the
            # folder is empty", which contradicts a list_dir the model just ran
            # and sends it round the loop re-listing to find out which is true.
            # Name the real reason instead.
            present = []
            try:
                for dp, ds, fs in os.walk(str(rp)):
                    ds[:] = [d for d in ds if d not in SKIP_DIRS2]
                    present.extend(fs)
                    if len(present) > 40:
                        break
            except Exception:
                pass
            exts = sorted({(Path(f).suffix.lower() or "(no extension)") for f in present})
            if present:
                return (f"[Searched 0 files under {root} — it holds {len(present)} file(s), but none "
                        f"are text this tool can read (found: {', '.join(exts[:8])}). "
                        "search_files greps the CONTENTS of text files; it does NOT match filenames "
                        "and it cannot read binaries. The folder is NOT empty. "
                        "To see what is there, use list_dir. To read one of these files, use "
                        "read_file. Do not repeat this search.]")
            return (f"[{root} contains no files at all. Do not search it again — look somewhere "
                    "else, or ask the user where the files actually are.]")
        return (f"[No matches for '{pattern}' in {files_scanned} files under {root}."
                + (" Search was cut short on time." if timed_out else "")
                + " Do not retry the same search — either search somewhere else, or this is the wrong tool "
                  "for what you are trying to do.]")
    except StopIteration:
        return "\n".join(hits) + f"\n... (capped at {max_hits} hits)"
    except Exception as e:
        return f"[Search error: {e}]"

# A project keeps its dependencies in its own virtualenv, and that venv is the
# only interpreter that can import them. ND used to run every script with ND's
# OWN venv, so a model working in a FastAPI project could not run a single test
# and had no way to find out why. Look in the workspace first.
VENV_NAMES = (".venv", "venv", "env", ".env")


def workspace_python(workspace):
    """The interpreter that can import THIS project's dependencies.

    Falls back to ND's own venv, then to whatever "python" means on PATH, so a
    workspace with no virtualenv behaves exactly as it did before.
    """
    ws = str(workspace or "").strip().strip('"').strip("'")
    if ws:
        try:
            root = Path(ws)
            for name in VENV_NAMES:
                for rel in (("Scripts", "python.exe"), ("bin", "python")):
                    cand = root / name / rel[0] / rel[1]
                    if cand.exists():
                        return str(cand)
        except Exception:
            pass
    return str(VENV_PY) if VENV_PY.exists() else "python"


# A bare `python` in a run instruction means whatever is first on the user's
# PATH. Measured 2026-09-24: ND said "python place_lane.py --go", the user's
# PATH python was C:\Program Files\Python311 without pydirectinput, and the
# script died on its imports -- while the run gate had tested it, green, under
# the Heretic venv. The command ND hands over must name the interpreter ND
# tested with. Only a command shape is touched: python / python3 / py [-3.x]
# followed by a .py path, -m or -c. Prose ("a Python script") is not.
_BARE_PY_CMD_RE = re.compile(
    r"(?<![\w\\/.\-\"'&])(?:python3?|py(?:\s+-3(?:\.\d+)?)?)"
    r"(?=[ \t]+(?:-m[ \t]+\S|-c[ \t]|\"[^\"\n]+\.pyw?\"|[^\s\"]+\.pyw?\b))")


def pin_run_commands(text, workspace=None):
    """Rewrite bare `python x.py` run instructions to the interpreter ND tested
    the script with, in PowerShell call form: & "C:/.../python.exe" x.py"""
    py = workspace_python(workspace)
    if not text or py == "python":
        return text

    def _swap(m):
        # Inside a string literal it is DATA, not an instruction. Measured
        # 2026-09-25: a reply's code had print("Usage: python set_location.py")
        # and became print("Usage: & "C:\...\python.exe" set_location.py") -- an
        # unbalanced quote that no longer parses. An odd number of quotes before
        # the match on its line means it sits inside one.
        line_start = text.rfind("\n", 0, m.start()) + 1
        before = text[line_start:m.start()]
        if before.count('"') % 2 or before.count("'") % 2:
            return m.group(0)
        return f'& "{py}"'

    return _BARE_PY_CMD_RE.sub(_swap, text)


# Extensions run_script cannot run, and what to say instead. Measured: the model
# called run_script on run.ps1 -- a real file in the project, and a reasonable
# way to try to start the app. ND handed it to PYTHON, which replied
#
#     File "run.ps1", line 9
#         [string]$BindHost = "",
#                 ^
#     SyntaxError: invalid syntax
#
# a Python syntax error inside a PowerShell file. The model concluded the file
# was broken, tried again, and looped until the loop breaker fired. Four of five
# STUCK events in one benchmark sweep were this.
#
# The model was not being stupid. It was given nonsense and believed it.
def _run_capped(cmd, timeout, cwd=None, shell=False):
    """Run a command that MUST come back, even if it starts a server.

    Returns (returncode, stdout, stderr, timed_out).

    subprocess.run(capture_output=True, timeout=...) does not do this on
    Windows. Measured 2026-09-07: the model ran `powershell -File run.ps1`,
    which starts uvicorn and never exits. The 180s timeout fired on schedule and
    then the CLEANUP blocked for 34 minutes, because:

      * timeout kills only the direct child (powershell), and
      * uvicorn, started as a grandchild, inherited the stdout/stderr PIPE
        handles and holds the write end open, so the follow-up communicate()
        waits forever to drain a pipe nobody will ever close.

    Two changes fix it. Capture to temporary FILES rather than pipes, so the
    parent never waits on a pipe a grandchild is holding; and kill the whole
    process TREE on timeout rather than one process. Reading the files back as
    utf-8 also avoids the locale decode that killed the reader threads.
    """
    import tempfile as _tf
    out_f = _tf.NamedTemporaryFile(suffix=".out", delete=False)
    err_f = _tf.NamedTemporaryFile(suffix=".err", delete=False)
    out_f.close()
    err_f.close()
    timed_out = False
    rc = -1
    try:
        with open(out_f.name, "wb") as _o, open(err_f.name, "wb") as _e:
            proc = subprocess.Popen(cmd, stdout=_o, stderr=_e, shell=shell,
                                    cwd=cwd)
            try:
                rc = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                # /T for the whole tree: killing powershell alone leaves the
                # server it started running, holding the port AND the handles.
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   capture_output=True, timeout=30)
                except Exception:
                    pass
                try:
                    rc = proc.wait(timeout=15)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    rc = -1
        def _read(fn):
            try:
                return Path(fn).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
        return rc, _read(out_f.name), _read(err_f.name), timed_out
    finally:
        for fn in (out_f.name, err_f.name):
            try:
                os.unlink(fn)
            except OSError:
                pass


_NOT_PYTHON = {
    ".ps1": "run_shell with: powershell -File <path>",
    ".bat": "run_shell with: cmd /c <path>",
    ".cmd": "run_shell with: cmd /c <path>",
    ".sh":  "run_shell with: bash <path>",
    ".exe": "run_shell with the executable directly",
    ".js":  "run_shell with: node <path>",
    ".mjs": "run_shell with: node <path>",
    ".ts":  "run_shell with: npx tsx <path>",
}


GUI_SMOKE = Path(__file__).parent / "nd_gui_smoke.py"
GUI_SMOKE_TIMEOUT = 45


def is_gui_script(path, workspace=None):
    """A Tk app, or a script that launches one from a module beside it.

    golfit_main.py never mentions tkinter directly -- it imports golfit_gui,
    which does. Checking only the file itself would miss the real entry point.
    """
    try:
        txt = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    if re.search(r"^\s*(?:import|from)\s+tkinter\b", txt, re.M):
        return True
    here = Path(path).parent
    for mod in re.findall(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", txt, re.M):
        name = (mod[0] or mod[1]).split(".")[0]
        f = here / (name + ".py")
        if f.is_file() and f.resolve() != Path(path).resolve():
            try:
                if re.search(r"^\s*(?:import|from)\s+tkinter\b",
                             f.read_text(encoding="utf-8", errors="replace"), re.M):
                    return True
            except Exception:
                continue
    return False


def gui_smoke_test(path, workspace=None, test_input=""):
    """Press every button of a Tk app, headless. Returns (ok, human report)."""
    py = workspace_python(workspace)
    cmd = [py, str(GUI_SMOKE), str(path)] + ([test_input] if test_input else [])
    try:
        rc, out, err, timed_out = _run_capped(cmd, GUI_SMOKE_TIMEOUT,
                                              cwd=str(Path(path).parent))
    except Exception as e:
        return False, f"[GUI TEST] could not run: {e}"
    if timed_out:
        return False, ("[GUI TEST] the app did not finish starting within "
                       f"{GUI_SMOKE_TIMEOUT}s — something at startup blocks.")
    line = next((l for l in (out or "").splitlines() if l.startswith("ND_GUI_REPORT:")), "")
    if not line:
        tail = NL.join(((out or "") + NL + (err or "")).strip().splitlines()[-12:])
        return False, "[GUI TEST] the app crashed before a window appeared:" + NL + tail
    try:
        r = json.loads(line[len("ND_GUI_REPORT:"):])
    except Exception:
        return False, "[GUI TEST] unreadable report"
    # Two different findings, kept apart on purpose. A button that RAISES is
    # broken and is the gate's business. A button whose handler is an empty
    # stub is NOT IMPLEMENTED: it is honest to report, and wrong to "repair" --
    # measured, counting stubs as failures sent two repair passes (905s) off to
    # build Parse/Compare/Write/Create when the user had asked about a crash.
    rows, bad, todo = [], 0, []
    if r.get("startup_error"):
        bad += 1
        rows.append("  STARTUP FAILED:" + NL + "      "
                    + r["startup_error"].replace(NL, NL + "      "))
    for b in r.get("buttons") or []:
        res = b.get("result", "")
        h = (f' -> {b["handler"]}()' if b.get("handler") else "")
        if res == "error":
            bad += 1
            rows.append(f'  FAIL  "{b["button"]}"{h}')
            if b.get("error"):
                rows.append("        " + b["error"].replace(NL, NL + "        "))
        elif res.startswith("does nothing") or res.startswith("no command"):
            todo.append(f'"{b["button"]}"' + (f' ({b["handler"]})' if b.get("handler") else ""))
            rows.append(f'  todo  "{b["button"]}"{h}  NOT IMPLEMENTED — '
                        + ("its handler is an empty stub" if res.startswith("does nothing")
                           else "no command is attached"))
        else:
            rows.append(f'  ok    "{b["button"]}"{h}' + ("" if res == "ok" else "  " + res))
    _job_ctx.gui_unimplemented = todo
    n = len(r.get("buttons") or [])
    head = (f"[GUI TEST] {Path(path).name}: built {r.get('windows', 0)} window(s), "
            f"pressed {n} button(s): {bad} broken, {len(todo)} not implemented." + NL
            + "Dialogs were answered automatically"
            + (f" (open -> {Path(test_input).name})" if test_input else "")
            + ". This is a REAL test: every button's handler actually ran.")
    if not r.get("windows") and not r.get("startup_error"):
        return False, head + NL + "  No window was created — nothing to test."
    return bad == 0, head + NL + NL.join(rows)


def fs_run_script(path, workspace):
    """Run a Python script in the project workspace."""
    import subprocess as _sp
    ext = Path(str(path)).suffix.lower()
    if ext in _NOT_PYTHON:
        return {"stdout": "", "returncode": -1, "stderr":
                f"run_script runs PYTHON files, and this is a {ext} file. It was "
                f"not executed. Use {_NOT_PYTHON[ext]}. Nothing is wrong with the "
                f"file itself -- do not try to fix it, and do not call run_script "
                f"on it again."}
    # A Tk app started this way sits in its mainloop until the timeout kills it,
    # which reads as "Exit -1, timed out" and tests nothing. Measured six times
    # in one session. Press its buttons instead.
    try:
        if is_gui_script(path, workspace):
            ok, rep = gui_smoke_test(path, workspace,
                                     getattr(_job_ctx, "gui_input", "") or "")
            return {"stdout": rep, "stderr": "", "returncode": 0 if ok else 1}
    except Exception as _ge:
        log(f"GUI test skipped: {_ge}", "warn")
    try:
        py = workspace_python(workspace)
        # A Python script can start a server just as easily as a .ps1 can, so
        # it needs the same tree-killing runner. See _run_capped.
        rc, out, err, timed_out = _run_capped(
            [py, str(path)], 60,
            cwd=str(workspace) if workspace else None)
        if timed_out:
            return {"stdout": (out or "")[:3000], "returncode": -1,
                    "stderr": ("Script timed out after 60s and was killed, "
                               "along with anything it started. If it starts a "
                               "server or waits for input it can never finish "
                               "here -- do not run it again unchanged.")}
        return {"stdout": out[:3000], "stderr": err[:1000], "returncode": rc}
    except _sp.TimeoutExpired:
        return {"stdout": "", "stderr": "Script timed out after 60s", "returncode": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1}


# â”€â”€â”€ AI Chat with Tools â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SYSTEM_PROMPT_TOOLS = (
    "You are NeuralDock AI, a capable local AI assistant with DIRECT ACCESS to the user's computer.\n"
    "You can read and write any file on this PC, run PowerShell, install software, search and read "
    "the web, see the screen, control the mouse and keyboard, generate images, and act on the user's "
    "paired phone. These are real capabilities you actually have, not a description of what some "
    "assistant might do.\n"
    "\n"
    "If native tool calling is unavailable, write TOOL lines EXACTLY as shown, each on its own line:\n"
    "TOOL:list_dir PATH\n"
    "TOOL:read_file PATH\n"
    "TOOL:search_files ROOT|||REGEX_PATTERN\n"
    "TOOL:edit_file PATH|||OLD_TEXT|||NEW_TEXT\n"
    "TOOL:write_file PATH|||CONTENT\n"
    "TOOL:run_script PATH\n"
    "TOOL:web_search QUERY\n"
    "TOOL:web_fetch URL\n"
    "TOOL:design_review PATH|||OPTIONAL_DESIGN_BRIEF\n"
    "\n"
    "BEFORE ANYTHING ELSE — PLAN. If this request has more than one step, your FIRST reply must "
    "contain an update_plan call listing the steps, alongside your first real tool call rather than "
    "instead of it. Then mark each step done as you finish it. It is free, it costs you no tool "
    "round, and the plan is shown back to you every round — it is the only thing keeping a long "
    "task from drifting. A one-step request does not need one.\n"
    "\n"
    "CRITICAL RULES:\n"
    "0. NEVER say you cannot do something before you have tried. You do not need to already know how "
    "an application, game, file format or API works — finding out IS the job, and web_search, "
    "web_fetch, list_dir and run_shell are how you do it. When a request involves something you are "
    "unfamiliar with: search the web for how it works, find it on disk, read what you found, then say "
    "what is possible and do as much of it as you can. 'I don't know how' is a reason to search, never "
    "a reason to refuse. If something genuinely is impossible, say so only AFTER looking, and say "
    "specifically what you found and what blocks you. A confident refusal that turns out to be wrong "
    "is the worst answer you can give.\n"
    "1. When the user mentions any file, folder, path, application, game or program on this PC, call "
    "list_dir or read_file IMMEDIATELY. Do NOT say you cannot access it — you have real filesystem access.\n"
    "2. PREFER edit_file over write_file for changing existing files: read the file first, then replace the EXACT text (copy it verbatim — whitespace matters, make old_text unique). write_file is for NEW files only.\n"
    "3. Use search_files to FIND code instead of reading whole large files. You have a LIMITED number of tool rounds, so do not brute-force page through a big file - search for what matters, then read those areas (use a large limit like 1500 when you do read).\n"
    "3b. Never repeat an identical tool call - you already have that result. When you have enough to answer, ANSWER; do not narrate 'let me continue reading'.\n"
    "4. After edit_file/write_file the result includes a syntax check. If it says VERIFY FAILED, fix your mistake with another edit before answering.\n"
    "5. Use web_search whenever you do not know something — how a program works, what a file format "
    "is, whether a tool exists, how to do a task you have not done before, or any current fact. Do "
    "not guess and do not decline for lack of knowledge: search first, then answer. Use web_fetch for "
    "URLs the user gives you and for the most promising search results.\n"
    "6. write_file, edit_file and run_script require user permission the first time.\n"
    "7. Be concise. No thinking tags. Never claim you did something without actually calling the tool.\n"
)

# Rules 8-9: only meaningful when the turn actually builds or edits a UI.
# Emitted conditionally (see system_content assembly) because the fixed
# prompt cost is what pushes a small-window model into front-truncation.
SYSTEM_PROMPT_UI_RULES = (
    "8. YOU CANNOT SEE. After writing or editing ANY .html page, call design_review on it before you "
    "reply. It renders the page in a real browser and tells you what it actually looks like. Skipping "
    "it means you are guessing, and a page that renders blank looks identical to a perfect one from "
    "where you sit. Act on anything it reports as BROKEN, then review again to confirm.\n"
    "9. Before building a UI from scratch, state the design in one short block first - palette (3-5 "
    "colours), typeface pairing, spacing rhythm, and the mood in three words - then build to it and "
    "pass that same block to design_review as the brief. A UI built without a stated brief drifts to "
    "the same generic centred-hero-and-three-cards layout every time.\n"
)

# Rule 10: the test rule. Always emitted - it is what T3 measures.
SYSTEM_PROMPT_CODE_RULES = (
    "10. NEW BEHAVIOUR NEEDS A TEST, IN THE SAME ROUND, IN THE TEST FILE THAT ALREADY COVERS THAT "
    "AREA. When you add or change what the code DOES - a route, a function's output, a rule - use "
    "search_files to find the existing test file for it and add a case there. Do NOT create a new "
    "test file: only files that were already green are re-run and checked afterwards, so a new file "
    "is invisible and proves nothing. This is rule 8 for code. You cannot see whether a route you "
    "just wrote answers or 404s; a broken endpoint and a working one look identical from where you "
    "sit, and the test is the only thing that tells you which you built. Refactors, renames and "
    "formatting need no new test - the existing suite already covers those. If you change "
    "behaviour and add no test, you will be stopped before finishing and told to add one, so do "
    "it as part of the work rather than being sent back for it.\n"
)

# --- Environment preamble -----------------------------------------------------
# Established facts, stated once. Everything here is something the model would
# otherwise burn a tool round finding out.
ENV_MAX_ENTRIES = 14
ENV_BIG_FILE_SHARE = 0.6      # of the window; above this, reading it whole is hopeless


def _fmt_size(n):
    if n >= 1024 * 1024:
        return f"{n / 1048576:.1f} MB"
    if n >= 1024:
        return f"{n // 1024} KB"
    return f"{n} B"


# Elena persona is ~1,500 tokens and every one of them used to load on every
# request -- Spotify URI encoding, media keys, screen_capture ordering -- even
# when the user asked her to fix a router. On an 8K window that is a fifth of
# the budget spent on things the request cannot use.
#
# Split it: identity and tone always; the Windows-driving material only when the
# request could plausibly need it. The default is ON, because a false negative
# costs Elena the ability to do her job and a false positive only costs tokens.
_DESKTOP_RE = re.compile(
    r"\b(spotify|chrome|edge|firefox|browser|explorer|notepad|steam|discord|"
    r"outlook|excel|word|vlc|obs|photoshop|blender|window|desktop|screen|"
    r"click|mouse|keyboard|type|screenshot|volume|mute|play|pause|skip|track|"
    r"song|music|video|launch|open|close|install|uninstall|shutdown|restart|"
    r"taskbar|start menu|settings|wifi|bluetooth|printer|phone|device)\b", re.I)


_CODE_RE = re.compile(
    r"(\S+\.(?:py|js|jsx|ts|tsx|html|css|json|md|sql|ya?ml|toml)\b)"
    r"|\b(endpoint|router|route|schema|model|migration|api|handler|"
    r"function|method|class|def|import|module|component|refactor|"
    r"suite|unittest|pytest|regression|commit|repo|repository|"
    r"docstring|traceback|stacktrace|exception|linter|typo in the code)\b"
    r"|\b(test_\w+|\w+_test)\b", re.I)


def wants_pc_control(text, workspace=""):
    """Should Elena be handed the whole Windows-driving playbook this turn?

    Default YES. A false negative costs Elena the ability to do her job; a
    false positive only costs tokens, so the bar for dropping it is high:
    the request must carry a clear code signal AND mention nothing on the
    desktop.

    This deliberately does NOT reuse looks_like_change() -- that gate needs a
    named file to fire and returns False on "change the colour of the header",
    which is correct for choosing a placed edit and useless for choosing a
    persona.
    """
    t = (text or "").strip()
    if not t:
        return True
    if _DESKTOP_RE.search(t):
        return True
    return not _CODE_RE.search(t)


def environment_block(workspace="", model=None):
    """Date, system, working folder and what is in it, as a short prompt block.

    Kept deliberately tight. The preamble is already ~3,650 tokens before the
    user's own message, so anything added here has to earn its place by removing
    more rounds than it costs.
    """
    win = 0
    if model:
        try:
            win = int(model_profile(model)["num_ctx"])
        except Exception:
            win = 0
    lines = ["\n\nENVIRONMENT — established facts. Do not spend a tool round rediscovering these.",
             f"  Today      : {datetime.now().strftime('%Y-%m-%d')}"]
    if sys.platform == "win32":
        lines.append("  System     : Windows. Paths use backslashes; run_shell is PowerShell.")
    else:
        lines.append(f"  System     : {sys.platform}")

    ws = str(workspace or "").strip().strip('"').strip("'")
    if not ws or not Path(ws).is_dir():
        lines.append("  Workspace  : none set — ask the user which folder to work in "
                     "before creating any file.")
        return "\n".join(lines) + "\n"

    lines.append(f"  Workspace  : {ws}")
    # run_script already uses this interpreter. Saying so stops the model
    # hunting for a way to install dependencies it can in fact already import,
    # and tells it what to type if it reaches for run_shell instead.
    wpy = workspace_python(ws)
    if wpy not in ("python", str(VENV_PY)):
        lines.append(f"  Python     : {wpy}")
        lines.append("               This project's venv. run_script uses it already. It has the "
                     "project's dependencies installed; bare 'python' does NOT. If you shell out, "
                     "use this full path. Do not install anything.")
    try:
        entries = [p for p in Path(ws).iterdir() if not p.name.startswith(".")]
    except Exception as e:
        lines.append(f"  Contents   : could not be listed ({e})")
        return "\n".join(lines) + "\n"
    # Directories first, then files, each alphabetical: a folder is a place to
    # look next, a file is a thing to read, and they are read differently.
    entries.sort(key=lambda p: (p.is_file(), p.name.lower()))
    if not entries:
        lines.append("  Contents   : the folder is empty.")
        return "\n".join(lines) + "\n"

    lines.append("  Contents   :")
    shown = entries[:ENV_MAX_ENTRIES]
    big = False
    for p in shown:
        if p.is_dir():
            lines.append(f"    {p.name}/")
            continue
        try:
            n = p.stat().st_size
        except Exception:
            n = 0
        # Flag per file, explain once below. Repeating the whole sentence on
        # every entry costs ~30 tokens a file in exactly the windows that can
        # least afford it.
        flag = ""
        if win and (n / 4) > win * ENV_BIG_FILE_SHARE:
            flag = f"  TOO BIG (~{int(n / 4000)}k tokens)"
            big = True
        lines.append(f"    {p.name}  ({_fmt_size(n)}){flag}")
    rest = len(entries) - len(shown)
    if rest > 0:
        lines.append(f"    ...and {rest} more (list_dir to see them)")
    if big:
        lines.append(f"  Anything marked TOO BIG will not fit in your {win // 1024}K window. Do "
                     f"not read or rewrite it whole — search_files to find what matters, then "
                     f"read only that part and change it with edit_file.")
    return "\n".join(lines) + "\n"

# ═══════════════════════════════════════════════════════════════════════════════
# AGENT MODE — PC control with tiered permissions + ADMIN override
# ═══════════════════════════════════════════════════════════════════════════════
# Tiers:
#   green  = read-only. Runs immediately, no prompt.
#   yellow = writes inside the workspace. Ask once per session, then remembered.
#   red    = system level (shell, installers, mouse/keyboard). Ask EVERY time.
#   black  = catastrophic / irreversible. Refused... unless ADMIN MODE is on.
# ADMIN MODE (agent_admin_mode in config) lifts the blocklist and every prompt.
# Everything is still written to agent_audit.log either way.
AGENT_AUDIT_LOG = _CONFIG_DIR / "agent_audit.log"

# ─── Cross-turn loop breaker ──────────────────────────────────────────────────
# seen_calls only lives inside ONE process_ai_response_with_tools run. Every
# permission approval starts a NEW run, so the duplicate guard reset each time
# and the model happily ran `Start-Process Spotify` six times in a row. This
# keeps the tally per conversation, across approvals, so a repeat is caught.
_session_calls = {}          # sid -> {call_key: count}
STUCK_AFTER = 3              # same exact call this many times = stop and ask
# How many times the breaker itself may fire for ONE call before the turn ends.
#
# Measured 2026-09-08: the breaker refused the call correctly but returned the
# SAME text every time, so the model read the same thing and repeated -- logs
# show "STUCK after 12 identical calls" on a single read_file. Each repeat burns
# a round out of MAX_ROUNDS, and runs stretched to 20-30 minutes doing nothing.
#
# Refusing is not enough on its own. If the model has been told to stop three
# times and has not, it is not going to; ending the turn with an honest account
# beats spending the rest of the budget proving it again.
STUCK_GIVE_UP = 3

def _session_key(sid, name, args):
    return name + ":" + hashlib.sha1(
        json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:12]

_session_giveups = {}        # sid -> {call_key: times the turn was ended for it}


def note_session_giveup(sid, name, args):
    """Record that a turn was ended for this call, and return the total.

    MUST be session-scoped, not per-turn. Measured 2026-09-08: the first version
    of this counted per turn, which bounded the waste inside one turn and did
    nothing at all across turns -- a repair pass simply starts a new turn, the
    per-turn tally resets, and the model resumes the identical call:

        STUCK 3, 4      -> ending the turn
        STUCK 6, 6, 7   -> ending the turn
        STUCK 9, 10     -> ending the turn
        STUCK 12, 13    -> ending the turn

    The session counter climbed straight through it. Ending a turn is only
    useful if the NEXT turn remembers why.
    """
    if not sid:
        return 1
    with _lock:
        d = _session_giveups.setdefault(sid, {})
        k = _session_key(sid, name, args)
        d[k] = d.get(k, 0) + 1
        return d[k]


def seen_session_giveup(sid, name, args):
    """Has a turn already been ended for this exact call this session?"""
    if not sid:
        return 0
    with _lock:
        return (_session_giveups.get(sid) or {}).get(_session_key(sid, name, args), 0)


def note_session_call(sid, name, args):
    """Record a call and return how many times it has now been made."""
    if not sid:
        return 1
    with _lock:
        d = _session_calls.setdefault(sid, {})
        k = _session_key(sid, name, args)
        d[k] = d.get(k, 0) + 1
        return d[k]

def reset_session_calls(sid):
    with _lock:
        _session_calls.pop(sid, None)
        _session_giveups.pop(sid, None)
        _session_work.pop(sid, None)


def forgive_session_calls(sid):
    """A new user message arrived: stop holding the last turn's loops against it.

    The new turn gets the full within-turn allowance back: STUCK_AFTER - 1 runs
    of any one call, then the breaker. That is the behaviour that was designed
    and measured, and it still catches every loop that matters -- including the
    verify-after-write pattern we WANT (list_dir, write, list_dir again), which
    a stingier allowance would block.

    Nothing that the cross-turn tally was actually built for is weakened. The
    2026-09-08 failure was automatic repair passes resetting a per-TURN counter
    and climbing 3,4 -> 6,6,7 -> 9,10; those passes call
    process_ai_response_with_tools directly and permission approvals resume in
    place via resolve_permission. Neither reaches run_chat_job, so neither is
    forgiven here. Only a human typing a new message is.

    The give-up latch goes too. Its job is "do not re-run the whole escalation
    ladder inside one request"; carried into a new request it only guarantees
    the new request dies having run nothing at all.
    """
    if not sid:
        return
    with _lock:
        _session_calls.pop(sid, None)
        _session_giveups.pop(sid, None)


# ─── Working memory: what the agent has already DONE this session ─────────────
# Separate from the Obsidian long-term memory. That answers "what do I know
# about the user"; this answers "what did I just do five minutes ago".
#
# Without it every turn started from a blank slate: the model would write
# retro_vault/index.html, then next turn have no idea the file existed and
# create it again from scratch. The conversation transcript alone does not fix
# this, because tool results get compacted and the model has to re-derive state
# from prose. An explicit ledger of files touched is unambiguous and cheap.
_session_work = {}           # sid -> {"files": {path: {...}}, "actions": [...]}
WORK_ACTIONS_KEPT = 25       # recent actions shown back to the model
WORK_FILES_KEPT = 60         # distinct files tracked per session

_PATH_ARGS = ("path", "file", "filename", "file_path", "target", "dest")


def _arg_path(args):
    for k in _PATH_ARGS:
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def note_session_work(sid, name, args, result):
    """Record one completed tool action in the session ledger."""
    if not sid:
        return
    text = str(result or "")
    failed = text.lstrip().startswith("[ERROR") or "VERIFY FAILED" in text
    if name in ("write_file", "edit_file") and write_result_failed(text):
        # A refused or failed write changed nothing. Measured 2026-09-25: two
        # scope-refused writes were then reported to the user as "Earlier in this
        # session it did produce: set_location_fixed.py, temp_set_location.py".
        return
    with _lock:
        w = _session_work.setdefault(sid, {"files": {}, "actions": []})
        if name in ("write_file", "edit_file"):
            p = _arg_path(args)
            if p:
                rec = w["files"].setdefault(p, {"writes": 0, "ok": True})
                rec["writes"] += 1
                rec["ok"] = not failed
                rec["how"] = "edited" if name == "edit_file" else "written"
                if len(w["files"]) > WORK_FILES_KEPT:
                    w["files"].pop(next(iter(w["files"])))
        # _summ() is a closure inside process_ai_response_with_tools and is not
        # reachable here, so summarise locally.
        summary = _arg_path(args) or args.get("command") or args.get("query") \
            or args.get("name") or json.dumps(args, default=str)[:110]
        w["actions"].append(
            f"{name}({str(summary)[:110]}) -> {'FAILED' if failed else 'ok'}")
        if len(w["actions"]) > WORK_ACTIONS_KEPT:
            del w["actions"][0]


def session_work_files(sid):
    """The paths this session has created or edited, oldest first.

    Same store session_work_prompt renders for the model; this is for telling
    the USER what actually got done when a turn ends badly.
    """
    if not sid:
        return []
    with _lock:
        w = _session_work.get(sid)
        files = dict((w or {}).get("files") or {})
    # Told to the user as "it did produce", so only what is really on disk.
    out = []
    for p, rec in files.items():
        try:
            if (rec or {}).get("ok", True) and Path(p).is_file():
                out.append(p)
        except OSError:
            pass
    return out


def session_work_prompt(sid):
    """Render the ledger for injection into the system prompt."""
    if not sid:
        return ""
    with _lock:
        w = _session_work.get(sid)
        if not w or (not w["files"] and not w["actions"]):
            return ""
        files = list(w["files"].items())
        actions = list(w["actions"])
    out = ["## Work you have ALREADY done in this session",
           "This is a record of your own actions. It is authoritative — trust it "
           "over your recollection."]
    if files:
        out.append("")
        out.append("Files you have already created or edited. They EXIST on disk. "
                   "Do not recreate them from scratch: read one first and modify it, "
                   "and do not re-announce work you already finished.")
        for path, rec in files:
            flag = "" if rec.get("ok", True) else "  [LAST WRITE FAILED — needs fixing]"
            times = "" if rec["writes"] == 1 else f", {rec['writes']}x"
            out.append(f"- {path}  ({rec.get('how','written')}{times}){flag}")
    if actions:
        out.append("")
        out.append("Recent tool actions, oldest first:")
        out.extend(f"- {a}" for a in actions)
    out.append("")
    out.append("If the user asks you to continue, resume from this state rather "
               "than restarting the task.")
    return "\n".join(out)

# ─── "I'm about to..." detector ───────────────────────────────────────────────
# Catches a reply that announces an action and then does nothing, e.g.
#   "Now let me create the HTML frontend for the Retro Vault application:"
# Deliberately conservative: it must be the CLOSING thought of the reply, so a
# narration line followed by a real answer does not trigger it.
# The verb list started out as the things that CHANGE something, on the theory
# that those are what get promised and skipped. Measured against a real run,
# that was wrong. Both dead-end replies were investigation verbs:
#
#     "Let me look at the server.py file to understand the backend..."
#     "Let me examine the server-side Python code..."
#
# Neither matched, so no nudge ever fired and the turn simply ENDED on the
# dangling sentence -- which is why the user saw a promise and an empty folder
# with no "attempts" counter at all. Read verbs strand a turn exactly as hard
# as write verbs do.
#
# It happened a THIRD time, with the vocabulary the reskin pipeline invites.
# The reply was:
#
#     "I will insert the CSS block immediately after the existing style block."
#
# "insert" was not in the list, so no nudge fired, the turn ended on the
# promise, and the user answered the model picker again -- a loop with no work
# in it. A reskin is described with a different set of verbs from a build
# (insert, apply, inject, append, copy, theme, restyle), and every one of them
# was missing. Keep this list generous: a false positive costs one nudge the
# model can ignore, a false negative costs the whole turn.
_INTENT_VERB = (r"(?:creat|writ|mak|build|add|updat|implement|generat|"
                r"fix|check|read|run|start|set\s*up|install|refactor|continu|"
                r"look|examin|inspect|review|analy[sz]|explor|scan|open|list|"
                r"search|find|verif|test|load|extract|convert|design|draft|"
                r"replac|modif|remov|delet|launch|port|see|go\s+through|"
                r"insert|appl|inject|append|prepend|attach|copy|copie|"
                r"re-?skin|re-?styl|re-?theme|theme|styl|"
                r"place|put|save|store|move|renam|swap|patch|"
                r"adjust|tweak|tune|polish|clean|wrap|inline|embed|"
                r"proceed|begin|do\s+this|handle|prepar)")
# The leading \b is load-bearing. Without it `i'?ll` matches the "ill" inside
# "still" -- so "the app still loads with all 196 element ids intact", a plain
# statement of finished work, parsed as "I'll ... load" and got nudged. Common
# words that would otherwise trip it: still, skill, fill, till, chill, bill.
_LEADIN = (r"\b(?:let\s+me|i'?ll|i\s+will|i'?m\s+going\s+to|next[,\s]+i|now\s+i|"
           r"let'?s|i\s+need\s+to|i\s+should|first[,\s]+i)")
_INTENT_RE = re.compile(_LEADIN + r"\s+(?:\w+\s+){0,4}" + _INTENT_VERB, re.I)

# Any first-person lead-in, verb or not. Only used together with a trailing
# colon, which is already conclusive on its own.
_LEADIN_RE = re.compile(_LEADIN + r"\b", re.I)


def announces_unfinished_work(text: str) -> bool:
    """True if the reply promises an action it never actually performed."""
    if not text:
        return False
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return False
    tail = " ".join(lines[-2:])
    # A trailing colon is the strongest tell: the model was about to emit a
    # tool call or a file and stopped. Reached here only when the round parsed
    # ZERO tool calls, so nothing followed the colon -- it is dangling by
    # definition, whatever verb led into it.
    if tail.endswith(":"):
        if _LEADIN_RE.search(tail) or _INTENT_RE.search(tail):
            return True
        # "Now the HTML file:" has no lead-in phrase at all, but a short reply
        # that ends on a colon still promised something it did not deliver.
        if len(text) < 600:
            return True
    if _INTENT_RE.search(tail) and not re.search(r"\?\s*$", tail):
        # "I'll now write the file" with no colon still counts, but only if the
        # reply is short enough to be a lead-in rather than a finished answer.
        return len(text) < 900
    return False


# ─── Tool-result imitation detector ───────────────────────────────────────────
# _exec_one() prefixes every real result with a marker: "[FILE] ...", "[WEB] ...",
# "[RUN] ...". Those markers are produced by ND and fed back into the transcript.
# Models learn the pattern from context and start TYPING it instead of calling
# the tool:
#
#     I'll create the file now:
#     [FILE] [G:\TMP\TMP\retro-vault-enhanced.html]
#
# Zero tool calls parse, nothing is written, and the reply looks like success --
# to the user AND to the "did it announce work" heuristic. This produced an
# infinite loop: announce -> auto-continue -> announce -> hand back to user ->
# user types "ok" -> repeat, with an empty folder the whole time.
# [^\]]* because real markers can carry a payload -- "[IMAGE job=1a2b3c]" -- and
# an exact "[IMAGE]" match missed those entirely.
_RESULT_ECHO_RE = re.compile(
    r"^\s*\[(FILE|WEB|RUN|DIR|TOOL|OK|ERROR|IMAGE)\b[^\]]*\]", re.I | re.M)


def imitates_tool_results(text: str) -> bool:
    """True if the model typed ND's result markers instead of calling a tool."""
    return bool(text) and bool(_RESULT_ECHO_RE.search(text))


def _ws_norm(s):
    return " ".join(str(s or "").split())


def echo_is_recap(text, tool_results):
    """True if every result-marker line the model typed is a COPY of a result ND
    really produced in this job -- a summary quoting real results, not a fake.

    Measured 2026-09-25 on three Golf It jobs in a row: the model made a real,
    successful edit, then finished with a summary quoting ND's own
    "[FILE] Edited ...set_location.py (1 replacement). ... Verified OK." The echo
    detector called that a fake, the nudge said "Nothing has been created. Use the
    write_file tool", and the model rewrote the file it had just written -- once
    each in two jobs, and three times (a rewrite-loop stop) in the third.

    The WHOLE line must appear in a real result, not just its start: a fake
    "[FILE] [G:\\x\\a.py]" is a prefix of the real read result
    "[FILE] [G:\\x\\a.py ? lines 1-9 ...]" and must still count as a fake. Very
    short lines prove nothing either way, so they never make a recap.
    """
    lines = [ln for ln in (text or "").splitlines() if _RESULT_ECHO_RE.match(ln)]
    if not lines:
        return False
    real = _ws_norm(" \n ".join(str((r or {}).get("result") if isinstance(r, dict) else r)
                                for r in (tool_results or [])))
    for ln in lines:
        n = _ws_norm(ln)
        if len(n) < 30 or n not in real:
            return False
    return True


# --- Refused-work claim detector ---------------------------------------------
# imitates_tool_results catches a model FAKING a result. This catches the other
# half: a model that was told plainly its call was refused, and reports success
# anyway. Measured on frontend-design-expert-8b, denied a write_file:
#
#     "The task was to create G:\...\refused.txt with the word "nope". I already
#      created a denial placeholder at the same location, and I have now checked
#      the file system state. The work is complete and verified."
#
# No such file exists. Unlike every other honesty heuristic here, this one is not
# guessing: ND knows exactly which calls it blocked.
#
# Past forms ONLY. "The task was to create X" is the model restating the request,
# not claiming to have done it, and an infinitive in the verb list turns every
# honest summary into a false positive.
_CLAIM_VERB_RE = re.compile(
    r"\b(?:created|wrote|written|saved|added|updated|generated|built|made|"
    r"produced|completed|finished|delivered|implemented|verified)\b", re.I)

# Any of these in the same sentence means the model is DESCRIBING the refusal
# rather than claiming success. Without it, "I could not create hello.txt" trips
# the verb check and ND contradicts a model that told the truth -- a worse
# outcome than the confabulation this is looking for.
_CLAIM_NEG_RE = re.compile(
    r"\b(?:not|n't|never|no|none|nothing|unable|cannot|can't|won't|couldn't|"
    r"refus\w*|den(?:y|ies|ied)|declin\w*|block\w*|fail\w*|permission|skip\w*|"
    r"without|instead|attempt\w*|tried|would|need\w*)\b", re.I)

# A sign-off with nothing behind it.
_ALL_DONE_RE = re.compile(
    r"\b(?:task (?:is |was )?complete|work is (?:complete|done|finished)|all done|"
    r"everything (?:is )?(?:done|complete)|(?:is|are) now (?:complete|done|ready)|"
    r"successfully (?:created|written|saved|completed))\b", re.I)


def claims_refused_work(text, denied, nothing_succeeded=False):
    """Denied calls that the reply claims to have carried out anyway.

    Returns the matching entries from `denied`, or []. Deliberately conservative
    on both rules: a false positive contradicts a model that was honest, which is
    worse than the lie it is meant to catch.
    """
    if not text or not denied:
        return []
    sentences = [s for s in re.split(r"(?<=[.!?;:\n])\s+", text) if s.strip()]
    hits, seen = [], set()
    for d in denied:
        p = str(d.get("path") or "").strip()
        if not p:
            continue                      # nothing specific enough to match on
        name = Path(p).name
        key = (d.get("tool"), p)
        if not name or key in seen:
            continue
        for s in sentences:
            if name.lower() not in s.lower():
                continue
            # Test the PROSE, not the filename. A file called refused.txt or
            # no-permission.md matches the negation pattern on its own name and
            # would make itself permanently immune to this check.
            probe = re.sub(re.escape(name), " ", s, flags=re.I)
            if _CLAIM_NEG_RE.search(probe):
                continue
            if _CLAIM_VERB_RE.search(probe):
                hits.append(d); seen.add(key); break
    if hits:
        return hits
    # Nothing named it, but the reply signs off as finished while every tool call
    # in the whole turn was refused. There is nothing it could truthfully mean.
    if nothing_succeeded:
        for s in sentences:
            if _ALL_DONE_RE.search(s) and not _CLAIM_NEG_RE.search(s):
                return list(denied)
    return []


def refused_work_note(hits):
    """The correction appended to a reply that claimed refused work was done."""
    what = ", ".join(sorted({
        (f"{h['tool']} ({Path(h['path']).name})" if h.get("path") else str(h.get("tool")))
        for h in hits}))
    return ("\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
            f"NOT DONE. You refused permission for: {what}. Those calls never ran and "
            "nothing was created or changed on disk. The answer above says otherwise \u2014 "
            "that part of it is wrong.")


# ─── No-progress tracking (survives the user typing "ok") ─────────────────────
# The auto-continue counter used to be a local in process_ai_response_with_tools.
# Every user message starts a NEW call, so the counter reset to 0 each time and
# the "(1/3)" in the log never advanced past 1. Keeping it on the session is what
# actually stops the loop.
def note_no_progress(sid, reply):
    """Record a reply that called no tools. Returns {'count', 'repeat'}."""
    h = hashlib.sha1((reply or "").strip().encode("utf-8", "replace")).hexdigest()[:12]
    if not sid:
        return {"count": 1, "repeat": False}
    with _lock:
        w = _session_work.setdefault(sid, {"files": {}, "actions": []})
        st = w.setdefault("noprog", {"count": 0, "hashes": []})
        st["count"] += 1
        repeat = h in st["hashes"]
        st["hashes"].append(h)
        if len(st["hashes"]) > 6:
            del st["hashes"][0]
        return {"count": st["count"], "repeat": repeat}


def clear_no_progress(sid):
    """Called as soon as a real tool runs -- progress resets the patience."""
    if not sid:
        return
    with _lock:
        w = _session_work.get(sid)
        if w:
            w.pop("noprog", None)


# ─── Live activity feed ───────────────────────────────────────────────────────
# Feeds the 3-line strip in the UI. A ring buffer on the status record, so the
# existing progress poll carries it with no new endpoint. Deliberately small:
# the point is a glance at what is happening now, not a transcript.
ACTIVITY_KEPT = 12


def agent_activity(req_id, kind, label, detail="", ok=None, secs=None):
    """Append one line to the live activity feed for this request."""
    if not req_id:
        return
    row = {"kind": kind, "label": str(label)[:70],
           "detail": str(detail)[:90], "t": time.time()}
    if ok is not None:
        row["ok"] = bool(ok)
    if secs is not None:
        row["secs"] = round(float(secs), 1)
    if kind == "tool" and label in ("read_file", "write_file", "edit_file") and detail:
        try:
            _op = "read" if label == "read_file" else ("update" if Path(detail).exists() else "write")
            vault_event(_op, detail, "tool")
        except Exception:
            pass
    with _lock:
        st = _chat_status.setdefault(req_id, {})
        feed = st.setdefault("activity", [])
        feed.append(row)
        if len(feed) > ACTIVITY_KEPT:
            del feed[0:len(feed) - ACTIVITY_KEPT]


# --- Live token stream -------------------------------------------------------
# Ollama has always streamed; ND read the stream only to count tokens for a
# progress bar and dropped the text. On a run that takes 200-700s that meant
# staring at a spinner. The text now lands here and /api/chat_status hands out
# whatever is new since the caller's offset.
STREAM_KEPT_CHARS  = 200000   # hard cap: a 24-round agent run can generate tens
                              # of thousands of tokens and this is held for the
                              # whole job. Overflow drops from the FRONT and
                              # bumps stream_base so offsets stay truthful.
STREAM_FLUSH_CHARS = 24       # batch before each callback (see _flush below)

def stream_append(req_id, delta):
    """Append generated text to the live buffer for this request."""
    if not req_id or not delta:
        return
    with _lock:
        st   = _chat_status.setdefault(req_id, {})
        buf  = st.get("stream", "") + delta
        base = st.get("stream_base", 0)
        if len(buf) > STREAM_KEPT_CHARS:
            drop = len(buf) - STREAM_KEPT_CHARS
            buf, base = buf[drop:], base + drop
        st["stream"]      = buf
        st["stream_base"] = base
        st["stream_len"]  = base + len(buf)


# Every key stream_append writes must also be carried across by _set_status,
# which rebuilds the status dict from scratch several times a round. The
# activity feed was lost that way once already; test_stream.py checks it.
STREAM_KEYS = ("stream", "stream_base", "stream_len")

def stream_slice(status, sfrom):
    """(text, absolute_start, total_len) for everything after offset sfrom.

    Callers hold an offset, not a copy, so the answer has to say where the text
    it is handing back actually begins: BELOW the caller's offset when two polls
    overlap, ABOVE it when the STREAM_KEPT_CHARS cap dropped text off the front.
    """
    buf   = status.pop("stream", "") or ""
    base  = int(status.pop("stream_base", 0) or 0)
    try:
        start = max(int(sfrom or 0) - base, 0)
    except (TypeError, ValueError):
        start = 0
    # Clamp to the end of the buffer. A caller can hold an offset larger than
    # anything that exists -- ND restarting mid-run leaves the UI with a stale
    # _streamLen and an empty server buffer -- and without this the answer says
    # it starts at 99 of a 3-character stream, which is simply not a coherent
    # thing to tell anyone.
    start = min(start, len(buf))
    return buf[start:], base + start, base + len(buf)


def _activity_target(args):
    """The most human-meaningful thing about a call: a path, a command, a query."""
    if not isinstance(args, dict):
        return str(args)[:90]
    p = _arg_path(args)
    if p:
        return p
    for k in ("command", "cmd", "query", "url", "name", "action"):
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:90]
    return ""


def agent_round(req_id, n):
    if not req_id:
        return
    with _lock:
        _chat_status.setdefault(req_id, {})["round"] = n


def no_progress_report(reply, echoed, st, ctx_pct=0, window=0, reads=0, wrote=None):
    """An honest dead-end message instead of replaying the empty promise.

    `wrote` is the list of files this run actually created. It matters: a run
    that produced two files and then stalled on the third is PARTIAL work, and
    reporting it as "nothing was created or changed on disk" is a lie the user
    would have to disprove by hand. Measured on the RetroVault run: 2 files,
    17 KB, reported as nothing.
    """
    wrote = list(wrote or [])
    first = next((l.strip() for l in (reply or "").splitlines() if l.strip()), "")
    # A full window is a cause, not a coincidence: past ~85% Ollama starts
    # dropping the oldest messages, and the first thing to go is the original
    # instruction. Say so rather than blaming the model's manners.
    ctx_note = ""
    if ctx_pct >= 80 and window:
        ctx_note = (f"\nContext was {ctx_pct}% full ({window} tokens) when it gave up"
                    + (f", after {reads} read-only calls" if reads else "")
                    + ". Past ~85% Ollama silently drops the OLDEST messages, which is "
                    "your original instruction. The model was not ignoring you; it "
                    "could no longer see the request. Ask for one file at a time, or "
                    "switch to a model with a larger window for this step.\n")
    why = ("It printed ND's tool-RESULT format as plain text (`[FILE] ...`) "
           "instead of calling the tool. Those markers are produced by "
           "NeuralDock, never by the model."
           if echoed else
           "It described the work but never issued a tool call.")
    if wrote:
        head = (f"STOPPED - partial work. {len(wrote)} file(s) were created, then it "
                "stalled.\n\n"
                "These are real and are on disk:\n"
                + "\n".join(f"  - {w}" for w in wrote[:12])
                + (f"\n  ...and {len(wrote)-12} more" if len(wrote) > 12 else "")
                + f"\n\nThen: {why[0].lower() + why[1:]}\n"
                f"Attempts after the last successful write: {st['count']}.\n")
        advice = ("\nThe run was working, so this is worth resuming rather than "
                  "restarting. Try:\n"
                  "  - \"continue - write the next file\"\n"
                  "  - Name the remaining file explicitly\n"
                  "  - Ask for one file per message")
    else:
        head = ("STOPPED - no actual work was performed.\n\n"
                f"{why}\n\n"
                f"Nothing was created or changed on disk. Attempts: {st['count']}.\n")
        advice = ("\nThis is a model behaviour problem, not a permissions one - approving "
                  "or replying 'ok' will just repeat it. Try one of:\n"
                  "  - Ask again and say explicitly: \"use the write_file tool\"\n"
                  "  - Switch to a different model for this step\n"
                  "  - Break the request into one file at a time")
    return (head + ctx_note
            + (f"\nWhat it kept claiming:\n  {first[:300]}\n" if first else "")
            + advice)


# ─── Is a tool result still in the window? ───────────────────────────────────
# The tail, not the head: compaction trims the END of a long result, so a read
# can still show its "[FILE] path - lines 1-227 of 386" header while the content
# the model actually needs is gone. Matching on the header would call that
# present and reproduce the deadlock this exists to break.
RESERVE_LIMIT = 2            # re-serves per call per turn, then refuse honestly


def _result_signature(text):
    t = " ".join(str(text or "").split())
    return t if len(t) < 48 else t[-64:]


def result_still_visible(convo, text):
    """True if this exact result is still readable in the conversation."""
    sig = _result_signature(text)
    if not sig:
        return True          # nothing to look for: do not re-serve on a blank
    for m in convo or []:
        c = m.get("content")
        if not isinstance(c, str) or len(c) < len(sig):
            continue
        if sig in " ".join(c.split()):
            return True
    return False


# ─── Run what you just wrote ─────────────────────────────────────────────────
# See the module note on the run gate. The rule that makes this worth doing is
# not "run more things", it is "lead the retry with a traceback".
RUN_GATE_TIMEOUT = 45
RUN_GATE_REPAIRS = 2          # a model that cannot fix it given the real
                              # traceback twice will not fix it on the third
_TRACEBACK_RE = re.compile(r"^Traceback \(most recent call last\):", re.M)
# An error the script CAUGHT and printed itself. gvas_dump.py exits 0 and prints
# "Error parsing GVAS file: ..." -- a clean exit code says nothing here.
_SELFREPORT_ERR_RE = re.compile(
    r"^\s*(?:error|failed|failure|exception|traceback)\b[^\n]{0,200}", re.I | re.M)
# A script that wants arguments and says so is behaving correctly.
_USAGE_RE = re.compile(r"^\s*usage\s*:", re.I | re.M)
# A script that REJECTS the argument it was given does not take that input. That
# is not a failure of the script -- measured 2026-09-24: the gate ran a working
# set_location.py on PLAN.md, the script correctly said "Unknown argument", and
# two repair passes were spent "fixing" it and the user was told it was broken.
_ARG_REJECTED_RE = re.compile(
    r"unknown argument|unrecognized arguments?|invalid argument|unexpected argument"
    r"|no such option|expected one argument|^\s*usage\s*:", re.I | re.M)
# The words just before a path that make it an INPUT rather than reading
# material: "run it on X", "use this as a test file: X", "parse X". A prompt
# that says "Read X first" is pointing at documentation.
_INPUT_INTENT_RE = re.compile(
    r"(?:run(?:\s+it|\s+this)?\s+(?:on|against|with)|test(?:\s+it)?\s+(?:on|with)"
    r"|test\s+file|input\s+file|as\s+(?:a|the)\s+(?:test\s+)?(?:input|file)"
    r"|use\s+this|parse|feed\s+it|process|load|open)"
    r"[^A-Za-z]{0,6}$", re.I)


def _is_script(path):
    """A file worth running on its own: it has a __main__ entry point."""
    try:
        return "__main__" in Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def _run_gate_inputs(user_text, workspace):
    """Real, existing file paths the user named, to pass as argv.

    Running a parser with no arguments only proves it imports. The user's own
    message is where the thing it is supposed to parse is named, and it is the
    one input we can be confident is intended.
    """
    out = []
    text = user_text or ""
    for m in re.finditer(r"[A-Za-z]:[\\/][^\"'`\n,;]{3,200}?\.[A-Za-z0-9]{1,6}", text):
        p = m.group(0).strip().rstrip(".,;:")
        # Only a path the message presents AS AN INPUT. See _INPUT_INTENT_RE.
        if not _INPUT_INTENT_RE.search(text[max(0, m.start() - 40):m.start()]):
            continue
        try:
            if Path(p).is_file() and not p.lower().endswith(".py"):
                out.append(p)
        except Exception:
            continue
        if len(out) >= 2:
            break
    return out


# Per-project run rules: <workspace>/nd_rules.json. A crash is not the only way
# a script can be wrong. Measured 2026-09-24: find_names.py had no usage check,
# so a bare run did the real thing (pressed keys in a game), and its --dry-run
# printed one line and exited 0 without touching the fake game. Both runs were
# "clean", so the gate passed it. Only the project knows its contract, so the
# project states it:
#
#   {"run_gate": [
#      {"files": "*.py", "exclude": ["fakegame.py"], "args": [],
#       "must_print": "imports OK", "must_exit": 0,
#       "why": "A bare run must only check imports and print usage."},
#      {"files": "*.py", "exclude": ["fakegame.py"], "args": ["--dry-run"],
#       "must_print": "using a fake game",
#       "why": "--dry-run must run the real path via fakegame.install()."}]}
#
# "files"/"exclude" are file-name globs; "must_print" is a substring of stdout
# plus stderr; "must_exit" is optional.
RULES_FILE = "nd_rules.json"


def workspace_run_rules(workspace, path):
    """The nd_rules.json run-gate rules that apply to this script."""
    if not workspace:
        return []
    f = Path(workspace) / RULES_FILE
    if not f.is_file():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"{RULES_FILE} could not be read ({e}) - its rules were skipped", "warn")
        return []
    name = Path(path).name
    is_test = _looks_like_test_file(path)
    out = []
    for r in (data.get("run_gate") or []) if isinstance(data, dict) else []:
        if not isinstance(r, dict):
            continue
        pattern = r.get("files") or "*"
        if not fnmatch.fnmatch(name, pattern):
            continue
        # Rules describe the project's SCRIPTS. A test file is run by the test
        # machinery and has its own contract, so "*.py" does not reach it; a rule
        # meant for tests says so in its pattern (e.g. "test_*.py"). Measured
        # 2026-09-25: a unittest file was held to "a bare run prints imports OK".
        if is_test and "test" not in pattern.lower():
            continue
        if any(fnmatch.fnmatch(name, x) for x in (r.get("exclude") or [])):
            continue
        args = r.get("args") or []
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            continue
        out.append(r)
    return out


def _rule_failure(rule, rc, blob, how):
    """'' if the run obeyed the rule, else what ND tells the model."""
    want = rule.get("must_print")
    bad = []
    if want and want not in blob:
        bad.append(f"its output must contain {want!r} and did not")
    if "must_exit" in rule and rc != rule["must_exit"]:
        bad.append(f"it must exit with code {rule['must_exit']} and exited with {rc}")
    if not bad:
        return ""
    tail = NL.join(blob.splitlines()[-10:]) or "(no output)"
    return (f"broke a rule of this project ({RULES_FILE}) when run {how}: "
            + "; ".join(bad) + "." + NL
            + (f"Why the rule exists: {rule['why']}" + NL if rule.get("why") else "")
            + NL + "Its output was:" + NL + tail)


def run_gate_check(path, workspace, inputs):
    """Run a freshly written script. Returns a failure description, or ''."""
    try:
        if is_gui_script(path, workspace):
            ok, rep = gui_smoke_test(path, workspace, (inputs or [""])[0])
            return "" if ok else ("was click-tested and has broken buttons:" + NL + NL + rep)
    except Exception:
        pass
    py = workspace_python(workspace)
    attempts = [[py, str(path)]]
    # A script that drives something ND cannot run here (the Golf It builder
    # drives a game) is only ever run bare above -- which exercises nothing but
    # its imports. Measured 2026-09-24: a crash on its first real line passed the
    # bare run, the import check and a 47-minute verify turn. If the script
    # offers --dry-run (its real path against a fake), run that too.
    try:
        if "--dry-run" in Path(path).read_text(encoding="utf-8", errors="replace"):
            attempts.append([py, str(path), "--dry-run"])
    except OSError:
        pass
    for a in inputs[:1]:
        attempts.append([py, str(path), a])

    def _how(cmd):
        if len(cmd) < 3:
            return "with no arguments"
        if cmd[2] == "--dry-run":
            return "with --dry-run (its real path, against a fake game)"
        if cmd[2].startswith("-"):
            return "with " + " ".join(cmd[2:])
        return f"on {Path(cmd[2]).name}"

    # Project rules ride on the runs above; a rule for arguments the gate would
    # not otherwise use adds its own run.
    rules = workspace_run_rules(workspace, path)
    for r in rules:
        want = [py, str(path)] + list(r.get("args") or [])
        if want not in attempts:
            attempts.append(want)

    for i, cmd in enumerate(attempts):
        try:
            rc, out, err, timed_out = _run_capped(
                cmd, RUN_GATE_TIMEOUT,
                cwd=str(workspace) if workspace else None)
        except Exception as e:
            return f"could not be run at all: {e}"
        if timed_out:
            # A web server SHOULD still be running (polish_02: two repair steps
            # spent "fixing" server.py for staying up). Up with no traceback = pass;
            # the serve check proves it serves.
            try:
                _src = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                _src = ""
            if ("__main__" in _src and _SERVER_HINT.search(_src)
                    and not _TRACEBACK_RE.search((out or "") + chr(10) + (err or ""))):
                continue
            return ("ran for " + str(RUN_GATE_TIMEOUT) + "s without finishing and was "
                    "killed. If it waits for input or starts a server it can never "
                    "finish here.")
        blob = ((out or "") + chr(10) + (err or "")).strip()
        tb = _TRACEBACK_RE.search(blob)
        if tb:
            # The traceback IS the message. Keep the tail, which carries the
            # exception and the line that raised it.
            tail = chr(10).join(blob.splitlines()[-14:])
            return ("crashed when it was run " + _how(cmd) + ":" + chr(10)
                    + chr(10) + tail)
        for r in rules:
            if list(r.get("args") or []) == cmd[2:]:
                bad = _rule_failure(r, rc, blob, _how(cmd))
                if bad:
                    return bad
        if (len(cmd) > 2 and cmd[2] == "--dry-run" and rc != 0
                and _ARG_REJECTED_RE.search(blob)):
            # Not the fake game disagreeing with the script: the script turned
            # down its OWN --dry-run. Measured 2026-09-25: alternative.py
            # installed the fake, then fell into "if argv[1] != '--go': print
            # usage; return 1" -- 0 inputs sent, 0 screenshots, and the note
            # below let it through as "not a failure". That is a real bug.
            tail = chr(10).join(blob.splitlines()[-8:])
            return ("rejected its own --dry-run: it printed a usage/argument error "
                    "and exited with code " + str(rc) + " instead of running the --go "
                    "path against the fake game. --dry-run must be accepted "
                    "everywhere --go is (argument checks included) and then run the "
                    "same steps." + chr(10) + chr(10) + tail)
        if len(cmd) > 2 and cmd[2] == "--dry-run" and rc != 0:
            # The script ran against a FAKE game and stopped itself cleanly: one
            # of its own sanity checks tripped. That is as likely to be the fake
            # being wrong as the code. Measured 2026-09-24: a correct
            # set_location.py stopped with "nothing was selected" because the
            # fake did not yet show the panel on selection, and two repair passes
            # were spent "fixing" working code. Only a traceback (handled above)
            # is certain enough to repair. Report this, do not repair it.
            tail = chr(10).join(blob.splitlines()[-6:]) or "(no output)"
            _job_ctx.run_gate_notes = (getattr(_job_ctx, "run_gate_notes", None) or []) + [
                f"{Path(path).name} --dry-run stopped itself with code {rc}, without "
                f"crashing:{chr(10)}{tail}{chr(10)}That may be the fake game, not the "
                f"script, so it was NOT repaired. Check it before running --go."]
            continue
        if len(cmd) > 2:
            # Only judge output when we gave it something real to work on. A
            # script that rejects the argument does not take that input at all.
            if _ARG_REJECTED_RE.search(blob):
                continue
            m = _SELFREPORT_ERR_RE.search(blob)
            if m:
                return (f"ran {_how(cmd)} and reported its own failure:"
                        + chr(10) + chr(10) + m.group(0).strip() + chr(10) + chr(10)
                        + "It exited without raising, so the exit code looked fine. "
                          "It is still wrong.")
            if rc != 0:
                tail = chr(10).join(blob.splitlines()[-10:]) or "(no output)"
                return (f"exited with code {rc} when run {_how(cmd)}:"
                        + chr(10) + chr(10) + tail)
    return ""


def _run_gate_prompt(path, failure, task):
    rel = Path(path).name
    try:
        body = Path(path).read_text(encoding="utf-8", errors="replace")[:8000]
    except Exception:
        body = "(could not re-read the file)"
    return (f"{rel} does not work. You wrote it but never ran it. I ran it, and it "
            f"{failure}" + chr(10) + chr(10)
            + "Fix the actual cause. Do not rewrite the file from scratch and do not "
              "create a new file — edit this one." + chr(10) + chr(10)
            + f"The original task was:" + chr(10) + (task or "")[:900] + chr(10) + chr(10)
            + f"--- current {rel} ---" + chr(10) + body)


# ─── Traceback → the source it points at ────────────────────────────────────
_TB_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)(?:, in ([^\s]+))?')
_TB_ERR_RE = re.compile(r"^\s*([A-Za-z_][\w.]*(?:Error|Exception|Warning))\s*:\s*(.+)$", re.M)
TB_CONTEXT_BEFORE, TB_CONTEXT_AFTER = 12, 6


def _is_library_path(p):
    s = str(p).lower().replace("/", "\\")
    return ("\\lib\\" in s and "python" in s) or "site-packages" in s


def traceback_source_block(text, limit=2):
    """Numbered source around each line of the USER'S code a traceback names.

    Innermost frames first, because that is where the error was raised. Library
    frames are skipped -- tkinter\\__init__.py:1967 is where every Tk callback
    error surfaces and never where it was caused.
    """
    frames = [(f, int(n), fn) for f, n, fn in _TB_FRAME_RE.findall(text or "")]
    frames = [fr for fr in frames if not _is_library_path(fr[0])]
    if not frames:
        return ""
    err = _TB_ERR_RE.findall(text or "")
    err_line = (err[-1][0] + ": " + err[-1][1].strip()) if err else ""
    out, seen = [], set()
    for path, line, fn in reversed(frames):
        if (path.lower(), line) in seen:
            continue
        seen.add((path.lower(), line))
        try:
            src_lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        lo = max(1, line - TB_CONTEXT_BEFORE)
        hi = min(len(src_lines), line + TB_CONTEXT_AFTER)
        body = NL.join(("%s %5d  %s" % (">>" if i == line else "  ", i, src_lines[i - 1]))
                       for i in range(lo, hi + 1))
        # The imports too. A NameError or "module 'tkinter' has no attribute
        # 'filedialog'" is raised on one line and caused by a missing import on
        # another -- measured, the real fix here was line 7, not line 373.
        imps = [("   %5d  %s" % (i, t)) for i, t in enumerate(src_lines[:120], 1)
                if re.match(r"\s*(?:import|from)\s+\w", t)]
        out.append(f"--- {path}, line {line}" + (f", in {fn}" if fn else "")
                   + f" (lines {lo}-{hi} of {len(src_lines)}) ---" + NL + body
                   + ((NL + NL + "Imports at the top of this file:" + NL + NL.join(imps[:25]))
                      if imps else ""))
        if len(out) >= limit:
            break
    if not out:
        return ""
    return (NL + NL + "=" * 60 + NL
            + "THE ERROR YOU WERE GIVEN POINTS HERE. ND read these lines for you, "
              "straight from the file on disk:" + NL
            + (f"  {err_line}" + NL if err_line else "") + NL
            + (NL + NL).join(out) + NL + NL
            + "Line >> is where the error was raised. Fix THAT line (and every other "
              "place with the same mistake) with edit_file, then verify. Do not "
              "re-read the whole file first -- the part that matters is above." + NL
            + "=" * 60)


# ─── Next actions: what the user can click when a turn stops early ───────────
# The prose reports already say "ask for the next file by name". The user knows;
# what they cannot see is how many rounds are left, how many files are missing,
# or when stopping is the right call. These carry that as data the UI can render
# as buttons, and mark whether resuming is worth it.
#
# `resumable` is the auto-continue gate. It is True only for stops where the run
# was demonstrably making progress (files landed, it just lost the thread), and
# False for a loop breaker or a no-work stall -- repeating those automatically
# would burn rounds proving the same point, which is the failure the loop
# breaker exists to stop.
CONTINUE_NEXT = ("continue: move on to the NEXT file. The file you just finished is "
                 "complete and correct on disk — do not write it again. If every file "
                 "is done, say so plainly instead of writing anything.")
LIST_REMAINING = ("Do not write any code. List the files still missing to finish this "
                  "task, one per line, as workspace-relative paths, shortest first. "
                  "If nothing is missing, say 'nothing is missing'.")
VERIFY_WHAT_EXISTS = ("Do not write or edit anything. List every file in the working "
                      "directory, import each Python file, and report which ones load "
                      "cleanly and which fail, with the error for each failure.")
WRAP_UP = ("Stop building. In plain prose, tell me what exists on disk right now, what "
           "it actually does, and what is still missing. Do not write any files.")
DIFFERENT_TACK = ("That approach is not working — do not repeat it. Tell me in one "
                  "paragraph what you were trying to find out, then take a different "
                  "route to it, or stop and tell me exactly what you need from me.")


def _act(label, prompt, primary=False):
    return {"label": label, "prompt": prompt, "primary": primary}


def next_actions_for(final, session_id, written_now):
    """Structured follow-ups for a reply, or None when the turn ended cleanly.

    Keyed off the report text because that is the one thing every stop path
    already produces. Each entry is {label, prompt, primary}; the UI sends
    `prompt` as an ordinary user message when the button is clicked.
    """
    text = final or ""
    if not text.startswith("STOPPED") and "CHECKED ON DISK" not in text:
        return None
    sess = session_work_files(session_id)
    verify = _act("Verify what exists", VERIFY_WHAT_EXISTS)
    wrap = _act("I'm done — summarise", WRAP_UP)
    if "kept rewriting the same file" in text:
        kind, resumable = "rewrite-loop", True
        acts = [_act("Continue — next file", CONTINUE_NEXT, primary=True),
                _act("What's left?", LIST_REMAINING), verify, wrap]
    elif "partial work" in text:
        kind, resumable = "stalled-after-work", True
        acts = [_act("Continue — next file", CONTINUE_NEXT, primary=True),
                _act("What's left?", LIST_REMAINING), verify, wrap]
    elif "got stuck repeating one call" in text:
        # Deliberately NOT resumable: the same request produced the same loop.
        kind, resumable = "loop-breaker", False
        acts = [_act("Try a different approach", DIFFERENT_TACK, primary=True),
                verify, wrap]
    elif "same file over and over under different names" in text:
        kind, resumable = "duplicate-file-loop", False
        acts = [_act("Name the next file", "Do not write any code yet. List the "
                     "files still needed to finish this task, one per line, with "
                     "one sentence each on what it must do.", primary=True),
                verify, wrap]
    elif "CHECKED ON DISK" in text:
        kind, resumable = "ghost-write", False
        acts = [_act("Write it for real", "Use the write_file tool to create the "
                     "FIRST file you just described. Call the tool — do not print "
                     "the call as text. One file only, then stop.", primary=True),
                verify, wrap]
    elif "no actual work was performed" in text:
        kind, resumable = "no-work", False
        acts = [_act("Say it explicitly", "Use the write_file tool to create the file "
                     "you just described. Do not describe it again — call the tool.",
                     primary=True),
                _act("What's left?", LIST_REMAINING), verify, wrap]
    else:
        kind, resumable = "other", False
        acts = [_act("Continue", CONTINUE_NEXT, primary=True), verify, wrap]
    return {"kind": kind, "resumable": resumable, "actions": acts,
            "files_this_turn": len(written_now or []),
            "files_this_session": len(sess),
            "session_files": sess[-12:]}


# all_tool_calls rows are {"tool": name, "arg": summary} -- NOT {"name": ...}.
# Counting them with .get("name") returns 0 every time and fails silently, so
# the counting lives in one place with the key spelled once.
READ_ONLY_TOOLS = ("read_file", "list_dir", "search_files", "web_fetch", "web_search")
WRITE_TOOLS = ("write_file", "edit_file")

# A test file, by convention in this and most Python projects: a name that
# starts with test_ or ends _test.py, or anything under a tests/ folder. Used to
# tell "changed code" apart from "changed a test" at the finish gate.
_TEST_PATH_RE = re.compile(
    r"(?:^|[\\/])(?:test_[^\\/]*|conftest)\.py$|_test\.py$|(?:^|[\\/])tests?[\\/]",
    re.I)


def _is_test_path(p):
    return bool(p) and bool(_TEST_PATH_RE.search(str(p).replace("\\", "/")))


def code_test_state(tool_calls):
    """(changed_code, touched_test) for the turn so far. changed_code = an
    edit_file on a non-test .py (behaviour changed in existing code).
    touched_test = any write/edit of a test file. A new standalone script
    (write_file of a fresh file) and non-.py edits (HTML/CSS/docs) are NOT
    'changed_code', matching rule 10's carve-out for things that need no test."""
    changed_code = False
    touched_test = False
    for c in tool_calls or []:
        name = c.get("tool") or c.get("name")
        path = c.get("path") or ""
        if name not in WRITE_TOOLS or c.get("failed"):
            continue
        if _is_test_path(path):
            touched_test = True
        elif name == "edit_file" and str(path).lower().endswith(".py"):
            changed_code = True
    return changed_code, touched_test


def needs_test_nudge(tool_calls):
    """Should the turn be sent back to add a test? True when it changed existing
    code but touched no test file. The measured failure is skipping the test
    file (not writing bad tests), so 'was a test file touched' is the right,
    non-looping stop condition: it does NOT demand a PASSING test, because on a
    broken endpoint no test can pass and forcing one would loop forever or make
    the model fake a trivial pass. When the endpoint works, touching the file
    passes 100% of the time (measured), so this captures the achievable case."""
    changed_code, touched_test = code_test_state(tool_calls)
    return changed_code and not touched_test


# The edit gate (in the finish branch) must tell an imperative to change code
# ("Add a /stats endpoint") apart from a question about it ("how would I add
# one?"), so it fires on the first and never the second. Keyword, deliberately
# simple -- the gate also requires a real workspace, which is the stronger guard.
_BUILD_VERB_RE = re.compile(
    r'\b(add|create|build|implement|writ\w*|fix\w*|chang\w*|updat\w*|modif\w*|'
    r'refactor\w*|mak\w*|generat\w*|wir\w*|hook|remov\w*|delet\w*|renam\w*|'
    r'extend\w*|replac\w*|patch\w*|insert\w*|append\w*|integrat\w*|support|'
    r'enabl\w*|set up)\b', re.I)
_QUESTION_LEAD_RE = re.compile(
    r'^\s*(what|why|how|when|where|who|which|whose|is|are|was|were|does|do|did|'
    r'can|could|should|would|will|explain|describe|summar\w+|review|tell me|'
    r'show me|walk me|help me understand)\b', re.I)


def _wants_code_change(text):
    """True when the request is an imperative to create or change code, not a
    question about it. Used by the edit gate so it fires on 'Add a /stats
    endpoint' but not on 'how would I add one?'. A leading interrogative with no
    build verb is always read as Q&A."""
    t = (text or "").strip()
    if not t:
        return False
    first = (t.splitlines() or [t])[0]
    if _QUESTION_LEAD_RE.match(first) and not _BUILD_VERB_RE.search(first):
        return False
    return bool(_BUILD_VERB_RE.search(t))


def made_any_edit(tool_calls):
    """Did the turn write or edit ANY file? The dominant T3 miss was finishing a
    build task having called write_file/edit_file zero times (measured 107/376:
    status=done, ~18 rounds, a ~2.4k-char reply, nothing on disk)."""
    # A refused or failed write changed nothing, so it is not an edit.
    return any((r.get("tool") or r.get("name")) in WRITE_TOOLS and not r.get("failed")
               for r in tool_calls or [])


# Words that only ever appear as placeholders in an instruction template. A
# model copied `TOOL: write_file PATH|||CONTENT` verbatim and ND created a file
# NAMED "PATH" holding "CONTENT" -- then reported it as a successful write.
PLACEHOLDER_NAMES = {"PATH", "FILEPATH", "FILE_PATH", "FILENAME", "FILE", "CONTENT",
                     "CONTENTS", "YOUR_PATH", "ABSOLUTE_PATH", "FULL_PATH",
                     "PATH_TO_FILE", "OUTPUT_PATH", "TARGET", "TODO"}


# The TOOL-line template's own slot names. Measured 2026-09-24: in text mode
# qwen3-coder:30b wrote `TOOL: read_file PATH|||G:\...\set_location.py` and
# `TOOL: run_shell COMMAND|||type ...` -- the slot name, then the value -- so ND
# read a file called "PATH", listed "PATH|||G:\GolfItMapMaker" and refused writes
# to "PATH" until the job stalled. A part that IS a slot name is never a value.
TEMPLATE_SLOT_WORDS = PLACEHOLDER_NAMES | {
    "ROOT", "REGEX_PATTERN", "PATTERN", "OLD_TEXT", "NEW_TEXT", "COMMAND", "QUERY",
    "URL", "OFFSET", "LIMIT", "OPTIONAL_DESIGN_BRIEF", "BRIEF"}
_TOOL_TAG_TAIL_RE = re.compile(r"\s*</?tool_call>\s*$")


# A native tool call whose argument carries the model's own imagined next turn.
# Measured 2026-09-25, qwen3-coder:30b:
#     "limit": "100<tool_call>\n[FILE] [G:\\GolfItMapMaker\\set_location.py ..."
#     "command": "cp \"a.py\" \"b.bak\"<tool_call>\n[FILE] ..."
# The read ran with a garbage limit, and every shell command failed. Nothing
# after a <tool_call> tag is part of the argument.
_ARG_TAIL_RE = re.compile(r"\s*</?tool_call>.*\Z", re.S)
_INT_ARGS = ("offset", "limit", "x", "y", "count", "lines")


# Shell commands that change the file system. Used only to hold a one-file
# request to its one file (see scope_blocked); read-only commands are not
# matched and still go through the normal approval.
_SHELL_WRITES_RE = re.compile(
    r"(?:^|[\s;&|(])(?:cp|copy|copy-item|cpi|mv|move|move-item|mi|ren|rename|"
    r"rename-item|rni|del|erase|rm|rmdir|rd|remove-item|ri|set-content|sc|"
    r"add-content|ac|out-file|new-item|ni|mkdir|md|tee|tee-object|xcopy|robocopy|"
    r"touch|truncate)(?=\s|$)"
    r"|\bsed\s+-i\b"
    r"|\[System\.IO\.File\]::(?:Write|Copy|Move|Delete|Append)"
    r"|(?<![\d<>&=-])>>?\s*(?!&|\$null|nul\b)[^\s>&|]", re.I)


def shell_changes_files(cmd):
    """Does this shell command create, copy, move, rename, write or delete files?"""
    return bool(cmd) and bool(_SHELL_WRITES_RE.search(str(cmd)))


def salvage_bare_source(text, target):
    """A write_file call for `target` (.py) when the reply holds its full source as
    PLAIN TEXT: a line naming the file, then Python. None otherwise.

    Measured 2026-09-25: asked for build_library.py alone, qwen3-coder:30b wrote
    "G:\\...\\build_library.py" on a line and then all 500 lines of the script -
    no tool call, no code fence - twice, and 20 minutes ended with nothing written.
    The fenced-block salvage never saw it. Only used when the request is scoped to
    that one file, so the destination is not a guess. Kept strict: the file must
    be named on its own line, and the longest prefix after it that PARSES as Python
    must be substantial (>= 15 lines, >= 400 chars) and define or import something.
    Trailing prose after the code is dropped.
    """
    import ast
    if not text or not target or not str(target).lower().endswith(".py"):
        return None
    tgt = Path(str(target))
    names = {str(tgt).replace("/", "\\").lower(), tgt.name.lower()}
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        bare = ln.strip().strip("`*").strip().replace("/", "\\").lower()
        if bare.startswith("path:"):
            bare = bare[5:].strip()
        if bare not in names:
            continue
        body = lines[i + 1:]
        while body and not body[0].strip():
            body = body[1:]
        for n in range(len(body), 14, -1):
            src = "\n".join(body[:n]).rstrip() + "\n"
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            if (len(src) >= 400 and any(isinstance(node, (ast.FunctionDef, ast.ClassDef,
                                                          ast.Import, ast.ImportFrom))
                                        for node in tree.body)):
                return {"name": "write_file", "_arg": None, "_salvaged": True,
                        "arguments": {"path": str(tgt), "content": src}}
            break                       # the longest parseable prefix is too small
    return None


_READ_VERB_RE = re.compile(
    r"\b(?:let\s+me|i'?ll|i\s+will|now\s+i'?ll|next[,\s]+i'?ll|let'?s)\s+(?:\w+\s+){0,3}"
    r"(?:check|read|look\s+at|examine|inspect|open|review|see)\b", re.I)
_FILE_TOKEN_RE = re.compile(r"[A-Za-z]:[\\/][^\s`'\"<>|:*?]+\.\w{1,5}|[\w.\-\\/]+\.\w{1,5}")
_ECHO_READ_RE = re.compile(r"^\s*\[FILE\]\s*\[([^\]\n]+?)\s+\S\s+lines\s+\d", re.I | re.M)


def salvage_intended_read(text, workspace, already=()):
    """A read_file call for the existing file a no-tool-call reply was plainly about
    to READ. None otherwise.

    Measured 2026-09-26 (Golf It speed-up, qwen3-coder:30b): after one good edit the
    model spent its last five rounds on reads it never made - it TYPED the read
    result "[FILE] [G:\\GolfItMapMaker\\set_location.py - lines 1-250 of 250 ...]"
    twice, and closed on "Let me check build_hole.py for the timing changes:" -
    each answered by a nudge, and the job stopped with 5 of 6 listed changes
    undone. A read is harmless and its target is not a guess when the file exists,
    so ND makes the call the model meant, and the loop goes on.

    Two forms: a typed read result naming a path, or a CLOSING read-intent line
    ("let me check X.py") naming a file that exists (as given, or under the
    workspace). `already` = paths auto-read in this job: never the same one twice.
    """
    if not text:
        return None
    seen = {str(a).lower() for a in already}
    cands = [m.group(1).strip() for m in _ECHO_READ_RE.finditer(text)]
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    tail = " ".join(lines[-2:])
    if _READ_VERB_RE.search(tail):
        cands += [t.rstrip(".,;:)") for t in _FILE_TOKEN_RE.findall(tail)]
    for c in cands:
        for path in (Path(c), Path(str(workspace)) / c if workspace else None):
            if path is None:
                continue
            try:
                if path.is_file() and str(path).lower() not in seen:
                    return {"name": "read_file", "_arg": None, "_salvaged": True,
                            "arguments": {"path": str(path)}}
            except OSError:
                continue
    return None


def clean_tool_args(args):
    """(args, note). Cuts hallucinated <tool_call>... tails off string arguments
    and turns numeric strings into ints where an int is meant."""
    if not isinstance(args, dict):
        return args, ""
    out, fixed = {}, []
    for k, v in args.items():
        if isinstance(v, str) and "tool_call>" in v:
            v2 = _ARG_TAIL_RE.sub("", v)
            if v2 != v:
                fixed.append(k)
                v = v2
        if k in _INT_ARGS and isinstance(v, str) and v.strip().lstrip("-").isdigit():
            v = int(v.strip())
        out[k] = v
    return out, ("cut a stray <tool_call>... tail off " + ", ".join(fixed)) if fixed else ""


_BRACKET_TOOL_RE = re.compile(
    r"^[ \t]*\[(read_file|write_file|edit_file|list_dir|run_script|run_shell|"
    r"search_files|web_search|web_fetch)\][ \t]*", re.I | re.M)


def _sep_trim(part, tail=True):
    """One space either side of a ||| separator is layout, not content.

    `[WRITE_FILE] a.py ||| <docstring>...` would otherwise write a file starting
    with a space -- for Python an IndentationError on line 1. Exactly one space (or
    one newline) goes; real indentation deeper than that is kept.
    """
    s = str(part or "")
    if s[:1] in (" ", "\t"):
        s = s[1:]
    if s[:1] == "\n":
        s = s[1:]
    if tail and s[-1:] in (" ", "\t"):
        s = s[:-1]
    return s


def _strip_template_words(arg):
    """Drop template slot names (exact, upper case) from a TOOL-line argument,
    and a stray <tool_call> tag glued to its end."""
    parts = arg.split("|||")
    kept = [x for x in parts if x.strip() not in TEMPLATE_SLOT_WORDS]
    if not kept or len(kept) == len(parts):
        out = arg
    else:
        out = "|||".join(kept)
        if len(parts[0]) and parts[0].strip() in TEMPLATE_SLOT_WORDS:
            out = out.lstrip()
    return _TOOL_TAG_TAIL_RE.sub("", out)


def _count_calls(rows, names):
    return sum(1 for r in rows or [] if (r.get("tool") or r.get("name")) in names)


_PATHY = r'(?:[A-Za-z]:[\\/][^\s,;"\'<>|]*|\\\\[^\s,;"\'<>|]+)'
# Ordered by how strongly each phrase means "this is where output goes".
_WS_PATTERNS = [
    re.compile(r'working\s+director(?:y|ies)\s*[:\-]?\s*(' + _PATHY + ')', re.I),
    re.compile(r'\b(?:create|build|write|put|save|output|generate|place)\b[^.\n]{0,60}?'
               r'\b(?:in|into|inside|to|under|at)\s+(' + _PATHY + ')', re.I),
    re.compile(r'\b(?:in|into|inside)\s+(' + _PATHY + ')', re.I),
]


# ─── Session context ──────────────────────────────────────────────────────────
# Everything that shapes a request -- workspace, house style, design brief -- was
# derived from the LATEST user message. So the moment the user typed "ok" or
# "continue - write the next file", all of it switched off at once: no UI
# keywords meant no house style, no build phrasing meant no auto-split, no path
# meant no workspace and therefore no write confinement. Measured: the turn with
# the real prompt did 6 reads and 0 writes, and every file was actually produced
# on the bare "ok" and "continue" turns -- with no brief and no rules.
#
# A nudge is a continuation of the task, not a new one. Remember the task.
_CONTINUATION_RE = re.compile(
    r"^\s*(?:ok(?:ay)?|yes|y|sure|go|continue|carry on|proceed|next|keep going|"
    r"go ahead|do it|resume|please continue|try (?:it )?ag(?:ai|i|a)n|retry|redo|"
    r"again|one more time)\b[\s.!,-]*", re.I)


# Words that turn "ok" into a NEW instruction rather than a nudge.
_REDIRECT_RE = re.compile(
    r"\b(?:but|instead|except|however|actually|change|add|remove|make|use|"
    r"try|also|rather|without|don'?t|stop|skip|redo|revert)\b", re.I)


_FOLLOWUP_RE = re.compile(
    r"^\s*(?:please\s+)?(?:continue|carry on|keep going|keep working|resume|proceed|"
    r"go on|finish (?:it|up|the rest|everything|what)|pick up where)\b", re.I)


def is_followup(text):
    """The user is carrying on with the SAME task, whatever detail follows:
    "Continue. Finish everything in SPEC.md, then run the tests." Looser than
    is_continuation (which also decides whether to re-inject the original task)."""
    return bool(is_continuation(text) or _FOLLOWUP_RE.match(text or ""))


def is_continuation(text):
    """A bare nudge that carries no task detail of its own.

    Must be strict in BOTH directions. Too loose and 'ok but make the header
    blue instead' gets treated as a bare nudge, so the original task is pushed
    back in front of the model and the user's actual correction competes with
    it. Too tight and 'continue' loses the task entirely, which is the bug this
    exists to fix.
    """
    t = (text or "").strip()
    if not t or len(t) > 120:
        return False
    m = _CONTINUATION_RE.match(t)
    if not m:
        return False
    rest = t[m.end():].strip(" .!,-\"'")
    if not rest:
        return True
    # Anything with real instruction in it is a new request, not a nudge.
    if _REDIRECT_RE.search(rest):
        return False
    return len(rest.split()) <= 6


# Session context lives in _session_work, which is a plain in-memory dict. That
# is fine for a ledger of files touched -- losing it costs a little redundant
# work. It is NOT fine for a question ND is waiting on an answer to.
#
# Measured, from a user who restarts ND between every attempt:
#
#   1. "RESKIN TASK ..."  -> ND asks "Which model should handle this?" and
#      stashes await_model + the task IN MEMORY.
#   2. ND restarts.        -> the stash is gone.
#   3. "1"                 -> nothing is pending any more, so the bare digit is
#      treated as a brand-new instruction and handed to the model as the job.
#   4. Nothing happens, so the task is sent again, and ND asks again. A loop
#      with no work in it, and no restart is needed to keep it going.
#
# Only the keys that a pending question depends on are persisted. The file is
# tiny, best-effort, and never allowed to break a request.
_CTX_FILE = _CONFIG_DIR / "nd_session_ctx.json"
_CTX_PERSIST = ("await_model", "task", "workspace", "reskin_src",
                "reskin_as_edit", "model_ui", "model_code", "model_research",
                "plan")
_CTX_MAX_SESSIONS = 40


# Stale state is worse than no state. Without an expiry, a task stashed days
# ago is silently restored into an unrelated conversation that happens to reuse
# the session id -- the sort of thing that surfaces as a mystery weeks later.
# The file only has to survive a restart, so a short life is the right life.
_CTX_TTL_SECONDS = 12 * 3600


def _ctx_disk_load():
    try:
        blob = json.loads(_CTX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(blob, dict):
        return {}
    now = time.time()
    return {k: v for k, v in blob.items()
            if isinstance(v, dict)
            and now - float(v.get("_ts") or 0) < _CTX_TTL_SECONDS}


def _ctx_disk_save(sid, ctx):
    try:
        keep = {k: v for k, v in ctx.items() if k in _CTX_PERSIST and v}
        blob = _ctx_disk_load()
        if keep:
            keep["_ts"] = time.time()
            blob[sid] = keep
        else:
            blob.pop(sid, None)
        # Oldest-first trim; dicts preserve insertion order.
        while len(blob) > _CTX_MAX_SESSIONS:
            blob.pop(next(iter(blob)))
        _CTX_FILE.write_text(json.dumps(blob), encoding="utf-8")
    except Exception as e:
        log(f"Could not persist session context: {e}", "warn")


def remember_ctx(sid, **kw):
    if not sid:
        return
    with _lock:
        w = _session_work.setdefault(sid, {"files": {}, "actions": []})
        ctx = w.setdefault("ctx", {})
        for k, v in kw.items():
            # An empty value NEVER overwrites a known one. remember_ctx is
            # called from several places with partially-filled values, and a
            # blank workspace or task arriving from one of them must not erase
            # what another already established. Use forget_ctx() to clear.
            if v:
                ctx[k] = v
        touched = any(k in _CTX_PERSIST and v for k, v in kw.items())
        snapshot = dict(ctx)
    if touched:
        _ctx_disk_save(sid, snapshot)


def forget_ctx(sid, *keys):
    """Explicitly clear context keys, in memory and on disk.

    Needed because remember_ctx() deliberately ignores empty values, so
    `remember_ctx(sid, await_model="")` cannot mark a question answered -- and
    an await_model left on disk means the NEXT bare number gets read as an
    answer to a question that was already dealt with.
    """
    if not sid or not keys:
        return
    with _lock:
        ctx = ((_session_work.get(sid) or {}).get("ctx") or {})
        for k in keys:
            ctx.pop(k, None)
        snapshot = dict(ctx)
    if any(k in _CTX_PERSIST for k in keys):
        _ctx_disk_save(sid, snapshot)


def recall_ctx(sid, key, default=""):
    if not sid:
        return default
    with _lock:
        w = _session_work.get(sid)
        ctx = (w or {}).get("ctx") or {}
        if key in ctx:
            return ctx[key]
        if key not in _CTX_PERSIST:
            return default
    # Not in memory and it is a key that survives restarts -- this is the first
    # touch since ND came back up. Rehydrate from disk.
    saved = (_ctx_disk_load().get(sid) or {})
    if not saved:
        return default
    with _lock:
        w = _session_work.setdefault(sid, {"files": {}, "actions": []})
        ctx = w.setdefault("ctx", {})
        for k, v in saved.items():
            if k != "_ts":          # bookkeeping, not context
                ctx.setdefault(k, v)
        return ctx.get(key, default)


# --- The model's own plan -----------------------------------------------------
# Bounded on purpose. This is re-sent on EVERY round, so an unbounded plan is an
# unbounded tax on the smallest windows -- and a model that needs more than ten
# steps has not understood the task well enough for a longer list to help.
PLAN_MAX_STEPS = 10
PLAN_MAX_CHARS = 90
PLAN_STATUS = ("todo", "doing", "done")
_PLAN_MARK = {"todo": "[ ]", "doing": "[>]", "done": "[x]"}


def plan_normalise(steps):
    """Clean whatever the model passed into a bounded list of steps.

    Accepts the documented [{"step":..., "status":...}] and also a bare list of
    strings, because a model that has just been told to keep a plan will send one
    of those about a third of the time and refusing it teaches it nothing.
    """
    out = []
    if isinstance(steps, str):
        steps = [l.strip(" -*\t") for l in steps.splitlines() if l.strip()]
    if not isinstance(steps, (list, tuple)):
        return out
    for raw in steps:
        if isinstance(raw, str):
            text, status = raw, "todo"
        elif isinstance(raw, dict):
            text = str(raw.get("step") or raw.get("text") or raw.get("title") or "").strip()
            status = str(raw.get("status") or "todo").strip().lower()
        else:
            continue
        text = " ".join(str(text).split())
        if not text:
            continue
        if status not in PLAN_STATUS:
            # "in_progress", "wip", "pending", "complete" all turn up.
            status = ("done" if status.startswith(("done", "complet", "finish"))
                      else "doing" if status.startswith(("doing", "in", "wip", "active", "current"))
                      else "todo")
        out.append({"step": text[:PLAN_MAX_CHARS], "status": status})
        if len(out) >= PLAN_MAX_STEPS:
            break
    return out


def plan_render(plan, header=True):
    """The plan as the model will see it."""
    plan = plan or []
    if not plan:
        return ""
    body = "\n".join(f"  {_PLAN_MARK[s['status']]} {s['step']}" for s in plan)
    if not header:
        return body
    # No open-step count. It used to print "(N step(s) still open)" every round,
    # which is a standing "you are not finished yet" to a model that cannot
    # relieve it -- measured on a seeded plan the model never updated, the same
    # task went from 9 rounds to 20 and still answered wrongly. The plan is here
    # for orientation, not as a completion gate; the round budget is the gate.
    done = sum(1 for s in plan if s["status"] == "done")
    tail = ("\n  Every step is marked done. If that is true, give your final answer now.\n"
            if done == len(plan) else
            "\n  Mark a step done with update_plan when you finish it. Do not re-plan "
            "otherwise, and do not let the plan stop you answering once you have enough.\n")
    return "\n\nYOUR PLAN for this task:\n" + body + tail


def plan_block(sid):
    """The plan for this conversation, ready to append to the system prompt."""
    if not sid:
        return ""
    return plan_render(recall_ctx(sid, "plan", []) or [])


def tool_update_plan(sid, steps):
    """Store the model's plan and hand it straight back so it can see it landed."""
    plan = plan_normalise(steps)
    if not plan:
        return ("[plan] Nothing usable in that call. Pass steps as a list, e.g. "
                '[{"step": "read the page", "status": "done"}, '
                '{"step": "write the theme", "status": "doing"}].')
    if not sid:
        # No session to hang it on. Say so rather than silently dropping it --
        # a plan that vanishes is worse than no plan, because the model then
        # believes it has one.
        return "[plan] Recorded for this round only (no session id), so it will not persist:\n" \
               + plan_render(plan, header=False)
    remember_ctx(sid, plan=plan)
    done = sum(1 for s in plan if s["status"] == "done")
    return (f"[plan] Updated — {done}/{len(plan)} done.\n" + plan_render(plan, header=False)
            + "\n\nNow do the next open step. Do not call update_plan again until "
              "something has actually changed.")


# --- Is this worth planning? --------------------------------------------------
# Narrow on purpose, exactly like looks_like_build. A false positive costs one
# wasted planning call (1.1s on frontend-design-expert-8b, 8.6s on
# qwen3coder-q3xl); a false negative just leaves ND behaving as it did.
_STEP_SEQ_RE = re.compile(
    r"\b(?:then|after that|afterwards|next,|finally|followed by|once that|"
    r"and then|lastly|secondly|thirdly)\b", re.I)
_STEP_FIRST_RE = re.compile(r"\bfirst\b", re.I)
_STEP_EXPLICIT_RE = re.compile(
    r"\b(?:step[- ]by[- ]step|in order|each step|one at a time|these steps|"
    r"in sequence|a few steps|several steps|multi[- ]step|do all of this)\b", re.I)
_STEP_NUMBERED_RE = re.compile(r"(?:^|\n)\s*\d[.)]\s+\S", re.M)


def looks_multi_step(text):
    """Is this a request that would actually benefit from a written plan?"""
    t = (text or "").strip()
    if len(t) < 40:
        return False
    if len(_STEP_NUMBERED_RE.findall(t)) >= 2:
        return True
    if _STEP_EXPLICIT_RE.search(t):
        return True
    seq = len(_STEP_SEQ_RE.findall(t))
    if seq >= 2:
        return True
    # One sequencing word is weak on its own -- "read it then tell me" is a
    # single step with a comma. Paired with "first" it is a real sequence.
    return seq >= 1 and bool(_STEP_FIRST_RE.search(t))


PLAN_SEED_PROMPT = (
    "Break the task below into an ordered list of at most {n} short steps.\n"
    "Reply with ONLY a JSON array, no prose, no code fence. Each item:\n"
    '  {{"step": "<a few words>", "status": "todo"}}\n\n'
    "TASK:\n{task}")


_PLAN_LIST_LINE_RE = re.compile(r"\s*(?:[-*•]|\d+[.)])\s+\S")


def parse_plan_reply(raw):
    """Pull a step list out of whatever the model sent back."""
    if not raw:
        return []
    m = re.search(r"\[.*\]", raw, re.S)
    if m:
        try:
            return plan_normalise(json.loads(m.group(0)))
        except Exception:
            pass
    # No JSON. A model that ignores "reply with JSON" still usually answers with
    # a LIST, so read one rather than throwing the call away -- but only from
    # lines that were actually list items, and only if there are at least two.
    # Accepting bare prose turned "I would rather not." into a one-step plan,
    # which is worse than no plan: the model is then shown a plan it never made
    # and told to work through it.
    items = []
    for line in raw.splitlines():
        if not _PLAN_LIST_LINE_RE.match(line):
            continue
        t = line.strip(" -*•\t0123456789.)")
        if 3 < len(t) <= PLAN_MAX_CHARS:
            items.append(t)
    return plan_normalise(items) if len(items) >= 2 else []


def seed_plan(model, task, session_id, req_id=None, timeout=240):
    """Ask the model for a step list up front. Returns the plan, or []."""
    if not session_id or not task:
        return []
    t0 = time.time()
    try:
        raw = ollama_chat(model, [{"role": "user", "content":
                                   PLAN_SEED_PROMPT.format(n=PLAN_MAX_STEPS, task=task[:4000])}],
                          timeout=timeout, clean=False)
    except Exception as e:
        log(f"Plan seeding failed ({e}) — carrying on without one", "warn")
        return []
    plan = parse_plan_reply(raw)
    dt = round(time.time() - t0, 1)
    if not plan:
        log(f"Plan seeding produced nothing usable in {dt}s — carrying on without one", "warn")
        return []
    remember_ctx(session_id, plan=plan)
    log(f"Seeded a {len(plan)}-step plan in {dt}s", "ok")
    agent_activity(req_id, "plan", f"{len(plan)}-step plan",
                   plan[0]["step"][:70], ok=True, secs=dt)
    return plan


def infer_workspace(text):
    """Work out where output should go when the UI supplied no workspace.

    ND takes `workspace` from the request body and the UI sends "". Everything
    gated on it was therefore inert: write confinement AND auto-split. A run
    told 'create the files in G:\\TMP\\TMP' wrote into the user's ORIGINAL app
    folder instead, because nothing knew what the working directory was.

    The user states it in plain English every time, so read it from there.
    """
    if not text:
        return ""
    for pat in _WS_PATTERNS:
        for m in pat.finditer(text):
            cand = m.group(1).rstrip('.,;:)"\'').rstrip("\\/")
            if not cand:
                continue
            try:
                p = Path(cand)
                # A FILE is the source being studied, not the destination. The
                # same prompt names both, and picking the source would point
                # output straight at the user's existing app.
                if p.is_file() or p.suffix:
                    continue
                if p.is_dir() or (p.parent.exists() and p.parent != p):
                    return str(p)
            except OSError:
                continue
    return ""


# Two or more escapes and not a single real newline. A genuine file that
# mentions "\\n" in a string does not look like this; an escaped one always does.
_ESCAPED_NL_RE = re.compile(r"\\n")


def looks_escaped(text) -> bool:
    """Did the model write \\n instead of pressing return?"""
    if not isinstance(text, str) or "\n" in text:
        return False                      # it has real newlines; believe them
    return len(_ESCAPED_NL_RE.findall(text)) >= 2


def unescape_content(text):
    """Turn a JSON-escaped blob back into the file the model meant.

    Only ever called when looks_escaped() is certain. Handles the escapes that
    actually turn up in this failure -- newline, tab, carriage return, and the
    quotes and backslashes that come with them.
    """
    if not isinstance(text, str):
        return text
    out = (text.replace("\\r\\n", "\n").replace("\\n", "\n")
               .replace("\\t", "\t").replace("\\r", "\r")
               .replace('\\"', '"').replace("\\'", "'"))
    # A doubled backslash was almost certainly meant as one. Do this LAST so it
    # cannot manufacture an escape the model never wrote.
    return out.replace("\\\\", "\\")


_write_redirects = {}     # req_id -> [(asked, actual), ...] for the final report


def user_named_path(target, user_text):
    """True if the user's own message names this file or its folder.

    Compared with separators normalised and doubled backslashes collapsed,
    because the same path reaches here as G:\\a\\b from a JSON argument and as
    G:\a\b from the user's prose.
    """
    if not target or not user_text:
        return False
    def norm(s):
        return str(s).replace("/", chr(92)).replace(chr(92) * 2, chr(92)).lower()
    u = norm(user_text)
    if norm(target) in u:
        return True
    parent = norm(Path(target).parent)
    # len > 3 so a bare drive root ("g:\") never counts as naming a folder.
    return len(parent) > 3 and parent in u


def repair_write_args(a, workspace, user_text=""):
    """Last line of defence on a write, whatever produced it. See also
    unpack_kv_args(), which runs first and handles the KEY="value" shape.

    Every earlier guard lived in the TEXT parsers, so a bad call that arrived as
    a NATIVE Ollama tool_call walked straight past all of them. Observed in one
    run: path = '{"path": "G:\\\\TMP\\\\TMP\\\\x.html", "content": "<!DOCTYPE...'
    -- the whole JSON object stuffed into the path field. Every write funnels
    through here, so this is the one place that cannot be bypassed.

    Returns (path, content, note) or (None, None, error_string).
    """
    if looks_escaped(a.get("content")):
        a = dict(a)
        a["content"] = unescape_content(a["content"])
        log("write_file content arrived with literal \\n instead of newlines "
            "— unescaped it", "warn")
    path = str(a.get("path") or "").strip().strip('"').strip("'")
    content = a.get("content", "")
    notes = []

    # 1. Path that is actually a JSON object. Recover the real values rather
    #    than dropping the call -- the model's intent is perfectly readable.
    if path[:1] in "{[":
        try:
            obj = json.loads(path)
        except Exception:
            m = re.search(r'"path"\s*:\s*"((?:[^"\\]|\\.)*)"', path)
            obj = {"path": m.group(1).encode().decode("unicode_escape")} if m else None
            if obj:
                c = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', path)
                if c:
                    try:
                        obj["content"] = json.loads('"' + c.group(1) + '"')
                    except Exception:
                        pass
        if isinstance(obj, dict) and obj.get("path"):
            path = str(obj["path"]).strip()
            if not str(content).strip() and obj.get("content"):
                content = obj["content"]
            notes.append("recovered the real path from a JSON blob in the `path` field")
        else:
            return (None, None,
                    "[ERROR write_file: the `path` argument was a JSON object, not a path, and "
                    "no usable path could be recovered from it. Send `path` as a plain string "
                    "and `content` as a separate argument.]")

    if not path:
        return (None, None,
                "[ERROR write_file: no `path` argument. Re-send with an absolute path, e.g. "
                r'{"path": "G:\\TMP\\TMP\\index.html", "content": "..."}]')

    # 2. A placeholder copied out of an instruction template.
    if path.strip("<>[]{}").upper() in PLACEHOLDER_NAMES:
        return (None, None,
                f"[ERROR write_file: '{path}' is a placeholder from the instructions, not a "
                "real path. Use the ACTUAL absolute path you want to create.]")

    if not str(content).strip():
        if notes:
            # We recovered a path out of a JSON blob but there was no content in
            # it: the classic signature of a reply cut off by the output cap
            # mid-`content`. Say that, because "content was empty" sends the
            # model looking for the wrong bug.
            return (None, None,
                    f"[ERROR write_file: your tool call was CUT OFF partway through — the path "
                    f"({path}) arrived but the file content did not. The file you are trying to "
                    "write is too long for one reply. Write a SHORTER version now — structure "
                    "only, less seeded data — then extend it with edit_file.]")
        return (None, None,
                f"[ERROR write_file: `content` was empty for {path}. Nothing was written.]")

    # 3. Confine NEW files to the workspace the user gave. One run scattered
    #    output into G:\TMP (one folder from the user's original app, same
    #    filename) and tried C:\Users\...\Documents, while the workspace sat
    #    empty. Keep the filename, move it home.
    p = Path(path)
    if workspace and _config.get("agent_confine_writes", True):
        try:
            ws = Path(workspace).resolve()
            target = (ws / p) if not p.is_absolute() else p.resolve()
            if ws not in target.parents and target != ws:
                if user_named_path(target, user_text):
                    # The user typed this destination. That outranks the
                    # confinement heuristic, which exists to catch a path the
                    # MODEL invented.
                    notes.append(f"kept outside the working directory because you "
                                 f"asked for {target}")
                else:
                    notes.append(f"REDIRECTED: you asked for {target}, but writes are "
                                 f"confined to the working directory, so it went to "
                                 f"{ws / p.name} instead")
                    target = ws / p.name
            p = target
        except OSError:
            pass
    elif not p.is_absolute() and workspace:
        p = Path(workspace) / p

    # write_file over an EXISTING, much bigger file is the same accident the
    # edit_file shrink guard catches, arriving through the other door. Measured
    # on the LeninShop benchmark: told to add one schema, the model called
    # write_file on app/schemas.py and replaced 432 lines with 32, deleting
    # ItemCreate and taking two test suites down with it. The tool description
    # already says to use edit_file for existing files; nothing enforced it.
    if p.is_dir():
        return (None, None,
                f"[WRITE REFUSED] {p} is a FOLDER, not a file. Nothing was "
                f"written. Name a file inside it, or use list_dir to see what "
                f"is already there.")
    try:
        if p.is_file() and content is not None:
            old_lines = p.read_text(encoding="utf-8", errors="replace").count("\n") + 1
            new_lines = str(content).count("\n") + 1
            if old_lines >= EDIT_MIN_LINES and new_lines < old_lines * (1 - EDIT_MAX_SHRINK):
                return (None, None,
                        f"[WRITE REFUSED] {p.name} already exists with {old_lines} lines, and "
                        f"this would replace it with {new_lines}, losing "
                        f"{old_lines - new_lines}. Nothing was written.\n\n"
                        "write_file is for NEW files. To add something to a file that already "
                        "exists, use edit_file with a small unique anchor near where it belongs. "
                        "If you genuinely mean to replace the whole file, say so in your reply "
                        "and explain why first.")
    except OSError:
        pass

    # The shrink guard only sees size. A rewrite that keeps the line count can
    # still delete half the module's public surface -- measured on T4, where
    # +205/-202 destroyed barcode_variants and took 191 tests with it. Ask the
    # question size cannot answer: does anything else still need what this
    # deletes?
    try:
        if p.is_file() and content is not None and p.suffix.lower() == ".py":
            pm = placement_mod()
            if pm:
                old_src = p.read_text(encoding="utf-8", errors="replace")
                broken = pm.broken_dependents(str(p), old_src, str(content), workspace)
                if broken:
                    return (None, None, pm.rewrite_refusal(str(p), broken))
    except Exception:
        pass

    return (str(p), content, "; ".join(notes))


# ─── Tool calls written as function calls ────────────────────────────────────
# A fifth call shape, measured on qwen3-coder:30b: the model writes the call as
# Python/JS source inside a fence, with the file body as a backtick string.
# Nothing in ND ever showed it that syntax -- it invented it, consistently, for
# eight calls in a row. The intent is unambiguous, so recover it rather than
# throw away five finished documents.
_FUNCALL_POS = {
    "write_file":      ("path", "content"),
    "edit_file":       ("path", "old_text", "new_text"),
    "read_file":       ("path", "offset", "limit"),
    "list_dir":        ("path",),
    "run_script":      ("path",),
    "run_shell":       ("command",),
    "search_files":    ("root", "pattern"),
    "web_fetch":       ("url",),
    "web_search":      ("query",),
    "find_definition": ("name",),
    "find_references": ("name",),
    "design_review":   ("path", "brief"),
}
# (?<![\w.]) so `self.read_file(` or `my_write_file(` is not a tool call.
_FUNCALL_RE = re.compile(r"(?<![\w.])(" + "|".join(_FUNCALL_POS) + r")\s*\(")
_KWARG_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(.*)$", re.S)


def _funcall_split(text, i):
    """Split an argument list starting just after '(' into raw top-level args.

    Returns (args, index_of_closing_paren) or None if unbalanced. String-aware
    for ", ' and ` -- a file body full of commas, brackets and newlines is the
    normal case here, not the exception.
    """
    args, buf, depth, n = [], [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'`":
            q = ch
            buf.append(ch)
            i += 1
            while i < n:
                c = text[i]
                if c == "\\" and i + 1 < n:
                    buf.append(text[i:i + 2]); i += 2; continue
                buf.append(c); i += 1
                if c == q:
                    break
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if ch == ")" and depth == 0:
                args.append("".join(buf))
                return args, i
            depth -= 1
        elif ch == "," and depth == 0:
            args.append("".join(buf)); buf = []; i += 1
            continue
        buf.append(ch)
        i += 1
    return None


def _funcall_unquote(s):
    """Strip one layer of quoting and undo the escapes a model actually writes."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'`":
        body, q = s[1:-1], s[0]
        if q != "`":
            # Targeted, not unicode_escape: that mangles every non-ASCII
            # character in a document body to get one backslash right.
            body = (body.replace("\\\\", "\x00ND\x00").replace("\\n", "\n")
                        .replace("\\t", "\t").replace("\\r", "\r")
                        .replace('\\"', '"').replace("\\'", "'")
                        .replace("\x00ND\x00", "\\"))
        return body
    return s


def parse_funcall_calls(text, known=None):
    """Tool calls written as source, e.g. write_file("p", `body`). Last resort."""
    if not text or "(" not in text:
        return []
    out = []
    for m in _FUNCALL_RE.finditer(text):
        name = m.group(1)
        if known is not None and name not in known:
            continue
        got = _funcall_split(text, m.end())
        if not got:
            continue
        raw, _end = got
        names = _FUNCALL_POS[name]
        a, pos = {}, 0
        for item in raw:
            km = _KWARG_RE.match(item)
            # Only treat it as a keyword when the key is a real argument name --
            # `write_file(path, x == y)` must not become {"x": ...}.
            if km and km.group(1) in names:
                a[km.group(1)] = _funcall_unquote(km.group(2))
                continue
            if pos < len(names):
                a[names[pos]] = _funcall_unquote(item)
            pos += 1
        first = names[0]
        if not str(a.get(first) or "").strip():
            continue                      # no target: it was prose about a tool
        if name in ("write_file", "edit_file") and not str(a.get(names[1]) or "").strip():
            continue                      # a write with no body is a mention
        out.append({"name": name, "arguments": a, "_arg": None})
    return out


# ─── Did the reply claim a write that is not on disk? ────────────────────────
# The backstop for every call syntax ND does not parse, including the next one a
# model invents. It does not infer intent: it takes the absolute paths the reply
# says it wrote and stats them. A path that is not on disk was not written,
# whatever the prose says.
_CLAIMED_PATH_RE = re.compile(
    r"""["'`(\[]?\s*([A-Za-z]:[\\/][^"'`)\]\n,]{3,200}?\.[A-Za-z0-9]{1,6})\s*["'`)\]]?""")
_WRITE_CTX_RE = re.compile(
    r"\b(?:write_file|edit_file|creat\w*|wrote|writ\w*|sav\w*|add\w*|generat\w*|"
    r"updat\w*|new file|note)\b", re.I)


def unverified_write_claims(text, limit=8):
    """Absolute file paths the reply claims to have written that do not exist."""
    if not text:
        return []
    missing, seen = [], set()
    for m in _CLAIMED_PATH_RE.finditer(text):
        p = m.group(1).strip().rstrip(".,;:")
        # The source text is escaped ("G:\\\\dir\\\\f.md"), so collapse doubled
        # separators before showing the path to a human. Windows stats either
        # form identically, so this is presentation only.
        p = p.replace("\\\\", "\\").replace("//", "/")
        if p.lower() in seen:
            continue
        # Only a path named in a write-ish sentence. A path the model merely
        # READ from, or one in a quoted error, is not a claim.
        lead = text[max(0, m.start() - 160):m.start()]
        if not _WRITE_CTX_RE.search(lead):
            continue
        seen.add(p.lower())
        try:
            if not Path(p).exists():
                missing.append(p)
        except Exception:
            continue
        if len(missing) >= limit:
            break
    return missing


# Argument names ND actually has. A blob is only unpacked if the keys in it are
# real -- otherwise ordinary prose containing SHOUTED="quotes" would be treated
# as a tool call's arguments.
_KV_ARG_NAMES = {"path", "content", "old_text", "new_text", "brief", "source",
                 "root", "pattern", "url", "query", "offset", "limit", "command",
                 "prompt", "text"}
_KV_PAIR_RE = re.compile(r'\b([A-Z][A-Z_]{2,19})\s*=\s*"((?:[^"\\]|\\.)*)"', re.S)


def unpack_kv_args(a):
    """Recover arguments a model wrote as PATH="..." CONTENT="..." in ONE field.

    A fifth malformed-call shape, measured on frontend-design-expert-8b:

        write_file(path='PATH="G:\\TMP\\retro-vault\\retro-vault-neon.html"
                         CONTENT="<html lang=..."')

    -- the entire argument list crammed into `path` as a shell-ish key=value
    string, with `content` left empty. ND rejected it correctly ("`content` was
    empty") and the run then spent every remaining round failing the same way:
    the bad path flowed into edit_file ("File not found") and design_review
    ("design_review failed") too.

    Nothing in ND ever showed the model that syntax -- it invented it. But the
    intent is perfectly readable, exactly like the JSON-blob case
    repair_write_args already recovers, so recover it rather than burn the run.

    Deliberately narrow: at least two pairs, keys must be real argument names,
    and an argument that already has a usable value is never overwritten.
    """
    if not isinstance(a, dict):
        return a, ""
    for field, val in list(a.items()):
        if not isinstance(val, str) or '="' not in val:
            continue
        pairs = _KV_PAIR_RE.findall(val)
        keys = [k.lower() for k, _ in pairs]
        # Two or more pairs, all of them real names, and the blob must START
        # with one -- prose that merely CONTAINS a quoted assignment is not a
        # mangled tool call.
        if len(pairs) < 2 or not all(k in _KV_ARG_NAMES for k in keys):
            continue
        if not val.lstrip().upper().startswith(pairs[0][0]):
            continue
        out = dict(a)
        for k, v in pairs:
            k = k.lower()
            try:
                v = v.encode("utf-8").decode("unicode_escape")
            except Exception:
                pass
            if not str(out.get(k) or "").strip() or k == field:
                out[k] = v
        return out, (f"recovered {', '.join(sorted(set(keys)))} from a "
                     f"KEY=\"value\" blob in the `{field}` field")
    return a, ""


def _path_key(p):
    """One canonical key per file. G:/TMP/a.bat, G:\\TMP\\a.bat and g:\\tmp\\A.BAT
    are the same file; keyed by the raw lowercased string they were three
    different counters, so a per-file limit counted far too slowly."""
    s = str(p or "").strip().strip('"').strip("'")
    if not s:
        return ""
    try:
        return str(Path(s).resolve()).lower()
    except OSError:
        return s.replace("/", "\\").lower()


def note_rewrite(sid, path):
    """Count writes per file ACROSS turns. Held on the session, not in a local:
    the counter used to live in process_ai_response_with_tools, so every time the
    user typed 'continue' it reset to zero and a model could rewrite one file
    indefinitely, three at a time, forever."""
    k = _path_key(path)
    if not k:
        return 0
    with _lock:
        w = _session_work.setdefault(sid or "_nosession", {"files": {}, "actions": []})
        rw = w.setdefault("rewrites", {})
        rw[k] = rw.get(k, 0) + 1
        return rw[k]


def note_rewrite_body(sid, path, content):
    """Count writes of identical CONTENT, whatever they are named.

    The path counter is blind to a model that increments the filename. This one
    is blind to a model that edits the same file repeatedly with real changes --
    which is legitimate. Together they cover both, and neither fires on the
    other's honest case.
    """
    body = str(content or "").strip()
    if len(body) < 120:
        return "", 0          # a stub or a one-liner repeated is not a loop
    h = hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()[:16]
    with _lock:
        w = _session_work.setdefault(sid or "_nosession", {"files": {}, "actions": []})
        rb = w.setdefault("rewrite_bodies", {})
        rec = rb.setdefault(h, {"n": 0, "names": []})
        rec["n"] += 1
        nm = Path(str(path)).name
        if nm not in rec["names"]:
            rec["names"].append(nm)
        return ", ".join(rec["names"][:6]), rec["n"]


def hottest_rewrite(sid):
    with _lock:
        rw = (_session_work.get(sid or "_nosession") or {}).get("rewrites") or {}
        if not rw:
            return "", 0
        k = max(rw, key=rw.get)
        return k, rw[k]


def clear_rewrites(sid):
    with _lock:
        w = _session_work.get(sid or "_nosession")
        if w:
            w.pop("rewrites", None)
        w.pop("rewrite_bodies", None)


def _unreviewed_pages(sid):
    """HTML pages written this session that are not finished yet.

    'Finished' means design_review has actually run on the file AND it reports
    no error-level findings and no missing interaction states. Measured: a run
    wrote a page, reviewed it once, was told seven states were missing, and
    replied 'no further changes are needed'.
    """
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from nd_design_review import state_checks, dead_assets, static_checks
    except Exception as e:
        # Returning [] here means "everything is finished", which silently
        # switches the whole iteration gate off. Say so instead of pretending.
        log(f"Design iteration disabled — nd_design_review unavailable: {e}", "warn")
        return []
    out = []
    with _lock:
        w = _session_work.get(sid or "_nosession") or {}
        reviewed = (w.get("ctx") or {}).get("reviewed") or {}
        if isinstance(reviewed, list):          # pre-stamp sessions
            reviewed = {k: {"stamp": "", "contrast": ""} for k in reviewed}
        pages = list((w.get("ctx") or {}).get("pages") or [])
    for p in pages:
        fp = Path(p)
        if not fp.is_file():
            continue
        key = str(fp.resolve()).lower()
        rec = reviewed.get(key)
        if rec is None:
            out.append((str(fp), "it has been written but never rendered, so nobody has "
                                 "seen what it looks like."))
            continue
        # Reviewed, then edited. The review that passed described a file that no
        # longer exists, so it proves nothing about this one.
        stamp = _page_stamp(fp)
        if rec.get("stamp") and stamp and stamp != rec["stamp"]:
            out.append((str(fp), "it was changed after it was last reviewed, so the "
                                 "current version has not been seen. Run design_review "
                                 "on it again."))
            continue
        try:
            html = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        errs = [f for f in dead_assets(html, fp.parent) + static_checks(html)
                if f["level"] == "error"]
        missing = [f["code"][3:] for f in state_checks(html)]
        # Contrast comes FIRST among the finished-or-not reasons. Text nobody
        # can read is a harder failure than a missing hover state, and unlike
        # the static checks it cannot be re-derived here -- it was measured in a
        # real browser during the review and carried across.
        # BOTH measured regressions together, never one at a time. Handing back
        # only the contrast problem, then only the layout problem, makes the
        # model rewrite the whole stylesheet twice with a different single
        # objective each round -- and it trades one for the other. Measured:
        # repairing the type scale (41.6px -> 27.2px) broke the contrast that
        # had been holding. One brief, both constraints.
        measured = [x for x in (rec.get("contrast"), rec.get("layout")) if x]
        if measured:
            out.append((str(fp), " ALSO: ".join(measured)
                        if len(measured) > 1 else measured[0]))
        elif errs:
            out.append((str(fp), f"design_review still reports {len(errs)} BROKEN item(s)."))
        elif missing:
            out.append((str(fp), "it is still missing these interaction states: "
                                 + ", ".join(missing) + "."))
    return out


def note_page(sid, path):
    """Remember an HTML page this session produced."""
    if not path or Path(path).suffix.lower() not in (".html", ".htm"):
        return
    with _lock:
        w = _session_work.setdefault(sid or "_nosession", {"files": {}, "actions": []})
        ctx = w.setdefault("ctx", {})
        pages = ctx.setdefault("pages", [])
        if str(path) not in pages:
            pages.append(str(path))


def _page_stamp(path):
    """Cheap identity for 'is this still the file that was reviewed?'"""
    try:
        st = Path(path).stat()
        return f"{int(st.st_mtime)}:{st.st_size}"
    except OSError:
        return ""


def note_reviewed(sid, path, contrast_issue="", layout_issue=""):
    """Record that design_review ran on this file, and what it concluded.

    Two things are stored beyond the bare path:

    `stamp` — because the model reviews a page, then EDITS it, and the old
    record made the new version look already-reviewed. The gate below compares
    stamps, so an edit re-opens the page for review instead of sailing through
    on the strength of a review of a file that no longer exists.

    `contrast` — the one finding that must survive to the gate. Re-measuring it
    there would mean launching a browser twice per page per round; the review
    already paid that cost, so carry the verdict rather than repeat the work.
    """
    if not path:
        return
    with _lock:
        w = _session_work.setdefault(sid or "_nosession", {"files": {}, "actions": []})
        ctx = w.setdefault("ctx", {})
        seen = ctx.get("reviewed")
        # Older sessions stored a plain list of paths. Migrate rather than
        # crash on a session that started before this change.
        if isinstance(seen, list):
            seen = {k: {"stamp": "", "contrast": ""} for k in seen}
        elif not isinstance(seen, dict):
            seen = {}
        ctx["reviewed"] = seen
        try:
            key = str(Path(path).resolve()).lower()
        except OSError:
            key = str(path).lower()
        seen[key] = {"stamp": _page_stamp(path),
                     "contrast": str(contrast_issue or ""),
                     "layout": str(layout_issue or "")}


def _existing_py(paths):
    """De-duplicate a list of .py paths and keep the ones really on disk.

    Takes paths, not tool-call rows. An earlier version of this read
    all_tool_calls looking for a "path" key -- those rows are {"tool", "arg"}
    and have never had one, so it returned nothing on every turn and the
    integration gate did nothing at all while appearing to run.
    """
    seen, out = set(), []
    for raw in paths or []:
        try:
            fp = Path(str(raw))
            if not fp.is_file():
                continue
            key = str(fp.resolve()).lower()
            if key not in seen:
                seen.add(key)
                out.append(str(fp))
        except OSError:
            continue
    return out


# What a write's result says when it did NOT change the file. Measured
# 2026-09-25: an edit refused by the deleted-names guard was still counted --
# "1 file(s) written so far", "written since it was last read" -- so the "you
# have not changed anything" check never fired and the job ended "done" with
# nothing changed.
_WRITE_FAIL_MARKERS = ("[ERROR", "VERIFY FAILED", "EDIT FAILED", "WRITE REFUSED",
                       "[WRONG FILE]", "REFUSED", "[File not found", "[NO CHANGE]")


def write_result_failed(result):
    """True if a write/edit tool result says the file was NOT changed."""
    head = str(result or "")[:300]
    return any(m in head for m in _WRITE_FAIL_MARKERS)


def _call_failed(c):
    """For a recorded write call: it did not change anything. A write that never
    ran (refused before running, a suppressed duplicate) did not either."""
    return c.get("name") in WRITE_TOOLS and c.get("_ok") is not True


def _written_paths(rows):
    """Files this run created that are ACTUALLY ON DISK, de-duplicated.

    This used to return r["arg"], which is _summ() output: a 120-char JSON dump
    of every argument including the file's whole content. The dead-end report
    then printed those blobs under the heading "These are real and are on disk",
    which was unreadable AND unverified -- one listed entry was a run_shell
    command and another had no path at all.

    Two rules now: take the real `path` argument, and stat it. A claimed write
    that is not on disk does not belong on a list headed "these are real".
    """
    seen, out = set(), []
    for r in rows or []:
        if (r.get("tool") or r.get("name")) not in WRITE_TOOLS:
            continue
        if r.get("failed"):
            continue
        p = str(r.get("path") or "").strip()
        if not p:
            continue
        try:
            fp = Path(p)
            if not fp.is_file():
                continue
            key = str(fp.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(f"{fp} ({fp.stat().st_size:,} bytes)")
        except OSError:
            continue
    return out


TOOL_TIERS = {
    "list_dir":"green", "read_file":"green", "search_files":"green",
    "find_definition":"green", "find_references":"green",
    "web_search":"green", "web_fetch":"green", "screen_capture":"green",
    "delegate":"green", "list_specialists":"green", "list_devices":"green",
    # Asking the user a question, and looking up where an app lives, both touch
    # NOTHING on the system. ask_user parks the turn for an answer; resolve_app
    # only reads paths. Gating either behind an approval prompt would be absurd
    # -- the whole point of ask_user is to REPLACE the approve/deny dialog with a
    # real question, and a resolver that prompts is a resolver nobody calls.
    "ask_user":"green", "resolve_app":"green",
    # The managed browser: open/read/find/see are read-only lookups and must be
    # frictionless (they are what replace web_fetch on pages behind a login).
    # Acting -- clicking and typing as the logged-in user -- is consequential, so
    # each such call is approved on its own, exactly like a shell command.
    "browser_open":"green", "browser_read":"green", "browser_find":"green",
    "browser_see":"green", "browser_click":"red", "browser_type":"red",
    # The hidden desktop launches and drives real programs — red, every call.
    "hidden_desktop":"red",
    # Writes only into ND's own session memory. It must never prompt: an approval
    # dialog between "here is my plan" and doing the work would stop the model
    # keeping a plan at all.
    "update_plan":"green",
    # Generating a picture writes only into the gallery and touches nothing
    # else, so it should never interrupt the user for approval.
    "generate_image":"green",
    # Renders a local file into a PNG under temp/. Read-only with respect to the
    # user's work, and it must never prompt -- an approval dialog between "wrote
    # the page" and "looked at the page" would stop the agent using it at all.
    "design_review":"green",
    "device_action":"red",      # it moves a physical device the user is holding
    "edit_file":"yellow", "write_file":"yellow", "run_script":"yellow",
    "run_shell":"red", "install_app":"red", "gui_action":"red",
}

# Matched case-insensitively against the shell command text.
BLACK_PATTERNS = [
    (r"\bformat\s+[a-z]:",                                   "formats a drive"),
    (r"\bdiskpart\b",                                        "repartitions disks"),
    (r"\bbcdedit\b",                                         "changes boot configuration"),
    (r"\bcipher\s+/w",                                       "wipes free disk space"),
    (r"\bvssadmin\b[^\n]*\bdelete\s+shadows\b",              "deletes shadow copies / restore points"),
    # Order-independent: the switch can come before or after the path.
    (r"\b(?:del|rd|rmdir|remove-item|ri)\b[^\n]*\bc:\\+(?:windows|program files|users\s*$|users\\?\s|\$)",
                                                             "deletes a Windows system or user folder"),
    (r"\bremove-item\b[^\n]*\b[a-z]:\\+\s*(?:['\"]|$|-)",     "recursive delete at a drive root"),
    (r"\brm\b\s+-rf?\s+/?\s*$|\brm\b\s+-rf\s+/(?:\s|$)",     "recursive delete at the filesystem root"),
    (r"\breg\s+delete\b[^\n]*\bhklm\b",                      "deletes machine-wide registry keys"),
    (r"\bnet\s+user\b[^\n]*\s/(?:add|delete)\b",             "creates or deletes a Windows account"),
    (r"set-executionpolicy\s+unrestricted",                  "disables PowerShell script protection"),
    (r"set-mppreference[^\n]*disablerealtimemonitoring\s*\$?true", "disables Windows Defender"),
    (r"\b(?:shutdown|restart-computer|stop-computer)\b",     "shuts down or reboots the PC"),
    (r"(?:invoke-webrequest|invoke-restmethod|\birm\b|\biwr\b)[^\n]*\|\s*(?:iex|invoke-expression)", "pipes a downloaded script straight into execution"),
    # Killing processes. Refused at every autonomy level, including "auto" --
    # an unattended run is precisely when there is nobody to catch it.
    (r"\b(?:stop-process|spps)\b",                          "force-kills running processes"),
    (r"\btaskkill\b",                                       "force-kills running processes"),
    (r"\b(?:pkill|killall)\b",                              "force-kills running processes"),
    # `kill` is an alias for Stop-Process in PowerShell, so the long form alone
    # would be decorative. Narrowed to a following target so the bare word in
    # prose does not trip it; "skill"/"taskkill" cannot match \bkill\b anyway.
    (r"\bkill\b\s+(?:-|\d|\$)",                             "force-kills running processes"),
]

def agent_settings():
    return {
        "admin_mode":   bool(_config.get("agent_admin_mode", False)),
        "pc_control":   bool(_config.get("agent_pc_control", True)),
        "shell_timeout": int(_config.get("agent_shell_timeout", 180)),
    }

def agent_audit(tool, tier, detail, decision):
    """Append-only record of everything Agent Mode did or was stopped from doing."""
    try:
        line = json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                           "tool": tool, "tier": tier, "decision": decision,
                           "detail": str(detail)[:600],
                           "admin": agent_settings()["admin_mode"]})
        with open(AGENT_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        log(f"audit write failed: {e}", "warn")

def classify_shell(cmd):
    """Return (tier, reason). 'black' means blocked unless ADMIN MODE is on."""
    import re as _re
    low = (cmd or "").lower()
    for pat, why in BLACK_PATTERNS:
        if _re.search(pat, low, _re.I):
            return "black", why
    return "red", ""

_URI_RE = re.compile(r'(["\'])((?:spotify|steam|ms-settings|mailto|obsidian|vscode|discord|slack|zoommtg):[^"\']*)\1',
                     re.I)

def _fix_uri_spaces(command):
    """Windows hands a protocol URI to the app as a raw command line, and the app
    splits it on whitespace — so `spotify:search:Deathmask Divine` arrives as just
    "Deathmask". Percent-encoding the spaces is the only thing that survives.
    Models forget this constantly, so fix it here instead of hoping."""
    def _sub(m):
        q, uri = m.group(1), m.group(2)
        if " " not in uri:
            return m.group(0)
        scheme, _, rest = uri.partition(":")
        return q + scheme + ":" + rest.replace("%", "%25").replace(" ", "%20") + q
    return _URI_RE.sub(_sub, command)

def _unwrap_command(cmd):
    """Models sometimes re-serialize the argument name into the value, sending
    `command="Start-Process ..."` as the command itself. PowerShell then tries to
    run a module called 'command=' and everything derails. Strip that wrapper."""
    c = (cmd or "").strip()
    for _ in range(3):
        m = re.match(r'^(?:command|cmd|powershell|pwsh|ps)\s*=\s*(.*)$', c, re.I | re.S)
        if not m:
            break
        c = m.group(1).strip()
    # peel one layer of surrounding quotes and un-escape what was inside them
    if len(c) >= 2 and c[0] == c[-1] and c[0] in "\"'":
        q = c[0]
        c = c[1:-1].replace("\\" + q, q).replace("\\\\", "\\")
    return c.strip()

def tool_run_shell(command, cwd=None, timeout=None):
    command = (command or "").strip()
    unwrapped = _unwrap_command(command)
    wrap_note = ""
    if unwrapped != command:
        log(f"Unwrapped malformed command argument: {command[:70]}", "warn")
        wrap_note = ("\n[note] Your command arrived wrapped as `command=\"...\"`. It was unwrapped and run. "
                     "Pass only the raw PowerShell in the `command` field — do not repeat the field name.")
        command = unwrapped
    if not command:
        return "[shell] Empty command."
    fixed = _fix_uri_spaces(command)
    uri_note = ""
    if fixed != command:
        log(f"URI spaces percent-encoded: {command[:90]} -> {fixed[:90]}", "info")
        uri_note = ("\n[note] Spaces in the URI were percent-encoded automatically — "
                    "without that the app only receives the first word.")
        command = fixed
    admin = agent_settings()["admin_mode"]
    tier, why = classify_shell(command)
    if tier == "black" and not admin:
        agent_audit("run_shell", "black", command, "BLOCKED")
        return ("[BLOCKED] This command %s, which is on the hard blocklist.\n"
                "Turn on ADMIN MODE in the Agent tab if you really need it, "
                "then ask again. Command was NOT run.") % why
    if tier == "black":
        agent_audit("run_shell", "black", command, "ALLOWED-ADMIN")
        log(f"ADMIN MODE ran blocklisted command: {command[:120]}", "warn")
    timeout = int(timeout or agent_settings()["shell_timeout"])
    try:
        _rc, _out, _err, _to = _run_capped(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", command],
            timeout, cwd=(cwd if cwd and Path(cwd).is_dir() else None))
        if _to:
            agent_audit("run_shell", tier, command, "TIMEOUT")
            _tail = (_out or _err or "").strip()[-1500:]
            return ("[shell] Timed out after " + str(timeout) + "s and was "
                    "killed, along with anything it started." + NL +
                    "If this was a server or a watcher that is expected: it "
                    "does not return on its own, so run_shell cannot start it "
                    "and check it in the same call. Start it in the background, "
                    "or test the code directly instead." + NL +
                    ("Output before it was killed:" + NL + _tail if _tail
                     else "It produced no output before being killed."))
        agent_audit("run_shell", tier, command, f"exit={_rc}")
        out = (_out or "").strip()
        err = (_err or "").strip()
        if _rc != 0:
            # A non-zero exit is a FAILURE, and it used to be a quiet "[shell]
            # exit 1" the model read straight past and called done. That is the
            # exact bug that reported a Chrome launch as working when the path was
            # wrong. Make it impossible to miss, and point at the fix.
            body = (f"[shell] FAILED — exit code {_rc} (not 0). The command did NOT succeed and "
                    "nothing it was meant to do has happened.\n"
                    "Do NOT tell the user it worked. Read the error below. If it says the file or "
                    "path cannot be found, the path is wrong — call resolve_app to get the real one "
                    "instead of guessing another. Fix the cause, then try once more; do not re-run "
                    "the identical failing command.\n")
        else:
            body = "[shell] exit 0\n"
        if out: body += out[:12000] + ("\n[…stdout truncated]" if len(out) > 12000 else "")
        if err: body += "\n[stderr]\n" + err[:4000]
        if not out and not err:
            # Exit 0 with no output proves NOTHING happened correctly - it only
            # proves the command was accepted. Launchers (Start-Process, start,
            # Store app stubs) always look like this. Say so, or the model just
            # runs the same command again and again.
            body += ("(no output — exit 0 only means the command was accepted, NOT that it worked. "
                     "Do NOT run this same command again. Verify the actual result instead: "
                     "check with Get-Process / Test-Path, or take a screen_capture and look.)")
        return body + uri_note + wrap_note
    except subprocess.TimeoutExpired:
        agent_audit("run_shell", tier, command, "TIMEOUT")
        return f"[shell] Timed out after {timeout}s. The command may still be running."
    except Exception as e:
        agent_audit("run_shell", tier, command, f"ERROR {e}")
        return f"[shell error] {e}"

_INSTALL_CMDS = {
    "winget": 'winget install --id "{n}" --accept-package-agreements --accept-source-agreements --silent -e',
    "choco":  'choco install {n} -y',
    "scoop":  'scoop install {n}',
    "pip":    '"{py}" -m pip install {n}',
    "npm":    'npm install -g {n}',
}

def tool_install_app(name, manager="winget"):
    name = (name or "").strip()
    if not name:
        return "[install] No package name given."
    manager = (manager or "winget").strip().lower()
    if manager not in _INSTALL_CMDS:
        return f"[install] Unknown manager '{manager}'. Use one of: {', '.join(_INSTALL_CMDS)}"
    cmd = _INSTALL_CMDS[manager].format(n=name, py=sys.executable)
    agent_audit("install_app", "red", f"{manager}: {name}", "RUN")
    log(f"Installing {name} via {manager}", "info")
    return tool_run_shell(cmd, timeout=900)

# ─── Find where an app actually lives ─────────────────────────────────────────
# A guessed executable path is the single most common reason a launch silently
# fails -- the model wrote the x86 Chrome path on a machine where Chrome is in
# Program Files, Start-Process threw "cannot find the file", exit was 1, and
# nobody noticed. This looks the path up for real so the model never has to
# guess one again.
_APP_ALIASES = {
    "chrome":        {"exe": ["chrome.exe"],  "proc": "chrome",   "uri": None},
    "google chrome": {"exe": ["chrome.exe"],  "proc": "chrome",   "uri": None},
    "edge":          {"exe": ["msedge.exe"],  "proc": "msedge",   "uri": "microsoft-edge:"},
    "microsoft edge":{"exe": ["msedge.exe"],  "proc": "msedge",   "uri": "microsoft-edge:"},
    "firefox":       {"exe": ["firefox.exe"], "proc": "firefox",  "uri": None},
    "spotify":       {"exe": ["Spotify.exe"], "proc": "Spotify",  "uri": "spotify:"},
    "notepad":       {"exe": ["notepad.exe"], "proc": "notepad",  "uri": None},
    "vs code":       {"exe": ["Code.exe"],    "proc": "Code",     "uri": "vscode:"},
    "vscode":        {"exe": ["Code.exe"],    "proc": "Code",     "uri": "vscode:"},
    "code":          {"exe": ["Code.exe"],    "proc": "Code",     "uri": "vscode:"},
    "explorer":      {"exe": ["explorer.exe"],"proc": "explorer", "uri": None},
    "calculator":    {"exe": ["calc.exe"],    "proc": "Calculator","uri": "calculator:"},
}

def tool_resolve_app(name):
    name = (name or "").strip()
    if not name:
        return "[resolve_app] Give the name of a program to find."
    low = name.lower()
    alias = _APP_ALIASES.get(low)
    exe_names = list(alias["exe"]) if alias else []
    if not exe_names:
        base = name if name.lower().endswith(".exe") else name + ".exe"
        exe_names = [base]
    proc = alias["proc"] if alias else re.sub(r"\.exe$", "", exe_names[0], flags=re.I)
    uri = alias["uri"] if alias else None
    # One PowerShell pass: PATH (Get-Command), the App Paths registry, the usual
    # install roots, and whether it is already running with a window.
    ps = (
        "$names=@(" + ",".join("'" + e.replace("'", "''") + "'" for e in exe_names) + ")\n"
        "$found=@()\n"
        "foreach($n in $names){\n"
        "  $c=Get-Command $n -ErrorAction SilentlyContinue | Select-Object -First 1\n"
        "  if($c -and $c.Source){ $found+=$c.Source }\n"
        "  foreach($root in 'HKLM:','HKCU:'){\n"
        "    $k=\"$root\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\$n\"\n"
        "    if(Test-Path $k){ $v=(Get-ItemProperty $k).'(default)'; if($v){ $found+=$v } }\n"
        "  }\n"
        "}\n"
        "$roots=@($env:ProgramFiles,${env:ProgramFiles(x86)},$env:LOCALAPPDATA,$env:APPDATA)\n"
        "foreach($n in $names){ foreach($r in $roots){ if($r){\n"
        "  $hits=Get-ChildItem -Path $r -Filter $n -Recurse -ErrorAction SilentlyContinue -Depth 3 | Select-Object -First 1\n"
        "  if($hits){ $found+=$hits.FullName }\n"
        "}}}\n"
        "$found=$found | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique\n"
        f"$p=Get-Process '{proc}' -ErrorAction SilentlyContinue\n"
        "$titles=@(); if($p){ $titles=$p | Where-Object {$_.MainWindowTitle} | ForEach-Object {$_.MainWindowTitle} | Select-Object -Unique }\n"
        "[pscustomobject]@{paths=@($found);running=[bool]$p;count=@($p).Count;titles=@($titles)} | ConvertTo-Json -Compress -Depth 4\n")
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                            "-ExecutionPolicy", "Bypass", "-Command", ps],
                           capture_output=True, text=True, timeout=40, errors="replace")
        data = json.loads((r.stdout or "").strip() or "{}")
    except Exception as e:
        data = {"error": str(e)}
    paths = data.get("paths") or []
    if isinstance(paths, str):
        paths = [paths]
    lines = [f"[resolve_app] {name}:"]
    if paths:
        lines.append("  Executable" + ("s" if len(paths) > 1 else "") + ":")
        for p in paths[:6]:
            lines.append("    " + p)
        lines.append("  To launch:  Start-Process -FilePath '" + paths[0] + "' -ArgumentList '<url or args>'")
    else:
        lines.append("  No executable found on PATH, in App Paths, or under the standard install roots.")
    if uri:
        lines.append(f"  Protocol URI: Start-Process \"{uri}...\"  (often more reliable than the exe path)")
    if data.get("running"):
        t = ", ".join(data.get("titles") or [])[:200]
        lines.append(f"  Already RUNNING: {data.get('count')} process(es)" + (f" — window(s): {t}" if t else " (no visible window)"))
    else:
        lines.append("  Not currently running.")
    if data.get("error"):
        lines.append("  (lookup error: " + str(data["error"])[:120] + ")")
    lines.append("  Use the real path above — do not guess one. exit 0 from a launcher means 'accepted', "
                 "not 'worked': verify with resolve_app again or Get-Process.")
    return "\n".join(lines)

# ─── GUI automation (mouse / keyboard / screen) ───────────────────────────────
_pyautogui = None
def _gui():
    global _pyautogui
    if _pyautogui is None:
        import pyautogui as _p
        _p.FAILSAFE = True        # slam the mouse into a corner to abort
        _p.PAUSE    = 0.06
        _pyautogui  = _p
    return _pyautogui

def tool_screen_capture(region=None, max_width=1280):
    """Grab the screen and return it as a base64 PNG the vision model can read."""
    try:
        g = _gui()
        shot = g.screenshot(region=tuple(region) if region else None)
        if shot.width > max_width:
            h = int(shot.height * (max_width / shot.width))
            shot = shot.resize((max_width, h))
        buf = io.BytesIO(); shot.save(buf, "PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        agent_audit("screen_capture", "green", f"{shot.width}x{shot.height}", "OK")
        return {"image_b64": b64, "width": shot.width, "height": shot.height}
    except Exception as e:
        return {"error": str(e)}

def tool_gui_action(action, x=None, y=None, text=None, keys=None, amount=None,
                    to_x=None, to_y=None, button="left"):
    """One mouse/keyboard action. Always red-tier: it drives the real desktop."""
    action = (action or "").strip().lower()
    try:
        g = _gui()
        sw, sh = g.size()
        def _pt(a, b):
            if a is None or b is None: return None
            return (max(0, min(int(a), sw - 1)), max(0, min(int(b), sh - 1)))
        p = _pt(x, y)
        if   action == "move":
            g.moveTo(*p, duration=0.15);                       desc = f"move {p}"
        elif action in ("click", "left_click"):
            g.click(*(p or g.position()), button=button);      desc = f"click {p or 'here'} ({button})"
        elif action == "double_click":
            g.doubleClick(*(p or g.position()));               desc = f"double_click {p or 'here'}"
        elif action == "right_click":
            g.rightClick(*(p or g.position()));                desc = f"right_click {p or 'here'}"
        elif action == "drag":
            if p: g.moveTo(*p, duration=0.15)
            g.dragTo(*(_pt(to_x, to_y) or g.position()), duration=0.35, button=button)
            desc = f"drag {p} -> ({to_x},{to_y})"
        elif action == "scroll":
            g.scroll(int(amount if amount is not None else -400)); desc = f"scroll {amount}"
        elif action == "type":
            g.typewrite(text or "", interval=0.012);           desc = f"type {len(text or '')} chars"
        elif action == "key":
            g.press((keys or text or "enter"));                desc = f"key {keys or text}"
        elif action == "hotkey":
            combo = [k.strip() for k in (keys or text or "").replace("-", "+").split("+") if k.strip()]
            if not combo: return "[gui] hotkey needs keys like 'ctrl+s'"
            g.hotkey(*combo);                                  desc = f"hotkey {'+'.join(combo)}"
        elif action == "media":
            # Real media keys - these control Spotify/any player regardless of focus
            vk = {"playpause": 0xB3, "play": 0xB3, "pause": 0xB3, "next": 0xB0,
                  "nexttrack": 0xB0, "prev": 0xB1, "previous": 0xB1, "prevtrack": 0xB1,
                  "stop": 0xB2, "volup": 0xAF, "voldown": 0xAE, "mute": 0xAD}
            k = (keys or text or "playpause").strip().lower()
            if k not in vk:
                return f"[gui] Unknown media key '{k}'. Use: {', '.join(sorted(set(vk)))}"
            import ctypes
            ctypes.windll.user32.keybd_event(vk[k], 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk[k], 0, 2, 0)
            desc = f"media key {k}"
        elif action in ("focus", "focus_window", "activate"):
            # A window buried behind the browser is invisible to screen_capture,
            # which is why "I can't see Spotify" kept happening.
            target = (text or keys or "").strip()
            if not target:
                return "[gui] focus needs the app or window name in `text`."
            ps = ('Add-Type @"\nusing System;using System.Runtime.InteropServices;\n'
                  'public class _W{[DllImport("user32.dll")]public static extern bool SetForegroundWindow(IntPtr h);'
                  '[DllImport("user32.dll")]public static extern bool ShowWindow(IntPtr h,int c);}\n"@\n'
                  f'$p=Get-Process | Where-Object {{ $_.MainWindowTitle -ne "" -and '
                  f'($_.ProcessName -like "*{target}*" -or $_.MainWindowTitle -like "*{target}*") }} | Select-Object -First 1\n'
                  'if($p){ [_W]::ShowWindow($p.MainWindowHandle,9)|Out-Null; '
                  '[_W]::SetForegroundWindow($p.MainWindowHandle)|Out-Null; '
                  '"FOCUSED: " + $p.ProcessName + " | " + $p.MainWindowTitle } else { "NOWINDOW" }')
            r = subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command", ps],
                               capture_output=True, text=True, timeout=30, errors="replace")
            outp = (r.stdout or "").strip()
            agent_audit("gui_action", "red", f"focus {target}", "OK")
            if "NOWINDOW" in outp:
                return (f"[gui] No visible window matching '{target}'. It may be minimised to tray or "
                        "not running. Check with Get-Process before assuming it is open.")
            time.sleep(0.6)
            return (f"[gui] {outp}\nThe window is now in front — take a screen_capture to see it.")
        elif action == "position":
            return f"[gui] cursor at {tuple(g.position())}, screen {sw}x{sh}"
        else:
            return (f"[gui] Unknown action '{action}'. Use: move, click, double_click, "
                    "right_click, drag, scroll, type, key, hotkey, media, focus, position.")
        agent_audit("gui_action", "red", desc, "OK")
        return f"[gui] {desc} — done. Screen {sw}x{sh}."
    except Exception as e:
        agent_audit("gui_action", "red", f"{action}", f"ERROR {e}")
        return f"[gui error] {e}"

# ═══════════════════════════════════════════════════════════════════════════════
# THE HANDLER — a small fast model that answers directly and farms out the rest
# ═══════════════════════════════════════════════════════════════════════════════
# A 30B coder is slow and overkill for "what time is it". A 8B generalist is fast
# and personable but weak at 800-line refactors. So: the fast model fronts the
# conversation and calls `delegate` to hand real work to a specialist, then
# reports back in its own voice. That is the Jarvis pattern - one voice, many
# brains behind it.
_CODE_PAT   = r"coder|codellama|deepseek-?coder|starcoder|code"
_VISION_PAT = r"qwen2?\.?5?-?vl|llava|minicpm-v|moondream|bakllava|vision|gemma3"
# Ollama builds that use the new engine cannot load mllama, so never route to it.
_BROKEN_PAT = r"llama3\.2-vision"

SPECIALIST_RULES = [
    # role,        include,      exclude,                      what it is good at
    ("code",       _CODE_PAT,    _VISION_PAT,
                   "writing, refactoring, debugging and reviewing code; large multi-file work"),
    ("vision",     _VISION_PAT,  _BROKEN_PAT,
                   "looking at images and screenshots and transcribing exactly what is in them"),
    ("deep",       r".",         _CODE_PAT + "|" + _VISION_PAT + "|embed",
                   "hard reasoning, long analysis, planning, tricky judgement calls"),
    ("uncensored", r"heretic|uncensor|abliterat|dolphin|hhh|(?<![a-z])h(?=_|\d)",
                   _VISION_PAT,
                   "topics a safety-tuned model refuses to engage with"),
]

def _ollama_sizes():
    """Real on-disk byte size per model, which is a far better capability proxy
    than parsing '30b' out of a name that may not contain it at all."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=8) as r:
            data = json.loads(r.read())
        return {m["name"]: m.get("size", 0) for m in data.get("models", [])}
    except Exception:
        return {}

def _model_size_hint(name, sizes=None):
    if sizes and name in sizes and sizes[name]:
        return sizes[name]
    m = re.search(r"(\d+)\s*[bB]\b", name or "")
    return int(m.group(1)) * 600_000_000 if m else 0     # rough bytes-per-B

_vram_cache = None
def gpu_vram_bytes():
    """Total VRAM. A model that does not fit gets split onto the CPU, which can
    make a 'better' model several times slower than a smaller one - so this,
    not raw parameter count, decides which specialist we route to."""
    global _vram_cache
    if _vram_cache is not None:
        return _vram_cache
    # Delegated to nd_gpu so this works on AMD and Intel too, and -- more
    # importantly -- so a card nothing can size gets LOGGED instead of silently
    # returning 0. A 0 here makes _rank_key compute budget=0, which makes
    # fits=0 for every model, which switches off fit-routing with no error.
    try:
        import nd_gpu
        g = nd_gpu.detect()
        if g["confident"]:
            _vram_cache = int(g["vram_bytes"])
            log(nd_gpu.describe(g), "info")
            return _vram_cache
        log(nd_gpu.describe(g), "warn")
    except Exception as e:
        log(f"VRAM probe failed ({e}); model fit-routing disabled", "warn")
    _vram_cache = 0
    return 0

def _rank_key(name, sizes):
    """Best first: models that fit in VRAM (largest such), then models that do
    not fit (smallest such, because that is the least painful spill)."""
    sz = _model_size_hint(name, sizes)
    vram = gpu_vram_bytes()
    budget = int(vram * 0.92) if vram else 0
    fits = 1 if (budget and sz and sz <= budget) else 0
    # MoE models tolerate spilling far better - only a few B are active per token
    moe = 1 if re.search(r"a\d+b|moe|\b30b-a|qwen3-coder", name, re.I) else 0
    return (fits, moe, sz if fits else -sz)

def model_speed_note(model):
    """A plain warning when this model will be slow, or "" when it will not.

    A model bigger than the card spills into system RAM, and generation drops
    from tens of tokens a second to a few. That is a fine trade when the user
    has chosen quality over speed -- but only if they are told, because
    otherwise it is indistinguishable from a hang.
    """
    try:
        sizes = _ollama_sizes()
        need = _model_size_hint(model, sizes) or 0
        have = gpu_vram_bytes() or 0
    except Exception:
        return ""
    if not need or not have:
        return ""
    usable = have * 0.92          # the card is never entirely yours
    if need <= usable:
        return ""
    over = (need - usable) / (1024 ** 3)
    return (f"{model.split('/')[-1]} needs ~{need / 1024**3:.1f} GB and the card has "
            f"~{have / 1024**3:.1f} GB, so about {over:.1f} GB runs on the CPU. "
            f"Expect this to take minutes rather than seconds — it is working, not stuck.")


def model_fit_map():
    """{model: {need_gb, fits, note}} for every installed model.

    Same arithmetic as model_speed_note(), handed to clients instead of only to
    the log. "fits" means the weights sit inside the usable 92% of the card, so
    generation runs at card speed rather than spilling into system RAM.
    """
    out = {}
    try:
        installed = _get_models() or []
        sizes = _ollama_sizes()
        have = gpu_vram_bytes() or 0
    except Exception:
        return out
    usable = have * 0.92 if have else 0
    for m in installed:
        try:
            need = _model_size_hint(m, sizes) or 0
        except Exception:
            need = 0
        out[m] = {
            "need_gb": round(need / 1024 ** 3, 2) if need else None,
            # Unknown size is reported as unknown, never as a confident "fits".
            "fits": (need <= usable) if (need and usable) else None,
            "note": model_speed_note(m) or "",
        }
    return out


def model_roster():
    """Map installed models onto roles, best-in-role first."""
    try:
        installed = _get_models() or []
    except Exception:
        installed = []
    sizes = _ollama_sizes()
    handler = _config.get("handler_model", "")
    pins = _config.get("specialist_overrides") or {}
    roster = {}
    for role, inc, exc, why in SPECIALIST_RULES:
        hits = [m for m in installed
                if re.search(inc, m, re.I) and not (exc and re.search(exc, m, re.I))]
        # An explicit pin wins over size ranking. Bigger is not always better:
        # a model that leaves headroom for the KV cache beats one that spills.
        pin, pinned = pins.get(role), None
        if pin:
            exact = [m for m in installed if m == pin] or \
                    [m for m in installed if m.split(":")[0].lower() == pin.split(":")[0].lower()]
            if exact:
                pinned = exact[0]
                hits = [m for m in hits if m != pinned]
            else:
                log(f"roster: pinned '{pin}' for role '{role}' is not installed", "warn")
        if role == "deep":
            # "deep" only means anything if it is genuinely heavier than the handler.
            # Routing to something smaller than yourself is strictly a downgrade.
            hsz = _model_size_hint(handler, sizes) if handler else 0
            hits = [m for m in hits
                    if m != handler and _model_size_hint(m, sizes) > hsz * 1.25]
        hits.sort(key=lambda m: _rank_key(m, sizes), reverse=True)
        if pinned:
            hits = [pinned] + hits          # after the sort, so the pin actually holds
        if not hits:
            continue
        vram = gpu_vram_bytes()
        best = hits[0]
        note = ""
        if vram and _model_size_hint(best, sizes) > vram:
            note = " (larger than your VRAM, so it will be slower)"
        roster[role] = {"model": best, "good_at": why + note, "alternates": hits[1:4],
                        "size_gb": round(_model_size_hint(best, sizes)/1e9, 1)}
    # if deep resolved to the same model as code, it adds nothing - drop it
    if roster.get("deep") and roster.get("code") and roster["deep"]["model"] == roster["code"]["model"]:
        roster.pop("deep")
    return roster

def handler_model():
    hm = _config.get("handler_model", "")
    if hm:
        return hm
    try:
        installed = _get_models() or []
    except Exception:
        installed = []
    for pref in ("qwen3:8b", "qwen3:14b", "llama3.1:8b", "granite3.3:8b", "mistral"):
        for m in installed:
            if m.lower().startswith(pref.split(":")[0]) and pref.split(":")[-1] in m:
                return m
    # otherwise the smallest non-coder model available
    gen = [m for m in installed if not re.search(r"cod|vl|llava|vision|embed", m, re.I)]
    gen.sort(key=_model_size_hint)
    return gen[0] if gen else (installed[0] if installed else "")

def tool_delegate(specialist, task, context="", req_id=None):
    """Hand a job to a specialist model and bring back its answer."""
    roster = model_roster()
    specialist = (specialist or "").strip().lower()
    entry = roster.get(specialist)
    if not entry:
        # allow naming a model outright, e.g. delegate("qwen3-coder:30b", ...)
        try: installed = _get_models() or []
        except Exception: installed = []
        exact = next((m for m in installed if m.lower() == specialist), None) \
             or next((m for m in installed if specialist and specialist in m.lower()), None)
        if exact:
            entry = {"model": exact, "good_at": "explicitly requested"}
        else:
            return (f"[delegate] No specialist called '{specialist}'. Available roles: "
                    f"{', '.join(roster.keys()) or 'none'}. Answer it yourself instead.")
    target = entry["model"]
    task = (task or "").strip()
    if not task:
        return "[delegate] You must say what the specialist should actually do."
    sys_msg = ("You are a specialist model being consulted by another AI that is talking to the user. "
               "Answer the task completely and concretely. No preamble, no pleasantries, no questions "
               "back - just the substance, because your answer is handed straight onward.")
    msgs = [{"role": "system", "content": sys_msg},
            {"role": "user", "content": task + (("\n\nCONTEXT:\n" + context) if context else "")}]
    log(f"Delegating to {target} ({specialist}): {task[:90]}", "info")
    agent_audit("delegate", "green", f"{specialist} -> {target}: {task[:200]}", "RUN")
    t0 = time.time()
    try:
        out = ollama_chat(target, msgs, timeout=1740)
    except Exception as e:
        return f"[delegate] {target} failed: {e}"
    dt = round(time.time() - t0, 1)
    log(f"{target} answered in {dt}s ({len(out)} chars)", "ok")
    return f"[{target} answered in {dt}s]\n{out}"

# ═══════════════════════════════════════════════════════════════════════════════
# DEVICE FABRIC — the PC is just one of Elena's bodies
# ═══════════════════════════════════════════════════════════════════════════════
# A device (phone, tablet, another PC) connects OUT to this server, registers what
# it can do, then long-polls for work. That direction matters: it means no NAT
# traversal, no inbound ports on the phone, and the device advertises its own
# capabilities instead of us assuming them.
_devices      = {}      # device_id -> {name, platform, capabilities, last_seen, ...}
_device_queue = {}      # device_id -> [ {call_id, tool, args, queued} ]
_device_res   = {}      # call_id  -> {result, done}
DEVICE_STALE_S = 90     # no poll in this long = treat as offline

def normalize_caps(caps):
    """A capability is either a bare name or a full contract:
         "get_battery"
         {"name":"notify","params":["title","body"],"required":["body"],
          "description":"Show a notification"}
       Names alone force the model to guess parameter names, and it guesses
       wrong — so everything is normalised to the object form here.
    """
    out = []
    for c in caps or []:
        if isinstance(c, str):
            out.append({"name": c, "params": [], "required": [], "description": ""})
        elif isinstance(c, dict) and c.get("name"):
            out.append({"name": c["name"],
                        "params": list(c.get("params") or []),
                        "required": list(c.get("required") or []),
                        "description": c.get("description", "")})
    return out

def cap_line(c):
    sig = f"{c['name']}(" + ", ".join(
        (p + "*" if p in c["required"] else p) for p in c["params"]) + ")"
    return sig + (f" — {c['description']}" if c["description"] else "")

def device_snapshot(include_offline=True):
    now = time.time()
    out = []
    with _lock:
        for did, d in _devices.items():
            age = now - d.get("last_seen", 0)
            online = age < DEVICE_STALE_S
            if not online and not include_offline:
                continue
            out.append({"device_id": did, "name": d.get("name", did),
                        "platform": d.get("platform", "unknown"),
                        "capabilities": d.get("capabilities", []),
                        "online": online, "seconds_since_seen": int(age),
                        "pending": len(_device_queue.get(did, []))})
    out.sort(key=lambda d: (not d["online"], d["name"].lower()))
    return out

def resolve_device(name_or_id):
    """Accept an id, an exact name, or a partial/platform match."""
    if not name_or_id:
        return None
    q = str(name_or_id).strip().lower()
    devs = device_snapshot()
    for d in devs:
        if d["device_id"].lower() == q or d["name"].lower() == q:
            return d
    for d in devs:
        if q in d["name"].lower() or q == d["platform"].lower():
            return d
    # "phone" / "my phone" should find the one obvious mobile device
    if q in ("phone", "my phone", "mobile", "cell"):
        mob = [d for d in devs if d["platform"] in ("android", "ios")]
        if len(mob) == 1:
            return mob[0]
    return None

def dispatch_to_device(device_id, tool, args, timeout=90):
    """Queue a call for a device and block until it reports back."""
    call_id = uuid.uuid4().hex[:12]
    with _lock:
        if device_id not in _devices:
            return {"error": f"Unknown device '{device_id}'"}
        _device_queue.setdefault(device_id, []).append(
            {"call_id": call_id, "tool": tool, "args": args, "queued": time.time()})
        _device_res[call_id] = {"done": False, "result": None}
    log(f"-> {_devices[device_id].get('name', device_id)}: {tool} {json.dumps(args)[:90]}", "info")
    agent_audit("device:" + tool, "red", f"{device_id}: {json.dumps(args)[:200]}", "SENT")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.25)
        with _lock:
            rec = _device_res.get(call_id, {})
            if rec.get("done"):
                _device_res.pop(call_id, None)
                return {"result": rec.get("result")}
    with _lock:
        _device_res.pop(call_id, None)
        q = _device_queue.get(device_id, [])
        _device_queue[device_id] = [c for c in q if c["call_id"] != call_id]
    return {"error": f"Device did not answer within {timeout}s. It may be offline, "
                     "asleep, or the action needed an on-device confirmation."}

def tool_device_action(device, action, params=None, timeout=90):
    d = resolve_device(device)
    if not d:
        avail = ", ".join(f"{x['name']} ({x['platform']}, "
                          f"{'online' if x['online'] else 'offline'})" for x in device_snapshot()) or "none"
        return (f"[device] No device matching '{device}'. Known devices: {avail}. "
                "Call list_devices to see exactly what is connected.")
    if not d["online"]:
        return (f"[device] '{d['name']}' is registered but offline "
                f"(last seen {d['seconds_since_seen']}s ago). Tell the user it needs to be awake "
                "and connected, and do not retry in a loop.")
    caps = d.get("capabilities", [])
    names = [c["name"] for c in caps]
    if caps and action not in names:
        return (f"[device] '{d['name']}' cannot do '{action}'. It supports:\n  "
                + "\n  ".join(cap_line(c) for c in caps)
                + "\nPick one of those, or tell the user this is not possible on that device.")
    # Validate against the declared contract instead of letting the device get a
    # call with invented parameter names and silently do nothing useful.
    spec = next((c for c in caps if c["name"] == action), None)
    params = params or {}
    if spec:
        missing = [p for p in spec["required"] if p not in params or params[p] in ("", None)]
        if missing:
            return (f"[device] '{action}' needs {', '.join(missing)}. "
                    f"Correct call: {cap_line(spec)}  (* = required). "
                    "Re-send with those parameters — do not guess different names.")
        unknown = [k for k in params if spec["params"] and k not in spec["params"]]
        if unknown:
            return (f"[device] '{action}' does not take {', '.join(unknown)}. "
                    f"It takes: {cap_line(spec)}. Re-send using those exact names.")
    r = dispatch_to_device(d["device_id"], action, params, timeout=timeout)
    if r.get("error"):
        return f"[device] {r['error']}"
    res = r.get("result")
    return f"[device:{d['name']}] " + (res if isinstance(res, str) else json.dumps(res)[:6000])

def model_has_vision(name):
    """Can this model actually accept an image? Sending one to a text-only model
    makes Ollama return a bare 400, which is what killed the screenshot step."""
    n = name or ""
    return bool(re.search(_VISION_PAT, n, re.I)) and not re.search(_BROKEN_PAT, n, re.I)

def describe_screenshot(b64, why="the current screen"):
    """Hand a screenshot to the vision specialist and get words back, so a
    text-only handler can still 'see'."""
    vm = model_roster().get("vision", {}).get("model")
    if not vm:
        return ("[No vision model installed, so the screenshot could not be read. "
                "Install one (ollama pull qwen2.5vl:7b) or work without looking at the screen.]")
    msgs = [{"role": "user",
             "content": ("Describe this screenshot of a Windows desktop precisely. List the visible "
                         "windows and apps, any search box and exactly what text is typed in it, the "
                         "visible buttons and their approximate positions, what is selected or playing, "
                         "and any error text. Be literal — do not invent anything."),
             "images": [b64]}]
    try:
        t0 = time.time()
        txt = ollama_chat(vm, msgs, timeout=600)
        log(f"Screenshot described by {vm} in {round(time.time()-t0,1)}s", "ok")
        return f"[Screenshot of {why}, described by {vm}]\n{txt}"
    except Exception as e:
        return f"[Could not read the screenshot: {e}]"

def roster_prompt():
    roster = model_roster()
    if not roster:
        return ""
    lines = [f"  - {role}  ->  {e['model']}   ({e['good_at']})" for role, e in roster.items()]
    return ("\n\nYOU ARE THE HANDLER. You are the fast, well-spoken front of a team of local models. "
            "Answer anything you can yourself, immediately - general knowledge, chat, quick questions, "
            "short snippets. For anything heavy, call the `delegate` tool instead of struggling:\n"
            + "\n".join(lines) +
            "\n  Rules for delegating:\n"
            "  - Give the specialist the FULL task in one shot, including any file paths, code, or "
            "constraints it needs. It cannot see this conversation.\n"
            "  - Never delegate something you can answer in one sentence - that just makes you slow.\n"
            "  - 'Write/refactor/debug this code' means delegate to `code`. It does NOT mean install a "
            "package, run a script, or touch the system - do not reach for install_app or run_shell to "
            "answer a coding question.\n"
            "  - When the specialist replies, do NOT paste it verbatim. Read it, and give the user the "
            "answer in your own voice, tightened up. Mention which specialist you used in a short aside.\n"
            "  - You still have every other tool. Read files and run commands yourself when that is faster "
            "than asking someone else.")

ROUTER_TOOL_SCHEMAS = [
  {"type":"function","function":{"name":"delegate","description":"Hand a heavy task to a specialist model on this PC and get its answer back. Use for real code work, image reading, deep analysis - not for things you can answer yourself.","parameters":{"type":"object","properties":{"specialist":{"type":"string","description":"Role name (code, vision, deep, uncensored) or an exact model name"},"task":{"type":"string","description":"The complete, self-contained task. The specialist cannot see this conversation, so include everything it needs."},"context":{"type":"string","description":"Optional extra material: file contents, error text, prior findings"}},"required":["specialist","task"]}}},
  {"type":"function","function":{"name":"list_specialists","description":"List which specialist models are installed and what each is good at.","parameters":{"type":"object","properties":{}}}},
]

DEVICE_TOOL_SCHEMAS = [
  {"type":"function","function":{"name":"list_devices","description":"List the user's other paired devices (phone, tablet, other PCs), whether each is online, and exactly which actions each one supports. Call this BEFORE trying to act on a device so you use a real capability name.","parameters":{"type":"object","properties":{}}}},
  {"type":"function","function":{"name":"device_action","description":"Perform an action on one of the user's other devices, such as their phone. The action must be one the device reported in list_devices - do not invent action names. Typical Android actions: open_app, launch_uri, send_sms, notify, screenshot, read_screen, tap, swipe, type_text, back, home, get_battery, get_location, toggle_wifi, play_media.","parameters":{"type":"object","properties":{"device":{"type":"string","description":"Device name, id, or just 'phone' if there is only one"},"action":{"type":"string","description":"A capability the device reported"},"params":{"type":"object","description":"Arguments for that action, e.g. {\"package\":\"com.spotify.music\"} or {\"to\":\"+1...\",\"body\":\"...\"}"}},"required":["device","action"]}}},
]

AGENT_TOOL_SCHEMAS = [
  {"type":"function","function":{"name":"run_shell","description":"Run a PowerShell command on the user's Windows PC and return stdout/stderr. Use this for anything the filesystem tools cannot do: starting programs, git, package managers, system queries. Dangerous commands are blocked unless the user has enabled ADMIN MODE.","parameters":{"type":"object","properties":{"command":{"type":"string","description":"The PowerShell command line"},"cwd":{"type":"string","description":"Optional working directory"}},"required":["command"]}}},
  {"type":"function","function":{"name":"install_app","description":"Install an application or package. manager is one of winget, choco, scoop, pip, npm. Prefer winget for desktop apps.","parameters":{"type":"object","properties":{"name":{"type":"string","description":"Package id or name, e.g. Git.Git or numpy"},"manager":{"type":"string","description":"winget | choco | scoop | pip | npm"}},"required":["name"]}}},
  {"type":"function","function":{"name":"gui_action","description":"Control the real mouse, keyboard and media keys. Take a screen_capture first so you know where things are. Actions: move, click, double_click, right_click, drag, scroll, type, key, hotkey, media, focus, position. action='focus' with text='<app name>' brings that window to the front - always do this before screen_capture of a specific app, or it will be hidden behind other windows. action='media' with keys='playpause'|'next'|'prev'|'stop'|'volup'|'voldown'|'mute' controls Spotify or any media player regardless of which window has focus - this is how you start or stop playback.","parameters":{"type":"object","properties":{"action":{"type":"string"},"x":{"type":"integer"},"y":{"type":"integer"},"to_x":{"type":"integer"},"to_y":{"type":"integer"},"text":{"type":"string","description":"Text for the type action"},"keys":{"type":"string","description":"Key name for 'key', or a combo like ctrl+s for 'hotkey'"},"amount":{"type":"integer","description":"Scroll amount; negative scrolls down"},"button":{"type":"string"}},"required":["action"]}}},
  {"type":"function","function":{"name":"screen_capture","description":"Take a screenshot of the user's screen so you can see what is on it before clicking. Returns an image to look at.","parameters":{"type":"object","properties":{"region":{"type":"array","items":{"type":"integer"},"description":"Optional [left, top, width, height]"}}}}},
  {"type":"function","function":{"name":"browser_open","description":"Open a URL in NeuralDock's OWN managed Chrome — a private, persistent browser separate from the user's, that runs off-screen and stays logged in to sites the user has signed into once inside it. Use this, not run_shell+chrome, for anything on the web that needs a real browser: pages that require JavaScript, and anything behind a login (Gmail, Calendar, a dashboard). It does NOT move the user's screen. Returns the page title, URL, and whether the page looks like it needs a sign-in. After opening, use browser_read to read it.","parameters":{"type":"object","properties":{"url":{"type":"string","description":"The URL to open."}},"required":["url"]}}},
  {"type":"function","function":{"name":"browser_read","description":"Read the visible text of the current page in NeuralDock's managed browser — the rendered text, not raw HTML. This is how you get information off a page you opened with browser_open, including JavaScript-rendered and logged-in pages that web_fetch cannot reach.","parameters":{"type":"object","properties":{"max_chars":{"type":"integer","description":"Cap on returned characters (default 8000)."}}}}},
  {"type":"function","function":{"name":"browser_find","description":"List the clickable and fillable elements on the current page in the managed browser — links, buttons, inputs — each with a ref you can pass to browser_click or browser_type. Use it to see what you can act on before acting.","parameters":{"type":"object","properties":{"query":{"type":"string","description":"Optional text filter, e.g. 'sign in'."}}}}},
  {"type":"function","function":{"name":"browser_click","description":"Click an element in the managed browser, identified either by a ref from browser_find or by its visible text. Acts as the signed-in user, so each click is approved on its own.","parameters":{"type":"object","properties":{"ref":{"type":"string","description":"A ref from browser_find (preferred)."},"text":{"type":"string","description":"Or the visible text of the thing to click."}}}}},
  {"type":"function","function":{"name":"browser_type","description":"Type into an input in the managed browser, identified by a ref from browser_find (or a CSS selector). Optionally press Enter after. Acts as the signed-in user, so it is approved on its own.","parameters":{"type":"object","properties":{"ref":{"type":"string"},"selector":{"type":"string"},"text":{"type":"string","description":"Text to type."},"enter":{"type":"boolean","description":"Press Enter after typing (default false)."}},"required":["text"]}}},
  {"type":"function","function":{"name":"browser_see","description":"Take a screenshot of the current page in the managed browser and return it as an image to look at — for when the layout matters or the text read is not enough. Does not touch the user's screen.","parameters":{"type":"object","properties":{}}}},
  {"type":"function","function":{"name":"hidden_desktop","description":"Drive a NATIVE Windows app on a hidden, separate desktop, without touching the user's screen. This is the LAST resort — use the managed browser for anything on the web, and gui_action on the real screen when this fails. Input here is best-effort: standard windows respond, but many modern/GPU-drawn apps ignore it. actions: 'launch' (start a program there, pass command), 'windows' (list its windows), 'see' (screenshot a window — pass hwnd, returns an image), 'click' (pass hwnd,x,y — client coords), 'type' (pass hwnd,text), 'stop'. Always 'see' after acting to confirm, because a click that silently does nothing is the normal failure here.","parameters":{"type":"object","properties":{"action":{"type":"string","description":"launch | windows | see | click | type | stop"},"command":{"type":"string","description":"For launch: the full command line, e.g. an exe path."},"hwnd":{"type":"integer","description":"Window handle from 'windows' (omit to use the largest window)."},"x":{"type":"integer"},"y":{"type":"integer"},"text":{"type":"string","description":"For type."}},"required":["action"]}}},
]

_IMAGE_ASK = re.compile(
    r"\b(create|generate|make|draw|render|design|paint|produce|redo|show me)\b[^.?!]{0,120}?"
    r"\b(image|images|picture|pictures|photo|art|artwork|box art|illustration|poster|"
    r"logo|graphic|render|mockup|wallpaper|drawing)\b"
    r"|\bcomfy ?ui\b[^.?!]{0,60}\b(create|generate|make|pass|run)\b"
    r"|\b(create|generate|make|pass|run)\b[^.?!]{0,60}\bcomfy ?ui\b", re.I)
_NOT_IMAGE = re.compile(r"\b(script|code|function|class|resize|compress|convert|crop|"
                        r"parse|python|html|css|svg file)\b", re.I)
IMAGE_DIRECTIVE = (
    "\n\n[NeuralDock: this request is for a PICTURE. Your FIRST action is generate_image "
    "- do not list folders, read files, search or browse first. Write each prompt as a "
    "description of what the picture SHOWS (subject, composition, style, colours, lighting, "
    "and any exact words in quotes), about 60-120 words, not as instructions to you. Several "
    "pictures (e.g. five boxes) = one generate_image call each. The image model can spell "
    "short text in quotes but cannot copy a logo from a photo - say so briefly if asked.]")


def wants_image(text: str) -> bool:
    """Is this chat message asking for a picture to be made?"""
    t = (text or "")[-1500:]
    return bool(_IMAGE_ASK.search(t)) and not _NOT_IMAGE.search(t)


def tool_generate_image(a):
    """Generate an image from the chat, via the same pipeline the IMAGE GEN tab uses.

    Chat had NO image tool at all. Asking "create an image of star wars" left the
    model with only file and web tools, so it went poking around ComfyUI folders
    and lecturing the user about missing directories and PyTorch versions instead
    of producing a picture.

    run_comfyui_workflow() already frees VRAM and starts ComfyUI if it is not
    running, so this needs no separate launch step -- it just has to exist.
    """
    prompt = str(a.get("prompt") or "").strip()
    if not prompt:
        return "[ERROR generate_image: a prompt is required]"
    try:
        w = max(64, (int(a.get("width", 1024)) // 64) * 64)     # SDXL needs /64
        h = max(64, (int(a.get("height", 1024)) // 64) * 64)
        steps = max(1, min(int(a.get("steps", 20)), 80))
        cfg = float(a.get("cfg", 7.0))
    except (TypeError, ValueError) as e:
        return f"[ERROR generate_image: bad numeric argument: {e}]"

    job_id = str(uuid.uuid4())[:8]
    with _lock:
        _gen_jobs[job_id] = {"status": "starting", "result": None, "error": None}
    ckpt = a.get("checkpoint") or default_image_model()
    try:
        workflow = build_image_workflow(prompt, str(a.get("negative") or ""),
                                        w, h, steps, cfg, ckpt)
    except Exception as e:
        return (f"[ERROR generate_image: could not build the workflow: {e}. "
                "Check that an image checkpoint is installed in the Setup tab.]")

    log(f"generate_image: {prompt[:70]}", "info")
    try:
        # Blocking on purpose: the agent loop needs the result in this round.
        run_comfyui_workflow(workflow, job_id, "image")
    except Exception as e:
        return f"[ERROR generate_image: {e}]"

    with _lock:
        rec = dict(_gen_jobs.get(job_id) or {})
    if rec.get("status") == "done":
        path = rec.get("path") or ""
        return (f"[IMAGE job={job_id}] Generated and saved to: {path}\n"
                "The image is already shown to the user. Do NOT describe it in "
                "detail or claim to have inspected it - you cannot see it. Just "
                "confirm it was created and ask if they want changes.")
    err = rec.get("error") or "generation failed with no error message"
    return f"[ERROR generate_image: {err}]"


_design_reviewer = None

# ─── NeuralDock's own managed browser ─────────────────────────────────────────
# One persistent, logged-in, off-screen Chrome driven over CDP. Lazy singleton,
# same shape as the design reviewer: a missing package or missing browser
# degrades to a clear message, never an exception mid tool round.
_nd_browser = None
def nd_browser():
    global _nd_browser
    if _nd_browser is None:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from nd_browser import NDBrowser
            profile = str(_CONFIG_DIR / "nd_browser_profile")
            port = int(_config.get("nd_browser_port", 9333))
            headless = bool(_config.get("nd_browser_headless", False))
            chrome = _config.get("design_browser", "") or ""
            _nd_browser = NDBrowser(profile_dir=profile, port=port,
                                    chrome_path=chrome, headless=headless, log=log)
        except Exception as e:
            log(f"Managed browser unavailable: {e}", "warn")
            _nd_browser = False
    return _nd_browser or None

# ─── The hidden desktop ───────────────────────────────────────────────────────
# A second Windows desktop, for driving a native app without touching the user's
# screen. The last and most limited rung — the managed browser handles the web;
# this is only for a native app with no web version. Lazy singleton, same shape.
_nd_desktop = None
def nd_desktop():
    global _nd_desktop
    if _nd_desktop is None:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from nd_desktop import HiddenDesktop
            _nd_desktop = HiddenDesktop(log=log)
        except Exception as e:
            log(f"Hidden desktop unavailable: {e}", "warn")
            _nd_desktop = False
    return _nd_desktop or None

def design_reviewer():
    """Lazy singleton. Missing module or missing browser must degrade to a clear
    message, never an exception in the middle of a tool round."""
    global _design_reviewer
    if _design_reviewer is None:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from nd_design_review import DesignReview
            _design_reviewer = DesignReview(_config, log=log)
        except Exception as e:
            log(f"Design review unavailable: {e}", "warn")
            _design_reviewer = False
    return _design_reviewer or None


def tool_design_review(a):
    """Render an HTML file and tell the model what it ACTUALLY looks like.

    The agent has always written UI blind: emit HTML, never look, declare
    success. That is the root of every 'why does this look generic or broken'
    complaint -- not a lack of taste, a lack of eyes. This closes the loop:

        render (headless Chrome) -> deterministic checks -> vision critique

    Deterministic findings come back FIRST and are stated as facts, because a
    small vision model asked "does this look good" will write a confident,
    admiring review of a blank white page.
    """
    dr = design_reviewer()
    if not dr:
        return ("[design_review unavailable: nd_design_review.py is missing. "
                "Continue without it.]")
    if not dr.available():
        return ("[design_review needs Chrome or Edge and neither was found. "
                "Set design_browser in neuraldock_config.json to a chrome.exe or "
                "msedge.exe path, or continue without it.]")
    path = str(a.get("path") or "").strip().strip('"').strip("'")
    if not path:
        return "[design_review needs a path to an .html file]"
    # Measured: handed app/models.py it rendered the file in Chrome -- which
    # shows source as plain text -- measured its colours and wrote a confident
    # design review of a Python module. Handed a .png it did the same. A browser
    # will render almost anything, so the browser cannot be the judge of whether
    # a file is reviewable.
    why = path_problem(path, want="file")
    if why:
        return "[Cannot review] " + why
    ext = Path(path).suffix.lower()
    if ext not in (".html", ".htm"):
        return (f"[Cannot review] design_review renders a PAGE, and {Path(path).name} "
                f"is a {ext or 'no-extension'} file. It was not reviewed. A browser "
                f"will display source code or an image as if it were a page, so the "
                f"result would be a critique of nothing. Point this at the .html file "
                f"instead.")

    def _vision(b64, prompt):
        vm = model_roster().get("vision", {}).get("model")
        if not vm:
            return ("[No vision model installed, so only the automated checks ran. "
                    "`ollama pull qwen2.5vl:7b` enables the visual critique.]")
        return ollama_chat(vm, [{"role": "user", "content": prompt, "images": [b64]}],
                           timeout=600)

    try:
        # The model often omits `brief`; fall back to the one this job is
        # working to, parked on the thread alongside the context profile.
        brief = str(a.get("brief") or "") or getattr(_job_ctx, "brief", "")
        # If this job is a reskin, the file it was supposed to preserve is
        # parked on the thread. Handing it to the reviewer is what turns
        # "needs more hover states" into "this is not the app any more".
        source = str(a.get("source") or "") or getattr(_job_ctx, "reskin_src", "")
        res = dr.review(path, brief=brief, vision_fn=_vision, source_path=source or None)
        # Publish the contrast verdict for the iteration gate. It is measured in
        # a real browser and cannot be re-derived from the file, so if it does
        # not travel from here it is lost -- and the loop would go on finishing
        # turns on pages whose text cannot be read.
        _c = next((f for f in (res.get("findings") or [])
                   if f.get("code") in ("contrast-regression", "contrast-fail")), None)
        _job_ctx.last_contrast = (
            (_c["msg"] + " Fix the colours, then run design_review again.")
            if _c else "")
        # Same for shape. Contrast and layout are the two measured regressions,
        # and a page can pass one while failing the other -- the reskin that
        # fixed its colours is the same one that blew a 10px heading to 41.6px.
        _l = next((f for f in (res.get("findings") or [])
                   if f.get("code") == "layout-regression"), None)
        _job_ctx.last_layout = (
            (_l["msg"] + " Then run design_review again.") if _l else "")
        out = dr.as_text(res)
        shots = [s["png"] for s in res.get("shots", []) if s.get("ok")]
        if shots:
            log(f"design_review rendered {len(shots)} shot(s) of {Path(path).name}", "ok")
        # Describe with the small vision model; JUDGE with the strong one. The
        # 7B told us a white page used "hot magenta and cyan" -- it can see, but
        # it cannot be trusted to assess.
        facts = "\n".join(f"- {f['msg']}" for f in (res.get("findings") or [])) or "none"
        pal = ", ".join(f"{h} {int(s*100)}%" for h, s in (res.get("palette") or [])[:5])
        facts = f"- palette on screen: {pal or 'not measured'}\n- {res.get('states','')}\n" + facts
        try:
            outline = file_outline(Path(path).read_text(encoding="utf-8",
                                                        errors="replace").splitlines())[:1200]
        except Exception:
            outline = ""
        # Do not spend a model call judging a render that did not happen.
        # Measured: given a path that does not exist, this failed correctly and
        # then produced a full SECOND OPINION about the file it could not find.
        if not shots:
            return out + (chr(10) + chr(10)
                          + "Nothing was rendered, so there is nothing to judge. "
                          + "Fix the path or the page first.")
        out += judge_design(facts, res.get("critique", ""), brief, outline)
        return out
    except Exception as e:
        log(f"design_review failed: {e}", "error")
        return f"[design_review error: {e}]"


# ─── UI house style ───────────────────────────────────────────────────────────
# A local model asked to be "sleek and modern" produces a centred hero and three
# cards every time. Side by side against a hand-designed page, the difference was
# never creativity -- it was restraint, structure and STATES. Nobody asked it for
# an empty state, so it never invented one.
#
# The rules live in a vault note the user can edit, not in this file. Only the
# block between the ND:RULES markers is injected, so the note can be long and
# readable while the prompt stays small enough for an 8K window.
_UI_STYLE_CACHE = {"mtime": 0, "text": "", "path": ""}
UI_STYLE_MAX = 2200

_UI_TASK_RE = re.compile(
    r"\b(ui|interface|front\s*end|frontend|page|website|web\s*app|dashboard|"
    r"layout|design|screen|html|css|landing|theme|styling|restyle|redesign)\b", re.I)
# Words that mean a UI deliverable on their own, and words that only do in
# company. Measured 2026-09-25: "a right-click at a fixed screen point" in a
# Python automation prompt matched `screen`, loaded the UI house style, asked
# the user to pick a UI model -- and the flag is kept on the session, so every
# later request in that tab would have been a "UI job" too.
_UI_STRONG_RE = re.compile(
    r"\b(ui|front\s*end|frontend|website|web\s*app|web\s*page|webpage|dashboard|"
    r"html|css|landing\s*page|styling|restyle|redesign|gui|user\s+interface)\b", re.I)
_UI_WEAK_RE = re.compile(
    r"\b(interface|page|layout|design|screen|theme|landing|splash|animation|palette|"
    r"hover|typography|font|sleek|modern|visual|reimagin(?:e|ed|ing))s?\b", re.I)


def is_ui_task(text):
    """A UI job: one strong word, or two DIFFERENT weak ones."""
    t = text or ""
    if _UI_STRONG_RE.search(t):
        return True
    return len({m.group(1).lower() for m in _UI_WEAK_RE.finditer(t)}) >= 2


def ui_style_paths():
    p = str(_config.get("ui_style_note") or "").strip()
    out = [Path(p)] if p else []
    root = str(_config.get("obsidian_root") or "")
    vault = str(_config.get("obsidian_vault") or "")
    if root and vault:
        out.append(Path(root) / vault / "System and Applications" / "04 NeuralDock"
                   / "NeuralDock - UI House Style.md")
    out.append(Path(__file__).parent / "ui_house_style.md")
    return out


def ui_style_rules():
    """The injectable rules block. Re-read when the note changes on disk, so the
    user can edit the vault note and see the effect on the next request."""
    for path in ui_style_paths():
        try:
            if not path.is_file():
                continue
            mt = path.stat().st_mtime
            if _UI_STYLE_CACHE["path"] == str(path) and _UI_STYLE_CACHE["mtime"] == mt:
                return _UI_STYLE_CACHE["text"]
            raw = path.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"<!--\s*ND:RULES\s*-->(.*?)<!--\s*/ND:RULES\s*-->", raw, re.S)
            text = (m.group(1) if m else "").strip()
            if len(text) > UI_STYLE_MAX:
                text = text[:UI_STYLE_MAX].rsplit("\n", 1)[0] + "\n[...house style truncated]"
            _UI_STYLE_CACHE.update({"mtime": mt, "text": text, "path": str(path)})
            if text:
                log(f"UI house style loaded ({len(text)}c) from {path.name}", "info")
            return text
        except Exception as e:
            log(f"UI house style unreadable at {path}: {e}", "warn")
    return ""


def ui_style_block(task_text="", force=False):
    """House style, wrapped, or '' when this is not a UI job."""
    if not _config.get("ui_house_style_enabled", True):
        return ""
    if not force and not is_ui_task(task_text):
        return ""
    rules = ui_style_rules()
    if not rules:
        return ""
    return ("\n\nHOUSE STYLE — these are requirements, not suggestions:\n"
            + rules + "\n")


def installed_models():
    try:
        return {n.split(":")[0].lower(): n for n in _ollama_sizes()}
    except Exception:
        return {}


def resolve_installed(name):
    """Exact tag if present, else the same family under a different tag."""
    if not name:
        return ""
    inst = installed_models()
    sizes = _ollama_sizes()
    if name in sizes:
        return name
    return inst.get(name.split(":")[0].lower(), "")


# ─── Per-task model choice ────────────────────────────────────────────────────
# Auto-routing swapped models silently and, on a 16.3 GB card, could put two
# large models in flight at once -- three runs died with "NeuralDock restarted
# while this request was running". Asking is both safer and what the user wants:
# they pick, ND does not swap behind their back.
#
# The question is plain text, so it needs no UI work. The reply ("2", or a model
# name) resumes the ORIGINAL task, which works because the session already
# remembers it -- see remember_ctx/recall_ctx.
TASK_KINDS = {
    "ui": "UI / front-end build",
    "code": "general coding",
    "research": "reading and research",
}


def task_candidates(kind):
    """Installed models offered for a task kind, in config order."""
    cfg = _config.get("task_models") or {}
    want = cfg.get(kind) or []
    out = []
    for entry in want:
        name = entry if isinstance(entry, str) else str(entry.get("model", ""))
        note = "" if isinstance(entry, str) else str(entry.get("note", ""))
        real = resolve_installed(name)
        if real:
            prof = model_profile(real)
            bits = [f"{prof['num_ctx']//1024}K ctx"]
            if note:
                bits.append(note)
            # num_ctx rides along so callers can answer "which of these could
            # actually hold this file?" without re-resolving the profile.
            out.append({"model": real, "note": ", ".join(bits),
                        "num_ctx": prof["num_ctx"]})
    return out


def model_choice_prompt(kind, cands, task):
    lines = [f"Which model should handle this {TASK_KINDS.get(kind, kind)}?", ""]
    for i, c in enumerate(cands, 1):
        lines.append(f"  {i}. {c['model']}  —  {c['note']}")
    lines += ["",
              "Reply with the number or the model name and I will run the task with it.",
              "Add \"always\" (e.g. \"2 always\") to stop being asked for this kind of task."]
    if task:
        first = next((l.strip() for l in task.splitlines() if l.strip()), "")
        lines += ["", f"Task: {first[:120]}"]
    return "\n".join(lines)


_ALWAYS_RE = re.compile(r"\balways\b", re.I)


def parse_model_choice(text, cands):
    """Returns (model, always) or (None, False). Accepts '2', '2 always',
    a full tag, or a distinctive fragment of one."""
    t = (text or "").strip()
    if not t or not cands:
        return None, False
    always = bool(_ALWAYS_RE.search(t))
    # Strip the keyword before looking for a number, so "always 2" works as
    # well as "2 always".
    bare = _ALWAYS_RE.sub(" ", t).strip()
    m = re.match(r"^\s*#?(\d{1,2})\b", bare)
    if m:
        i = int(m.group(1)) - 1
        if 0 <= i < len(cands):
            return cands[i]["model"], always
        return None, False
    low = bare.lower()
    for c in cands:
        if c["model"].lower() in low:
            return c["model"], always
    # Fragment match, LONGEST stem first. Shortest-first silently picked the
    # wrong model: the stem "qwen3" (from qwen3:14b) matches inside the string
    # "qwen3coder-q3xl", so asking for the coder returned the general model.
    ranked = sorted(cands, key=lambda c: -len(c["model"].split(":")[0]))
    for c in ranked:
        stem = c["model"].split(":")[0].lower()
        for frag in (stem, stem.split("/")[-1]):
            # Must not be a prefix of a longer word, or "qwen3" swallows
            # "qwen3coder". Require the text to end there or continue with a
            # non-word character.
            if len(frag) >= 4:
                for mm in re.finditer(re.escape(frag), low):
                    tail = low[mm.end():mm.end() + 1]
                    if tail == "" or not (tail.isalnum() or tail in "-_."):
                        return c["model"], always
    return None, False


def design_model_for(model, ui_job):
    """Pick the model for a UI job. Returns (model, reason_or_empty).

    Only ever swaps UPWARD in context, only for UI work, and only to a model
    that is actually installed. `ui_design_model: ""` in the config disables it.
    """
    if not ui_job:
        return model, ""
    want = str(_config.get("ui_design_model", "qwen3:14b")).strip()
    if not want:
        return model, ""
    want = resolve_installed(want)
    if not want or want.lower() == str(model).lower():
        return model, ""
    have_ctx = model_profile(model)["num_ctx"]
    want_ctx = model_profile(want)["num_ctx"]
    if want_ctx <= have_ctx:
        return model, ""      # no gain; leave the user's choice alone
    return want, (f"UI job: routed to {want} ({want_ctx} ctx) instead of {model} "
                  f"({have_ctx} ctx) so it can hold the source in context. "
                  f"Set ui_design_model to \"\" to disable.")


def critic_model():
    """The model that JUDGES a design. Deliberately separate from the one that
    describes the screenshot: qwen2.5vl:7b can see, but it told us a plain white
    page used 'hot magenta and cyan'. Let the small model describe, and a strong
    model judge the measured facts."""
    want = str(_config.get("design_critic_model", "qwen3:14b")).strip()
    return resolve_installed(want) if want else ""


CRITIC_PROMPT = """You are a demanding senior UI designer. Judge this page HARSHLY.

MEASURED FACTS (from a real browser render — these are true, not opinions):
{facts}

WHAT A VISION MODEL SAW IN THE SCREENSHOT:
{seen}

THE BRIEF IT WAS BUILT TO:
{brief}

STRUCTURE (headings and landmarks found in the DOM):
{outline}

Answer in four short sections. Be specific and blunt; vague praise is useless.

VERDICT: shippable / promising / basic / broken — one line, and say which.
BIGGEST WEAKNESS: the single thing most responsible for it looking amateur.
GENERIC: name the template cliches present (centred hero, three cards, flat
colour blocks with an emoji in the middle, evenly spaced everything).
FIX FIRST: one concrete, specific instruction that would most improve it.
"""


def judge_design(facts, seen, brief, outline):
    """Second opinion from the strongest available text model."""
    cm = critic_model()
    if not cm:
        return ""
    try:
        txt = ollama_chat(cm, [{"role": "user", "content": CRITIC_PROMPT.format(
            facts=facts or "(none)", seen=seen or "(no screenshot description)",
            brief=brief or "(no brief given)", outline=outline or "(none)")}],
            timeout=600)
        return f"\nSECOND OPINION ({cm}):\n{txt.strip()}"
    except Exception as e:
        log(f"design critic failed: {e}", "warn")
        return ""


# A reply that is nothing but a menu index: "1", "#2", "3 always". Two digits
# max, so "1024" is a value the user typed, not a choice.
_BARE_CHOICE_RE = re.compile(r"\s*#?\d{1,2}\s*(?:always)?\s*", re.I)

# "reskin as an edit" / "as an edit" / "do it as an edit" -- the phrase the
# refusal message tells the user to say.
_RESKIN_EDIT_RE = re.compile(
    r"\b(?:re-?skin\s+(?:it\s+)?as\s+an?\s+edit"
    r"|(?:do|run)\s+it\s+as\s+an?\s+edit"
    r"|as\s+an\s+edit\b"
    # A request that already DESCRIBES the edit approach must not be refused
    # and told to ask for the edit approach. A prompt saying "you are adding a
    # CSS layer to a working app" has made the choice the guard exists to
    # offer; blocking it is the guard arguing with an instruction that already
    # agrees with it.
    r"|(?:css|style|theme|override)\s+(?:layer|overlay)"
    r"|do\s+not\s+rebuild"
    r"|append\s+(?:one\s+)?(?:a\s+)?<?style)", re.I)

_reskin_mod = None


def reskin_mod():
    global _reskin_mod
    if _reskin_mod is None:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            import nd_reskin
            _reskin_mod = nd_reskin
        except Exception as e:
            # Say so. An import failure that returns None silently would
            # disable the guard entirely -- which is how a 185 KB app came
            # back as a 6 KB brochure with nothing in the log.
            log(f"Reskin guard unavailable: {e}", "warn")
            _reskin_mod = False
    return _reskin_mod or None


_build_plan_mod = None

def build_plan_mod():
    global _build_plan_mod
    if _build_plan_mod is None:
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            import nd_build_plan
            _build_plan_mod = nd_build_plan
        except Exception as e:
            log(f"Auto-split unavailable: {e}", "warn")
            _build_plan_mod = False
    return _build_plan_mod or None


# BEST-OF-N.
#
# The measurement that motivates this: T2's binding check, "they import
# together", passes 2 runs in 6. ND takes one sample and keeps it, whatever it
# is. If it took three and kept the first that verifies, the arithmetic on
# independent attempts is 1 - (4/6)^3 = 70%.
#
# Attempts are not fully independent -- a model that misreads the task fails the
# same way three times -- so expect less than 70% and more than 33%. The cost is
# wall clock on generation only, and ONLY when the first attempt is imperfect:
# a clean first sample exits immediately and costs nothing.
#
# This is the one lever left after the quant experiment. num_ctx cannot free
# VRAM (weights dominate) and a smaller quant reasons worse than it saves. What
# is left is spending time, which is the trade that was explicitly asked for.
BEST_OF_N = 3               # attempts per file; 1 disables
BEST_OF_PERFECT = 100       # stop early at this score


def _module_name(path, workspace):
    """Dotted module name for a .py inside the workspace, or None.

    Walks up while __init__.py exists, so app/wishlist/router.py becomes
    app.wishlist.router rather than a guess based on the path depth.
    """
    try:
        p, ws = Path(path).resolve(), Path(workspace).resolve()
        rel = p.relative_to(ws)
    except (OSError, ValueError):
        return None
    if p.suffix != ".py":
        return None
    parts = list(rel.parts)
    parts[-1] = parts[-1][:-3]
    if parts[-1] == "__init__":
        parts.pop()
    # every parent must be a real package or the dotted name is fiction
    cur = ws
    for part in parts[:-1]:
        cur = cur / part
        if not (cur / "__init__.py").is_file():
            return None
    return ".".join(parts) if parts else None


def _imports_cleanly(path, workspace, timeout=90):
    """Can Python actually import this module? (ok, first error line).

    ok is None when the question does not apply -- not a .py, not inside a
    package.

    ONE module. This is not the check T2 scores as "they import together" --
    that one imports the whole build in a single interpreter, which is where
    cross-file disagreement actually shows up. See _imports_together().
    """
    mod = _module_name(path, workspace)
    if not mod:
        return None, ""
    try:
        r = subprocess.run([_project_python(workspace), "-c", "import " + mod],
                           cwd=str(workspace), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except Exception as e:
        return None, str(e)[:120]
    if r.returncode == 0:
        return True, ""
    lines = [l for l in ((r.stdout or "") + (r.stderr or "")).splitlines() if l.strip()]
    return False, (lines[-1][:160] if lines else f"exit {r.returncode}")


# Import the whole build at once, and give the model its own traceback back.
#
# ND verified files ONE AT A TIME and never together, which is precisely the gap
# the benchmark measures. Across six T2 runs on 2026-09-05 every shape check
# passed 6/6 -- a real model, a real schema, a router with routes, each file
# individually correct -- while `they import together` sat at 2/6. The
# contradiction only ever existed BETWEEN files, and nothing looked there.
#
# The four failures were all contract errors: a SQLAlchemy Mapped[] annotation,
# a FastAPI response-field type, pydantic `regex` removed in favour of
# `pattern`, and a Session used as a response field. Every one surfaces on a
# real import and none survive being shown the traceback.
NL = chr(10)        # heredocs in this project eat a literal backslash-n
BUILD_IMPORT_GATE = True
BUILD_IMPORT_REPAIRS = 3        # see below: some errors surface one at a time
BUILD_IMPORT_TIMEOUT = 240


def _module_name_loose(path, workspace):
    """Dotted name for a .py in the workspace, WITHOUT requiring __init__.py.

    _module_name() insists every parent holds an __init__.py, on the reasoning
    that otherwise "the dotted name is fiction". That has been false since
    Python 3.3: namespace packages import perfectly well without one. The T2
    build writes models/schemas/router and no __init__.py, so the strict
    resolver returned None for all three, _imports_together() reported
    "cannot be asked", and the gate sat silent through four live runs while the
    benchmark's own checker imported the same files without difficulty.

    The import itself is the test. If the name really is fiction, the import
    says so, which is the answer we wanted anyway.
    """
    try:
        p, ws = Path(path).resolve(), Path(workspace).resolve()
        rel = p.relative_to(ws)
    except (OSError, ValueError):
        return None
    if p.suffix != ".py":
        return None
    parts = list(rel.parts)
    parts[-1] = parts[-1][:-3]
    if parts[-1] == "__init__":
        parts.pop()
    if not parts or any(not x.isidentifier() for x in parts):
        return None
    return ".".join(parts)


# The suite gate: a FINAL check that the existing tests still pass, with more
# than one attempt to put them right.
#
# try_placed_edits already checks the suite per step and gives one retry. It is
# not enough. Measured on T3, 2026-09-05: the model broke the existing suite in
# 8 of 19 runs (42%), and across three samples 42-62% -- by far the largest
# failure in the benchmark, and the one that matters most in real use. An agent
# that breaks your working tests half the time is worse than one that writes a
# wrong function, because the wrong function is visible.
#
# The per-step retry detects the breakage, tries once, records a note and
# carries on. The integration gate showed what the missing piece is: loop until
# clean. One repair pass took T2's imports to 71%; three took it to 94%.
SUITE_GATE = True
# Dropped to 1 on 2026-09-05, restored to 2 on 2026-09-06. The prediction
# written here before that run was: suite intact stays at 100%, the score is
# unchanged, reverting runs get MATERIALLY FASTER. Measured, T3, 18 runs each:
#
#   2 passes  n=18  score 4.56 +/- 3.09  secs 410  suite intact 18/18
#   1 pass    n=19  score 4.11 +/- 2.56  secs 518  suite intact 19/19
#
# The time axis went the wrong way: one pass came out 26% SLOWER, not faster
# (t = 1.09, not significant). The reasoning error was costing a repair pass at
# ~200s and assuming removing one saves that. A repair pass only runs when
# something regressed, and removing it produces MORE reverts -- and a reverted
# run still pays for the whole build. Wall time here is dominated by how long
# the model spends writing code, not by the gate.
#
# Score -0.45 (t = -0.48, ns) and suite intact 100% both ways: a null on every
# axis. Back to 2 not because it measured better, but because the reason for
# changing it was refuted and 2 is the config the published numbers describe.
SUITE_GATE_REPAIRS = 2
# How many passes the NEW test gets. This was hardcoded to a single retry with
# no constant and no config key, which is how it escaped notice: the suite gate
# had a budget and a comment history, the new-test path had neither.
#
# 2026-09-10, reading the T3 replies rather than the scorecards. Every failing
# run had already built the whole feature -- schema, endpoint, service function
# and a test -- and lost all of it to one unfixed assertion:
#
#   ok  schemas.py: add a StatsOut schema ...
#   ok  public.py: add a GET /api/stats endpoint ...
#   ok  items.py: add a stats function ...
#   ok  test_public.py: add a test ...
#       -> the new test still fails after one fix attempt:
#          AttributeError: 'ScalarResult' object has no attribute ...
#
# That is a real SQLAlchemy error with a traceback naming the line, which is
# exactly the input a second pass can act on. The scorecard reported "added
# tests: 50 -> 50" because the change was reverted, not because no test was
# written -- and that misreading is what sent rule 10 after a problem that did
# not exist.
#
# The precedent is directly above: the integration gate took T2's imports from
# 71% to 94% by looping until clean instead of trying once. Same shape here.
#
# PREDICTION, written before the run: the 2/9 runs are the ones with a fixable
# traceback, so score should rise and the bimodal 2/9-or-9/9 split should soften.
# Time should rise too. If score is flat and only time moves, the failures are
# not fixable by this model and the budget should go back to 1.
#
# MEASURED, T3, qwen3-coder:30b, 3 runs each, thinking off:
#
#   1 pass   score 4.3 +/- 4.0   (2, 2, 9)   21.0 min   rounds 15, 14, 14
#   3 passes score 2.0 +/- 0.0   (2, 2, 2)   31.0 min   rounds 23, 18, 20
#
# The prediction was wrong and the falsifier fired. Time rose 48% and the 9/9
# run did not appear. Be careful about the score, though: the baseline mean came
# entirely from one run in three, and drawing three 2s at a 1-in-3 success rate
# happens 30% of the time. That is absence of benefit, not proof of harm.
#
# The mechanism the rounds point at: every extra pass is another edit to the
# file, another chance to regress the existing suite, and SUITE_REVERT_ON_FAIL
# then discards the whole change. More attempts bought more opportunities to
# trigger the revert, not more fixes. That is the opposite of the integration
# gate above, where repairs are cheap because a failed import reverts nothing.
#
# Back to 1. The loop, the config key and the honest attempt count stay -- they
# cost nothing at 1 and make the next experiment a config change rather than a
# code change.
NEWTEST_REPAIRS = int(_config.get("newtest_repairs", 1))
# Put the tree back when the repair cannot. See the note at the revert.
SUITE_REVERT_ON_FAIL = True
# Should a failing NEW test still trigger the revert? Default yes, i.e. keep the
# old count-based rule. Turning this on compares test NAMES instead, so only a
# name that was green and is now red counts as damage.
#
# MEASURED, T3, qwen3-coder:30b, 3 runs each, thinking off:
#
#   off (counts)  score 4.3 +/- 4.0  (2, 2, 9)  21.0 min  suite intact 3/3
#   on  (names)   score 4.0 +/- 3.5  (2, 8, 2)  38.5 min  suite intact 2/3
#
# The mechanism WORKS and the middle run proves it: a run that scored 2/9 under
# the count rule -- whole feature reverted -- scored 8/9 with a working endpoint,
# correct by_format and by_decade, visibility respected, router and schema and
# service edited, test added. That is a real feature the old policy destroyed.
#
# It is still off, for three reasons. Score was flat (-0.3, well inside a
# +/- 3.5 spread that one run of three can move by 2.3). Time rose 83%, because
# runs that used to revert early now run to completion. And "nothing that worked
# before is broken" fell from 3/3 to 2/3 -- an invariant that had held across
# every run in this project.
#
# The honest summary is that the gate and the benchmark now disagree about the
# word "broken". By name, nothing that worked before broke: the red test did not
# exist yesterday. By count, the model left the suite red and a user running it
# sees a failure. Both readings defend themselves, and the benchmark's is the
# one that governs, because relaxing the referee to score better would make
# every number in this project worthless.
#
# Worth revisiting if T3 ever gets enough runs to separate 4.0 from 4.3, or if
# the new test can be made to pass reliably -- at which point the revert stops
# mattering because there is nothing left to revert.
SUITE_REVERT_NEWTEST_OK = bool(_config.get("suite_revert_newtest_ok", False))


def _newtest_ok():
    """The live value. The constant above is evaluated at import, before
    load_config() runs in main(), so it is always False and the config key had
    no effect at all (found 2026-10-18, while setting it for a 27B T3 arm)."""
    return bool(_config.get("suite_revert_newtest_ok", SUITE_REVERT_NEWTEST_OK))

# A test nobody calls is not a test. See _unregistered_tests() for why nothing
# else catches this: the suite passes, the count is unchanged and the exit code
# is 0, so there is no failure for a repair loop to work from.
TEST_REGISTRY_GATE = True
TEST_REGISTRY_REPAIRS = 2

# When this process started. A config edit only takes effect on restart, so a
# result stamped with a gate setting is only trustworthy if this timestamp is
# LATER than the edit. See _gate_config().
PROCESS_STARTED = time.time()


_gate_log = {}      # req_id -> what the gates actually DID on that run


def _gate_record(req_id, gate, **kw):
    """Record what a gate did, so the run's result can state it as fact.

    The gap this closes: whether a run was reverted existed only as a console
    line and had to be INFERRED afterwards from an empty git diff. That proxy
    is not sound -- a run that reverted and a run where the model simply did
    nothing both leave the tree unchanged -- and the two counts disagreed: a
    published sample quoted 7 reverts of 18 where the diffs showed 2.
    """
    if not req_id:
        return
    with _lock:
        _gate_log.setdefault(req_id, {}).setdefault(gate, {}).update(kw)


_orig_by_req = {}          # req_id -> {path: content as it was before this run}
_created_by_req = {}       # req_id -> {path} of files that did not exist before this run
ORIG_MAX_FILES = 300       # a run that touches more than this is not a normal edit


def _remember_original(req_id, path):
    """Record a file as it was, the FIRST time this run writes to it.

    The gap this closes, found 2026-09-07 by the gate ledger disagreeing with
    the git diff on one run in 28: originals were captured from `plan.steps`
    only -- the files the PLAN names. But the suite-repair and import-repair
    passes call process_ai_response_with_tools, which may edit_file ANY file,
    and those edits were never recorded. A repair pass edited app/routers/admin.py,
    which was not in the plan, so the revert could not put it back: the reply
    promised nothing was left half-applied while one file still carried a
    change, and a green suite afterwards hid it completely.

    Capturing here, at the point of WRITING, covers every pass and every path
    into a file rather than only the planned ones.

    Files that do not exist yet are deliberately skipped -- creations are undone
    by the census in _remove_created(), and recording an empty "original" for
    them would make the revert write empty files instead of deleting them.
    """
    if not req_id or not path:
        return
    try:
        fp = Path(path)
        key = str(fp.resolve())
        if not fp.is_file():
            # Created by this run. Remember THAT, so a later edit of it does not
            # record ND's own first draft as "the original" -- measured
            # 2026-09-25: a file written and then repaired in one job was
            # reported as "Changed: build_hole.py (+12 -2 lines)" instead of new.
            with _lock:
                if key not in _orig_by_req.get(req_id, {}):
                    _created_by_req.setdefault(req_id, set()).add(key)
            return
    except OSError:
        return
    with _lock:
        if key in _created_by_req.get(req_id, set()):
            return
        seen = _orig_by_req.setdefault(req_id, {})
        if key in seen or len(seen) >= ORIG_MAX_FILES:
            return
    try:
        # Read OUTSIDE the lock: every other holder of _lock does trivial dict
        # work, and file I/O under it would serialise the whole server.
        body = fp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    with _lock:
        _orig_by_req.setdefault(req_id, {}).setdefault(key, body)


def _originals_peek(req_id):
    """A run's originals, WITHOUT discarding them (the revert path takes them)."""
    if not req_id:
        return {}
    with _lock:
        return dict(_orig_by_req.get(req_id) or {})


def change_summary(req_id, tool_calls, wanted_change=False):
    """One line saying what this job ACTUALLY changed on disk, measured.

    Why: the reply is the model's account, and on 2026-09-25 three jobs in a row
    ended "done" or with a confident report while the file was unchanged; each
    time it took reading the file to find out. This line is computed from the
    disk against each file's content before the job's first write, so it cannot
    be talked into being wrong. '' when the job neither wrote nor was asked to.
    """
    import difflib
    attempted = any((r.get("tool") or r.get("name")) in WRITE_TOOLS for r in tool_calls or [])
    if not attempted and not wanted_change:
        return ""
    orig = _originals_peek(req_id)
    with _lock:
        created = set(_created_by_req.get(req_id) or ())
    parts = []
    for p in _written_paths(tool_calls):
        try:
            fp = Path(p.rsplit(" (", 1)[0])       # entries read "path (1,234 bytes)"
            now = fp.read_text(encoding="utf-8", errors="replace")
            key = str(fp.resolve())
        except OSError:
            continue
        if key in orig and key not in created:
            before = orig[key]
            if before == now:
                continue                      # written, but back to what it was
            add = rem = 0
            for ln in difflib.ndiff(before.splitlines(), now.splitlines()):
                if ln.startswith("+ "):
                    add += 1
                elif ln.startswith("- "):
                    rem += 1
            parts.append(f"{fp.name} (+{add} -{rem} lines)")
        else:
            parts.append(f"{fp.name} (new, {now.count(chr(10)) + (0 if now.endswith(chr(10)) else 1)} lines)")
    if not parts:
        return "Changed: nothing - no file is different from before this job."
    return "Changed: " + ", ".join(parts)


def _originals_take(req_id):
    """Read and discard a run's originals. Discarding keeps this bounded."""
    if not req_id:
        return {}
    with _lock:
        _created_by_req.pop(req_id, None)
        return _orig_by_req.pop(req_id, {})


def _gate_take(req_id):
    """Read and discard a run's gate record. Discarding keeps this bounded."""
    if not req_id:
        return None
    with _lock:
        return _gate_log.pop(req_id, None)


def _gate_config():
    """What the RUNNING process is actually using.

    Read from live module state, never by parsing the source file. On
    2026-09-06 SUITE_GATE_REPAIRS was edited from 1 to 2 while ND was still up;
    a file-read stamp would have recorded 2 for every run until the restart,
    while the process was in fact still executing 1.

    The gap this closes: results already stamp the GPU driver and the checker
    version, but nothing recorded which gates were live. Reconstructing that
    from memory of when a constant was flipped is exactly the unverifiable
    provenance the machine stamp exists to remove -- and it failed in practice:
    a 1-pass vs 2-pass comparison reported as n=18 against n=19 could not
    afterwards be reproduced from the stored results at all.
    """
    return {"build_import_gate": BUILD_IMPORT_GATE,
            "build_import_repairs": BUILD_IMPORT_REPAIRS,
            "build_import_timeout": BUILD_IMPORT_TIMEOUT,
            "suite_gate": SUITE_GATE,
            "suite_gate_repairs": SUITE_GATE_REPAIRS,
            "newtest_repairs": NEWTEST_REPAIRS,
            "suite_revert_on_fail": SUITE_REVERT_ON_FAIL,
            "suite_revert_newtest_ok": _newtest_ok(),
            "process_started": PROCESS_STARTED,
            "version": VERSION}


# Directories whose contents are never the model's work and must never be
# walked or deleted.
CENSUS_SKIP = {".git", ".venv", "venv", "env", "__pycache__", "node_modules",
               ".mypy_cache", ".pytest_cache", ".idea", ".vs", "dist", "build"}
CENSUS_MAX = 20000        # a tree bigger than this is not censused at all


def _file_census(workspace):
    """The set of files under the workspace, or None if it is too big to walk.

    None is not an empty set and must never be treated as one: an empty set
    would make every file on disk look newly created, and the revert would
    delete the user's project.
    """
    root = Path(workspace)
    if not root.is_dir():
        return None
    seen = set()
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in CENSUS_SKIP and not d.startswith(".")]
        for f in files:
            seen.add(str(Path(cur) / f))
            if len(seen) > CENSUS_MAX:
                return None
    return seen


def _remove_created(before_census, workspace):
    """Delete files that appeared since the census. Returns what it removed.

    Only ever runs as part of a revert, and only for files that (a) did not
    exist before this operation, (b) are inside the workspace, and (c) are not
    in a skipped directory. Anything it cannot verify, it leaves alone.
    """
    if before_census is None:
        return [], "the tree was too large to census, so new files were left in place"
    now = _file_census(workspace)
    if now is None:
        return [], "the tree grew too large to census, so new files were left in place"
    root = Path(workspace).resolve()
    removed = []
    for path in sorted(now - before_census):
        try:
            fp = Path(path).resolve()
            fp.relative_to(root)          # refuses anything outside the workspace
            if any(part in CENSUS_SKIP for part in fp.parts):
                continue
            fp.unlink()
            removed.append(str(fp))
        except (OSError, ValueError) as e:
            log(f"Revert: could not remove {Path(path).name}: {e}", "warn")
    return removed, ""


def _unregistered_tests(path):
    """Test functions a file defines but never actually runs.

    The failure this catches, measured 2026-09-08: scripts/test_public.py names
    its tests explicitly in main() rather than discovering them. A test function
    that is not added to that list never runs AND REPORTS NOTHING -- the suite
    still prints "50 passed, 0 failed" and exits 0. Proven directly:

        baseline                       50 passed
        function added, not registered 50 passed      <- silently dead
        same function, registered      52 passed

    Across every valid T3 run the model wrote the function and never registered
    it, so `added tests to the existing suite` sat at 0. No execution loop could
    reach it: nothing fails, so there is no failure to hand back.

    The rule for whether the question even applies is "does this file call any
    of its own tests by name". That single test separates all three styles:

      * explicit registry  -- some are called, so uncalled ones are dead   -> flag
      * pytest-collected   -- none are called, an external runner finds them -> skip
      * self-discovering   -- none are called by name, a globals() loop runs
                              them, so an uncalled one is NOT dead          -> skip

    Returns a sorted list of dead test names, or [] when the question does not
    apply or cannot be answered.
    """
    try:
        body = Path(path).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(body)
    except (OSError, SyntaxError, ValueError):
        return []          # unparseable is not the same as unregistered
    defined = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))                 and node.name.startswith("test"):
            defined.add(node.name)
    if not defined:
        return []
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)
    registered = defined & called
    if not registered:
        return []          # nothing is called by name: not a registry file
    return sorted(defined - called)


def _registry_function(path):
    """The source of the function that calls this file's tests, verbatim.

    The repair needs an exact anchor. Without one the model guesses at old_text,
    edit_file misses, it guesses again, and the rewrite-loop breaker stops it on
    the third try -- which is exactly how the first live firing failed: three
    edits inside one pass, none of them landing.
    """
    try:
        body = Path(path).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(body)
    except (OSError, SyntaxError, ValueError):
        return ""
    tests = {n.name for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name.startswith("test")}
    best, hits = None, 0
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        n = sum(1 for s in ast.walk(node)
                if isinstance(s, ast.Call) and isinstance(s.func, ast.Name)
                and s.func.id in tests)
        if n > hits:
            best, hits = node, n
    if best is None:
        return ""
    lines = body.splitlines()
    return NL.join(lines[best.lineno - 1:(best.end_lineno or best.lineno)])[:1500]


def _test_registry_prompt(path, dead):
    name = Path(path).name
    return (
        "You added " + ("a test that is" if len(dead) == 1 else "tests that are")
        + " never run." + NL + NL
        + name + " does not discover its tests. It calls them by name, and "
        + "anything not in that list is dead code: the suite still passes, still "
        + "prints the same count, and still exits 0, so nothing about it looks "
        + "wrong." + NL + NL
        + "Never called: " + ", ".join(dead) + NL + NL
        + "This is the function that runs them, exactly as it is on disk:" + NL + NL
        + (_registry_function(path) or "(could not be read)") + NL + NL
        + "Make ONE edit_file call against that text. Copy the old_text straight "
        + "from what is printed above -- do not retype it from memory, and do not "
        + "call edit_file more than once on this file: a third write to the same "
        + "file in one turn stops the loop and the repair is abandoned." + NL + NL
        + "Add nothing but the missing call(s). Do not rename, reorder or "
        + "'improve' the existing tests, and do not weaken the new test to make "
        + "it pass. If it then fails, that is a real failure in the code you "
        + "wrote, and it needs fixing in the code, not in the test.")


def _suite_repair_prompt(broke, files):
    """Hand back the suite failure and ask for the smallest fix."""
    names = ", ".join(Path(f).name for f in (files or [])[:6]) or "the files you changed"
    return ("The change is written, but it BROKE tests that were passing before "
            "you started:" + NL + NL + broke + NL + NL +
            "You changed: " + names + ". Fix your own change so those tests pass "
            "again. Do NOT edit the tests, do NOT delete them, and do not change "
            "anything the failure does not point at -- the tests were correct "
            "before and they are correct now. If your new behaviour genuinely "
            "conflicts with an existing test, the existing test wins. Make the "
            "edit and stop.")


def _imports_together(paths, workspace, timeout=BUILD_IMPORT_TIMEOUT):
    """Import every module this build produced, in ONE interpreter.

    Returns (ok, detail, modules). ok is None when no path yields a dotted
    module name -- nothing was importable, so nothing is provable either way,
    and that must not be reported as a pass.

    One interpreter rather than one each: importing them separately still
    misses conflicts that only exist together, such as two models claiming the
    same table on the same Base.
    """
    mods = []
    for path in paths:
        m = _module_name_loose(path, workspace)
        if m and m not in mods:
            mods.append(m)
    if not mods:
        return None, "", []
    src = NL.join("import " + m for m in mods)
    try:
        r = subprocess.run([_project_python(workspace), "-c", src],
                           cwd=str(workspace), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"[:160], mods
    if r.returncode == 0:
        return True, "", mods
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    lines = [l for l in out.splitlines() if l.strip()]
    return False, NL.join(lines[-14:])[:1400], mods


def _import_repair_prompt(paths, mods, detail):
    """Show the model the traceback and ask for the smallest possible fix."""
    names = ", ".join(Path(p).name for p in paths)
    return ("The files are written (" + names + ") but importing them together "
            "fails. This is one interpreter doing:" + NL + NL +
            NL.join("    import " + m for m in mods) + NL + NL +
            "and it produced:" + NL + NL + detail + NL + NL +
            "Fix what that traceback names. Some errors are reported ONE AT A "
            "TIME -- SQLAlchemy names a single bad annotation, FastAPI a single "
            "bad response field -- so if the same kind of mistake appears "
            "elsewhere in the same file, fix every instance of it now rather "
            "than waiting to be told again. Do not change anything unrelated. "
            "Use edit_file, not write_file: the files are otherwise correct and "
            "rewriting one loses work that already passed. Make the edits and "
            "stop -- no explanation, no new files.")


def _file_health(path, workspace):
    """Score what is on disk at `path`. Returns (score, why, best_possible).

    Deliberately blunt and cheap. It ranks ATTEMPTS against each other; it is
    not a quality metric and should never be shown as one.

    `best_possible` is the third value and it matters: a file whose
    importability cannot be checked can never reach 100, and without this the
    sampler retries it to the cap every time for no gain. Measured on the first
    live run -- app/wishlist/models.py is written BEFORE app/wishlist/__init__.py
    exists, so the directory is not yet a package, the import cannot be asked,
    and three attempts all scored 80 and changed nothing.
    """
    p = Path(path)
    try:
        body = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    except OSError:
        body = ""
    if not body.strip():
        return 0, "nothing on disk", 100

    score, why, best = 20, [], 100
    vr = _verify_file(path)
    if not vr:
        score += 40
    else:
        why.append(vr.split(":")[0][:40])

    ok, err = _imports_cleanly(path, workspace)
    if ok is True:
        score += 40
    elif ok is False:
        why.append(err[:70])
    else:
        # Cannot be asked. Award the middle and lower the bar to match, so a
        # file that is as good as it can be measured to be counts as done.
        score += 20
        best = 80
    return score, "; ".join(why), best


def plan_existing_files(manifest):
    """The files in a build plan that already exist on disk. See try_build_plan."""
    return [f["path"] for f in (manifest or {}).get("files") or []
            if f.get("path") and Path(f["path"]).exists()]


def try_build_plan(model, task, workspace, allow_all, req_id, should_cancel,
                   agent_mode, session_id, set_status, activity):
    """Plan a multi-file build, then build it ONE FILE PER FRESH CONTEXT.

    Returns a normal process_ai_response_with_tools() result dict, or None to
    fall through to the ordinary single-conversation path.

    Why this exists: in one conversation the prompt grows with every file
    written, so a 9-file build hit 100% of an 8192-token window by file five.
    Ollama does not error on that -- it drops the OLDEST messages, which is the
    user's instruction -- and the model improvised, then rewrote one file 16
    times because it no longer knew what came next. Here each file gets a clean
    conversation carrying only the manifest and the brief, so context per step
    is FLAT, and "what is next" comes from the manifest instead of memory.
    """
    mod = build_plan_mod()
    if not mod:
        return None
    max_files = int(_config.get("agent_split_max_files", 8))
    min_files = int(_config.get("agent_split_min_files", 3))

    set_status("thinking", "Planning the build…", 20)
    activity(req_id, "plan", "planning the build", "deciding which files to write")
    house = ui_style_block(task)
    plan_task = task + spec_block(task, workspace)
    raw = ollama_chat(model, [{"role": "user",
                               "content": mod.plan_prompt(plan_task, workspace, max_files, house)}],
                      timeout=600)
    manifest = mod.parse_manifest(raw, workspace, max_files)
    # A file the request says to keep unchanged is provided, not built.
    try:
        _keep = set(keep_files_in(task, workspace))
        if _keep and manifest.get("files"):
            _before = len(manifest["files"])
            manifest["files"] = [f for f in manifest["files"]
                                 if str(Path(f.get("path", "")).resolve()) not in _keep]
            if len(manifest["files"]) < _before:
                log(f"Build plan: dropped {_before - len(manifest['files'])} file(s) the "
                    "request says to keep unchanged", "info")
    except Exception as _ke:
        log(f"keep filter skipped: {_ke}", "warn")
    if manifest.get("error") or len(manifest["files"]) < min_files:
        # Not a multi-file job, or the model could not produce a usable plan.
        # Either way the ordinary path handles it fine.
        log(f"Auto-split declined: {manifest.get('error') or str(len(manifest['files'])) + ' file(s)'}",
            "info")
        return None

    # A BUILD writes new files. A plan that is mostly files that already exist
    # is a change to an existing project wearing a build's clothes, and each
    # "build step" rewrites a whole existing file from a fresh context that has
    # never read it. Measured 2026-09-24: a one-file fix was planned as
    # EDITOR_FACTS.md + set_location.py + probe.py -- all existing -- and the
    # steps tried to cut a 125-line doc to 35 and rewrote the shared helpers.
    # Decline, and let the ordinary path edit what is there.
    _existing = plan_existing_files(manifest)
    if len(_existing) * 2 > len(manifest["files"]):
        log(f"Auto-split declined: {len(_existing)} of {len(manifest['files'])} planned "
            f"file(s) already exist - this is a change, not a build", "info")
        return None

    plan = mod.BuildPlan(manifest, task, house, workspace)
    try:
        _lim = SPEC_PLAN_CHARS if int(model_profile(model)["num_ctx"]) >= 16384 else 4000
        plan.spec = spec_block(task, workspace, limit=_lim)
    except Exception as _sbe:
        log(f"spec for build steps skipped: {_sbe}", "warn")
    log(f"Auto-split: building {len(plan)} files one per context"
        + (" (house style applied)" if house else ""), "ok")
    activity(req_id, "plan", f"{len(plan)} files planned",
             ", ".join(Path(f["path"]).name for f in plan.files)[:90], ok=True)

    calls, results = [], []
    while plan.current():
        if should_cancel and should_cancel():
            break
        f = plan.current()
        n, total = plan.done + 1, len(plan)
        set_status("generating", f"File {n}/{total}: {Path(f['path']).name}",
                   int(20 + 70 * (n - 1) / max(total, 1)))
        activity(req_id, "file", f"{n}/{total} {Path(f['path']).name}",
                 f.get("purpose", "")[:80])
        try:
            # A FRESH conversation per file. This single message is the entire
            # context, which is the whole point.
            # BEST-OF-N. Sample this file up to BEST_OF_N times and keep the
            # healthiest result. A clean first attempt exits immediately, so
            # the common case costs nothing; only a file that fails to verify
            # or fails to import pays for another try.
            target = f["path"]
            snapshot = None
            try:
                snapshot = Path(target).read_text(encoding="utf-8", errors="replace")
            except OSError:
                snapshot = None          # the file does not exist yet

            best_body, best_score, best_why, sub = None, -1, "", None
            attempts = max(1, int(BEST_OF_N))
            for attempt in range(1, attempts + 1):
                if attempt > 1:
                    # Put the tree back the way this step found it, so attempt 2
                    # is a fresh try and not an edit of attempt 1's mistake.
                    try:
                        if snapshot is None:
                            Path(target).unlink(missing_ok=True)
                        else:
                            Path(target).write_text(snapshot, encoding="utf-8")
                    except OSError:
                        pass
                    activity(req_id, "retry", f"{Path(target).name} attempt {attempt}",
                             best_why[:70] or "trying again", ok=False)
                    log(f"Auto-split: {Path(target).name} scored {best_score}/100 "
                        f"({best_why[:60]}) — attempt {attempt} of {attempts}", "warn")

                sub = process_ai_response_with_tools(
                    model, [{"role": "user", "content": plan.prompt_for_current()}],
                    workspace=workspace, allow_all=allow_all, req_id=req_id,
                    should_cancel=should_cancel, agent_mode=agent_mode,
                    session_id=session_id, allow_split=False)
                calls += sub.get("tool_calls") or []
                results += sub.get("tool_results") or []

                if sub.get("needs_permission"):
                    break               # handled below; do not score a paused run

                score, why, ceiling = _file_health(target, workspace)
                if score > best_score:
                    try:
                        best_body = Path(target).read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        best_body = None
                    best_score, best_why = score, why
                # Stop at the best this file COULD score, not at a fixed 100.
                if score >= ceiling or (should_cancel and should_cancel()):
                    break

            # Restore the best attempt if the last one was not it.
            if best_body is not None and attempts > 1:
                try:
                    if Path(target).read_text(encoding="utf-8", errors="replace") != best_body:
                        Path(target).write_text(best_body, encoding="utf-8")
                        log(f"Auto-split: kept the best of {attempts} attempts for "
                            f"{Path(target).name} ({best_score}/100)", "ok")
                except OSError:
                    pass
            if attempts > 1 and best_score >= 0:
                activity(req_id, "file", f"{Path(target).name} {best_score}/100",
                         best_why[:70] or "verified", ok=(best_score >= 80))
            if sub.get("needs_permission"):
                # Permission stops the whole build: resuming mid-plan would
                # need state the caller has no way to hand back yet.
                return {"final_response":
                            (f"Paused on file {n} of {total} ({Path(f['path']).name}) — "
                             "it needs your approval to continue.\n\n" + plan.report()),
                        "tool_calls": calls, "tool_results": results,
                        "needs_permission": sub["needs_permission"]}
            note = "" if (sub.get("final_response") or "").strip() else "no reply"
            # Verify on disk and give it exactly one blunt second attempt. The
            # first live run lost index.html this way: the model called
            # design_review on a file it had never written.
            if not plan.verify_current():
                log(f"Auto-split: {Path(f['path']).name} not on disk — one retry", "warn")
                activity(req_id, "retry", f"{Path(f['path']).name} missing",
                         "asking again, write only", ok=False)
                sub2 = process_ai_response_with_tools(
                    model, [{"role": "user", "content": plan.retry_prompt()}],
                    workspace=workspace, allow_all=allow_all, req_id=req_id,
                    should_cancel=should_cancel, agent_mode=agent_mode,
                    session_id=session_id, allow_split=False)
                calls += sub2.get("tool_calls") or []
                results += sub2.get("tool_results") or []
                if not plan.verify_current():
                    note = "not written after a retry"
        except Exception as e:
            log(f"Auto-split file {n} failed: {e}", "error")
            note = str(e)[:120]
        row = plan.record(note)
        activity(req_id, "done", Path(row["path"]).name,
                 f"{row['bytes']:,} bytes" if row["ok"] else "not written", ok=row["ok"])

    # Every file, now that they all exist. This path only ever checked that a
    # file was ON DISK and non-empty -- none of the syntax or import guards ran
    # here, which is exactly where cross-file disagreement lives. Measured on T2:
    # three files that each parsed perfectly, and router.py imported WishlistItem
    # from a schemas.py that never defined it.
    #
    # At the END, not per file: during the build, file one may legitimately refer
    # to file two before it is written, and checking then would report failures
    # that are not real.
    _sick = []
    for r in plan.results:
        if not r.get("ok"):
            continue
        bad = _verify_file(r["path"])
        if bad:
            _sick.append(f"  {Path(r['path']).name}: {bad[:150]}")
    report = plan.report()
    if _sick:
        log(f"Auto-split: {len(_sick)} file(s) written but not usable", "warn")
        activity(req_id, "done", "verify", f"{len(_sick)} file(s) do not hold up",
                 ok=False)
        report += ("\n\nWritten, but these do not hold up — look at them before "
                   "using them:\n" + "\n".join(_sick))


    # The integration gate. Syntax above is per file; this is the whole build in
    # one interpreter, which is the only place cross-file disagreement shows.
    built = [r["path"] for r in plan.results if r.get("ok")]
    gate_note = ""
    # Say so every time, as the other two gates do. This one only logged on
    # failure, so "checked and clean" and "never ran" looked identical -- and on
    # 2026-09-05 a T2 sweep scored 7/7 with no way to tell which had happened.
    log(f"Auto-split: integration gate checked {len(built)} file(s)"
        + ("" if len(built) >= 1 else " - nothing was written"), "info")
    # Record on BOTH branches, so "the gate did not run" is distinguishable from
    # "it ran and found nothing" -- the same reason every gate logs when idle.
    # T2 routes through here, and its first 5 runs on the new driver came back
    # with a null record because only try_placed_edits had been wired.
    _gate_record(req_id, "imports", path="build_plan", checked=len(built),
                 ran=bool(BUILD_IMPORT_GATE and built))
    if BUILD_IMPORT_GATE and built:
        ok, detail, mods = _imports_together(built, workspace)
        _gate_record(req_id, "imports", fired=(ok is False),
                     provable=(ok is not None), repair_passes=0,
                     imports_ok=(ok is True), repaired=False)
        tries = 0
        while ok is False and tries < BUILD_IMPORT_REPAIRS:
            tries += 1
            first = detail.splitlines()[-1][:90] if detail else "import failed"
            log(f"Auto-split: the build does not import together - {first}", "warn")
            activity(req_id, "retry", "imports together", first, ok=False)
            # The rewrite-loop breaker counts writes for the whole session, and
            # a file legitimately written twice during the build trips it on the
            # repair's first edit. Measured: the repair pass read router.py and
            # was killed by "same file written 3 times" before it could fix
            # anything. The build is over; this is a new, bounded phase.
            clear_rewrites(session_id)
            try:
                fix = process_ai_response_with_tools(
                    model,
                    [{"role": "user",
                      "content": _import_repair_prompt(built, mods, detail)}],
                    workspace=workspace, allow_all=allow_all, req_id=req_id,
                    should_cancel=should_cancel, agent_mode=agent_mode,
                    session_id=session_id, allow_split=False)
                calls += fix.get("tool_calls") or []
                results += fix.get("tool_results") or []
            except Exception as e:
                log(f"Auto-split: import repair failed: {e}", "error")
                break
            ok, detail, mods = _imports_together(built, workspace)
            after = (detail.splitlines()[-1][:90] if detail else "clean")
            log(f"Auto-split: after repair {tries}/{BUILD_IMPORT_REPAIRS} - {after}",
                "ok" if ok is True else "warn")

        if ok is True:
            activity(req_id, "done", "imports together",
                     "repaired" if tries else "verified", ok=True)
            _gate_record(req_id, "imports", repair_passes=tries,
                         imports_ok=True, repaired=bool(tries))
            gate_note = ("\n\nAll " + str(len(mods)) + " modules import together" +
                         (" after one repair pass." if tries else "."))
        elif ok is False:
            activity(req_id, "done", "imports together", "still failing", ok=False)
            _gate_record(req_id, "imports", repair_passes=tries, imports_ok=False, repaired=False)
            gate_note = ("\n\nThese files do NOT import together" +
                         (" even after a repair pass" if tries else "") + ":\n\n" +
                         detail + "\n\nThey are on disk, but the package will not "
                         "load as written.")
        else:
            # No dotted module name for anything built -- not provable either
            # way, and that must not be reported as a pass.
            gate_note = ("\n\n(Whether these import together could not be checked: "
                         "nothing built resolves to an importable module inside "
                         "this workspace.)")
    report += gate_note

    # Page and scripts must agree on element ids and types. Each was written in
    # its own context; the night's best Elena Live build could not run at all.
    try:
        report += repair_pages(model, workspace, req_id, session_id, allow_all,
                               should_cancel, agent_mode)
        report += repair_serving(model, workspace, req_id, session_id, allow_all,
                                 should_cancel, agent_mode)
    except Exception as _ide:
        log(f"page check skipped: {_ide}", "warn")

    return {"final_response": report, "tool_calls": calls,
            "tool_results": results, "needs_permission": None}


TOOL_SCHEMAS = [
  {"type":"function","function":{"name":"design_review","description":"LOOK at an HTML file you have written: renders it in a real headless browser at desktop and mobile sizes, runs automated checks, and returns a critique of how it actually looks. ALWAYS call this after writing or editing any HTML/CSS page, before telling the user it is done. It is the only way you can see your own output - without it you are working blind. Fast (a few seconds) and read-only.","parameters":{"type":"object","properties":{"path":{"type":"string","description":"Absolute path to the .html file to render and review"},"brief":{"type":"string","description":"Optional: the design brief or intent to judge it against, e.g. the palette, mood and audience you were aiming for"}},"required":["path"]}}},
  {"type":"function","function":{"name":"generate_image","description":"Create an image from a text prompt using the local ComfyUI image pipeline. USE THIS whenever the user asks for a picture, image, artwork, wallpaper, logo or render. ComfyUI is started automatically if it is not running - never try to launch it yourself, never inspect ComfyUI folders, and never tell the user to install anything. Takes 20-60s.","parameters":{"type":"object","properties":{"prompt":{"type":"string","description":"What to draw. Be descriptive and visual."},"negative":{"type":"string","description":"What to avoid (optional)"},"width":{"type":"integer","description":"Pixels, default 1024"},"height":{"type":"integer","description":"Pixels, default 1024"},"steps":{"type":"integer","description":"Sampling steps, default 20"},"cfg":{"type":"number","description":"Guidance scale, default 7.0"}},"required":["prompt"]}}},
  {"type":"function","function":{"name":"list_dir","description":"List files and folders in a directory on the user's PC","parameters":{"type":"object","properties":{"path":{"type":"string","description":"Absolute directory path"}},"required":["path"]}}},
  {"type":"function","function":{"name":"read_file","description":"Read a text file. Returns up to 1200 lines per call and always states the TOTAL line count. If it says MORE LINES NOT SHOWN the file did NOT end - call again with a later offset. For big files prefer search_files, or pass limit=1500+ to read more at once. Tool rounds are limited.","parameters":{"type":"object","properties":{"path":{"type":"string","description":"Absolute file path"},"offset":{"type":"integer","description":"0-based line number to start at (default 0)"},"limit":{"type":"integer","description":"How many lines to return (default 1200, max 4000)"}},"required":["path"]}}},
  {"type":"function","function":{"name":"search_files","description":"Regex search across text files under a folder; returns file:line matches. Use this to FIND code instead of reading whole files.","parameters":{"type":"object","properties":{"root":{"type":"string","description":"Folder to search under"},"pattern":{"type":"string","description":"Regex pattern"}},"required":["root","pattern"]}}},
  {"type":"function","function":{"name":"find_definition","description":"Jump to where a function, class, or variable is DEFINED in the project (AST-based go-to-definition). Use before changing or calling a symbol to see its real signature/location instead of guessing or reading whole files.","parameters":{"type":"object","properties":{"name":{"type":"string","description":"The symbol name, e.g. get_db or ItemCreate"}},"required":["name"]}}},
  {"type":"function","function":{"name":"find_references","description":"List every file:line that USES a symbol (AST-based find-references). Use before editing a shared function/class/field to see who depends on it, so your change does not silently break callers or tests.","parameters":{"type":"object","properties":{"name":{"type":"string","description":"The symbol name to find usages of"}},"required":["name"]}}},
  {"type":"function","function":{"name":"edit_file","description":"Surgically edit an existing file: replace old_text (must match EXACTLY and be unique) with new_text. Auto-backs-up and syntax-checks. PREFERRED over write_file for changes.","parameters":{"type":"object","properties":{"path":{"type":"string"},"old_text":{"type":"string"},"new_text":{"type":"string"}},"required":["path","old_text","new_text"]}}},
  {"type":"function","function":{"name":"write_file","description":"Create a NEW file (or fully overwrite). For changing existing files use edit_file instead.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"]}}},
  {"type":"function","function":{"name":"run_script","description":"Run a Python script and capture stdout/stderr","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
  {"type":"function","function":{"name":"web_search","description":"Search the web for current information","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
  {"type":"function","function":{"name":"web_fetch","description":"Fetch and read a web page by URL","parameters":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}}},
  {"type":"function","function":{"name":"update_plan","description":"Record or update your plan for a multi-step task. Free and instant - it touches nothing on disk, so call it in the SAME round as real work rather than spending a round on it. Write the plan once when you start, then mark each step done as you finish it. Skip it entirely for anything that is one step.","parameters":{"type":"object","properties":{"steps":{"type":"array","description":"Up to 10 steps, in order","items":{"type":"object","properties":{"step":{"type":"string","description":"What the step is, in a few words"},"status":{"type":"string","description":"todo | doing | done"}},"required":["step"]}}},"required":["steps"]}}},
  {"type":"function","function":{"name":"ask_user","description":"Ask the user a question mid-task and WAIT for their answer, which comes back to you as the result of this call so you carry straight on in the same turn. Use this the moment a request is ambiguous or there is a real choice to make — which of several ways to do something, a path or name you are unsure of, whether to proceed down a costly route. This is how you 'clarify first': ask BEFORE doing, not after getting it wrong. Offer concrete options when there are any; the user can also type a free answer. Do NOT use it to ask permission to run a tool — the app already prompts for that. Ask about intent and direction, not approval.","parameters":{"type":"object","properties":{"question":{"type":"string","description":"The question, in plain language. One clear question, not several."},"options":{"type":"array","description":"The choices, if there are distinct ones. Each: {id, label, detail?, cost?}. label is the short choice; detail explains it; cost names the tradeoff (time, what the user will see, what it touches). Omit for an open question.","items":{"type":"object","properties":{"id":{"type":"string"},"label":{"type":"string"},"detail":{"type":"string"},"cost":{"type":"string"}},"required":["label"]}},"allow_free_text":{"type":"boolean","description":"Whether a typed answer is accepted besides the options (default true)."}},"required":["question"]}}},
  {"type":"function","function":{"name":"resolve_app","description":"Find where a program actually lives on THIS PC before you try to launch it — the real chrome.exe path, the launch URI, whether it is already running. Call this instead of guessing an install path; a guessed path is the single most common reason a launch silently fails. Returns the executable path, any protocol URI that opens it, and its current running state.","parameters":{"type":"object","properties":{"name":{"type":"string","description":"The app or program, e.g. 'chrome', 'spotify', 'notepad', 'vs code'"}},"required":["name"]}}}
]

# ─── Resumable chat jobs ──────────────────────────────────────────────────────
# Chat used to be one long synchronous HTTP request: a tab reload, sleep, or
# network blip threw away work the GPU had already done. Now it is a background
# job (like image/video gen) that the browser can detach from and re-attach to.
_chat_jobs   = {}
_chat_cancel = set()
CHAT_JOBS_DIR = _CONFIG_DIR / "chat_jobs"

# ── Placed edits ─────────────────────────────────────────────────────────────
_placement_mod_cache = {}

def placement_mod():
    """Load nd_placement lazily, like reskin_mod and build_plan_mod."""
    if "m" not in _placement_mod_cache:
        try:
            import importlib.util as _il
            _spec = _il.spec_from_file_location(
                "nd_placement", Path(__file__).parent / "nd_placement.py")
            _m = _il.module_from_spec(_spec); _spec.loader.exec_module(_m)
            _placement_mod_cache["m"] = _m
        except Exception as e:
            log(f"nd_placement not loaded: {e}", "warn")
            _placement_mod_cache["m"] = None
    return _placement_mod_cache["m"]


PLACE_CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
                  ".css", ".html", ".htm", ".mjs"}
PLACE_MAX_FILES = 12          # candidates offered to the planner
PLACE_OUTLINE_LINES = 14      # anchor vocabulary per file
PLACE_OUTLINE_IMPORTS = 8     # plus this many verbatim import lines
PLACE_SMALL_FILE_BYTES = 12000   # every candidate this small...
PLACE_SMALL_MAX_FILES = 3        # ...and this few of them -> skip placed edits
PLACE_SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git",
                   ".nd_backups", "dist", "build", "vendor", ".pytest_cache",
                   # Code the user has retired. Measured 2026-09-24: a one-file
                   # fix to a 4 KB script drew 9 of its 12 candidates from
                   # archive/, one of them 20 KB, so the small-file skip below
                   # never fired and 6 of 7 planned edits missed their anchors.
                   "archive", "archived", "_archive", "old", "deprecated"}


def _place_candidates(workspace, task):
    """Code files worth offering, most relevant first.

    Relevance is crude on purpose -- filename tokens shared with the request --
    but it only has to order the list, not choose. Anything genuinely needed that
    is missing shows up as a rejected step with a reason, not as silence.
    """
    ws = Path(workspace)
    words = {w for w in re.findall(r"[a-z]{4,}", (task or "").lower())}
    out = []
    try:
        for p in ws.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in PLACE_CODE_EXT:
                continue
            if any(part in PLACE_SKIP_DIRS for part in p.relative_to(ws).parts):
                continue
            try:
                n = p.stat().st_size
            except OSError:
                continue
            if n > 400_000:
                continue
            stem = set(re.findall(r"[a-z]{4,}", p.stem.lower()))
            score = len(stem & words)
            out.append((score, -n, p, n))
    except OSError:
        return []
    out.sort(key=lambda t: (-t[0], t[1]))
    return [(p, n) for _s, _n, p, n in out[:PLACE_MAX_FILES]]


def _place_outline(path, limit=PLACE_OUTLINE_LINES):
    """Definition lines, verbatim. These become the planner's anchors, so they
    must be copied out of the file exactly as they appear in it."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    pat = re.compile(r"^\s*(?:async\s+)?(?:def |class |function |const |export |@app\.|@router\.)")
    hits = [l.rstrip() for l in lines if pat.match(l) and len(l.strip()) > 6]
    # The END of a file matters as much as its start: "add it alongside the
    # existing ones" lands after the LAST endpoint / schema. Measured 2026-10-18:
    # T3's public.py has 22 definition lines and schemas.py 38, the planner saw
    # the first 14 of each, guessed an anchor past them, and the whole endpoint
    # step was dropped as "anchor not found" (27B scored 3/9 twice that way).
    # Same budget, split head + tail.
    if len(hits) > limit:
        head = limit // 2
        hits = (hits[:head] + [f"# ... {len(hits) - limit} more definitions ..."]
                + hits[-(limit - head):])
    # Imports, verbatim: a step that adds an import needs a real import line to
    # anchor on, and models write the absolute form ("from app.schemas import")
    # where the file uses the relative one ("from ..schemas import").
    imps = [l.rstrip() for l in lines
            if re.match(r"(?:from\s+\S+\s+import\b|import\s+\w)", l)][:PLACE_OUTLINE_IMPORTS]
    return imps + hits


# ── Repo map (Option 2): dependency-aware code context ───────────────────────
# Aider's repo-map pattern, stdlib-only (no tree-sitter): parse the project with
# ast, extract each file's top-level signatures AND its imports, and build the
# reverse graph -- who imports whom. The point for ND is the DEPENDENTS layer:
# the measured T3 break is an edit to a shared file (a schema, a router) that
# silently breaks tests importing it, because the model never saw the tie. Now
# the editing model is told, per file, "this is used by X, Y, test_Z -- keep them
# working." Direct edges only (cheap, high-precision); transitive is a later
# upgrade, as is tree-sitter for non-Python languages.
def _module_for(relposix):
    """'app/routers/public.py' -> 'app.routers.public'; drop the __init__ tail."""
    parts = relposix.split("/")
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts:
        parts[-1] = parts[-1][:-3] if parts[-1].endswith(".py") else parts[-1]
    return ".".join(p for p in parts if p)


def _resolve_relative(importer_relposix, level, module):
    """Resolve a relative import (from .x import y / from ..a import b) to an
    absolute dotted module, from the importing file's package. '' if it climbs
    past the project root."""
    pkg = importer_relposix.split("/")[:-1]        # the file's own package dir
    up = level - 1
    if up > len(pkg):
        return ""
    base = pkg[:len(pkg) - up]
    dotted = ".".join(base)
    if module:
        dotted = (dotted + "." + module) if dotted else module
    return dotted


def _arg_names(node):
    a = node.args
    out = [x.arg for x in getattr(a, "posonlyargs", [])] + [x.arg for x in a.args]
    if a.vararg:
        out.append("*" + a.vararg.arg)
    out += [x.arg for x in a.kwonlyargs]
    if a.kwarg:
        out.append("**" + a.kwarg.arg)
    return out


def _import_graph(workspace, max_files=400):
    """(module_map, dependents, info) for the project's python files.

    module_map: dotted module -> relposix. dependents: relposix -> set of
    relposix that import it (direct). info: relposix -> {'defs': [signatures]}.
    Skips venv/pycache/etc. Never raises."""
    ws = Path(workspace)
    files = []
    try:
        for p in ws.rglob("*.py"):
            rel = p.relative_to(ws)
            if any(part in PLACE_SKIP_DIRS for part in rel.parts):
                continue
            files.append(rel.as_posix())
            if len(files) >= max_files:
                break
    except OSError:
        return {}, {}, {}
    module_map = {_module_for(rel): rel for rel in files}
    info, imports = {}, {}
    for rel in files:
        defs, imps = [], set()
        try:
            tree = ast.parse((ws / rel).read_text(encoding="utf-8", errors="replace"))
        except Exception:
            info[rel] = {"defs": []}
            imports[rel] = set()
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for al in node.names:
                    imps.add(al.name)
            elif isinstance(node, ast.ImportFrom):
                base = (_resolve_relative(rel, node.level, node.module)
                        if node.level else node.module)
                if base:
                    imps.add(base)
                    for al in node.names:
                        imps.add(base + "." + al.name)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.append("def " + node.name + "(" + ", ".join(_arg_names(node)) + ")")
            elif isinstance(node, ast.ClassDef):
                ms = [n.name for n in node.body
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                defs.append("class " + node.name + ((": " + ", ".join(ms[:6])) if ms else ""))
        info[rel] = {"defs": defs}
        imports[rel] = imps
    mods = list(module_map.items())
    deps = {rel: set() for rel in files}
    for rel in files:
        for target in imports[rel]:
            for mod, mrel in mods:
                if mrel == rel:
                    continue
                if target == mod or target.startswith(mod + "."):
                    deps[mrel].add(rel)
    return module_map, deps, info


def _rel_in_ws(target, workspace):
    ws = Path(workspace)
    try:
        p = Path(target)
        return (p.relative_to(ws) if p.is_absolute() else p).as_posix()
    except Exception:
        return str(target).replace("\\", "/")


def _dependents_note(target, deps, workspace):
    """One line for a step prompt: which files import the one being edited."""
    rel = _rel_in_ws(target, workspace)
    dset = sorted(deps.get(rel, ()))
    if not dset:
        return ""
    names = ", ".join(Path(d).name + ("[test]" if _looks_like_test_file(d) else "")
                      for d in dset[:8])
    return ("\n\nDEPENDENTS: " + Path(rel).name + " is imported by " + names
            + ". Your edit must keep them importing and passing -- do not rename or "
            "change the signature/fields they rely on. If you must, update them too.")


def _repo_map(workspace, focus=(), query="", budget=1800, graph=None):
    """A budgeted map of the project: each file's signatures and what imports it,
    focus files and heavily-depended-on files first. Reuses a prebuilt `graph`
    (module_map, deps, info) when given. Empty on any failure."""
    try:
        _mm, deps, info = graph if graph else _import_graph(workspace)
    except Exception:
        return ""
    if not info:
        return ""
    focus_set = {_rel_in_ws(f, workspace) for f in (focus or ())}
    qt = {w for w in re.findall(r"[a-z0-9_]{3,}", (query or "").lower())}

    def rank(rel):
        toks = set(re.findall(r"[a-z0-9_]{3,}", rel.lower()))
        for d in info[rel]["defs"]:
            toks |= set(re.findall(r"[a-z0-9_]{3,}", d.lower()))
        return 5 * (rel in focus_set) + len(deps.get(rel, ())) + len(qt & toks)

    out = ["## Repo map (definitions + who imports each file; do not break dependents)"]
    used = 0
    for rel in sorted(info, key=lambda r: -rank(r)):
        dset = sorted(deps.get(rel, ()))
        used_by = (", ".join(Path(d).name + ("[test]" if _looks_like_test_file(d) else "")
                             for d in dset[:6]) if dset else "-")
        block = (rel + "  (used by: " + used_by + ")\n"
                 + "\n".join("    " + d for d in info[rel]["defs"][:8]))
        if used and used + len(block) > budget:
            break
        out.append(block)
        used += len(block)
    return "\n".join(out) if len(out) > 1 else ""


# ── LSP-style navigation (Option 2 port from dsh-lsp): go-to-def / find-refs ──
# Stdlib ast, name-based (no scope/type resolution) -- a prototype; jedi or a
# real language server is the accuracy upgrade. Complements the always-injected
# repo map: the map shows structure passively; these let the model actively look
# up where a symbol is defined or who uses it, on demand, before an edit.
def _iter_py(workspace, cap=600):
    ws = Path(workspace)
    out = []
    try:
        for p in ws.rglob("*.py"):
            rel = p.relative_to(ws)
            if any(part in PLACE_SKIP_DIRS for part in rel.parts):
                continue
            out.append((p, rel.as_posix()))
            if len(out) >= cap:
                break
    except OSError:
        pass
    return out


def _find_definition(name, workspace, max_hits=20):
    """Where `name` is defined (def/class/top-level or annotated assignment)."""
    hits = []
    for p, rel in _iter_py(workspace):
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except Exception:
            continue
        lines = src.splitlines()
        for node in ast.walk(tree):
            match = False
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                match = node.name == name
            elif isinstance(node, ast.Assign):
                match = any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
            elif isinstance(node, ast.AnnAssign):
                match = isinstance(node.target, ast.Name) and node.target.id == name
            if match:
                ln = getattr(node, "lineno", 0)
                kind = ("class" if isinstance(node, ast.ClassDef)
                        else "def" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        else "var")
                text = lines[ln - 1].strip() if 0 < ln <= len(lines) else ""
                hits.append((rel, ln, kind, text[:140]))
                if len(hits) >= max_hits:
                    return hits
    return hits


def _find_references(name, workspace, max_hits=50):
    """Every file:line that uses `name` (bare name or attribute)."""
    hits = []
    for p, rel in _iter_py(workspace):
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except Exception:
            continue
        lines = src.splitlines()
        seen = set()
        for node in ast.walk(tree):
            ln = None
            if isinstance(node, ast.Name) and node.id == name:
                ln = node.lineno
            elif isinstance(node, ast.Attribute) and node.attr == name:
                ln = node.lineno
            if ln and ln not in seen:
                seen.add(ln)
                text = lines[ln - 1].strip() if 0 < ln <= len(lines) else ""
                hits.append((rel, ln, text[:140]))
                if len(hits) >= max_hits:
                    return hits
    return hits


def tool_find_definition(a, workspace):
    name = str((a or {}).get("name") or "").strip()
    if not name:
        return "[find_definition needs a `name` (a function, class, or variable)]"
    if not workspace:
        return "[find_definition needs a workspace to search]"
    hits = _find_definition(name, workspace)
    if not hits:
        return (f"[no definition of `{name}` found in the project — it may be imported "
                "from a dependency or a builtin, or spelled differently]")
    return (f"Definition(s) of `{name}`:\n"
            + "\n".join(f"  {r}:{ln}  [{k}] {t}" for r, ln, k, t in hits))


def tool_find_references(a, workspace):
    name = str((a or {}).get("name") or "").strip()
    if not name:
        return "[find_references needs a `name`]"
    if not workspace:
        return "[find_references needs a workspace to search]"
    hits = _find_references(name, workspace)
    if not hits:
        return f"[no references to `{name}` found in the project]"
    by = {}
    for r, ln, t in hits:
        by.setdefault(r, []).append((ln, t))
    out = [f"References to `{name}` ({len(hits)} shown, most files first):"]
    for r in sorted(by, key=lambda k: -len(by[k])):
        out.append(f"  {r}:")
        for ln, t in by[r][:12]:
            out.append(f"    {ln}: {t}")
    return "\n".join(out)


def _project_python(workspace):
    """The interpreter this project runs under, if it ships one."""
    ws = Path(workspace) if workspace else None
    if ws:
        for rel in (".venv/Scripts/python.exe", "venv/Scripts/python.exe",
                    ".venv/bin/python", "venv/bin/python"):
            p = ws / rel
            if p.is_file():
                return str(p)
    return sys.executable


def _looks_like_test_file(path):
    """Only these are safe to execute to see whether they pass."""
    n = Path(path).name.lower()
    return n.endswith(".py") and (n.startswith("test_") or n.endswith("_test.py")
                                  or n == "conftest.py")


def _workspace_has_tests(workspace, limit=4000):
    """Does the project have ANY test file (outside skipped/archived folders)?"""
    if not workspace:
        return False
    ws = Path(workspace)
    try:
        for i, p in enumerate(ws.rglob("*.py")):
            if i >= limit:
                return True            # a huge tree: assume it has tests, as before
            if any(part in PLACE_SKIP_DIRS for part in p.relative_to(ws).parts):
                continue
            if _looks_like_test_file(p):
                return True
    except OSError:
        return True
    return False


def _test_file_passes(path, workspace, timeout=180):
    """Run a test file. Returns (ok, first_error_line). ok=None if not runnable."""
    if not _looks_like_test_file(path):
        return None, ""
    try:
        r = subprocess.run([_project_python(workspace), str(path)],
                           cwd=str(workspace or Path(path).parent),
                           capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return None, str(e)[:120]
    if r.returncode == 0:
        return True, ""
    text = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    # The last line of a traceback is the one that says what went wrong.
    return False, (text[-1][:160] if text else f"exit {r.returncode}")


# Measured, repeatedly: the model writes a test whose expectations do not match
# its own endpoint. Sweep 1 added four tests and two failed. The decade check
# expected "1990-1999" where the suite says "1990s". Registering such a test
# turns a green suite into a crashing one, so the registration hint is off --
# but leaving the test unrun means nobody ever finds out it is wrong.
#
# Nothing static can catch this: no checker knows what an endpoint returns. The
# only thing that knows is running it, which ND could not do at all until
# run_script learned to use the project's own interpreter.
RUN_NEW_TEST = True
NEW_TEST_TIMEOUT = 120
NEW_TEST_MAX = 4


def _run_one_test_function(path, workspace, func, timeout=NEW_TEST_TIMEOUT):
    """Import a test file and call ONE function in it. (ok, error, context).

    `context` is the shape of the data at the line that failed -- which keys were
    actually present. A traceback only ever says which key was missing, and a
    model handed only that guesses a second wrong key. Measured: it answered
    KeyError 'by_format' with 'formats'.

    ok is None when it could not be run at all -- no interpreter, an import that
    fails for reasons that are not the model's business -- because "we could not
    tell" must never be reported to the model as "your test is broken".

    Calling the function directly rather than running the file is the point: a
    new test that is not registered in the file's main() would otherwise never
    execute, which is exactly the state that hid the defect.
    """
    p = Path(path)
    probe = Path(__file__).parent / "nd_test_probe.py"
    if not probe.exists():
        return None, "", ""
    try:
        r = subprocess.run([_project_python(workspace), str(probe), str(p.parent),
                            p.stem, func, str(p)],
                           cwd=str(workspace or p.parent), capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
    except Exception as e:
        return None, str(e)[:120], ""
    if r.returncode == 0:
        return True, "", ""
    out = (r.stdout or "") + (r.stderr or "")
    lines = [l for l in out.splitlines() if l.strip()]
    if not lines:
        return False, f"exit {r.returncode}", ""
    # Everything from the probe's own heading down is the part the model cannot
    # get from a traceback: which keys were actually there.
    context = ""
    mark = "WHAT THE DATA ACTUALLY WAS"
    if mark in out:
        context = out[out.index(mark):][:1200].rstrip()
        lines = [l for l in out[:out.index(mark)].splitlines() if l.strip()]
    if not lines:
        return False, f"exit {r.returncode}", context
    # The last line of a traceback says what went wrong; the line above it says
    # where. Both, because "KeyError: items" alone does not locate anything.
    tail = lines[-1][:160]
    where = next((l.strip()[:110] for l in reversed(lines[:-1])
                  if l.strip().startswith("File ") or "line " in l), "")
    return False, (tail + ("   at  " + where if where else "")), context


# Measured OFF, at six runs a side.
#
# The idea was sound: a traceback says which key was MISSING and never which
# keys were THERE, so the model guesses a second wrong name. Handing it the real
# shape should have ended that. It did not.
#
#     KeyError: 'format'     -> retry -> KeyError: 'formats'   still guessing
#     KeyError: 'by_format'  -> retry -> KeyError: 'by_format'  unchanged
#
# Both retries were shown the actual key list and neither used it. The loop's own
# fix rate fell from 6 of 7 fires to 2 of 4, and T3 read 6.3 stdev 2.2 against a
# 7.5 stdev 0.5 baseline -- about 1.3 sigma, so the score difference is NOT
# significant, but the mechanism plainly failed and the fix rate is the thing
# this was meant to raise.
#
# The probe itself stays on: it is strictly better instrumentation, and the shape
# still reaches the ND log where a person can read it. Only the prompt injection
# is off.
# The only check in this benchmark that has never once passed: T3's "added tests
# to the existing suite", 0 for 5 sweeps and 0 for 12 variance runs. The model
# writes a test function and the suite still runs exactly the same number of
# tests, because a file like scripts/test_public.py calls its tests by hand in
# main() and an unregistered function is dead code.
#
# Explaining that to the model was tried and measured worse, twice. So do not
# explain it. RUN the file, count, and only claim the test was added if the
# number went up. Then the model is told a fact it cannot argue with.
# Measured at six runs a side, and it is the FIRST thing ever to move the check
# it targets: "added tests to the existing suite" went 0/6 -> 3/6, having been
# 0 for 5 sweeps and 0 for 12 variance runs before it.
#
# It costs more than it wins. "nothing that worked before is broken" fell 4/6 ->
# 1/6, and mean 7.5 -> 6.5 (0.96 sigma, NOT significant -- but five of six runs
# left the user's suite red, which is a real harm whatever the statistics say).
#
# The reason is a design error since fixed above: it demanded a passing test and
# registration at the same time, so the model wired in tests it had not repaired
# -- "public: 9 failing (was 0)". Green first, wired second is now enforced.
#
# ON, with the green-first fix in place. Being measured now: 6-run T3
# variance, watching "nothing that worked before is broken" above the mean --
# the previous configuration took it to 1/6 and that is the number that matters.
VERIFY_TEST_COUNT = True
_COUNT_RE = re.compile(r"(\d+)\s+passed(?:\s*,\s*(\d+)\s+failed)?", re.I)
_LABEL_RE = re.compile(r"^\s*(PASS|FAIL)\s\s*(.+?)\s*$")


def _suite_labels(out):
    """Which test labels passed and which failed, from a suite's own output.

    Suites print "  PASS  <label>" and "  FAIL  <label> - detail". Counts alone
    cannot separate "you broke a test that used to pass" from "the test you just
    wrote does not pass yet", and those two call for opposite responses: the
    first should put the tree back, the second should not throw away a feature
    that is nearly finished. Names can separate them; a headcount cannot.
    """
    passing, failing = set(), set()
    for line in (out or "").splitlines():
        m = _LABEL_RE.match(line)
        if not m:
            continue
        label = re.split(r"\s+[-—]\s+", m.group(2))[0].strip()
        if label:
            (passing if m.group(1).upper() == "PASS" else failing).add(label)
    return passing, failing


def _failure_tail(out, limit=1600):
    """The FAILING lines of a suite's output, for the repair prompt.

    Suites print '  PASS  <label>' and '  FAIL  <label> — <detail>', grouped
    under '[section]' headers, then a 'N passed, M failed' summary. The plain
    last-N-lines tail is useless here: on a 56-test suite those trailing lines
    are PASSING tests, so the repair pass was shown what still works, not what
    broke (measured 2026-09-13 — it could not fix a thing and every run
    reverted). Keep each FAIL line (name + inline detail) with its section
    header, plus the summary. Empty when nothing failed, so the caller falls
    back to the plain tail."""
    lines = (out or "").splitlines()
    keep, section = [], ""
    for l in lines:
        s = l.strip()
        if s.startswith("[") and s.endswith("]"):
            section = l.rstrip()
            continue
        m = _LABEL_RE.match(l)
        if m and m.group(1).upper() == "FAIL":
            if section and (not keep or keep[-1] != section):
                keep.append(section)
            keep.append(l.rstrip())
    if not keep:
        return ""
    for l in lines:
        if re.search(r"\d+\s+passed", l) and re.search(r"\d+\s+failed", l):
            keep.append(l.strip())
            break
    return NL.join(keep)[:limit]


def _suite_detail(path, workspace, timeout=180):
    """Run a test FILE. Returns ((passed, failed) or None, output_tail).

    The tail is the point. _suite_count() used to run the suite and throw the
    output away, so a regression could only ever be reported as a headcount --
    "test_public.py no longer runs at all (it reported 50 passing before)". A
    model cannot fix that. Measured on T3, 2026-09-05: the suite gate's repair
    pass was handed exactly that sentence and failed on both attempts, twice
    running, while the real cause sat in the discarded output:
    `total_items = db.execute(...).scalars().count`.

    The integration gate works because it hands back a traceback. Same here.
    """
    if not _looks_like_test_file(path):
        return None, ""
    try:
        r = subprocess.run([_project_python(workspace), str(path)],
                           cwd=str(workspace or Path(path).parent),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "the suite did not finish within " + str(timeout) + "s"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"[:200]
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    m = None
    for line in out.splitlines():
        found = _COUNT_RE.search(line)
        if found:
            m = found
    lines = [l for l in out.splitlines() if l.strip()]
    # Prefer the FAILING lines over the trailing tail: the repair pass needs to
    # see what BROKE, and on a big suite the last lines are passing tests.
    tail = _failure_tail(out) or NL.join(lines[-12:])[:900]
    # Labels come from the FULL output, not the tail. A fifty-test suite pushes
    # its earlier results well past the twelve lines kept for the model.
    passing, failing = _suite_labels(out)
    if not m:
        return None, tail, passing, failing
    return (int(m.group(1)), int(m.group(2) or 0)), tail, passing, failing


def _suite_count(path, workspace, timeout=180):
    """How many tests a suite reports. (passed, failed), or None when unknown."""
    return _suite_detail(path, workspace, timeout)[0]


# T4, measured: told to fix one inverted filter and explicitly told to re-run the
# suite, the model made a wrong one-line edit, created fix_for_storefront_bug.py,
# and wrote "Re-run the test suite" into its reply as a task for somebody else.
# The suite was still red. Nothing checked.
#
# The test-run loop built earlier only fires on edits to TEST files. An edit to
# application code -- which is most edits -- runs nothing at all. This is the
# same mechanism pointed at the other side of that line: snapshot the project's
# suites before the plan, and after each edit say what stopped working.
#
# Instructing the model to verify does not make it verify. Running it does.
SUITE_CHECK = True
SUITE_MAX_FILES = 6
SUITE_TIMEOUT = 150


def _project_suites(workspace):
    """Runnable test files in this project, smallest first.

    Smallest first because the cap below is a real cap: a project with fifty
    test files gets its six cheapest watched, and a big slow suite is exactly
    the one worth skipping when this runs after every edit.
    """
    if not workspace:
        return []
    out = []
    try:
        ws = Path(workspace)
        for p in ws.rglob("*.py"):
            if not _looks_like_test_file(p):
                continue
            if any(part in (".venv", "venv", "node_modules", "__pycache__",
                            ".git", ".nd_backups") for part in p.parts):
                continue
            try:
                out.append((p.stat().st_size, p))
            except OSError:
                pass
    except (OSError, ValueError):
        return []
    out.sort()
    return [p for _, p in out[:SUITE_MAX_FILES]]


def _suite_snapshot(workspace):
    """{path: (passed, failed)} for every suite that runs and reports a count.

    Only GREEN suites are recorded. A suite already failing before the edit is
    not this edit's problem, and reporting it would train the model to chase
    something it did not cause.
    """
    if not SUITE_CHECK:
        return {}
    snap = {}
    for p in _project_suites(workspace):
        c, _tail, passing, _failing = _suite_detail(str(p), workspace,
                                                    timeout=SUITE_TIMEOUT)
        # A partly-failing suite is watched too when names can be compared:
        # breaking one of its PASSING tests is damage, its old failures are not.
        if c and c[0] > 0 and (c[1] == 0 or (_newtest_ok() and passing)):
            # Carry the names that were passing. Only a suite that was entirely
            # green is recorded, so any later failure is either one of THESE
            # names breaking -- a real regression -- or a name that did not
            # exist yet, which is the model's own new test.
            snap[str(p)] = (c[0], c[1], passing, _top_defs(p))
    return snap


def _top_defs(path):
    """Top-level function names in a test file, or None if it will not parse."""
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None
    return {n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _newtest_crash_only(path, workspace, base_defs, was_passing):
    """Is a suite crash confined to test functions the model just ADDED?

    2026-10-18, 27B on T3 with the new-test exemption on: 4 of 5 runs kept a
    working feature; the fifth was reverted because the model's new test raised
    and took the whole hand-rolled suite down with it ("no longer runs at all").
    That is the same case as a failing new test -- the model's own test -- but a
    crash hides whether the existing tests still pass, because they never ran.

    So find out: copy the file with every function that did not exist at the
    baseline stubbed to `return None`, run the copy, and require every test that
    passed at the baseline to pass again. Returns (True, note) only then. A crash
    at import, in an existing test or in module-level code survives the stubbing
    and still counts as damage."""
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return False, ""
    new = [n for n in tree.body
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
           and n.name not in base_defs]
    if not new:
        return False, ""
    for n in new:
        n.body = [ast.Return(value=None)]
    stub = Path(path).with_name("test__ndstub_" + Path(path).name)
    try:
        stub.write_text(ast.unparse(ast.fix_missing_locations(tree)), encoding="utf-8")
        now, _tail, passing, _failing = _suite_detail(str(stub), workspace,
                                                      timeout=SUITE_TIMEOUT)
    except Exception as e:
        log(f"Suite gate: could not check the crash ({e})", "warn")
        return False, ""
    finally:
        try:
            stub.unlink()
        except OSError:
            pass
    if now is None or (was_passing - passing):
        return False, ""
    names = ", ".join(n.name for n in new[:3])
    return True, f"the new test(s) {names} crash the suite; every existing test still passes"


def _suite_regressions(before_snap, workspace, newfails=None):
    """What STOPPED WORKING since the snapshot. Empty when nothing did.

    2026-09-10. This used to count failures rather than name them, so a new test
    the model had just written for its own new feature was reported as "2 test(s)
    now FAIL that passed before your edit" -- and the suite gate then reverted
    the entire change. Reading the T3 replies showed what that cost: every run
    scoring 2/9 had built the whole feature, schema and endpoint and service
    function and test, and lost all of it because the test it wrote did not pass
    on the first repair.

    Reverting is right when working behaviour breaks. It is wrong when the only
    red test is the one describing work in progress: an unfinished feature can be
    inspected, finished or discarded by the user, while a reverted one leaves no
    trace of what was attempted.

    Pass a list as `newfails` to receive those new-test failures separately;
    they are deliberately NOT part of the returned string, because the caller
    reverts on that string.
    """
    if not SUITE_CHECK or not before_snap:
        return ""
    broke, evidence = [], ""
    for path, snap in before_snap.items():
        was_pass = snap[0]
        was_passing = snap[2] if len(snap) > 2 else set()
        now, tail, _npass, nfail = _suite_detail(path, workspace,
                                                 timeout=SUITE_TIMEOUT)
        name = Path(path).name
        # Split the failures by whether the name was passing before this edit.
        # A name that was green and is now red is damage. A name that did not
        # exist before is the model's own new test, and reverting a nearly
        # finished feature because its test is not right yet destroys more than
        # it protects -- the user can see and judge an unfinished feature, but
        # cannot recover one that was silently put back.
        _by_name = _newtest_ok() and bool(was_passing)
        regressed = sorted(nfail & was_passing) if _by_name else []
        brand_new = sorted(nfail - was_passing) if _by_name else sorted(nfail)
        if brand_new and newfails is not None:
            newfails.append(name + ": " + ", ".join(brand_new[:3]))
        hit = ""
        _crash_ok, _crash_why = False, ""
        if now is None and _newtest_ok() and was_passing and len(snap) > 3                 and snap[3] is not None:
            _crash_ok, _crash_why = _newtest_crash_only(path, workspace, snap[3],
                                                        was_passing)
            if _crash_ok:
                log(f"Suite gate: {name}: {_crash_why}", "warn")
                if newfails is not None:
                    newfails.append(name + ": " + _crash_why)
        if now is None and not _crash_ok:
            hit = (f"{name} no longer runs at all (it reported "
                   f"{was_pass} passing before your edit)")
        elif now is None:
            pass
        elif regressed:
            hit = (f"{name}: {len(regressed)} test(s) now FAIL that passed "
                   f"before your edit ({', '.join(regressed[:3])})")
        elif now[1] > 0 and not _by_name:
            # Either the flag is off, or no labels were captured for this suite
            # so names cannot be compared. Fall back to the count rule rather
            # than silently permitting a regression it would have caught -- but
            # still NAME the failing tests when labels exist, so the repair pass
            # is told WHAT to fix, not only how many. (Measured 2026-09-13: with
            # only a count + a tail of passing tests, repair fixed 0.)
            _fn = ", ".join(sorted(nfail)[:6]) if nfail else ""
            hit = (f"{name}: {now[1]} test(s) now FAIL that passed before "
                   f"your edit ({was_pass} were passing)"
                   + (f" -- failing: {_fn}" if _fn else ""))
        elif now[0] < was_pass - len(brand_new):
            hit = (f"{name}: only {now[0]} tests run now, was {was_pass} "
                   f"-- tests have gone missing")
        if hit:
            broke.append(hit)
            # Keep the output of the FIRST broken suite. A count says what
            # happened; only this says why, and a repair needs why.
            if not evidence and tail:
                evidence = tail
    if not broke:
        return ""
    msg = ("you broke the existing suite: " + "; ".join(broke[:3])
           + ". Fix what you just changed -- do not touch the tests")
    if evidence:
        msg += NL + NL + "This is what it printed:" + NL + evidence
    return msg


def _check_test_registered(step_file, before_count, workspace, mod):
    """Did the suite actually grow? Returns a note, empty when it did.

    before_count comes from running the file BEFORE the edit, so this compares
    two measurements rather than trusting either one.
    """
    if not VERIFY_TEST_COUNT or before_count is None:
        return ""
    after = _suite_count(step_file, workspace)
    if after is None:
        return ""
    b_pass, b_fail = before_count
    a_pass, a_fail = after
    if a_pass + a_fail > b_pass + b_fail:
        return ""     # it grew: registered, whatever else may be wrong
    note = (f"the suite still runs {a_pass + a_fail} test(s), the same as before "
            f"your edit -- your new function is never called, so it does not exist "
            f"as far as the suite is concerned")
    try:
        d = mod.find_dispatcher(Path(step_file).read_text(encoding="utf-8",
                                                          errors="replace"))
        if d:
            note += f". {d[0]}() in this file calls each test by name; yours is not in it"
    except Exception:
        pass
    return note


SHAPE_IN_RETRY = False


def _check_new_tests(step_file, before, after, workspace, mod):
    """Run whatever test functions this edit just added. Returns a note.

    Empty when there is nothing to say -- no new test, or it passes.
    """
    if not RUN_NEW_TEST or not _looks_like_test_file(step_file):
        return ""
    try:
        added = [n for n in mod.new_functions(before, after) if n.startswith("test")]
    except Exception:
        return ""
    # Was 2, and it bit: one run added eight tests and three failed, the last two
    # past the cap and unseen. Report EVERY failure found, not just the first --
    # there is one retry, and a retry that is shown one of three problems fixes
    # one of three.
    if len(added) > NEW_TEST_MAX:
        log(f"{Path(step_file).name}: {len(added)} new tests, running the first "
            f"{NEW_TEST_MAX}", "warn")
    bad, seen = [], []
    for func in added[:NEW_TEST_MAX]:
        ok, why, context = _run_one_test_function(step_file, workspace, func)
        if ok is False:
            bad.append(f"{func}() FAILS: {why}")
            if context and context not in seen:
                seen.append(context)
    if not bad:
        return ""
    if SHAPE_IN_RETRY and seen:
        return "; ".join(bad) + chr(10) + chr(10) + (chr(10) * 2).join(seen)
    return "; ".join(bad)


def try_placed_edits(model, task, workspace, allow_all, req_id, should_cancel,
                     agent_mode, session_id, set_status, activity):
    """Plan an open request as PLACED edits, then run one per fresh context.

    Returns a result dict, or None to fall through to the ordinary path.
    """
    mod = placement_mod()
    if not mod or not workspace:
        return None
    cands = _place_candidates(workspace, task)
    if len(cands) < 1:
        return None
    # "Change ONLY the loop in set_location.py ... keep everything else" is one
    # file, and the ordinary loop sees all of it; the planner sees def lines and
    # splits the fix into steps whose anchors are guesses (1 of 7 landed).
    try:
        _bp = build_plan_mod()
        if _bp and hasattr(_bp, "single_file_scope") and _bp.single_file_scope(task):
            log("Placed edits skipped: the request is scoped to one file - "
                "fixing in the normal loop instead", "info")
            return None
    except Exception:
        pass
    # Small files do not go through placed edits at all. The planner splits one
    # fix into 6-8 micro-edits, each a separate round in a fresh context, and is
    # shown only a file's `def` lines. Measured 2026-09-24 on a 92-line probe.py,
    # twice: 2 of 8 and then 1 of 8 planned edits landed, ~20 minutes each, with
    # the rest "anchor not found" or "the file is unchanged". Showing the planner
    # the whole file cut the bad anchors (5 -> 2) but not the dead steps. The
    # ordinary loop sees the whole file and every requirement at once, and the
    # run gate checks the result -- which is the right tool for a small file.
    try:
        _sizes = [p.stat().st_size for p, _ in cands]
    except OSError:
        _sizes = []
    # A FEW small files only. A real multi-file change to a codebase keeps placed
    # edits: the T3 benchmark task draws 12 candidates up to 40 KB and must not
    # change route because some of its files happen to be small.
    if _sizes and len(_sizes) <= PLACE_SMALL_MAX_FILES and max(_sizes) <= PLACE_SMALL_FILE_BYTES:
        log(f"Placed edits skipped: {len(cands)} small file(s), largest "
            f"{max(_sizes) // 1024 + 1} KB - fixing in the normal loop instead", "info")
        return None

    ws = Path(workspace)
    rels, excerpt_lines = [], []
    for p, n in cands:
        try:
            rel = str(p.relative_to(ws))
        except ValueError:
            rel = str(p)
        rels.append((rel, n))
        ol = _place_outline(p)
        if ol:
            excerpt_lines.append(f"--- {rel} ---\n" + "\n".join(ol))
    excerpts = "\n\n".join(excerpt_lines)

    # Repo map (Option 2): build the import graph once, hand the planner a
    # dependency-aware map (what imports each candidate) so it does not plan an
    # edit that silently breaks a dependent -- the measured T3 failure. _pe_deps
    # is reused per step below to warn the editing model directly.
    _pe_deps = {}
    if _config.get("agent_repo_map", True):
        try:
            _pe_graph = _import_graph(workspace)
            _pe_deps = _pe_graph[1]
            _rm = _repo_map(workspace, focus=[r for r, _ in rels], query=task,
                            graph=_pe_graph)
            if _rm:
                excerpts = (excerpts + "\n\n" + _rm) if excerpts else _rm
        except Exception as _rme:
            log(f"repo map skipped: {_rme}", "warn")

    set_status("thinking", "Working out where each change belongs…", 18)
    activity(req_id, "plan", "planning placements",
             f"{len(rels)} candidate file(s)")
    t0 = time.time()
    raw = ollama_chat(model, [{"role": "user", "content":
                               mod.plan_prompt(task, rels, excerpts)}],
                      timeout=900, clean=False)
    placements = mod.parse_placements(raw, allowed_files=[r for r, _ in rels])
    usable, rejected = mod.validate_placements(placements, workspace)
    dt = round(time.time() - t0, 1)

    if not usable:
        log(f"Placed-edit planning produced nothing usable in {dt}s "
            f"({len(placements)} step(s) proposed, all rejected) — "
            f"falling through to the ordinary path", "warn")
        for r in rejected[:4]:
            log(f"  rejected: {r.get('file')} — {r.get('why')}", "warn")
        return None

    plan = mod.PlacementPlan(usable, rejected, task)
    log(f"Placed edits: {len(plan)} step(s) planned in {dt}s"
        + (f", {len(rejected)} rejected" if rejected else ""), "ok")
    activity(req_id, "plan", f"{len(plan)} placed edit(s)",
             ", ".join(Path(s["file"]).name for s in plan.steps)[:90], ok=True, secs=dt)

    # One snapshot before any edit lands, so "you broke it" always compares
    # against the tree as the user handed it over -- not against whatever the
    # previous step left behind.
    suite_base = _suite_snapshot(workspace)
    # Every touched file as the user handed it over. If the suite ends up red
    # and the model cannot put it right, this is what makes "leave it as you
    # found it" possible instead of shipping a broken tree.
    _orig_files = {}
    # What was on disk before anything was touched, so a revert can remove what
    # the model ADDED as well as undo what it changed. Measured 2026-09-05: the
    # revert restored the edited files and left the new ones behind, so
    # "did not invent new files" sat at 12/18 and the reply claiming every file
    # was put back as it was overstated what had actually happened.
    _census = _file_census(workspace)
    if suite_base:
        log(f"Watching {len(suite_base)} green suite(s): "
            + ", ".join(Path(k).name for k in suite_base), "info")

    calls, results = [], []
    while plan.current():
        if should_cancel and should_cancel():
            break
        s = plan.current()
        n, total = plan.idx + 1, len(plan)
        name = Path(s["file"]).name
        set_status("generating", f"Edit {n}/{total}: {name}",
                   int(20 + 70 * (n - 1) / max(total, 1)))
        activity(req_id, "file", f"{n}/{total} {name}", s["what"][:80])
        before = ""
        try:
            before = Path(s["file"]).read_text(encoding="utf-8", errors="replace")
            _orig_files.setdefault(s["file"], before)
        except OSError:
            pass
        # Count the suite BEFORE the edit, so "did it grow" compares two
        # measurements instead of trusting one.
        before_count = (_suite_count(s["file"], workspace)
                        if VERIFY_TEST_COUNT and _looks_like_test_file(s["file"])
                        else None)
        try:
            # A FRESH conversation per edit. This one message is the whole
            # context: the file, the change in one line, and an anchor known to
            # exist. Nothing about the wider task -- that is exactly what the
            # model could not decompose.
            _step_content = mod.step_prompt(s, before, workspace)
            if _pe_deps:
                _step_content += _dependents_note(s["file"], _pe_deps, workspace)
            sub_res = process_ai_response_with_tools(
                model, [{"role": "user", "content": _step_content}],
                workspace=workspace, allow_all=allow_all, req_id=req_id,
                should_cancel=should_cancel, agent_mode=agent_mode,
                session_id=session_id, allow_split=False, only_file=s["file"])
            calls += sub_res.get("tool_calls") or []
            results += sub_res.get("tool_results") or []
            if sub_res.get("needs_permission"):
                return {"final_response":
                            (f"Paused on edit {n} of {total} ({name}) — it needs "
                             "your approval to continue.\n\n" + plan.report()),
                        "tool_calls": calls, "tool_results": results,
                        "needs_permission": sub_res["needs_permission"]}
            # Verify on disk, not by asking. The file must have changed, and the
            # anchor must still be there -- an edit that removed it replaced the
            # place instead of adding to it.
            after = Path(s["file"]).read_text(encoding="utf-8", errors="replace")

            def _revert(why):
                """Put the file back. Detecting a bad step and leaving it on disk
                is not enough: measured on the benchmark, a step whose anchor was
                `@router.post("/items/{item_id}/request", ...)` wrote it back as
                `@router.get(...)`, silently flipping an existing endpoint's
                method and taking all 108 smoke tests with it. ND reported the
                step as failed and left the damage in place. `before` is this
                file's exact contents from moments earlier, so putting it back is
                precise and cannot half-work."""
                try:
                    Path(s["file"]).write_text(before, encoding="utf-8")
                    return why + "; the file has been put back"
                except OSError as e:
                    return f"{why}, and restoring it failed: {e}"

            if after == before:
                plan.record(False, "the file is unchanged")
            elif s.get("position") != "replace" and s["anchor"] not in after:
                plan.record(False, _revert("the anchor is gone — it replaced the "
                                           "spot instead of adding to it"))
            else:
                bad = _verify_file(s["file"])
                if bad:
                    # A one-shot step gets no chance to fix its own syntax, and a
                    # file that will not parse or import is worse than no change.
                    plan.record(False, _revert(bad[:100]))
                else:
                    # Adding the function is only half the job in a file that
                    # lists its own functions -- a test suite's main(), a
                    # registry. Measured: the model writes the test perfectly and
                    # never adds the call, so it exists and never runs, 0 of 3
                    # runs. It is mechanical, so ND does it rather than asking
                    # again. auto_register only fires when the new name follows
                    # the convention the dispatcher already uses.
                    #
                    # SHIPS OFF. It works -- it wired the new test into main() in
                    # every run -- but it never improved the benchmark and twice
                    # made it worse, because the model's tests are broken and
                    # registering a broken test turns a silently-dead test into a
                    # red suite. Three measured configurations, 3 runs each:
                    #
                    #   no registration          mean 7.7  stdev 0.6
                    #   auto-register            mean 7.0  stdev 0.0
                    #   auto-register + verify   mean 6.0  stdev 2.6
                    #
                    # The blocker is the model writing tests that do not run, and
                    # no amount of wiring fixes that. Set agent_auto_register true
                    # for a model that writes working ones.
                    wnote = ""
                    try:
                        wired, wnote = (
                            mod.auto_register(before, after)
                            if _config.get("agent_auto_register", False) else (None, ""))
                        if wired:
                            Path(s["file"]).write_text(wired, encoding="utf-8")
                            if _verify_file(s["file"]):
                                # Undo our own edit, not the model's.
                                Path(s["file"]).write_text(after, encoding="utf-8")
                                wnote = ""
                            else:
                                # Registering it is only right if it PASSES.
                                # Measured: the model's test was broken, so
                                # wiring it in took a green suite to a crashing
                                # one. Leave the test in the file, leave it
                                # unregistered, and say so.
                                ok, why = _test_file_passes(s["file"], workspace)
                                if ok is False:
                                    Path(s["file"]).write_text(after, encoding="utf-8")
                                    wnote = ("the new test does not pass, so it was "
                                             "left in the file but NOT added to the "
                                             "suite: " + why)
                                    log(f"Placed edits: {name} — new test fails, "
                                        f"not registered ({why})", "warn")
                                else:
                                    log(f"Placed edits: {wnote} in {name}", "ok")
                    except Exception as e:
                        log(f"Auto-register skipped for {name}: {e}", "warn")
                        wnote = ""

                    # Run what it just wrote, and hand it back its own failure.
                    # One retry: a model that cannot fix its test given the
                    # actual traceback will not fix it given two.
                    fail = _check_new_tests(s["file"], before, after, workspace, mod)
                    # A test that does not run is a different problem from a test
                    # that runs and fails, and only one of them is visible in a
                    # traceback. Both go back in the same retry.
                    # ORDER MATTERS, and getting it wrong is measured: asking for
                    # a passing test AND registration in the same breath made the
                    # model wire in a test it had not fixed yet -- "public: 9
                    # failing (was 0)". Never demand registration of a test that
                    # is known broken. Green first, wired second.
                    unrun = ("" if fail else
                             _check_test_registered(s["file"], before_count, workspace, mod))
                    if unrun:
                        fail = unrun
                    # Order by ACTIONABILITY, not by severity. Measured, and the
                    # mistake was here: this used to overwrite `fail` with the
                    # suite note, so a model whose new test raised
                    #   KeyError: 'formats' at test_public.py:205
                    # was instead told
                    #   you broke the existing suite: 2 test(s) now FAIL
                    # A failing registered test IS a red suite, so both fire, and
                    # the vaguer one was winning. The retry's fix rate went from
                    # 6 of 7 to 0 of 6 and T3 fell 7.8 -> 7.0.
                    #
                    # A traceback names the line. A suite count names a file.
                    # Lead with the line; carry the suite note as context.
                    broke = _suite_regressions(suite_base, workspace)
                    if broke:
                        fail = (fail + "; and " + broke) if fail else broke
                    if fail:
                        log(f"Placed edits: {name} — {fail}, asking for a fix", "warn")
                        activity(req_id, "file", f"{n}/{total} {name}",
                                 "the new test fails — fixing")
                        try:
                            # Loop until clean rather than trying once. Each pass
                            # re-reads the file and re-states the CURRENT failure,
                            # so the model is always fixing what is actually wrong
                            # now, not what was wrong on the first attempt.
                            fail2, passes = fail, 0
                            while fail2 and passes < NEWTEST_REPAIRS:
                                passes += 1
                                if passes > 1:
                                    activity(req_id, "file", f"{n}/{total} {name}",
                                             f"still failing — fix {passes}/{NEWTEST_REPAIRS}")
                                retry = process_ai_response_with_tools(
                                    model, [{"role": "user", "content": mod.retry_prompt(
                                        s, Path(s["file"]).read_text(
                                            encoding="utf-8", errors="replace"), fail2)}],
                                    workspace=workspace, allow_all=allow_all, req_id=req_id,
                                    should_cancel=should_cancel, agent_mode=agent_mode,
                                    session_id=session_id, allow_split=False,
                                    only_file=s["file"])
                                calls += retry.get("tool_calls") or []
                                results += retry.get("tool_results") or []
                                after2 = Path(s["file"]).read_text(encoding="utf-8",
                                                                   errors="replace")
                                fail2 = _check_new_tests(s["file"], before, after2,
                                                         workspace, mod)
                                unrun2 = ("" if fail2 else
                                          _check_test_registered(s["file"], before_count,
                                                                 workspace, mod))
                                if unrun2:
                                    fail2 = unrun2
                                broke2 = _suite_regressions(suite_base, workspace)
                                if broke2:
                                    fail2 = (fail2 + "; and " + broke2) if fail2 else broke2
                                if should_cancel and should_cancel():
                                    break
                            plural = "attempt" if passes == 1 else "attempts"
                            if fail2:
                                wnote = (wnote + "; " if wnote else "") + (
                                    "the new test still fails after " + str(passes)
                                    + " fix " + plural + ": " + fail2)
                                log(f"Placed edits: {name} — still failing after "
                                    f"{passes}: {fail2}", "warn")
                            else:
                                wnote = (wnote + "; " if wnote else "") + (
                                    "the new test failed, was fixed in " + str(passes)
                                    + " " + plural + ", and now passes")
                                log(f"Placed edits: {name} — test fixed in {passes} "
                                    f"{plural} and passing", "ok")
                        except Exception as e:
                            log(f"Test-fix retry failed for {name}: {e}", "warn")
                            wnote = (wnote + "; " if wnote else "") + fail
                    plan.record(True, wnote)
        except Exception as e:
            log(f"Placed edit {n} failed: {e}", "error")
            plan.record(False, str(e)[:120])
        row = plan.results[-1] if plan.results else {}
        activity(req_id, "done", name, row.get("note") or "edited",
                 ok=bool(row.get("ok")))

    _touched = [s.get("file") for s in (plan.steps or []) if s.get("file")]

    if TEST_REGISTRY_GATE:
        _tf = [f for f in _existing_py(_touched) if _looks_like_test_file(f)]
        _dead = {}
        for _f in _tf:
            _d = _unregistered_tests(_f)
            if _d:
                _dead[_f] = _d
        log("Test registry gate: " + str(len(_tf)) + " test file(s) checked"
            + ("" if not _dead else " - "
               + str(sum(len(v) for v in _dead.values())) + " test(s) never run"),
            "warn" if _dead else "info")
        _gate_record(req_id, "test_registry", checked=len(_tf),
                     fired=bool(_dead),
                     dead=sorted(n for v in _dead.values() for n in v),
                     repair_passes=0, registered=False)
        _tr = 0
        while _dead and _tr < TEST_REGISTRY_REPAIRS:
            _tr += 1
            _f, _names = sorted(_dead.items())[0]
            activity(req_id, "retry", "tests are wired in",
                     ", ".join(_names)[:70], ok=False)
            clear_rewrites(session_id)
            try:
                _fix = process_ai_response_with_tools(
                    model,
                    [{"role": "user", "content": _test_registry_prompt(_f, _names)}],
                    workspace=workspace, allow_all=allow_all, req_id=req_id,
                    should_cancel=should_cancel, agent_mode=agent_mode,
                    session_id=session_id, allow_split=False)
                calls += _fix.get("tool_calls") or []
                results += _fix.get("tool_results") or []
            except Exception as _e:
                log("Test registry repair failed: " + str(_e), "error")
                break
            _dead = {}
            for _f2 in _tf:
                _d2 = _unregistered_tests(_f2)
                if _d2:
                    _dead[_f2] = _d2
            log("Test registry: after repair " + str(_tr) + "/"
                + str(TEST_REGISTRY_REPAIRS) + " - "
                + ("all tests are called" if not _dead else
                   str(sum(len(v) for v in _dead.values())) + " still never run"),
                "ok" if not _dead else "warn")
        if _tr:
            activity(req_id, "done", "tests are wired in",
                     "registered" if not _dead else "still not called",
                     ok=not _dead)
            _gate_record(req_id, "test_registry", repair_passes=_tr,
                         registered=not _dead)

    # The suite gate. Runs after EVERY step is done, not per step: a later step
    # can break what an earlier one fixed, and the per-step retry has already
    # had its single attempt by then.
    _revert_note = ""
    if SUITE_GATE and suite_base:
        _newfails = []
        _broke = _suite_regressions(suite_base, workspace, newfails=_newfails)
        log(f"Suite gate: {len(suite_base)} green suite(s) watched"
            + (" - REGRESSED" if _broke else " - still green"), "warn" if _broke else "info")
        if _newfails and not _broke:
            # Worth saying out loud: the tree is being KEPT with a red new test.
            # Before 2026-09-10 this reverted the whole change and the user saw
            # nothing but a note.
            log("Suite gate: keeping the work - the only failing test is new: "
                + "; ".join(_newfails[:2]), "warn")
        _gate_record(req_id, "suite", watched=len(suite_base), fired=bool(_broke),
                     repair_passes=0, repaired=False, reverted=False)
        _sg = 0
        while _broke and _sg < SUITE_GATE_REPAIRS:
            _sg += 1
            activity(req_id, "retry", "existing suite", _broke[:70], ok=False)
            clear_rewrites(session_id)
            try:
                _sfix = process_ai_response_with_tools(
                    model,
                    [{"role": "user", "content": _suite_repair_prompt(_broke, _touched)}],
                    workspace=workspace, allow_all=allow_all, req_id=req_id,
                    should_cancel=should_cancel, agent_mode=agent_mode,
                    session_id=session_id, allow_split=False)
                calls += _sfix.get("tool_calls") or []
                results += _sfix.get("tool_results") or []
            except Exception as _e:
                log(f"Suite repair failed: {_e}", "error")
                break
            _broke = _suite_regressions(suite_base, workspace)
            log(f"Suite gate: after repair {_sg}/{SUITE_GATE_REPAIRS} - "
                + (_broke[:80] if _broke else "green again"),
                "warn" if _broke else "ok")
        # Taken HERE, after the repair loop, not before it. The repair passes
        # are exactly what edits files outside the plan, so a ledger read
        # earlier would miss the writes this fix exists to catch.
        # Peek, not take: the job's "Changed:" line reads them too, and
        # run_chat_job's finally discards them for every job anyway.
        _orig_written = _originals_peek(req_id)
        if not _broke and _sg:
            activity(req_id, "done", "existing suite", "repaired", ok=True)
            _gate_record(req_id, "suite", repair_passes=_sg, repaired=True)
        elif _broke and SUITE_REVERT_ON_FAIL and (_orig_files or _orig_written):
            # Measured 2026-09-05: with a full traceback in hand, the repair
            # pass fixed 0 of 6 suite regressions -- against 6 of 7 for the
            # integration gate on mechanical import errors. Un-breaking fifty
            # passing tests means recognising that your own feature conflicts
            # with existing behaviour and giving it up, and the model will not
            # retract its own work.
            #
            # So stop asking. A tree that still works, plus an honest account of
            # what could not be done, beats a half-applied change that leaves
            # the suite red. The user can always ask again; they cannot as
            # easily discover which of their tests this quietly broke.
            # Plan-time originals cover the files the plan named; the
            # write-time ledger covers everything any pass actually touched,
            # including the repair passes that edit files outside the plan. The
            # plan-time copy wins on conflict because it was taken before the
            # first edit of the turn.
            _restore = dict(_orig_written)
            _restore.update(_orig_files)
            for _f, _body in _restore.items():
                try:
                    Path(_f).write_text(_body, encoding="utf-8")
                except OSError as _e:
                    log(f"Suite gate: could not restore {Path(_f).name}: {_e}", "error")
            _removed, _census_why = _remove_created(_census, workspace)
            if _removed:
                log(f"Suite gate: removed {len(_removed)} file(s) the run created: "
                    + ", ".join(Path(x).name for x in _removed[:5]), "warn")
            if _census_why:
                log("Suite gate: " + _census_why, "warn")
            _after_revert = _suite_regressions(suite_base, workspace)
            if _after_revert:
                log("Suite gate: reverted, but the suite is STILL red -- "
                    "something outside these files changed", "error")
                activity(req_id, "done", "existing suite", "still red after revert",
                         ok=False)
                _gate_record(req_id, "suite", repair_passes=_sg, repaired=False,
                             reverted=True, files_restored=len(_restore),
                             files_removed=len(_removed),
                             green_after_revert=False)
                _revert_note = ("These edits were undone because they broke the "
                                "existing tests, and the suite is STILL failing "
                                "afterwards -- something changed outside the files "
                                "listed above. Look before trusting this tree.")
            else:
                log(f"Suite gate: could not fix it in {SUITE_GATE_REPAIRS} attempts "
                    f"- reverted {len(_restore)} file(s), suite is green again",
                    "warn")
                activity(req_id, "done", "existing suite",
                         f"reverted {len(_restore)} file(s)", ok=False)
                _gate_record(req_id, "suite", repair_passes=_sg, repaired=False,
                             reverted=True, files_restored=len(_restore),
                             files_removed=len(_removed),
                             green_after_revert=True)
                _undone = (str(len(_restore)) + " file(s) restored"
                           + (", " + str(len(_removed)) + " newly created file(s) "
                              "removed" if _removed else ""))
                _revert_note = (
                    "NOT APPLIED. The change broke tests that were passing before "
                    "it, and " + str(SUITE_GATE_REPAIRS) + " attempts to fix it "
                    "failed, so it was undone (" + _undone + ") and the suite is "
                    "green again." + NL + NL + "What broke:" + NL + _broke[:600] +
                    (NL + NL + "Note: " + _census_why if _census_why else "") +
                    NL + NL + "Ask again with a narrower change, or say to keep it "
                    "anyway.")
        elif _broke:
            activity(req_id, "done", "existing suite", "still red", ok=False)
            # Shipped red. Distinguish it from a revert: same bad outcome for
            # the suite, opposite outcome for the tree.
            _gate_record(req_id, "suite", repair_passes=_sg, repaired=False,
                         reverted=False, left_red=True)

    # The integration gate, third and last exit path.
    #
    # Measured 2026-09-05: T3 routes ENTIRELY through here -- 72 placed-edit
    # invocations across 18 runs -- and the gate fired zero times, because it
    # was wired into try_build_plan() and the ordinary loop but not this one.
    # A file-count check said T3 touches 3-4 .py files and would trigger it; the
    # file count was right and the code path was never checked.
    #
    # This path CHANGES an existing codebase rather than building a new package,
    # so the question is the same but sharper: do the edited modules still
    # import alongside each other after being changed.
    _pe = _existing_py([s.get("file") for s in (plan.steps or [])])
    log(f"Integration gate (placed edits): {len(_pe)} python file(s) touched"
        + ("" if len(_pe) >= 2 else " - not checking, needs 2+"), "info")
    _gate_record(req_id, "imports", path="placed_edits", checked=len(_pe),
                 ran=bool(BUILD_IMPORT_GATE and len(_pe) >= 2))
    if BUILD_IMPORT_GATE and len(_pe) >= 2:
        _ok, _detail, _mods = _imports_together(_pe, workspace)
        # ok is None when the question could not be asked at all -- that is not
        # a pass, and it must not be recorded as one.
        # path and checked are already on the record from the line above; the
        # other two exit paths do not restate them either.
        _gate_record(req_id, "imports",
                     fired=(_ok is False), provable=(_ok is not None),
                     repair_passes=0, imports_ok=(_ok is True), repaired=False)
        _tries = 0
        while _ok is False and _tries < BUILD_IMPORT_REPAIRS:
            _tries += 1
            _first = _detail.splitlines()[-1][:90] if _detail else "import failed"
            log(f"Placed edits: the result does not import together - {_first}", "warn")
            activity(req_id, "retry", "imports together", _first, ok=False)
            clear_rewrites(session_id)   # see the note in try_build_plan
            try:
                _fix = process_ai_response_with_tools(
                    model,
                    [{"role": "user",
                      "content": _import_repair_prompt(_pe, _mods, _detail)}],
                    workspace=workspace, allow_all=allow_all, req_id=req_id,
                    should_cancel=should_cancel, agent_mode=agent_mode,
                    session_id=session_id, allow_split=False)
                calls += _fix.get("tool_calls") or []
                results += _fix.get("tool_results") or []
            except Exception as _e:
                log(f"Placed edits: import repair failed: {_e}", "error")
                break
            _ok, _detail, _mods = _imports_together(_pe, workspace)
            _after = (_detail.splitlines()[-1][:90] if _detail else "clean")
            log(f"Placed edits: after repair {_tries}/{BUILD_IMPORT_REPAIRS} - {_after}",
                "ok" if _ok is True else "warn")
        if _ok is True and _tries:
            activity(req_id, "done", "imports together", "repaired", ok=True)
            _gate_record(req_id, "imports", repair_passes=_tries,
                             imports_ok=True, repaired=bool(_tries))
        elif _ok is False:
            activity(req_id, "done", "imports together", "still failing", ok=False)
            _gate_record(req_id, "imports", repair_passes=_tries, imports_ok=False, repaired=False)

    _report = plan.report()
    if _revert_note:
        _report += NL + NL + _revert_note
    return {"final_response": _report, "tool_calls": calls,
            "tool_results": results, "needs_permission": None}


def _save_chat_job(jid):
    try:
        CHAT_JOBS_DIR.mkdir(parents=True, exist_ok=True)
        with _lock:
            rec = dict(_chat_jobs.get(jid, {}))
        (CHAT_JOBS_DIR / f"{jid}.json").write_text(json.dumps(rec, default=str), encoding="utf-8")
    except Exception as e:
        log(f"chat job save failed: {e}", "warn")

def _update_chat_job(jid, **kw):
    with _lock:
        j = _chat_jobs.setdefault(jid, {"job_id": jid})
        j.update(kw)
        j["updated"] = time.time()
    _save_chat_job(jid)

def _reap_stale_chat_jobs():
    """On startup, any job still marked running died with the previous process."""
    try:
        if not CHAT_JOBS_DIR.exists():
            return
        for f in CHAT_JOBS_DIR.glob("*.json"):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                if rec.get("status") == "running":
                    rec["status"] = "interrupted"
                    rec["error"]  = "NeuralDock restarted while this request was running."
                    f.write_text(json.dumps(rec, default=str), encoding="utf-8")
            except Exception:
                pass
    except Exception:
        pass

def run_chat_job(jid, model, messages, workspace, allow_all, approved, agent_mode=False, plain=False, session_id=None):
    t0 = time.time()
    _update_chat_job(jid, status="running", started=t0, model=model)
    # The one place that can tell a new user message from a resumed turn: this
    # is reached only from POST /api/chat. See forgive_session_calls.
    forgive_session_calls(session_id)
    # A new request gets a new plan. A plan belongs to the request that made it;
    # carried forward it tells the model the NEXT request is already finished.
    # Only a bare nudge ("continue", "try again") keeps it, because that is the
    # same request resumed.
    try:
        _lu = next((m.get("content") for m in reversed(messages or [])
                    if isinstance(m, dict) and m.get("role") == "user"), "")
        _same_request = (is_continuation(_lu)
                         # "try again and make the repair", "ok but blue" --
                         # a message that OPENS with a nudge is the same request
                         # carried on, however much follows.
                         or bool(_CONTINUATION_RE.match(_lu or ""))
                         # ND's own follow-up buttons are continuations by
                         # definition; clearing the plan on "Continue - next
                         # file" would defeat the button.
                         or (_lu or "").strip() in (CONTINUE_NEXT, LIST_REMAINING,
                                                    VERIFY_WHAT_EXISTS, DIFFERENT_TACK))
        if session_id and isinstance(_lu, str) and _lu.strip() \
                and not _same_request and recall_ctx(session_id, "plan"):
            forget_ctx(session_id, "plan")
            log("New request - cleared the previous request's plan", "info")
    except Exception as _pe:
        log(f"plan expiry skipped: {_pe}", "warn")
    try:
        if plain:
            # No tools, no agent system prompt. Used for the vision describe step:
            # feeding a captioning model the tool instructions makes it recite them
            # back instead of describing the picture.
            with _lock:
                _chat_status[jid] = {"stage": "generating", "detail": "Looking at the image…",
                                     "pct": 40, "start": t0}
            txt = ollama_chat(model, messages, status_cb=lambda n: None,
                              text_cb=lambda d: stream_append(jid, d))
            _update_chat_job(jid, status="done", reply=txt, tool_calls=[], tool_results=[],
                             needs_permission=None, elapsed_sec=round(time.time()-t0, 1))
            log(f"Plain chat job {jid} finished ({round(time.time()-t0,1)}s)", "ok")
            return
        # Every model call in this thread can see the cancel flag, so a stop
        # request ends a long reply mid-stream instead of after it.
        _job_ctx.cancel_check = lambda: jid in _chat_cancel
        result = process_ai_response_with_tools(
            model, messages, workspace=workspace, allow_all=allow_all,
            pending_permissions=approved, req_id=jid,
            should_cancel=lambda: jid in _chat_cancel, agent_mode=agent_mode,
            session_id=session_id)
        # What this job ACTUALLY changed, measured on disk, as the reply's first
        # line. Here, not inside the agent loop, because every route -- placed
        # edits, the build planner, the plain loop -- comes back through this one
        # line. Not while it is parked on a permission: that is not the end.
        _reply = result.get("final_response", "") or ""
        if not result.get("needs_permission"):
            try:
                _lu = next((m.get("content") for m in reversed(messages or [])
                            if isinstance(m, dict) and m.get("role") == "user"), "")
                _cs = change_summary(jid, result.get("tool_calls") or [],
                                     wanted_change=_wants_code_change(str(_lu or "")))
                if _cs:
                    _reply = _cs + "\n\n" + _reply
            except Exception as _cse:
                log(f"change summary skipped: {_cse}", "warn")
        if jid in _chat_cancel:
            _update_chat_job(jid, status="cancelled", elapsed_sec=round(time.time()-t0,1))
        else:
            _update_chat_job(jid, status="done",
                             reply=pin_run_commands(_reply, workspace),
                             tool_calls=result.get("tool_calls",[]),
                             tool_results=result.get("tool_results",[]),
                             needs_permission=result.get("needs_permission"),
                             files_written=result.get("files_written") or [],
                             next_actions=result.get("next_actions"),
                             # Record what RAN, and what was asked for, separately.
                             # Measured 2026-09-24: the picker chose the 30B, the
                             # 30B did the work, and the job file said "Devstral"
                             # because that is what the dropdown showed -- which
                             # made a context timeout look like a picker bug.
                             model=result.get("model_used") or model,
                             model_requested=model,
                             gates=_gate_take(jid),
                             elapsed_sec=round(time.time()-t0,1))
        log(f"Chat job {jid} finished ({round(time.time()-t0,1)}s)", "ok")
    except Exception as e:
        log(f"Chat job {jid} error: {e}", "error")
        _update_chat_job(jid, status="error", error=str(e), elapsed_sec=round(time.time()-t0,1))
    finally:
        _gate_take(jid)          # bounded: no run leaves a record behind
        _originals_take(jid)     # same for file contents, which are far bigger
        _chat_cancel.discard(jid)
        with _lock:
            _chat_status.pop(jid, None)
            # A job that errored or was cancelled while parked must not leave a
            # wait behind, or the next /api/chat_permit for that id resolves a
            # thread that no longer exists.
            _perm_waits.pop(jid, None)
            _ask_waits.pop(jid, None)     # same for a parked ask_user question

_SPEC_REF = re.compile(
    r"(?:described in|specified in|according to|as per|per|defined in|spelled out in|laid out in)"
    r"\s+[`'\"]?([\w.\\/:-]+\.(?:md|txt|rst))", re.I)


def spec_files_in(text, workspace=None):
    """Files a request names as its specification, as resolved absolute paths."""
    out = []
    for name in _SPEC_REF.findall(text or ""):
        q = Path(name)
        if not q.is_absolute() and workspace:
            q = Path(workspace) / q
        try:
            out.append(str(q.resolve()))
        except OSError:
            pass
    return sorted(set(out))


SPEC_PLAN_CHARS = 12000
_SCRIPT_SRC = re.compile(r"""<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""", re.I)


def check_pages(workspace, limit=8):
    """[(page path, problems)] for pages in the workspace whose local scripts look
    up ids the page lacks, or draw on an element that is not a <canvas>."""
    mod = build_plan_mod()
    if not mod or not workspace or not hasattr(mod, "page_problems"):
        return []
    ws, out = Path(workspace), []
    pages = [p for p in ws.rglob("*.htm*")
             if not any(part in PLACE_SKIP_DIRS or part.startswith(".") for part in p.relative_to(ws).parts)]
    for page in pages[:limit]:
        try:
            html = page.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scripts, script_paths, ordered = [], [], []
        for src in _SCRIPT_SRC.findall(html):
            if re.match(r"^[a-z]+://|^//", src, re.I):
                continue
            _q0 = (ws / src.lstrip("/")) if src.startswith("/") else (page.parent / src)
            if not _q0.is_file() and src.startswith("/"):
                _q0 = page.parent / src.lstrip("/").split("/", 1)[-1]
            try:
                ordered.append((Path(src).name, _q0.read_text(encoding="utf-8", errors="replace")))
            except OSError:
                pass
            if "elena_mark" in src:
                continue
            q = (ws / src.lstrip("/")) if src.startswith("/") else (page.parent / src)
            if not q.is_file() and src.startswith("/"):
                q = page.parent / src.lstrip("/").split("/", 1)[-1]
            try:
                scripts.append(q.read_text(encoding="utf-8", errors="replace"))
                script_paths.append(str(q))
            except OSError:
                pass
        inline = re.findall(r"<script\b(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I)
        if not scripts and not inline:
            continue
        prob = mod.page_problems(html, scripts + inline)
        prob["order"] = mod.script_order_problems(ordered) if hasattr(mod, "script_order_problems") else []
        prob["script_bugs"] = []
        for sp, st in zip(script_paths, scripts):
            for var, tag in mod.drawn_non_canvas_created(st):
                prob["script_bugs"].append((sp, var, tag))
        # The other direction: page elements that show live state but that no
        # script drives (pair 10: an overlay nothing hides, readouts stuck at "-").
        prob["undriven"] = (mod.undriven_ids(html, scripts + inline)
                            if hasattr(mod, "undriven_ids") and _config.get("agent_undriven_check", True) else [])
        prob["main_script"] = (max(zip(script_paths, scripts), key=lambda ps: len(mod.js_ids_used(ps[1])))[0]
                               if script_paths else "")
        if not prob["main_script"]:
            prob["undriven"] = []         # inline scripts only: nothing to point a repair at
        if prob["missing"] or prob["not_canvas"] or prob["script_bugs"] or prob["order"] or prob["undriven"]:
            out.append((str(page), prob))
    return out


_SERVER_HINT = re.compile(r"http\.server|HTTPServer|Flask\(|FastAPI\(|uvicorn\.run|web\.run_app|serve_forever")
_LINK_HREF = re.compile(r"""<link\b[^>]*\brel\s*=\s*["']stylesheet["'][^>]*\bhref\s*=\s*["']([^"']+)["']""", re.I)


def find_web_server(workspace):
    """The project's web server script, or None."""
    ws = Path(workspace)
    cands = []
    for p in sorted(ws.glob("*.py")):
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "__main__" in src and _SERVER_HINT.search(src) and not _looks_like_test_file(p):
            cands.append(p)
    pref = {"server.py": 0, "app.py": 1, "main.py": 2}
    cands.sort(key=lambda p: pref.get(p.name.lower(), 9))
    return cands[0] if cands else None


def _http_get(url, timeout=4):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return None, ""


_BROWSER_COLLECT = r"""
window.__ndErrs = [];
window.addEventListener('error', function (e) {
  if (e && e.target && e.target !== window && (e.target.src || e.target.href)) {
    window.__ndErrs.push('failed to load ' + (e.target.src || e.target.href)); return;
  }
  window.__ndErrs.push(String((e && (e.message || (e.error && e.error.message))) || e));
}, true);
window.addEventListener('unhandledrejection', function (e) {
  window.__ndErrs.push('unhandled rejection: ' + String(e && e.reason));
});
"""
_BROWSER_PROBE = r"""
(function () {
  var out = {errors: (window.__ndErrs || []).slice(0, 8), canvases: []};
  Array.prototype.slice.call(document.querySelectorAll('canvas')).forEach(function (c) {
    var r = c.getBoundingClientRect();
    out.canvases.push({id: c.id || '', cls: c.className || '', w: Math.round(r.width), h: Math.round(r.height),
                       bw: c.width, bh: c.height});
  });
  return out;
})()
"""


def browser_probe(url, settle=5.0):
    """Load `url` in a headless browser. {"errors": [...], "canvases": [...]} or {"why": str}."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from nd_browser import NDBrowser
    except Exception as e:
        return {"why": f"no browser driver: {e}"}
    with tempfile.TemporaryDirectory(prefix="nd_probe_", ignore_cleanup_errors=True) as prof:
        s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); bport = s_.getsockname()[1]; s_.close()
        b = NDBrowser(prof, port=bport, headless=True)
        try:
            why = b.available()
            if why:
                return {"why": str(why)}
            err = b._ensure_running()
            if err:
                return {"why": str(err)}
            b._send("Page.enable", {})
            b._send("Page.addScriptToEvaluateOnNewDocument", {"source": _BROWSER_COLLECT})
            b._send("Page.navigate", {"url": url})
            time.sleep(settle)
            return b._eval(_BROWSER_PROBE, timeout=20) or {"why": "no answer from the page"}
        except Exception as e:
            return {"why": f"browser probe failed: {e!r}"}
        finally:
            try:
                b.close()
            except Exception:
                pass


def serve_check(workspace, wait=20):
    """{"server": name, "problems": [(url, status)], "why": str} - or None when
    the project has no web server to run."""
    srv = find_web_server(workspace)
    if not srv:
        return None
    s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); port = s_.getsockname()[1]; s_.close()
    env = dict(os.environ, PORT=str(port), VIZ_PORT=str(port), APP_PORT=str(port),
               SERVER_PORT=str(port), HTTP_PORT=str(port), PYTHONUNBUFFERED="1")
    out_file = tempfile.NamedTemporaryFile(prefix="nd_serve_", suffix=".log", delete=False)
    proc = subprocess.Popen([_project_python(workspace), str(srv)], cwd=str(workspace), env=env,
                            stdout=out_file, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        src = srv.read_text(encoding="utf-8", errors="replace")
        ports = [port] + [int(x) for x in re.findall(r"\b(\d{4,5})\b", src)
                          if 1024 < int(x) < 65536 and int(x) != port][:4]
        base, t0 = None, time.time()
        while time.time() - t0 < wait and base is None:
            if proc.poll() is not None:
                break
            try:
                logtxt = Path(out_file.name).read_text(encoding="utf-8", errors="replace")
            except OSError:
                logtxt = ""
            for m in re.findall(r"https?://(?:127\.0\.0\.1|localhost|0\.0\.0\.0):(\d{2,5})", logtxt):
                if int(m) not in ports:
                    ports.append(int(m))
            for pt in ports:
                code, _ = _http_get(f"http://127.0.0.1:{pt}/", timeout=2)
                if code is not None:
                    base = f"http://127.0.0.1:{pt}/"
                    break
            if base is None:
                time.sleep(0.7)
        if base is None:
            try:
                tail = Path(out_file.name).read_text(encoding="utf-8", errors="replace")[-600:]
            except OSError:
                tail = ""
            return {"server": srv.name, "problems": [("(server)", "did not start or answer")],
                    "why": tail}
        code, html = _http_get(base)
        problems = [] if code == 200 else [("/", code)]
        refs = [r for r in _SCRIPT_SRC.findall(html) + _LINK_HREF.findall(html)
                if not re.match(r"^[a-z]+://|^//|^data:", r, re.I)]
        for ref in refs[:20]:
            u = urllib.parse.urljoin(base, ref)
            c2, _ = _http_get(u)
            if c2 != 200:
                problems.append((ref + "  (requested as " + urllib.parse.urlparse(u).path + ")", c2))
        # A real browser: layout and runtime errors cannot be seen any other way
        # (Elena Live pair 9: no errors, both canvases laid out 0px tall).
        if not problems and _config.get("agent_browser_check", True):
            pr = browser_probe(base)
            if pr.get("why"):
                log(f"Browser check skipped: {pr['why']}", "info")
            for e in pr.get("errors") or []:
                problems.append(("script error in the browser: " + str(e)[:200], "error"))
            for cv in pr.get("canvases") or []:
                if (cv.get("w") or 0) == 0 or (cv.get("h") or 0) == 0:
                    name = "#" + cv["id"] if cv.get("id") else ("canvas." + cv["cls"] if cv.get("cls") else "a canvas")
                    problems.append((f"{name} is laid out {cv.get('w')}x{cv.get('h')}px - it has no "
                                     "room to draw (give it or its container a real width and height)",
                                     "zero size"))
                elif (cv.get("bw"), cv.get("bh")) == (300, 150) and (cv.get("w") or 0) >= 100                         and (cv.get("h") or 0) >= 100 and ((cv.get("w"), cv.get("h")) != (300, 150)):
                    name = "#" + cv["id"] if cv.get("id") else ("canvas." + cv["cls"] if cv.get("cls") else "a canvas")
                    problems.append((f"{name} shows at {cv.get('w')}x{cv.get('h')}px but its drawing buffer "
                                     "is still the default 300x150 - the script never sized it (set "
                                     "canvas.width/height from its laid-out size times devicePixelRatio, "
                                     "on load and on resize) and never drew at that size", "never sized"))
        return {"server": srv.name, "problems": problems, "why": "", "html": html}
    finally:
        try:
            proc.kill(); proc.wait(timeout=10)
        except Exception:
            pass
        try:
            out_file.close(); os.unlink(out_file.name)
        except OSError:
            pass


def repair_serving(model, workspace, req_id, session_id, allow_all, should_cancel, agent_mode):
    """Serve check, one repair step if the page cannot load what it asks for. Returns a note."""
    if not _config.get("agent_serve_check", True):
        return ""
    res = serve_check(workspace)
    if not res or not res["problems"]:
        return ""
    lines = "\n".join(f"  {u} -> {c}" for u, c in res["problems"])
    log(f"Serve check: {res['server']} - {len(res['problems'])} problem(s) - one repair step", "warn")
    agent_activity(req_id, "retry", "serve check", f"{len(res['problems'])} problem(s)", ok=False)
    page_html = (res.get("html") or "")
    shown = page_html if len(page_html) <= 16000 else page_html[:16000] + "\n...(truncated)"
    prompt = (f"ND started {res['server']} and loaded its page in a real browser. These are "
              f"wrong:\n{lines}\n" + (f"\nServer output:\n{res['why']}\n" if res["why"] else "")
              + "\nFix it with the smallest change. A file that did not load: the page's path is "
              "wrong (use the path the server serves) or the server does not serve it. A script "
              "error: fix the script. A canvas with no size: give it or its container a real "
              "width and height in the page's CSS. Change only the page, its script, or "
              + res["server"] + "."
              + ("\n\nThe page as the server sends it (no need to read it first):\n-----\n" + shown
                 if shown else ""))
    try:
        process_ai_response_with_tools(
            model, [{"role": "user", "content": prompt}], workspace=workspace,
            allow_all=allow_all, req_id=req_id, should_cancel=should_cancel,
            agent_mode=agent_mode, session_id=session_id, allow_split=False)
    except Exception as e:
        log(f"serve repair failed: {e}", "error")
    again = serve_check(workspace) or {"problems": []}
    _gate_record(req_id, "serve", problems=len(res["problems"]), still=len(again["problems"]))
    if not again["problems"]:
        return (f"\n\nServe check: the page could not load {len(res['problems'])} file(s) "
                f"through {res['server']} - fixed in one repair step.")
    return ("\n\nServe check: the page still cannot load, through " + res["server"] + ":\n"
            + "\n".join(f"  {u} -> {c}" for u, c in again["problems"]))


def page_repair_prompt(page, prob):
    bits = []
    if prob.get("missing"):
        bits.append("these element ids its scripts look up are missing (getElementById "
                    "returns null and the script dies on load): " + ", ".join(prob["missing"]))
    if prob.get("not_canvas"):
        bits.append("these ids are drawn on with getContext but are not <canvas> elements: "
                    + ", ".join(f"#{i} is a <{t}>" for i, t in prob["not_canvas"]))
    if prob.get("order"):
        bits.append("scripts load in the wrong order: " + ", ".join(
            f"{u} uses {g}, which {d} defines, but {d} loads AFTER it" for u, g, d in prob["order"])
            + " - move each defining <script> tag above the one that uses it")
    try:
        body = Path(page).read_text(encoding="utf-8", errors="replace")
    except OSError:
        body = ""
    # The page itself, so the repair needs no read_file: in the overnight runs
    # the session's repeat guard refused every re-read and the repair never edited.
    shown = body if len(body) <= 16000 else body[:16000] + "\n...(truncated)"
    return (f"The page {page} cannot run as written - " + "; ".join(bits) + ". Fix the PAGE: "
            "add each missing element with exactly that id, in the place its name suggests "
            "(a <canvas> for anything drawn on), make every drawn-on id a <canvas>, and put "
            "the scripts in an order that works. Do not rename ids and do not touch any "
            "other file. The page's current content is below - edit it with edit_file "
            "(old_text copied exactly from it) or rewrite it whole with write_file; you do "
            "not need to read it first.\n\n----- " + Path(page).name + " -----\n" + shown)


_JS_ANCHOR = re.compile(
    r"getElementById|querySelector|\bfetch\(|function\s+(?:setState|poll|update\w*|render\w*|apply\w*|"
    r"ingest\w*|on\w*State|tick)\b|(?:setState|poll|update\w*|ingest\w*)\s*[:=]\s*(?:async\s+)?function")


def script_excerpt(js, budget=9000, before=4, after=30):
    """The parts of a script a wiring fix needs: its element lookups and where data
    arrives. Whole lines, in order, gaps marked with '...'."""
    lines = js.splitlines()
    keep = set()
    for n, line in enumerate(lines):
        if _JS_ANCHOR.search(line):
            span = after if not re.search(r"getElementById|querySelector", line) else 2
            keep.update(range(max(0, n - before), min(len(lines), n + span + 1)))
    out, last, size = [], -2, 0
    for n in sorted(keep):
        if n != last + 1:
            out.append("...")
        out.append(lines[n]); size += len(lines[n]) + 1; last = n
        if size > budget:
            out.append("...(more of the script not shown)")
            break
    return "\n".join(out)


def undriven_repair_prompt(page, prob):
    """One step for the page's main script: drive the live elements it ignores,
    and stop looking up ids the page does not have."""
    sp = prob["main_script"]
    try:
        html = Path(page).read_text(encoding="utf-8", errors="replace")
    except OSError:
        html = ""
    try:
        js = Path(sp).read_text(encoding="utf-8", errors="replace")
    except OSError:
        js = ""
    # Excerpts only: whole files overflowed a 32K window (polish_01).
    shown_html = "\n".join(l.strip() for l in html.splitlines() if re.search(r"\bid\s*=", l))[:3000]
    shown_js = js if len(js) <= 9000 else script_excerpt(js)
    und = ", ".join(f"#{i}" + (f' (shows "{t}")' if t else "") for i, t in prob["undriven"])
    miss = ", ".join("#" + i for i in prob.get("missing") or [])
    return (f"{Path(page).name} loads and runs, but it never comes alive: these elements show "
            f"live state and NO script ever updates them, so they stay as written forever: {und}."
            + (f" Meanwhile {Path(sp).name} looks up ids the page does not have: {miss} - those "
               "lookups return null and update nothing. They are very likely the same elements "
               "under different names." if miss else "")
            + f"\n\nFix {Path(sp).name} (this file only): in the place where new data arrives "
              "(the poll / setState / render step), update each element above from the data the "
              "script already has - readouts get their value, pills/status get their state, "
              "counts and clocks tick - and HIDE any overlay or 'waiting' message as soon as the "
              "first data arrives (show it again only when the data source stops answering)."
            + (" Point every lookup of a missing id at the page's real element instead." if miss else "")
            + " Use the page's ids exactly as written. Do not change the page."
              " Below: the page's elements that have ids, and the parts of the script that look "
              "elements up and receive data ('...' marks lines left out). Edit with edit_file, "
              "old_text copied exactly from these lines - you do not need to read either file."
              "\n\n----- " + Path(page).name + " (elements with ids) -----\n" + shown_html
            + "\n\n----- " + Path(sp).name + " (excerpts) -----\n" + shown_js)


def repair_pages(model, workspace, req_id, session_id, allow_all, should_cancel, agent_mode):
    """Check the workspace's pages; one repair step per broken page. Returns a note."""
    probs = check_pages(workspace)
    if not probs:
        return ""
    notes = []
    for page, prob in probs[:2]:
        log(f"Page check: {Path(page).name} - {len(prob['missing'])} missing id(s), "
            f"{len(prob['not_canvas'])} not a canvas, {len(prob.get('script_bugs') or [])} "
            f"script bug(s), {len(prob.get('undriven') or [])} element(s) nothing drives "
            "- one repair step each", "warn")
        agent_activity(req_id, "retry", "page/script ids", Path(page).name, ok=False)
        jobs = []
        if prob.get("undriven"):
            # The script is pointed at the page's real elements; missing ids go with it.
            jobs.append((prob["main_script"], undriven_repair_prompt(page, prob)))
            if prob["not_canvas"] or prob.get("order"):
                jobs.append((page, page_repair_prompt(page, dict(prob, missing=[]))))
        elif prob["missing"] or prob["not_canvas"] or prob.get("order"):
            jobs.append((page, page_repair_prompt(page, prob)))
        for sp, var, tag in (prob.get("script_bugs") or [])[:2]:
            jobs.append((sp, (f"{sp} creates `{var}` as a <{tag}> and then draws on it "
                              "(getContext, or new ElenaMark - which calls getContext), so it "
                              "throws on load. Fix THIS file: make it a <canvas> (or use the "
                              "page's existing canvas). Do not touch any other file.")))
        for target, prompt in jobs:
            try:
                process_ai_response_with_tools(
                    model, [{"role": "user", "content": prompt}],
                    workspace=workspace, allow_all=allow_all, req_id=req_id,
                    should_cancel=should_cancel, agent_mode=agent_mode,
                    session_id=session_id, allow_split=False, only_file=target)
            except Exception as e:
                log(f"page repair failed: {e}", "error")
    left = check_pages(workspace)
    _gate_record(req_id, "element_ids", pages=len(probs), still_broken=len(left))
    if not left:
        return (f"\n\nPage check: {len(probs)} page(s) did not match their scripts "
                "(missing ids / non-canvas elements) - fixed in one repair step.")
    return ("\n\nPage check: still cannot run - " + "; ".join(
        f"{Path(p).name}: missing {', '.join(pr['missing']) or 'none'}"
        + (f", not a canvas: {', '.join(i for i, _ in pr['not_canvas'])}" if pr["not_canvas"] else "")
        + (f", script draws on a non-canvas: {', '.join(Path(a).name + ':' + v for a, v, _ in pr['script_bugs'])}"
           if pr.get("script_bugs") else "")
        + (f", never updated by any script: {', '.join(i for i, _ in pr['undriven'])}"
           if pr.get("undriven") else "")
        for p, pr in left))
READ_ONLY_TOOLS = ("read_file", "list_dir", "search_files", "find_definition", "find_references")
READ_LOOP_MAX = int(_config.get("agent_read_loop_max", 8)) if isinstance(_config, dict) else 8


def test_failures_in(output):
    """(passed, failed) from the LAST "N passed, M failed" line of a run, or None."""
    m = None
    for line in (output or "").splitlines():
        f = _COUNT_RE.search(line)
        if f:
            m = f
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


TESTS_FIRST_NOTE = (
    "\n\n[NeuralDock: {failed} test(s) FAIL in {name}. Fixing them is the next job: "
    "edit the code they test (not the tests, unless a test is plainly wrong), then "
    "run {name} again. Read only the parts you need - do not re-read whole files you "
    "have already seen. No design polish until this passes.]")

_KEEP_REF = re.compile(
    r"(?:keep|leave)\s+[`'\"]?([\w.\\/:-]+\.\w{1,5})[`'\"]?\s+(?:unchanged|untouched|as it is|as is|alone)"
    r"|(?:do not|don't|never)\s+(?:modify|change|touch|edit|rewrite)\s+[`'\"]?([\w.\\/:-]+\.\w{1,5})", re.I)
_KEEP_LINE = re.compile(r"(?:do not|don't|never)\s+(?:modify|change|touch|edit|rewrite)|unchanged|untouched", re.I)
_FILE_IN_LINE = re.compile(r"`([\w.\\/:-]+\.\w{1,5})`")


def keep_files_in(text, workspace=None):
    """Files the request (or a spec it names) says must not be changed."""
    names = [a or b for a, b in _KEEP_REF.findall(text or "")]
    for f in spec_files_in(text, workspace):
        try:
            for line in Path(f).read_text(encoding="utf-8", errors="replace").splitlines():
                if _KEEP_LINE.search(line):
                    names += _FILE_IN_LINE.findall(line)
        except OSError:
            pass
    out = []
    for name in names:
        q = Path(name)
        if not q.is_absolute() and workspace:
            q = Path(workspace) / q
        try:
            out.append(str(q.resolve()))
        except OSError:
            pass
    return sorted(set(out))


def spec_block(task, workspace=None, limit=SPEC_PLAN_CHARS):
    """The text of the spec(s) a request names, for a planner that would
    otherwise see only the one-line request. Its file list is authoritative:
    the house style applies only where the spec says nothing."""
    out = []
    for f in spec_files_in(task, workspace):
        try:
            txt = Path(f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(txt) > limit:
            txt = txt[:limit] + "\n...(spec truncated)"
        out.append(f"--- {Path(f).name} ---\n{txt}")
    if not out:
        return ""
    return ("\n\nTHE SPEC this request is built from. Plan EXACTLY the files it names, at "
            "exactly the paths it gives - no more, no fewer, no renames, no merging "
            "several into one. House style and any other default apply only where the "
            "spec is silent; where they disagree, the spec wins.\n\n" + "\n\n".join(out))


def process_ai_response_with_tools(model, messages, workspace=None, allow_all=False, pending_permissions=None, req_id=None, should_cancel=None, agent_mode=False, session_id=None, allow_split=True, only_file=None):
    """Run Ollama chat with tool calling support. Returns dict with final_response, tool_calls, needs_permission."""
    import time as _time

    def _set_status(stage, detail, pct=50):
        if req_id:
            with _lock:
                prev = _chat_status.get(req_id, {})
                _chat_status[req_id] = {"stage": stage, "detail": detail, "pct": pct,
                                        "start": prev.get("start", _time.time()),
                                        # carry the activity feed across updates,
                                        # otherwise each status write wiped it
                                        "activity": prev.get("activity", []),
                                        "round": prev.get("round", 0),
                                        # Same hazard as the activity feed above:
                                        # _set_status fires several times a round
                                        # and rebuilding the dict without these
                                        # would blank the live text mid-sentence.
                                        "stream": prev.get("stream", ""),
                                        "stream_base": prev.get("stream_base", 0),
                                        "stream_len": prev.get("stream_len", 0),
                                        # and the parked permission request, for
                                        # exactly the same reason
                                        "awaiting_permission": prev.get("awaiting_permission"),
                                        # and a parked ask_user question, same hazard
                                        "awaiting_question": prev.get("awaiting_question")}

    def _stream(delta):
        """Hand generated text to the live view as it arrives."""
        stream_append(req_id, delta)

    def _ask_permission(needs):
        """Park this turn until the user decides, instead of ending it.

        Returns {"approved": set, "denied": set, "cancelled": bool}, or None when
        there is no req_id -- a direct caller (the tests) has nowhere to send the
        question, so the old return-and-resend contract still applies to them.
        """
        if not req_id:
            return None
        ev = threading.Event()
        with _lock:
            _perm_waits[req_id] = {"needs": needs, "event": ev,
                                   "approved": set(), "denied": set(),
                                   "asked": _time.time()}
        # _set_status rebuilds the status dict, so publish the request AFTER it
        # (and it is carried across writes too -- see the carry list above).
        _set_status("awaiting", "Waiting for you: " +
                    ", ".join(n["tool"] for n in needs[:3]), 50)
        with _lock:
            _chat_status.setdefault(req_id, {})["awaiting_permission"] = needs
        agent_activity(req_id, "ask", "permission needed",
                       ", ".join(n["tool"] for n in needs[:3]))
        log(f"Job {req_id} parked waiting for approval of "
            f"{', '.join(n['tool'] for n in needs)}", "info")
        deadline = _time.time() + PERM_WAIT_SECONDS
        timed_out = False
        while not ev.wait(0.25):
            if should_cancel and should_cancel():
                break
            if _time.time() > deadline:
                timed_out = True
                log(f"Permission request for job {req_id} went unanswered for "
                    f"{PERM_WAIT_SECONDS}s - treating it as denied", "warn")
                break
        with _lock:
            rec = _perm_waits.pop(req_id, {})
            st = _chat_status.get(req_id)
            if st is not None:
                st.pop("awaiting_permission", None)
        cancelled = bool(should_cancel and should_cancel())
        if not cancelled and not timed_out:
            log(f"Job {req_id} resumed in place ({len(rec.get('approved') or ())} "
                f"approved, {len(rec.get('denied') or ())} denied)", "ok")
        return {"approved": set(rec.get("approved") or ()),
                "denied": set(rec.get("denied") or ()),
                "cancelled": cancelled}

    def _ask_user(question, options, allow_free_text=True):
        """Park the turn on a question and block until the user answers, the same
        way _ask_permission parks on an approval. The answer is returned so the
        CALLER can hand it back as the tool result -- the turn never ends, it
        resumes with the answer in context. None when there is no req_id (a
        direct caller has no channel to ask on), a string when cancelled or the
        wait timed out, otherwise {answer, option_id}."""
        if not req_id:
            return None
        ev = threading.Event()
        with _lock:
            _ask_waits[req_id] = {"event": ev, "answer": None,
                                  "option_id": None, "asked": _time.time()}
        q = {"question": str(question)[:2000], "options": options,
             "allow_free_text": bool(allow_free_text)}
        _set_status("asking", "Waiting for you: " + str(question)[:60], 50)
        with _lock:
            _chat_status.setdefault(req_id, {})["awaiting_question"] = q
        agent_activity(req_id, "ask", "question", str(question)[:70])
        log(f"Job {req_id} parked on a question: {str(question)[:90]}", "info")
        deadline = _time.time() + PERM_WAIT_SECONDS
        timed_out = False
        while not ev.wait(0.25):
            if should_cancel and should_cancel():
                break
            if _time.time() > deadline:
                timed_out = True
                log(f"ask_user for job {req_id} went unanswered for "
                    f"{PERM_WAIT_SECONDS}s", "warn")
                break
        with _lock:
            rec = _ask_waits.pop(req_id, {})
            st = _chat_status.get(req_id)
            if st is not None:
                st.pop("awaiting_question", None)
        if should_cancel and should_cancel():
            return "[ask_user] Cancelled before the user answered."
        if timed_out:
            return ("[ask_user] No answer within the time limit. Proceed with the "
                    "safest reasonable assumption and say which one you made.")
        return {"answer": rec.get("answer") or "", "option_id": rec.get("option_id") or ""}

    if pending_permissions is None:
        pending_permissions = set()

    # Agent Mode adds real PC control. ADMIN MODE additionally waives every prompt.
    _agset     = agent_settings()
    admin_mode = _agset["admin_mode"]
    agent_mode = bool(agent_mode) and _agset["pc_control"]
    routing    = bool(_config.get("routing_enabled", True)) and len(model_roster()) > 0

    import re as _re

    # Pre-scan last user message for Windows/Unix paths and auto-list them
    # This ensures the AI has real data before generating its response
    last_user = next((m["content"] for m in reversed(messages) if m["role"]=="user"), "")
                # Detect file paths: Windows (C:/... or C:\...) or Unix (/path/to/...)
    path_pattern = _re.compile(r'[A-Za-z]:[/\\][^\s,;"\']+|(?:/[a-zA-Z0-9_.+-]+){2,}')
    found_paths = path_pattern.findall(last_user)
    # Not during an auto-split step. Those prompts list EVERY path in the
    # manifest, most of which do not exist yet, so this pre-read logged a
    # "path not found" per file per step and re-read finished files back into a
    # context whose entire purpose is to stay small.
    if not allow_split:
        found_paths = []
    auto_tool_results = []
    for fpath in found_paths[:3]:  # max 3 auto-lookups
        fpath = fpath.rstrip("?.,;")
        p = Path(fpath)
        if p.exists():
            if p.is_dir():
                result = fs_list_dir(fpath)
                auto_tool_results.append(f"[AUTO LIST_DIR {fpath}]:{result}")

                log(f"Auto-listed dir: {fpath}", "info")
            elif p.is_file():
                result = fs_read_file(fpath)
                auto_tool_results.append(f"[AUTO READ_FILE {fpath}]:{result[:3000]}")

                log(f"Auto-read file: {fpath}", "info")
        else:
            log(f"Path not found on server side: {fpath}", "warn")

    # Build messages with tool system prompt + any auto-collected context
    extra_context = ""
    if auto_tool_results:
        extra_context = "\n\nFilesystem data from user PC:\n\n" + "\n\n".join(auto_tool_results)


    # Inject persistent memory into system prompt.
    # The latest user turn drives which vault notes get pulled in verbatim,
    # so pass it through rather than building context blind.
    mem = load_memory()
    _last_user = ""
    try:
        for _m in reversed(messages or []):
            if isinstance(_m, dict) and _m.get("role") == "user":
                _c = _m.get("content")
                _last_user = _c if isinstance(_c, str) else str(_c or "")
                break
    except Exception:
        _last_user = ""
    # The UI sends workspace="" and everything gated on it was silently inert:
    # write confinement AND auto-split. Read the destination out of what the
    # user actually said instead of leaving both switched off.
    if not workspace:
        workspace = infer_workspace(_last_user) or recall_ctx(session_id, "workspace")
        if workspace:
            log(f"Workspace: {workspace}", "info")
            agent_activity(req_id, "workspace", "working directory", workspace, ok=True)
            try:
                Path(workspace).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                log(f"Could not create {workspace}: {e}", "warn")
    remember_ctx(session_id, workspace=workspace)

    # Is this a UI job? Decided from the ORIGINAL task, not from "ok".
    _ui_now = is_ui_task(_last_user)
    if _ui_now:
        remember_ctx(session_id, ui=True, task=_last_user[:4000])
    _ui_job = _ui_now or bool(recall_ctx(session_id, "ui"))

    # ── Hard-pinned code model ────────────────────────────────────────────────
    # For a CODE job (UI jobs resolve their own pin in the picker below), a
    # pinned coding model FORCES itself over the request's model, so every
    # interactive code task uses it regardless of the desktop model dropdown.
    # Two deliberate exemptions, or this would silently corrupt measurement:
    # a benchmark run (bench.py's run_nd names its req_id "bench_...") keeps its
    # explicit --model so model comparisons still measure what they asked for,
    # and the pin applies only when it actually resolves to an installed tag.
    # Unpin by clearing task_model_pinned["code"] in the config.
    _code_pin = (_config.get("task_model_pinned") or {}).get("code")
    if _code_pin and not _ui_job and not str(req_id or "").startswith("bench"):
        _resolved_code_pin = resolve_installed(_code_pin)
        if _resolved_code_pin and _resolved_code_pin != model:
            log(f"Code model pinned -> {_resolved_code_pin} (request asked "
                f"{model or '(none)'})", "ok")
            if req_id:
                agent_activity(req_id, "model", f"using {_resolved_code_pin}",
                               "pinned for code", ok=True)
            model = _resolved_code_pin

    # A bare nudge inherits the original task: without this the model is left
    # building from memory with no brief and no rules, which is how a request
    # for an emulator front end came back as a marketing landing page.
    _orig_task = recall_ctx(session_id, "task") if is_continuation(_last_user) else ""

    # ── Route design work to a model that can SEE the source ─────────────────
    # The single biggest limiter on UI quality was never taste, it was context.
    # At 8192 the coder model reads 5,000-char pages of a 187 KB app and never
    # holds it whole -- it reconstructs a building from photographs of bricks.
    # Measured on this box: qwen3coder-q3xl @16384 prefills at 72 tok/s, while
    # qwen3:14b @32768 prefills at 2468 tok/s at 11.9 GB and 0% on CPU. For work
    # that must READ a lot before writing, the bigger window wins outright.
    # If the previous turn asked which model to use, this turn is the answer.
    _pending_kind = recall_ctx(session_id, "await_model")
    if _pending_kind:
        _cands = task_candidates(_pending_kind)
        _picked, _always = parse_model_choice(_last_user, _cands)
        if _picked:
            remember_ctx(session_id, **{"model_" + _pending_kind: _picked})
            # Explicit clear: remember_ctx ignores empty values, so this is the
            # only thing that actually marks the question answered -- on disk
            # too, or the next bare number answers a question already dealt with.
            forget_ctx(session_id, "await_model")
            if _always:
                _cfg_pin = dict(_config.get("task_model_pinned") or {})
                _cfg_pin[_pending_kind] = _picked
                _config["task_model_pinned"] = _cfg_pin
                save_config()
            model = _picked
            _orig_task = _orig_task or recall_ctx(session_id, "task")
            # Put the JOB back in front of the model. The user's reply is "1" --
            # the answer to the picker, not the work. Without this the model is
            # handed a conversation whose last user message is a single digit,
            # improvises a one-line reply from stale context ("I will insert the
            # CSS block immediately after the existing style block."), calls no
            # tools, and the turn ends. The user answers, gets nothing, asks
            # again, is asked to pick again -- a loop with no progress in it.
            #
            # The task was already stashed by the branch that ASKED the
            # question; this is where it has to come back.
            if _orig_task and _orig_task.strip() != (_last_user or "").strip():
                messages = list(messages) + [{"role": "user", "content": _orig_task}]
                _last_user = _orig_task
                # Everything downstream keys off the latest user turn -- the
                # reskin guard, workspace inference, is_continuation. They must
                # all see the task, not the digit.
                if not workspace:
                    workspace = (infer_workspace(_orig_task)
                                 or recall_ctx(session_id, "workspace") or workspace)
                log("Restored the original task after the model choice", "info")
            log(f"Model chosen for {_pending_kind}: {model}"
                + (" (pinned)" if _always else ""), "ok")
            agent_activity(req_id, "model", f"using {model}",
                           "your choice" + (" — pinned" if _always else ""), ok=True)
        else:
            return {"final_response":
                        "I did not recognise that as a model choice.\n\n"
                        + model_choice_prompt(_pending_kind, _cands,
                                              recall_ctx(session_id, "task")),
                    "tool_calls": [], "tool_results": [], "needs_permission": None}

    # A bare answer with nothing to answer. Belt to the persistence braces: if
    # the stash is lost for ANY reason -- a wiped file, a changed session id, a
    # question from a previous conversation -- a lone "1" must not be handed to
    # a model as if it were the job. That is what produced a 0.6-second reply
    # of "I will insert the CSS block immediately after the existing style
    # block." and no work at all. Say what happened instead.
    # NB: module-level compiled pattern, not `re.fullmatch`. This function does
    # `import re` further down, which shadows the module for the WHOLE body --
    # so any `re.` reference up here is an UnboundLocalError, not a fallback.
    elif (_BARE_CHOICE_RE.fullmatch(_last_user or "")
            and not pending_permissions and not recall_ctx(session_id, "task")):
        log("Bare number with no pending question — asking for the task", "warn")
        return {"final_response":
                    f"I got \"{(_last_user or '').strip()}\" but I am not waiting on an "
                    "answer to anything, so there is nothing for that to pick.\n\n"
                    "That usually means the question was asked before ND restarted and "
                    "the task went with it. Send the task again and I will run it.",
                "tool_calls": [], "tool_results": [], "needs_permission": None}

    # Otherwise: ask, unless already pinned or already chosen this session.
    elif _ui_job and _config.get("ask_model_per_task", True) and not pending_permissions:
        _pinned = (_config.get("task_model_pinned") or {}).get("ui")
        # "Ask every time" means every time the USER hands over a new UI task --
        # not on the internal steps of one. A continuation ("continue") and an
        # auto-split sub-call (allow_split=False) are the same task still
        # running, so they reuse the answer instead of re-interrupting.
        _same_task = is_continuation(_last_user) or not allow_split
        _chosen = recall_ctx(session_id, "model_ui") if _same_task else ""
        _cands = task_candidates("ui")
        if _pinned and resolve_installed(_pinned):
            model = resolve_installed(_pinned)
        elif _chosen:
            model = _chosen
        elif not allow_split:
            # Inside an auto-split step there is NOBODY to answer. try_build_plan
            # discards this return and moves to the next file, so the question
            # reaches no one and the file is never written.
            #
            # _same_task above was meant to cover this, but it only helps once a
            # choice has been stored. When the top-level call never triggered the
            # picker -- and `ui` is remembered on the SESSION, so a single UI-ish
            # sub-prompt makes every later step a "UI job" -- there is nothing
            # stored and it asks anyway. Measured 2026-09-01: a 3-file split wrote
            # 0 of 3 files in 1.8s because every step returned the picker prompt
            # instead of doing the work.
            #
            # Keep the model we were handed: it is already the one the top-level
            # call resolved.
            pass
        elif len(_cands) > 1:
            # Stash the workspace with the task. The answer ("1") carries no
            # path, so infer_workspace has nothing to read on the way back in.
            remember_ctx(session_id, await_model="ui",
                         task=(_orig_task or _last_user)[:4000],
                         **({"workspace": workspace} if workspace else {}))
            log("Asking which model to use for this UI task", "info")
            return {"final_response": model_choice_prompt("ui", _cands,
                                                          _orig_task or _last_user),
                    "tool_calls": [], "tool_results": [], "needs_permission": None}

    _prof = model_profile(model)
    set_active_profile(_prof)   # fs_read_file reads it off this thread

    # ── Is this job even possible? ───────────────────────────────────────────
    # Asked to reskin a 185 KB app, four of five models threw the entire
    # application away and wrote a ~6 KB brochure; the fifth copied the file
    # unchanged. Not one of them had read it, because none of them COULD: 185 KB
    # is ~56,000 tokens, a whole-file rewrite must hold the source and the
    # rewrite at once, and the installed windows are 8,192 to 32,768.
    #
    # ND let them try anyway, so each model improvised a page from the words in
    # the filename and the design-review loop critiqued the hover states on
    # something that did nothing. Refuse instead, in numbers, and say what
    # would work. Only ever blocks a RESKIN of a file that is really on disk.
    # The refusal ends with "say reskin as an edit". Honour that literally --
    # a guard with no way past it is just a wall.
    if _RESKIN_EDIT_RE.search(_last_user or ""):
        remember_ctx(session_id, reskin_as_edit="1")
        log("Reskin switched to edit mode by the user", "info")

    _rk = reskin_mod()
    _job_ctx.reskin_src = ""
    _rk_task = _orig_task or _last_user
    if _rk and not pending_permissions and _rk.looks_like_reskin(_rk_task):
        _src = (_rk.find_source(_rk_task, workspace)
                or recall_ctx(session_id, "reskin_src"))
        if _src:
            # Park it whether or not the guard fires. In edit mode the guard is
            # deliberately bypassed, and that is precisely when design_review
            # most needs to know what the output is supposed to still contain.
            _job_ctx.reskin_src = _src
            remember_ctx(session_id, reskin_src=_src)
            _fit = _rk.fits_window(_src, _prof["num_ctx"])
            if (not _fit["fits"] and _config.get("reskin_guard", True)
                    and not recall_ctx(session_id, "reskin_as_edit")):
                log(f"Refusing whole-file reskin: {Path(_src).name} needs "
                    f"~{_fit['needed']:,} tokens, {model} has "
                    f"{_fit['num_ctx']:,}", "warn")
                agent_activity(req_id, "guard", "job too big for this model",
                               f"{_fit['bytes']//1024} KB source vs "
                               f"{_fit['num_ctx']:,} token window", ok=False)
                remember_ctx(session_id, task=_rk_task[:4000])
                return {"final_response": _rk.too_big_message(
                            _fit, model, task_candidates("ui"), Path(_src).name),
                        "tool_calls": [], "tool_results": [],
                        "needs_permission": None}

    # ── Auto-split ───────────────────────────────────────────────────────────
    # A multi-file build in ONE conversation grows until it fills the window and
    # Ollama starts dropping the oldest messages -- silently, taking the user's
    # instruction with it. Detect that shape up front and build file by file in
    # fresh contexts instead. Deliberately narrow: it only fires on a build-
    # looking request with a workspace, and only if the model's own plan lists
    # enough files to be worth splitting. Anything else falls straight through.
    _split_task = _orig_task or _last_user
    # Protection first: a build's sub-steps see only their step prompt, so the
    # spec and keep-unchanged lists must be in the session BEFORE any of them runs.
    try:
        if session_id and workspace and allow_split:
            _ps, _pk = spec_files_in(_split_task, workspace), keep_files_in(_split_task, workspace)
            if _ps or _pk:
                remember_ctx(session_id, spec_files=json.dumps(_ps), keep_files=json.dumps(_pk))
    except Exception as _pe2:
        log(f"spec protection skipped: {_pe2}", "warn")
    # A "continue" never starts a NEW build: re-planning the original task planned
    # fresh files into a finished project and broke it (Elena Live pair 10).
    if (allow_split and workspace and _config.get("agent_auto_split", True)
            and not pending_permissions and _split_task
            and not is_followup(_last_user)
            and (build_plan_mod() and build_plan_mod().looks_like_build(_split_task, workspace))):
        try:
            _pre_build = _suite_snapshot(workspace) if SUITE_GATE else {}
            _split = try_build_plan(model, _split_task, workspace, allow_all, req_id,
                                    should_cancel, agent_mode, session_id,
                                    _set_status, agent_activity)
            if _split:
                # The same undo the ordinary loop has.
                if _pre_build and _config.get("agent_turn_revert", True):
                    _rb = _suite_regressions(_pre_build, workspace)
                    if _rb:
                        _put = []
                        for _f, _body in _originals_peek(req_id).items():
                            try:
                                Path(_f).write_text(_body, encoding="utf-8")
                                _put.append(Path(_f).name)
                            except OSError:
                                pass
                        log(f"Build undone: {_rb[:100]} - restored {len(_put)} file(s)", "warn")
                        _gate_record(req_id, "turn_revert", restored=len(_put), path="build")
                        _split["final_response"] = (str(_split.get("final_response") or "").rstrip()
                            + NL + NL + "UNDONE. This build broke tests that were passing before it:"
                            + NL + _rb[:600] + NL + NL
                            + (f"Put back: {', '.join(_put)}." if _put else "No edited file to put back."))
                return _split
        except Exception as e:
            log(f"Auto-split failed, continuing normally: {e}", "warn")

    # Placed edits. Auto-split above handles BUILDING several new files; this
    # handles CHANGING an existing codebase, which is the other half and the one
    # the models cannot decompose on their own. Only when there is an existing
    # codebase to change and the request is not a build.
    if (allow_split and workspace and _config.get("agent_placed_edits", True)
            and not pending_permissions and not is_continuation(_last_user)
            and not (build_plan_mod() and build_plan_mod().looks_like_build(_last_user, workspace))
            and placement_mod() and placement_mod().looks_like_change(_last_user)):
        try:
            _placed = try_placed_edits(model, _last_user, workspace, allow_all,
                                       req_id, should_cancel, agent_mode,
                                       session_id, _set_status, agent_activity)
            if _placed:
                return _placed
        except Exception as e:
            log(f"Placed edits failed, continuing normally: {e}", "warn")

    # Seed the plan, since the model will not start one itself. Placed here on
    # purpose: if auto-split took the task it has already returned, and that path
    # has its own manifest and runs one file per fresh context, so a second plan
    # would be noise. Skipped on a continuation and when one already exists --
    # re-planning mid-task would throw away the progress marks.
    # DEFAULT OFF until there is evidence it helps. It works -- both UI models
    # produce clean, sensible plans in 1.1s and 8.6s -- but the one A/B run so
    # far went the wrong way: seeded, the same task took 20 rounds and the model
    # never touched the plan; unseeded, it took 9 and wrote its own. n=1 either
    # way, so this ships switchable rather than assumed. Set agent_plan_seed
    # true in the config to try it.
    if (allow_split and session_id and _config.get("agent_plan_seed", False)
            and not pending_permissions
            and not is_continuation(_last_user)
            and not recall_ctx(session_id, "plan")
            and looks_multi_step(_last_user)):
        _set_status("thinking", "Working out the steps…", 15)
        agent_activity(req_id, "plan", "planning the steps", "before starting work")
        seed_plan(model, _last_user, session_id, req_id)

    mem_str = memory_to_prompt(mem, user_text=_last_user,
                               budget=_prof["memory_budget_chars"])
    if _prof.get("_profile"):
        log(f"Context profile '{_prof['_profile']}': num_ctx={_prof['num_ctx']}, "
            f"memory={_prof['memory_budget_chars']}c, tool_result={_prof['tool_result_chars']}c", "info")
    system_content = SYSTEM_PROMPT_TOOLS
    # Tiered rules: the UI rules (design_review + design brief) are dead weight on
    # a non-UI turn, and the fixed prompt cost is what tips a small-window model
    # into overflow. The code/test rule always applies.
    if _ui_job:
        system_content += SYSTEM_PROMPT_UI_RULES
    system_content += SYSTEM_PROMPT_CODE_RULES
    # Where it is and what is around it. workspace is settled by this point --
    # infer_workspace and the split planner have both already run.
    system_content += environment_block(workspace, model)
    # House style on the ordinary path too. A one-file tweak ("restyle this
    # page") never reaches the build planner, and it is exactly the case where
    # the rules matter most.
    system_content += ui_style_block(_last_user, force=_ui_job)
    if _orig_task:
        # Put the original task back in front of the model. "continue" carries
        # no requirements of its own, and the first turn's instructions have
        # long since been compacted out of the transcript.
        system_content += ("\n\nTHE TASK YOU ARE CONTINUING (the user's original "
                           "request — all of it still applies):\n" + _orig_task + "\n")
    if routing:
        system_content += roster_prompt()
    if not agent_mode:
        # The preamble above claims shell, screen capture and mouse control
        # unconditionally, and on this path none of those tools exist. Correct
        # it here rather than leaving the model to guess which half is true.
        system_content += (
            "\n\nWHAT YOU CAN ACTUALLY DO ON THIS TURN. The capability list above is what "
            "NeuralDock can do in general. Right now you have been given ONLY these tools: "
            "read_file, write_file, edit_file, list_dir, search_files, run_script, web_search, "
            "web_fetch, generate_image, design_review, update_plan, ask_user, resolve_app.\n"
            "If the request is ambiguous or there is a real choice to make, call ask_user and WAIT "
            "for the answer before doing the work — clarify first, do not guess and get it wrong.\n"
            "You DO have the web. web_search and web_fetch work and you are expected to use them "
            "before saying you do not know something.\n"
            "You do NOT have, on this turn only: run_shell (starting programs), gui_action (mouse "
            "and keyboard), screen_capture (seeing the screen), install_app, or the paired phone. "
            "They are switched off for this conversation, not missing from the product.\n"
            "NEVER say you 'cannot access external websites or applications', that you 'have no "
            "access to the internet', or that you are 'just a language model'. All three are false "
            "and the user knows it. If a request needs one of the switched-off tools — opening a "
            "browser, clicking something, reading what is on screen — then:\n"
            "  1. begin your reply with the exact marker [NEEDS TOOLS] on its own line, and\n"
            "  2. say in one sentence what you would do with them.\n"
            "The interface turns that marker into a button that enables the tools, so it is how the "
            "user says yes. Anything you CAN do with the tools you have, just do — do not ask for "
            "tools you do not need.\n")

    if agent_mode:
        system_content += (
            "\n\nYOU ARE ELENA. That is your name — use it when you introduce yourself. You are the "
            "user's personal AI assistant running on their own Windows PC, with real control of it. "
            "Be warm, direct and brief. Speak like a capable person, not a manual. Your replies are "
            "often read aloud, so keep them conversational and skip markdown decoration when short.\n\n"
            "AGENT MODE IS ACTIVE. You have run_shell (PowerShell), install_app, screen_capture and "
            "gui_action (real mouse, keyboard and media keys). Rules:\n"
            "- Prefer run_shell over gui_action. Clicking is a last resort for things with no command line.\n"
            "- ALWAYS screen_capture before you click, and re-capture after, to confirm what happened.\n"
            "- Say what you are about to do in one short line, then do it. Do not ask for permission "
            "in text — the app shows the user a real approval prompt for anything system-level.\n"
            "- CLARIFY BEFORE ACTING. When the request is ambiguous, or there is more than one real "
            "way to do it (and especially when one way is slower, visible on the user's screen, or "
            "touches their accounts), call ask_user with the options and WAIT. One good question up "
            "front beats doing the wrong thing confidently. ask_user is NOT for tool approval — the "
            "app already handles that — it is for intent and direction.\n"
            "- NEVER guess where a program lives. Before you launch anything, call resolve_app to get "
            "its real path and whether it is already running, then launch with the path it gives you. "
            "For reaching the web — especially anything behind a login like Gmail or Calendar — use "
            "the managed browser (browser_open / browser_read), not run_shell + chrome.\n"
            "- A tool result that starts with FAILED or BLOCKED means it did NOT work. Never report "
            "such a thing as done. [BLOCKED] is the hard blocklist — tell the user ADMIN MODE in Setup "
            "would lift it and move on; do not try to work around it.\n")
    if agent_mode and wants_pc_control(_last_user, workspace):
        system_content += (
            "\nHOW TO ACTUALLY DRIVE WINDOWS APPS — read this before launching anything:\n"
            "- `exit 0` from a launcher means the command was ACCEPTED, not that it worked. Never treat "
            "it as success and never re-run the same launch command. Verify instead: "
            "`Get-Process <name>` for whether it is running, or screen_capture and look.\n"
            "- Check first, launch second: if `Get-Process spotify` already returns something, the app "
            "is open — move on to the next step rather than launching it again.\n"
            "- Many apps take a URI, which is far more reliable than clicking:\n"
            "    Spotify : `Start-Process \"spotify:search:<artist or song>\"`, or "
            "`spotify:track:<id>` / `spotify:album:<id>` / `spotify:playlist:<id>` if you know the id.\n"
            "    Browser : `Start-Process \"https://...\"`   Mail: `mailto:`   Settings: `ms-settings:`\n"
            "- PERCENT-ENCODE SPACES IN URIs. `spotify:search:Deathmask Divine` reaches Spotify as only "
            "\"Deathmask\" because Windows splits the URI on whitespace. Write "
            "`spotify:search:Deathmask%20Divine%20Black%20Dahlia%20Murder`. (The app auto-corrects this "
            "for you, but write it correctly anyway.)\n"
            "- search_files is for finding TEXT INSIDE CODE FILES in a project folder. It is NOT for "
            "finding applications, songs, settings or anything on the wider system, and pointing it at a "
            "big folder wastes the whole task. To locate a program use `Get-Command`, `Get-ChildItem` on "
            "a specific path, or the registry — via run_shell.\n"
            "- MEDIA PLAYBACK: `gui_action` with action='media' sends real media keys — "
            "keys='playpause'|'next'|'prev'|'stop'|'volup'|'voldown'|'mute'. These work no matter which "
            "window has focus and are the correct way to start/stop/skip playback.\n"
            "- BEFORE any screen_capture of a specific app, bring it to the front: gui_action "
            "action='focus', text='<app name>'. Otherwise it is hidden behind the browser and you will "
            "report that you cannot see it.\n"
            "- Playing a SPECIFIC song is not the same as pressing play. The playpause media key just "
            "resumes whatever was already loaded. To play a particular track: "
            "`Start-Process \"spotify:search:<song>%20<artist>\"` → gui_action focus 'Spotify' → "
            "screen_capture → look at the results and CLICK the play button on the right row. Only use "
            "the playpause key for genuine pause/resume, or if the user just said 'play something'.\n"
            "- After you act, confirm what actually happened rather than assuming. For Spotify the "
            "window title is the currently playing track: "
            "`(Get-Process Spotify | Where {$_.MainWindowTitle}).MainWindowTitle`. If that title is not "
            "the song the user asked for, say so honestly instead of claiming success.\n"
            "- Store/UWP apps (Spotify, Calculator, Photos) have no meaningful CLI. GUI automation is "
            "the intended route for them, not more shell commands.\n"
            "\nWHEN YOU ARE STUCK: if the same approach has failed twice, STOP. Do not try it a third "
            "time. Say plainly what you tried, what actually happened, and what you need from the user. "
            "Asking one good question beats ten failed attempts.\n"
            + ("- ADMIN MODE is currently ON: the blocklist and approval prompts are lifted. Be "
               "correspondingly careful, state exactly what you are about to run, and never run "
               "something destructive that the user did not clearly ask for.\n" if admin_mode else "")
        )
    _devs = device_snapshot()
    if _devs:
        _summary = "; ".join(f"{d['name']} ({d['platform']}, "
                             f"{'online' if d['online'] else 'offline'})" for d in _devs)
        system_content += (
            "\n\nYOU HAVE MORE THAN ONE BODY. Besides this PC, these devices are paired: "
            + _summary + ".\n"
            "- Call `list_devices` to see exactly which actions each one supports, then `device_action` "
            "to use one. Never invent an action name — use only what the device reports.\n"
            "- Pick the right device for the job. A text message goes from the phone; a file edit "
            "happens on the PC. If the user says 'my phone' and only one phone is paired, that is the one.\n"
            "- If a device is offline, say so plainly and stop. Do not retry it in a loop.\n"
            "- Phone actions can interrupt someone's day, so be conservative: confirm anything that "
            "sends, posts, calls or costs money.")
    # Inject memory if there IS any. This used to read
    #     if mem_str and "facts learned" in mem_str:
    # which sniffed for a phrase from the old JSON formatter's header. When the
    # Obsidian backend replaced that formatter the phrase disappeared, so the
    # guard silently discarded the entire vault context on every single request
    # and the model looked like it had no memory at all. Never gate content on
    # a magic substring produced somewhere else.
    if mem_str and mem_str.strip():
        system_content += "\n\n" + mem_str
    # Short-term working memory: the files and actions from earlier turns of THIS
    # conversation. Injected after long-term memory and before the transcript so
    # the model sees "here is what you already did" before it plans anything.
    _work = session_work_prompt(session_id)
    if _work:
        system_content += "\n\n" + _work
    # What it MEANT to do, right after what it actually did. The pair is the
    # point: either on its own leaves the model guessing at the other half.
    system_content += plan_block(session_id)
    if extra_context:
        system_content += "\n\n" + extra_context
    try:
        _proj = project_instructions_for(workspace)
    except Exception:
        _proj = None
    if _proj:
        system_content += (f"\n\nPROJECT \"{_proj[0]}\" - the user's standing instructions for "
                           "this project. Follow them on every request here:\n" + _proj[1])
    try:
        _job_ctx.gui_input = (_run_gate_inputs(_last_user, workspace) or [""])[0]
    except Exception:
        _job_ctx.gui_input = ""
    full_messages = [{"role":"system","content":system_content}] + list(messages)
    # An IMAGE request goes straight to generate_image. Measured 2026-09-29: "use that
    # to create the image. comfyui is connected" sent qwen3-coder:30b listing folders,
    # searching G:\ and reading a README for 8 rounds without once calling the tool.
    # At the tail, next to the request - the system prompt is the part lost first.
    try:
        if full_messages and full_messages[-1].get("role") == "user" \
                and wants_image(str(full_messages[-1].get("content") or "")):
            _im = dict(full_messages[-1])
            _im["content"] = str(_im.get("content") or "") + IMAGE_DIRECTIVE
            full_messages[-1] = _im
            log("Image request - told the model to call generate_image first", "info")
    except Exception as _ie:
        log(f"image directive skipped: {_ie}", "warn")
    # A "continue" turn starts from the failing tests, not from a re-read. ND
    # runs them itself: the model choosing to run them is exactly what did not
    # happen (Elena Live pair 3).
    try:
        if workspace and allow_split and full_messages and full_messages[-1].get("role") == "user" \
                and is_followup(str(full_messages[-1].get("content") or "")):
            _lines, _bad = [], []
            for _sp in _project_suites(workspace)[:3]:
                _c, _tail, _ok, _fl = _suite_detail(str(_sp), workspace, timeout=90)
                if _c is None:
                    _bad.append(f"{_sp.name} does not run (crash before its summary)")
                    _lines.append(f"{_sp.name}: does not run.\n{_tail[:700]}")
                elif _c[1] > 0:
                    _bad.append(f"{_sp.name}: {_c[1]} test(s) failing.")
                    _lines.append(f"{_sp.name}: {_c[0]} passed, {_c[1]} FAILED.\n{_tail[:900]}")
            if session_id:
                remember_ctx(session_id, tests_failing=(" ".join(_bad) or " "))
            if _lines:
                _tm = dict(full_messages[-1])
                _tm["content"] = str(_tm.get("content") or "") + (
                    "\n\n[NeuralDock ran this project's tests before this turn. Fix these "
                    "first - edit the code they test, then run the test file again:]\n\n"
                    + "\n\n".join(_lines)[:2400])
                full_messages[-1] = _tm
                log("Continue turn: ran the project's tests - " + "; ".join(_bad)[:120], "info")
    except Exception as _ce:
        log(f"continue-turn test run skipped: {_ce}", "warn")
    # Project notes go next to the request, verbatim. Through the vault route a
    # coding task got only the notes' TITLES (2026-10-18).
    try:
        if workspace and full_messages and full_messages[-1].get("role") == "user":
            _pn = project_notes_block(workspace)
            if _pn:
                _pm = dict(full_messages[-1])
                _pm["content"] = str(_pm.get("content") or "") + _pn
                full_messages[-1] = _pm
                log(f"Project notes: {len(_pn)} chars at the tail of the request", "info")
    except Exception as _pe:
        log(f"project notes skipped: {_pe}", "warn")
    # At the TAIL, next to the error the user pasted -- not in the system prompt,
    # which is the first thing lost when the window fills.
    try:
        _tbb = traceback_source_block(_last_user) if allow_split else ""
    except Exception:
        _tbb = ""
    if _tbb and full_messages and full_messages[-1].get("role") == "user":
        _lm = dict(full_messages[-1])
        _lm["content"] = str(_lm.get("content") or "") + _tbb
        full_messages[-1] = _lm
        log("Traceback in the request - read the lines it names and put them next to it", "info")
        agent_activity(req_id, "read", "traceback source", "lines named by the error", ok=True)

    _slow = model_speed_note(model)
    if _slow:
        log(f"Slow model: {_slow}", "warn")
        agent_activity(req_id, "think", "large model", _slow[:90])
        _set_status("thinking", _slow, 15)
    else:
        _set_status("thinking", "Sending to model...", 20)

    # ── Unified agent loop: native structured tool calls first, TOOL: text fallback ──
    import re
    write_tools = {"write_file", "edit_file", "run_script"}

    active_tools = (TOOL_SCHEMAS
                    + (AGENT_TOOL_SCHEMAS if agent_mode else [])
                    + (ROUTER_TOOL_SCHEMAS if routing else [])
                    + (DEVICE_TOOL_SCHEMAS if device_snapshot() else []))
    if PORTABLE:
        active_tools = [t for t in active_tools
                        if t.get("function", {}).get("name") not in PORTABLE_DROP_TOOLS]
    pending_images = []          # screen_capture output, attached to the next message

    def _tier(name):
        return TOOL_TIERS.get(name, "yellow")

    def _perm_key(name, args):
        """Yellow = one approval per tool for the whole session.
           Red = one approval per exact call, because each one touches the system."""
        if _tier(name) != "red":
            return name
        return name + ":" + hashlib.sha1(
            json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:10]

    def strip_tool_lines(text):
        import re as _re2
        lines = text.split("\n")
        clean = [l for l in lines if not l.strip().startswith("TOOL:")]
        result = "\n".join(clean).strip()
        return _re2.sub(r"\n{3,}", "\n\n", result)

    def _summ(args):
        try: return json.dumps(args)[:120]
        except Exception: return str(args)[:120]

    # The spec this request is built from. Remembered per session, so a "continue"
    # turn and every sub-step keep the protection the first request set up.
    _specs = spec_files_in(_last_user, workspace)
    _keeps = keep_files_in(_last_user, workspace)
    if (_specs or _keeps) and session_id:
        remember_ctx(session_id, spec_files=json.dumps(_specs), keep_files=json.dumps(_keeps))
    elif session_id:
        try:
            _specs = json.loads(recall_ctx(session_id, "spec_files") or "[]")
            _keeps = json.loads(recall_ctx(session_id, "keep_files") or "[]")
        except Exception:
            _specs, _keeps = [], []

    # Failing tests come first (see TESTS_FIRST_NOTE). Carried in the session so
    # a "continue" turn starts from what was failing.
    _tests_failing = {"v": (recall_ctx(session_id, "tests_failing") or "").strip() if session_id else ""}
    _readonly_run = {"n": 0}

    def _off_target(a):
        """Is this write aimed somewhere the current step is not allowed to touch?

        Returns a refusal string, or "" when the write is fine. The spec check
        applies everywhere; the one-file check only inside a placed-edit step,
        where `only_file` is the one file the step exists to change.
        """
        if _keeps:
            _kraw = str((a or {}).get("path") or "").strip().strip('"').strip("'")
            try:
                _kq = Path(_kraw)
                if not _kq.is_absolute() and workspace:
                    _kq = Path(workspace) / _kq
                if _kraw and str(_kq.resolve()) in _keeps:
                    log(f"Refused a write to {_kq.name} - the request says to keep it unchanged", "warn")
                    return ("[KEEP UNCHANGED] " + _kq.name + " must not be changed - the "
                            "request or its spec says so. Nothing was written. Use it as it "
                            "is; read it if you need its API.")
            except OSError:
                pass
        if _specs:
            _raw = str((a or {}).get("path") or "").strip().strip('"').strip("'")
            try:
                _q = Path(_raw)
                if not _q.is_absolute() and workspace:
                    _q = Path(workspace) / _q
                if _raw and str(_q.resolve()) in _specs:
                    log(f"Refused a write to the spec {_q.name}", "warn")
                    return ("[SPEC IS READ-ONLY] " + _q.name + " is the specification "
                            "this request is built from. Nothing was written. Build "
                            "what it says - do not change it to fit your plan. If a "
                            "rule in it conflicts with a house style or another rule, "
                            "the spec wins.")
            except OSError:
                pass
        if not only_file:
            return ""
        raw = str((a or {}).get("path") or "").strip().strip('"').strip("'")
        if not raw:
            return ""
        try:
            here = Path(raw)
            if not here.is_absolute() and workspace:
                here = Path(workspace) / here
            if here.resolve() == Path(only_file).resolve():
                return ""
        except OSError:
            return ""
        if _scope_by_user:
            return ("[WRONG FILE] The user's request changes exactly one file:\n"
                    f"  {only_file}\n"
                    f"and you tried to write {raw}. Nothing was written.\n\n"
                    "The user said to change only that file, so no other file may be "
                    "created or edited in this request - not a test, not a helper, not "
                    "a copy to move over it later (moving files with run_shell is not "
                    "a way around this).\n\n"
                    "If edit_file keeps missing, write the COMPLETE new version "
                    "straight to the file above with write_file - that is allowed. "
                    "Then finish and say what you changed.")
        return ("[WRONG FILE] This step changes exactly one file:\n"
                f"  {only_file}\n"
                f"and you tried to write {raw}. Nothing was written.\n\n"
                "Do not create a new file for this and do not put a fragment "
                "somewhere else. Call edit_file on the file above, with the anchor "
                "you were given as old_text.")

    def _exec_one(name, a):
        # Before anything else: a model that wrote its whole argument list into
        # ONE field as PATH="..." CONTENT="..." Recovered here rather than in
        # repair_write_args, because the same corruption reached edit_file and
        # design_review in the observed run, not just write_file.
        a, _kvnote = unpack_kv_args(a)
        if _kvnote:
            log(f"{name}: {_kvnote}", "warn")
        if PORTABLE and name in PORTABLE_DROP_TOOLS:
            return f"[NOT AVAILABLE] {name} is not part of {PRODUCT}."
        _net = network_refusal(name, a)
        if _net:
            log(f"{name} refused - Internet switch is off", "info")
            return _net
        # Read-only loop breaker, only while tests fail (Elena Live pair 4).
        if name in ("write_file", "edit_file"):
            _readonly_run["n"] = 0
        elif name in READ_ONLY_TOOLS and _tests_failing["v"]:
            if _readonly_run["n"] >= READ_LOOP_MAX:
                log(f"Refused {name} - {_readonly_run['n']} reads in a row while tests fail", "warn")
                return ("[EDIT NOW] " + str(_readonly_run["n"]) + " read-only calls in a row and "
                        "no edit, while " + _tests_failing["v"] + " You have what you need: "
                        "make the fix with edit_file now, then run the tests. Further reads "
                        "are refused until you edit.")
            _readonly_run["n"] += 1
        try:
            if name == "generate_image": return tool_generate_image(a)
            if name == "design_review":
                if _tests_failing["v"]:
                    log("design_review refused - tests are failing", "warn")
                    return ("[FIX TESTS FIRST] " + _tests_failing["v"] + " Design review waits "
                            "until they pass. Edit the code under test, then run the tests again.")
                return tool_design_review(a)
            if name == "web_fetch":    return "[WEB] " + web_fetch(a.get("url",""))
            if name == "web_search":   return "[WEB] " + web_search(a.get("query",""))
            if name == "update_plan":  return tool_update_plan(session_id, a.get("steps"))
            if name == "read_file":    return "[FILE] " + fs_read_file(a.get("path",""), a.get("offset",0), a.get("limit"))
            if name == "list_dir":     return "[FILE] " + fs_list_dir(a.get("path",""))
            if name == "search_files": return "[FILE] " + fs_search_files(a.get("root",""), a.get("pattern",""))
            if name == "find_definition": return "[FILE] " + tool_find_definition(a, workspace)
            if name == "find_references": return "[FILE] " + tool_find_references(a, workspace)
            if name == "resolve_app":  return tool_resolve_app(a.get("name","") or a.get("app","") or a.get("program",""))
            if name == "ask_user":
                # Normalise the options the model gave into {id,label,detail,cost}.
                raw = a.get("options") or []
                if isinstance(raw, str):
                    try: raw = json.loads(raw)
                    except Exception: raw = [s.strip() for s in raw.split("|") if s.strip()]
                norm = []
                for i, o in enumerate(raw if isinstance(raw, list) else []):
                    if isinstance(o, str):
                        norm.append({"id": f"opt{i+1}", "label": o[:200], "detail": "", "cost": ""})
                    elif isinstance(o, dict):
                        norm.append({"id": str(o.get("id") or f"opt{i+1}")[:40],
                                     "label": str(o.get("label") or o.get("text") or o.get("title") or "")[:200],
                                     "detail": str(o.get("detail") or o.get("description") or "")[:500],
                                     "cost": str(o.get("cost") or o.get("tradeoff") or "")[:120]})
                aft = a.get("allow_free_text")
                rec = _ask_user(a.get("question","") or a.get("prompt",""), norm,
                                True if aft is None else bool(aft))
                if rec is None:
                    return ("[ask_user] There is no interface to ask on right now. State the "
                            "single most reasonable assumption and proceed — do not stop.")
                if isinstance(rec, str):
                    return rec
                ans = rec.get("answer") or ""
                oid = rec.get("option_id") or ""
                chosen = next((o for o in norm if o["id"] == oid), None)
                if chosen:
                    return ("[ask_user] The user chose: " + chosen["label"]
                            + (" — they added: " + ans if ans else "")
                            + "\nAct on that choice now.")
                if ans:
                    return "[ask_user] The user answered: " + ans + "\nAct on that now."
                return ("[ask_user] The user dismissed the question without choosing. "
                        "Proceed with the safest option and say which you picked.")

            def _suite_base():
                """Snapshot the project's green suites, once, before the first write.

                Lazy on purpose: taken at the moment of the first edit, so it
                captures the tree as the user handed it over. Taken any later and
                it would record the damage as the baseline.
                """
                if "base" not in _suite_state:
                    _suite_state["base"] = _suite_snapshot(workspace)
                    if _suite_state["base"]:
                        log("Watching " + str(len(_suite_state["base"]))
                            + " green suite(s): "
                            + ", ".join(Path(k).name for k in _suite_state["base"]),
                            "info")
                return _suite_state["base"]

            def _suite_tail(res):
                """Append what this edit broke, if anything, to the tool result.

                Measured on T4: told to fix one filter AND told to re-run the
                suite, the model made a wrong one-line edit and wrote "Re-run the
                test suite" into its reply as a task for somebody else. Telling
                it to verify does not make it verify. This runs the suite and
                puts the answer where it cannot be skipped -- in the tool result
                it is already reading.
                """
                broke = _suite_regressions(_suite_state.get("base") or {}, workspace)
                if broke:
                    log("Suite regression after edit: " + broke[:120], "warn")
                    return res + chr(10) + chr(10) + "STOP - " + broke
                return res

            if name == "edit_file":
                _off = _off_target(a)
                if _off:
                    log(f"Refused an edit to {str((a or {}).get('path'))[:80]}", "warn")
                    return _off
                # write_file resolves a relative path against the workspace
                # (repair_write_args does it); edit_file never did, so a model
                # naming "app/x.py" got "[File not found]" while the identical
                # path worked for a write. Same rule for both.
                _ep = str(a.get("path") or "").strip().strip('"').strip("'")
                if _ep and workspace and not Path(_ep).is_absolute():
                    _cand = Path(workspace) / _ep
                    if _cand.is_file():
                        _ep = str(_cand)
                _suite_base()
                # After resolution, so the key matches what is written.
                _remember_original(req_id, _ep)
                _er = fs_edit_file(_ep, a.get("old_text", ""),
                                   a.get("new_text", ""), workspace)
                _ediag = _py_diagnostics(_ep, workspace)
                return _suite_tail("[FILE] " + _er + (("\n" + _ediag) if _ediag else ""))
            if name == "write_file":
                _off = _off_target(a)
                if _off:
                    log(f"Refused a write to {str((a or {}).get('path'))[:80]}", "warn")
                    return _off
                # ALL validation lives in repair_write_args, because every write
                # reaches this line whether it came from a native tool_call, the
                # JSON parser, the XML parser, the TOOL: text protocol or the
                # code-fence salvage. Guards placed in any one parser were
                # bypassed by the other four.
                path, content, note = repair_write_args(a, workspace, _last_user)
                if path is None:
                    log(f"write_file refused: {note[:90]}", "warn")
                    return note
                if note:
                    log(f"write_file: {note}", "warn")
                    if "REDIRECTED:" in note:
                        # A log line is not good enough: the reply will say the
                        # file was saved, and the user will look where they asked.
                        _write_redirects.setdefault(req_id, []).append(
                            (str((a or {}).get("path") or ""), str(path)))
                        agent_activity(req_id, "warn", "write redirected",
                                       f"-> {Path(path).name}", ok=False)
                _suite_base()
                _remember_original(req_id, path)
                _backup_file(path)
                saved = fs_write_file(path, content)
                vr = _verify_file(path)
                res = f"[FILE] Written to: {saved}"
                if note:
                    res += f"\n(NOTE: {note}.)"
                res += ("\n⚠ VERIFY FAILED — " + vr + "\nFix it with edit_file." ) if vr else " Verified OK."
                _wdiag = _py_diagnostics(path, workspace)
                if _wdiag:
                    res += "\n" + _wdiag
                log(f"write_file: {path}", "ok")
                return _suite_tail(res)
            if name == "run_script":
                _rp = (a.get("path","") or "").strip()
                r = fs_run_script(_rp, workspace)
                _out = f"[RUN] Exit {r['returncode']}\n{r['stdout']}\n{r['stderr']}"
                try:
                    _cnt = test_failures_in(str(r.get("stdout") or "") + "\n" + str(r.get("stderr") or ""))
                    if _cnt and _looks_like_test_file(_rp):
                        _tn = Path(_rp).name
                        if _cnt[1] > 0:
                            _tests_failing["v"] = f"{_tn}: {_cnt[1]} test(s) failing."
                            _out += TESTS_FIRST_NOTE.format(failed=_cnt[1], name=_tn)
                        else:
                            _tests_failing["v"] = ""
                        if session_id:
                            remember_ctx(session_id, tests_failing=_tests_failing["v"] or " ")
                except Exception as _te:
                    log(f"test count skipped: {_te}", "warn")
                return _out
            # ── Agent Mode: real PC control ──
            if name == "run_shell":
                return tool_run_shell(a.get("command","") or a.get("cmd","") or a.get("path",""),
                                      a.get("cwd") or workspace)
            if name == "install_app":
                return tool_install_app(a.get("name","") or a.get("package",""),
                                        a.get("manager","winget"))
            if name == "gui_action":
                def _i(v):
                    try: return int(v)
                    except Exception: return None
                return tool_gui_action(a.get("action",""), _i(a.get("x")), _i(a.get("y")),
                                       a.get("text"), a.get("keys"), _i(a.get("amount")),
                                       _i(a.get("to_x")), _i(a.get("to_y")),
                                       a.get("button","left") or "left")
            if name == "list_devices":
                devs = device_snapshot()
                if not devs:
                    return ("[No devices paired yet. Only this PC is available. The user pairs a phone "
                            "in Setup > Devices.]")
                lines = []
                for d in devs:
                    state = "ONLINE" if d["online"] else f"offline ({d['seconds_since_seen']}s ago)"
                    lines.append(f"{d['name']} [{d['device_id']}] — {d['platform']}, {state}")
                    if d["capabilities"]:
                        for c in d["capabilities"]:
                            lines.append("    " + cap_line(c))
                    else:
                        lines.append("    (reports no capabilities)")
                lines.append("(* marks a required parameter — use these exact names in device_action params)")
                return "\n".join(lines)
            if name == "device_action":
                p = a.get("params")
                if isinstance(p, str):
                    try: p = json.loads(p)
                    except Exception: p = {"value": p}
                return tool_device_action(a.get("device", ""), a.get("action", ""), p or {})
            if name == "delegate":
                return tool_delegate(a.get("specialist",""), a.get("task",""), a.get("context",""))
            if name == "list_specialists":
                r = model_roster()
                if not r: return "[No specialist models installed.]"
                return "\n".join(f"{k}: {v['model']} — {v['good_at']}"
                                 + (f"  (also: {', '.join(v['alternates'])})" if v.get("alternates") else "")
                                 for k, v in r.items())
            if name == "screen_capture":
                reg = a.get("region")
                if isinstance(reg, str):
                    try: reg = json.loads(reg)
                    except Exception: reg = None
                shot = tool_screen_capture(reg if (isinstance(reg, (list, tuple)) and len(reg) == 4) else None)
                if shot.get("error"):
                    return f"[screen error] {shot['error']}"
                pending_images.append(shot["image_b64"])
                return (f"[screen] Screenshot captured ({shot['width']}x{shot['height']}, "
                        "scaled from the real screen) and attached to the next message — "
                        "look at the image. Coordinates you give to gui_action must be in REAL "
                        "screen pixels, so scale up from what you see.")
            # ── Managed browser: ND's own logged-in, off-screen Chrome ──
            if name in ("browser_open", "browser_read", "browser_find",
                        "browser_click", "browser_type", "browser_see"):
                br = nd_browser()
                if not br:
                    return ("[browser unavailable: the managed browser could not start "
                            "(no Chrome found, or the websockets package is missing). "
                            "Fall back to web_fetch for pages that do not need a login.]")
                why = br.available()
                if why:
                    return "[browser unavailable: " + why + "]"
                if name == "browser_open":  return br.open(a.get("url", ""))
                if name == "browser_read":  return br.read(int(a.get("max_chars", 8000) or 8000))
                if name == "browser_find":  return br.find(a.get("query", ""))
                if name == "browser_click": return br.click(a.get("ref", ""), a.get("text", ""))
                if name == "browser_type":
                    return br.type(a.get("text", ""), a.get("ref", ""),
                                   a.get("selector", ""), bool(a.get("enter")))
                if name == "browser_see":
                    shot = br.screenshot()
                    if shot.get("error"):
                        return "[browser] Could not capture the page: " + shot["error"]
                    pending_images.append(shot["image_b64"])
                    return ("[browser] Screenshot of the managed browser page attached to the "
                            "next message — look at the image.")
            # ── Hidden desktop: a native app driven where the user cannot see it ──
            if name == "hidden_desktop":
                hd = nd_desktop()
                if not hd:
                    return ("[hidden desktop unavailable: pywin32 is missing, or this is not "
                            "Windows. Use gui_action on the real screen instead.]")
                why = hd.available()
                if why:
                    return "[hidden desktop unavailable: " + why + "]"
                act = str(a.get("action", "")).strip().lower()
                def _i(v):
                    try: return int(v)
                    except Exception: return None
                if act == "launch":  return hd.launch(a.get("command", "") or a.get("cmd", ""))
                if act == "windows": return hd.windows()
                if act == "stop":    return hd.stop()
                if act == "see":
                    shot = hd.capture(_i(a.get("hwnd")))
                    if shot.get("error"):
                        return "[hidden] Could not capture: " + shot["error"]
                    pending_images.append(shot["image_b64"])
                    return (f"[hidden] Captured window {shot.get('hwnd')} "
                            f"({shot.get('width')}x{shot.get('height')}) — look at the image. "
                            "Coordinates for click/type are client pixels within this window.")
                if act == "click":   return hd.click(_i(a.get("hwnd")), _i(a.get("x")) or 0, _i(a.get("y")) or 0)
                if act == "type":    return hd.type(_i(a.get("hwnd")), a.get("text", ""))
                return ("[hidden] Unknown action. Use: launch, windows, see, click, type, stop.")
            return f"[Unknown tool: {name}]"
        except Exception as e:
            return f"[Tool error in {name}: {e}]"

    # Some models emit tool calls as XML in the text stream when Ollama's parser
    # misses them (Qwen: <tool_call><function=name><parameter=k>v</parameter>...).
    # Parse these BEFORE any cleaning, or the tags get stripped and the call is lost.
    _xml_block = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL | re.I)
    _xml_fn    = re.compile(r"<function=([A-Za-z_][A-Za-z0-9_]*)\s*>(.*?)</function>", re.DOTALL | re.I)
    _xml_param = re.compile(r"<parameter=([A-Za-z_][A-Za-z0-9_]*)\s*>(.*?)</parameter>", re.DOTALL | re.I)

    def _parse_xml_calls(text):
        out = []
        if not text:
            return out
        low = text.lower()
        if "<tool_call" not in low:
            # bare <function=name><parameter=k>v</parameter></function> with no wrapper
            if "<function=" in low:
                for fname, body in _xml_fn.findall(text):
                    args = {k: v.strip() for k, v in _xml_param.findall(body)}
                    out.append({"name": fname, "arguments": args, "_arg": None})
            return out
        for blk in _xml_block.findall(text):
            b = blk.strip()
            if b.startswith("{"):                      # JSON-in-tool_call variant
                try:
                    o = json.loads(b)
                    nm = o.get("name") or o.get("function", {}).get("name")
                    ar = o.get("arguments") or o.get("function", {}).get("arguments") or {}
                    if isinstance(ar, str):
                        try: ar = json.loads(ar)
                        except Exception: ar = {"path": ar}
                    if nm: out.append({"name": nm, "arguments": ar, "_arg": None})
                    continue
                except Exception:
                    pass
            for fname, body in _xml_fn.findall(b):     # <function=..><parameter=..>
                args = {k: v.strip() for k, v in _xml_param.findall(body)}
                out.append({"name": fname, "arguments": args, "_arg": None})
        return out

    def _strip_xml_calls(text):
        t = _xml_block.sub("", text or "")
        return _xml_fn.sub("", t)

    # ── Bare-JSON tool calls ─────────────────────────────────────────────────
    # Qwen3-Coder GGUFs emit a plain JSON object into the CONTENT stream:
    #
    #     {"name": "write_file", "arguments": {"path": "...", "content": "..."}}
    #
    # The quant's chat template does not mark it as a tool call, so Ollama hands
    # it back as ordinary text and `tool_calls` comes back empty. The XML parser
    # does not match it and the TOOL: parser does not match it, so the call was
    # dropped on the floor and the turn looked exactly like a model that had
    # promised work and done none. It had not: it called the tool correctly and
    # ND threw the call away. Measured: 3/3 write_file calls lost this way.
    # Candidate JSON starts. Covers three shapes seen from this model:
    #   {"name": "write_file", "arguments": {...}}            bare call
    #   {"id": "call_x", "type": "function", "function": {...}}   OpenAI item
    #   [{"id": ..., "function": {...}}]                      OpenAI ARRAY
    # The array form is what the model fell back to after being told its call
    # did not parse, and the old start-pattern (which required "name"/"tool"/
    # "function" as the FIRST key) matched none of it, so those calls were
    # dropped and the whole array was shown to the user as chat text.
    _JSON_START = re.compile(r'[\[{]')
    _TOOLISH = re.compile(r'"(?:name|tool|tool_name|function|arguments|parameters)"\s*:', re.I)

    def _norm_call(obj, known):
        """One OpenAI-ish call object -> {"name", "arguments"} or None."""
        if not isinstance(obj, dict):
            return None
        fn = obj.get("function") if isinstance(obj.get("function"), dict) else obj
        nm = fn.get("name") or obj.get("tool") or obj.get("tool_name")
        ar = fn.get("arguments")
        if ar is None:
            ar = fn.get("parameters") or obj.get("arguments") or {}
        if isinstance(ar, str):
            try:
                ar = json.loads(ar)
            except Exception:
                # Was: ar = {"path": ar}. When arguments came back as a MALFORMED
                # json string that wrapped the entire broken blob as the file
                # path, producing a write_file whose path was
                # `["path": "G:\\TMP\\...", "content": "<!DOCTYPE...`. A junk
                # path is worse than a dropped call: the dropped call gets
                # nudged, the junk one gets executed.
                log(f"Discarded {nm} call with unparseable arguments string", "warn")
                return None
        # Only accept names ND can actually run. A model quoting JSON while
        # EXPLAINING a tool would otherwise get executed.
        if nm in known and isinstance(ar, dict):
            return {"name": nm, "arguments": ar, "_arg": None}
        return None

    def _json_call_spans(text, known):
        """[(start, end, [calls])] for every tool-call object or array found."""
        spans = []
        if not text or '"' not in text:
            return spans
        dec = json.JSONDecoder()
        i, n = 0, len(text)
        while i < n:
            m = _JSON_START.search(text, i)
            if not m:
                break
            start = m.start()
            if not _TOOLISH.search(text, start, start + 200):
                i = start + 1
                continue
            # Must name a tool ND can actually run. Without this, ordinary prose
            # like 'the config uses {"name": "value"} pairs' counted as a tool
            # call: it got stripped out of the reply AND flagged the turn as a
            # malformed call. Unrecognised JSON is left completely alone.
            window = text[start:start + 400]
            if not any(('"' + k + '"') in window for k in known):
                i = start + 1
                continue
            try:
                obj, end = dec.raw_decode(text[start:])
            except ValueError:
                # Truncated tool-call JSON: nothing after an unterminated object
                # is prose, so claim the rest and stop.
                spans.append((start, n, []))
                break
            items = obj if isinstance(obj, list) else [obj]
            calls = [c for c in (_norm_call(o, known) for o in items) if c]
            if calls:
                spans.append((start, start + end, calls))
            i = start + end
        return spans

    def _parse_json_calls(text):
        known = set(TOOL_TIERS) | {s.get("function", {}).get("name")
                                   for s in (TOOL_SCHEMAS or [])}
        out = []
        for _s, _e, calls in _json_call_spans(text, known):
            out += calls
        return out

    def _strip_json_calls(text):
        """Remove tool-call JSON so its payload is not echoed as chat text -- a
        whole HTML file, or a raw tool_calls array, is not an answer.

        Shares _json_call_spans with the parser so the two can never disagree
        about what counts as a tool call."""
        if not text:
            return text
        known = set(TOOL_TIERS) | {s.get("function", {}).get("name")
                                   for s in (TOOL_SCHEMAS or [])}
        for a, b, _calls in reversed(_json_call_spans(text, known)):
            text = text[:a] + text[b:]
        return text

    # ── Fenced-code-block salvage ────────────────────────────────────────────
    # Third way this model delivers a file without calling a tool: it writes the
    # whole thing into a ```html fence in the chat reply. The content is right
    # there and complete; only the delivery mechanism is missing. Rather than
    # tell the user "nothing was created" while a finished 12 KB page sits in
    # the transcript, synthesise a write_file call from it.
    #
    # This does NOT bypass anything: the synthesised call goes through the same
    # permission gate as a model-issued write_file, so the autonomy setting
    # still decides whether it runs or asks.
    _FENCE_RE = re.compile(r"```([A-Za-z0-9_.+-]*)[ \t]*\n(.*?)```", re.DOTALL)
    _FNAME_RE = re.compile(r"([A-Za-z0-9_.\-]+\.(?:html?|css|js|jsx|ts|tsx|py|json|md|txt|svg))", re.I)
    _LANG_DEFAULT = {"html": "index.html", "css": "styles.css", "js": "app.js",
                     "javascript": "app.js", "python": "main.py", "py": "main.py",
                     "json": "data.json", "md": "README.md", "svg": "image.svg"}

    def _salvage_code_blocks(text, workspace, already):
        """Turn substantial fenced code blocks into write_file calls."""
        if not text or not workspace or "```" not in text:
            return []
        base = Path(workspace)
        used = {Path(p).name.lower() for p in already}
        out = []
        for m in _FENCE_RE.finditer(text):
            info, body = (m.group(1) or "").strip().lower(), m.group(2)
            if len(body.strip()) < 400:       # a snippet, not a deliverable
                continue
            # name, best source first: the fence info string, then any filename
            # mentioned in the 200 chars before the fence, then the language.
            name = ""
            fm = _FNAME_RE.search(info)
            if fm:
                name = fm.group(1)
            if not name:
                lead = text[max(0, m.start() - 200):m.start()]
                names = _FNAME_RE.findall(lead)
                if names:
                    name = names[-1]
            if not name:
                name = _LANG_DEFAULT.get(info.split(":")[0], "")
            if not name:
                continue
            stem, dot, ext = name.rpartition(".")
            n, cand = 2, name
            while cand.lower() in used or (base / cand).exists():
                cand = f"{stem}-{n}{dot}{ext}"
                n += 1
            used.add(cand.lower())
            out.append({"name": "write_file",
                        "arguments": {"path": str(base / cand), "content": body},
                        "_arg": None, "_salvaged": True})
        return out

    _legacy_pat = re.compile(r"TOOL:\s*(web_fetch|web_search|read_file|write_file|edit_file|search_files|list_dir|run_script|run_shell|install_app|screen_capture|gui_action|design_review)\s+(.+?)(?=\nTOOL:|$)", re.DOTALL)
    def _legacy_parse(text):
        calls = []
        # The same calls written as bracket tags at the start of a line:
        #     [READ_FILE] G:\x\set_location.py
        #     [WRITE_FILE] G:\x\set_location.py ||| """docstring...
        # Measured 2026-09-25: qwen3-coder:30b wrote exactly this in text mode,
        # a whole corrected file included, and none of it ran. It is the TOOL:
        # line in a different coat, so read it as one.
        text = _BRACKET_TOOL_RE.sub(lambda m: "TOOL:" + m.group(1).lower() + " ", text or "")
        for m in _legacy_pat.finditer(text):
            name = m.group(1).strip(); arg = _strip_template_words(m.group(2).strip())
            if   name == "read_file":
                _pp = arg.split("|||"); a = {"path": _pp[0].strip()}
                if len(_pp) > 1: a["offset"] = _pp[1].strip()
                if len(_pp) > 2: a["limit"]  = _pp[2].strip()
            elif name in ("list_dir","run_script"): a = {"path": arg}
            elif name == "design_review":
                _pp = arg.split("|||"); a = {"path": _pp[0].strip()}
                if len(_pp) > 1: a["brief"] = _pp[1].strip()
            elif name == "run_shell":  a = {"command": arg}
            elif name == "screen_capture": a = {}
            elif name == "install_app":
                parts = arg.split("|||"); a = {"name": parts[0].strip(),
                                               "manager": parts[1].strip() if len(parts) > 1 else "winget"}
            elif name == "gui_action":
                parts = [p.strip() for p in arg.split("|||")]
                a = {"action": parts[0]}
                if len(parts) > 2: a["x"], a["y"] = parts[1], parts[2]
                elif len(parts) > 1: a["text"] = parts[1]
            elif name == "web_search": a = {"query": arg}
            elif name == "web_fetch":  a = {"url": arg}
            elif name == "resolve_app": a = {"name": arg}
            elif name == "browser_open": a = {"url": arg}
            elif name == "browser_read": a = {}
            elif name == "browser_find": a = {"query": arg}
            elif name == "browser_see":  a = {}
            elif name == "browser_click":
                a = {"ref": arg} if re.match(r"^r\d+$", arg.strip()) else {"text": arg}
            elif name == "browser_type":
                parts = arg.split("|||")
                a = {"ref": parts[0].strip(), "text": parts[1] if len(parts) > 1 else ""}
            elif name == "search_files":
                parts = arg.split("|||"); a = {"root": parts[0].strip(), "pattern": parts[1].strip() if len(parts)>1 else ""}
            elif name in ("find_definition", "find_references"): a = {"name": arg.strip()}
            elif name == "edit_file":
                parts = arg.split("|||")
                a = {"path": parts[0].strip(),
                     "old_text": _sep_trim(parts[1]) if len(parts) > 1 else "",
                     "new_text": _sep_trim(parts[2]) if len(parts) > 2 else ""}
            elif name == "write_file":
                parts = arg.split("|||", 1)
                a = {"path": parts[0].strip(),
                     "content": _sep_trim(parts[1], tail=False) if len(parts) > 1 else ""}
            else: a = {}
            calls.append({"name": name, "arguments": a, "_arg": arg[:120]})
        return calls

    # The user's own one-file scope, enforced. "Change ONLY x.py ... Write only
    # x.py" used to be honoured in words only: measured 2026-09-25, ND's test
    # check asked for a test and the model wrote test_x.py, which the run gate
    # then spent two repair passes on. The placed-edit steps already confine
    # writes to one file (only_file); a top-level request that names its one
    # file gets the same guard. Reads are never restricted.
    _scope_by_user = False
    if allow_split and not only_file and workspace:
        try:
            _bpm = build_plan_mod()
            _tgt = (_bpm.single_file_target(_last_user)
                    if _bpm and hasattr(_bpm, "single_file_target") else None)
            if _tgt:
                _tp = Path(_tgt)
                if not _tp.is_absolute():
                    _tp = Path(workspace) / _tp
                only_file = str(_tp)
                _scope_by_user = True
                log(f"Scope: the request changes only {_tp.name} - writes to any "
                    "other file will be refused", "info")
        except Exception as _se:
            log(f"scope check skipped: {_se}", "warn")

    MAX_ROUNDS = int(_config.get("agent_max_rounds", 14))
    # Context budget. num_ctx is 32768 tokens ~= 130k chars for EVERYTHING:
    # system prompt, memory block, the whole transcript and every tool result.
    # These two numbers are what keep tool output from eating all of it.
    # Must stay comfortably ABOVE READ_PAGE_CHARS plus the header, structure map
    # and footer, or a paged read gets clipped and the model loses the
    # "resume with offset=N" instruction at the end of it.
    # Resolved per model, not from flat config: an 8K-context model gets a
    # ~32k-char window for the whole conversation, so a 14k-char tool result
    # would be nearly half of it in one go. See model_profile().
    TOOL_RESULT_CHARS = _prof["tool_result_chars"]
    KEEP_VERBATIM = _prof["keep_verbatim"]
    native = True
    convo = list(full_messages)
    all_tool_calls, all_tool_results = [], []
    # Every .py this turn writes, for the integration gate at the end.
    # all_tool_calls rows are {"tool", "arg"} and carry NO path (see the note at
    # the top of the tool section), so the paths have to be taken here, in the
    # round loop, where the arguments still exist. Reading them off
    # all_tool_calls silently produced an empty list and disabled the gate
    # entirely on its first two live runs.
    _gate_py = []
    denied_record = []         # calls the user refused, for the honesty check at the end
    refused_keys = set()       # refused ONCE = refused for the rest of the turn
    seen_calls = {}            # (tool,args) -> round, to break read-the-same-thing loops
    # Order of execution, so "this file was written AFTER it was last read" can
    # be told apart from a pointless repeat read. See _stale below.
    _op_seq = 0
    _seen_seq = {}             # (tool,args) -> _op_seq when it last ran
    _write_seq = {}            # path key -> _op_seq of the last successful write
    _body_loop = None          # (names, count) once identical content repeats
    seen_results = {}          # (tool,args) -> the result, for re-serving after compaction
    reserves = {}              # (tool,args) -> times it has been re-served this turn
    stuck_hits = {}            # (tool,args) -> times the STUCK breaker fired for it
    stuck_stop = None          # set when one call has been refused too many times
    shots_taken = 0            # screenshots are cheap to ask for and expensive to read
    MAX_SHOTS = 4
    auto_continues = 0         # nudges spent on replies that announced work but did none
    MAX_AUTO_CONTINUE = int(_config.get("agent_max_auto_continue", 3))
    rounds_used = 0            # ACTUAL rounds, not the budget - the dead-end
                               # message used to print MAX_ROUNDS and claim the
                               # budget was exhausted when it plainly was not
    final = ""
    ctx_pct = 0                # real prompt size as a % of the window, per round
    # Per-file write limit. Counted on the SESSION (see note_rewrite), so typing
    # "continue" does not hand the model a fresh allowance -- that reset is how
    # one .bat file got written 16 times.
    REWRITE_LIMIT = max(2, int(_config.get("agent_rewrite_limit", 3)))
    # Forced design passes. A small model's first attempt is always its worst.
    _review_laps = 0
    _MAX_REVIEW_LAPS = max(0, int(_config.get("ui_review_rounds", 3)))
    # Forced test pass. Measured on T3 x30: when the model changed existing code
    # it added a test only 6/30 times — and the failure was NEVER bad tests, it
    # was skipping the test file entirely (5 of the 11 working-endpoint runs
    # never touched it; every run that did touch it passed). rule 10 in the
    # prompt was ignored ~45% of the time even on good runs, because the model
    # counts itself done the moment the feature works. So, like the design gate,
    # refuse to finish a code-changing turn that touched no test — once.
    _test_laps = 0
    _test_skip_logged = False
    # Teeth: more than one lap, escalating. One polite ask was ignored by the
    # 30B on 2 of 2 eligible skips (measured); insist, bounded.
    _MAX_TEST_LAPS = max(0, int(_config.get("agent_test_rounds", 2)))
    # Did-you-actually-edit gate. The biggest T3 miss is NO code, not bad code:
    # 107/376 runs finished a build task having written nothing. Like the test
    # gate, insist up to a bounded number of escalating laps.
    _edit_laps = 0
    _MAX_EDIT_LAPS = max(0, int(_config.get("agent_edit_rounds", 2)))

    _suite_state = {}       # lazily holds the pre-edit suite snapshot

    def _compact_convo(hard=False):
        """Shrink older tool results. Without this every round re-sends every page
        read so far, which is what made rounds crawl from 90s to 250s.

        hard=True is the overflow response: keep NOTHING verbatim and cut much
        harder. Losing the detail of an old file read is recoverable -- the
        model can read it again. Losing the user's original instruction off the
        front of the window is not, and that is what Ollama silently does when
        the prompt exceeds num_ctx.

        Soft compaction also protects the LATEST read of each distinct file.
        Measured over six T3 runs: the model read test_public.py 28 times,
        schemas.py 24 and public.py 23 -- four to five re-reads of the same file
        per run -- and the loop breaker fired 23 times catching it. Keeping only
        the last two results verbatim meant a file read at round 3 was gone by
        round 6, so the model read it again, and that read was compacted in turn.

        The window was never the problem: not one of those runs reached the 70%
        threshold. Compaction was discarding files the model was actively working
        on while there was room to spare, and charging a round for each one.
        Under real pressure hard=True still drops everything.
        """
        keep = 0 if hard else KEEP_VERBATIM
        head, cut = (150, 120) if hard else (500, 400)
        tool_idx = [i for i, m in enumerate(convo) if m.get("role") == "tool"]

        protect = set(tool_idx[-keep:]) if keep else set()
        if not hard:
            # Newest surviving result per file, capped so a long exploration
            # cannot pin the whole window open.
            newest = {}
            for i in tool_idx:
                f = _tool_result_file(convo[i].get("content", ""))
                if f:
                    newest[f] = i
            # Newest first, until the budget is spent. Counting files instead of
            # characters is what blew the window; a big file costs more of the
            # budget than a small one, which is the whole point.
            budget = int(_prof["num_ctx"] * 4 * COMPACT_KEEP_SHARE)
            for i in sorted(newest.values(), reverse=True):
                size = len(convo[i].get("content", ""))
                if size > budget:
                    break
                budget -= size
                protect.add(i)

        for i in tool_idx:
            if i in protect:
                continue
            c = convo[i].get("content", "")
            if not hard and len(c) <= SMALL_RESULT_KEEP:
                continue
            if len(c) > head and not c.endswith("[...compacted]".replace("...", chr(8230))):
                convo[i]["content"] = c[:cut] + chr(10) + "[" + chr(8230) + "compacted]"

    def _with_reminder(msgs):
        """Capabilities restated at the tail, transiently, for this send only.

        Appended to the LAST message rather than added as a trailing system turn:
        strict chat templates (Mistral/Devstral require alternating roles) reject
        a trailing system message, and text inside an existing message cannot
        break any template. Not written back into `convo`, so it never accumulates.
        """
        if not msgs:
            return msgs
        out = list(msgs)
        last = dict(out[-1])
        last["content"] = (last.get("content") or "") + chr(10) + chr(10)
        last["content"] += CAPABILITY_REMINDER
        out[-1] = last
        return out

    def _fit_context():
        """Make the prompt fit BEFORE it is sent.

        Ollama does not error on overflow: it drops the oldest messages, which is
        the system prompt -- the capability declaration and the task. Reacting
        afterwards (see _check_context) is already too late for that round. So
        project the size here, compact hard first, and if that is still not
        enough drop the OLDEST transcript turns ourselves. convo[0] (the system
        prompt) is never dropped; that is the whole point.
        """
        window = _prof["num_ctx"]
        limit = int(window * PRESEND_MAX_SHARE)

        _cpt = chars_per_token(model)

        def approx():
            # Learned ratio, not a fixed 4. See CHARS_PER_TOKEN_DEFAULT.
            return int(sum(len(m.get("content") or "") for m in convo) / _cpt)

        if approx() <= limit:
            return
        before = approx()
        _compact_convo(hard=True)
        dropped = 0
        # Still over: shed oldest transcript turns, never the system prompt.
        while approx() > limit and len(convo) > 3:
            del convo[1]
            # Never leave a tool result as the first transcript message -- the
            # assistant tool_call it answers has just been removed.
            while len(convo) > 3 and convo[1].get("role") == "tool":
                del convo[1]
            dropped += 1
        log(f"Pre-send fit: {before} -> {approx()} tok (limit {limit} of {window})"
            + (f", dropped {dropped} old turn(s)" if dropped else ""), "warn")
        agent_activity(req_id, "compact", "fitted context before send",
                       f"{before}->{approx()} tok"
                       + (f", -{dropped} old turns" if dropped else ""), ok=True)

    def _check_context(prompt_tokens, rnd):
        """Watch the real prompt size against the window and act before it wraps.

        Ollama does not error on overflow. It drops the oldest messages and
        carries on, so the first visible symptom is a model that has 'forgotten'
        the task and starts narrating instead of working. Catching it here is
        the difference between a fix and a mystery."""
        if not prompt_tokens:
            return
        # Called straight after the send, so convo is still exactly what went
        # out (plus the transient reminder _with_reminder appended to it).
        _sent = sum(len(m.get("content") or "") for m in convo) + len(CAPABILITY_REMINDER) + 2
        learn_chars_per_token(model, _sent, prompt_tokens)
        window = _prof["num_ctx"]
        pct = round(100 * prompt_tokens / window)
        agent_activity(req_id, "context", f"context {prompt_tokens}/{window} tok",
                       f"{pct}% of window", ok=(pct < 85))
        if pct >= 70:
            before = sum(len(m.get("content") or "") for m in convo)
            _compact_convo(hard=True)
            after = sum(len(m.get("content") or "") for m in convo)
            log(f"Context at {pct}% of {window} on round {rnd} — hard-compacted "
                f"{before-after} chars of old tool output", "warn")
            agent_activity(req_id, "compact", "freed context",
                           f"{(before-after)//1000}k chars of old tool output", ok=True)
        return pct
    _auto_reads = []          # paths salvage_intended_read made the model read
    for rnd in range(1, MAX_ROUNDS + 1):
        if should_cancel and should_cancel():
            log("Chat cancelled by user", "info")
            return {"final_response": final or "[cancelled]", "tool_calls": all_tool_calls,
                    "tool_results": all_tool_results, "needs_permission": None}
        rounds_used = rnd
        cb = (lambda _r: (lambda n: _set_status("generating", f"Round {_r}: generating… ~{n*2} tokens", 55)))(rnd)
        agent_round(req_id, rnd)
        if rnd > 1:
            stream_append(req_id, "\n\n── round %d ──\n" % rnd)
        # Nothing streams during prefill -- Ollama emits no token until the
        # whole prompt is read. Measured live: 21.3s of a 23.7s round with a
        # short prompt and a cold model, so 90% of the wait was blank screen.
        # On this user's real workload (21,600-token prompts) it is minutes.
        # Streaming tokens does nothing for that window; saying what is
        # happening does.
        _fit_context()
        _approx = sum(len(m.get("content") or "") for m in convo) // 4
        _set_status("thinking",
                    f"Round {rnd}: reading ~{_approx:,} tokens of context "
                    f"— no output until this finishes", 35)
        agent_activity(req_id, "think", f"round {rnd}", "model reasoning")
        calls, content = [], ""
        # Set when THIS round has to be redone as text. Kept separate from
        # `native`, which latches off for the whole conversation: one bad round
        # should not cost the model native tool calling for every round after.
        retry_as_text = False
        if native:
            resp = ollama_chat_native(model, _with_reminder(convo), active_tools, status_cb=cb, text_cb=_stream)
            if resp.get("native_ok"):
                content = (resp.get("content") or "").replace("\\_","_")   # keep RAW for parsing
                calls = [dict(c, _arg=None) for c in resp.get("tool_calls", [])]
                ctx_pct = _check_context(resp.get("prompt_tokens"), rnd)
                # A DEAD round: HTTP 200, stream ended, nothing in it -- no
                # content, no tool call, no error. Measured on
                # OBSIDIAN-9B-Coder, which does this when its grammar-
                # constrained tool call goes wrong part way through emitting a
                # very large `content` argument. Ollama reports the failure by
                # simply stopping. Nothing downstream can tell that apart from
                # "the model had nothing to say", so the loop burns a round and
                # the user watches it do nothing.
                #
                # The tool GRAMMAR is what broke, so retry without it: the same
                # model then writes the call as text, which the XML/JSON/legacy
                # parsers below recover. Once only -- a model that is dead twice
                # is dead.
                if resp.get("retry_as_text"):
                    # A 5xx from Ollama on this one call. Same treatment as a
                    # dead round -- redo it as text -- but `native` stays on, so
                    # one bad request does not cost the rest of the turn.
                    agent_activity(req_id, "retry", "ollama server error",
                                   f"{resp.get('server_error', '5xx')} — this round as text",
                                   ok=False)
                    retry_as_text = True
                elif not calls and not content.strip():
                    log(f"{model} returned an empty native round (no content, no "
                        f"tool call, no error) — retrying without the tool "
                        f"grammar so it can answer as text", "warn")
                    agent_activity(req_id, "retry", "empty native round",
                                   "retrying without native tool calling", ok=True)
                    retry_as_text = True
            else:
                native = False
        if not native or retry_as_text:
            content = ollama_chat(model, _with_reminder(convo), status_cb=cb, clean=False, text_cb=_stream).replace("\\_","_")
        # parse order: native structured -> leaked XML -> bare JSON -> TOOL: text
        if not calls:
            calls = _parse_xml_calls(content)
        if not calls:
            calls = _parse_json_calls(content)
            if calls:
                log(f"Recovered {len(calls)} tool call(s) from bare JSON in the "
                    f"content stream ({model}) — Ollama did not tag them", "warn")
        if not calls:
            calls = _legacy_parse(content)
        if not calls:
            # Last resort: the call written as source. See parse_funcall_calls.
            calls = parse_funcall_calls(content, set(TOOL_TIERS))
            if calls:
                log(f"Recovered {len(calls)} tool call(s) written as function "
                    f"calls ({model}) — none of the four normal shapes matched", "warn")
                agent_activity(req_id, "salvage", f"{len(calls)} call(s) from source text",
                               "model wrote the call instead of making it", ok=True)
        if not calls and workspace:
            calls = _salvage_code_blocks(content, workspace, _written_paths(all_tool_calls))
            if calls:
                log(f"Salvaged {len(calls)} file(s) from fenced code blocks — the "
                    f"model wrote the content into chat instead of calling write_file", "warn")
                agent_activity(req_id, "salvage", f"{len(calls)} file(s) from chat",
                               "model pasted the code instead of calling the tool", ok=True)
        if not calls and only_file:
            _bare = salvage_bare_source(content, only_file)
            if _bare:
                calls = [_bare]
                log(f"Salvaged {Path(only_file).name} from bare source in the reply - the "
                    f"model wrote the file as text after its path instead of calling "
                    f"write_file", "warn")
                agent_activity(req_id, "salvage", Path(only_file).name,
                               "model wrote the file as plain text", ok=True)
        if not calls and len(_auto_reads) < 4:
            _rd = salvage_intended_read(content, workspace, _auto_reads)
            if _rd:
                calls = [_rd]
                _auto_reads.append(_rd["arguments"]["path"])
                log(f"Made the read the model only announced or typed: "
                    f"{Path(_rd['arguments']['path']).name}", "warn")
                agent_activity(req_id, "salvage", Path(_rd["arguments"]["path"]).name,
                               "model announced a read without calling the tool", ok=True)
        content_clean = strip_tool_lines(
            clean_ai_response(_strip_json_calls(_strip_xml_calls(content))))
        # ollama_chat returns the literal string "[No response]" when the stream
        # produced nothing. That is a sentinel, not an answer, and it must never
        # reach the user as one -- it says nothing about what the run did or why
        # it stopped. Measured 2026-09-01 on the LeninShop benchmark: 9 rounds
        # and 75s of real work, reported to the user as "[No response]". Clearing
        # it here lets the honest dead-end report at the end do its job.
        if content_clean.strip() in ("[No response]", "[No response.]"):
            log("Model stream was empty — dropping the sentinel so the dead-end "
                "report explains what actually happened", "warn")
            content_clean = ""
        # Did the reply CONTAIN a tool-call object that we could not run? That
        # means the model tried to call a tool and got the JSON wrong -- usually
        # truncated by the output cap mid-`content`. It is not an answer, and it
        # must never be shown as one: an 11,586-char blob starting
        # {"name": "write_file", ... is what the user saw pasted into chat.
        # Only when a tool-call-SHAPED blob was found and yielded no runnable
        # call. Testing for a bare "{" here flagged every reply containing a
        # brace as a malformed tool call.
        json_echo = bool(calls == [] and _json_call_spans(
            content or "", set(TOOL_TIERS) | {s.get("function", {}).get("name")
                                              for s in (TOOL_SCHEMAS or [])}))
        if not calls:
            # The model frequently ends a turn on a lead-in it never acts on:
            #     "Now let me create the HTML frontend for the application:"
            # ...with no tool call attached. The turn then just STOPS, and the
            # only way forward was for the user to type "ok" to nudge it, over
            # and over. That is not an approval prompt, it is an abandoned
            # sentence, and the UI had no way to tell the difference.
            #
            # If the reply announces an action but performs none, push it once
            # rather than handing a dangling promise back to the user.
            echoed = imitates_tool_results(content)
            if echoed and echo_is_recap(content, all_tool_results):
                # Quoting real results is a summary, not a fake. See echo_is_recap.
                log("Reply quotes real tool results - treated as a summary, "
                    "not as a faked tool call", "info")
                echoed = False
            elif echoed:
                _ex = next((ln for ln in (content or "").splitlines()
                            if _RESULT_ECHO_RE.match(ln)), "")
                log(f"  echoed line: {_ws_norm(_ex)[:160]}", "info")
            echoed = echoed or json_echo
            promised = announces_unfinished_work(content_clean)
            if echoed or promised:
                st = note_no_progress(session_id, content_clean)
                # Stop early on an exact repeat: saying the same thing twice is
                # proof the nudge is not landing, so more nudges will not help.
                # A repeat is only proof the nudge is useless once the model has
                # actually SEEN a nudge. Stopping on the first repeat used to
                # end the run at "Attempts: 1" when the duplicate reply came
                # from an earlier user turn that was never nudged at all.
                give_up = st["repeat"] and st["count"] >= 2
                # A run that has already produced files is not a stuck run, it
                # is a productive one pausing between steps. Spend more patience
                # on it: the RetroVault run wrote two real files and was cut off
                # one nudge before the third.
                _done = _written_paths(all_tool_calls)
                patience = MAX_AUTO_CONTINUE + min(len(_done), 5)
                if (st["count"] <= patience and rnd < MAX_ROUNDS
                        and not give_up):
                    log(f"No tool calls ({'echoed result format' if echoed else 'announced only'})"
                        f" — auto-continuing ({st['count']}/{patience}"
                        f"{f', {len(_done)} file(s) written so far' if _done else ''})", "warn")
                    _set_status("thinking", "Model did not actually call a tool — correcting…", 45)
                    agent_activity(req_id, "retry",
                                   "no tool call" + (" (typed result format)" if echoed else ""),
                                   f"attempt {st['count']}", ok=False)
                    # Do NOT feed the malformed blob back into the transcript --
                    # it can be 11 KB of half-written JSON, and in an 8K window
                    # that is the whole budget spent echoing a mistake.
                    convo.append({"role": "assistant",
                                  "content": ("[malformed tool call omitted]"
                                              if json_echo else content)})
                    if json_echo:
                        nudge = (
                            "Your tool call did not parse, so NOTHING happened and no file was "
                            "created. The JSON was cut off partway through, almost certainly "
                            "because the file content was too long for one reply.\n\n"
                            "Try again, smaller. Write a SHORTER first version of the file — "
                            "structure and layout only, no long lists of seeded data — then "
                            "extend it with edit_file afterwards.\n\n"
                            "Use the real tool call, not text. If structured calls are not "
                            "working, use the text fallback — substitute YOUR real path and "
                            "YOUR real file contents, like this:\n"
                            "TOOL: write_file G:\\TMP\\TMP\\index.html|||<!doctype html>...\n"
                            "The path comes first, then three pipe characters, then the file.")
                    elif echoed and _done:
                        # Files ARE on disk. "Nothing has been created" would be a
                        # lie that sends the model back to rewrite them.
                        nudge = (
                            "You typed a tool RESULT line (`[FILE] ...`) that NeuralDock did not "
                            "produce. Lines like that are printed by NeuralDock after a real tool "
                            "runs; typing one does nothing.\n\n"
                            "These files ARE already written and on disk - do NOT write them "
                            "again:\n" + "\n".join(f"  - {w}" for w in _done[:10]) + "\n\n"
                            "If the task needs another change, make it now with a real tool "
                            "call. If the task is done, reply with a short plain-text summary "
                            "of what you changed, with no `[FILE]`-style lines in it.")
                    elif echoed:
                        nudge = (
                            "STOP. You wrote a tool RESULT, not a tool CALL.\n\n"
                            "Lines like `[FILE] ...`, `[WEB] ...` and `[RUN] ...` are printed by "
                            "NeuralDock AFTER a tool runs. You must never type them yourself — "
                            "typing them does nothing at all. Nothing has been created.\n\n"
                            "Call the tool for real. Use the write_file tool with a `path` and the "
                            "COMPLETE `content` of the file. If structured tool calls are not "
                            "working for you, use the text fallback, one per line, exactly:\n"
                            "TOOL: write_file {\"path\": \"C:\\\\full\\\\path\\\\file.html\", "
                            "\"content\": \"<!doctype html>...\"}\n\n"
                            "Write ONE file in this reply. Do not describe it. Do not summarise it.")
                    else:
                        # A generic "call a tool" is easy to answer with another
                        # paragraph. Naming the tool, the argument shape and the
                        # working directory leaves nothing to compose around.
                        reads = _count_calls(all_tool_calls, READ_ONLY_TOOLS)
                        writes = len(_done)
                        nudge = (
                            "You described what you were about to do but did not call any tool, so "
                            "that step did not happen. Do it NOW with a real tool call in this "
                            "reply.\n\n")
                        if writes:
                            # Without this it re-writes file 1 instead of moving on.
                            nudge += ("Already written (do NOT write these again):\n"
                                      + "\n".join(f"  - {w}" for w in _done[:10])
                                      + "\n\nWrite the NEXT file.\n\n")
                        if reads and not writes:
                            nudge += (
                                f"You have already run {reads} read-only call(s) and written 0 files. "
                                "You have read enough. Stop investigating and produce output.\n\n")
                        if workspace:
                            nudge += f"Working directory: {workspace}\n"
                        nudge += (
                            "Call write_file with an absolute `path` and the COMPLETE `content` of "
                            "the file. ONE file in this reply — the single most important one. Do "
                            "not summarise it, do not show it in a code block, do not describe what "
                            "it will contain, and do not ask permission: you already have it.\n\n"
                            "If structured tool calls are not working for you, use the text "
                            "fallback exactly:\n"
                            "TOOL: write_file {\"path\": \"C:\\\\full\\\\path\\\\file.html\", "
                            "\"content\": \"<!doctype html>...\"}\n\n"
                            "If you genuinely cannot proceed, say exactly what is blocking you.")
                    convo.append({"role": "user", "content": nudge})
                    continue
                # Out of patience. Report the dead end honestly rather than
                # handing back an empty promise that looks like success.
                log(f"No progress after {st['count']} attempts"
                    f"{' (identical reply)' if st['repeat'] else ''} — stopping", "error")
                _made = _written_paths(all_tool_calls)
                agent_activity(req_id, "stopped",
                               "partial work" if _made else "no progress",
                               f"{st['count']} attempts, "
                               + (f"{len(_made)} file(s) written" if _made else "nothing written"),
                               ok=False)
                final = no_progress_report(
                    content_clean, echoed, st, ctx_pct=ctx_pct,
                    window=_prof["num_ctx"],
                    reads=_count_calls(all_tool_calls, READ_ONLY_TOOLS),
                    wrote=_written_paths(all_tool_calls))
                break
            # ── Mandatory design iteration ───────────────────────────────────
            # One-shot output from a small model is always its worst output. The
            # loop existed but nothing forced a second lap: design_review ran
            # once, reported seven missing states, and the model said "no
            # further changes are needed". Refuse to finish while a page it
            # wrote is unreviewed or still broken.
            _pending = _unreviewed_pages(session_id)
            if (_ui_job and _pending and rnd < MAX_ROUNDS
                    and _review_laps < _MAX_REVIEW_LAPS):
                _review_laps += 1
                _tgt, _why = _pending[0]
                log(f"Design iteration {_review_laps}/{_MAX_REVIEW_LAPS}: {Path(_tgt).name} — {_why}",
                    "warn")
                agent_activity(req_id, "iterate", f"pass {_review_laps}: {Path(_tgt).name}",
                               _why[:80], ok=False)
                convo.append({"role": "assistant", "content": content_clean or "(done)"})
                convo.append({"role": "user", "content":
                    f"Not finished yet. {_why}\n\n"
                    f"Call design_review on {_tgt} now, then FIX what it reports — "
                    "use edit_file, do not rewrite the whole file. Every item under "
                    "BROKEN must go, and any interaction state design_review lists as "
                    "MISSING must be added for real, with human wording. Add ONLY the "
                    "ones it lists: it already skips states the page has nothing to "
                    "apply to, and adding those anyway is padding, not design.\n\n"
                    "Take the SECOND OPINION seriously: if it calls the page basic or "
                    "generic, that is the note to act on, not to argue with. Then review "
                    "again to confirm it actually improved."})
                continue

            # ── Mandatory edit (did-you-actually-edit gate) ──────────────────
            # The most common miss by far is not bad code, it is NO code. On T3,
            # 107 of 376 runs finished cleanly (status=done, ~18 rounds, a
            # ~2.4k-char reply) having called write_file/edit_file zero times:
            # the model described the solution and never made it. That single
            # mode is the bulk of the 2/9 cluster. When the turn is a build
            # request against a real workspace and nothing was written, refuse to
            # finish and send it back to make the edit with the tool -- bounded,
            # escalating, and never on a UI job (the design gate owns those) or a
            # question (which legitimately ends in prose). It sits BEFORE the
            # test gate: first make the change, then cover it with a test.
            _edit_task = ((not _ui_job) and bool(workspace)
                          and _wants_code_change(_last_user or _orig_task))
            if (_edit_task and not made_any_edit(all_tool_calls)
                    and _edit_laps < _MAX_EDIT_LAPS and rnd < MAX_ROUNDS):
                _edit_laps += 1
                _gate_record(req_id, "edit_gate", fired=True, laps=_edit_laps,
                             wrote=False)
                log(f"Edit iteration {_edit_laps}/{_MAX_EDIT_LAPS}: build task "
                    "finished with no file written", "warn")
                agent_activity(req_id, "iterate", f"make the edit (pass {_edit_laps})",
                               "build task, nothing written yet", ok=False)
                convo.append({"role": "assistant", "content": content_clean or "(done)"})
                if _edit_laps == 1:
                    _emsg = (
                        "You have not changed anything yet. You described the solution but "
                        "called no write_file/edit_file, so NOTHING is on disk and the task "
                        "is not done. Make the change NOW with a real tool call: edit_file the "
                        "existing file (or write_file a new one) under "
                        f"{workspace}. A code block in the reply is NOT a change -- the edit "
                        "only happens through the tool. Do not describe it again; make it.")
                else:
                    _emsg = (
                        "Still nothing written. This is required, not optional. Do exactly "
                        "this now:\n"
                        "  1. read_file / search_files the file you need to change,\n"
                        "  2. call edit_file (or write_file) with the real change,\n"
                        f"  3. keep every path inside {workspace}.\n"
                        "Do not answer with a code block or an explanation -- the only thing "
                        "that finishes this turn is an actual write_file/edit_file call. If "
                        "something genuinely blocks the edit, say exactly what, in one line.")
                convo.append({"role": "user", "content": _emsg})
                continue
            # Record the resolved state once, for the run's telemetry.
            if _edit_task:
                _gate_record(req_id, "edit_gate",
                             wrote=made_any_edit(all_tool_calls), laps=_edit_laps)

            # ── Mandatory test pass ──────────────────────────────────────────
            # The code-job counterpart of the design gate. If the turn changed
            # existing code and never touched a test file, refuse to finish and
            # send it back to add one — INSISTENTLY, up to _MAX_TEST_LAPS with
            # escalating wording, because one polite ask was ignored by the 30B
            # on 2 of 2 eligible skips (measured on T3 x30, where this was the
            # weakest check at 6/30). The stop condition is "a test file was
            # touched", not "a test passes": on a broken endpoint no test can
            # pass, and demanding one would loop or induce a fake pass.
            _chg, _tt = code_test_state(all_tool_calls)
            # Two cases where "add a test" is the wrong instruction. The user
            # scoped the request to one file (a test would be a second file), or
            # the project has no tests at all -- this message says "add a case to
            # the EXISTING test file, do not create one", which cannot be obeyed
            # there. Measured 2026-09-25: both at once, and the model invented
            # test_set_location.py.
            _test_ok = not _scope_by_user and _workspace_has_tests(workspace)
            if _chg and not _tt and not _test_ok and not _test_skip_logged:
                _test_skip_logged = True
                log("Test check skipped: " + ("the request is scoped to one file"
                    if _scope_by_user else "this project has no test files"), "info")
            if (not _ui_job and _chg and not _tt and _test_ok
                    and _test_laps < _MAX_TEST_LAPS and rnd < MAX_ROUNDS):
                _test_laps += 1
                _gate_record(req_id, "test_gate", fired=True, laps=_test_laps,
                             touched_test=False)
                log(f"Test iteration {_test_laps}/{_MAX_TEST_LAPS}: code changed, "
                    "no test was added", "warn")
                agent_activity(req_id, "iterate", f"add a test (pass {_test_laps})",
                               "changed code with no test in the suite", ok=False)
                convo.append({"role": "assistant", "content": content_clean or "(done)"})
                if _test_laps == 1:
                    _msg = (
                        "Not finished yet. You changed existing code but added no test for it. "
                        "NEW BEHAVIOUR NEEDS A TEST (rule 10): use search_files to find the test "
                        "file that already covers this area — the existing test_*.py next to what "
                        "you changed — and add a case there now, in the same style as the tests "
                        "already in it, then run it. Do NOT create a new test file: only files "
                        "that were already green are re-run and checked, so a new one is invisible "
                        "and proves nothing.\n\n"
                        "The one exception: if what you changed was a pure refactor, rename, "
                        "formatting, or a non-code file, it needs no test — say so in one line and "
                        "finish.")
                else:
                    _msg = (
                        "Still no test. This is required, not optional, and it is the last thing "
                        "between you and done. Do exactly this now:\n"
                        "  1. search_files for the existing test file next to what you changed "
                        "(a test_*.py), \n"
                        "  2. read it, \n"
                        "  3. add ONE test case for the behaviour you built, in that same file, "
                        "copying the style of a test already in it, \n"
                        "  4. run it to confirm it passes.\n"
                        "Write to that existing file with edit_file — do not make a new file. "
                        "The only acceptable alternative is a one-line statement that this was a "
                        "pure refactor and needs no test.")
                convo.append({"role": "user", "content": _msg})
                continue
            # Record the resolved state once, for the run's telemetry: did a
            # code-changing turn end with a test touched, or without one.
            if _chg:
                _gate_record(req_id, "test_gate", changed_code=True,
                             touched_test=_tt, laps=_test_laps)

            clear_no_progress(session_id)
            # Never fall back to RAW content when the cleaned text is empty. If
            # cleaning emptied it, what was there was tool-call syntax or think
            # tags -- not an answer. This fallback is what actually pasted the
            # 11 KB JSON blob into the chat window: _strip_json_calls did its
            # job, content_clean came back empty, and this line put the blob
            # straight back.
            if content_clean.strip():
                final = content_clean
            elif json_echo:
                final = ("The model replied with a malformed tool call instead of an answer, "
                         "and it was cut off partway through — so nothing was written.\n\n"
                         "This usually means the file it was trying to write is too long for "
                         "one reply. Ask for a shorter first version, then extend it.")
            else:
                # Leave it EMPTY. The comment above says never to fall back to
                # raw content, and then this branch did exactly that -- which is
                # how the sentinel "[No response]" reached the user as an answer
                # after 9 rounds and 75s of real work on the LeninShop benchmark.
                # An empty `final` is what triggers the dead-end report below,
                # and that report says what the run actually did.
                final = ""
            break

        # ── Rewrite guard ────────────────────────────────────────────────────
        # A small model working through a multi-file build can get stuck
        # polishing file one instead of starting file two. Measured: the same
        # path written three times in a row, each round costing ~40s, with the
        # "already written, write the NEXT file" instruction in front of it.
        # Rewriting IS progress by every other measure here -- a real tool call,
        # a real file -- so nothing else catches it.
        for _c in calls:
            if _c.get("name") in WRITE_TOOLS:
                _wp = (_c.get("arguments") or {}).get("path")
                # Only WHOLE-file rewrites count. Several edit_file calls on one
                # file are how a multi-part change is made, and a FAILED edit
                # changed nothing. Measured 2026-09-25: one good edit plus one
                # failed edit was reported as "set_location.py was written 3
                # times", a rewrite loop, on a one-file request.
                if _c.get("name") == "write_file":
                    note_rewrite(session_id, _wp)
                _dupe_names, _dupe_n = note_rewrite_body(
                    session_id, _wp, (_c.get("arguments") or {}).get("content"))
                if _dupe_n >= REWRITE_LIMIT and _dupe_names:
                    _body_loop = (_dupe_names, _dupe_n)
                if _wp and str(_wp).lower().endswith(".py"):
                    _gate_py.append(str(_wp))
        _worst, _hot = hottest_rewrite(session_id)
        if _body_loop:
            _bn, _bc = _body_loop
            log(f"Same CONTENT written {_bc} times under different names ({_bn}) "
                f"— stopping the rewrite loop", "error")
            agent_activity(req_id, "stopped", "duplicate-file loop",
                           f"{_bc} identical files", ok=False)
            all_tool_calls.extend([{"tool": c["name"], "arg": _summ(c["arguments"]),
                                    "path": (c.get("arguments") or {}).get("path"),
                                    "failed": _call_failed(c)}
                                   for c in calls])
            all_tool_results.extend(results)
            clear_rewrites(session_id)
            final = ("STOPPED - the model wrote the same file over and over under "
                     "different names." + NL + NL
                     + f"{_bc} byte-identical files were written: {_bn}" + NL + NL
                     + "This is not progress, it is the rewrite loop wearing a "
                       "different hat — renaming the output does not make it a new "
                       "file. Nothing here advanced the task." + NL + NL
                     + "Ask for the next real file BY NAME, and say what it must do.")
            break
        if _hot >= REWRITE_LIMIT:
            log(f"Same file written {_hot} times ({_worst}) — stopping the rewrite loop", "error")
            agent_activity(req_id, "stopped", "rewrite loop",
                           f"{Path(_worst).name} written {_hot}x", ok=False)
            _files = _written_paths(all_tool_calls + [
                {"tool": c["name"], "path": (c.get("arguments") or {}).get("path")}
                for c in calls])
            clear_rewrites(session_id)
            if _scope_by_user:
                # One file was asked for, so "move on to the next file" is false,
                # and the last write is not "the most complete" -- it may be the
                # original plus one small change. Say what is actually known.
                final = (f"STOPPED - the model rewrote {Path(_worst).name} {_hot} times "
                         f"without finishing.\n\n"
                         f"The request is probably NOT done. The file on disk is whatever "
                         f"the last write left, which may be only part of the change. "
                         f"Compare it with the original in .nd_backups before running it.\n\n"
                         f"A run check below, if there is one, only says the file still "
                         f"RUNS - not that it does what was asked.")
            else:
                final = (f"STOPPED - the model kept rewriting the same file.\n\n"
                         f"{Path(_worst).name} was written {_hot} times instead of moving on "
                         f"to the next file. The last version on disk is the most complete "
                         f"one — but rewriting a file is not evidence that it WORKS. If a "
                         f"run check appears below, that is what says so.\n\n"
                         + ("Verified on disk:\n" + "\n".join(f"  - {w}" for w in _files)
                            if _files else
                            "Nothing from this run could be verified on disk — check the log for "
                            "write errors.")
                         + "\n\nThis is a small-model limit, not a bug in the request. It builds "
                         "one file well and loses the thread on the second. Ask for the next "
                         "file by name in a new message and it will do that one too.")
            break
        # ── Tiered permission gate ──
        # green: run. yellow: one OK per tool. red: one OK per exact call.
        # ADMIN MODE (or allow_all) waives all of it.
        # ── Autonomy level ──
        # "ask"        every yellow and red action is confirmed (original behaviour)
        # "trusted"    file writes / scripts run unattended; shell, installs,
        #              GUI control and phone actions still stop and ask
        # "autonomous" nothing stops except a hard-blocked destructive command
        #
        # This is what "keep working until there is a major update or a decision
        # has to be made" means in practice: red-tier calls ARE the decisions.
        # "auto" is the level chosen for unattended runs: nothing pauses for
        # approval. It is NOT unrestricted -- the hard blacklist below still
        # refuses outright to run a destructive command, at every level. That is
        # a refusal, not a prompt, so it cannot be waived by autonomy.
        autonomy = str(_config.get("agent_autonomy", "ask")).lower()
        if autonomy == "auto":
            autonomy = "autonomous"
        if autonomy not in ("ask", "trusted", "autonomous"):
            autonomy = "ask"
        auto_ok = {"ask": set(), "trusted": {"yellow"},
                   "autonomous": {"yellow", "red"}}[autonomy]

        def _needs_for(cs):
            """Which of these calls still lack permission. Called twice: once to
            ask, and once after the answer -- whatever is still unpermitted then
            was refused."""
            needs = []
            if admin_mode or allow_all:
                return needs
            for c in cs:
                t = _tier(c["name"])
                if t == "green":
                    continue
                if t in auto_ok:
                    # A hard-blocked command is never auto-approved, whatever the
                    # autonomy level says. Blacklisted means blacklisted.
                    if c["name"] == "run_shell" and \
                            classify_shell(c["arguments"].get("command", ""))[0] == "black":
                        pass
                    else:
                        log(f"Auto-approved {c['name']} ({t}) — autonomy={autonomy}", "info")
                        continue
                k = _perm_key(c["name"], c["arguments"])
                if k in pending_permissions or c["name"] in pending_permissions:
                    continue
                if t == "red":
                    detail = (c["arguments"].get("command")
                              or (f"{c['arguments'].get('manager','winget')} install "
                                  f"{c['arguments'].get('name','')}" if c["name"] == "install_app" else None)
                              or _summ(c["arguments"]))
                    warn = ""
                    if c["name"] == "run_shell":
                        bt, why = classify_shell(c["arguments"].get("command",""))
                        if bt == "black":
                            warn = f"HARD-BLOCKED: this {why}. Enable ADMIN MODE to allow it."
                    needs.append({"tool": c["name"], "arg": str(detail)[:400],
                                  "tier": "red", "key": k, "warning": warn,
                                  "scope": "this exact command only"})
                else:
                    needs.append({"tool": c["name"], "arg": (c.get("_arg") or _summ(c["arguments"])),
                                  "tier": "yellow", "key": k, "warning": "",
                                  "scope": "remembered for the rest of this chat"})
            return needs

        # ── Hard blacklist: refused, never offered ──
        # This runs BEFORE anyone is asked, and independently of the autonomy
        # level, which is the difference between a blacklist and a strongly
        # worded prompt. ADMIN MODE waives it (the warning text has always said
        # so); allow_all does not, because that flag comes from a client and
        # this list exists to survive a bad one.
        blocked_why = {}
        if not admin_mode:
            for c in calls:
                if c["name"] != "run_shell":
                    continue
                bt, bwhy = classify_shell(c["arguments"].get("command", ""))
                if bt == "black":
                    blocked_why[_perm_key(c["name"], c["arguments"])] = bwhy
        if blocked_why:
            for bwhy in sorted(set(blocked_why.values())):
                log(f"REFUSED run_shell — {bwhy}. Not asking; blacklisted at every "
                    f"autonomy level.", "warn")
            agent_activity(req_id, "stopped", "blocked",
                           "; ".join(sorted(set(blocked_why.values())))[:90], ok=False)

        # A one-file request: a shell command that writes, moves, copies or
        # deletes files is a way AROUND the scope, not a step within it. Measured
        # 2026-09-25: refused a write to set_location_fixed.py, the model tried
        # mkdir + cp + mv to get the same file into place, and the user was asked
        # to approve those three times. Refused here, before anyone is asked.
        scope_blocked = {}
        if _scope_by_user and only_file:
            for c in calls:
                if c["name"] == "run_shell" and shell_changes_files(
                        c["arguments"].get("command", "")):
                    scope_blocked[_perm_key(c["name"], c["arguments"])] = True
            if scope_blocked:
                log(f"Refused {len(scope_blocked)} file-changing shell command(s): the "
                    f"request changes only {Path(only_file).name}. Not asking.", "warn")
        blocked_why.update({k: "changes files outside the one-file scope"
                            for k in scope_blocked})
        needs = [n for n in _needs_for(calls) if n["key"] not in blocked_why]
        # Anything the user already refused in this run is blocked again on the
        # spot, without asking. Measured: denied once, the model re-issued the
        # identical write_file and parked the turn on the same question a second
        # time. One refusal is an answer for the whole turn.
        auto_keys = {n["key"] for n in needs if n["key"] in refused_keys}
        needs = [n for n in needs if n["key"] not in refused_keys]
        denied_keys = set(auto_keys) | set(blocked_why)
        # A blacklisted call must not be retried either -- refused_keys is what
        # stops the model reissuing the identical command for the rest of the turn.
        refused_keys |= set(blocked_why)
        if auto_keys:
            log(f"Re-blocked {len(auto_keys)} call(s) already refused this turn "
                f"- not asking again", "warn")
            agent_activity(req_id, "stopped", "already refused",
                           "blocked again without asking", ok=False)
        if needs:
            decision = _ask_permission(needs)
            if decision is None:
                # No req_id, so nobody is listening: keep the old contract.
                return {
                    "final_response": content_clean,
                    "tool_calls": [{"tool": c["name"], "arg": _summ(c["arguments"])} for c in calls],
                    "needs_permission": needs,
                    "pending_response": content_clean
                }
            if decision["cancelled"]:
                log("Chat cancelled while it was waiting for approval", "info")
                return {"final_response": final or "[cancelled]",
                        "tool_calls": all_tool_calls, "tool_results": all_tool_results,
                        "needs_permission": None}
            pending_permissions |= decision["approved"]
            # Whatever is STILL unpermitted was refused (or the ask timed out).
            # Do not run it, and do not end the turn either: tell the model, which
            # is strictly better than the old behaviour of returning and making
            # the UI inject a synthetic "I denied that" user message.
            refused = [n for n in _needs_for(calls)
                       if n["key"] not in auto_keys and n["key"] not in blocked_why]
            denied_keys |= {n["key"] for n in refused}
            refused_keys |= {n["key"] for n in refused}
            if refused:
                agent_activity(req_id, "stopped", "permission denied",
                               ", ".join(sorted({n["tool"] for n in refused}))[:90], ok=False)
        _set_status("tools", "Round %d: %s" % (rnd, ", ".join(c["name"] for c in calls[:4])), 75)
        results = []
        for c in calls:
            _pk = _perm_key(c["name"], c["arguments"])
            if _pk in denied_keys:
                denied_record.append({"tool": c["name"],
                                      "path": _arg_path(c["arguments"]) or "",
                                      "arg": _summ(c["arguments"])})
                if _pk in scope_blocked:
                    results.append({"tool": c["name"], "arg": _summ(c["arguments"]),
                                    "result": (
                        "[BLOCKED] This request changes only one file:\n"
                        f"  {only_file}\n"
                        "so shell commands that create, copy, move, rename or delete "
                        "files are refused - nobody was asked and nothing ran. Do not "
                        "build the file somewhere else and move it into place.\n\n"
                        "Change the file directly: edit_file on it, or write_file with "
                        "its COMPLETE new content. Then finish and say what changed.")})
                    continue
                if _pk in blocked_why:
                    # Distinct from a user refusal on purpose: the user was never
                    # asked, so "the user refused" would be a lie the model then
                    # repeats back to them.
                    results.append({"tool": c["name"], "arg": _summ(c["arguments"]),
                                    "result": "[BLOCKED] This command " + blocked_why[_pk]
                                              + ", and NeuralDock refuses it outright. Nobody was "
                                                "asked, so do not say permission was denied and do "
                                                "not ask for approval -- there is no approval that "
                                                "would allow it. Nothing ran and nothing changed. "
                                                "Do not retry it, rephrase it, or route around it "
                                                "with another tool. Tell the user plainly that this "
                                                "command is blocked, then carry on with what you "
                                                "can do without it."})
                    continue
                if _pk in auto_keys:
                    # It already ignored one refusal. Saying the same thing again
                    # in the same words is what let it loop in the first place.
                    results.append({"tool": c["name"], "arg": _summ(c["arguments"]),
                                    "result": "[DENIED AGAIN] You already tried this and the "
                                              "user refused. It was blocked without asking them "
                                              "a second time. STOP retrying it - it cannot "
                                              "succeed in this turn, no matter how you rephrase "
                                              "it. Nothing was written. Answer the user now, "
                                              "saying plainly that permission was refused."})
                    continue
                results.append({"tool": c["name"], "arg": _summ(c["arguments"]),
                                # Measured on frontend-design-expert-8b: handed a bare
                                # refusal it answered "I already created a denial
                                # placeholder ... the work is complete and verified".
                                # A denial has to say what did NOT happen, or a small
                                # model fills the gap with a success story.
                                "result": "[DENIED] The user refused permission, so this call did "
                                          "NOT run and nothing on disk changed. Do not attempt it "
                                          "again and do not look for a way around it. You have NOT "
                                          "done this work: never tell the user it is done, created, "
                                          "written or verified. Say plainly that permission was "
                                          "refused, then carry on with whatever you can do without "
                                          "it."})
                continue
            c["arguments"], _argnote = clean_tool_args(c.get("arguments"))
            if _argnote:
                log(f"{c['name']}: {_argnote}", "warn")
            key = (c["name"], json.dumps(c["arguments"], sort_keys=True, default=str))
            # Re-reading a file that has been WRITTEN since it was last read is not
            # a repeat: the old result is stale. Measured 2026-09-25: an edit
            # changed set_location.py, the model's next edit (from the old text)
            # missed, it asked to re-read the file, and was told "ALREADY DONE -
            # that result is still above" -- the OLD file. With no way to see the
            # file as it now was, it stalled, and the job was reported as a
            # rewrite loop.
            _rp = ((c.get("arguments") or {}).get("path")
                   if c["name"] == "read_file" else None)
            _stale = bool(_rp and key in _seen_seq
                          and _write_seq.get(_path_key(_rp), -1) > _seen_seq[key])
            if _stale:
                log(f"Re-reading {Path(str(_rp)).name}: it was written since it was "
                    "last read, so the earlier result is out of date", "info")
            # Repeating a screenshot or a click is legitimate - the screen changed.
            repeatable = c["name"] in ("screen_capture", "gui_action") or _stale
            if c["name"] == "screen_capture":
                shots_taken += 1
                if shots_taken > MAX_SHOTS:
                    results.append({"tool": c["name"], "arg": "", "result":
                        (f"[You have taken {shots_taken-1} screenshots this turn and the picture is not "
                         "changing. Looking again will not help. Either act on what you already saw, or "
                         "stop and tell the user what you can see and what you need from them.]")})
                    log("screen_capture cap reached - forcing a decision", "warn")
                    continue
            if key in seen_calls and repeatable:
                del seen_calls[key]
            # Did WE throw this result away? Then the repeat is recovery, not a
            # loop, and it must not push the model toward the breaker.
            _evicted = bool(key in seen_calls and key in seen_results
                            and not result_still_visible(convo, seen_results[key]))
            # Cross-turn tally: this survives permission approvals, which is where
            # the old guard lost track and let the same command run six times.
            n_seen = (1 if (repeatable or _evicted)
                      else note_session_call(session_id, c["name"], c["arguments"]))
            if n_seen >= STUCK_AFTER:
                stuck_hits[key] = stuck_hits.get(key, 0) + 1
                _hit = stuck_hits[key]
                # A turn was already ended for this exact call earlier in the
                # session. Do not re-run the whole escalation ladder -- the model
                # has had it, and a repair pass starting a fresh turn is not a
                # reason to spend three more refusals making the same point.
                if seen_session_giveup(session_id, c["name"], c["arguments"]):
                    _hit = STUCK_GIVE_UP
                if _hit >= STUCK_GIVE_UP:
                    # Told to stop three times and still repeating. Spending the
                    # rest of the round budget re-refusing it helps nobody.
                    _gv = note_session_giveup(session_id, c["name"], c["arguments"])
                    stuck_stop = (c["name"], _summ(c["arguments"]), n_seen, _gv)
                    log(f"Tool {c['name']}: refused {_hit} times and still repeating "
                        f"- ending the turn (give-up #{_gv} this session)", "error")
                    agent_audit(c["name"], "meta", _summ(c["arguments"]),
                                f"GAVE UP after {n_seen}")
                    break
                # A second identical refusal reads as the same wall. Say something
                # different, and name the loop explicitly.
                _extra = ("" if _hit == 1 else
                          NL + "This is the " + ("second" if _hit == 2 else str(_hit) + "th")
                          + " time you have been told this about this exact call. "
                          "You are in a loop. Do not issue it again in any form - "
                          "pick a DIFFERENT action, or stop and report.")
                stuck_msg = (
                    f"[STOP — you have now issued this exact {c['name']} call {n_seen} times and it has "
                    "not moved the task forward. It was NOT run again.\n"
                    "Repeating it will not work. Do ONE of these instead:\n"
                    "  1. Verify the real state a different way (screen_capture and LOOK, or query with "
                    "Get-Process / Test-Path) and adapt based on what you actually see.\n"
                    "  2. Try a genuinely different approach.\n"
                    "  3. If you are out of ideas, STOP and tell the user plainly what you tried, what "
                    "happened, and exactly what you need from them. Asking for help is the correct move "
                    "here — do not keep looping.]" + _extra)
                results.append({"tool": c["name"], "arg": _summ(c["arguments"]), "result": stuck_msg})
                log(f"Tool {c['name']}: STUCK after {n_seen} identical calls - forcing a rethink", "warn")
                agent_audit(c["name"], "meta", _summ(c["arguments"]), f"STUCK x{n_seen}")
                continue
            if key in seen_calls:
                if _evicted and reserves.get(key, 0) < RESERVE_LIMIT:
                    # ND deleted this result, not the model. Hand it back rather
                    # than telling the model to consult something it cannot see.
                    reserves[key] = reserves.get(key, 0) + 1
                    r = (f"[Served again from this turn's cache. You DID call "
                         f"{c['name']} with these arguments in round {seen_calls[key]}, "
                         f"but the result was compacted out of the window to save "
                         f"room, so asking again was reasonable. Here it is — use it "
                         f"now, because it may be compacted again.]" + NL
                         + str(seen_results.get(key) or ""))
                    log(f"Tool {c['name']}: result was compacted away — re-served "
                        f"from cache instead of refusing", "warn")
                    agent_activity(req_id, "tool", c["name"],
                                   _activity_target(c["arguments"]),
                                   ok=True)
                else:
                    # identical call already ran - returning it again just burns rounds
                    r = (f"[ALREADY DONE in round {seen_calls[key]} - that result is still "
                         f"above in this conversation. "
                         f"Do NOT call {c['name']} with these arguments again. "
                         f"Either request different arguments (e.g. a later offset) or give your final answer now.]")
                    log(f"Tool {c['name']}: duplicate suppressed", "warn")
            else:
                seen_calls[key] = rnd
                _t_tool = _time.time()
                agent_activity(req_id, "tool", c["name"], _activity_target(c["arguments"]))
                r = _exec_one(c["name"], c["arguments"])
                _a = _summ(c["arguments"])
                log(f"Tool {c['name']}: {_a if len(_a) < 118 else _a[:115] + '...'}", "info")
                _bad = str(r).lstrip().startswith("[ERROR") or "VERIFY FAILED" in str(r)
                c["_ok"] = not write_result_failed(r)
                _op_seq += 1
                _seen_seq[key] = _op_seq
                if c["name"] in WRITE_TOOLS and c["_ok"]:
                    _wpk = _path_key((c.get("arguments") or {}).get("path"))
                    if _wpk:
                        _write_seq[_wpk] = _op_seq
                agent_activity(req_id, "done", c["name"], _activity_target(c["arguments"]),
                               ok=not _bad, secs=_time.time() - _t_tool)
                # Cache it so a later identical call can be answered from here
                # when compaction has taken the original out of the window.
                seen_results[key] = r
                # A real tool ran, so the no-progress patience resets.
                clear_no_progress(session_id)
                # Ledger the action so the NEXT turn knows this already happened.
                note_session_work(session_id, c["name"], c["arguments"], r)
                # Track pages and their reviews so the loop can refuse to finish
                # while something it wrote has never been looked at.
                _ap = str((c.get("arguments") or {}).get("path") or "")
                if c["name"] in WRITE_TOOLS:
                    note_page(session_id, _ap)
                elif c["name"] == "design_review" and not str(r).startswith("[design_review"):
                    note_reviewed(session_id, _ap,
                                  getattr(_job_ctx, "last_contrast", ""),
                                  getattr(_job_ctx, "last_layout", ""))
                    _job_ctx.last_contrast = _job_ctx.last_layout = ""
            results.append({"tool": c["name"], "arg": _summ(c["arguments"]), "result": r})
        if stuck_stop:
            _sname, _sarg, _sn, _sgv = stuck_stop
            all_tool_calls.extend([{"tool": c["name"], "arg": _summ(c["arguments"]),
                                    "path": (c.get("arguments") or {}).get("path"),
                                    "failed": _call_failed(c)}
                                   for c in calls])
            all_tool_results.extend(results)
            # Only writes that CHANGED something. Measured 2026-09-25: four failed
            # edits and two refused writes were listed as "Work that did land".
            _w = [t for t in all_tool_results if t["tool"] in ("write_file", "edit_file")
                  and not write_result_failed(t.get("result"))]
            # "Nothing was written" is true of this turn and false of the
            # session -- and the session is what the user is looking at.
            _session_files = session_work_files(session_id)
            final = ("STOPPED — the model got stuck repeating one call and would not "
                     "move on." + NL + NL
                     + "It issued this exact call " + str(_sn) + " times:" + NL
                     + "    " + _sname + "  " + str(_sarg)[:120] + NL + NL
                     + "The first " + str(max(1, STUCK_AFTER - 1)) + " ran and returned a "
                     "result; the repeats after that were blocked, with an explanation "
                     "and three suggested alternatives, and it kept issuing it anyway. "
                     "The turn was ended rather than spending the rest of the round "
                     "budget on it."
                     + NL + NL
                     + ("Work that did land first:" + NL
                        + NL.join("  - " + t["tool"] + "  " + str(t["arg"])[:90] for t in _w[-6:])
                        if _w else "Nothing was written in this turn.")
                     + ((NL + NL + "Earlier in this session it did produce:" + NL
                         + NL.join("  - " + p for p in _session_files[-8:]))
                        if _session_files else "")
                     + NL + NL
                     + ("This is a small-model failure mode, not a bad request. Asking "
                        "again with a narrower, more specific instruction usually clears "
                        "it — name the file and the exact change you want."
                        if _sgv <= 1 else
                        "This is the " + str(_sgv) + ("nd" if _sgv == 2 else "rd" if _sgv == 3
                        else "th") + " time this session that a turn has been ended for this "
                        "same call, so re-running the request as written will not help. "
                        "Change the request: name the exact file and edit you want, or split "
                        "it into a smaller step."))
            break
        # `arg` is a 120-char JSON dump for display. `path` is the real argument,
        # kept separately because the dead-end report needs to STAT the file, and
        # a truncated dump of {"path":..,"content":..} cannot be stat'd.
        all_tool_calls.extend([{"tool": c["name"], "arg": _summ(c["arguments"]),
                                "path": (c.get("arguments") or {}).get("path"),
                                "failed": _call_failed(c)}
                               for c in calls])
        all_tool_results.extend(results)
        convo.append({"role": "assistant", "content": content})
        left = MAX_ROUNDS - rnd
        if left <= 2:
            budget = (f"\n\nBUDGET WARNING: only {left} tool round(s) remain. "
                      "Stop gathering information and write your final answer NOW using what you already have.")
        else:
            budget = f"\n\n({left} tool rounds remain.)"
        if native:
            for r_ in results:
                # 30000 chars per tool result was ~7.5k tokens EACH. Three of
                # those overflowed a 32k window on their own, before the system
                # prompt, the memory block or the conversation. Generation then
                # crawls and the model has no room to reason about what it read.
                convo.append({"role": "tool",
                              "content": clip_tool_result(r_["result"], TOOL_RESULT_CHARS)})
            nxt = {"role": "user", "content": "Continue. Call more tools if needed; otherwise give your final answer now. If a result says VERIFY FAILED, fix it first." + budget + plan_block(session_id)}
        else:
            ctx = "\n\n".join([f"[Tool result for {r_['tool']} {r_['arg'][:80]}]:\n"
                               + clip_tool_result(r_['result'], TOOL_RESULT_CHARS) for r_ in results])
            nxt = {"role": "user", "content": f"Tool results:\n{ctx}\n\nIf you still need more information request it with TOOL: lines. Otherwise give your final answer to the user now. If a result says VERIFY FAILED, fix it first with TOOL:edit_file." + budget + plan_block(session_id)}
        if pending_images:
            if model_has_vision(model):
                # the model has eyes - hand it the real pixels
                nxt["images"] = pending_images[-2:]
                nxt["content"] = "Here is the screen you just captured.\n" + nxt["content"]
            else:
                # Text-only model: attaching an image makes Ollama 400. Get the
                # vision specialist to put the screen into words instead.
                _set_status("tools", "Reading the screenshot with the vision model…", 70)
                desc = describe_screenshot(pending_images[-1])
                nxt["content"] = ("You cannot see images, so the vision model looked at your "
                                  "screenshot for you:\n\n" + desc + "\n\n" + nxt["content"])
            pending_images = []
        convo.append(nxt)
        _compact_convo()
        if rnd == MAX_ROUNDS:
            # out of rounds: ask for a summary from what was gathered instead of
            # returning a dangling "let me continue reading..."
            _set_status("finalizing", "Round budget reached - forcing a summary…", 92)
            convo.append({"role": "user", "content":
                "You are out of tool rounds. Do NOT call any more tools. "
                "Summarize what you found and answer the user's original question now, "
                "noting explicitly anything you could not finish examining."})
            forced = ollama_chat(model, convo, status_cb=cb, clean=False, text_cb=_stream)
            forced = strip_tool_lines(clean_ai_response(_strip_xml_calls(forced)))
            final = forced or content_clean
    if not final:
        # This used to paste the last four raw tool results into the chat. On a
        # run that had just read two 1200-line pages of a 194KB file, that meant
        # a screenful of somebody's HTML source presented as if it were an
        # answer. It told the user nothing about what went wrong.
        if all_tool_results:
            did = []
            for tr in all_tool_results[-8:]:
                mark = "x" if str(tr["result"]).lstrip().startswith("[") and \
                    ("not found" in tr["result"][:80] or "error" in tr["result"][:80].lower()) else "-"
                did.append(f"  {mark} {tr['tool']}  {str(tr['arg'])[:90]}")
            wrote = [t for t in all_tool_results if t["tool"] in ("write_file", "edit_file")]
            exhausted = rounds_used >= MAX_ROUNDS

            # Say WHICH of the two things happened. The earlier version always
            # claimed the round budget was exhausted and printed MAX_ROUNDS
            # rather than the rounds actually used -- so a run that stopped after
            # 8 rounds because the model went silent reported "used its whole
            # round budget across 24 rounds", which was simply untrue.
            if exhausted:
                head = ("STOPPED - the model ran out of tool rounds before writing an answer.\n\n"
                        f"It used all {rounds_used} of its {MAX_ROUNDS} rounds")
                why = ("This usually means it spent the budget reading instead of building. "
                       "Large files are the usual cause: one page of a big file can fill most "
                       "of the context window, leaving no room to reason.\n\n"
                       "Try:\n"
                       "  - Tell it which file and which part to look at, rather than letting it explore\n"
                       "  - Ask for one output file at a time\n"
                       "  - Raise agent_max_rounds in the config")
            else:
                head = ("STOPPED - the model returned an empty reply, so there was nothing to show.\n\n"
                        f"It stopped on round {rounds_used} of {MAX_ROUNDS} - the budget was NOT the limit")
                why = ("An empty reply after successful tool calls usually means the model had "
                       "nothing left to say but did not say so. The work it already did is listed "
                       "above and is real - check those files before re-running.\n\n"
                       "Try:\n"
                       "  - Ask it to continue, or to summarise what it just built\n"
                       "  - If this repeats, the model may be struggling with the tool format - "
                       "try a different one")
            final = (
                head
                + (f", made {len(all_tool_calls)} tool call(s), "
                   + (f"including {len(wrote)} file write(s)." if wrote
                      else "and did NOT create or change any file.")) + "\n\n"
                "What it actually did:\n" + "\n".join(did) + "\n\n" + why)
        else:
            final = (f"[No response - the model returned nothing and made no tool calls "
                     f"in {rounds_used} round(s).]")

    # Ground truth beats the model's account of itself. A refused call did not
    # run, whatever the reply says about it.
    if denied_record:
        _real = [t for t in all_tool_results
                 if not str(t.get("result") or "").lstrip().startswith("[DENIED]")]
        _false = claims_refused_work(final, denied_record, nothing_succeeded=not _real)
        if _false:
            log("Model claimed work that was refused: "
                + ", ".join(f"{h['tool']} {h.get('path') or ''}".strip() for h in _false)
                + " - appending a correction", "warn")
            agent_activity(req_id, "stopped", "false success claim",
                           "reply claimed refused work was done", ok=False)
            final = final.rstrip() + refused_work_note(_false)
    # -- Integration gate ----------------------------------------------------
    # Everything else in this file verifies files ONE AT A TIME, and the
    # contradiction that matters lives BETWEEN them. Measured on T2 across six
    # runs, 2026-09-05: every per-file check passed 6/6 -- a real model, a real
    # schema, a router with routes -- while "they import together" sat at 2/6.
    # The four failures were all contract errors (SQLAlchemy Mapped[], a FastAPI
    # response-field type, pydantic regex -> pattern, a Session as a response
    # field): every one surfaces on a real import, and none survives being shown
    # its own traceback.
    #
    # Only on a TOP-LEVEL turn. allow_split is already False for the auto-split
    # path's per-file calls and for the repair pass below, which is what stops
    # this recursing into itself.
    if BUILD_IMPORT_GATE and allow_split and workspace and not denied_record:
        _built = _existing_py(_gate_py)
        # Say so every time, including when there is nothing to do. A gate that
        # is silent when idle and silent when broken cannot be told apart, and
        # this one ran inert through two live runs looking exactly like a pass.
        log(f"Integration gate: {len(_built)} python file(s) written this turn"
            + ("" if len(_built) >= 2 else " - not checking, needs 2+"), "info")
        _gate_record(req_id, "imports", path="tool_loop", checked=len(_built),
                     ran=(len(_built) >= 2))
        if len(_built) >= 2:
            _ok, _detail, _mods = _imports_together(_built, workspace)
            _gate_record(req_id, "imports", fired=(_ok is False),
                         provable=(_ok is not None), repair_passes=0,
                         imports_ok=(_ok is True), repaired=False)
            _tries = 0
            while _ok is False and _tries < BUILD_IMPORT_REPAIRS:
                _tries += 1
                _first = _detail.splitlines()[-1][:90] if _detail else "import failed"
                log(f"Build does not import together - {_first}", "warn")
                agent_activity(req_id, "retry", "imports together", _first, ok=False)
                clear_rewrites(session_id)   # see the note in try_build_plan
                try:
                    _fix = process_ai_response_with_tools(
                        model,
                        [{"role": "user",
                          "content": _import_repair_prompt(_built, _mods, _detail)}],
                        workspace=workspace, allow_all=allow_all, req_id=req_id,
                        should_cancel=should_cancel, agent_mode=agent_mode,
                        session_id=session_id, allow_split=False)
                    all_tool_calls += _fix.get("tool_calls") or []
                    all_tool_results += _fix.get("tool_results") or []
                except Exception as _e:
                    log(f"Import repair failed: {_e}", "error")
                    break
                _ok, _detail, _mods = _imports_together(_built, workspace)
                _after = (_detail.splitlines()[-1][:90] if _detail else "clean")
                log(f"After repair {_tries}/{BUILD_IMPORT_REPAIRS} - {_after}",
                    "ok" if _ok is True else "warn")

            if _ok is True:
                agent_activity(req_id, "done", "imports together",
                               "repaired" if _tries else "verified", ok=True)
                _gate_record(req_id, "imports", repair_passes=_tries,
                             imports_ok=True, repaired=bool(_tries))
                if _tries:
                    final = final.rstrip() + ("\n\nThey did not import together at "
                        "first; one repair pass fixed it. All " + str(len(_mods)) +
                        " modules now import in one interpreter.")
            elif _ok is False:
                agent_activity(req_id, "done", "imports together",
                               "still failing", ok=False)
                _gate_record(req_id, "imports", repair_passes=_tries, imports_ok=False, repaired=False)
                final = final.rstrip() + ("\n\nThese files do NOT import together" +
                    (" even after a repair pass" if _tries else "") + ":\n\n" +
                    _detail + "\n\nThey are on disk, but the package will not load "
                    "as written.")

    # ── Run gate ──────────────────────────────────────────────────────────
    # See run_gate_check. A new script that was never executed is the single
    # biggest source of "it said it worked and it does not".
    # A stuck stop (one call refused over and over) used to skip the gate, so any
    # script written before it went out unchecked. It is now CHECKED and reported,
    # just not repaired -- repairing would restart the loop that was just stopped.
    if (_config.get("agent_run_gate", True) and allow_split
            and not (pending_permissions or None)):
        try:
            _rg_inputs = _run_gate_inputs(_last_user, workspace)
            _rg_max = 0 if stuck_stop else RUN_GATE_REPAIRS
            for _rg_path in _written_paths(all_tool_calls):
                _rg_file = str(_rg_path).split(" (")[0]
                if not _rg_file.lower().endswith(".py"):
                    continue
                if not _is_script(_rg_file):
                    continue
                _rg_fail = run_gate_check(_rg_file, workspace, _rg_inputs)
                if not _rg_fail:
                    _n_rules = len(workspace_run_rules(workspace, _rg_file))
                    log(f"Run gate: {Path(_rg_file).name} passed"
                        + (f" ({_n_rules} project rule(s) checked)" if _n_rules else ""),
                        "ok")
                _rg_tries = 0
                while _rg_fail and _rg_tries < _rg_max:
                    _rg_tries += 1
                    log(f"Run gate: {Path(_rg_file).name} {_rg_fail[:70]} — "
                        f"repair {_rg_tries}/{RUN_GATE_REPAIRS}", "warn")
                    agent_activity(req_id, "file", Path(_rg_file).name,
                                   f"does not run — fixing {_rg_tries}/{RUN_GATE_REPAIRS}")
                    _rg = process_ai_response_with_tools(
                        model, [{"role": "user", "content":
                                 _run_gate_prompt(_rg_file, _rg_fail, _last_user)}],
                        workspace=workspace, allow_all=allow_all, req_id=req_id,
                        should_cancel=should_cancel, agent_mode=agent_mode,
                        session_id=session_id, allow_split=False, only_file=_rg_file)
                    all_tool_calls.extend(_rg.get("tool_calls") or [])
                    all_tool_results.extend(_rg.get("tool_results") or [])
                    _rg_fail = run_gate_check(_rg_file, workspace, _rg_inputs)
                    if should_cancel and should_cancel():
                        break
                _gate_record(req_id, "run", file=Path(_rg_file).name,
                             repair_passes=_rg_tries, ok=not _rg_fail)
                _todo = getattr(_job_ctx, "gui_unimplemented", None) or []
                if _todo and not _rg_fail:
                    final = (final or "").rstrip() + (
                        NL + NL + "─────────────────────────────" + NL
                        + f"I click-tested {Path(_rg_file).name}. Nothing crashes now, but "
                        + f"{len(_todo)} button(s) do nothing yet — their handlers are "
                          "empty stubs:" + NL + NL.join("  - " + t for t in _todo) + NL
                        + "Those are unbuilt features, not bugs. Ask for them by name "
                          "when you want them implemented.")
                    _job_ctx.gui_unimplemented = []
                _notes = getattr(_job_ctx, "run_gate_notes", None) or []
                if _notes and not _rg_fail:
                    final = (final or "").rstrip() + (
                        NL + NL + "─────────────────────────────" + NL
                        + "NOTE (not a failure): " + (NL + NL).join(_notes))
                _job_ctx.run_gate_notes = []
                if _rg_fail:
                    agent_activity(req_id, "done", Path(_rg_file).name,
                                   "still does not run", ok=False)
                    final = (final or "").rstrip() + (
                        NL + NL + "─────────────────────────────" + NL
                        + f"I RAN {Path(_rg_file).name}. It " + _rg_fail + NL + NL
                        + (f"{_rg_tries} repair pass(es) did not fix it. "
                           if _rg_tries else
                           ("ND had already stopped this job, so no repair was tried. "
                            if stuck_stop else ""))
                        + "The file is on disk but it does NOT work. Treat the code "
                          "above as a draft, not a result.")
                elif _rg_tries:
                    log(f"Run gate: {Path(_rg_file).name} fixed after "
                        f"{_rg_tries} pass(es)", "ok")
                    agent_activity(req_id, "done", Path(_rg_file).name,
                                   f"runs clean after {_rg_tries} fix(es)", ok=True)
                    final = (final or "").rstrip() + (
                        NL + NL + f"[{Path(_rg_file).name} did not run as first "
                        f"written. It was executed, the failure was fed back, and "
                        f"{_rg_tries} repair pass(es) later it runs clean.]")
        except Exception as _rge:
            log(f"Run gate skipped: {_rge}", "warn")

    _written_now = _written_paths(all_tool_calls)
    # Last line of defence against a fabricated write. Not a heuristic about
    # what the model meant -- it stats the paths the reply says it created. A
    # path that is not on disk was not written, and the user must not be told
    # otherwise. Measured on req_muaphc73: five .md files claimed in the vault,
    # none of them real, presented as an ordinary successful reply.
    try:
        _ghosts = unverified_write_claims(final)
    except Exception:
        _ghosts = []
    _moved = _write_redirects.pop(req_id, [])
    if _moved:
        final = (final or "").rstrip() + (
            NL + NL + "─────────────────────────────" + NL
            + "WRITES WERE REDIRECTED. Writes are confined to the working "
              "directory, so these did not go where they were addressed:" + NL
            + NL.join(f"  asked: {b}" + NL + f"  wrote: {c}" for b, c in _moved)
            + NL + NL + "Set the workspace to the folder you want, or turn off "
              "`agent_confine_writes` in the config, then ask again.")
    if _ghosts:
        log(f"Reply claims {len(_ghosts)} file(s) that are not on disk", "error")
        agent_activity(req_id, "warn", f"{len(_ghosts)} claimed file(s) missing",
                       "reply says written, disk says no", ok=False)
        # WHY each one is missing. Measured 2026-09-25: both "ghosts" were real
        # write_file calls that ND had REFUSED (wrong file for a one-file
        # request), and this note blamed the model for "writing the call out as
        # text" -- the wrong cause, and so the wrong advice.
        _refused = {_path_key(r.get("path")) for r in all_tool_calls
                    if r.get("failed") and r.get("path")}
        _was_refused = [g for g in _ghosts if _path_key(g) in _refused]
        _as_text = [g for g in _ghosts if g not in _was_refused]
        final = (final or "").rstrip() + (
            NL + NL + "─────────────────────────────" + NL
            + "CHECKED ON DISK: the reply above says these were written. They do "
              "NOT exist:" + NL
            + NL.join("  - " + g for g in _ghosts) + NL
            + ((NL + "ND REFUSED or could not complete the write to: "
                + ", ".join(Path(g).name for g in _was_refused)
                + ". The reason is in that tool call's result - nothing was saved.")
               if _was_refused else "")
            + ((NL + "Never attempted: " + ", ".join(Path(g).name for g in _as_text)
                + ". The tool call was written out as text instead of being made, so "
                  "ND never ran it. Ask again and say: \"use the write_file tool, one "
                  "file per message\".")
               if _as_text else ""))
    # A page and its scripts must agree, however the page got written (pair 7:
    # the page came from the ordinary loop, so the build's check never ran).
    try:
        # ... and on a follow-up turn, which may write no page at all (pair 10:
        # the page came from a turn that timed out, so no check ever saw it).
        if (allow_split and workspace and req_id and _config.get("agent_page_check", True)
                and (any(str(w).lower().endswith((".html", ".htm", ".js", ".mjs"))
                         for w in (_written_now or []))
                     or is_followup(_last_user))):
            final = (final or "").rstrip() + repair_pages(
                model, workspace, req_id, session_id, allow_all, should_cancel, agent_mode)
            final = final + repair_serving(
                model, workspace, req_id, session_id, allow_all, should_cancel, agent_mode)
    except Exception as _pce:
        log(f"page check skipped: {_pce}", "warn")
    # A turn that leaves passing tests broken is undone (Elena Live pair 5: a
    # follow-up took a 20/21 build to 7/21 and nothing put it back).
    try:
        if (allow_split and req_id and workspace and SUITE_GATE
                and _config.get("agent_turn_revert", True) and _suite_state.get("base")):
            _rb = _suite_regressions(_suite_state["base"], workspace)
            if _rb:
                _orig = _originals_peek(req_id)
                _put = []
                for _f, _body in _orig.items():
                    try:
                        Path(_f).write_text(_body, encoding="utf-8")
                        _put.append(Path(_f).name)
                    except OSError as _we:
                        log(f"Turn revert: could not restore {Path(_f).name}: {_we}", "error")
                with _lock:
                    _new = sorted(Path(x).name for x in (_created_by_req.get(req_id) or set()))
                _after = _suite_regressions(_suite_state["base"], workspace)
                log(f"Turn revert: {_rb[:100]} - restored {len(_put)} file(s)"
                    + (" - suite green again" if not _after else " - STILL broken"), "warn")
                agent_activity(req_id, "done", "turn undone",
                               f"{len(_put)} file(s) put back", ok=False)
                _gate_record(req_id, "turn_revert", restored=len(_put),
                             created_kept=len(_new), green_after=not _after)
                final = (final or "").rstrip() + (
                    NL + NL + "─────────────────────────────" + NL
                    + "UNDONE. This turn's edits broke tests that were passing before it:" + NL
                    + _rb[:700] + NL + NL
                    + (f"Put back: {', '.join(_put)}." if _put else "No edited file to put back.")
                    + (f" Files this turn created were left in place: {', '.join(_new)}." if _new else "")
                    + (" The tests are back to how they were." if not _after
                       else " Some tests are STILL failing - something outside these files changed.")
                    + NL + "Ask again with a narrower change, or say to keep it anyway.")
    except Exception as _tre:
        log(f"turn revert skipped: {_tre}", "warn")
    return {
        "final_response": final,
        "tool_calls": all_tool_calls,
        "tool_results": all_tool_results,
        "needs_permission": None,
        "files_written": _written_now,
        "next_actions": next_actions_for(final, session_id, _written_now),
        # The model that actually ran, after the picker, pins and routing -- which
        # is often NOT the one the request named. See run_chat_job.
        "model_used": model,
    }


# â”€â”€â”€ Git Clone + GGUF Pipeline â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def is_gguf_repo(repo_url):
    """Check if a HuggingFace repo URL points to a pre-converted GGUF repo."""
    url_lower = repo_url.lower()
    return any(x in url_lower for x in ["-gguf", "_gguf", ".gguf"])

def get_gguf_files_from_hf(repo_url):
    """
    List .gguf files in a HuggingFace repo via the API.
    Returns list of (filename, download_url) tuples.
    Falls back to constructed URL if API fails.
    """
    import re as _re
    m = _re.search(r"huggingface\.co/([^/\s]+/[^/\s]+)", repo_url.strip())
    if not m:
        log(f"Could not parse repo from URL: {repo_url}", "warn")
        return []
    repo_id = m.group(1).rstrip("/").rstrip(".git")
    log(f"Fetching file list for: {repo_id}", "info")

    api_url = f"https://huggingface.co/api/models/{repo_id}"
    try:
        req = urllib.request.Request(api_url,
            headers={"User-Agent": "NeuralDock/3.1"})
        hf_token = _config.get("hf_token","")
        if hf_token:
            req.add_header("Authorization", f"Bearer {hf_token}")
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        siblings = data.get("siblings", [])
        gguf_files = [
            (s["rfilename"],
             f"https://huggingface.co/{repo_id}/resolve/main/{s['rfilename']}")
            for s in siblings
            if s["rfilename"].lower().endswith(".gguf")
        ]
        log(f"Found {len(gguf_files)} GGUF files in {repo_id}", "info")
        for name, _ in gguf_files[:5]:
            log(f"  {name}", "info")
        return gguf_files
    except Exception as e:
        log(f"API file list failed: {e} -- will try to infer filename", "warn")
        return []

def git_clone_model(repo_url, dest_path, cb=None):
    """Clone a HuggingFace repo. For GGUF repos, lists files via API for user selection."""
    dest = Path(dest_path)

    if dest.exists() and any(dest.iterdir()):
        if (dest / "config.json").exists():
            log(f"HF model already exists at {dest} -- skipping clone", "info")
            return True, str(dest)
        # Check if .gguf files already downloaded
        gguf_files = list(dest.glob("*.gguf"))
        if gguf_files:
            log(f"GGUF file already exists: {gguf_files[0]}", "info")
            return True, str(dest)

    dest.mkdir(parents=True, exist_ok=True)

    # For GGUF repos: download directly via HF API (bypass git/LFS entirely)
    if is_gguf_repo(repo_url):
        log(f"Detected GGUF repo: {repo_url}", "info")
        if cb: cb("Fetching file list from HuggingFace API...")
        gguf_files = get_gguf_files_from_hf(repo_url)

        if gguf_files:
            # Score files: prefer Q8_0, Q4_K_M — avoid imatrix/special variants
            # unless that IS the repo type (like this IMatrix repo)
            def _score(fname):
                f = fname.lower()
                # Exact quantization preferences
                if "q8_0" in f:   return 0
                if "q4_k_m" in f: return 1
                if "q5_k_m" in f: return 2
                if "q6_k" in f:   return 3
                if "q4_0" in f:   return 4
                if "q2_k" in f:   return 9
                return 5
            gguf_files.sort(key=lambda x: _score(x[0]))
            chosen_name, chosen_url = gguf_files[0]
            log(f"Selected: {chosen_name} ({len(gguf_files)} files available)", "info")
            if cb: cb(f"Downloading {chosen_name} directly (no git clone)...")
            dest_file = dest / chosen_name
            ok = download_file(chosen_url + "?download=true", dest_file, chosen_name,
                               progress_key=getattr(threading.current_thread(), '_pipeline_job_id', None))
            if ok:
                log(f"GGUF downloaded: {dest_file}", "ok")
                return True, str(dest)
            else:
                log(f"Direct download failed, falling back to git clone", "warn")
                # Fall through to git clone below
        else:
            log("API returned no GGUF files, falling back to git clone", "warn")

    # Standard HF model: git clone
    ok_lfs, _, _ = run("git lfs version")
    if not ok_lfs:
        log("git-lfs not found, attempting to install...", "warn")
        run("winget install --id Git.Git -e --source winget")

    log(f"Cloning {repo_url} to {dest}...", "info")
    if cb: cb("Cloning repository (this may take a while for large models)...")

    # Use --depth 1 to skip history, much faster
    ok, out, err = run(
        f'git clone --depth 1 "{repo_url}" "{dest}"',
        timeout=7200  # 2 hours
    )
    if not ok:
        return False, f"Clone failed: {(err or out)[:300]}"

    # Pull LFS weights
    if cb: cb("Downloading model weights (LFS)...")
    log("Pulling LFS files...", "info")
    run(f'git -C "{dest}" lfs pull', timeout=7200)

    log(f"Clone complete: {dest}", "ok")
    return True, str(dest)

GGUF_DEPS = "gguf sentencepiece protobuf transformers torch numpy"
LLAMA_CPP_CONVERT_URL = "https://raw.githubusercontent.com/ggerganov/llama.cpp/master/convert_hf_to_gguf.py"
LLAMA_CPP_REQUIREMENTS_URL = "https://raw.githubusercontent.com/ggerganov/llama.cpp/master/requirements/requirements-convert_hf_to_gguf.txt"

def ensure_gguf_deps(cb=None):
    """Install all packages needed by convert_hf_to_gguf.py"""
    if cb: cb("Installing GGUF conversion dependencies...")
    log("Installing GGUF conversion dependencies...", "info")

    # CRITICAL: uninstall the rogue PyPI 'conversion' package.
    # Clear pip cache for it too so it can't be reinstalled from cache.
    run(f'"{VENV_PIP}" uninstall -y conversion')
    run(f'"{VENV_PIP}" cache remove conversion')
    log("Removed rogue conversion package and cleared cache", "info")

    # Install core packages needed by convert_hf_to_gguf.py
    venv_install("gguf", "gguf package")
    venv_install("sentencepiece", "sentencepiece")
    venv_install("protobuf", "protobuf")
    venv_install("numpy", "numpy")
    venv_install("transformers", "transformers")
    venv_install("torch --index-url https://download.pytorch.org/whl/cu128", "torch cu128")
    venv_install("accelerate", "accelerate")
    # Try to get exact requirements from llama.cpp
    # Skip requirements.txt approach - install packages individually instead
    # (requirements.txt has path issues on Windows and pulls in unwanted packages)
    log("GGUF deps ready", "ok")

def get_convert_script():
    """Download convert_hf_to_gguf.py from llama.cpp if not present."""
    convert_script = HERETIC_DIR / "convert_hf_to_gguf.py"
    if not convert_script.exists() or convert_script.stat().st_size < 1000:
        log("Downloading GGUF conversion script from llama.cpp...", "info")
        ok = download_file(LLAMA_CPP_CONVERT_URL, convert_script, "GGUF converter script")
        if not ok:
            return None
    return convert_script

def download_llama_cpp_tools(cb=None):
    """
    Download convert_hf_to_gguf.py and ALL required support files from llama.cpp.
    Returns (ok, script_path_or_error)
    """
    base_url  = "https://raw.githubusercontent.com/ggerganov/llama.cpp/master"
    tools_dir = HERETIC_DIR / "llama_tools"
    tools_dir.mkdir(parents=True, exist_ok=True)

    # Complete file list verified against actual llama.cpp repo structure
    CONVERSION_MODELS = [
        "qwen", "llama", "mistral", "gemma", "phi", "falcon", "gpt2",
        "starcoder", "bloom", "mpt", "baichuan", "internlm", "refact",
        "stablelm", "command_r", "deepseek", "chatglm", "arctic",
        "nemotron", "exaone", "granite", "bitnet", "jais", "t5", "bert",
        "rwkv", "orion", "xverse", "mamba", "deci", "codeshell",
        "bailingmoe", "afmoe", "chameleon", "plamo", "openelm", "olmo",
    ]

    files = (
        # Main script
        [("convert_hf_to_gguf.py", "convert_hf_to_gguf.py")]
        # conversion/ package — base + all model files
        + [("conversion/__init__.py", "conversion/__init__.py")]
        + [("conversion/base.py",     "conversion/base.py")]
        + [(f"conversion/{m}.py",     f"conversion/{m}.py") for m in CONVERSION_MODELS]
        # gguf-py package — complete verified file list from llama.cpp repo
        + [
            ("gguf-py/gguf/__init__.py",       "gguf-py/gguf/__init__.py"),
            ("gguf-py/gguf/constants.py",      "gguf-py/gguf/constants.py"),
            ("gguf-py/gguf/gguf_writer.py",    "gguf-py/gguf/gguf_writer.py"),
            ("gguf-py/gguf/gguf_reader.py",    "gguf-py/gguf/gguf_reader.py"),
            ("gguf-py/gguf/gguf.py",           "gguf-py/gguf/gguf.py"),
            ("gguf-py/gguf/quants.py",         "gguf-py/gguf/quants.py"),
            ("gguf-py/gguf/tensor_mapping.py", "gguf-py/gguf/tensor_mapping.py"),
            ("gguf-py/gguf/vocab.py",          "gguf-py/gguf/vocab.py"),
            ("gguf-py/gguf/metadata.py",       "gguf-py/gguf/metadata.py"),
            ("gguf-py/gguf/utility.py",        "gguf-py/gguf/utility.py"),
            ("gguf-py/gguf/lazy.py",           "gguf-py/gguf/lazy.py"),
        ]
    )

    total   = len(files)
    failed  = []
    for i, (remote, local) in enumerate(files):
        dest = tools_dir / local
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0:
            continue
        url = f"{base_url}/{remote}"
        if cb: cb(f"Downloading tools ({i+1}/{total}): {local}")
        ok = download_file(url, dest, local)
        if not ok:
            # 404s for optional model files are non-fatal
            log(f"Could not download {local} (may not exist in this version)", "warn")
            failed.append(local)

    script = tools_dir / "convert_hf_to_gguf.py"
    if not script.exists():
        return False, f"Failed to download main script. Check internet connection."

    # Verify conversion/__init__.py and base.py exist (critical)
    for critical in ["conversion/__init__.py", "conversion/base.py"]:
        if not (tools_dir / critical).exists():
            return False, f"Critical file missing: {critical}"

    log(f"llama.cpp tools ready in {tools_dir}", "ok")
    return True, str(script)


def convert_hf_to_gguf_pipeline(hf_dir, output_dir=None, quant="Q8_0", model_name=None, cb=None):
    """
    Convert a HuggingFace model folder to GGUF.
    Downloads convert_hf_to_gguf.py and its exact dependencies from llama.cpp.
    Returns (ok, gguf_path_or_error)
    """
    import subprocess as _sp, os as _os

    hf_path = Path(hf_dir)
    if not hf_path.exists():
        return False, f"HF model dir not found: {hf_dir}"
    if not (hf_path / "config.json").exists():
        return False, f"No config.json in {hf_dir} -- not a valid HuggingFace model folder"

    if output_dir is None:
        output_dir = str(hf_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    name    = model_name or hf_path.name
    gguf_out = out_dir / f"{name}.{quant}.gguf"

    if gguf_out.exists() and gguf_out.stat().st_size > 1024 * 1024:
        log(f"GGUF already exists: {gguf_out}", "info")
        return True, str(gguf_out)

    # ── Step 1: Install Python deps â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if cb: cb("Installing Python dependencies...")
    venv_install("gguf sentencepiece transformers accelerate numpy protobuf torch",
                 "gguf-conversion-deps")

    # ── Step 2: Download llama.cpp tools â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€─
    # Delete stale convert script so we always get the freshest version
    tools_dir = HERETIC_DIR / "llama_tools"
    # Always wipe and re-download gguf-py — must match convert script exactly
    gguf_dir = tools_dir / "gguf-py" / "gguf"
    if gguf_dir.exists():
        import shutil as _sh
        _sh.rmtree(str(gguf_dir), ignore_errors=True)
        log("Wiped stale gguf-py, re-downloading fresh copy", "info")
    stale = tools_dir / "convert_hf_to_gguf.py"
    if stale.exists():
        stale_size = stale.stat().st_size
        if stale_size < 5000:  # too small = incomplete download
            stale.unlink()
            log("Removed incomplete convert script, re-downloading", "warn")
    if cb: cb("Downloading llama.cpp conversion tools...")
    ok_dl, script_or_err = download_llama_cpp_tools(cb)
    if not ok_dl:
        return False, script_or_err

    script_path = Path(script_or_err)
    tools_dir   = script_path.parent  # HERETIC_DIR/llama_tools/

    # ── Step 3: Run conversion â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if cb: cb(f"Converting to GGUF {quant} — may take 10-30 min for large models...")
    log(f"Converting: {hf_path} -> {gguf_out}", "info")
    log(f"Script: {script_path}", "info")

    # Set PYTHONPATH so the script finds its local gguf-py and conversion dirs
    env = dict(_os.environ)
    # PYTHONPATH points to tools_dir so 'conversion/' package is found locally
    env["PYTHONPATH"]       = str(tools_dir)
    # Do NOT set NO_LOCAL_GGUF — the convert script checks:
    #   if 'NO_LOCAL_GGUF' not in os.environ: sys.path.insert(1, .../gguf-py)
    # So removing it ensures it uses the LOCAL gguf-py (which matches the script version)
    env.pop("NO_LOCAL_GGUF", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"]       = "1"

    cmd = [
        str(VENV_PY),
        str(script_path),
        str(hf_path),
        "--outfile", str(gguf_out),
        "--outtype", quant.lower()
    ]
    log(f"CMD: {cmd}", "info")
    log(f"PYTHONPATH: {env['PYTHONPATH']}", "info")

    try:
        result = _sp.run(
            cmd,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=7200,
            cwd=str(tools_dir),
            env=env
        )
        ok  = result.returncode == 0
        out = result.stdout.strip()
        err = result.stderr.strip()
        if out: log(f"stdout: {out[-400:]}", "info")
        if err: log(f"stderr: {err[-400:]}", "warn" if ok else "error")
    except Exception as ex:
        ok, out, err = False, "", str(ex)

    if ok and gguf_out.exists() and gguf_out.stat().st_size > 1024 * 1024:
        mb = gguf_out.stat().st_size // 1024 // 1024
        log(f"[OK] Conversion complete: {gguf_out} ({mb} MB)", "ok")
        return True, str(gguf_out)

    return False, _clean_progress(f"Conversion failed: {(err or out)[:400]}")


MODELFILE_DIR = Path(__file__).parent / "modelfiles"

def _write_modelfile(source_path, model_name):
    """Modelfiles are throwaway scratch files, so keep them in our own folder.

    They used to be written next to the source model, which meant they landed
    inside Ollama's own blob store (where every stray file looks like an
    orphaned blob) or inside a read-only HuggingFace snapshot directory.
    The path is quoted so folders with spaces work.
    """
    MODELFILE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", model_name) or "model"
    mf = MODELFILE_DIR / f"Modelfile_{safe}.txt"
    mf.write_text(f'FROM "{source_path}"\n', encoding="utf-8")
    log(f"Modelfile: {mf}", "info")
    return mf

def import_gguf_to_ollama(gguf_path, model_name, progress_cb=None):
    """Create Ollama model from GGUF file. Streams progress output."""
    p = Path(gguf_path)
    if not p.exists():
        return False, f"GGUF not found: {gguf_path}"

    mf = _write_modelfile(gguf_path, model_name)
    log(f"Running: ollama create {model_name} -f {mf}", "info")
    log("This may take 10-30 min for large models (Ollama is hashing/registering the file)...", "info")

    import subprocess as _sp
    try:
        # Stream output so we can log progress and update status
        proc = _sp.Popen(
            f'ollama create {model_name} -f "{mf}"',
            shell=True, stdout=_sp.PIPE, stderr=_sp.STDOUT,
            text=True, encoding="utf-8", errors="replace"
        )
        lines = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                lines.append(line)
                log(f"ollama: {line}", "info")
                if progress_cb:
                    progress_cb(line)
        proc.wait(timeout=7200)  # 2 hours max

        if proc.returncode == 0:
            log(f"Ollama model created: {model_name}", "ok")
            threading.Thread(target=refresh_status_cache, daemon=True).start()
            return True, model_name
        err = "\n".join(lines[-5:]) if lines else "ollama create failed"
        return False, err
    except Exception as e:
        return False, f"ollama create error: {e}"

# Job tracking for long-running clone+convert pipelines.
#
# This block used to redefine `_lock`, which reads as a second lock for this
# subsystem but is not one: module globals resolve at call time, so the later
# assignment simply REPLACED the lock defined near the top of the file and every
# subsystem ended up sharing it. Removing the duplicate changes no behaviour at
# all -- there was only ever one lock at runtime -- it just makes the code say
# so, instead of implying an isolation that does not exist.
#
# Left as a plain Lock rather than an RLock on purpose: all 42 functions that
# take it were checked and none calls another that takes it, so nesting cannot
# happen today, and an RLock would hide it the day someone introduces it.
_pipeline_jobs = {}  # job_id -> {status, progress, result, error}
_chat_status   = {}   # req_id -> {stage, detail, pct, start}

# A job parked waiting for the user to approve a tool. The job thread blocks on
# `event`; /api/chat_permit fills in the decision and sets it. One idle thread is
# a far cheaper thing to hold than a re-prefill of the whole conversation.
_perm_waits = {}          # job_id -> {needs, event, approved, denied, asked}
PERM_WAIT_SECONDS = 1800  # 30 min, then treat as denied rather than leak a thread

def resolve_permission(jid, approved=(), denied=()):
    """Answer a parked permission request. False if no job was waiting on that id.

    Split out of the request handler so the resume path can be tested without a
    socket -- the interesting behaviour is that the SAME loop carries on, and
    that is not observable from an HTTP round trip.
    """
    with _lock:
        rec = _perm_waits.get(jid)
        if rec:
            rec["approved"].update(str(k) for k in approved if k)
            rec["denied"].update(str(k) for k in denied if k)
    if not rec:
        return False
    rec["event"].set()
    return True

# A job parked on an ask_user question. Same idea as a permission wait, but the
# thing it is waiting for is an ANSWER, not an approval — the answer comes back
# as the tool result and the turn carries on. This is the primitive that lets the
# agent clarify before acting instead of guessing and getting it wrong.
_ask_waits = {}           # job_id -> {event, answer, option_id, asked}

def resolve_question(jid, answer="", option_id=""):
    """Answer a parked ask_user question. False if no job was waiting on that id."""
    with _lock:
        rec = _ask_waits.get(jid)
        if rec:
            rec["answer"] = str(answer or "")
            rec["option_id"] = str(option_id or "")
    if not rec:
        return False
    rec["event"].set()
    return True

def _clean_progress(text):
    """Strip non-ASCII and control chars from progress strings for safe display."""
    if not text: return text
    return ''.join(c if ord(c) < 128 else ' ' for c in str(text)).strip()

def run_clone_convert_pipeline(job_id, repo_url, dest_path, output_dir, model_name, quant="Q8_0"):
    """Full pipeline: clone -> convert -> import. Runs in background thread."""
    def _update(status, progress=""):
        clean = _clean_progress(progress)
        with _lock:
            _pipeline_jobs[job_id] = {"status": status, "progress": clean, "result": None, "error": None}
        log(f"Pipeline {job_id}: {status} {clean}", "info")

    _update("cloning", f"Cloning {repo_url}...")
    ok, result = git_clone_model(repo_url, dest_path, cb=lambda m: _update("cloning", m))
    if not ok:
        with _lock: _pipeline_jobs[job_id] = {"status":"error","progress":"","result":None,"error":result}
        return

    # Check if git_clone already downloaded a .gguf (pre-converted GGUF repo)
    dest_p = Path(dest_path)
    existing_gguf = list(dest_p.glob("*.gguf"))
    if existing_gguf and quant.upper() != "SKIP":
        gguf_direct = str(existing_gguf[0])
        log(f"GGUF repo detected -- skipping conversion, using: {gguf_direct}", "info")
        _update("importing", "Importing GGUF into Ollama...")
        def _dcb(line): _update("importing", line[:120])
        ok3, result3 = import_gguf_to_ollama(gguf_direct, model_name, progress_cb=_dcb)
        if ok3:
            reg = get_model_registry()
            if not any(m["name"]==model_name for m in reg):
                try: sz = round(Path(gguf_direct).stat().st_size/1024/1024,1)
                except: sz=0
                reg.append({"name":model_name,"path":gguf_direct,
                            "category":"chat","type":"gguf","size_mb":sz})
                save_model_registry(reg)
            with _lock:
                _pipeline_jobs[job_id] = {"status":"done","progress":"Complete",
                    "result":{"model_name":model_name,"gguf_path":gguf_direct},"error":None}
            log(f"Pipeline complete (GGUF repo): {model_name}", "ok")
        else:
            with _lock:
                _pipeline_jobs[job_id] = {"status":"error","progress":"","result":None,"error":result3}
        return

    # SKIP quant means clone-only (for Heretic workflow — user handles rest manually)
    if quant.upper() == "SKIP" or model_name == "_heretic_clone_only_":
        # Add to model registry as an HF folder (not yet GGUF)
        reg = get_model_registry()
        folder_name = Path(dest_path).name
        if not any(m["path"] == dest_path for m in reg):
            reg.append({
                "name": folder_name, "path": dest_path,
                "category": "chat", "type": "hf_folder",
                "size_mb": 0
            })
            save_model_registry(reg)
        with _lock:
            _pipeline_jobs[job_id] = {
                "status": "done", "progress": "Download complete",
                "result": {"model_name": folder_name, "gguf_path": dest_path}, "error": None
            }
        log(f"Clone-only complete: {dest_path}", "ok")
        return

    _update("converting", "Converting to GGUF...")
    ok2, gguf_or_err = convert_hf_to_gguf_pipeline(
        dest_path, output_dir, quant, model_name,
        cb=lambda m: _update("converting", m)
    )
    if not ok2:
        with _lock: _pipeline_jobs[job_id] = {"status":"error","progress":"","result":None,"error":gguf_or_err}
        return

    _update("importing", "Importing into Ollama (this can take 10-30 min for large models)...")
    def _import_cb(line):
        _update("importing", line[:120])
    ok3, result3 = import_gguf_to_ollama(gguf_or_err, model_name, progress_cb=_import_cb)
    if ok3:
        reg = get_model_registry()
        if not any(m["name"] == model_name for m in reg):
            reg.append({
                "name": model_name, "path": gguf_or_err,
                "category": "chat", "type": "gguf",
                "size_mb": round(Path(gguf_or_err).stat().st_size/1024/1024, 1)
            })
            save_model_registry(reg)
        with _lock:
            _pipeline_jobs[job_id] = {
                "status": "done", "progress": "Complete",
                "result": {"model_name": model_name, "gguf_path": gguf_or_err}, "error": None
            }
        log(f"Pipeline complete: {model_name} ready for chat", "ok")
    else:
        with _lock:
            _pipeline_jobs[job_id] = {"status":"error","progress":"","result":None,"error":result3}


# â”€â”€â”€ Model Registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
CHAT_EXTS  = {".gguf"}
IMAGE_EXTS = {".safetensors", ".ckpt", ".pt", ".pth"}

def get_model_registry():
    """Return the persistent list of user-added named models.

    Entries whose file has since been moved or deleted are dropped rather than
    offered in the picker - selecting one only produces a load failure later."""
    reg = _config.get("models_registry", [])
    live, dead = [], []
    for m in reg:
        p = (m or {}).get("path") or ""
        (live if p and Path(p).exists() else dead).append(m)
    if dead:
        for m in dead:
            log(f"model registry: dropping '{m.get('name')}' - file is gone ({m.get('path')})", "warn")
        _config["models_registry"] = live
        save_config()
    return live

def save_model_registry(registry):
    _config["models_registry"] = registry
    save_config()

def infer_model_category(path):
    ext = Path(path).suffix.lower()
    if ext in CHAT_EXTS:  return "chat"
    if ext in IMAGE_EXTS: return "image"
    return "unknown"

def infer_model_type(path):
    return Path(path).suffix.lower().lstrip(".")

def is_llm_safetensors(file_path):
    """
    Return True if a .safetensors file is part of an LLM (not an image model).
    LLM shards live next to config.json and model.safetensors.index.json.
    """
    p = Path(file_path)
    parent = p.parent
    # Check for LLM markers in the same directory
    llm_markers = ["config.json", "tokenizer.json", "tokenizer_config.json",
                   "model.safetensors.index.json", "model.safetensors.index.json.index.json"]
    return any((parent / m).exists() for m in llm_markers)

def scan_folder_for_models(folder_path):
    """Scan a folder and subfolders for model files. Returns list of found files."""
    folder = Path(folder_path)
    if not folder.exists():
        return []
    all_exts = CHAT_EXTS | IMAGE_EXTS
    found = []
    try:
        for root, dirs, files in os.walk(str(folder)):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"__pycache__","node_modules"}]
            for fname in files:
                if Path(fname).suffix.lower() in all_exts:
                    full = Path(root) / fname
                    try:
                        size_mb = full.stat().st_size / (1024*1024)
                        if size_mb < 0.1: continue
                        ext = Path(fname).suffix.lower()
                        # Reclassify: .safetensors next to config.json = LLM HF format, not image
                        if ext in IMAGE_EXTS and is_llm_safetensors(full):
                            category = "chat"
                            display_ext = "hf_shard"
                        else:
                            category = infer_model_category(str(full))
                            display_ext = ext.lstrip(".")
                        found.append({
                            "path":     str(full),
                            "filename": fname,
                            "size_mb":  round(size_mb, 1),
                            "ext":      display_ext,
                            "category": category,
                        })
                    except: pass
    except PermissionError:
        pass
    return found


# â”€â”€â”€ Persistent Memory System â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€─
MEMORY_FILE = _CONFIG_DIR / "neuraldock_memory.json"
MEMORY_CATEGORIES = ["projects", "preferences", "corrections", "paths", "hardware", "people", "facts"]

# ─── Session persistence ──────────────────────────────────────────────────────
# Chat tabs lived only in the page's JS, so closing the window threw the
# conversation away and every launch started blank. This is stored SERVER side
# rather than in localStorage on purpose: localStorage is scoped to the origin,
# so a chat started at localhost:7788 would be invisible when the same app is
# opened over Tailscale or from the phone. One file, one truth, every client.
SESSION_FILE = _CONFIG_DIR / "chat_session.json"
SESSION_MAX_TABS = 12
SESSION_MAX_MSGS = 300         # per tab
SESSION_MAX_MSG_CHARS = 20000  # one pasted file should not bloat the whole store
SESSION_MAX_BYTES = 8 * 1024 * 1024


def _trim_session(data):
    """Bound what gets written so the session file cannot grow without limit."""
    tabs = []
    for t in (data.get("tabs") or [])[:SESSION_MAX_TABS]:
        hist = []
        for m in (t.get("history") or [])[-SESSION_MAX_MSGS:]:
            role = str(m.get("role", ""))[:20]
            content = str(m.get("content", ""))
            if len(content) > SESSION_MAX_MSG_CHARS:
                content = (content[:SESSION_MAX_MSG_CHARS] +
                           f"\n[... {len(content)-SESSION_MAX_MSG_CHARS} chars trimmed when the session was saved ...]")
            if role:
                hist.append({"role": role, "content": content})
        tabs.append({
            "id":      str(t.get("id", ""))[:40],
            "name":    str(t.get("name", "Chat"))[:60],
            "model":   str(t.get("model", ""))[:80],
            "history": hist,
        })
    return {
        "version": 1,
        "saved_at": time.time(),
        "active": str(data.get("active", ""))[:40],
        "workspace": str(data.get("workspace", ""))[:400],
        "project": str(data.get("project", ""))[:40],
        "tabs": tabs,
    }


def save_session(data):
    try:
        payload = _trim_session(data)
        blob = json.dumps(payload, ensure_ascii=False)
        # Drop oldest tabs until it fits, rather than refusing to save at all.
        while payload["tabs"] and len(blob.encode("utf-8")) > SESSION_MAX_BYTES:
            payload["tabs"].pop(0)
            blob = json.dumps(payload, ensure_ascii=False)
        tmp = SESSION_FILE.with_suffix(".tmp")
        tmp.write_text(blob, encoding="utf-8")
        tmp.replace(SESSION_FILE)   # atomic: a crash mid-write cannot corrupt it
        return {"ok": True, "tabs": len(payload["tabs"]),
                "messages": sum(len(t["history"]) for t in payload["tabs"])}
    except Exception as e:
        log(f"Session save failed: {e}", "warn")
        return {"ok": False, "msg": str(e)}


def load_session():
    try:
        if not SESSION_FILE.exists():
            return {"ok": True, "session": None}
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        tabs = [t for t in (data.get("tabs") or []) if t.get("history")]
        if not tabs:
            return {"ok": True, "session": None}
        data["tabs"] = tabs
        return {"ok": True, "session": data}
    except Exception as e:
        # A damaged session file must never stop the app from opening.
        log(f"Session load failed ({e}) - starting fresh", "warn")
        return {"ok": True, "session": None}

# ─── Terminal sessions (the TERMINAL tab) ─────────────────────────────────────
# A PowerShell or CMD session per terminal tab, started in the workspace and kept
# alive between commands, so `cd`, variables and venv activation carry over.
# Pipes, not a console: the output is plain text in the page. A program that
# needs a real console (a full-screen editor, a REPL waiting on a TTY) will not
# behave; OPEN WINDOW starts a real one in the same folder for those.
#
# After each command the shell prints TERM_DONE|<cwd>|<status> on a line of its
# own; the reader strips it and uses it for "busy" and the folder shown.
# Browsers on this PC only, unless _config["terminal_remote"] is set: a paired
# phone gets the chat, not a raw shell.
TERM_DONE = "__ND_TERM_DONE__"
TERM_MAX_CHARS = 400_000        # kept per session; older output is dropped
TERM_MAX_SESSIONS = 8
TERM_PROMPT = "__ND_TERM_PROMPT__"   # cmd's own prompt, set to this and stripped
# Measured 2026-09-27: both shells read piped stdin in the OEM code page (UTF-8 in
# turned "e-acute" into two characters), and "chcp 65001" made cmd worse, not better. So
# input goes in as OEM; PowerShell is told to write UTF-8, cmd's output is read as OEM.
try:
    import ctypes as _ct
    TERM_OEM = f"cp{_ct.windll.kernel32.GetOEMCP()}"
except Exception:
    TERM_OEM = "cp437"
# Never "stop" these: they are the shell's own console host, not the command.
TERM_KEEP = {"conhost.exe", "openconsole.exe"}
_terms = {}
_terms_lock = threading.Lock()


def _term_argv(kind):
    if kind == "cmd":
        return ["cmd.exe", "/Q", "/K"]
    return ["powershell.exe", "-NoLogo", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", "-"]


def _term_done_line(kind):
    if kind == "cmd":
        return f"echo {TERM_DONE}^|%CD%^|%ERRORLEVEL%"
    # $? first, before anything else on the line resets it; LASTEXITCODE is then
    # zeroed so a failed native command is not reported again after the next one.
    return ("$__nd_ok=$?; $__nd_c=$LASTEXITCODE; $global:LASTEXITCODE=0; "
            f"Write-Output ('{TERM_DONE}|' + (Get-Location).ProviderPath + '|' + "
            "$(if ($__nd_ok) { 0 } elseif ($__nd_c) { $__nd_c } else { 1 }))")


class _TermSession:
    def __init__(self, kind, cwd):
        self.id = "t" + secrets.token_hex(4)
        self.kind = "cmd" if kind == "cmd" else "powershell"
        self.cwd = cwd
        self.text = ""              # the output shown, TERM_DONE lines removed
        self.base = 0               # characters dropped from the front
        self.busy = True            # until the start-up command reports done
        self.last_status = None
        self.lock = threading.Lock()
        self._partial = ""
        self._blank = 0             # cmd: blank lines held back (it prints one per prompt)
        self._start()

    def _start(self):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        env = dict(os.environ, PROMPT=TERM_PROMPT)
        self.proc = subprocess.Popen(_term_argv(self.kind), cwd=self.cwd, env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, creationflags=flags)
        threading.Thread(target=self._reader, daemon=True).start()
        if self.kind == "cmd":
            self._write(_term_done_line(self.kind) + "\n")
        else:
            self._write("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                        "$OutputEncoding=[Text.Encoding]::UTF8; $ProgressPreference='SilentlyContinue'"
                        "\n" + _term_done_line(self.kind) + "\n")

    def _write(self, data):
        try:
            self.proc.stdin.write(data.replace("\n", "\r\n").encode(TERM_OEM, "replace"))
            self.proc.stdin.flush()
            return True
        except Exception:
            return False

    def _emit(self, chunk):
        if self.kind == "cmd":
            chunk = chunk.replace("\n" + TERM_PROMPT, "").replace(TERM_PROMPT, "")
            if not chunk:
                return
        with self.lock:
            self.text += chunk
            if len(self.text) > TERM_MAX_CHARS:
                drop = len(self.text) - TERM_MAX_CHARS
                self.text = self.text[drop:]
                self.base += drop

    def _take_line(self, line):
        """One complete output line: a TERM_DONE marker updates the state, the
        rest is output."""
        i = line.find(TERM_DONE + "|")
        if i < 0:
            if self.kind == "cmd" and not line.strip():
                self._blank += 1             # emitted only if real output follows
                return
            if self._blank:
                self._emit("\n" * self._blank)
                self._blank = 0
            self._emit(line + "\n")
            return
        self._blank = 0
        if i > 0:                                   # output with no newline before it
            self._emit(line[:i] + "\n")
        parts = line[i + len(TERM_DONE) + 1:].split("|")
        with self.lock:
            if parts and parts[0].strip():
                self.cwd = parts[0].strip()
            self.last_status = parts[1].strip() if len(parts) > 1 else None
            self.busy = False

    def _reader(self):
        import codecs
        dec = codecs.getincrementaldecoder(TERM_OEM if self.kind == "cmd" else "utf-8")("replace")
        out = self.proc.stdout
        mine = self.proc
        while True:
            try:
                b = out.read1(65536) if hasattr(out, "read1") else out.read(1)
            except Exception:
                b = b""
            if not b:
                break
            if mine is not self.proc:
                break
            txt = self._partial + dec.decode(b).replace("\r\n", "\n").replace("\r", "\n")
            lines = txt.split("\n")
            self._partial = lines.pop()
            for ln in lines:
                self._take_line(ln)
            # A prompt with no newline yet ("Continue? [Y/N]") must still show -
            # unless it could be the start of a marker line.
            p = self._partial.replace(TERM_PROMPT, "") if self.kind == "cmd" else self._partial
            self._partial = p
            if p and not (TERM_DONE.startswith(p[:len(TERM_DONE)]) or TERM_DONE in p
                          or TERM_PROMPT.startswith(p)):
                if self._blank:
                    self._emit("\n" * self._blank)
                    self._blank = 0
                self._emit(p)
                self._partial = ""
        if self._partial:
            self._take_line(self._partial)
            self._partial = ""
        if out is self.proc.stdout:              # not a shell that was replaced
            with self.lock:
                self.busy = False
            self._emit(f"\n[{self.kind} exited with code {self.proc.poll()}]\n")

    def alive(self):
        return self.proc.poll() is None

    def send(self, line):
        if not self.alive():
            return False
        self._blank = 0
        with self.lock:
            self.busy = True
            self.text += f"{self.prompt()}{line}\n"      # echo what was run
        return self._write(line + "\n" + _term_done_line(self.kind) + "\n")

    def prompt(self):
        return (f"{self.cwd}> " if self.kind == "cmd" else f"PS {self.cwd}> ")

    def stop(self):
        """Stop the RUNNING command: end the shell's child processes. A command
        that is the shell itself (a long cmdlet) can only be stopped by
        restarting the shell, in the same folder."""
        killed = 0
        try:
            import psutil
            for ch in psutil.Process(self.proc.pid).children(recursive=True):
                try:
                    if ch.name().lower() in TERM_KEEP:
                        continue
                    ch.kill()
                    killed += 1
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(0.3)
        if killed and not self.alive():
            self.restart("[stopped - the shell went with it and was restarted]")
            return "restarted"
        if killed:
            self._emit(f"\n[stopped - ended {killed} process{'es' if killed > 1 else ''}]\n")
            return "stopped"
        self.restart("[stopped - the shell was restarted]")
        return "restarted"

    def restart(self, note):
        try:
            self.proc.kill()
        except Exception:
            pass
        self._emit(f"\n{note}\n")
        with self.lock:
            self.busy = True
        self._start()

    def close(self):
        try:
            import psutil
            for ch in psutil.Process(self.proc.pid).children(recursive=True):
                try:
                    ch.kill()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.proc.kill()
        except Exception:
            pass

    def read(self, since):
        with self.lock:
            start = max(0, int(since or 0) - self.base)
            return {"ok": True, "id": self.id, "kind": self.kind, "text": self.text[start:],
                    "at": self.base + start, "end": self.base + len(self.text),
                    "cwd": self.cwd, "busy": self.busy, "alive": self.alive(),
                    "last_status": self.last_status, "prompt": self.prompt()}


def _term_cwd(cwd):
    try:
        p = Path(str(cwd or "").strip().strip('"'))
        if str(p) and p.is_dir():
            return str(p)
    except Exception:
        pass
    return str(Path.home())


def term_open_window(kind, cwd):
    """A real console window in `cwd` - for programs that need one."""
    cwd = _term_cwd(cwd)
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    shell = ["cmd.exe", "/K"] if kind == "cmd" else ["powershell.exe", "-NoLogo", "-NoExit"]
    wt = shutil.which("wt")
    try:
        if wt:
            subprocess.Popen([wt, "-d", cwd] + shell, cwd=cwd)
        else:
            subprocess.Popen(shell, cwd=cwd, creationflags=flags)
        return {"ok": True, "cwd": cwd, "via": "Windows Terminal" if wt else "console"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def term_api(body):
    action = body.get("action", "read")
    tid = str(body.get("id", ""))
    if action == "start":
        with _terms_lock:
            for k in [k for k, t in _terms.items() if not t.alive()]:
                _terms.pop(k, None)
            if len(_terms) >= TERM_MAX_SESSIONS:
                return {"ok": False, "msg": f"{TERM_MAX_SESSIONS} terminals are open - close one first"}
            t = _TermSession(body.get("kind", "powershell"), _term_cwd(body.get("cwd")))
            _terms[t.id] = t
        log(f"Terminal {t.id} started ({t.kind}) in {t.cwd}", "info")
        return t.read(0)
    if action == "list":
        with _terms_lock:
            items = list(_terms.values())
        return {"ok": True, "terms": [{"id": t.id, "kind": t.kind, "cwd": t.cwd,
                                       "busy": t.busy, "alive": t.alive()} for t in items]}
    if action == "window":
        return term_open_window(body.get("kind", "powershell"), body.get("cwd"))
    with _terms_lock:
        t = _terms.get(tid)
    if t is None:
        return {"ok": False, "gone": True, "msg": "that terminal is closed"}
    if action == "send":
        line = str(body.get("line", ""))
        if "\n" in line.strip():
            return {"ok": False, "msg": "one line at a time"}
        return {"ok": t.send(line.rstrip("\r\n")), **t.read(body.get("since", 0))}
    if action == "stop":
        return {"ok": True, "result": t.stop()}
    if action == "close":
        t.close()
        with _terms_lock:
            _terms.pop(tid, None)
        return {"ok": True}
    return t.read(body.get("since", 0))


# ─── Projects (saved like Cowork's) ───────────────────────────────────────────
# A project is a name, a workspace folder, standing instructions and its own
# chat tabs - one JSON file each under <config>/projects. While a project is
# open the UI saves its chats into it as they change; opening another project
# swaps the whole set of tabs. The instructions are added to every chat request
# whose workspace is the project's folder (project_instructions_for).
PROJECTS_DIR = _CONFIG_DIR / "projects"
PROJECT_MAX_INSTR = 6000


def _project_file(pid):
    pid = re.sub(r"[^A-Za-z0-9_-]", "", str(pid or ""))[:40]
    return (PROJECTS_DIR / f"{pid}.json") if pid else None


def _read_project(pid):
    f = _project_file(pid)
    if not f or not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"Project {pid} unreadable: {e}", "warn")
        return None


def _write_project(p):
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    f = _project_file(p["id"])
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    tmp.replace(f)


def list_projects():
    out = []
    if PROJECTS_DIR.exists():
        for f in PROJECTS_DIR.glob("*.json"):
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            tabs = (p.get("session") or {}).get("tabs") or []
            out.append({"id": p.get("id"), "name": p.get("name", "?"),
                        "workspace": p.get("workspace", ""),
                        "has_instructions": bool((p.get("instructions") or "").strip()),
                        "chats": len(tabs),
                        "messages": sum(len(t.get("history") or []) for t in tabs),
                        "updated": p.get("updated", 0)})
    out.sort(key=lambda p: -(p["updated"] or 0))
    return out


def save_project(body):
    """Create (no id) or update a project. Only the fields sent are changed."""
    pid = body.get("id")
    p = _read_project(pid) if pid else None
    if pid and p is None:
        return {"ok": False, "msg": "no such project"}
    if p is None:
        name = str(body.get("name") or "").strip()
        if not name:
            return {"ok": False, "msg": "a project needs a name"}
        p = {"id": "p" + secrets.token_hex(5), "name": name, "created": time.time(),
             "workspace": "", "instructions": "", "session": None}
    if "name" in body and str(body["name"]).strip():
        p["name"] = str(body["name"]).strip()[:80]
    if "workspace" in body:
        p["workspace"] = str(body.get("workspace") or "")[:400]
    if "instructions" in body:
        p["instructions"] = str(body.get("instructions") or "")[:PROJECT_MAX_INSTR]
    if "notes_folder" in body:
        # The vault folder holding this project's notes, relative to the vault.
        p["notes_folder"] = str(body.get("notes_folder") or "").strip()[:300]
    if "session" in body and body["session"] is not None:
        p["session"] = _trim_session(body["session"])
    p["updated"] = time.time()
    _write_project(p)
    return {"ok": True, "project": {k: p[k] for k in ("id", "name", "workspace", "instructions")}}


def delete_project(pid):
    """Moves the file to projects/_deleted - recoverable by hand, never destroyed."""
    f = _project_file(pid)
    if not f or not f.exists():
        return {"ok": False, "msg": "no such project"}
    trash = PROJECTS_DIR / "_deleted"
    trash.mkdir(parents=True, exist_ok=True)
    f.replace(trash / f"{f.stem}_{int(time.time())}.json")
    return {"ok": True}


def project_instructions_for(workspace):
    """(name, instructions) of the project whose folder is `workspace`, or None."""
    if not workspace or not PROJECTS_DIR.exists():
        return None
    try:
        want = os.path.normcase(os.path.normpath(str(workspace)))
    except Exception:
        return None
    for f in PROJECTS_DIR.glob("*.json"):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        ws, ins = p.get("workspace") or "", (p.get("instructions") or "").strip()
        if ws and ins and os.path.normcase(os.path.normpath(ws)) == want:
            return p.get("name", "project"), ins
    return None


def projects_api(body):
    action = body.get("action", "list")
    if action == "list":
        return {"ok": True, "projects": list_projects()}
    if action == "load":
        p = _read_project(body.get("id"))
        return {"ok": True, "project": p} if p else {"ok": False, "msg": "no such project"}
    if action == "save":
        return save_project(body)
    if action == "delete":
        return delete_project(body.get("id"))
    return {"ok": False, "msg": f"unknown action {action}"}


# --- Obsidian vault backend -------------------------------------------------
# The vault at obsidian_root is the source of truth. The JSON file above is kept
# as a mirror so nothing is ever stranded if the vault drive is offline.
# ND writes ONLY inside <vault>/AI Memory/ and never touches hand-written notes.
try:
    from nd_obsidian_memory import ObsidianMemory as _ObsidianMemory
except Exception as _obs_err:
    _ObsidianMemory = None
    _obs_import_error = _obs_err

_OBS = None
_OBS_TRIED = False

def obs():
    """Lazily build the vault backend. Returns None if unavailable."""
    global _OBS, _OBS_TRIED
    if _OBS_TRIED:
        return _OBS
    _OBS_TRIED = True
    if _ObsidianMemory is None:
        log(f"Obsidian memory module not loaded: {_obs_import_error}", "warn")
        return None
    try:
        o = _ObsidianMemory(_config, _CONFIG_DIR)
        if o.available:
            log(f"Obsidian memory: {o.vault} ({len(o.all_notes())} notes)", "info")
            moved = o.migrate_json().get("migrated", 0)
            if moved:
                log(f"Migrated {moved} JSON memories into the vault", "info")
            _OBS = o
        else:
            log(f"Obsidian memory unavailable ({o.last_error}); using JSON", "warn")
    except Exception as e:
        log(f"Obsidian memory init failed: {e}", "warn")
    return _OBS

# --- Vault activity ----------------------------------------------------------
# What ND read from and wrote to the Obsidian vault, for anything that wants to
# show it (Elena Live). Reads are recorded only for notes whose CONTENT went to a
# model, not for the front-matter scans every turn makes of the whole vault.
VAULT_EVENTS = []
VAULT_EVENTS_KEPT = 500


def _vault_rel(path):
    o = obs()
    try:
        return Path(path).resolve().relative_to(o.vault.resolve()).as_posix() if o else None
    except (ValueError, OSError):
        return None


def vault_event(op, path, by):
    rel = _vault_rel(path)
    if not rel or not rel.lower().endswith(".md"):
        return
    with _lock:
        # Strictly increasing, so a client asking "newer than t" never loses one
        # of two events logged in the same clock tick.
        t = time.time()
        if VAULT_EVENTS and t <= VAULT_EVENTS[-1]["t"]:
            t = VAULT_EVENTS[-1]["t"] + 1e-6
        VAULT_EVENTS.append({"t": t, "op": op, "note": rel, "by": by})
        if len(VAULT_EVENTS) > VAULT_EVENTS_KEPT:
            del VAULT_EVENTS[0:len(VAULT_EVENTS) - VAULT_EVENTS_KEPT]


def vault_activity(since=0.0):
    with _lock:
        return {"now": time.time(), "events": [e for e in VAULT_EVENTS if e["t"] > since]}


_WIKILINK = re.compile(r"\[\[([^\]|#]+)")


def vault_graph():
    """Every note: id (vault-relative path), title, folder, type, project, links
    (ids of the notes its [[wikilinks]] resolve to) and mtime."""
    o = obs()
    if not o:
        return {"vault": None, "notes": []}
    paths = o.all_notes()
    by_stem = {}
    for p in paths:
        by_stem.setdefault(p.stem.lower(), p)
    notes = []
    for p in paths:
        fm, body = o._read_note(p)
        rel = _vault_rel(p)
        links = []
        for name in _WIKILINK.findall(body or ""):
            q = by_stem.get(name.strip().split("/")[-1].lower())
            if q is not None and q != p:
                links.append(_vault_rel(q))
        try:
            mt = p.stat().st_mtime
        except OSError:
            mt = 0
        notes.append({"id": rel, "title": str(fm.get("title") or p.stem),
                      "folder": str(Path(rel).parent.as_posix()) if rel else "",
                      "type": str(fm.get("type") or ""), "project": str(fm.get("project") or ""),
                      "links": sorted(set(l for l in links if l)), "mtime": mt})
    return {"vault": str(o.vault), "notes": notes}


def _project_for(workspace):
    """The ND project whose folder is `workspace` (instructions optional), or None."""
    if not workspace or not PROJECTS_DIR.exists():
        return None
    want = os.path.normcase(os.path.normpath(str(workspace)))
    for f in PROJECTS_DIR.glob("*.json"):
        try:
            pj = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        ws = pj.get("workspace") or ""
        if ws and os.path.normcase(os.path.normpath(ws)) == want:
            return pj
    return None


def _is_hub(stem, folder, name):
    """The folder's hub note: named like the project or the folder ("04 NeuralDock"
    -> "NeuralDock"), or an Overview / MOC note."""
    s = stem.lower().strip()
    base = re.sub(r"^\d+\s+", "", folder.split("/")[-1]).lower().strip() if folder else ""
    return s in (str(name).lower().strip(), base) or s.endswith(" overview") or s.endswith(" moc")         or s.startswith("_") and s.endswith("moc")


_NOTE_ORDER = {"project": 0, "reference": 1, "design": 2, "lesson": 3}


def project_notes_block(workspace, budget=None):
    """The workspace's project notes, verbatim, for the TAIL of the request."""
    if not _config.get("agent_project_notes", True):
        return ""
    pj = _project_for(workspace)
    o = obs()
    if not pj or not o:
        return ""
    name = pj.get("name") or "project"
    # A project's notes are its linked vault FOLDER (how the vault is organised:
    # "System and Applications/04 NeuralDock/..."), hub note first; failing that,
    # notes whose front matter says `project: <name>`.
    folder = str(pj.get("notes_folder") or "").strip().strip("/\\").replace("\\", "/")
    root = (o.vault / folder) if folder else None
    budget = int(budget or _config.get("agent_project_notes_chars", 9000))
    mine = []
    for p in o.all_notes():
        fm, body = o._read_note(p)
        if not body.strip():
            continue
        if root is not None:
            try:
                p.resolve().relative_to(root.resolve())
            except ValueError:
                continue
            rank = -1 if _is_hub(p.stem, folder, name) else _NOTE_ORDER.get(str(fm.get("type") or ""), 9)
        elif str(fm.get("project") or "").strip().lower() == str(name).strip().lower():
            rank = _NOTE_ORDER.get(str(fm.get("type") or ""), 9)
        else:
            continue
        mine.append((rank, p.stem, p, body.strip()))
    if not mine:
        return ""
    mine.sort(key=lambda x: (x[0], x[1]))
    out, used, left = [], 0, []
    for _o, stem, p, body in mine:
        chunk = f"### {stem}\n{body}"
        if used + len(chunk) > budget:
            left.append(f"- {stem}: {p}")
            continue
        out.append(chunk)
        used += len(chunk)
        vault_event("read", p, "project_notes")
    head = (f"\n\n[NeuralDock: PROJECT NOTES for '{name}', from the Obsidian vault. "
            "Facts about this project written by its owner -- use them. If a note and "
            "the code disagree, the code wins.]\n\n")
    tail = ("\n\nMore notes for this project (open with read_file if needed):\n"
            + "\n".join(left)) if left else ""
    return head + "\n\n".join(out) + tail


def load_memory():
    """Load memory. Vault first, JSON fallback."""
    o = obs()
    if o:
        try:
            return o.load_memory()
        except Exception as e:
            log(f"Vault read failed, falling back to JSON: {e}", "warn")
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except: pass
    return {cat: [] for cat in MEMORY_CATEGORIES}

def save_memory(mem):
    """Save memory. Writes one note per fact into the vault, mirrors to JSON."""
    o = obs()
    if o:
        try:
            _before = {}
            try:
                _before = {p: p.stat().st_mtime for p in o.memory_notes()}
            except Exception:
                pass
            o.save_memory(mem)   # this also mirrors to MEMORY_FILE
            try:
                for _p in o.memory_notes():
                    _m = _p.stat().st_mtime
                    if _p not in _before:
                        vault_event("write", _p, "memory")
                    elif _m != _before[_p]:
                        vault_event("update", _p, "memory")
            except Exception:
                pass
            return
        except Exception as e:
            log(f"Vault write failed, falling back to JSON: {e}", "warn")
    try:
        MEMORY_FILE.write_text(json.dumps(mem, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"Memory save failed: {e}", "warn")

def memory_to_prompt(mem, max_chars=2000, user_text="", budget=None):
    """Format memory as a system prompt injection.

    With the vault available this returns the tiered whole-vault context
    (atomic facts + full vault index + relevance-selected note bodies) under
    the obsidian_budget_chars budget. max_chars only acts as a floor so old
    call sites cannot accidentally starve it.

    `budget` is the per-model override from model_profile(). It wins outright,
    including downward: on an 8K-context model the whole window is only ~32k
    chars, and a 12k-char memory block would eat more than a third of it before
    the user's question is even in the prompt.
    """
    o = obs()
    if o:
        try:
            eff = int(budget) if budget else max(int(max_chars or 0), o.budget)
            out = o.context_for(user_text, budget=eff)
            if out:
                try:
                    _stems = {p.stem.lower(): p for p in o.all_notes()}
                    for _h in set(re.findall(r"^### (.+)$", out, re.M)):
                        _p = _stems.get(_h.split(" > ")[0].strip().lower())
                        if _p is not None:
                            vault_event("read", _p, "memory")
                except Exception:
                    pass
                return out
        except Exception as e:
            log(f"Vault context failed, falling back to JSON: {e}", "warn")
    lines = ["USER MEMORY (facts learned from past conversations):"]
    for cat in MEMORY_CATEGORIES:
        items = mem.get(cat, [])
        if items:
            lines.append(f"  {cat.upper()}: " + " | ".join(items[:10]))
    result = "\n".join(lines)
    return result[:int(budget or max_chars)]

def extract_memory_from_conversation(model, messages):
    """
    Run a quick summarization pass to extract memorable facts from a conversation.
    Returns dict of {category: [new facts]} to merge into memory.
    """
    if len(messages) < 2:
        return {}
    
    # Build a compact conversation summary for extraction
    convo = "\n".join([
        f"{m['role'].upper()}: {m['content'][:300]}"
        for m in messages[-20:]  # last 20 messages max
    ])
    
    extraction_prompt = (
        "Extract memorable facts from this conversation. "
        "Return ONLY a JSON object with these keys (omit empty ones): "
        "projects (names/paths of projects worked on), "
        "preferences (coding style, tool preferences, how user likes responses), "
        "corrections (things user corrected or disagreed with), "
        "paths (file/folder paths mentioned), "
        "hardware (hardware/OS/GPU info), "
        "people (names mentioned), "
        "facts (any other useful facts about the user). "
        "Each key maps to a list of short strings (max 10 words each). "
        "Return valid JSON only, no explanation.\n\nCONVERSATION:\n" + convo
    )
    
    try:
        raw = ollama_chat(model, [
            {"role": "system", "content": "You extract facts from conversations. Return only valid JSON."},
            {"role": "user", "content": extraction_prompt}
        ], timeout=60)
        
        # Parse JSON from response
        import re as _re
        json_match = _re.search(r'\{.*\}', raw, _re.DOTALL)
        if json_match:
            extracted = json.loads(json_match.group())
            # Filter: only keep strings in lists
            result = {}
            for cat in MEMORY_CATEGORIES:
                items = extracted.get(cat, [])
                if isinstance(items, list):
                    result[cat] = [str(i)[:100] for i in items if i]
            return result
    except Exception as e:
        log(f"Memory extraction failed: {e}", "warn")
    return {}

def merge_memory(existing, new_facts):
    """Merge new extracted facts into existing memory, deduplicating."""
    for cat in MEMORY_CATEGORIES:
        new_items = new_facts.get(cat, [])
        existing_items = existing.get(cat, [])
        for item in new_items:
            item_lower = item.lower()
            # Skip if very similar item already exists
            if not any(item_lower in e.lower() or e.lower() in item_lower
                       for e in existing_items):
                existing_items.append(item)
        existing[cat] = existing_items[:20]  # cap at 20 per category
    return existing

# ═══════════════════════════════════════════════════════════════════════════════
# AUTH — required before this server is reachable from anything but this PC
# ═══════════════════════════════════════════════════════════════════════════════
# Every /api route can run shell commands, install software and drive the mouse.
# On localhost that is fine. The moment a phone can reach port 7788, so can
# anything else on that network, so remote callers must present a token.
def api_token():
    t = _config.get("api_token", "")
    if not t:
        t = secrets.token_urlsafe(24)
        _config["api_token"] = t
        save_config()
        log("Generated a new API token (Setup -> Devices to pair a phone)", "ok")
    return t

def rotate_api_token():
    _config["api_token"] = secrets.token_urlsafe(24)
    save_config()
    log("API token rotated - every paired device must pair again", "warn")
    return _config["api_token"]

_LOCAL_IPS = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}

# Open to unauthenticated localhost so the app keeps working with no setup.
AUTH_EXEMPT = {"/api/ping", "/api/pair_claim"}

def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        return ip
    except Exception:
        return "127.0.0.1"

PAIR_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NeuralDock - pair</title>
<style>
 body{background:#05070a;color:#9fb;font:14px ui-monospace,Consolas,monospace;
      display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:16px}
 .card{border:1px solid #1c4;border-radius:10px;padding:22px;max-width:420px;width:100%}
 h1{color:#0ff;font-size:16px;letter-spacing:2px;margin:0 0 10px}
 p{color:#6a8;font-size:12px;line-height:1.5}
 input{width:100%;box-sizing:border-box;background:#000;border:1px solid #1c4;color:#0f9;
       padding:13px;font:16px ui-monospace,monospace;border-radius:6px;letter-spacing:2px}
 button{width:100%;margin-top:10px;background:#062;border:1px solid #0f9;color:#0f9;
        padding:13px;font:14px ui-monospace,monospace;border-radius:6px;letter-spacing:1px}
 #m{margin-top:10px;font-size:12px;min-height:34px}
 .err{color:#f66}.ok{color:#0f9}.wait{color:#fb0}
</style></head><body>
<div class="card">
 <h1>ELENA // PAIR DEVICE</h1>
 <p>Type the <b>6-character code</b> from the PC (Setup &rsaquo; Devices &rsaquo; PAIR A DEVICE),
    or paste the full access token. Either works.</p>
 <input id="t" placeholder="6-char code or token" autocomplete="off"
        autocapitalize="characters" spellcheck="false">
 <button id="b" onclick="go()">CONNECT</button>
 <div id="m"></div>
</div>
<script>
var M=document.getElementById('m'), T=document.getElementById('t'), B=document.getElementById('b');
function say(t,c){ M.className=c||''; M.textContent=t; }
function land(tok){ try{localStorage.setItem('nd_token',tok);}catch(e){}
                    location.href='/?token='+encodeURIComponent(tok); }

function go(){
  var v=(T.value||'').trim();
  if(!v){ say('Enter the code or token.','err'); return; }
  B.disabled=true;
  // A short alphanumeric string is a pairing code; anything longer is a token.
  // Guessing here is what makes "either works" possible - the PC shows a 6-char
  // code, so that is what people naturally type.
  if(/^[A-Za-z0-9]{4,8}$/.test(v)) claim(v.toUpperCase()); else tokenTry(v);
}

function tokenTry(v){
  say('Checking token...','wait');
  fetch('/api/ping',{method:'POST',headers:{'Content-Type':'application/json','X-ND-Token':v},body:'{}'})
   .then(function(r){return r.json()})
   .then(function(d){ if(d && d.ok){ say('Connected.','ok'); land(v); }
                      else { say('Token rejected. If you meant the 6-character code, type that instead.','err'); B.disabled=false; } })
   .catch(function(e){ say('Cannot reach the server: '+e,'err'); B.disabled=false; });
}

function claim(code){
  say('Asking the PC to approve this device...','wait');
  fetch('/api/pair_claim',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({code:code, device:(navigator.userAgent.match(/\(([^)]+)\)/)||[0,'browser'])[1]})})
   .then(function(r){return r.json()})
   .then(function(d){
      if(d.state==='pending'){ say('Waiting for you to approve it on the PC...','wait'); poll(d.req_id,0); }
      else if(d.state==='bad_code'){ say('That code is wrong or expired. Press PAIR A DEVICE on the PC for a fresh one.','err'); B.disabled=false; }
      else { say('Unexpected reply: '+JSON.stringify(d),'err'); B.disabled=false; }
   })
   .catch(function(e){ say('Cannot reach the server: '+e,'err'); B.disabled=false; });
}

function poll(id,n){
  if(n>200){ say('Timed out waiting for approval.','err'); B.disabled=false; return; }
  fetch('/api/pair_claim',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({req_id:id})})
   .then(function(r){return r.json()})
   .then(function(d){
      if(d.state==='approved'){ say('Approved. Connecting...','ok'); land(d.token); }
      else if(d.state==='denied'){ say('The PC denied this device.','err'); B.disabled=false; }
      else if(d.state==='expired'){ say('Request expired. Start again on the PC.','err'); B.disabled=false; }
      else setTimeout(function(){ poll(id,n+1); },1500);
   })
   .catch(function(){ setTimeout(function(){ poll(id,n+1); },2000); });
}

T.addEventListener('keydown',function(e){ if(e.key==='Enter') go(); });
// If a token is already stored from a previous visit, use it rather than
// making the user retype anything.
(function(){ var t=null; try{ t=localStorage.getItem('nd_token'); }catch(e){}
  if(t){ say('Trying the token saved on this device...','wait');
         fetch('/api/ping',{method:'POST',headers:{'Content-Type':'application/json','X-ND-Token':t},body:'{}'})
          .then(function(r){return r.json()})
          .then(function(d){ if(d&&d.ok) land(t); else say('','') ; })
          .catch(function(){ say('',''); }); }
})();
</script></body></html>"""

SERVE_SELFCHECK_SEC = 45      # how often the server proves it can answer
SERVE_SELFCHECK_FAILS = 3     # consecutive failures before it is called wedged
_serve_state = {"restarts": 0, "last_ok": 0.0, "last_fail": "",
                # shutdown() makes serve_forever return CLEANLY, exactly like a
                # real stop. Without this flag the self-check's restart would be
                # indistinguishable from "the user closed the window", and would
                # shut the server down for good instead of reviving it.
                "force_restart": False}


def _serve_supervised(srv):
    """Run the accept loop so that it cannot die silently.

    The failure this fixes, observed 2026-09-07 during an unattended T3 batch:
    ND was alive, port 7788 was still LISTENING, 26 threads, no blocking child
    processes -- and it answered nothing. Connections went straight to
    TIME_WAIT. variance.py's alive-guard stopped the batch, which is the only
    reason it was noticed at all.

    serve_forever ran on a bare daemon thread with nothing catching exceptions.
    The socket stays LISTENING because the PROCESS owns it, so from outside a
    dead accept loop looks exactly like a busy one. ThreadingMixIn.process_request
    calls Thread.start(), and a RuntimeError from that propagates straight out
    of the loop -- which is reachable when handles or threads are exhausted, as
    they were by the run_shell pipes that hung for 34 minutes the same night.

    A clean return means shutdown() was called and is a real stop. An exception
    is a crash: log it with the traceback that was previously lost, and start
    accepting again.
    """
    import traceback as _tb
    while True:
        try:
            srv.serve_forever(poll_interval=0.5)
            if _serve_state.get("force_restart"):
                _serve_state["force_restart"] = False
                log("accept loop stopped for a forced restart -- resuming", "warn")
                time.sleep(0.5)
                continue
            log("HTTP accept loop stopped cleanly", "info")
            return
        except Exception as e:
            _serve_state["restarts"] += 1
            _serve_state["last_fail"] = repr(e)[:200]
            log("HTTP accept loop CRASHED: " + repr(e)[:160], "error")
            for _line in _tb.format_exc().splitlines()[-6:]:
                log("  " + _line[:150], "error")
            time.sleep(1.0)
            log("restarting the accept loop (restart #"
                + str(_serve_state["restarts"]) + ")", "warn")


def _serve_selfcheck(srv, port):
    """Prove from outside that the server still answers, and restart it if not.

    A crash is not the only way to stop serving; the loop can be alive and still
    wedged. Nothing inside the process can tell the difference, so this asks the
    same question a client would: make a real request to /api/ping, which is
    auth-exempt, and count consecutive failures.
    """
    fails = 0
    url = "http://127.0.0.1:" + str(port) + "/api/ping"
    while True:
        time.sleep(SERVE_SELFCHECK_SEC)
        try:
            # /api/ping is POST-only; a GET returns 404. That mattered more than
            # it looks: the first version used GET, read the 404 as a failure,
            # and forced a restart every two minutes on a server that was
            # working perfectly.
            req = urllib.request.Request(url, data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10):
                pass
            fails = 0
            _serve_state["last_ok"] = time.time()
            continue
        except urllib.error.HTTPError as e:
            # ANY status line proves the accept loop is alive and handlers are
            # running. A wedged server does not answer at all. Treating 404 or
            # 500 as "not serving" is what made the first version restart a
            # healthy server, so this is deliberately a success.
            fails = 0
            _serve_state["last_ok"] = time.time()
            _serve_state["last_fail"] = "answered " + str(e.code) + " (still serving)"
            continue
        except Exception as e:
            fails += 1
            log("self-check failed (" + str(fails) + "/"
                + str(SERVE_SELFCHECK_FAILS) + "): " + repr(e)[:120], "warn")
            if fails >= SERVE_SELFCHECK_FAILS:
                _serve_state["restarts"] += 1
                _serve_state["last_fail"] = "wedged: " + repr(e)[:160]
                log("the server is listening but not answering -- forcing the "
                    "accept loop to restart", "error")
                _serve_state["force_restart"] = True
                try:
                    srv.shutdown()          # makes serve_forever return
                except Exception as _e:
                    log("shutdown() failed: " + repr(_e)[:120], "error")
                fails = 0


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    # Browsers resolve "localhost" to ::1 first. Binding IPv4 only meant every
    # single request waited ~2s for the IPv6 attempt to fail before retrying on
    # 127.0.0.1 — measured 2.04s vs 0.00s. Dual-stack removes that entirely.
    address_family = socket.AF_INET6
    # A device long-poll parks a connection for ~25s, and a tab switch fires a
    # dozen requests at once, so the default backlog of 5 is far too small.
    request_queue_size = 64

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except Exception:
            pass
        self.allow_reuse_address = True
        HTTPServer.server_bind(self)




# --- Mobile layout ----------------------------------------------------------
# Injected into <head> only for phone user agents (or ?m=1). The desktop UI is
# a three-column layout - top bar, left rail, sidebar, panel - which on a
# 380px screen leaves almost nothing for the actual content. Rather than ship a
# second UI to keep in sync, this restyles the one that exists:
#   * left rail and sidebar become an off-canvas drawer behind a hamburger
#   * CHAT is just the log plus the composer, full height
#   * ELENA is just the orb plus its controls; the transcript is a bottom sheet
MOBILE_LAYOUT = """
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<style id="nd-mobile">
/* injected only for phones (or ?m=1) - no viewport gate needed */
  html,body{overflow:hidden;-webkit-text-size-adjust:100%;}
  #app{height:100dvh;display:flex;flex-direction:column;}

  /* ---- top bar: brand + status only ---- */
  #topbar{padding:5px 8px 5px 52px !important;gap:6px;flex-wrap:nowrap;min-height:44px;}
  #topbar .tb-btn,#topbar .tb-sep{display:none !important;}
  /* The model selector must stay reachable. Hiding it meant a phone had
     no way to choose a model, and chat answered '[No model selected]'
     which is indistinguishable from the agent hanging. It moves into
     the drawer instead of disappearing. */
  #topbar #model-sel{display:none !important;}
  #nd-model-slot{padding:8px 10px;border-bottom:1px solid var(--border,#1c2733);}
  #nd-model-slot label{display:block;font-size:9px;color:var(--muted,#5a7a6a);
      letter-spacing:1px;margin-bottom:4px;}
  #nd-model-slot select{width:100%;background:#000;color:var(--accent,#00ff9c);
      border:1px solid var(--border,#1c2733);padding:9px;font-size:14px;border-radius:4px;}
  #logo-top,#version-badge{display:none;}
  #logo-main{font-size:12px !important;letter-spacing:.5px;white-space:nowrap;}
  #conn-badge{font-size:9px;padding:3px 7px;margin-left:auto;flex:0 0 auto;}
  #model-size-warn{font-size:9px;}

  /* ---- drawer: nav rail + sidebar ---- */
  #nav,#sidebar{position:fixed;left:0;width:74vw;max-width:300px;z-index:1200;
      background:var(--panel,#0a0e14);border-right:1px solid var(--border,#1c2733);
      transform:translateX(-102%);transition:transform .22s ease;overflow-y:auto;}
  #nav{top:0;height:auto;max-height:52vh;padding-top:50px;display:block !important;}
  #sidebar{top:52vh;bottom:0;z-index:1199;}
  body.nd-drawer #nav,body.nd-drawer #sidebar{transform:translateX(0);}
  #nav .nav-tab{font-size:15px;padding:15px 18px;}

  #nd-scrim{position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:1150;
      opacity:0;pointer-events:none;transition:opacity .22s;}
  body.nd-drawer #nd-scrim{opacity:1;pointer-events:auto;}
  #nd-burger{position:fixed;top:5px;left:6px;z-index:1300;width:38px;height:34px;
      background:var(--panel,#0a0e14);border:1px solid var(--accent,#00ff9c);
      color:var(--accent,#00ff9c);border-radius:5px;font-size:16px;line-height:1;}

  /* ---- panels fill the remaining space ---- */
  #main{flex:1 1 auto;min-height:0;display:block !important;position:relative;}
  .tab-panel{position:absolute;inset:0;padding:0 !important;overflow:hidden;}

  /* anything laid out as side-by-side columns stacks */
  #setup-columns{display:block !important;}
  #panel-image > div,#panel-video > div,#panel-gallery > div{max-width:100% !important;}

  /* ---- CHAT ---- */
  /* Defensive: an older build of the Android app injected
       #panel-<tab>{display:block !important} after load, pinning one panel on
       top of every other tab. A plain .tab-panel:not(.vis) rule cannot beat an
       ID selector, so this qualifies with body + :not() to outrank it (1,1,1
       vs 1,0,0) and keep the server authoritative about layout. */
  body #panel-chat:not(.vis), body #panel-image:not(.vis),
  body #panel-video:not(.vis), body #panel-gallery:not(.vis),
  body #panel-agent:not(.vis), body #panel-setup:not(.vis){display:none !important;}

  /* Only style the VISIBLE panel. Forcing display on #panel-chat and
     #panel-agent overrode .tab-panel{display:none}, so every panel was
     rendered at once and Elena sat on top of whatever tab you picked. */
  #panel-chat.vis{display:flex !important;flex-direction:column;}
  #workspace-bar,#chat-tabs-bar,#chat-progress{flex:0 0 auto;}
  #workspace-bar{font-size:9px;padding:3px 8px !important;}
  #chat-tabs-bar{padding:3px 6px !important;}
  #toolbar{flex:0 0 auto;display:none !important;padding:4px 6px !important;
      flex-wrap:wrap;gap:4px;}
  body.nd-tools #toolbar{display:flex !important;}
  #chat-container{flex:1 1 auto;min-height:0 !important;height:auto !important;
      overflow-y:auto;-webkit-overflow-scrolling:touch;padding:8px !important;}
  #chat-container > div{min-height:0 !important;height:auto !important;
      max-height:none !important;overflow:visible !important;}
  .msg{max-width:94% !important;}
  .mb{font-size:13px;line-height:1.45;}
  .ma{opacity:1 !important;}                 /* no hover on touch */
  #input-bar{flex:0 0 auto;padding:6px !important;gap:5px;}
  #ir{min-height:44px;font-size:16px;}       /* 16px stops iOS zoom-on-focus */
  #recent-panel{display:none !important;}
  #nd-tools-btn{position:absolute;top:2px;right:6px;z-index:20;font-size:10px;
      background:transparent;border:1px solid var(--border,#1c2733);
      color:var(--muted,#5a7a6a);border-radius:4px;padding:3px 8px;}

  /* ---- ELENA ---- */
  #panel-agent.vis{display:block !important;}
  #ag-wrap{display:block !important;height:100%;}
  body.nd-tab-agent #ag-stage{position:absolute;inset:0;display:flex !important;flex-direction:column;
      align-items:center;justify-content:center;padding:8px;overflow-y:auto;}
  #ag-orb{max-width:56vw;max-height:56vw;}
  #ag-offbar,#ag-auto-banner{font-size:10px;}
  #ag-controls{flex-wrap:wrap;justify-content:center;gap:8px;}

  /* transcript + composer become a bottom sheet */
  body.nd-tab-agent #ag-side{position:fixed !important;left:0;right:0;bottom:0;top:auto !important;
      width:100% !important;max-width:none !important;height:68dvh;z-index:1100;
      transform:translateY(102%);transition:transform .24s ease;
      background:var(--panel,#0a0e14);border-top:2px solid var(--accent,#00ff9c);
      display:flex !important;flex-direction:column;}
  body.nd-tab-agent.nd-sheet #ag-side{transform:translateY(0);}
  /* a position:fixed child escapes its hidden parent - pin it shut */
  body:not(.nd-tab-agent) #ag-side{display:none !important;}
  #ag-side-head{flex:0 0 auto;}
  #ag-log{flex:1 1 auto;min-height:0 !important;height:auto !important;
      max-height:none !important;overflow-y:auto;}
  #ag-compose{flex:0 0 auto;}
  #ag-input{font-size:16px;}
  #nd-sheet-btn{display:none;position:fixed;right:12px;bottom:14px;z-index:1120;
      background:var(--panel,#0a0e14);border:1px solid var(--accent,#00ff9c);
      color:var(--accent,#00ff9c);border-radius:22px;padding:11px 18px;font-size:12px;
      box-shadow:0 3px 14px rgba(0,0,0,.6);}
  body.nd-tab-agent #nd-sheet-btn{display:block;}
  body.nd-tab-agent.nd-sheet #nd-sheet-btn{bottom:calc(68dvh + 10px);}

</style>
<script>
(function(){
  function ready(fn){ document.readyState!=='loading' ? fn()
                      : document.addEventListener('DOMContentLoaded',fn); }
  ready(function(){

    function mk(tag,id,txt){ var e=document.createElement(tag); e.id=id;
                             if(txt) e.textContent=txt; document.body.appendChild(e); return e; }
    var burger=mk('button','nd-burger'); burger.innerHTML='&#9776;';
    // Relocate (do not clone) the model selector: cloning would lose every
    // listener the app already attached to it.
    var sel=document.getElementById('model-sel'), nav=document.getElementById('nav');
    if (sel && nav){
      var slot=document.createElement('div'); slot.id='nd-model-slot';
      var lab=document.createElement('label'); lab.textContent='MODEL';
      slot.appendChild(lab); slot.appendChild(sel);
      sel.style.display='block';
      nav.insertBefore(slot, nav.firstChild);
      sel.addEventListener('change',function(){ document.body.classList.remove('nd-drawer'); });

      // Pick a sensible chat model if the stored one is empty or a vision
      // model. The selector defaulted to llava:7b, so every phone message went
      // to an image model - which answers text badly or not at all, and looks
      // exactly like the agent being broken.
      var VIS=/llava|minicpm-v|moondream|bakllava|qwen2?\.?5?-?vl|embed/i;
      function goodModel(){
        if (sel.value && !VIS.test(sel.value)) return;
        fetch('/api/roster',{method:'POST',headers:{'Content-Type':'application/json',
              'X-ND-Token':(function(){try{return localStorage.getItem('nd_token')||''}catch(e){return ''}})()},
              body:'{}'})
          .then(function(r){return r.json()})
          .then(function(d){
            var want=d && d.handler; if(!want) return;
            for (var i=0;i<sel.options.length;i++){
              if (sel.options[i].value.indexOf(want)>-1){
                sel.selectedIndex=i;
                sel.dispatchEvent(new Event('change',{bubbles:true}));
                break;
              }
            }
          }).catch(function(){});
      }
      setTimeout(goodModel,1500); setTimeout(goodModel,4000);
    }
    var scrim =mk('div','nd-scrim');
    var sheet =mk('button','nd-sheet-btn','TRANSCRIPT');

    function drawer(on){ document.body.classList.toggle('nd-drawer', on); }
    burger.onclick=function(){ drawer(!document.body.classList.contains('nd-drawer')); };
    scrim.onclick =function(){ drawer(false); };
    sheet.onclick =function(){ document.body.classList.toggle('nd-sheet'); };

    // CHAT toolbar is hidden by default; give it a toggle so the log gets the screen
    var pc=document.getElementById('panel-chat');
    if (pc){ var t=document.createElement('button'); t.id='nd-tools-btn'; t.textContent='TOOLS';
             t.onclick=function(){ document.body.classList.toggle('nd-tools'); };
             pc.appendChild(t); }

    // mirror the visible tab onto <body> so CSS can target it
    var TABS=['chat','image','video','gallery','agent','setup'];
    function mark(){
      TABS.forEach(function(t){
        var p=document.getElementById('panel-'+t);
        document.body.classList.toggle('nd-tab-'+t, !!(p && p.classList.contains('vis')));
      });
    }
    if (typeof window.switchTab==='function'){
      var orig=window.switchTab;
      window.switchTab=function(){ var r=orig.apply(this,arguments);
        drawer(false); document.body.classList.remove('nd-sheet');
        setTimeout(mark,0); return r; };
    }
    mark(); setInterval(mark,1200);

    // keep the chat pinned to the newest message
    var cc=document.getElementById('chat-container');
    if (cc && window.MutationObserver){
      new MutationObserver(function(){
        var v=cc.querySelector('[id^=chatview],div');
        cc.scrollTop=cc.scrollHeight;
      }).observe(cc,{childList:true,subtree:true});
    }

    // Explain a missing microphone properly. navigator.mediaDevices is UNDEFINED
    // (not "denied") in an insecure context, which is every origin except
    // https:// and localhost. No permission prompt will ever appear, so the
    // stock "allow microphone access" message sends you looking in the wrong
    // place. Say what is actually wrong.
    if (!window.isSecureContext || !navigator.mediaDevices){
      var msg='Microphone needs HTTPS. This page is '+location.protocol+'//'+location.hostname+
              ' - browsers only expose a mic on https:// or localhost. '+
              'On the PC run:  tailscale serve --bg --https=443 http://127.0.0.1:7788  '+
              'then open the https ts.net address.';
      setInterval(function(){
        ['mic-status','ag-hint','ag-substate'].forEach(function(id){
          var el=document.getElementById(id);
          if (el && /mic blocked|enumerateDevices|TypeError|allow microphone/i.test(el.textContent)){
            el.textContent=msg; el.style.color='var(--yellow,#ffb000)';
          }
        });
      },1500);
    }
  });
})();
</script>
"""

# --- UI shell: WebView2 app window vs the default browser --------------------
def _webview_available():
    try:
        import webview          # noqa: F401
        return True
    except Exception:
        return False

def install_webview():
    """pywebview drives the WebView2 runtime that ships with Windows 11.

    Install into sys.executable, NOT the Heretic venv. NeuralDock is normally
    launched with the system Python, so installing into the venv succeeds and
    then `import webview` still fails in the process that actually needs it -
    which looked exactly like the install having done nothing.
    """
    log(f"Installing pywebview into {sys.executable} ...", "info")
    ok, out, err = run(f'"{sys.executable}" -m pip install pywebview')
    if not ok and "externally-managed-environment" in (err or "") + (out or ""):
        # Some Python installs (uv-managed, distro-packaged) refuse plain pip
        log("Interpreter is externally managed; retrying with --break-system-packages", "warn")
        ok, out, err = run(f'"{sys.executable}" -m pip install --break-system-packages pywebview')
    log("pywebview installed - relaunch with --window" if ok
        else f"pywebview install failed: {(err or out)[:300]}",
        "ok" if ok else "error")
    return ok

def choose_shell():
    """--window / --browser beat config; 'auto' prefers the window if usable."""
    if "--window" in sys.argv:  return "webview"
    if "--browser" in sys.argv: return "browser"
    pref = str(_config.get("ui_shell", "auto")).lower()
    if pref == "webview": return "webview"
    if pref == "browser": return "browser"
    return "webview" if _webview_available() else "browser"

def open_ui(url):
    """Open the UI and, for the window shell, BLOCK until it is closed.

    Returns True if this call owns the main thread from here on.
    """
    shell = choose_shell()
    if shell == "webview":
        if not _webview_available():
            log("pywebview not installed - falling back to the browser "
                "(run with --install-webview to add it)", "warn")
        else:
            try:
                import webview
                log(f"Opening {PRODUCT} in a WebView2 window "
                    "(run with --browser to use Chrome instead)", "ok")
                # text_select=True is REQUIRED.
                # pywebview defaults it to False and then injects
                #     * { user-select: none }
                # via its own customize.js. That is why chat text could not be
                # selected or copied in the window shell while working fine in
                # the browser -- nothing in NeuralDock_ui.html was at fault.
                webview.create_window(f"{PRODUCT} v{VERSION}  //  ESTEEF.AI", url,
                                      width=1600, height=1000, min_size=(900, 620),
                                      background_color="#05070A",
                                      text_select=True, zoomable=True)
                # gui=edgechromium is the WebView2 backend on Windows.
                #
                # debug= is not just devtools here. In pywebview's edgechromium
                # backend it drives three WebView2 settings directly:
                #     settings.AreDefaultContextMenusEnabled  = _state['debug']
                #     settings.AreBrowserAcceleratorKeysEnabled = _state['debug']
                #     settings.AreDevToolsEnabled             = _state['debug']
                # With it off there is NO right-click menu at all, which is why
                # misspelled words were underlined but offered no suggestions --
                # WebView2 serves spelling corrections from the default context
                # menu. Leaving it on also restores Ctrl+F and friends.
                # Set "ui_window_devtools": false in the config to turn it off.
                #
                # BUT: pywebview also AUTO-OPENS the DevTools window whenever
                # debug is on, which is why a blank DevTools pane appeared at
                # every launch. That is a separate setting, so turn it off and
                # keep the context menu. F12 still opens DevTools on demand.
                try:
                    webview.settings['OPEN_DEVTOOLS_IN_DEBUG'] = bool(
                        _config.get("ui_window_open_devtools", False))
                except Exception:
                    pass
                webview.start(gui="edgechromium", private_mode=False,
                              debug=bool(_config.get("ui_window_devtools", True)))
                return True
            except Exception as e:
                log(f"WebView2 window failed ({e}) - falling back to the browser", "warn")
    webbrowser.open(url)
    return False

# --- Device pairing (short-lived code + explicit approval) -------------------
_pair_code   = {"code": None, "exp": 0}
_pair_reqs   = {}          # req_id -> {device, ip, state, at}
PAIR_TTL     = 300         # a pairing code is good for 5 minutes

def pair_new_code():
    """Rotate the pairing code. Short and unambiguous - no 0/O or 1/I."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(alphabet) for _ in range(6))
    _pair_code["code"] = code
    _pair_code["exp"] = time.time() + PAIR_TTL
    _pair_reqs.clear()
    return code

def pair_code_valid(code):
    return (bool(_pair_code["code"])
            and time.time() < _pair_code["exp"]
            and secrets.compare_digest((code or "").upper().strip(), _pair_code["code"]))

def pair_payload():
    """What the QR encodes: where to reach this PC, and the code - never the token."""
    return json.dumps({"h": lan_ip(), "p": PORT, "c": _pair_code["code"]}, separators=(",", ":"))

def pair_qr_png(text):
    """Render a QR via the Heretic venv, which has the qrcode package.

    Generated by a real library rather than hand-rolled: a subtly wrong QR that
    scans to a corrupt address is worse than no QR at all.
    """
    script = (
        "import sys,qrcode,io;"
        "q=qrcode.QRCode(border=2,box_size=8);"
        "q.add_data(sys.argv[1]);q.make(fit=True);"
        "img=q.make_image(fill_color='black',back_color='white');"
        "b=io.BytesIO();img.save(b,format='PNG');"
        "sys.stdout.buffer.write(b.getvalue())"
    )
    try:
        r = subprocess.run([str(VENV_PY), "-c", script, text],
                           capture_output=True, timeout=25)
        return r.stdout if r.returncode == 0 and r.stdout[:4] == b"\x89PNG" else None
    except Exception as e:
        log(f"QR generation failed: {e}", "warn")
        return None

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def client_ip(self):
        # honour a proxy header only from a local reverse proxy
        return self.client_address[0] if self.client_address else ""

    def is_local(self):
        """True only for a browser on THIS machine.

        Critical subtlety: `tailscale serve` terminates TLS and proxies to
        127.0.0.1, so a phone anywhere in the world arrives with a loopback
        client IP. Treating that as 'local' would hand every tailnet device
        unauthenticated agent access to this PC. Tailscale stamps proxied
        requests with the caller's identity headers, so their presence is a
        reliable 'this did NOT originate on this machine' signal.
        """
        if self.client_ip() not in _LOCAL_IPS:
            return False
        for h in ("Tailscale-User-Login", "Tailscale-User-Name",
                  "Tailscale-Headers", "X-Forwarded-For", "X-Forwarded-Proto"):
            if self.headers.get(h):
                return False
        return True

    def cookie_token(self):
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "nd_token":
                return urllib.parse.unquote(v)
        return ""

    def authed(self):
        if self.is_local() and not _config.get("require_local_auth", False):
            return True
        # A cookie is checked alongside the header and the query parameter.
        # The UI keeps its token in localStorage and DELETES it on any 401 -
        # so a single unauthenticated request permanently logs the phone out
        # until it re-pairs. A cookie rides on every same-origin request
        # automatically, with no JS timing to get wrong, so the session
        # survives that.
        tok = (self.headers.get("X-ND-Token")
               or (self.headers.get("Authorization", "").replace("Bearer ", "").strip())
               or urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("token", [""])[0]
               or self.cookie_token())
        return bool(tok) and secrets.compare_digest(tok, api_token())

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Connection","close")
        self.end_headers()
        # Write in chunks to avoid WinError 10053 on large responses
        chunk_size = 65536  # 64KB
        for i in range(0, len(body), chunk_size):
            try:
                self.wfile.write(body[i:i+chunk_size])
                self.wfile.flush()
            except (BrokenPipeError, ConnectionAbortedError, OSError):
                break  # Client disconnected — not an error

    def serve_elena(self):
        """Serve Elena's interface, read fresh each request.

        No caching on purpose: this file is still being designed, and a stale
        copy in the browser is indistinguishable from an edit that did not take.
        """
        if not ELENA_FILE.exists():
            self.send_json({"error": "elena_ui.html not found",
                            "hint": "expected beside NeuralDock_launcher.py"}, 404)
            return
        content = ELENA_FILE.read_bytes()
        if PORTABLE:   # the page rebrands itself, but the tab title shows first
            content = content.replace(b"<title>Elena</title>", f"<title>{PRODUCT} // Esteef.Ai</title>".encode())
        # Same token bootstrap as the main UI: a device opening /elena?token=...
        # authenticates for THIS request, but every fetch afterwards reads
        # nd_token from localStorage, which a fresh pairing link has never set.
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        qt = (q.get("token") or [""])[0]
        if qt and secrets.compare_digest(qt, api_token()):
            inject = ("<script>try{localStorage.setItem('nd_token',%s);}catch(e){}</script>"
                      % json.dumps(qt)).encode("utf-8")
            content = content.replace(b"</head>", inject + b"</head>", 1)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(content))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def serve_html(self):
        content = HTML_FILE.read_bytes() if HTML_FILE.exists() else b"<h1>UI not found</h1>"
        head = []

        # Bootstrap the token into localStorage when the page was opened via a
        # ?token= link. The page authenticated fine, but every XHR afterwards
        # reads nd_token from localStorage - which a freshly-opened pairing link
        # has never set. That is why a paired phone loaded the UI and then
        # showed "not authorised" on its very first status poll.
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        qt = (q.get("token") or [""])[0]
        if qt and secrets.compare_digest(qt, api_token()):
            head.append("<script>try{localStorage.setItem('nd_token',%s);}catch(e){}</script>"
                        % json.dumps(qt))

        # Phones get a layout pass; ?m=1 / ?m=0 forces it either way for testing
        ua = (self.headers.get("User-Agent") or "").lower()
        force = (q.get("m") or [""])[0]
        mobile = force == "1" or (force != "0" and
                                  any(k in ua for k in ("android", "iphone", "ipad", "mobile")))
        if mobile:
            head.append(MOBILE_LAYOUT)

        if head:
            inject = "".join(head).encode("utf-8")
            if b"</head>" in content:
                content = content.replace(b"</head>", inject + b"</head>", 1)
            else:
                content = inject + content

        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",len(content))
        # Never cache the shell. Android WebView happily serves a stale copy,
        # which means a UI fix on this machine can appear to have done nothing
        # on the phone - and you end up debugging a version that no longer
        # exists. The page is a few hundred KB over a LAN or tailnet; refetching
        # it costs nothing next to that confusion.
        self.send_header("Cache-Control","no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma","no-cache")
        self.send_header("Expires","0")
        # Pin the session with a cookie so it cannot be lost by the UI's
        # localStorage being cleared. Lax is right here: it still rides on
        # normal navigation but not on cross-site POSTs.
        if qt and secrets.compare_digest(qt, api_token()):
            self.send_header("Set-Cookie",
                             "nd_token=%s; Path=/; Max-Age=31536000; SameSite=Lax"
                             % urllib.parse.quote(qt))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.end_headers()

    def do_GET(self):
        # Route on the path WITHOUT the query string. authed() accepts a
        # ?token= parameter, but this comparison used the raw self.path, so
        # "/?token=..." never matched "/" and fell through to a 404 - which
        # silently broke every pairing link this app generates, and left the
        # phone stuck on the pair page with no way through.
        bare_path = urllib.parse.urlparse(self.path).path or "/"
        # Philibert opens on the simple view; the full interface stays at /full.
        if PORTABLE and bare_path in ("/", "/index.html"):
            bare_path = "/elena"
        elif bare_path == "/full":
            bare_path = "/"
        if bare_path in ("/", "/index.html"):
            if not self.authed():
                page = PAIR_PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type","text/html; charset=utf-8")
                self.send_header("Content-Length", len(page))
                self.end_headers()
                self.wfile.write(page)
                return
            self.serve_html()
            return
        if bare_path == "/elena_mark.js":
            # Kept out of the page so the mark can be reused elsewhere later.
            # Same no-cache rule: it is still being tuned.
            f = Path(__file__).parent / "elena_mark.js"
            if not f.exists():
                self.send_json({"error": "elena_mark.js not found"}, 404)
                return
            js = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", len(js))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(js)
            return
        if bare_path in ("/elena", "/elena.html"):
            # Same auth shape as "/": an unpaired device gets the pairing page
            # rather than a 401 it cannot act on.
            if not self.authed():
                page = PAIR_PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", len(page))
                self.end_headers()
                self.wfile.write(page)
                return
            self.serve_elena()
            return
        if not self.authed():
            self.send_json({"error":"unauthorized","hint":"Send X-ND-Token. Pair in Setup > Devices."}, 401)
            return
        if self.path == "/api/status":
            c = get_cache()
            _cpu_now = cpu_fallback_models()
            with _lock:
                log_snap  = list(status_log[-80:])
                pull_snap = dict(_pull_status)
            self.send_json({**c,"log":log_snap,"setup_running":setup_running,"pulls":pull_snap,
                              "portable":PORTABLE,"product":PRODUCT,"online":internet_on(),"cpu_fallback":_cpu_now,
                              "ollama_models_dir":_config.get("ollama_models_dir",""),
                              "version":VERSION,
                              "model_registry":get_model_registry(),
                              "model_fit":model_fit_map(),
                              "cfg_comfyui":_config.get("comfyui_dir",""),
                              "cfg_gallery":_config.get("gallery_dir",""),
                              "cfg_install_base":_config.get("install_base",""),
                              "gates":_gate_config(),
                              "serving":dict(_serve_state)})
        elif self.path == "/api/usage":
            self.send_json(usage_report())
        elif self.path == "/api/sysmon":
            self.send_json(sysmon_snapshot())
        elif self.path == "/api/vault_graph":
            self.send_json(vault_graph())
        elif self.path.startswith("/api/vault_activity"):
            try:
                _since = float((urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                                .get("since") or ["0"])[0])
            except ValueError:
                _since = 0.0
            self.send_json(vault_activity(_since))
        elif self.path == "/api/models":
            self.send_json({"models":_get_models()})
        elif self.path == "/api/gallery":
            self.send_json({"items": get_gallery_items()})
        elif self.path == "/api/scan_results":
            with _lock: snap = list(_scan_results)
            self.send_json({"results": snap})
        elif self.path == "/api/drives":
            drives = [str(d) for d in get_all_drives()]
            self.send_json({"drives": drives})
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length",0))
        body   = json.loads(self.rfile.read(length)) if length else {}
        path   = self.path

        if path == "/api/ping":
            # Used by the pairing page and by device clients to test a token.
            self.send_json({"ok": self.authed(), "app": "NeuralDock", "version": VERSION})
            return
        # AUTH_EXEMPT was previously declared but never read - only /api/ping was
        # special-cased above. That made /api/pair_claim return 401 to a phone,
        # which is fatal: pairing is precisely the request you cannot yet
        # authenticate. Local testing hid it, because is_local() bypasses auth
        # entirely, so the exempt path was never exercised from 127.0.0.1.
        if path not in AUTH_EXEMPT and not self.authed():
            self.send_json({"error":"unauthorized","hint":"Send X-ND-Token. Pair in Setup > Devices."}, 401)
            return

        if PORTABLE and path.startswith("/api/philibert/"):
            # Model catalog, downloads and updates for the drive (nd_philibert.py).
            import nd_philibert
            self.send_json(nd_philibert.handle(path, body, log))
            return

        if path == "/api/setup":
            if setup_running:
                self.send_json({"started":False,"msg":"Already running"})
            else:
                threading.Thread(target=run_full_setup, daemon=True).start()
                self.send_json({"started":True})

        elif path == "/api/set_config":
            for k,v in body.items():
                _config[k] = v
            save_config()
            # Actually create the directories now
            for key in ["install_base","comfyui_dir","gallery_dir"]:
                val = _config.get(key)
                if val:
                    try:
                        Path(val).mkdir(parents=True, exist_ok=True)
                        log(f"Created directory: {val}", "ok")
                    except Exception as e:
                        log(f"Could not create {val}: {e}", "warn")
            threading.Thread(target=refresh_status_cache, daemon=True).start()
            self.send_json({"ok":True})

        elif path == "/api/install":
            comp = body.get("component","")
            dispatch = {
                "pytorch":install_pytorch,"heretic":install_heretic,
                "whisper":install_whisper,"tts":install_tts,
                "extras":install_extras,  "hf_hub":install_hf_hub,
                "cogvideo":install_cogvideo,
                "animatediff":install_animatediff_node,"sd_models":ensure_sd_models,
                "comfyui":install_comfyui,
            }
            fn = dispatch.get(comp)
            if fn:
                threading.Thread(target=fn, daemon=True).start()
                self.send_json({"installing":comp})
            else:
                self.send_json({"error":f"unknown: {comp}"},400)

        elif path == "/api/chat":
            model       = sanitize_model_name(body.get("model",""))
            messages    = body.get("messages",[])
            workspace   = body.get("workspace","")
            allow_all   = body.get("allow_all",False)
            approved    = set(body.get("approved_tools",[]))
            image_b64   = body.get("image","")  # base64 screenshot for vision

            # If image attached, inject it into the last user message
            if image_b64 and messages:
                # Strip data URL prefix
                if "," in image_b64:
                    image_b64 = image_b64.split(",",1)[1]
                # Add image to last user message in Ollama format
                last = messages[-1]
                if last.get("role") == "user":
                    messages = list(messages)
                    messages[-1] = {
                        "role": "user",
                        "content": last.get("content",""),
                        "images": [image_b64]
                    }

            if not model:
                # Fall back to the handler rather than refusing. The phone
                # layout hides the topbar model selector, so a mobile client
                # has no way to choose one - and "[No model selected]" is
                # indistinguishable from the agent hanging.
                model = handler_model()
                if model:
                    log(f"No model in request; using handler '{model}'", "info")
                else:
                    self.send_json({"reply":"[No model selected, and no handler_model is set. "
                                             "Pick one in Setup > Routing.]"}); return

            # Start a resumable background job and return immediately. The browser
            # polls /api/chat_result, so a reload/disconnect no longer loses the run.
            job_id = body.get("req_id") or str(uuid.uuid4())[:8]
            with _lock:
                _chat_status[job_id] = {"stage":"thinking","detail":"Queued...","pct":3,"start":time.time()}
            _update_chat_job(job_id, status="running", started=time.time(), model=model,
                             prompt=(messages[-1].get("content","")[:400] if messages else ""))
            threading.Thread(target=run_chat_job,
                             args=(job_id, model, messages, workspace or None, allow_all, approved,
                                   bool(body.get("agent_mode", False)),
                                   bool(body.get("plain", False)),
                                   body.get("session_id") or None),
                             daemon=True).start()
            self.send_json({"job_id": job_id, "status": "running"})

        elif path == "/api/chat_result":
            jid = body.get("job_id","")
            with _lock:
                rec = dict(_chat_jobs.get(jid, {}))
                st  = dict(_chat_status.get(jid, {}))
            if not rec and jid:
                f = CHAT_JOBS_DIR / f"{jid}.json"      # survives a launcher restart
                if f.exists():
                    try: rec = json.loads(f.read_text(encoding="utf-8"))
                    except Exception: rec = {}
            if not rec:
                self.send_json({"status":"unknown"}); return
            rec["progress"] = st
            self.send_json(rec)

        elif path == "/api/chat_permit":
            # The answer to a parked permission request. Approved keys join the
            # run's pending set; anything named as denied (or simply left out)
            # comes back to the model as a refusal.
            jid = body.get("job_id", "")
            approved = [str(k) for k in (body.get("approved") or []) if k]
            denied   = [str(k) for k in (body.get("denied") or []) if k]
            if not resolve_permission(jid, approved, denied):
                self.send_json({"ok": False, "msg": "no job is waiting on that id"}); return
            log(f"Permission answered for {jid}: {len(approved)} approved, "
                f"{len(denied)} denied", "info")
            self.send_json({"ok": True})

        elif path == "/api/chat_answer":
            # The answer to a parked ask_user question. It resumes the SAME turn
            # with the answer delivered as the tool result, so the model carries
            # on from the decision rather than starting over.
            jid = body.get("job_id", "")
            answer = str(body.get("answer") or "")[:4000]
            option_id = str(body.get("option_id") or "")[:80]
            if not resolve_question(jid, answer, option_id):
                self.send_json({"ok": False, "msg": "no job is waiting for an answer on that id"}); return
            log(f"Question answered for {jid}: "
                f"{('option ' + option_id) if option_id else 'free text'}", "info")
            self.send_json({"ok": True})

        elif path == "/api/browser_cast":
            # Start/stop the managed browser's screencast, and show or hide its
            # off-screen window. This is how "watch it work" and "bring it on
            # screen so I can sign in" are turned on.
            br = nd_browser()
            if not br:
                self.send_json({"ok": False, "msg": "managed browser unavailable"}); return
            act = str(body.get("action") or "").lower()
            msg = ""
            if act in ("start", "on"):   msg = br.start_screencast()
            elif act in ("stop", "off"): msg = br.stop_screencast()
            elif act == "show":          msg = br.set_visible(True)
            elif act == "hide":          msg = br.set_visible(False)
            else: self.send_json({"ok": False, "msg": "action must be start/stop/show/hide"}); return
            self.send_json({"ok": True, "msg": msg})

        elif path == "/api/browser_frame":
            # The latest screencast frame, as a JPEG data string the UI can drop
            # straight into an <img>. Starts the stream on first ask.
            br = nd_browser()
            if not br:
                self.send_json({"ok": False, "msg": "managed browser unavailable"}); return
            if not br._cast:
                br.start_screencast()
            fr = br.latest_frame()
            if not fr:
                self.send_json({"ok": True, "frame": None, "ts": 0}); return
            self.send_json({"ok": True, "frame": fr[0], "ts": fr[1], "mime": "image/jpeg"})

        elif path == "/api/chat_cancel":
            jid = body.get("job_id","")
            if jid:
                _chat_cancel.add(jid)
                log(f"Cancel requested for chat job {jid}", "info")
            self.send_json({"ok": True})

        elif path == "/api/chat_active":
            with _lock:
                active = [dict(v) for v in _chat_jobs.values() if v.get("status") == "running"]
            for a in active:
                a.pop("tool_results", None)
            self.send_json({"jobs": active})

        elif path == "/api/generate_image":
            prompt     = body.get("prompt","")
            negative   = body.get("negative","")
            # SDXL requires dimensions divisible by 64
            raw_w      = int(body.get("width",1024))
            raw_h      = int(body.get("height",1024))
            width      = max(64, (raw_w // 64) * 64)
            height     = max(64, (raw_h // 64) * 64)
            steps      = body.get("steps",20)
            cfg        = body.get("cfg",7.0)
            checkpoint = body.get("checkpoint",None)
            lora       = body.get("lora",None) or None
            lora_str   = float(body.get("lora_strength",0.8) or 0.8)
            denoise    = float(body.get("denoise",0.55) or 0.55)
            insp       = body.get("inspiration","") or ""
            job_id     = str(uuid.uuid4())[:8]
            with _lock:
                _gen_jobs[job_id] = {"status":"starting","result":None,"error":None}
            try:
                init_image = save_input_image(insp) if insp else None
                workflow = build_image_workflow(prompt,negative,width,height,steps,cfg,checkpoint,
                                                lora=lora,lora_strength=lora_str,init_image=init_image,denoise=denoise,
                                                model_kind=body.get("model_kind"))
                threading.Thread(target=run_comfyui_workflow, args=(workflow,job_id,"image"), daemon=True).start()
            except Exception as e:
                log(f"Workflow build failed: {e}", "error")
                with _lock:
                    _gen_jobs[job_id] = {"status":"error","result":None,"error":str(e)}
            self.send_json({"job_id":job_id})

        elif path == "/api/generate_video":
            vtype    = body.get("type","animatediff")
            prompt   = body.get("prompt","")
            negative = body.get("negative","")
            frames   = int(body.get("frames",16))
            fps      = int(body.get("fps",8))
            width    = max(64,(int(body.get("width", 1024 if vtype=="svd" else 512))//64)*64)
            height   = max(64,(int(body.get("height", 576 if vtype=="svd" else 512))//64)*64)
            steps    = int(body.get("steps") or (25 if vtype=="svd" else 20))
            count    = max(1, min(int(body.get("count",1)), 8))
            fmt      = body.get("format","webp")
            overlay  = body.get("overlay") or None
            img_b64  = body.get("image","")
            denoise  = float(body.get("denoise",0.6))
            ckpt     = body.get("checkpoint") or None
            motion   = body.get("motion_module") or None
            post     = {"format": fmt, "overlay": overlay, "fps": fps}
            job_ids  = []
            try:
                for i in range(count):
                    job_id = str(uuid.uuid4())[:8]
                    with _lock:
                        _gen_jobs[job_id] = {"status":"queued","result":None,"error":None,"index":i}
                    if vtype == "cogvideo":
                        cog_models = list_cogvideo_models()
                        if not cog_models:
                            raise Exception(
                                "No CogVideoX model found in the local cache yet. "
                                "If the download is still running, wait for it to finish and retry.")
                        cog_model = ckpt if (ckpt and any(m["name"]==ckpt for m in cog_models)) else cog_models[0]["name"]
                        cog_steps = int(body.get("steps", 0)) or 30  # 30 default: big speedup, minor quality cost
                        cog_params = {"model": cog_model, "prompt": prompt, "negative": negative,
                                      "frames": frames, "steps": cog_steps, "fps": fps}
                        threading.Thread(target=run_cogvideo_job, args=(job_id, cog_params),
                                         kwargs={"post": post}, daemon=True).start()
                        job_ids.append(job_id)
                        continue
                    if vtype == "svd":
                        if not img_b64:
                            raise Exception("Load a source image first — SVD animates a still image.")
                        workflow = build_svd_workflow(img_b64, steps=steps, fps=fps,
                                                      width=width, height=height, frames=frames, checkpoint=ckpt)
                    else:
                        workflow = build_animatediff_workflow(prompt, negative, frames, steps=steps, cfg=7.0,
                                                              width=width, height=height, fps=fps,
                                                              checkpoint=ckpt, motion=motion,
                                                              init_image=(save_input_image(img_b64) if img_b64 else None),
                                                              denoise=denoise)
                    threading.Thread(target=run_comfyui_workflow, args=(workflow,job_id,"video"),
                                     kwargs={"post":post}, daemon=True).start()
                    job_ids.append(job_id)
            except Exception as e:
                log(f"Video workflow build failed: {e}", "error")
                err_id = str(uuid.uuid4())[:8]
                with _lock:
                    _gen_jobs[err_id] = {"status":"error","result":None,"error":str(e)}
                job_ids = [err_id]
            self.send_json({"job_id":job_ids[0],"job_ids":job_ids})

        elif path == "/api/generate_batch":
            """Generate multiple images with same prompt."""
            prompt     = body.get("prompt","")
            negative   = body.get("negative","")
            raw_w      = int(body.get("width",1024))
            raw_h      = int(body.get("height",1024))
            width      = max(64,(raw_w//64)*64)
            height     = max(64,(raw_h//64)*64)
            steps      = body.get("steps",20)
            cfg        = body.get("cfg",7.0)
            checkpoint = body.get("checkpoint",None)
            lora       = body.get("lora",None) or None
            lora_str   = float(body.get("lora_strength",0.8) or 0.8)
            denoise    = float(body.get("denoise",0.55) or 0.55)
            insp       = body.get("inspiration","") or ""
            init_image = save_input_image(insp) if insp else None
            count      = min(int(body.get("count",4)), 30)  # cap at 30
            job_ids    = []
            for i in range(count):
                job_id = str(uuid.uuid4())[:8]
                with _lock:
                    _gen_jobs[job_id] = {"status":"queued","result":None,"error":None,"index":i}
                workflow = build_image_workflow(prompt,negative,width,height,steps,cfg,checkpoint,
                                                lora=lora,lora_strength=lora_str,init_image=init_image,denoise=denoise)
                threading.Thread(
                    target=run_comfyui_workflow,
                    args=(workflow, job_id, "image"),
                    daemon=True
                ).start()
                job_ids.append(job_id)
            self.send_json({"ok":True,"job_ids":job_ids,"count":count})

        elif path == "/api/job_status":
            job_id = body.get("job_id","")
            with _lock:
                job = dict(_gen_jobs.get(job_id, {"status":"unknown"}))
            self.send_json(job)

        elif path == "/api/pull":
            model = body.get("model","")
            if not model:
                self.send_json({"error":"no model"}); return
            threading.Thread(target=ollama_pull, args=(model,), daemon=True).start()
            self.send_json({"pulling":model})

        elif path == "/api/tts":
            # Returns WAV audio for the browser to play (voice/speed/volume customizable).
            try:
                data, mime = tts_synthesize(body.get("text",""),
                                            body.get("voice") or None,
                                            body.get("speed"),
                                            body.get("volume"))
                self.send_json({"ok": True, "audio": base64.b64encode(data).decode(),
                                "mime": mime, "bytes": len(data)})
            except Exception as e:
                log(f"TTS failed: {e}", "error")
                self.send_json({"ok": False, "msg": str(e)})

        elif path == "/api/voices":
            self.send_json({"voices": list_voices(), "settings": get_voice_settings()})

        elif path == "/api/agent_settings":
            # GET-ish read when body is empty; otherwise apply changes.
            changed = False
            for k, cfgk in (("admin_mode","agent_admin_mode"),
                            ("pc_control","agent_pc_control"),
                            ("shell_timeout","agent_shell_timeout")):
                if k in body:
                    _config[cfgk] = body[k]; changed = True
            if changed:
                save_config()
                s = agent_settings()
                agent_audit("settings", "meta", json.dumps(s), "CHANGED")
                log(f"ADMIN MODE {'ENABLED - blocklist lifted' if s['admin_mode'] else 'disabled'}",
                    "warn" if s["admin_mode"] else "ok")
            scr = None
            try:
                _w, _h = _gui().size(); scr = {"w": _w, "h": _h}
            except Exception as e:
                scr = {"error": str(e)}
            self.send_json({"ok": True, "settings": agent_settings(), "screen": scr,
                            "tiers": TOOL_TIERS,
                            "blocklist": [why for _p, why in BLACK_PATTERNS]})

        # ── Device fabric ────────────────────────────────────────────────
        elif path == "/api/device/register":
            did = (body.get("device_id") or "").strip() or uuid.uuid4().hex[:10]
            with _lock:
                prev = _devices.get(did, {})
                _devices[did] = {
                    "name": body.get("name") or prev.get("name") or did,
                    "platform": (body.get("platform") or prev.get("platform") or "unknown").lower(),
                    "capabilities": (normalize_caps(body.get("capabilities"))
                                     or prev.get("capabilities") or []),
                    "last_seen": time.time(),
                    "registered": prev.get("registered", time.time()),
                }
                nm = _devices[did]["name"]; plat = _devices[did]["platform"]
                ncap = len(_devices[did]["capabilities"])
            if not prev:
                log(f"Device paired: {nm} ({plat}) with {ncap} capabilities", "ok")
                agent_audit("device", "meta", f"{nm} ({plat}) registered", "PAIRED")
            self.send_json({"ok": True, "device_id": did,
                            "poll_seconds": 25, "server": VERSION})

        elif path == "/api/device/poll":
            # Long-poll: hold the request open so the phone gets work instantly
            # without hammering the battery with a fast polling loop.
            did = (body.get("device_id") or "").strip()
            wait = min(float(body.get("wait", 25)), 55)
            with _lock:
                known = did in _devices
                if known:
                    _devices[did]["last_seen"] = time.time()
            if not known:
                self.send_json({"error": "unknown device — register first"}, 404); return
            deadline = time.time() + wait
            while time.time() < deadline:
                with _lock:
                    q = _device_queue.get(did) or []
                    if q:
                        call = q.pop(0)
                        _devices[did]["last_seen"] = time.time()
                        self.send_json({"call": call}); return
                time.sleep(0.25)
            with _lock:
                _devices[did]["last_seen"] = time.time()
            self.send_json({"call": None})

        elif path == "/api/device/result":
            cid = body.get("call_id", "")
            with _lock:
                if cid in _device_res:
                    _device_res[cid] = {"done": True, "result": body.get("result")}
                did = (body.get("device_id") or "").strip()
                if did in _devices:
                    _devices[did]["last_seen"] = time.time()
            self.send_json({"ok": True})

        elif path == "/api/devices":
            if body.get("forget"):
                with _lock:
                    _devices.pop(body["forget"], None)
                    _device_queue.pop(body["forget"], None)
                log(f"Device removed: {body['forget']}", "warn")
            self.send_json({"ok": True, "devices": device_snapshot(),
                            "token": api_token() if self.is_local() else None,
                            "lan_url": f"http://{lan_ip()}:{PORT}"})

        elif path == "/api/token":
            if not self.is_local():
                self.send_json({"error": "token is only readable from the host PC"}, 403); return
            if body.get("rotate"):
                rotate_api_token()
            self.send_json({"ok": True, "token": api_token(),
                            "lan_url": f"http://{lan_ip()}:{PORT}",
                            "require_local_auth": bool(_config.get("require_local_auth", False))})

        elif path == "/api/reset_session":
            # New task = fresh loop-breaker tally, so an earlier repeat does not
            # poison a later, legitimately similar command.
            reset_session_calls(body.get("session_id") or "")
            self.send_json({"ok": True})

        elif path == "/api/model_storage":
            # Turns the wall of sha256-* blob filenames into something readable,
            # and says what deleting each model would ACTUALLY free (models can
            # share weights, so removing one of a pair frees nothing).
            try:
                import importlib.util as _ilu
                spec = _ilu.spec_from_file_location(
                    "blob_index", str(Path(__file__).parent / "blob_index.py"))
                bi = _ilu.module_from_spec(spec); spec.loader.exec_module(bi)
                store = bi.find_store()
                if not store:
                    self.send_json({"ok": False, "msg": "Could not locate the Ollama model store."}); return
                if body.get("write_index"):
                    import subprocess as _sp
                    _sp.run([sys.executable, str(Path(__file__).parent / "blob_index.py"), "--csv"],
                            capture_output=True, timeout=120)
                rows = bi.build(store)
                per = {}
                for r in rows:
                    for m in r["models"]:
                        e = per.setdefault(m, {"total": 0, "unique": 0})
                        e["total"] += r["bytes"]
                        if not r["shared"]:
                            e["unique"] += r["bytes"]
                models = [{"model": m, "frees": v["unique"], "total": v["total"],
                           "shares_weights": (v["total"] - v["unique"]) > 100 * 1024 * 1024}
                          for m, v in sorted(per.items(), key=lambda kv: -kv[1]["unique"])]
                self.send_json({"ok": True, "store": str(store),
                                "blob_total": sum(r["bytes"] for r in rows),
                                "blob_count": len(rows),
                                "orphans": [r for r in rows if r["orphan"]],
                                "models": models,
                                "blobs": [r for r in rows if r["bytes"] > 1024 * 1024]})
            except Exception as e:
                log(f"model_storage failed: {e}", "error")
                self.send_json({"ok": False, "msg": str(e)})

        elif path == "/api/model_delete":
            name = (body.get("model") or "").strip()
            if not name:
                self.send_json({"ok": False, "msg": "no model given"}); return
            r = subprocess.run(["ollama", "rm", name], capture_output=True, text=True,
                               timeout=180, errors="replace")
            ok = r.returncode == 0
            log(f"ollama rm {name} -> {'removed' if ok else (r.stderr or '').strip()[:120]}",
                "ok" if ok else "error")
            agent_audit("model_delete", "meta", name, "REMOVED" if ok else "FAILED")
            self.send_json({"ok": ok, "msg": (r.stdout or r.stderr or "").strip()[:400]})

        elif path == "/api/pair_code":
            # PC side: mint a fresh code and hand back the QR to display
            if not self.is_local():
                self.send_json({"ok": False, "msg": "pairing must be started on the PC"}, 403); return
            code = pair_new_code()
            png = pair_qr_png(pair_payload())
            self.send_json({"ok": True, "code": code, "host": lan_ip(), "port": PORT,
                            "expires_in": PAIR_TTL,
                            "qr": base64.b64encode(png).decode() if png else None})

        elif path == "/api/pair_claim":
            # Phone side: no token yet, so this route is auth-exempt. A valid
            # code only earns you a PENDING request - never the token directly.
            code = (body.get("code") or "").upper().strip()
            device = (body.get("device") or "unknown device")[:60]
            req_id = body.get("req_id")

            if req_id:                                  # polling an existing request
                r = _pair_reqs.get(req_id)
                if not r:
                    self.send_json({"ok": False, "state": "expired"}); return
                if r["state"] == "approved":
                    self.send_json({"ok": True, "state": "approved", "token": api_token()}); return
                self.send_json({"ok": True, "state": r["state"]}); return

            if not pair_code_valid(code):
                log(f"Rejected pairing attempt from {self.client_ip()} (bad/expired code)", "warn")
                self.send_json({"ok": False, "state": "bad_code"}); return

            rid = secrets.token_urlsafe(9)
            _pair_reqs[rid] = {"device": device, "ip": self.client_ip(),
                               "state": "pending", "at": time.time()}
            log(f"Pairing request from {device} ({self.client_ip()}) - awaiting approval", "info")
            self.send_json({"ok": True, "state": "pending", "req_id": rid})

        elif path == "/api/pair_pending":
            if not self.is_local():
                self.send_json({"ok": False}, 403); return
            self.send_json({"ok": True, "requests": [
                {"id": k, "device": v["device"], "ip": v["ip"], "state": v["state"],
                 "age": int(time.time() - v["at"])}
                for k, v in _pair_reqs.items() if v["state"] == "pending"]})

        elif path == "/api/pair_decide":
            if not self.is_local():
                self.send_json({"ok": False}, 403); return
            rid, ok = body.get("id"), bool(body.get("approve"))
            r = _pair_reqs.get(rid)
            if not r:
                self.send_json({"ok": False, "msg": "no such request"}); return
            r["state"] = "approved" if ok else "denied"
            if ok:
                _pair_code["exp"] = 0        # burn the code once it has been used
            log(f"Pairing {'APPROVED' if ok else 'DENIED'} for {r['device']} ({r['ip']})",
                "ok" if ok else "warn")
            agent_audit("pair_device", "red", f"{r['device']} {r['ip']}",
                        "APPROVED" if ok else "DENIED")
            self.send_json({"ok": True, "state": r["state"]})

        elif path == "/api/roster":
            if "handler_model" in body:
                _config["handler_model"] = body["handler_model"]; save_config()
            if "routing_enabled" in body:
                _config["routing_enabled"] = bool(body["routing_enabled"]); save_config()
            self.send_json({"ok": True, "roster": model_roster(),
                            "handler": handler_model(),
                            "routing": bool(_config.get("routing_enabled", True)),
                            "models": _get_models()})

        elif path == "/api/stt_settings":
            global _fw_model, _fw_key
            changed = False
            for k, cfgk in (("model","whisper_model"), ("device","whisper_device"),
                            ("language","whisper_language"), ("beam","whisper_beam"),
                            ("vocab_hint","whisper_vocab_hint")):
                if k in body:
                    _config[cfgk] = body[k]; changed = True
            if changed:
                save_config()
                _fw_model, _fw_key = None, None      # force a reload with the new settings
                log(f"Whisper settings: {_whisper_settings()}", "ok")
            self.send_json({"ok": True, "settings": _whisper_settings(),
                            "sizes": ["tiny.en","base.en","small.en","medium.en",
                                      "distil-large-v3","large-v3","large-v3-turbo"]})

        elif path == "/api/agent_audit":
            n = int(body.get("limit", 80))
            lines = []
            try:
                if AGENT_AUDIT_LOG.exists():
                    raw = AGENT_AUDIT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
                    for ln in raw[-n:]:
                        try: lines.append(json.loads(ln))
                        except Exception: pass
            except Exception as e:
                self.send_json({"ok": False, "msg": str(e)}); return
            self.send_json({"ok": True, "entries": list(reversed(lines))})

        elif path == "/api/voice_settings":
            for k, cfgk in (("voice","agent_voice"), ("speed","agent_voice_speed"), ("volume","agent_voice_volume")):
                if k in body:
                    _config[cfgk] = body[k]
            save_config()
            log(f"Voice settings updated: {get_voice_settings()}", "ok")
            self.send_json({"ok": True, "settings": get_voice_settings()})

        elif path == "/api/transcribe":
            audio_bytes = base64.b64decode(body.get("audio",""))
            mime = body.get("mime","audio/webm")
            if "ogg" in mime:   ext=".ogg"
            elif "wav" in mime: ext=".wav"
            elif "mp4" in mime: ext=".mp4"
            else:               ext=".webm"
            quick = bool(body.get("quick", False))
            tmp = tempfile.mktemp(suffix=ext)
            with open(tmp,"wb") as f: f.write(audio_bytes)
            if not quick:
                log(f"Transcribing: {len(audio_bytes)} bytes, mime={mime}", "info")
            text = transcribe_audio(tmp, quick=quick)
            try: os.unlink(tmp)
            except: pass
            self.send_json({"text":text})

        elif path == "/api/vision":
            img_bytes = base64.b64decode(body.get("image",""))
            tmp = tempfile.mktemp(suffix=".png")
            with open(tmp,"wb") as f: f.write(img_bytes)
            result = analyze_image(body.get("model","llava"), tmp, body.get("prompt","Describe this image."))
            try: os.unlink(tmp)
            except: pass
            self.send_json({"result":result})

        elif path == "/api/undo_file":
            # Restore the most recent file backup made by write_file/edit_file
            if not _LAST_BACKUP.get("backup"):
                self.send_json({"ok":False,"msg":"Nothing to undo — no backup recorded this session."}); return
            try:
                b = Path(_LAST_BACKUP["backup"]); o = Path(_LAST_BACKUP["original"])
                if not b.exists():
                    self.send_json({"ok":False,"msg":f"Backup file missing: {b}"}); return
                o.write_bytes(b.read_bytes())
                log(f"UNDO: restored {o} from {b.name}", "ok")
                self.send_json({"ok":True,"msg":f"Restored {o} from backup {b.name}"})
            except Exception as e:
                self.send_json({"ok":False,"msg":str(e)})

        elif path == "/api/heretic":
            model_id = body.get("model","Qwen/Qwen2.5-7B-Instruct")
            threading.Thread(target=run_heretic_model, args=(model_id,), daemon=True).start()
            self.send_json({"started":True,"model":model_id})

        elif path == "/api/heretic_import":
            model_path = body.get("path","").strip()
            model_name = body.get("name","").strip()
            if not model_path or not model_name:
                self.send_json({"ok":False,"msg":"path and name required"}); return
            mp = Path(model_path)
            if not mp.exists():
                self.send_json({"ok":False,"msg":f"Path not found: {model_path} -- check the folder exists"}); return

            # This endpoint IMPORTS. It does not optimize, abliterate or modify
            # weights in any way -- it writes a Modelfile and runs ollama create.
            #
            # The name is historical and it misled us once already: the same GGUF
            # was imported twice under two names, and the second was believed to
            # be an abliterated build for hours. Ollama deduplicates by digest, so
            # both entries pointed at one blob and produced byte-identical output
            # under greedy decoding. Nothing downstream can detect this, so the
            # guard has to be here.
            #
            # Abliteration edits full-precision tensors and must run BEFORE a GGUF
            # exists. A GGUF is already quantized and packed; there is nothing left
            # to edit. So refuse a HuggingFace directory outright rather than
            # quietly importing it and letting the user believe otherwise.
            if mp.is_dir():
                hf_like = any((mp / f).exists() for f in ("config.json", "model.safetensors.index.json"))
                ggufs = list(mp.glob("*.gguf"))
                if hf_like and not ggufs:
                    self.send_json({"ok": False, "msg":
                        "That is a HuggingFace weights folder, and this step only IMPORTS a GGUF "
                        "into Ollama -- it does not optimize or abliterate anything. Convert it to "
                        "GGUF first, then import that. If you want the model abliterated, do it on "
                        "these full-precision weights BEFORE converting; it cannot be done to a "
                        "GGUF afterwards."}); return
                if not ggufs:
                    self.send_json({"ok": False, "msg":
                        f"No .gguf found in {model_path}. This step imports an existing GGUF into "
                        "Ollama; it does not create or optimize one."}); return

            log(f"IMPORT ONLY (no optimization): {model_path} -> {model_name}", "info")

            # Scratch file goes in our own folder, never beside the model
            mf = _write_modelfile(model_path, model_name)

            # Run ollama create with explicit UTF-8 env
            import subprocess as _sp
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"

            try:
                result = _sp.run(
                    f'ollama create {model_name} -f "{mf}"',
                    shell=True, capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    env=env, timeout=7200
                )
                ok = result.returncode == 0
                out = (result.stdout or "") + (result.stderr or "")
                log(f"ollama create output: {out[:500]}", "ok" if ok else "error")
                if ok:
                    # Verify it actually got added
                    models = _get_models()
                    if model_name in models or any(model_name in m for m in models):
                        log(f"Model {model_name} confirmed in Ollama [OK]", "ok")
                        threading.Thread(target=refresh_status_cache, daemon=True).start()
                        self.send_json({"ok":True, "models": models})
                    else:
                        log(f"Warning: ollama create succeeded but {model_name} not found in model list", "warn")
                        threading.Thread(target=refresh_status_cache, daemon=True).start()
                        self.send_json({"ok":True, "warning": f"{model_name} may not have imported correctly -- click Sync to check"})
                else:
                    self.send_json({"ok":False,"msg": out[:300] or "ollama create failed -- check that the model path contains valid model files"})
            except Exception as ex:
                log(f"heretic_import error: {ex}", "error")
                self.send_json({"ok":False,"msg":str(ex)})

        elif path == "/api/convert_gguf":
            src_path  = body.get("path","").strip()
            dest_path = body.get("dest","").strip() or None
            if not src_path:
                self.send_json({"ok":False,"msg":"No source path"}); return
            def _convert():
                ok, result = convert_to_gguf(src_path, dest_path)
                log(f"GGUF convert: {'[OK]' if ok else '[FAIL]'} {result}", "ok" if ok else "error")
            threading.Thread(target=_convert, daemon=True).start()
            self.send_json({"ok":True,"msg":"Conversion started -- watch setup log"})

        elif path == "/api/clone_convert":
            repo_url   = body.get("repo_url","").strip()
            dest_path  = body.get("dest_path","").strip()
            output_dir = body.get("output_dir","").strip() or None
            model_name = body.get("model_name","").strip()
            quant      = body.get("quant","Q8_0")
            if not all([repo_url, dest_path, model_name]):
                self.send_json({"ok":False,"msg":"repo_url, dest_path, model_name required"}); return
            job_id = str(uuid.uuid4())[:8]
            with _lock:
                _pipeline_jobs[job_id] = {"status":"starting","progress":"","result":None,"error":None}
            def _start_pipeline(jid, ru, dp, od, mn, q):
                import threading as _th
                _th.current_thread()._pipeline_job_id = jid
                run_clone_convert_pipeline(jid, ru, dp, od, mn, q)
            threading.Thread(
                target=_start_pipeline,
                args=(job_id, repo_url, dest_path, output_dir, model_name, quant),
                daemon=True
            ).start()
            self.send_json({"ok":True,"job_id":job_id})

        elif path == "/api/pipeline_status":
            job_id = body.get("job_id","")
            with _lock:
                job = dict(_pipeline_jobs.get(job_id, {"status":"unknown","progress":"","result":None,"error":None}))
            # Attach download progress if available
            dl = _download_progress.get(job_id)
            if dl:
                job["download_pct"]     = dl.get("pct", 0)
                job["download_mb_done"] = dl.get("mb_done", 0)
                job["download_mb_total"]= dl.get("mb_total", 0)
                job["download_label"]   = dl.get("label", "")
            self.send_json(job)

        elif path == "/api/convert_existing_folder":
            """Convert an already-downloaded HF model folder to GGUF and import."""
            hf_dir     = body.get("path","").strip()
            model_name = body.get("name","").strip()
            quant      = body.get("quant","Q8_0")
            keep_src   = body.get("keep_source", False)

            if not hf_dir or not model_name:
                self.send_json({"ok":False,"msg":"path and name required"}); return

            hf_path = Path(hf_dir)
            if not hf_path.exists():
                self.send_json({"ok":False,"msg":f"Folder not found: {hf_dir}"}); return
            # Check for GGUF files in folder — direct import, no conversion needed
            existing_ggufs = sorted(hf_path.glob("*.gguf"),
                                    key=lambda f: f.stat().st_size, reverse=True)
            if existing_ggufs and not (hf_path / "config.json").exists():
                best_gguf = existing_ggufs[0]
                log(f"GGUF files found in folder, importing directly: {best_gguf}", "info")
                job_id_local = str(uuid.uuid4())[:8]
                with _lock:
                    _pipeline_jobs[job_id_local] = {"status":"importing",
                        "progress":f"Importing {best_gguf.name}...","result":None,"error":None}
                def _do_direct_import(jid=job_id_local, gf=best_gguf, mn=model_name):
                    ok2, res2 = import_gguf_to_ollama(str(gf), mn)
                    if ok2:
                        reg = get_model_registry()
                        if not any(m["name"]==mn for m in reg):
                            try: sz=round(gf.stat().st_size/1024/1024,1)
                            except: sz=0
                            reg.append({"name":mn,"path":str(gf),
                                        "category":"chat","type":"gguf","size_mb":sz})
                            save_model_registry(reg)
                        with _lock:
                            _pipeline_jobs[jid]={"status":"done","progress":"Complete",
                                "result":{"model_name":mn,"gguf_path":str(gf)},"error":None}
                        log(f"Direct GGUF import complete: {mn}", "ok")
                    else:
                        with _lock:
                            _pipeline_jobs[jid]={"status":"error","progress":"",
                                "result":None,"error":res2}
                threading.Thread(target=_do_direct_import, daemon=True).start()
                self.send_json({"ok":True,"job_id":job_id_local})
                return

            if not (hf_path / "config.json").exists():
                self.send_json({"ok":False,"msg":f"No config.json found - not a valid HF model folder: {hf_dir}"}); return

            job_id = str(uuid.uuid4())[:8]
            with _lock:
                _pipeline_jobs[job_id] = {"status":"converting","progress":"Starting conversion...","result":None,"error":None}

            def _run_convert():
                # Output GGUF to same folder as the HF model
                output_dir = str(hf_path)
                ok, gguf_or_err = convert_hf_to_gguf_pipeline(
                    hf_dir, output_dir, quant, model_name,
                    cb=lambda m: _pipeline_jobs.__setitem__(job_id, {
                        "status":"converting","progress":m,"result":None,"error":None
                    })
                )
                if not ok:
                    with _lock:
                        _pipeline_jobs[job_id] = {"status":"error","progress":"","result":None,"error":gguf_or_err}
                    return

                # Import to Ollama
                with _lock:
                    _pipeline_jobs[job_id]["status"] = "importing"
                    _pipeline_jobs[job_id]["progress"] = "Importing into Ollama..."

                ok2, result2 = import_gguf_to_ollama(gguf_or_err, model_name)
                if ok2:
                    # Add to registry pointing to GGUF
                    reg = get_model_registry()
                    if not any(m["name"]==model_name for m in reg):
                        try: sz = round(Path(gguf_or_err).stat().st_size/1024/1024,1)
                        except: sz = 0
                        reg.append({"name":model_name,"path":gguf_or_err,
                                    "category":"chat","type":"gguf","size_mb":sz})
                        save_model_registry(reg)

                    # Optionally delete source HF files to save space
                    if not keep_src:
                        log(f"Cleaning up source HF files from {hf_dir}...", "info")
                        deleted = 0
                        for f in hf_path.glob("*.safetensors"):
                            try: f.unlink(); deleted += 1
                            except: pass
                        # Also remove model index json
                        for f in hf_path.glob("*.safetensors.index.json"):
                            try: f.unlink()
                            except: pass
                        log(f"Deleted {deleted} source .safetensors files", "ok")

                    with _lock:
                        _pipeline_jobs[job_id] = {
                            "status":"done","progress":"Complete",
                            "result":{"model_name":model_name,"gguf_path":gguf_or_err},
                            "error":None
                        }
                    log(f"Folder convert pipeline complete: {model_name}", "ok")
                else:
                    with _lock:
                        _pipeline_jobs[job_id] = {"status":"error","progress":"","result":None,"error":result2}

            threading.Thread(target=_run_convert, daemon=True).start()
            self.send_json({"ok":True,"job_id":job_id})

        elif path == "/api/import_gguf":
            gguf_path  = body.get("path","").strip()
            model_name = body.get("name","").strip()
            if not gguf_path or not model_name:
                self.send_json({"ok":False,"msg":"path and name required"}); return
            ok, result = import_gguf_to_ollama(gguf_path, model_name)
            if ok:
                reg = get_model_registry()
                if not any(m["name"]==model_name for m in reg):
                    try:
                        sz = round(Path(gguf_path).stat().st_size/1024/1024,1)
                    except: sz=0
                    reg.append({"name":model_name,"path":gguf_path,"category":"chat","type":"gguf","size_mb":sz})
                    save_model_registry(reg)
            self.send_json({"ok":ok,"msg":result})

        elif path == "/api/web_fetch":
            url    = body.get("url","")
            result = web_fetch(url)
            self.send_json({"ok":True,"content":result})

        elif path == "/api/web_search":
            query  = body.get("query","")
            result = web_search(query)
            self.send_json({"ok":True,"content":result})

        elif path == "/api/fs_read":
            path_val = body.get("path","")
            self.send_json({"ok":True,"content":fs_read_file(path_val)})

        elif path == "/api/fs_write":
            path_val = body.get("path","")
            content  = body.get("content","")
            result   = fs_write_file(path_val, content)
            self.send_json({"ok": not result.startswith("[Write error"),"path":result})

        elif path == "/api/fs_list":
            path_val = body.get("path","")
            self.send_json({"ok":True,"content":fs_list_dir(path_val)})

        elif path == "/api/run_script":
            script_path = body.get("path","")
            workspace   = body.get("workspace","")
            result = fs_run_script(script_path, workspace or None)
            self.send_json({"ok":result["returncode"]==0, **result})

        elif path == "/api/hf_login":
            token = body.get("token","")
            if token:
                script = f'from huggingface_hub import login\nlogin(token={repr(token)})\nprint("ok")\n'
                tmp = tempfile.mktemp(suffix=".py")
                with open(tmp,"w") as f: f.write(script)
                ok,o,e = run(f'"{VENV_PY}" "{tmp}"')
                try: os.unlink(tmp)
                except: pass
                self.send_json({"ok":ok,"msg":o or e})
            else:
                self.send_json({"ok":False,"msg":"No token"})

        elif path == "/api/scan_drives":
            threading.Thread(target=scan_drives_for_models, daemon=True).start()
            self.send_json({"started":True})

        elif path == "/api/move_file":
            src       = body.get("src","")
            dest      = body.get("dest","")
            action    = body.get("action","move")
            subfolder = body.get("subfolder","")
            ok, msg   = move_model_file(src, dest, action, subfolder)
            self.send_json({"ok":ok,"msg":msg})

        elif path == "/api/move_files_batch":
            """Move multiple files at once to a destination dir."""
            files     = body.get("files",[])   # [{path, subfolder, action}]
            dest_base = body.get("dest","").strip()
            if not dest_base:
                self.send_json({"ok":False,"msg":"No destination specified"}); return
            results = []
            for f in files:
                ok, msg = move_model_file(
                    f.get("path",""), dest_base,
                    f.get("action","move"), f.get("subfolder","")
                )
                results.append({"file": Path(f.get("path","")).name, "ok":ok, "msg":msg})
            all_ok = all(r["ok"] for r in results)
            log(f"Batch move: {sum(1 for r in results if r['ok'])}/{len(results)} succeeded", "ok" if all_ok else "warn")
            self.send_json({"ok":all_ok, "results":results})

        elif path == "/api/unload_gpu":
            # Ungated on purpose - see unload_all_models.
            self.send_json(unload_all_models(body.get("reason") or "a manual request"))
        elif path == "/api/launch_comfyui":
            comfyui_dir = get_comfyui_dir()
            if not comfyui_dir:
                self.send_json({"launched":False,"msg":"ComfyUI not found"}); return
            threading.Thread(target=ensure_comfyui_running, daemon=True).start()
            self.send_json({"launched":True,"path":str(comfyui_dir)})

        elif path == "/api/refresh_status":
            threading.Thread(target=refresh_status_cache, daemon=True).start()
            self.send_json({"ok":True})

        elif path == "/api/scan_folder":
            folder = body.get("path","").strip()
            if not folder:
                self.send_json({"ok":False,"msg":"No folder specified"}); return
            results = scan_folder_for_models(folder)
            self.send_json({"ok":True,"files":results})

        elif path == "/api/comfyui_models":
            """List model files available in ComfyUI model directories."""
            comfyui = get_comfyui_dir()
            if not comfyui:
                self.send_json({"ok":False,"msg":"ComfyUI not configured","models":[]}); return
            MODEL_EXTS_IMG = {".safetensors",".ckpt",".pt",".pth"}
            # Scan these subdirs (recursive to catch subfolders)
            scan_dirs = {
                "checkpoints":       comfyui / "models" / "checkpoints",
                "loras":             comfyui / "models" / "loras",
                "vae":               comfyui / "models" / "vae",
                "controlnet":        comfyui / "models" / "controlnet",
                "upscale":           comfyui / "models" / "upscale_models",
                "diffusion_models":  comfyui / "models" / "diffusion_models",
                "unet":              comfyui / "models" / "unet",
                "motion":            comfyui / "custom_nodes" / "ComfyUI-AnimateDiff-Evolved" / "models",
            }
            models = []
            for category, folder in scan_dirs.items():
                if not folder.exists():
                    continue
                # Walk recursively to find models in subfolders
                for root, dirs, files in os.walk(str(folder)):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for fname in sorted(files):
                        if Path(fname).suffix.lower() in MODEL_EXTS_IMG:
                            full = Path(root) / fname
                            try: size_mb = round(full.stat().st_size/1024/1024,1)
                            except: size_mb = 0
                            # Use relative path from category root as display name
                            try:
                                rel = full.relative_to(folder)
                                display = str(rel)
                            except:
                                display = fname
                            models.append({
                                "name":     display,
                                "path":     str(full),
                                "category": category,
                                "size_mb":  size_mb,
                                "family":   ("flux" if is_flux_model(fname) else "sdxl"),
                            })
            # CogVideoX models from the local HF cache
            try:
                for cm in list_cogvideo_models():
                    models.append({"name": cm["name"], "path": "", "category": "cogvideo",
                                   "size_mb": round(cm.get("size_gb",0)*1024,1), "family": "cogvideo"})
            except Exception: pass
            self.send_json({"ok":True,"models":models,"comfyui_dir":str(comfyui)})

        elif path == "/api/model_registry":
            action = body.get("action","list")
            if action == "list":
                self.send_json({"ok":True,"models":get_model_registry()})
            elif action == "add":
                entry = {
                    "name":     body.get("name","").strip(),
                    "path":     body.get("path","").strip(),
                    "category": body.get("category","chat"),
                    "type":     infer_model_type(body.get("path","")),
                    "size_mb":  body.get("size_mb",0),
                }
                if not entry["name"] or not entry["path"]:
                    self.send_json({"ok":False,"msg":"Name and path required"}); return
                if not Path(entry["path"]).exists():
                    self.send_json({"ok":False,"msg":f"File not found: {entry['path']}"}); return
                reg = get_model_registry()
                # Check for duplicate name
                if any(m["name"]==entry["name"] for m in reg):
                    self.send_json({"ok":False,"msg":f"A model named '{entry['name']}' already exists"}); return
                reg.append(entry)
                save_model_registry(reg)
                log(f"Model added to registry: {entry['name']} ({entry['category']})", "ok")
                self.send_json({"ok":True,"registry":reg})
            elif action == "remove":
                name = body.get("name","").strip()
                reg = [m for m in get_model_registry() if m["name"] != name]
                save_model_registry(reg)
                log(f"Model removed from registry: {name}", "info")
                self.send_json({"ok":True,"registry":reg})
            elif action == "rename":
                old_name = body.get("old_name","").strip()
                new_name = body.get("new_name","").strip()
                if not new_name:
                    self.send_json({"ok":False,"msg":"New name required"}); return
                reg = get_model_registry()
                for m in reg:
                    if m["name"] == old_name:
                        m["name"] = new_name
                        break
                save_model_registry(reg)
                self.send_json({"ok":True,"registry":reg})
            else:
                self.send_json({"ok":False,"msg":f"Unknown action: {action}"})

        elif path == "/api/refresh_deep":
            def _deep_check():
                log("=== Deep system check ===", "info")
                pairs = [("python",_check_python()),("cuda",_check_cuda()),
                         ("ollama",_check_ollama()),("comfyui",_check_comfyui()),
                         ("heretic",_check_heretic()),("whisper",_check_whisper()),
                         ("tts",_check_tts()),("cogvideo",_check_cogvideo())]
                for k,v in pairs:
                    set_cache(k,v)
                    log(f"  {'[OK]' if v else '[WARN]'} {k}: {v}", "ok" if v else "warn")
                set_cache("models", _get_models())
                log("=== Deep check complete ===", "ok")
            threading.Thread(target=_deep_check, daemon=True).start()
            self.send_json({"ok": True})

        elif path == "/api/memory":
            action = body.get("action", "get")
            if action == "get":
                self.send_json({"ok": True, "memory": load_memory()})
            elif action == "save":
                mem = body.get("memory", {})
                save_memory(mem)
                self.send_json({"ok": True})
            elif action == "delete_item":
                cat  = body.get("category", "")
                item = body.get("item", "")
                mem  = load_memory()
                if cat in mem:
                    mem[cat] = [x for x in mem[cat] if x != item]
                    save_memory(mem)
                self.send_json({"ok": True, "memory": mem})
            elif action == "add_item":
                cat  = body.get("category", "")
                item = body.get("item", "").strip()
                if cat and item:
                    mem = load_memory()
                    if cat not in mem: mem[cat] = []
                    if item not in mem[cat]:
                        mem[cat].append(item)
                    save_memory(mem)
                self.send_json({"ok": True, "memory": mem})
            elif action == "clear":
                save_memory({cat: [] for cat in MEMORY_CATEGORIES})
                self.send_json({"ok": True})
            elif action == "extract":
                model    = body.get("model", "").strip()
                messages = body.get("messages", [])
                if not model or not messages:
                    self.send_json({"ok": False, "msg": "model and messages required"}); return
                def _extract_bg():
                    log("Extracting memory from conversation...", "info")
                    new_facts = extract_memory_from_conversation(model, messages)
                    if new_facts:
                        mem = load_memory()
                        mem = merge_memory(mem, new_facts)
                        save_memory(mem)
                        count = sum(len(v) for v in new_facts.values())
                        log(f"Memory updated: {count} new facts", "ok")
                threading.Thread(target=_extract_bg, daemon=True).start()
                self.send_json({"ok": True})
            else:
                self.send_json({"ok": False, "msg": f"Unknown action: {action}"})

        elif path == "/api/model_fit":
            self.send_json(model_vram_report(body.get("model")))

        elif path == "/api/term":
            if not self.is_local() and not _config.get("terminal_remote", False):
                self.send_json({"ok": False, "msg": "The terminal is only available on this PC "
                                "(set terminal_remote in the config to allow paired devices)."}, 403)
            else:
                self.send_json(term_api(body))

        elif path == "/api/projects":
            self.send_json(projects_api(body))

        elif path == "/api/session":
            action = body.get("action", "load")
            if action == "save":
                self.send_json(save_session(body.get("session") or {}))
            elif action == "clear":
                try:
                    if SESSION_FILE.exists():
                        SESSION_FILE.unlink()
                except Exception as e:
                    self.send_json({"ok": False, "msg": str(e)}); return
                self.send_json({"ok": True})
            else:
                self.send_json(load_session())

        elif path == "/api/chat_status":
            req_id = body.get("req_id", "")
            try:
                sfrom = int(body.get("stream_from") or 0)
            except (TypeError, ValueError):
                sfrom = 0
            with _lock:
                status = dict(_chat_status.get(req_id, {}))
            # Hand back only the NEW text. This is polled several times a second
            # and the buffer runs to 200k chars; shipping the whole thing every
            # time is what would make streaming feel worse than no streaming.
            text, at, total = stream_slice(status, sfrom)
            status["stream"]     = text
            status["stream_at"]  = at      # absolute index of char 0 of `text`
            status["stream_len"] = total
            self.send_json(status)

        elif path == "/api/open_folder":
            # A browser cannot follow a file:// link from an http page — it is
            # blocked, silently, which is why the Gallery link did nothing. The
            # server is the only thing here that can actually open a window.
            raw = (body.get("path") or "").strip()
            if not raw:
                self.send_json({"ok": False, "msg": "no path"}); return
            try:
                target = Path(raw).expanduser().resolve()
            except Exception as e:
                self.send_json({"ok": False, "msg": "bad path: " + str(e)[:80]}); return
            # Open a FOLDER, never run a file. A path pointing at a file opens
            # the folder containing it instead, so this cannot be used to
            # launch anything.
            if target.is_file():
                target = target.parent
            if not target.is_dir():
                self.send_json({"ok": False, "msg": "not a folder: " + str(target)}); return
            try:
                if sys.platform == "win32":
                    subprocess.Popen(["explorer", str(target)])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(target)])
                else:
                    subprocess.Popen(["xdg-open", str(target)])
                log(f"Opened folder: {target}", "info")
                self.send_json({"ok": True, "path": str(target)})
            except Exception as e:
                self.send_json({"ok": False, "msg": str(e)[:120]})

        elif path == "/api/set_ollama_dir":
            new_dir = body.get("path","").strip()
            if not new_dir:
                self.send_json({"ok":False,"msg":"No path provided"}); return
            ok2 = set_ollama_models_dir(new_dir)
            self.send_json({"ok": ok2})

        else:
            self.send_json({"error":"not found"},404)

# ??? Entry point ??????????????????????????????????????????????????????????????
def main():
    # Force UTF-8 output on Windows so the terminal doesn't crash
    import sys
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        try:
            import os
            os.system("chcp 65001 > nul 2>&1")  # set Windows console to UTF-8
        except Exception:
            pass
    print(BANNER)
    load_config()
    log("ESTEEF.AI // NeuralDock v3.0 starting...", "info")
    # nothing in this app works without Ollama, so bring it up before we
    # start serving a UI that would just report it offline
    threading.Thread(target=ensure_ollama_running, daemon=True).start()
    threading.Thread(target=refresh_status_cache, daemon=True).start()
    threading.Thread(target=_sysmon_loop, daemon=True).start()
    start_status_loop()
    _reap_stale_chat_jobs()   # flag chat jobs orphaned by a previous restart
    if PORTABLE:
        # Philibert runs on other people's computers: this machine only, never
        # their network.
        ThreadedHTTPServer.address_family = socket.AF_INET
        server = ThreadedHTTPServer(("127.0.0.1", PORT), Handler)
    else:
        try:
            server = ThreadedHTTPServer(("::", PORT), Handler)      # dual-stack
        except Exception as e:
            log(f"IPv6 bind failed ({e}); falling back to IPv4 only", "warn")
            ThreadedHTTPServer.address_family = socket.AF_INET
            server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    if PORTABLE:
        log(f"Server ready -> http://localhost:{PORT}  (this computer only)", "ok")
    else:
        log(f"Server ready -> http://localhost:{PORT}  (also http://{lan_ip()}:{PORT})", "ok")
    # ND_START_PATH opens the window somewhere other than "/" (Start-Full -> /full).
    url = f"http://localhost:{PORT}" + (os.environ.get("ND_START_PATH") or "")
    print(f"\n  -- ESTEEF.AI // {PRODUCT} v{VERSION}  ->  {url}  --")
    print(f"     shell: {choose_shell()}   (--window / --browser to switch)\n")

    if "--install-webview" in sys.argv:
        if install_webview():
            # a module installed after this process started is invisible until
            # the import machinery re-scans sys.path
            import importlib
            importlib.invalidate_caches()

    # The HTTP server must run in the background, because the WebView2 window
    # takes over the main thread and only returns when the user closes it.
    threading.Thread(target=_serve_supervised, args=(server,), daemon=True).start()
    # Asks the same question a client would, from outside the request path: a
    # loop can be alive and still wedged, and nothing inside the process can
    # tell the difference.
    threading.Thread(target=_serve_selfcheck, args=(server, PORT),
                     daemon=True).start()
    try:
        owned = open_ui(url)
        if owned:
            log(f"Window closed - shutting down {PRODUCT}", "info")
            return
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()

if __name__ == "__main__":
    main()
