"""Philibert Code Setup's window bridge (installer/code_app.py), from source. Read-only: it only looks.
Run: python installer/tests/test_code_app.py"""
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import code_app  # noqa: E402

fails = []


def check(label, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + label + ("" if ok else f"   ({str(detail)[:300]})"))
    if not ok:
        fails.append(label)


api = code_app.CodeApi()
pins = code_app._pins()
check("pins load from the repo (and from the bundle in a build)", pins["model"]["tag"] == "q36c-nd128k", pins.get("model"))

found = api.installs()
check("installs() lists set-up Philibert installs with their version", all({"path", "version", "code_installed"} <= set(x) for x in found), found)
for x in found:
    print(f"      found {x['path']}  version={x['version'][:40]!r}  code={x['code_installed']}")

c = api.check(tempfile.gettempdir())
check("check() on a folder that is not Philibert: a plain problem, nothing else", c.get("problem") and "ollama" not in c, c)

if found:
    c = api.check(found[0]["path"], True)
    check("check() on a real install has Ollama, hardware and space", {"ollama", "hardware", "space"} <= set(c) and c["problem"] is None, c)
    check("its Ollama verdict follows the pin", c["ollama"]["ok"] == (code_app.ce.version_tuple(c["ollama"]["have"])
                                                                      >= code_app.ce.version_tuple(pins["ollama_min"])), c["ollama"])
    check("space counts the 22 GB model only when it is wanted",
          api.check(found[0]["path"], False)["space"]["need_gb"] < c["space"]["need_gb"] - 20, c["space"])
    check("the hardware line names the graphics card", bool(c["hardware"]["gpu"]) and "GB" in c["hardware"]["message"], c["hardware"])
    print(f"      {found[0]['path']}: Ollama {c['ollama']}, space {c['space']}")

src = code_app.philibert_setup.source()
check("from source it installs from this repo folder", Path(src.get("local", "")).resolve() == HERE.parent.parent.resolve(), src)
check("the GitHub sign-in comes from Philibert Setup", callable(getattr(api, "github_status", None)) and callable(api.progress))
ui = (HERE.parent / "code_ui" / "code_setup.js").read_text(encoding="utf-8")
calls = set(re.findall(r'api\("([a-z_]+)"', ui))
missing = [c for c in calls if not callable(getattr(api, c, None))]
check("every call the page makes exists on the bridge", not missing, missing)
check("model text never lands in innerHTML unescaped (esc() on computer text)", "esc(c.problem)" in ui and "esc(s.error)" in ui)

print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED'}")
sys.exit(1 if fails else 0)
