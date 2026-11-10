r"""End-to-end: start Philibert Code from inside a stand-in Philibert install, headless, and check it.

    python dev/test_code_start.py            uses E:\Philibert's runtime and models (read only)
    set PHILIBERT_TEST_INSTALL=K:\Philibert  to borrow another install's

The stand-in is a scratch folder: a copy of this repo's code\, a test notes vault, and junctions to the
real install's runtime\win-x64 and models\ (only read: Ollama runs with OLLAMA_NOPRUNE). Nothing is
written to the real install. Checks: Philibert's presence is required, the page is Philibert Code, the
left-out endpoints refuse, the notes vault is Philibert's, data goes to data\code, and closing Philibert
Code stops the Ollama it started.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REAL = Path(os.environ.get("PHILIBERT_TEST_INSTALL") or r"E:\Philibert")
results = []


def check(label, ok, got=""):
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f" - got {got!r}"[:300]), flush=True)


def post(base, path, body):
    req = urllib.request.Request(base + path, json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Origin": base})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def up(url):
    try:
        urllib.request.urlopen(url, timeout=2).read()
        return True
    except Exception:
        return False


def stop_launcher(root):
    """Close the Philibert Code started from `root` (only that one), as closing its window would."""
    import psutil
    for pr in psutil.process_iter(["name", "cmdline"]):
        try:
            cmd = " ".join(pr.info["cmdline"] or [])
            if (pr.info["name"] or "").lower() == "python.exe" and str(root) in cmd and "NeuralDock_launcher.py" in cmd:
                pr.kill()
        except (psutil.Error, OSError):
            pass


def start(root, extra=()):
    out = root / "start.out"
    p = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                          str(root / "code" / "start.ps1"), "-Headless", *extra],
                         stdout=open(out, "w"), stderr=subprocess.STDOUT)
    return p, out


def main():
    if not (REAL / "runtime" / "win-x64" / "python" / "python.exe").is_file():
        print(f"SKIP: no Philibert runtime at {REAL} (set PHILIBERT_TEST_INSTALL)")
        return 0
    root = Path(tempfile.mkdtemp(prefix="pc_install_"))
    try:
        # -- without Philibert, Philibert Code refuses to start -----------------------------------------
        shutil.copytree(REPO / "code", root / "code", ignore=shutil.ignore_patterns("__pycache__"))
        p, out = start(root)
        p.wait(60)
        check("without Philibert it refuses to start, and says why", p.returncode == 1
              and "needs Philibert" in out.read_text(errors="replace"), out.read_text(errors="replace")[-300:])

        # -- the stand-in install ----------------------------------------------------------------------
        (root / "app").mkdir()
        (root / "app" / "NeuralDock_launcher.py").write_text("# stand-in\n")
        (root / "runtime").mkdir()
        for link, target in ((root / "runtime" / "win-x64", REAL / "runtime" / "win-x64"), (root / "models", REAL / "models")):
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
        note = root / "data" / "vault" / "Projects" / "Shared note.md"
        note.parent.mkdir(parents=True)
        note.write_text("# Shared note\nWritten in Philibert, read by Philibert Code.\n", encoding="utf-8")
        chat = root / "data" / "chats" / "c20261109-090000-abcd.json"
        chat.parent.mkdir(parents=True)
        chat.write_text(json.dumps({"id": "c20261109-090000-abcd", "title": "Venue load-in times", "updated": time.time(),
                                    "messages": [{"role": "user", "content": "When is load-in at the Roxy?"},
                                                 {"role": "assistant", "content": "Load-in is at 4 pm."}]}), encoding="utf-8")

        p, out = start(root)
        base = ollama = None
        end = time.time() + 120
        while time.time() < end and p.poll() is None:
            t = out.read_text(errors="replace")
            m, o = re.search(r"localhost:(\d+)", t), re.search(r"Ollama on port (\d+)", t)
            if m and up(f"http://127.0.0.1:{m.group(1)}/api/status"):
                base, ollama = f"http://127.0.0.1:{m.group(1)}", o and o.group(1)
                break
            time.sleep(0.5)
        check("it starts inside Philibert", base is not None, out.read_text(errors="replace")[-400:])
        if base:
            html = urllib.request.urlopen(base + "/", timeout=10).read().decode("utf-8", "replace")
            check("the page is Philibert Code", "<title>Philibert Code // Esteef.Ai" in html)
            check("the Heretic and device panels are hidden", "Philibert Code: not included" in html)
            for path in ("/api/heretic", "/api/devices", "/api/device/register", "/api/pair_code"):
                code, body = post(base, path, {})
                check(f"{path} is not part of Philibert Code", code == 404 and "not part of Philibert Code" in str(body), (code, body))
            code, body = post(base, "/api/ping", {})
            check("everything else still answers", code == 200 and body.get("ok"), (code, body))
            code, body = post(base, "/api/notes", {"op": "info"})
            check("the notes vault is Philibert's (data\\vault)", Path(str(body.get("vault"))).resolve()
                  == (root / "data" / "vault").resolve(), body)
            code, body = post(base, "/api/notes", {"op": "read", "id": "Projects/Shared note.md"})
            check("a note written in Philibert opens in Philibert Code", "read by Philibert Code" in str(body.get("body")), body)
            code, body = post(base, "/api/chatref", {"op": "list"})
            check("phase 3: Philibert Code lists Philibert's chats", code == 200 and body.get("from") == "Philibert"
                  and [c["title"] for c in body.get("chats", [])] == ["Venue load-in times"], (code, body))
            code, body = post(base, "/api/chatref", {"op": "get", "id": "c20261109-090000-abcd"})
            check("phase 3: and turns one into a quoted, labelled block",
                  '[Referenced chat from Philibert: "Venue load-in times"' in str(body.get("text"))
                  and "> Philibert: Load-in is at 4 pm." in str(body.get("text")), body)
            req = urllib.request.Request(base + "/api/chatref", b'{"op":"list"}', method="POST",
                                         headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
            try:
                urllib.request.urlopen(req, timeout=10)
                refused = False
            except urllib.error.HTTPError as e:
                refused = e.code == 403
            check("phase 3: another website cannot read the chats", refused)
            run = root / "data" / "code" / "run.json"
            rj = json.loads(run.read_text(encoding="utf-8-sig")) if run.is_file() else {}
            check("phase 5: run.json says where it runs", rj.get("url") == base, rj)
            again = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                    str(root / "code" / "start.ps1"), "-Headless"], capture_output=True, text=True, timeout=60)
            check("phase 5: a second start does not start a second copy", again.returncode == 0
                  and "already running" in again.stdout, again.stdout[-200:] + again.stderr[-200:])
            check("its own data goes to data\\code", (root / "data" / "code" / "logs" / "philibert-code.log").is_file())
            check("Philibert's data is not written to", sorted(x.name for x in (root / "data").iterdir()) == ["chats", "code", "vault"],
                  sorted(x.name for x in (root / "data").iterdir()))
        # -- closing Philibert Code stops the Ollama it started ------------------------------------------
        stop_launcher(root)
        try:
            p.wait(30)
        except subprocess.TimeoutExpired:
            p.kill()
        check("closing it stops the Ollama it started", ollama is not None and not up(f"http://127.0.0.1:{ollama}/api/version"),
              (ollama, out.read_text(errors="replace")[-200:]))
        check("phase 5: closing it removes run.json", not (root / "data" / "code" / "run.json").exists())
    finally:
        stop_launcher(root)
        # The junctions point at a REAL install. Remove each link itself (os.rmdir never follows it);
        # if any link is still there, leave the whole scratch folder rather than delete through it.
        links_gone = True
        for j in (root / "runtime" / "win-x64", root / "models"):
            if os.path.lexists(j):
                try:
                    os.rmdir(j)
                except OSError as e:
                    links_gone = False
                    print(f"  NOTE  could not remove the link {j} ({e}); left {root} in place - remove the links by hand")
        if links_gone:
            shutil.rmtree(root, ignore_errors=True)
    passed = sum(results)
    print(f"{passed} passed, {len(results) - passed} failed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
