"""T06: build.bat makes one portable dist\\WizTry.exe whose report is right."""
import json
import os
import subprocess
import sys
import tempfile

from _t import EXPECTED, FIXTURE, WS, check, finish

exe = WS / "dist" / "WizTry.exe"
if exe.exists():
    exe.unlink()
r = subprocess.run(["cmd", "/c", str(WS / "build.bat")], capture_output=True, text=True, timeout=900, cwd=str(WS),
                   env=dict(os.environ, WIZTRY_PY=sys.executable))      # the Python that has PyInstaller
check("build.bat succeeds", r.returncode == 0, ((r.stdout or "") + (r.stderr or ""))[-600:])
check("dist\\WizTry.exe exists", exe.exists())
check("it is one self-contained file (over 5 MB)", exe.exists() and exe.stat().st_size > 5_000_000,
      exe.exists() and exe.stat().st_size)
out = os.path.join(tempfile.mkdtemp(), "exe_report.json")
if exe.exists():
    clean = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHON", "VIRTUAL_ENV"))}
    clean["PATH"] = r"C:\Windows\system32;C:\Windows"             # no Python on the PATH
    rr = subprocess.run([str(exe), "--scan", FIXTURE, "--json", out], capture_output=True, timeout=180, env=clean)
    check("the exe runs without Python and exits 0", rr.returncode == 0, rr.returncode)
    rep = json.loads(open(out, encoding="utf-8").read()) if os.path.exists(out) else {}
    for key in ("total_size", "files", "folders", "by_ext", "top_level"):
        check(f"exe report: {key}", rep.get(key) == EXPECTED[key], rep.get(key))
check("build output is ignored by git", all(x in (WS / ".gitignore").read_text() for x in ("dist/", "build/")))
finish()
