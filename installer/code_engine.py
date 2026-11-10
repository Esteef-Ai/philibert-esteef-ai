"""Philibert Code Setup - the install itself (dev/PHILIBERT_CODE.md, phase 4).

Philibert Code is an add-on to an existing Philibert install: it goes into <Philibert>\\code\\ and uses
Philibert's Python, Ollama and model store. CodeInstaller reuses Philibert's Installer for downloads
(resumable), unpacking, model pulls and progress; the steps are its own:

    check    Philibert is there and set up; this computer's graphics card and memory; Ollama's version
    app      code\\app, start.ps1, the .bat, pins and requirements from the source (local repo or GitHub)
    tools    OpenCode and Git (MinGit), sha256-checked, into code\\tools
    python   ruff, pillow, pywin32 into code\\pylib (+ a sitecustomize that makes it a real site dir)
    model    the coding model pulled into Philibert's store, and its 128K-window tag made
    finish   code\\install.json

The plan:
    {"philibert": "E:\\\\Philibert", "source": {"local": "<repo>"} | {"repo": "owner/name", "branch": "main", "token": "..."},
     "accept_slow": false, "model": true}
Re-running updates the program and fills in what is missing; data\\code (settings, chats) is never touched.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

import core
from engine import IS_WIN, _NO_WINDOW, Installer, free_port

PLAT = "win-x64"
# What an install gets from the repo's code\ folder
CODE_SHIP = ["app", "start.ps1", "Start-Philibert-Code.bat", "requirements.txt", "pins.json", "philibert-code.ico",
             "update.py", "Update-Philibert-Code.bat"]
SITECUSTOMIZE = (
    "# Philibert Code: make code\\pylib a real site dir, so pywin32.pth runs (adds win32 paths and\n"
    "# registers its DLL folder). Written by Setup; PYTHONPATH=code\\pylib makes Python import it.\n"
    "import os, site\n"
    "site.addsitedir(os.path.dirname(os.path.abspath(__file__)))\n")


def version_tuple(v):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", str(v or ""))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def find_philibert(extra=()):
    """Philibert installs this computer can see: <drive>:\\Philibert, plus any folders given."""
    cands = [Path(x) for x in extra]
    if IS_WIN:
        import string
        cands += [Path(f"{d}:\\Philibert") for d in string.ascii_uppercase]
    seen, out = set(), []
    for p in cands:
        try:
            key = str(p.resolve()).lower()
            if key not in seen and philibert_problem(p) is None:
                seen.add(key)
                out.append(p)
        except OSError:
            continue
    return out


def philibert_problem(root):
    """None if `root` is a Philibert install that has been started once (its runtime is set up), else why not."""
    root = Path(root)
    if not (root / "app" / "NeuralDock_launcher.py").is_file():
        return f"Philibert is not installed in {root}."
    for need, what in ((root / "runtime" / PLAT / "python" / "python.exe", "its Python"),
                       (root / "runtime" / PLAT / "ollama" / "ollama.exe", "its Ollama")):
        if not need.is_file():
            return f"Philibert in {root} is not set up on this computer yet ({what} is missing): start Philibert once, then run this Setup again."
    return None


def hardware_verdict(info, need):
    """-> (ok, plain-words message). Philibert Code warns; the user may go on anyway."""
    vram, ram = float(info.get("fast_gb") or 0), float(info.get("ram_gb") or 0)
    short = []
    if vram < need["vram_gb"]:
        short.append(f"{vram:g} GB of graphics memory (it wants {need['vram_gb']} GB)")
    if ram < need["ram_gb"]:
        short.append(f"{ram:g} GB of memory (it wants {need['ram_gb']} GB)")
    if not short:
        return True, f"This computer is ready for coding jobs: {vram:g} GB graphics memory, {ram:g} GB memory."
    return False, ("This computer has " + " and ".join(short) + ". Coding jobs will be very slow here, or the "
                   "coding model will not load at all. You can install Philibert Code anyway.")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class CodeInstaller(Installer):
    def __init__(self, plan, report, log_path=None):
        root = Path(plan["philibert"])
        super().__init__(dict(plan, dest=str(root), pcs=["windows"]), report,
                         log_path or root / "data" / "code" / "logs" / "setup.log")
        self.root = root
        self.code = root / "code"
        self.py = root / "runtime" / PLAT / "python" / "python.exe"
        self.ollama_exe = root / "runtime" / PLAT / "ollama" / "ollama.exe"

    # -- check -------------------------------------------------------------------------------------
    def step_check(self):
        why = philibert_problem(self.root)
        if why:
            raise RuntimeError("Philibert Code needs Philibert. " + why)
        src = self._source()
        self.pins = json.loads((src / "code" / "pins.json").read_text(encoding="utf-8"))
        self.emit(-1, "Looking at this computer")
        ok, msg = hardware_verdict(core.survey(), self.pins["hardware"])
        self.state["hardware"] = msg
        self.log(msg)
        if not ok:
            if not self.plan.get("accept_slow"):
                raise RuntimeError(msg + " (Choose 'install anyway' to go on.)")
            self.state["warnings"].append(msg)
        have = self.ollama_version()
        need = self.pins["ollama_min"]
        self.log(f"Philibert's Ollama: {have or 'unknown'}; Philibert Code needs {need}+")
        if version_tuple(have) < version_tuple(need):
            raise RuntimeError(f"Philibert Code's coding model needs Ollama {need} or newer, and this Philibert has "
                               f"{have or 'an unknown version'}. Update Philibert (its UPDATE button), then run this Setup again.")

    def ollama_version(self):
        """The version of Philibert's ollama.exe itself. `ollama --version` also asks whatever Ollama server
        answers on its host and prints THAT version first ("ollama version is 0.40.15" from this computer's
        own Ollama, then "client version is 0.40.4") - so point it at a port nobody serves, and prefer the
        client line."""
        env = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{free_port(47000)}"}
        try:
            r = subprocess.run([str(self.ollama_exe), "--version"], capture_output=True, text=True, timeout=30,
                               env=env, creationflags=_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            return ""
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        m = re.search(r"client version is\s+(\d+\.\d+\.\d+)", out) or re.search(r"(\d+\.\d+\.\d+)", out)
        return m.group(1) if m else ""

    # -- app ---------------------------------------------------------------------------------------
    def _source(self):
        """The repo folder to copy from: the local one, or GitHub's zip (fetched once)."""
        if getattr(self, "_src_root", None):
            return self._src_root
        src = self.plan.get("source") or {}
        if src.get("local"):
            self._src_root = Path(src["local"])
        else:
            repo, branch = src.get("repo"), src.get("branch", "main")
            tmp = Path(tempfile.mkdtemp(prefix="philibert_code_"))
            if src.get("token"):
                z = self.download(f"https://api.github.com/repos/{repo}/zipball/{branch}", tmp / "src.zip",
                                  "Philibert Code", {"Authorization": f"Bearer {src['token']}",
                                                     "Accept": "application/vnd.github+json"})
            else:
                z = self.download(f"https://codeload.github.com/{repo}/zip/refs/heads/{branch}", tmp / "src.zip",
                                  "Philibert Code")
            with zipfile.ZipFile(z) as zf:
                zf.extractall(tmp)
            self._src_root = next(p for p in tmp.iterdir() if p.is_dir())
        if not (self._src_root / "code" / "app" / "NeuralDock_launcher.py").is_file():
            raise RuntimeError("The Philibert Code program was not found in the download.")
        return self._src_root

    def step_app(self):
        src = self._source() / "code"
        new = self.code / ".app-new"
        if new.exists():
            shutil.rmtree(new)
        files = [f for f in (src / "app").rglob("*") if f.is_file() and "__pycache__" not in f.parts]
        for i, f in enumerate(files):
            out = new / f.relative_to(src / "app")
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, out)
            if i % 20 == 0:
                self.emit(i / max(1, len(files)), f"Copying Philibert Code - {i} of {len(files)} files")
        old = self.code / "app"
        if old.exists():                       # a file removed from the program goes on update too
            shutil.rmtree(old)
        new.rename(old)
        for item in CODE_SHIP[1:]:
            shutil.copy2(src / item, self.code / item)
        (self.root / "data" / "code").mkdir(parents=True, exist_ok=True)   # its own data; never overwritten
        self.log(f"app: {len(files)} files")

    # -- tools -------------------------------------------------------------------------------------
    def _tool(self, key, label, expect_rel):
        pin = self.pins[key]
        dest = self.code / "tools" / key
        stamp = dest / ".philibert-version"
        if self._stamp_is(stamp, pin["version"]) and (dest / expect_rel).is_file():
            self.log(f"{label} {pin['version']}: already here")
            return
        dl = self.code / "_download" / f"{key}-{pin['version']}.zip"
        if not (dl.exists() and sha256(dl) == pin["sha256"]):
            dl.unlink(missing_ok=True)
            self.download(pin[PLAT], dl, f"{label} {pin['version']}")
        got = sha256(dl)
        if got != pin["sha256"]:
            dl.unlink(missing_ok=True)
            raise RuntimeError(f"The {label} download is not the expected file (sha256 {got[:12]}..., expected "
                               f"{pin['sha256'][:12]}...). Nothing was installed. Run Setup again; if it repeats, "
                               f"the download is being changed on its way here.")
        if dest.exists():
            shutil.rmtree(dest)
        self.unpack(dl, dest, dest / expect_rel, label)
        stamp.write_text(pin["version"], encoding="utf-8")
        self.log(f"{label} {pin['version']} installed")

    def step_tools(self):
        self._tool("opencode", "OpenCode", "opencode.exe")
        self._tool("git", "Git", "cmd/git.exe")

    # -- python packages ---------------------------------------------------------------------------
    def step_python(self):
        pkgs = list(self.pins["packages"])
        lib = self.code / "pylib"
        stamp = lib / ".philibert-packages"
        if self._stamp_is(stamp, " ".join(pkgs)) and (lib / "sitecustomize.py").is_file():
            self.log("packages: already here")
            return
        new = self.code / ".pylib-new"
        if new.exists():
            shutil.rmtree(new)
        tmp = self.root / "runtime" / "_download" / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PYTHONNOUSERSITE": "1", "TEMP": str(tmp), "TMP": str(tmp), "PIP_NO_INPUT": "1"}
        env.pop("PYTHONPATH", None)
        self.emit(-1, "Getting Philibert Code's Python packages")
        code = self.run_lines([str(self.py), "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check",
                               "--target", str(new), *pkgs],
                              lambda line: self.emit(-1, line[:90]), env=env)
        if code != 0:
            raise RuntimeError("Could not install Philibert Code's Python packages (details in data\\code\\logs\\setup.log).")
        (new / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
        if lib.exists():
            shutil.rmtree(lib)
        new.rename(lib)
        stamp.write_text(" ".join(pkgs), encoding="utf-8")
        # prove it: the three import from pylib the way start.ps1 runs Python
        chk = subprocess.run([str(self.py), "-c", "import win32gui, PIL, ruff; print('ok')"], capture_output=True, text=True,
                             env={**env, "PYTHONPATH": str(lib)}, timeout=120, creationflags=_NO_WINDOW)
        if "ok" not in chk.stdout:
            raise RuntimeError("Philibert Code's Python packages did not load: " + (chk.stderr or chk.stdout)[-300:])
        self.log("packages: " + " ".join(pkgs))

    # -- the coding model --------------------------------------------------------------------------
    def _running_ollama(self):
        """Philibert's own Ollama, if it is running (same exe): its URL, so the store has one writer."""
        try:
            import psutil
        except ImportError:
            return None
        want = str(self.ollama_exe.resolve()).lower()
        for pr in psutil.process_iter(["exe"]):
            try:
                if str(pr.info["exe"] or "").lower() != want:
                    continue
                for c in pr.net_connections(kind="tcp"):
                    if c.status == psutil.CONN_LISTEN and c.laddr.ip in ("127.0.0.1", "::1", "0.0.0.0", "::"):
                        url = f"http://127.0.0.1:{c.laddr.port}"
                        urllib.request.urlopen(url + "/api/version", timeout=2)
                        return url
            except Exception:
                continue
        return None

    def step_model(self):
        m = self.pins["model"]
        srv = None
        self.ollama_url = self.plan.get("ollama_url") or self._running_ollama()
        if not self.ollama_url:
            port = free_port(11435)
            env = {**os.environ, "OLLAMA_MODELS": str(self.root / "models"), "OLLAMA_HOST": f"127.0.0.1:{port}",
                   "OLLAMA_NOPRUNE": "1"}
            srv = subprocess.Popen([str(self.ollama_exe), "serve"], env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
            self.ollama_url = f"http://127.0.0.1:{port}"
            for _ in range(60):
                try:
                    urllib.request.urlopen(self.ollama_url + "/api/version", timeout=2)
                    break
                except Exception:
                    time.sleep(0.5)
        try:
            if not self._has_tag(m["tag"], m["num_ctx"]):
                warned = len(self.state["warnings"])
                self.pull(m["pull"], "The coding model (Qwen3.6 coding, about 22 GB)")
                if len(self.state["warnings"]) > warned:      # Installer.pull warns instead of raising
                    self.state["warnings"].pop()
                    raise RuntimeError("The coding model did not finish downloading. Run Setup again to continue it.")
                self.emit(-1, "Making the coding model's 128K-window version")
                body = json.dumps({"model": m["tag"], "from": m["pull"], "parameters": {"num_ctx": m["num_ctx"]},
                                   "stream": False}).encode()
                req = urllib.request.Request(self.ollama_url + "/api/create", data=body, method="POST",
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=600) as r:
                    res = json.loads(r.read() or b"{}")
                if res.get("error") or not self._has_tag(m["tag"], m["num_ctx"]):
                    raise RuntimeError(f"Could not make {m['tag']}: {res.get('error') or 'it is not there afterwards'}")
            self.log(f"model ready: {m['tag']} (num_ctx {m['num_ctx']}, from {m['pull']})")
        finally:
            if srv is not None:
                subprocess.run(["taskkill", "/PID", str(srv.pid), "/T", "/F"], capture_output=True, creationflags=_NO_WINDOW)

    def _has_tag(self, tag, num_ctx):
        req = urllib.request.Request(self.ollama_url + "/api/show", data=json.dumps({"model": tag}).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                info = json.loads(r.read() or b"{}")
        except Exception:
            return False
        return bool(re.search(rf"(?m)^num_ctx\s+{num_ctx}\b", str(info.get("parameters") or "")))

    # -- the optional desktop shortcut (the only thing Setup would put on this computer) -------------
    _SHORTCUT_PS = r"""
$d=[Environment]::GetFolderPath('Desktop'); if ($env:PC_DESKTOP) { $d=$env:PC_DESKTOP }   # tests
$l=Join-Path $d 'Philibert Code.lnk'
$w=New-Object -ComObject WScript.Shell
$s=$w.CreateShortcut($l); $s.TargetPath=$env:PC_TARGET; $s.WorkingDirectory=$env:PC_DIR
$s.WindowStyle=7; $s.Description='Philibert Code'; $s.IconLocation=$env:PC_ICO + ',0'; $s.Save()
if (Test-Path -LiteralPath $l) { 'OK ' + $l } else { 'MISSING ' + $l }
"""

    def step_shortcut(self):
        """Desktop\\Philibert Code.lnk -> code\\Start-Philibert-Code.bat, with Philibert Code's icon. Values go in
        through the environment, never pasted into the script. The real desktop (OneDrive may have moved it)."""
        if not self.plan.get("shortcut") or not IS_WIN:
            return
        env = {**os.environ, "PC_TARGET": str(self.code / "Start-Philibert-Code.bat"), "PC_DIR": str(self.code),
               "PC_ICO": str(self.code / "philibert-code.ico")}
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", self._SHORTCUT_PS],
                               capture_output=True, text=True, env=env, timeout=60, creationflags=_NO_WINDOW)
            line = ((r.stdout or "").strip().splitlines() or [(r.stderr or "").strip()[:200]])[-1]
        except (OSError, subprocess.SubprocessError) as e:
            line = f"ERROR {e}"
        self.log(f"desktop shortcut: {line}")
        if not line.startswith("OK "):
            self.state["warnings"].append("Couldn't put a Philibert Code shortcut on the desktop - start it with "
                                          "code\\Start-Philibert-Code.bat in the Philibert folder.")

    # -- finish ------------------------------------------------------------------------------------
    def step_finish(self):
        rec = {"product": "Philibert Code", "installed": datetime.now().isoformat(timespec="seconds"),
               "opencode": self.pins["opencode"]["version"], "git": self.pins["git"]["version"],
               "packages": self.pins["packages"], "model": self.pins["model"]["tag"] if self.plan.get("model", True) else "",
               "build": json.loads((self.code / "app" / "BUILD.json").read_text(encoding="utf-8")).get("source", {})}
        (self.code / "install.json").write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        shutil.rmtree(self.code / "_download", ignore_errors=True)
        self.log("install finished")

    def run(self):
        steps = [("check", "Checking Philibert and this computer", 1, self.step_check),
                 ("app", "Copying Philibert Code", 3, self.step_app),
                 ("tools", "Getting OpenCode and Git", 10, self.step_tools),
                 ("python", "Getting Philibert Code's Python packages", 6, self.step_python)]
        if self.plan.get("model", True):
            steps.append(("model", "Getting the coding model", 80, self.step_model))
        steps.append(("finish", "Finishing", 1, self.step_finish))
        if self.plan.get("shortcut"):
            steps.insert(-1, ("shortcut", "Putting a shortcut on the desktop", 1, self.step_shortcut))
        self.state["steps"] = [{"id": i, "title": t, "weight": w} for i, t, w, _ in steps]
        self.log(f"---- Philibert Code into {self.code} ----")
        try:
            for n, (_, _, _, fn) in enumerate(steps):
                self.state["step"] = n
                self.emit(0.0, "")
                fn()
            self.state["step_pct"] = 1.0
            self.state["done"] = True
            self.emit(1.0, "Philibert Code is ready")
        except Exception as e:                  # Cancelled included: the message says so
            self.state["error"] = "cancelled" if type(e).__name__ == "Cancelled" else str(e)
            self.log(f"STOPPED: {self.state['error']}")
            self.report_cb(dict(self.state))
        return self.state
