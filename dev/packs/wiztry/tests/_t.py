"""Shared bits for the WizTry tests: PASS/FAIL lines, the fixture and its known answers."""
import json
import os
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))
FIXTURE = r"{FIXTURE}"
FIXTURE_BIG = r"{FIXTURE_BIG}"
EXPECTED = json.loads((Path(__file__).parent / "expected.json").read_text(encoding="utf-8"))
_results = []


def check(label, ok, got=""):
    _results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f" - got {got!r}"[:400]), flush=True)


def finish():
    passed = sum(_results)
    print(f"{passed} passed, {len(_results) - passed} failed", flush=True)
    sys.exit(0 if passed == len(_results) else 1)


def listing(root):
    """(path, size, mtime) of every file under root, to prove a scan changed nothing."""
    out = []
    for d, _dirs, files in os.walk(root):
        for f in files:
            st = os.stat(os.path.join(d, f))
            out.append((os.path.join(d, f), st.st_size, st.st_mtime_ns))
    return sorted(out)
