"""Philibert (portable ND): model catalog, downloads, first run and updates.

Loaded only in portable mode. The drive is a git checkout of the Philibert repo:

    <root>/models.json   the catalog - which models the dropdown offers. Adding a
                         model to it and pushing is how a new model reaches every
                         drive: the next Update brings the list, and the model is
                         downloaded (from Ollama's library or Hugging Face) the
                         first time someone picks it.
    <root>/models/       the drive's own Ollama store
    <root>/philibert.json  {"repo": "owner/name", "branch": "main"} - where Update looks

Every network action here is one the user clicked (Download, Update). The
Internet switch governs what the AI may do on its own; it does not stop a person
updating their own drive.

    python nd_philibert.py --first-run     (the setup scripts call this once Ollama is up)
"""
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(os.environ.get("PHILIBERT_ROOT") or Path(__file__).resolve().parent.parent)
OLLAMA_URL = os.environ.get("ND_OLLAMA_URL") or "http://127.0.0.1:11435"
CATALOG = ROOT / "models.json"
REPO_FILE = ROOT / "philibert.json"
# What an update may replace. data/, models/, runtime/ and secrets/ are the
# user's or the machine's and are never touched.
UPDATABLE = ("app", "setup", "models.json", "philibert.json", "README.md", "Start-Windows.bat",
             "Start-Full-Windows.bat", "Start-Mac.command", ".gitattributes", ".gitignore")

_pulls = {}               # tag -> {"status", "done", "total", "error", "started"}
_lock = threading.Lock()


def _say(log, msg, level="info"):
    (log or (lambda m, l="info": print(m, flush=True)))(msg, level)


# ── catalog ──────────────────────────────────────────────────────────────────
def catalog():
    try:
        return json.loads(CATALOG.read_text(encoding="utf-8")).get("models", [])
    except Exception:
        return []


def installed():
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=10) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return []


def _same(a, b):
    """Ollama lists "nomic-embed-text:latest" for "nomic-embed-text"."""
    norm = lambda t: t if ":" in t.split("/")[-1] else t + ":latest"
    return norm(a) == norm(b)


def gpu_gb():
    """Memory the models can use: the NVIDIA card's, or on a Mac two thirds of the
    unified memory (what macOS lets the GPU have). 0 when unknown -> CPU tiers."""
    if sys.platform == "darwin":
        try:
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                 text=True, timeout=10).stdout
            return round(int(out.strip()) / 1e9 * 0.66, 1)
        except Exception:
            return 0.0
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return round(max(int(x) for x in out.split() if x.strip().isdigit()) / 1024, 1)
    except Exception:
        return 0.0


def pick_default(models=None, gb=None):
    """The biggest chat model marked "auto" that this machine's GPU memory fits."""
    models = models if models is not None else catalog()
    gb = gpu_gb() if gb is None else gb
    chat = [m for m in models if m.get("kind", "chat") == "chat" and m.get("auto", True)]
    fits = [m for m in chat if (m.get("min_gpu_gb") or 0) <= gb]
    pool = fits or chat
    if not pool:
        return None
    pick = max(pool, key=lambda m: m.get("size_gb", 0)) if fits else min(pool, key=lambda m: m.get("size_gb", 0))
    return pick["tag"]


def view():
    """The dropdown's list: every catalog model plus anything else on the drive."""
    have = installed()
    out = []
    for m in catalog():
        on = any(_same(m["tag"], h) for h in have)
        with _lock:
            p = dict(_pulls.get(m["tag"], {}))
        out.append({**m, "installed": on, "pull": p or None})
    for h in have:
        if not any(_same(h, m["tag"]) for m in catalog()):
            out.append({"tag": h, "label": h.split("/")[-1], "kind": "embed" if "embed" in h else "chat",
                        "installed": True, "pull": None, "extra": True})
    return {"models": out, "default": pick_default(), "gpu_gb": gpu_gb()}


# ── downloads ────────────────────────────────────────────────────────────────
def pull(tag, log=None, wait=False):
    if not any(m["tag"] == tag for m in catalog()):
        return {"ok": False, "error": f"{tag} is not in models.json"}
    with _lock:
        cur = _pulls.get(tag)
        if cur and cur.get("status") not in ("done", "error"):
            return {"ok": True, "already": True}
        _pulls[tag] = {"status": "starting", "done": 0, "total": 0, "error": "", "started": time.time()}
    t = threading.Thread(target=_pull_run, args=(tag, log), daemon=True)
    t.start()
    if wait:
        t.join()
    return {"ok": True}


def _pull_run(tag, log):
    _say(log, f"Downloading {tag} ...")
    try:
        req = urllib.request.Request(OLLAMA_URL + "/api/pull", method="POST",
                                     data=json.dumps({"model": tag, "stream": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        last = 0
        with urllib.request.urlopen(req, timeout=3600) as r:
            for line in r:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("error"):
                    raise RuntimeError(o["error"])
                with _lock:
                    p = _pulls[tag]
                    p["status"] = o.get("status", p["status"])
                    if o.get("total"):
                        p["done"], p["total"] = o.get("completed", 0), o["total"]
                if not log and time.time() - last > 5 and o.get("total"):
                    last = time.time()
                    print(f"  {tag}: {o.get('completed', 0) / 1e9:.1f} / {o['total'] / 1e9:.1f} GB", flush=True)
        with _lock:
            _pulls[tag].update(status="done")
        _say(log, f"Downloaded {tag}", "ok")
    except Exception as e:
        with _lock:
            _pulls[tag].update(status="error", error=str(e)[:300])
        _say(log, f"Download of {tag} failed: {e}", "warn")


# -- speech -------------------------------------------------------------------
SPEECH = ROOT / "speech"            # HF_HOME (Whisper models) and voices/, set by setup
VOICE = "en_US-amy-medium"
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/"
WHISPER_MODELS = ("small.en", "base.en")     # requests / the wake word
# Plain folders, not the Hugging Face cache: exFAT cannot hold the cache's symlinks.
WHISPER_DIR = Path(os.environ.get("ND_WHISPER_DIR") or SPEECH / "whisper")


def speech_ready():
    """Voice and both Whisper models already on the drive (checked without the
    network, so an offline start stays quiet)."""
    voices = Path(os.environ.get("ND_VOICES_DIR") or SPEECH / "voices")
    whisper = all((WHISPER_DIR / m / "model.bin").is_file() for m in WHISPER_MODELS)
    return (voices / f"{VOICE}.onnx").exists() and (voices / f"{VOICE}.onnx.json").exists() and whisper


def get_speech():
    """Whisper models and one voice onto the drive, so listening and speaking work
    offline. Returns a list of what failed."""
    bad = []
    voices = Path(os.environ.get("ND_VOICES_DIR") or SPEECH / "voices")
    voices.mkdir(parents=True, exist_ok=True)
    for ext in (".onnx", ".onnx.json"):
        f = voices / (VOICE + ext)
        if f.exists():
            continue
        print(f"Downloading the voice {f.name} ...", flush=True)
        try:
            tmp = f.with_suffix(f.suffix + ".part")
            with urllib.request.urlopen(VOICE_URL + f.name, timeout=600) as r, open(tmp, "wb") as out:
                shutil.copyfileobj(r, out)
            tmp.replace(f)
        except Exception as e:
            bad.append(f"{f.name}: {e}")
    try:
        from faster_whisper.utils import download_model
        for m in WHISPER_MODELS:
            print(f"Getting the speech model {m} ...", flush=True)
            if not (WHISPER_DIR / m / "model.bin").is_file():
                download_model(m, output_dir=str(WHISPER_DIR / m))   # real files on the drive
    except Exception as e:
        bad.append(f"whisper: {e}")
    return bad


# -- warm-up ------------------------------------------------------------------
# A model loads off a USB drive at the drive's speed - 1-5 minutes on a hard
# drive - and until it is in memory nothing visible happens. Loading the chosen
# model the moment the window opens turns that into time spent reading the screen.
_warming = {}             # tag -> started


def loaded():
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/ps", timeout=5) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return []


def preload(tag, log=None):
    if not tag or any(_same(tag, m) for m in loaded()):
        return {"ok": True, "loaded": True}
    with _lock:
        if tag in _warming:
            return {"ok": True, "loading": True}
        _warming[tag] = time.time()

    def run():
        t0 = time.time()
        try:
            req = urllib.request.Request(OLLAMA_URL + "/api/generate", method="POST",
                                         data=json.dumps({"model": tag, "keep_alive": "60m"}).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=1800).read()
            _say(log, f"{tag} is loaded ({time.time() - t0:.0f}s from the drive)", "ok")
        except Exception as e:
            _say(log, f"Warm-up of {tag} failed: {e} - it will load on the first question instead", "warn")
        finally:
            with _lock:
                _warming.pop(tag, None)
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "loading": True}


def load_state():
    with _lock:
        w = {t: round(time.time() - s) for t, s in _warming.items()}
    return {"loaded": loaded(), "loading": w}


def first_run():
    """Called by the setup scripts: make sure the drive has the embedder and one chat
    model that suits this machine. Prints progress; returns non-zero on failure."""
    have = installed()
    cat = catalog()
    need = [m["tag"] for m in cat if m.get("required")]     # the embedder and the vision model
    chat_on = [h for h in have if any(_same(h, m["tag"]) for m in cat if m.get("kind", "chat") == "chat")]
    if not chat_on:
        d = pick_default(cat)
        if d:
            print(f"This computer's GPU has {gpu_gb()} GB - starting with {d}.", flush=True)
            need.append(d)
    todo = [t for t in need if not any(_same(t, h) for h in have)]
    speech_bad = [] if speech_ready() else get_speech()
    for b in speech_bad:
        print(f"  !! {b}", flush=True)
    if not todo:
        return 1 if speech_bad else 0
    for t in todo:
        pull(t, wait=True)
    bad = [t for t in todo if _pulls.get(t, {}).get("status") != "done"]
    for t in bad:
        print(f"  !! {t}: {_pulls[t].get('error')}", flush=True)
    return 1 if (bad or speech_bad) else 0


# ── updates ──────────────────────────────────────────────────────────────────
def _repo():
    try:
        d = json.loads(REPO_FILE.read_text(encoding="utf-8"))
        return d.get("repo", ""), d.get("branch", "main")
    except Exception:
        return "", "main"


def _git(*args, timeout=300):
    # exFAT keeps no owner, so git calls every checkout on it "dubious" and refuses.
    cmd = ["git", "-c", f"safe.directory={ROOT.as_posix()}", "-C", str(ROOT), *args]
    # No console to type a password into: fail rather than wait forever. Git's own
    # sign-in window (Git Credential Manager on Windows) still appears if needed.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def version():
    if (ROOT / ".git").exists() and shutil.which("git"):
        r = _git("log", "-1", "--format=%h %cs %s")
        if r.returncode == 0:
            return r.stdout.strip()
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


# A private repo: the GitHub sign-in for this session. In memory only - never
# written to the drive, so a lost drive gives nobody access to the repo.
_GH = {"token": "", "user": "", "device": None}


def _client_id():
    try:
        return json.loads(REPO_FILE.read_text(encoding="utf-8")).get("github_client_id", "")
    except Exception:
        return ""


def github(name, body):
    import nd_github
    repo = _repo()[0]
    if name == "github_status":
        return {"signed_in": bool(_GH["token"]), "user": _GH["user"], "device": bool(_client_id()),
                "private": bool(repo and nd_github.repo_needs_signin(repo))}
    if name == "github_start":
        try:
            d = nd_github.start(_client_id())
        except Exception as e:
            return {"ok": False, "message": f"Could not start signing in: {e}"}
        _GH["device"] = d
        try:
            import webbrowser
            webbrowser.open(d["verification_uri"])
        except Exception:
            pass
        return {"ok": True, "user_code": d["user_code"], "uri": d["verification_uri"], "interval": d.get("interval", 5)}
    if name == "github_poll":
        if not _GH["device"]:
            return {"state": "error", "message": "Start signing in first."}
        try:
            r = nd_github.poll(_client_id(), _GH["device"]["device_code"])
        except Exception as e:
            return {"state": "pending", "message": str(e)}
        if r["state"] != "ok":
            return r
        chk = nd_github.check(repo, r["token"])
        if not chk["ok"]:
            return {"state": "denied", "message": chk["message"]}
        _GH.update(token=r["token"], user=chk["user"], device=None)
        return {"state": "ok", "user": chk["user"]}
    return {"error": "unknown"}


def update(log=None):
    """Bring the drive up to the repo's latest. git when the drive is a checkout and
    git is installed; otherwise the repo's zip (signed in, for a private repo).
    Never touches data/ or models/."""
    before = version()
    busy = []                                 # files in use that could not be replaced
    repo, branch = _repo()
    auth = {"Authorization": f"Bearer {_GH['token']}", "Accept": "application/vnd.github+json"} if _GH["token"] else {}
    if (ROOT / ".git").exists() and shutil.which("git"):
        f = _git("fetch", "origin", branch)
        if f.returncode != 0:
            return {"ok": False, "message": "Could not reach the update server: " + (f.stderr or f.stdout).strip()[-300:]}
        st = _git("status", "--porcelain", "--untracked-files=no")
        if st.stdout.strip():
            # Local edits to tracked files would block a fast-forward; keep them aside.
            _git("stash", "push", "-m", "philibert-update " + time.strftime("%Y-%m-%d %H:%M"))
        r = _git("merge", "--ff-only", f"origin/{branch}")
        if r.returncode != 0:
            return {"ok": False, "message": "Update failed: " + (r.stderr or r.stdout).strip()[-300:]}
        how = "git"
    else:
        if not repo:
            return {"ok": False, "message": "No repo set in philibert.json, so there is nowhere to update from."}
        url = (f"https://api.github.com/repos/{repo}/zipball/{branch}" if auth
               else f"https://codeload.github.com/{repo}/zip/refs/heads/{branch}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Philibert", **auth})
            with urllib.request.urlopen(req, timeout=600) as r:
                z = zipfile.ZipFile(io.BytesIO(r.read()))
        except urllib.error.HTTPError as e:
            if e.code == 404:     # what GitHub says about a private repo to a stranger
                if _client_id():
                    return {"ok": False, "need_signin": True,
                            "message": "This copy of Philibert is shared privately: sign in to GitHub to update."}
                return {"ok": False, "message": "The Philibert repo is private and this drive has no way to sign "
                        "in to it. Set the drive up again with Philibert Setup. Your data/ and models/ are kept."}
            return {"ok": False, "message": f"Could not download the update: {e}"}
        except Exception as e:
            return {"ok": False, "message": f"Could not download the update: {e}"}
        top = z.namelist()[0].split("/")[0]
        for n in z.namelist():
            rel = n[len(top) + 1:]
            if not rel or n.endswith("/") or rel.split("/")[0] not in UPDATABLE:
                continue
            dst = ROOT / rel
            data = z.read(n)
            try:
                if dst.is_file() and dst.read_bytes() == data:
                    continue                  # unchanged: never touch it (it may be open, e.g. the setup window's header)
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_name(dst.name + ".updating")
                tmp.write_bytes(data)
                os.replace(tmp, dst)
            except OSError:                   # in use right now: the next update brings it
                busy.append(rel)
                try:
                    tmp.unlink()
                except (OSError, UnboundLocalError):
                    pass
        sha = ""
        try:
            creq = urllib.request.Request(f"https://api.github.com/repos/{repo}/commits/{branch}",
                                          headers={"User-Agent": "Philibert", **auth})
            with urllib.request.urlopen(creq, timeout=30) as r:
                c = json.loads(r.read())
                sha = f"{c['sha'][:7]} {c['commit']['committer']['date'][:10]} {c['commit']['message'].splitlines()[0]}"
        except Exception:
            sha = time.strftime("%Y-%m-%d") + " (zip)"
        (ROOT / "VERSION").write_text(sha, encoding="utf-8")
        how = "download"
    after = version()
    changed = after != before
    if busy:
        _say(log, "Update: in use, not replaced this time: " + ", ".join(busy[:8]), "warn")
    _say(log, f"Update ({how}): {before} -> {after}", "ok")
    return {"ok": True, "changed": changed, "before": before, "after": after,
            "busy": busy,
            "message": (("Updated to " + after + ". Close Philibert and start it again to use the new version.")
                        if changed else "Already up to date (" + after + ").")
                       + (f" {len(busy)} file(s) were in use and will update next time." if busy else "")}


# ── HTTP ─────────────────────────────────────────────────────────────────────
def handle(path, body, log=None):
    name = path.rsplit("/", 1)[-1]
    if name == "models":
        return view()
    if name == "pull":
        return pull(str(body.get("tag", "")), log)
    if name == "preload":
        return preload(str(body.get("tag", "")), log)
    if name == "load_state":
        return load_state()
    if name == "version":
        return {"version": version(), "repo": _repo()[0]}
    if name == "update":
        return update(log)
    if name.startswith("github_"):
        return github(name, body)
    return {"error": "unknown"}


if __name__ == "__main__":
    if "--first-run" in sys.argv:
        sys.exit(first_run())
    if "--pick" in sys.argv:
        print(pick_default())
