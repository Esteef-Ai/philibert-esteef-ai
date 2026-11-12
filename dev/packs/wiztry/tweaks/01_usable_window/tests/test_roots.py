"""T07: a folder path means what a person typing it means ("C:" is the drive, not the current folder on it)."""
import json
import os
import subprocess
import sys
import tempfile

from _t import FIXTURE, WS, check, finish

try:
    from wiztry.scanner import clean_root, scan
except Exception as e:                                  # noqa: BLE001
    check("wiztry.scanner has clean_root", False, e)
    finish()

D = os.environ.get("SystemDrive", "C:").upper()         # "C:"
WIN = os.path.join(D + "\\", "Windows")

check("a bare drive letter is the drive's root", clean_root(D) == D + "\\", clean_root(D))
check("a lower-case drive letter too", clean_root(D.lower()).upper() == D + "\\", clean_root(D.lower()))
check("a drive root stays a drive root", clean_root(D + "\\") == D + "\\", clean_root(D + "\\"))
check("spaces around the path are dropped", clean_root("   " + WIN + "  ") == WIN, clean_root("   " + WIN + "  "))
check("double quotes around the path are dropped", clean_root('"' + WIN + '"') == WIN, clean_root('"' + WIN + '"'))
check("quotes and spaces together", clean_root(' "' + WIN + '" ') == WIN, clean_root(' "' + WIN + '" '))
check("forward slashes become backslashes", clean_root(FIXTURE.replace("\\", "/")) == FIXTURE, clean_root(FIXTURE.replace("\\", "/")))
check("a trailing backslash is dropped", clean_root(FIXTURE + "\\") == FIXTURE, clean_root(FIXTURE + "\\"))
check("an empty path stays empty", clean_root("") == "" and clean_root("   ") == "" and clean_root('""') == "",
      (clean_root(""), clean_root("   "), clean_root('""')))
check("clean_root does not need the folder to exist", clean_root(FIXTURE + "\\no_such_folder\\") == FIXTURE + "\\no_such_folder",
      clean_root(FIXTURE + "\\no_such_folder\\"))

top, _skipped = scan('"' + FIXTURE.replace("\\", "/") + '/"')
check("scan() cleans its root the same way", top.path == FIXTURE and top.files == 91, (top.path, top.files))

out = os.path.join(tempfile.mkdtemp(), "report.json")
r = subprocess.run([sys.executable, str(WS / "WizTry.py"), "--scan", FIXTURE.replace("\\", "/") + "/", "--json", out],
                   capture_output=True, text=True, timeout=120, cwd=tempfile.gettempdir())
rep = json.loads(open(out, encoding="utf-8").read()) if os.path.exists(out) else {}
check("the command line cleans the folder too", r.returncode == 0 and rep.get("root") == FIXTURE and rep.get("files") == 91,
      (r.returncode, rep.get("root"), rep.get("files"), (r.stderr or "")[-200:]))
finish()
