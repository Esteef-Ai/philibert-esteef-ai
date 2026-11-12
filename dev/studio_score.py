"""Score a Studio build from the outside: the numbers against G:\\WIZTRY's kit, and what the real window shows.

    python dev/studio_score.py <ws> [--json out.json]

Knows nothing of the build's internal names: it runs the entry script, and drives the window by finding a
button. Runs the window off-screen in the build's own Python.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURE = r"G:\WIZTRY\fixture"
EXPECTED = Path(r"G:\WIZTRY\kit\expected.json")
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

PROBE = r'''
import json, re, runpy, sys, time, tkinter as tk, tkinter.filedialog as fd
from tkinter import ttk
entry, target, out = sys.argv[1:4]
result = {"opened": False, "error": None}
def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)
def rows(tv, parent=""):
    n = 0
    for i in tv.get_children(parent):
        n += 1 + rows(tv, i)
    return n
def pump(root, s):
    end = time.time() + s
    while time.time() < end:
        root.update()
        time.sleep(0.01)
def drive(root, n=0):
    result["opened"] = True
    root.geometry("1100x760+-4000+-4000")
    pump(root, 0.6)
    fd.askdirectory = lambda *a, **k: target
    def label_text():
        out = []
        for w in walk(root):
            try:
                if w.winfo_class() in ("Label", "TLabel"):
                    out.append(str(w.cget("text")))
            except tk.TclError:
                pass
        return out
    buttons = [w for w in walk(root) if w.winfo_class() in ("Button", "TButton")]
    names = [str(b.cget("text")) for b in buttons]
    result["buttons"] = names
    start = next((b for b in buttons if re.search(r"scan|select|folder|browse|open", str(b.cget("text")), re.I)), None)
    result["started_with"] = str(start.cget("text")) if start is not None else None
    if start is not None:
        start.invoke()
    end = time.time() + 60
    while time.time() < end and not any(re.search(r"\bfiles?\b.* in ", t) for t in label_text()):
        root.update()
        time.sleep(0.02)
    pump(root, 1.0)
    result["labels"] = [t for t in label_text() if t][:12]
    result["trees"] = [{"mapped": bool(w.winfo_ismapped()), "w": w.winfo_width(), "h": w.winfo_height(), "rows": rows(w),
                        "first": [str(w.item(i, "text")) for i in w.get_children("")[:3]]}
                       for w in walk(root) if w.winfo_class() == "Treeview"]
    result["canvases"] = [{"mapped": bool(w.winfo_ismapped()), "w": w.winfo_width(), "h": w.winfo_height(), "items": len(w.find_all()),
                           "colours": len({w.itemcget(i, "fill") for i in w.find_all() if w.type(i) == "rectangle"})}
                          for w in walk(root) if w.winfo_class() == "Canvas"]
    json.dump(result, open(out, "w", encoding="utf-8"), indent=1)
    root.destroy()
_driving = []
def once(root):                      # a nested mainloop() (an app calling it from a button) must not re-drive
    if _driving:
        return
    _driving.append(1)
    drive(root)
tk.Misc.mainloop = lambda self, n=0: once(self.winfo_toplevel())
tk.mainloop = lambda n=0: once(tk._default_root)
sys.argv = [entry]
try:
    runpy.run_path(entry, run_name="__main__")
except SystemExit:
    pass
except BaseException as e:
    import traceback
    result["error"] = traceback.format_exc()[-1200:]
    json.dump(result, open(out, "w", encoding="utf-8"), indent=1)
'''


def find_entry(ws):
    for name in ("WizTry.py", "main.py", "app.py", "wiztry.py"):
        if (ws / name).is_file():
            return ws / name
    for p in ws.glob("*/__main__.py"):
        return p
    for name in ("main.py", "app.py", "cli.py"):          # a package's entry script (run 10: wiztry/main.py)
        for p in ws.glob(f"*/{name}"):
            if p.parent.name not in (".venv", "tests", "build", "dist"):
                return p
    return None


def score(ws):
    ws = Path(ws)
    py = str(ws / ".venv" / "Scripts" / "python.exe")
    out = {"ws": str(ws), "kit": None, "window": None, "tests": {}}
    entry = find_entry(ws)
    out["entry"] = entry.name if entry else None
    if entry:
        exp = json.loads(EXPECTED.read_text(encoding="utf-8"))
        rep_file = Path(tempfile.mkdtemp()) / "r.json"
        try:
            r = subprocess.run([py, str(entry), "--scan", FIXTURE, "--json", str(rep_file)], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", cwd=str(ws), timeout=300, env=ENV)
            rep = json.loads(rep_file.read_text(encoding="utf-8"))
            detail = {k: rep.get(k) == exp[k] for k in ("total_size", "files", "folders", "by_ext", "top_level")}
            out["kit"] = {"score": sum(detail.values()), "of": 5, "detail": detail, "got_top_level": rep.get("top_level"), "exit": r.returncode}
        except Exception as e:
            out["kit"] = {"score": 0, "of": 5, "error": str(e)[:400]}
        probe = Path(tempfile.mkdtemp()) / "probe.py"
        probe.write_text(PROBE, encoding="utf-8")
        res = probe.with_suffix(".json")
        try:
            r = subprocess.run([py, str(probe), str(entry), FIXTURE, str(res)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                               cwd=str(ws), timeout=180, env=ENV)
            out["window"] = json.loads(res.read_text(encoding="utf-8")) if res.exists() else {"error": (r.stdout + r.stderr)[-800:]}
        except Exception as e:
            out["window"] = {"error": str(e)[:400]}
    for t in sorted((ws / "tests").glob("test_*.py")):
        try:
            r = subprocess.run([py, str(t)], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ws), timeout=180, env=ENV)
            lines = (r.stdout + r.stderr).strip().splitlines()
            out["tests"][t.name] = lines[-1][:120] if lines else "(no output)"
        except Exception as e:
            out["tests"][t.name] = f"error: {e}"[:120]
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    res = score(args[0])
    text = json.dumps(res, indent=1, ensure_ascii=False)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(text)
    if "--json" in args:
        Path(args[args.index("--json") + 1]).write_text(text, encoding="utf-8")
