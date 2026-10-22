"""Philibert Setup - the install itself.

install(plan, report) puts Philibert into plan["dest"] and calls report(state)
as it goes. The plan comes from the wizard:

    {"dest": "K:\\Philibert", "pcs": ["windows", "mac"], "edition": "slim" | "full",
     "full": {"themes": {...}, "retro_vault": true}, "models": ["qwen3:8b", ...],
     "shortcut": false, "source": {"local": "<repo folder>"} |
                                   {"repo": "owner/name", "branch": "main", "token": "..."}}
    (the token, for a private repository, is only ever in memory - never in a log)

Everything goes to the destination; nothing is installed on the computer (the
optional desktop shortcut is the only exception, and only when asked for).
This computer's runtime is set up completely; the other computer's archives are
downloaded and unpacked on that computer's first start (Mac apps hold symlinks,
which a Windows PC cannot write onto exFAT). Re-running over an existing install
updates the app and fills in what is missing; the user's data is never touched.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
_NO_WINDOW = 0x08000000 if IS_WIN else 0

# What a drive gets from the repo (the same list as dev/deploy_local.py)
SHIP = ["app", "setup", "brand/final", "Start-Windows.bat", "Start-Full-Windows.bat",
        "Start-Mac.command", "Start-Full-Mac.command", "models.json", "philibert.json", "README.md"]


class Cancelled(Exception):
    pass


def this_platform():
    if IS_WIN:
        return "win-x64"
    import platform
    return "mac-arm64" if platform.machine().lower() == "arm64" else "mac-x64"


def platforms_for(pcs):
    out = []
    if "windows" in pcs:
        out.append("win-x64")
    if "mac" in pcs:
        out += ["mac-arm64", "mac-x64"]      # both chips: the drive may meet either
    return out


def free_port(start, count=20):
    for p in range(start, start + count):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"No free network port (tried {start}-{start + count - 1}).")


class Installer:
    def __init__(self, plan, report, log_path=None):
        self.plan = plan
        self.report_cb = report
        self.dest = Path(plan["dest"])
        self.pcs = plan.get("pcs") or ["windows", "mac"]
        self.cancel = False
        self.state = {"steps": [], "step": 0, "step_pct": 0.0, "detail": "", "overall": 0.0,
                      "error": "", "done": False, "warnings": []}
        self.log_path = Path(log_path) if log_path else None
        self.child = None

    # -- reporting ---------------------------------------------------------------
    def log(self, msg):
        if not self.log_path:
            return
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
        except OSError:
            pass

    def emit(self, pct=None, detail=None):
        if self.cancel:
            raise Cancelled()
        if pct is not None:
            self.state["step_pct"] = pct
        if detail is not None:
            self.state["detail"] = detail
        steps = self.state["steps"]
        total = sum(s["weight"] for s in steps) or 1
        done = sum(s["weight"] for s in steps[:self.state["step"]])
        within = self.state["step_pct"] if self.state["step_pct"] >= 0 else 0.35
        cur = steps[self.state["step"]]["weight"] if steps else 0
        self.state["overall"] = min(1.0, (done + cur * within) / total)
        self.report_cb(dict(self.state))

    # -- building blocks -----------------------------------------------------------
    def download(self, url, out, label, headers=None):
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, 9):
            try:
                have = out.stat().st_size if out.exists() else 0
                req = urllib.request.Request(url, headers={"User-Agent": "Philibert-setup", **(headers or {})})
                if have:
                    req.add_header("Range", f"bytes={have}-")
                with urllib.request.urlopen(req, timeout=60) as r:
                    if have and r.status != 206:
                        have = 0
                    length = int(r.headers.get("Content-Length") or 0)
                    total = have + length if length else 0
                    done, t0, start = have, time.time(), have
                    with open(out, "ab" if have else "wb") as f:
                        while True:
                            chunk = r.read(1 << 20)
                            if not chunk:
                                break
                            f.write(chunk)
                            done += len(chunk)
                            secs = max(0.5, time.time() - t0)
                            speed = (done - start) / 1048576 / secs
                            self.emit(done / total if total else -1,
                                      f"{label} - {done / 1048576:,.0f} of {total / 1048576:,.0f} MB  ({speed:.1f} MB/s)"
                                      if total else f"{label} - {done / 1048576:,.0f} MB")
                if total and out.stat().st_size < total:
                    raise IOError("the download was cut short")
                self.log(f"downloaded {url}")
                return out
            except Cancelled:
                raise
            except Exception as e:
                self.log(f"download attempt {attempt} of {url} failed: {e}")
                self.emit(-1, f"{label} - connection trouble, trying again ({attempt} of 8)")
                time.sleep(min(20, 3 * attempt))
        raise RuntimeError(f"Could not download {label}. Check the Internet connection and run "
                           f"Setup again - it continues where it stopped.")

    def unpack(self, archive, into, expect, label):
        self.emit(-1, f"{label} - unpacking")
        into = Path(into)
        into.mkdir(parents=True, exist_ok=True)
        archive = Path(archive)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as z:
                names = z.namelist()
                for i, n in enumerate(names):
                    z.extract(n, into)
                    if i % 200 == 0:
                        self.emit(i / max(1, len(names)), f"{label} - unpacking")
        else:
            with tarfile.open(archive) as t:
                members = t.getmembers()
                for i, m in enumerate(members):
                    if m.issym() or m.islnk():
                        continue          # this platform's archives have none we need
                    t.extract(m, into, set_attrs=False)
                    if i % 200 == 0:
                        self.emit(i / max(1, len(members)), f"{label} - unpacking")
        if not Path(expect).exists():
            raise RuntimeError(f"Could not unpack {label}.")
        archive.unlink(missing_ok=True)

    def run_lines(self, args, on_line, env=None):
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", creationflags=_NO_WINDOW, env=env)
        self.child = p
        try:
            for line in p.stdout:
                line = line.rstrip()
                if line:
                    self.log(line)
                    on_line(line)
                if self.cancel:
                    p.kill()
                    raise Cancelled()
            return p.wait()
        finally:
            self.child = None

    # -- the steps -------------------------------------------------------------------
    def step_app(self):
        src = self.plan.get("source") or {}
        if src.get("local"):
            root = Path(src["local"])
        else:
            repo, branch = src.get("repo"), src.get("branch", "main")
            tmp = Path(tempfile.mkdtemp(prefix="philibert_"))
            if src.get("token"):              # a private repository: GitHub's API, signed in
                z = self.download(f"https://api.github.com/repos/{repo}/zipball/{branch}", tmp / "philibert.zip",
                                  "Philibert", {"Authorization": f"Bearer {src['token']}",
                                                "Accept": "application/vnd.github+json"})
            else:
                z = self.download(f"https://codeload.github.com/{repo}/zip/refs/heads/{branch}",
                                  tmp / "philibert.zip", "Philibert")
            with zipfile.ZipFile(z) as zf:
                zf.extractall(tmp)
            root = next(p for p in tmp.iterdir() if p.is_dir())
        files = []
        for item in SHIP:
            p = root / item
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files += [f for f in p.rglob("*") if f.is_file() and "__pycache__" not in f.parts]
        for i, f in enumerate(files):
            out = self.dest / f.relative_to(root)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, out)
            if i % 20 == 0:
                self.emit(i / max(1, len(files)), f"Copying Philibert - {i} of {len(files)} files")
        self.pins = json.loads((self.dest / "setup" / "pins.json").read_text(encoding="utf-8"))
        self.log(f"app: {len(files)} files")

    def _stamp_is(self, f, value):
        return f.exists() and f.read_text(encoding="utf-8").strip() == value

    def step_runtime_here(self):
        """This computer's runtime, complete: Python + packages, Ollama, the window."""
        plat = this_platform()
        rt = self.dest / "runtime" / plat
        dl = self.dest / "runtime" / "_download" / plat
        pins = self.pins
        py = rt / "python" / ("python.exe" if IS_WIN else "bin/python3")
        if not (rt / "python" / ".philibert-ready").exists():
            a = self.download(pins["python"][plat], dl / "python.tar.gz", "Python (about 30 MB)")
            self.unpack(a, rt, py, "Python")
            (rt / "python" / ".philibert-ready").write_text("ok", encoding="ascii")
        pkgs = pins["packages"]["windows" if IS_WIN else "mac"]
        stamp = rt / "python" / ".philibert-packages"
        if not self._stamp_is(stamp, " ".join(pkgs)):
            seen = [0]
            env = {**os.environ, "PYTHONNOUSERSITE": "1", "TEMP": str(dl / "tmp"), "TMP": str(dl / "tmp"),
                   "TMPDIR": str(dl / "tmp")}
            (dl / "tmp").mkdir(parents=True, exist_ok=True)

            def on_line(line):
                if line.startswith(("Collecting", "Requirement already satisfied")):
                    seen[0] += 1
                    self.emit(min(0.9, seen[0] / 40), "Getting " + line.split()[1].split("=")[0].split(">")[0])
                elif line.startswith("Installing collected packages"):
                    self.emit(0.93, "Installing onto the drive")
            code = self.run_lines([str(py), "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check",
                                   "--no-warn-script-location", "--progress-bar", "off", *pkgs], on_line, env)
            if code != 0:
                raise RuntimeError("Could not install the app's building blocks. Check the Internet "
                                   "connection and run Setup again.")
            stamp.write_text(" ".join(pkgs), encoding="ascii")
        self.step_ollama_window(plat, rt, dl)

    def step_ollama_window(self, plat, rt, dl):
        pins = self.pins
        ol = rt / "ollama" / ("ollama.exe" if IS_WIN else "ollama")
        if not self._stamp_is(rt / "ollama" / ".philibert-version", pins["ollama"]["version"]):
            name = "ollama.zip" if IS_WIN else "ollama.tgz"
            a = self.download(pins["ollama"][plat], dl / name, "Ollama")
            self.unpack(a, rt / "ollama", ol, "Ollama")
            (rt / "ollama" / ".philibert-version").write_text(pins["ollama"]["version"], encoding="ascii")
        if IS_WIN:
            cr = rt / "chromium" / "chrome-win64" / "chrome.exe"
            if not self._stamp_is(rt / "chromium" / ".philibert-version", pins["chromium"]["version"]):
                a = self.download(pins["chromium"][plat], dl / "chromium.zip", "the window")
                self.unpack(a, rt / "chromium", cr, "the window")
                (rt / "chromium" / ".philibert-version").write_text(pins["chromium"]["version"], encoding="ascii")
        self.ollama_exe = ol

    def step_other_pcs(self):
        """Archives for the other computers, unpacked there on their first start."""
        here = this_platform()
        for plat in platforms_for(self.pcs):
            if plat == here:
                continue
            dl = self.dest / "runtime" / "_download" / plat
            if (self.dest / "runtime" / plat / "python" / ".philibert-ready").exists():
                continue
            pretty = {"win-x64": "Windows", "mac-arm64": "Mac (Apple chip)", "mac-x64": "Mac (Intel chip)"}[plat]
            win = plat == "win-x64"
            for key, name in (("python", "python.tar.gz"), ("ollama", "ollama.zip" if win else "ollama.tgz"),
                              ("chromium", "chromium.zip")):
                f = dl / name
                if f.exists() and (dl / (name + ".ok")).exists():
                    continue
                self.download(self.pins[key][plat], f, f"{pretty}: {key if key != 'chromium' else 'window'}")
                (dl / (name + ".ok")).write_text("ok", encoding="ascii")

    def step_data(self):
        data = self.dest / "data"
        for d in ("vault", "exports", "logs"):
            (data / d).mkdir(parents=True, exist_ok=True)
        (self.dest / "secrets").mkdir(exist_ok=True)
        (self.dest / "models").mkdir(exist_ok=True)
        cfg = data / "neuraldock_config.json"
        if not cfg.exists():
            shutil.copy2(self.dest / "setup" / "default_config.json", cfg)
        vault = data / "vault"
        if not any(vault.rglob("*.md")):
            shutil.copytree(self.dest / "setup" / "welcome_vault", vault, dirs_exist_ok=True)
        if self.plan.get("edition") == "full" and (self.plan.get("full") or {}).get("retro_vault", True):
            (self.dest / "Entertainment" / "Cartridges").mkdir(parents=True, exist_ok=True)
        info = {"version": 1, "installed": datetime.now().isoformat(timespec="seconds"),
                "edition": self.plan.get("edition", "slim"), "pcs": self.pcs,
                "full": self.plan.get("full") or {}, "models": self.plan.get("models") or []}
        (data / "install.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        self.emit(1.0, "Your notes and settings live in data on this drive")

    def step_models(self):
        tags = list(dict.fromkeys(self.plan.get("models") or []))
        if not tags:
            return
        ol = getattr(self, "ollama_exe", None)
        tmp_ollama = None
        if not ol or not Path(ol).exists():
            # e.g. a Mac-only drive set up from a Windows PC: borrow this PC's Ollama
            # just to fetch the models (the store is the same on both), then drop it
            tmp_ollama = Path(tempfile.mkdtemp(prefix="philibert_ollama_"))
            plat = this_platform()
            a = self.download(self.pins["ollama"][plat], tmp_ollama / ("o.zip" if IS_WIN else "o.tgz"), "Ollama (temporary)")
            ol = tmp_ollama / ("ollama.exe" if IS_WIN else "ollama")
            self.unpack(a, tmp_ollama, ol, "Ollama (temporary)")
        port = free_port(11435)
        env = {**os.environ, "OLLAMA_MODELS": str(self.dest / "models"), "OLLAMA_HOST": f"127.0.0.1:{port}",
               "OLLAMA_NOPRUNE": "1"}
        srv = subprocess.Popen([str(ol), "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=_NO_WINDOW)
        self.ollama_url = f"http://127.0.0.1:{port}"
        try:
            for _ in range(60):
                try:
                    urllib.request.urlopen(self.ollama_url + "/api/version", timeout=2)
                    break
                except Exception:
                    time.sleep(0.5)
            for n, tag in enumerate(tags):
                self.pull(tag, f"Model {n + 1} of {len(tags)}: {tag.split('/')[-1]}")
            if "windows" in self.pcs and IS_WIN or "mac" in self.pcs and IS_MAC:
                self.step_speech()
        finally:
            if IS_WIN:
                subprocess.run(["taskkill", "/PID", str(srv.pid), "/T", "/F"], capture_output=True,
                               creationflags=_NO_WINDOW)
            else:
                srv.terminate()
            if tmp_ollama:
                shutil.rmtree(tmp_ollama, ignore_errors=True)

    def pull(self, tag, label):
        req = urllib.request.Request(self.ollama_url + "/api/pull", method="POST",
                                     data=json.dumps({"model": tag, "stream": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        for attempt in range(1, 6):
            try:
                with urllib.request.urlopen(req, timeout=3600) as r:
                    for raw in r:
                        ev = json.loads(raw or b"{}")
                        if ev.get("error"):
                            raise RuntimeError(ev["error"])
                        tot, got = ev.get("total") or 0, ev.get("completed") or 0
                        if tot:
                            self.emit(got / tot, f"{label} - {got / 2**30:.1f} of {tot / 2**30:.1f} GB")
                        else:
                            self.emit(-1, f"{label} - {ev.get('status', '')}")
                self.log(f"model ready: {tag}")
                return
            except Cancelled:
                raise
            except Exception as e:
                self.log(f"pull {tag} attempt {attempt} failed: {e}")
                self.emit(-1, f"{label} - trying again ({attempt} of 5)")
                time.sleep(5 * attempt)
        self.state["warnings"].append(f"{tag} did not finish downloading; pick it in Philibert's model list later.")

    def step_speech(self):
        plat = this_platform()
        py = self.dest / "runtime" / plat / "python" / ("python.exe" if IS_WIN else "bin/python3")
        env = {**os.environ, "PYTHONNOUSERSITE": "1", "ND_OLLAMA_URL": self.ollama_url,
               "HF_HOME": str(self.dest / "speech" / "hf"), "ND_VOICES_DIR": str(self.dest / "speech" / "voices"),
               "ND_WHISPER_DIR": str(self.dest / "speech" / "whisper"), "HF_HUB_DISABLE_TELEMETRY": "1",
               "PYTHONIOENCODING": "utf-8"}
        self.emit(-1, "Getting the voices")

        def on_line(line):
            self.emit(-1, line.strip()[:90])
        code = self.run_lines([str(py), str(self.dest / "app" / "nd_philibert.py"), "--first-run"], on_line, env)
        if code != 0:
            self.state["warnings"].append("Some voice files did not finish; Philibert fetches them on its next start.")

    def step_games(self):
        """Retro Vault: EmulatorJS and its cores onto the drive (about 24 MB), so games
        play offline. Fetched here, not shipped in git: they are GPL / non-commercial."""
        py = self.dest / "runtime" / this_platform() / "python" / ("python.exe" if IS_WIN else "bin/python3")
        env = {**os.environ, "PYTHONNOUSERSITE": "1", "PYTHONIOENCODING": "utf-8"}
        got = [0]

        def on_line(line):
            got[0] += 1
            self.emit(min(1.0, got[0] / 26), line.replace("emulator: ", "Game player: ")[:90])
        code = self.run_lines([str(py), str(self.dest / "app" / "nd_retro_vault.py"), "--fetch",
                               str(self.dest / "Entertainment")], on_line, env)
        if code != 0:
            self.state["warnings"].append("Retro Vault's game players did not finish downloading; "
                                          "run Setup again with the Internet on.")

    def step_shortcut(self):
        if not self.plan.get("shortcut") or not IS_WIN:
            return
        desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
        lnk = desktop / "Philibert.lnk"
        target = self.dest / "Start-Windows.bat"
        icon = self.dest / "setup" / "assets" / "philibert.ico"
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{0}');$s.TargetPath='{1}';"
              "$s.WorkingDirectory='{2}';{3}$s.Save()").format(
            lnk, target, self.dest, f"$s.IconLocation='{icon}';" if icon.exists() else "")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, creationflags=_NO_WINDOW)

    # -- the whole thing -------------------------------------------------------------
    def run(self):
        here_pc = "windows" if IS_WIN else "mac"
        steps = [("app", "Copying Philibert onto the drive", 4, self.step_app)]
        if here_pc in self.pcs:
            steps.append(("runtime", "Setting up Philibert for this computer", 45, self.step_runtime_here))
        if any(p != this_platform() for p in platforms_for(self.pcs)):
            steps.append(("others", "Getting what the other computers need", 25, self.step_other_pcs))
        steps += [("data", "Making room for your notes", 1, self.step_data),
                  ("models", "Getting the AI models and voices", 40, self.step_models)]
        if self.plan.get("edition") == "full" and (self.plan.get("full") or {}).get("retro_vault", True) \
                and here_pc in self.pcs:
            steps.append(("games", "Getting Retro Vault's game players", 3, self.step_games))
        steps.append(("shortcut", "Finishing", 1, self.step_shortcut))
        self.state["steps"] = [{"id": i, "title": t, "weight": w} for i, t, w, _ in steps]
        self.log(f"---- install to {self.dest} ({', '.join(self.pcs)}, {self.plan.get('edition')}) ----")
        try:
            self.dest.mkdir(parents=True, exist_ok=True)
            for n, (_, _, _, fn) in enumerate(steps):
                self.state["step"] = n
                self.emit(0.0, "")
                fn()
            self.state["step_pct"] = 1.0
            self.state["done"] = True
            self.emit(1.0, "Philibert is ready")
            self.log("install finished")
        except Cancelled:
            self.state["error"] = "cancelled"
            self.log("cancelled")
            self.report_cb(dict(self.state))
        except Exception as e:
            self.state["error"] = str(e)
            self.log(f"STOPPED: {e}")
            self.report_cb(dict(self.state))
        return self.state
