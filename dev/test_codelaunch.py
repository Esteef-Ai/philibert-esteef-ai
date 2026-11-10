"""Phase 5 (dev/PHILIBERT_CODE.md): Philibert's desktop -> Philibert Code (shared/nd_codelaunch.py), the update
script's refusal while it runs, and the desktop edits in Philibert's app. Starts nothing.

    python dev/test_codelaunch.py
"""
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

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared"))
import nd_codelaunch as cl  # noqa: E402

results = []


def check(label, ok, got=""):
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f" - got {got!r}"[:300]))


class Status(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Status)
threading.Thread(target=srv.serve_forever, daemon=True).start()
live = f"http://127.0.0.1:{srv.server_port}"

root = Path(tempfile.mkdtemp(prefix="codelaunch_"))
try:
    check("no Philibert Code here: not installed, no icon", cl.status(root) == {"installed": False, "running": ""})
    r = cl.open_code(root)
    check("opening it when not installed says how to get it", not r["ok"] and "Philibert Code Setup" in r["msg"], r)
    (root / "code").mkdir()
    (root / "code" / "start.ps1").write_text("# stand-in")
    check("start.ps1 alone (a git checkout of the repo) is not an install", not cl.status(root)["installed"])
    (root / "code" / "install.json").write_text("{}")
    check("Setup's install.json: installed, not running", cl.status(root) == {"installed": True, "running": ""})
    run = root / "data" / "code" / "run.json"
    run.parent.mkdir(parents=True)
    run.write_text("﻿" + json.dumps({"url": live, "pid": 1}), encoding="utf-8")   # PowerShell writes a BOM
    check("run.json that answers: running, at that address", cl.status(root)["running"] == live, cl.status(root))
    r = cl.open_code(root)
    check("opening it while it runs: its address (Philibert opens a window on it), nothing started",
          r == {"ok": True, "url": live}, r)
    run.write_text(json.dumps({"url": "http://192.168.0.5:7810"}), encoding="utf-8")
    check("an address that is not this computer is never used", cl.status(root)["running"] == "")
    run.write_text(json.dumps({"url": "http://127.0.0.1:1"}), encoding="utf-8")
    check("a run.json left by a crash (nothing answers) counts as not running", cl.status(root)["running"] == "")
    run.write_text("{not json", encoding="utf-8")
    check("a damaged run.json counts as not running", cl.status(root)["running"] == "")

    # the update script refuses while Philibert Code runs (it would replace the program under it)
    shutil.copy(REPO / "code" / "update.py", root / "code" / "update.py")
    shutil.copy(REPO / "philibert.json", root / "philibert.json")
    run.write_text(json.dumps({"url": live}), encoding="utf-8")
    u = subprocess.run([sys.executable, str(root / "code" / "update.py")], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PC_UPDATE_NO_PAUSE": "1"})
    check("the update refuses while Philibert Code runs, and says to close it", u.returncode == 1
          and "Close its window" in u.stdout, u.stdout[-300:] + u.stderr[-300:])
finally:
    srv.shutdown()
    shutil.rmtree(root, ignore_errors=True)

# -- the desktop edits in Philibert's app ------------------------------------------------------------------
app = REPO / "app"
js = (app / "live" / "static" / "desktop" / "desktop.js").read_text(encoding="utf-8")
la = (app / "NeuralDock_launcher.py").read_text(encoding="utf-8")
check("Philibert's app has the module and the icon", (app / "nd_codelaunch.py").is_file()
      and (app / "live" / "static" / "desktop" / "philibert-code.svg").is_file())
check("the desktop shows the icon only when Philibert Code is installed (code_status)",
      'if (st.code) list.push({ id: "code"' in js and 'op: "code_status"' in js and "r.installed" in js)
check("the server answers code_status and open_code inside /api/desktop (after the sign-in check)",
      la.index('if body.get("op") in ("code_status", "open_code"):') > la.index("if path not in AUTH_EXEMPT and not self.authed():"))
svg = (REPO / "shared" / "philibert-code.svg").read_text(encoding="utf-8")
check("the icon SVG has no comment with '--' and no script (it loads as an <img>)", "<!--" not in svg and "<script" not in svg.lower())
node = shutil.which("node")
if node:
    p = subprocess.run([node, "-e", "new Function(require('fs').readFileSync(process.argv[1],'utf8'))",
                        str(app / "live" / "static" / "desktop" / "desktop.js")], capture_output=True, text=True)
    check("desktop.js still parses", p.returncode == 0, p.stderr[-300:])

passed = sum(results)
print(f"{passed} passed, {len(results) - passed} failed")
sys.exit(0 if passed == len(results) else 1)
