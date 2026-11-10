"""Philibert Code Setup, from a console (the engine is installer/code_engine.py; a window comes later).

    python installer\\code_setup.py --list                       Philibert installs this computer can see
    python installer\\code_setup.py E:\\Philibert [--local <repo>] [--accept-slow] [--no-model]

--local installs from a repo folder (development); without it, from GitHub (needs access, see Setup).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import code_engine as ce  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("philibert", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--local")
    info = json.loads((Path(__file__).resolve().parent.parent / "philibert.json").read_text(encoding="utf-8"))
    ap.add_argument("--repo", default=info["repo"])          # the same repository Philibert installs from
    ap.add_argument("--accept-slow", action="store_true")
    ap.add_argument("--no-model", action="store_true")
    a = ap.parse_args(argv)
    if a.list or not a.philibert:
        found = ce.find_philibert()
        print("\n".join(str(p) for p in found) if found else "No Philibert install found on this computer's drives.")
        return 0
    plan = {"philibert": a.philibert, "accept_slow": a.accept_slow, "model": not a.no_model,
            "source": {"local": a.local} if a.local else {"repo": a.repo, "branch": "main"}}
    last = {"step": -1, "detail": ""}

    def report(s):
        if s["steps"] and s["step"] != last["step"]:
            last["step"] = s["step"]
            print(f"\n[{s['step'] + 1}/{len(s['steps'])}] {s['steps'][s['step']]['title']}", flush=True)
        d = s.get("detail") or ""
        if d and d != last["detail"]:
            last["detail"] = d
            print("   " + d[:110], flush=True)

    st = ce.CodeInstaller(plan, report).run()
    for w in st.get("warnings") or []:
        print("NOTE: " + w)
    if st.get("error"):
        print("\nSTOPPED: " + st["error"])
        return 1
    print("\nPhilibert Code is ready: " + str(Path(a.philibert) / "code" / "Start-Philibert-Code.bat"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
