"""Philibert Code Setup (installer/code_engine.py). Run: python installer/tests/test_code_engine.py

Unit checks run anywhere. The install check builds a stand-in Philibert in a scratch folder (junctions to a
real install's runtime, read-only) and runs every step except the model download; the model step runs
against a fake Ollama. Set PHILIBERT_TEST_INSTALL to borrow another install (default E:\\Philibert);
CODE_TEST_DOWNLOADS=<folder with opencode.zip and mingit.zip> skips downloading them again.
"""
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import code_engine as ce  # noqa: E402

REPO = HERE.parent.parent
REAL = Path(os.environ.get("PHILIBERT_TEST_INSTALL") or r"E:\Philibert")
fails = []


def check(label, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + label + ("" if ok else f"   ({str(detail)[:300]})"))
    if not ok:
        fails.append(label)


PINS = json.loads((REPO / "code" / "pins.json").read_text(encoding="utf-8"))

# -- pins ---------------------------------------------------------------------------------------------
for k in ("opencode", "git"):
    check(f"{k}: an https GitHub release, pinned version, sha256", PINS[k]["win-x64"].startswith("https://github.com/")
          and PINS[k]["version"] in PINS[k]["win-x64"] and re.fullmatch(r"[0-9a-f]{64}", PINS[k]["sha256"]))
check("packages are pinned exactly", all(re.fullmatch(r"[A-Za-z0-9_\-]+==[\w.]+", p) for p in PINS["packages"]), PINS["packages"])
worker = (REPO / "code" / "app" / "opencode_worker.py").read_text(encoding="utf-8")
check("the OpenCode pin matches the version the worker was measured on",
      f'OPENCODE_VERSION = "{PINS["opencode"]["version"]}"' in worker)
check("the model tag and window match the worker's", f'MODEL = "{PINS["model"]["tag"]}"' in worker
      and f"WINDOW = {PINS['model']['num_ctx']}" in worker)
check("hardware floor is 16 GB graphics / 32 GB memory", PINS["hardware"] == {"vram_gb": 16, "ram_gb": 32})

# -- small rules --------------------------------------------------------------------------------------
V = ce.version_tuple
check("versions compare as numbers", V("0.40.15") > V("0.40.4") and V("ollama version is 0.40.15") == (0, 40, 15)
      and V("Warning: client version is 0.40.4") == (0, 40, 4) and V("") == (0, 0, 0))
ok, msg = ce.hardware_verdict({"fast_gb": 16, "ram_gb": 64}, PINS["hardware"])
check("16 GB card + 64 GB memory: ready", ok and "ready" in msg, msg)
ok, msg = ce.hardware_verdict({"fast_gb": 8, "ram_gb": 16}, PINS["hardware"])
check("8 GB card + 16 GB memory: a plain warning naming both", not ok and "8 GB of graphics memory" in msg
      and "16 GB of memory" in msg and "anyway" in msg, msg)
tmp = Path(tempfile.mkdtemp(prefix="pc_unit_"))
check("no Philibert: says so", "not installed" in ce.philibert_problem(tmp))
(tmp / "app").mkdir()
(tmp / "app" / "NeuralDock_launcher.py").write_text("#")
check("Philibert never started here: asks to start it once", "start Philibert once" in ce.philibert_problem(tmp))
check("find_philibert skips folders that are not a set-up Philibert", tmp not in ce.find_philibert([tmp]))
shutil.rmtree(tmp, ignore_errors=True)

# -- a tampered download is refused --------------------------------------------------------------------
tmp = Path(tempfile.mkdtemp(prefix="pc_sha_"))
try:
    inst = ce.CodeInstaller({"philibert": str(tmp)}, lambda s: None, log_path=tmp / "log.txt")
    inst.pins = {"opencode": {"version": "9.9.9", "win-x64": "https://example.invalid/x.zip", "sha256": "0" * 64}}
    inst.state["steps"] = [{"id": "tools", "title": "t", "weight": 1}]
    inst.download = lambda url, out, label, headers=None: (Path(out).parent.mkdir(parents=True, exist_ok=True),
                                                          Path(out).write_bytes(b"not the real file"))[0]
    try:
        inst._tool("opencode", "OpenCode", "opencode.exe")
        check("a download with the wrong sha256 is refused", False, "it was accepted")
    except RuntimeError as e:
        check("a download with the wrong sha256 is refused, nothing installed", "not the expected file" in str(e)
              and not (tmp / "code" / "tools" / "opencode").exists() and not list((tmp / "code" / "_download").glob("*")), e)
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# -- the model step against a fake Ollama ---------------------------------------------------------------
class FakeOllama(http.server.BaseHTTPRequestHandler):
    calls, tags = [], {}

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        FakeOllama.calls.append((self.path, body))
        if self.path == "/api/show":
            t = FakeOllama.tags.get(body.get("model"))
            self._send(200 if t else 404, {"parameters": t} if t else {"error": "not found"})
        elif self.path == "/api/pull":
            self.send_response(200)
            self.end_headers()
            for done in (0, 11, 22):
                self.wfile.write(json.dumps({"status": "pulling", "total": 22, "completed": done}).encode() + b"\n")
            FakeOllama.tags[body["model"]] = "temperature 0.6"
        elif self.path == "/api/create":
            FakeOllama.tags[body["model"]] = f"num_ctx                        {body['parameters']['num_ctx']}\ntemperature 0.6"
            self._send(200, {"status": "success"})

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=srv.serve_forever, daemon=True).start()
tmp = Path(tempfile.mkdtemp(prefix="pc_model_"))
try:
    inst = ce.CodeInstaller({"philibert": str(tmp), "ollama_url": f"http://127.0.0.1:{srv.server_port}"},
                            lambda s: None, log_path=tmp / "log.txt")
    inst.pins = PINS
    inst.state["steps"] = [{"id": "model", "title": "t", "weight": 1}]
    inst.step_model()
    paths = [p for p, _ in FakeOllama.calls]
    create = next(b for p, b in FakeOllama.calls if p == "/api/create")
    check("the model is pulled, then its 128K tag is made from it", "/api/pull" in paths and paths.index("/api/pull") < paths.index("/api/create")
          and create == {"model": "q36c-nd128k", "from": "qwen3.6:35b-a3b-coding", "parameters": {"num_ctx": 131072}, "stream": False}, FakeOllama.calls)
    FakeOllama.calls.clear()
    inst.step_model()
    check("run again with the tag there: nothing is downloaded or made", [p for p, _ in FakeOllama.calls] == ["/api/show"], FakeOllama.calls)
finally:
    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)


# -- a real install into a stand-in Philibert (no model) ---------------------------------------------------
def standin():
    root = Path(tempfile.mkdtemp(prefix="pc_setup_"))
    (root / "app").mkdir()
    (root / "app" / "NeuralDock_launcher.py").write_text("# stand-in\n")
    (root / "runtime").mkdir()
    os.system(f'cmd /c mklink /J "{root / "runtime" / "win-x64"}" "{REAL / "runtime" / "win-x64"}" >nul')
    return root


def remove_standin(root):
    link = root / "runtime" / "win-x64"
    if os.path.lexists(link):
        try:
            os.rmdir(link)                    # the junction itself, never what it points to
        except OSError as e:
            print(f"NOTE  left {root}: could not remove the link ({e})")
            return
    shutil.rmtree(root, ignore_errors=True)


if (REAL / "runtime" / "win-x64" / "python" / "python.exe").is_file():
    class Installer(ce.CodeInstaller):
        def ollama_version(self):                       # the real check is tested on its own below
            return PINS["ollama_min"]

    root = standin()
    try:
        cache = os.environ.get("CODE_TEST_DOWNLOADS")
        if cache:
            (root / "code" / "_download").mkdir(parents=True)
            shutil.copy(Path(cache) / "opencode.zip", root / "code" / "_download" / f"opencode-{PINS['opencode']['version']}.zip")
            shutil.copy(Path(cache) / "mingit.zip", root / "code" / "_download" / f"git-{PINS['git']['version']}.zip")
        seen = []
        st = Installer({"philibert": str(root), "source": {"local": str(REPO)}, "accept_slow": True, "model": False},
                       lambda s: seen.append(s.get("detail"))).run()
        check("Setup finishes (no model)", st.get("done") and not st.get("error"), st.get("error"))
        c = root / "code"
        check("the program is in code\\app, with start.ps1 and the .bat", (c / "app" / "NeuralDock_launcher.py").is_file()
              and (c / "start.ps1").is_file() and (c / "Start-Philibert-Code.bat").is_file())
        check("OpenCode and Git are in code\\tools", (c / "tools" / "opencode" / "opencode.exe").is_file()
              and (c / "tools" / "git" / "cmd" / "git.exe").is_file())
        check("the Python packages are in code\\pylib with the sitecustomize", (c / "pylib" / "sitecustomize.py").is_file()
              and (c / "pylib" / "win32").is_dir() and (c / "pylib" / "PIL").is_dir())
        rec = json.loads((c / "install.json").read_text(encoding="utf-8"))
        check("install.json records the versions", rec["opencode"] == PINS["opencode"]["version"] and rec["model"] == "", rec)
        check("downloads are cleaned up", not (c / "_download").exists())
        check("data\\code is made, and nothing else in data", sorted(p.name for p in (root / "data").iterdir()) == ["code"])
        import subprocess
        v = subprocess.run([str(c / "tools" / "opencode" / "opencode.exe"), "--version"], capture_output=True, text=True, timeout=60)
        check("the installed OpenCode runs", v.stdout.strip() == PINS["opencode"]["version"], v.stdout + v.stderr)
        g = subprocess.run([str(c / "tools" / "git" / "cmd" / "git.exe"), "--version"], capture_output=True, text=True, timeout=60)
        check("the installed Git runs", "2.55.0" in g.stdout, g.stdout + g.stderr)
        mark = (c / "app" / "BUILD.json").stat().st_mtime_ns
        (root / "data" / "code" / "chats").mkdir()
        (root / "data" / "code" / "chats" / "keep.json").write_text("{}")
        seen.clear()
        st = Installer({"philibert": str(root), "source": {"local": str(REPO)}, "accept_slow": True, "model": False},
                       lambda s: seen.append(s.get("detail"))).run()
        check("run again: it updates the program and keeps the tools and packages", st.get("done")
              and not any("OpenCode 1" in str(d) and "MB" in str(d) for d in seen) and not any("pip" in str(d).lower() for d in seen), seen[-6:])
        check("run again: data\\code is untouched", (root / "data" / "code" / "chats" / "keep.json").read_text() == "{}")
        # the optional desktop shortcut (to a scratch desktop, never the real one)
        desk = Path(tempfile.mkdtemp(prefix="pc_desk_"))
        os.environ["PC_DESKTOP"] = str(desk)
        try:
            st = Installer({"philibert": str(root), "source": {"local": str(REPO)}, "accept_slow": True, "model": False,
                            "shortcut": True}, lambda s: None).run()
            lnk = desk / "Philibert Code.lnk"
            info = subprocess.run(["powershell", "-NoProfile", "-Command",
                                   "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:L); $s.TargetPath; $s.IconLocation"],
                                  capture_output=True, text=True, env={**os.environ, "L": str(lnk)}).stdout.splitlines()
            check("the shortcut is made when asked: Start-Philibert-Code.bat with Philibert Code's icon",
                  st.get("done") and lnk.is_file() and info and info[0].endswith("Start-Philibert-Code.bat")
                  and "philibert-code.ico" in info[1] and (c / "philibert-code.ico").is_file(), (st.get("error"), info))
        finally:
            os.environ.pop("PC_DESKTOP", None)
            shutil.rmtree(desk, ignore_errors=True)
        # Update-Philibert-Code: a zip of this repo instead of GitHub, through the same engine
        import zipfile
        zpath = Path(tempfile.mkdtemp(prefix="pc_zip_")) / "repo.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for top in ("installer", "code"):
                for f in (REPO / top).rglob("*"):
                    rel = f.relative_to(REPO)
                    if f.is_file() and not set(rel.parts) & {".buildenv", "build", "dist", "__pycache__", "tools", "pylib", "_download"}:
                        z.write(f, "philibert-esteef-ai-main/" + rel.as_posix())
            z.write(REPO / "philibert.json", "philibert-esteef-ai-main/philibert.json")
        shutil.copy(REPO / "philibert.json", root / "philibert.json")
        u = subprocess.run([sys.executable, str(c / "update.py")], capture_output=True, text=True, timeout=900,
                           env={**os.environ, "PC_UPDATE_ZIP": str(zpath), "PC_UPDATE_NO_PAUSE": "1"})
        shutil.rmtree(zpath.parent, ignore_errors=True)
        out = u.stdout + u.stderr
        own = ce.CodeInstaller({"philibert": str(root)}, lambda s: None, log_path=root / "x.log").ollama_version()
        if ce.version_tuple(own) >= ce.version_tuple(PINS["ollama_min"]):
            check("the update runs Setup again from the download and finishes", u.returncode == 0 and "Philibert Code is ready" in out, out[-400:])
        else:
            check(f"the update stops on this Philibert's old Ollama ({own}) and says to update Philibert first",
                  u.returncode == 1 and "Update Philibert" in out and (c / "app" / "NeuralDock_launcher.py").is_file(), out[-400:])
        check("the update leaves data\\code alone", (root / "data" / "code" / "chats" / "keep.json").read_text() == "{}")
        inst = ce.CodeInstaller({"philibert": str(root), "source": {"local": str(REPO)}, "accept_slow": True},
                                lambda s: None, log_path=root / "x.log")
        inst.ollama_version = lambda: "0.40.4"
        inst.state["steps"] = [{"id": "check", "title": "t", "weight": 1}]
        try:
            inst.step_check()
            msg = "accepted"
        except RuntimeError as e:
            msg = str(e)
        check("an Ollama older than the pin is refused, saying what to do",
              f"needs Ollama {PINS['ollama_min']}" in msg and "Update Philibert" in msg, msg)
        real = ce.CodeInstaller({"philibert": str(root)}, lambda s: None, log_path=root / "x.log").ollama_version()
        import subprocess as _sp
        raw = _sp.run([str(REAL / "runtime" / "win-x64" / "ollama" / "ollama.exe"), "--version"], capture_output=True, text=True,
                      env={**os.environ, "OLLAMA_HOST": "127.0.0.1:1"})
        own = re.search(r"client version is\s+(\d+\.\d+\.\d+)", raw.stdout + raw.stderr)
        check(f"the install's OWN Ollama version is read, not this computer's server ({real})",
              bool(re.fullmatch(r"\d+\.\d+\.\d+", real)) and (own is None or own.group(1) == real), (real, raw.stdout + raw.stderr))
    finally:
        remove_standin(root)
else:
    print(f"skip  the install check: no Philibert runtime at {REAL}")


print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED'}")
sys.exit(1 if fails else 0)
