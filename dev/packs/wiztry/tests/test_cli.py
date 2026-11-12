"""T04: WizTry.py --scan <folder> --json <file> writes the report without opening a window."""
import json
import os
import subprocess
import sys
import tempfile

from _t import EXPECTED, FIXTURE, WS, check, finish

out = os.path.join(tempfile.mkdtemp(), "report.json")
r = subprocess.run([sys.executable, str(WS / "WizTry.py"), "--scan", FIXTURE, "--json", out],
                   capture_output=True, text=True, timeout=120, cwd=str(WS))
check("exits with 0", r.returncode == 0, (r.returncode, (r.stderr or "")[-300:]))
rep = {}
try:
    rep = json.loads(open(out, encoding="utf-8").read())
except Exception as e:                                  # noqa: BLE001
    check("writes a JSON report", False, e)
for key in ("total_size", "files", "folders", "by_ext", "top_level"):
    check(f"report: {key}", rep.get(key) == EXPECTED[key], rep.get(key))
check("report: root, skipped and seconds", rep.get("root") == FIXTURE and rep.get("skipped") == 0
      and isinstance(rep.get("seconds"), (int, float)), (rep.get("root"), rep.get("skipped"), rep.get("seconds")))
check("nothing printed (it may run without a console)", not r.stdout.strip(), r.stdout[:200])

try:
    from wiztry.cli import main
    out2 = os.path.join(tempfile.mkdtemp(), "r2.json")
    code = main(["--scan", FIXTURE, "--json", out2])
    check("cli.main returns 0 and writes the file", code == 0 and os.path.exists(out2), code)
except Exception as e:                                  # noqa: BLE001
    check("cli.main works when imported", False, e)
r = subprocess.run([sys.executable, str(WS / "WizTry.py"), "--scan", FIXTURE], capture_output=True, text=True,
                   timeout=60, cwd=str(WS))
check("--json is required", r.returncode != 0)
finish()
