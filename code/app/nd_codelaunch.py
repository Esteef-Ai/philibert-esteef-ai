"""Philibert's desktop -> Philibert Code (dev/PHILIBERT_CODE.md, phase 5).

The Philibert Code icon on Philibert's retro desktop only shows when Philibert Code is installed in this
Philibert (code\\install.json, written by its Setup). Opening it starts Philibert Code (its own window), or -
if it is already running (data\\code\\run.json answers) - hands back its address so Philibert opens a window
on it. Nothing here changes Philibert Code; it only reads and starts it.
Owned by the Philibert repo (shared/), copied into Philibert's app by dev/sync_app.py.
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def status(root):
    """{"installed": bool, "running": url or ""} for the Philibert at `root`."""
    root = Path(root)
    code = root / "code"
    inst = (code / "install.json").is_file() and (code / "start.ps1").is_file()
    return {"installed": inst, "running": running(root) if inst else ""}


def running(root):
    run = Path(root) / "data" / "code" / "run.json"
    try:
        url = str(json.loads(run.read_text(encoding="utf-8-sig")).get("url") or "")
    except (OSError, ValueError):
        return ""
    if not url.startswith("http://127.0.0.1:"):           # only ever this computer
        return ""
    try:
        urllib.request.urlopen(url + "/api/status", timeout=3).read()
        return url
    except Exception:
        return ""


def open_code(root):
    """-> {"ok", "url" (already running: open a window on it) | "started": True (it opens its own window)}."""
    st = status(root)
    if not st["installed"]:
        return {"ok": False, "msg": "Philibert Code is not installed in this Philibert. Get it with Philibert Code Setup."}
    if st["running"]:
        return {"ok": True, "url": st["running"]}
    if sys.platform != "win32":
        return {"ok": False, "msg": "Philibert Code runs on Windows for now."}
    script = Path(root) / "code" / "start.ps1"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ND_", "PHILIBERT_", "OLLAMA_"))}
    env.pop("PYTHONPATH", None)                           # Philibert's own settings are not Philibert Code's
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script)],
                     cwd=str(script.parent), env=env, creationflags=NO_WINDOW | 0x00000008,   # DETACHED_PROCESS
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    return {"ok": True, "started": True}
