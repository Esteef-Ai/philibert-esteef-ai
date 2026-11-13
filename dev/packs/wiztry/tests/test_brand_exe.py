"""T19: the exe says who made it: Windows' file properties show Esteef.Ai."""
import faulthandler
import json
import os
import subprocess
import sys
import tempfile

faulthandler.dump_traceback_later(900, exit=True)
from _t import EXPECTED, FIXTURE, WS, check, finish  # noqa: E402

info = WS / "version_info.txt"
text = info.read_text(encoding="utf-8") if info.exists() else ""
check("version_info.txt is in the project folder", info.exists())
check("it is a PyInstaller version file (VSVersionInfo)", "VSVersionInfo" in text and "StringFileInfo" in text, text[:80])
bat = (WS / "build.bat").read_text(encoding="utf-8", errors="replace") if (WS / "build.bat").exists() else ""
check("build.bat gives it to PyInstaller with --version-file", "--version-file" in bat and "version_info.txt" in bat)
if not info.exists() or "--version-file" not in bat:
    finish()

exe = WS / "dist" / "WizTry.exe"
if exe.exists():
    exe.unlink()
r = subprocess.run(["cmd", "/c", str(WS / "build.bat")], capture_output=True, text=True, timeout=800, cwd=str(WS),
                   env=dict(os.environ, WIZTRY_PY=sys.executable))
check("build.bat still succeeds", r.returncode == 0 and exe.exists(), ((r.stdout or "") + (r.stderr or ""))[-500:])
if not exe.exists():
    finish()

ps = ("$v = (Get-Item -LiteralPath '%s').VersionInfo; "
      "@{company=$v.CompanyName; product=$v.ProductName; description=$v.FileDescription; copyright=$v.LegalCopyright; "
      "version=$v.ProductVersion; original=$v.OriginalFilename} | ConvertTo-Json -Compress" % str(exe))
p = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60)
try:
    v = json.loads(p.stdout)
except ValueError:
    v = {}
check("Windows can read the exe's version information", bool(v), (p.stdout or p.stderr)[-200:])
check("Company is Esteef.Ai", v.get("company") == "Esteef.Ai", v.get("company"))
check("Product name is WizTry", v.get("product") == "WizTry", v.get("product"))
check("File description is 'WizTry - disk space analyzer by Esteef.Ai'", v.get("description") == "WizTry - disk space analyzer by Esteef.Ai",
      v.get("description"))
check("Copyright names Esteef.Ai", "Esteef.Ai" in str(v.get("copyright")), v.get("copyright"))
check("Product version is 1.0.0", str(v.get("version")).startswith("1.0.0"), v.get("version"))
check("Original filename is WizTry.exe", v.get("original") == "WizTry.exe", v.get("original"))

out = os.path.join(tempfile.mkdtemp(), "exe_report.json")
clean = {k: val for k, val in os.environ.items() if not k.upper().startswith(("PYTHON", "VIRTUAL_ENV"))}
clean["PATH"] = r"C:\Windows\system32;C:\Windows"
rr = subprocess.run([str(exe), "--scan", FIXTURE, "--json", out], capture_output=True, timeout=180, env=clean)
rep = json.loads(open(out, encoding="utf-8").read()) if os.path.exists(out) else {}
check("the branded exe still runs without Python and reports the right total", rr.returncode == 0
      and rep.get("total_size") == EXPECTED["total_size"], (rr.returncode, rep.get("total_size")))
finish()
