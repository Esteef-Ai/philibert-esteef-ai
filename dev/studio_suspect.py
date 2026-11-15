"""Suspect tests: when a task keeps failing, is it the builder or the test?

One build lost 2.4 hours because a test browser was not empty: six attempts failed the same check while the code
changed every time. Nothing in the loop asked the obvious question. This module asks it, two ways:

  certain   The failing test is one that must already pass (a guard, or a test an earlier task turned green).
            Run it on the code as it was BEFORE the builder touched it. If it fails there too, the builder cannot
            be at fault: the test or the machine is.
  likely    Two or more attempts failed with exactly the same failing checks, although the builder said different
            things each time. Different code, same failure: read the test before spending more attempts.

studio_pack.py build watches for this while the foreman runs. A certain finding stops the build after the current
task (the foreman's STOP file) and the stuck task gets no fresh round; both kinds go into the handoff.

    python dev/studio_suspect.py check <workspace>        look now; prints and writes .studio/suspects.json
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
_done = {}                                   # (task, test, sha) -> finding or None: the untouched run is made once


def _state(ws):
    f = Path(ws) / ".foreman" / "state.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):            # the foreman is writing it this second
        return {}


def failing_test(detail):
    """The test file an attempt's failure names: `tests/x.py` does not pass / Your change broke `tests/x.py`."""
    m = re.search(r"`([^`]+\.py)`", detail or "")
    return m.group(1) if m else None


def signature(a):
    """What failed, with the parts that change from run to run (numbers, times, ports) taken out."""
    d = a.get("detail") or ""
    fails = sorted({re.sub(r"\d+", "#", ln.strip())[:160] for ln in d.splitlines() if ln.strip().startswith("FAIL")})
    if not fails:
        fails = [re.sub(r"\d+", "#", d.strip().splitlines()[0])[:160]] if d.strip() else []
    return a.get("gate"), failing_test(d), tuple(fails)


def untouched_copy(ws, sha, links=()):
    """The project as it was at `sha`, in a temp folder. Big folders nobody edits are linked, as in a workspace."""
    ws = Path(ws)
    tmp = Path(tempfile.mkdtemp(prefix="suspect_"))
    r = subprocess.run(["git", "archive", "--format=tar", sha], cwd=str(ws), capture_output=True)
    if r.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError("git archive failed: " + r.stderr.decode("utf-8", "replace")[:200])
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as t:
        t.extractall(tmp)
    for n in links:
        if (ws / n).is_dir() and not (tmp / n).exists():
            subprocess.run(["cmd", "/c", "mklink", "/J", str(tmp / n), str((ws / n).resolve())], capture_output=True)
    return tmp


def remove_copy(tmp, links=()):
    for n in links:                          # take the links away first, so nothing can follow them into the real folder
        p = Path(tmp) / n
        if p.exists():
            try:
                os.rmdir(p)
            except OSError:
                pass
    shutil.rmtree(tmp, ignore_errors=True)


def run_test(py, folder, name, timeout=600):
    try:
        r = subprocess.run([py, name], cwd=str(folder), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=ENV, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = ((r.stdout or "") + (r.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout} s"
    m = ([None] + list(re.finditer(r"(?m)^\s*(\d+) passed, (\d+) failed\s*$", out)))[-1]
    ok = bool(m) and r.returncode == 0 and int(m.group(2)) == 0 and int(m.group(1)) > 0
    fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("FAIL")]
    return ok, "\n".join(fails[:5]) or out[-300:]


def check(ws, run_untouched=True):
    """-> the findings for this workspace now (also written to .studio/suspects.json)."""
    ws = Path(ws)
    st = _state(ws)
    try:
        pack = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pack = {}
    guards = set(pack.get("guard_tests") or [])
    green = set((st.get("green") or {}).keys())
    links = pack.get("base_links") or []
    py = str(ws / ".venv" / "Scripts" / "python.exe")
    found = []
    for tid, t in (st.get("tasks") or {}).items():
        if t.get("status") == "passed":
            continue
        fails = [a for a in t.get("attempts") or [] if a.get("verdict") != "pass" and a.get("gate") in ("tests", "broke")]
        if not fails:
            continue
        last = fails[-1]
        test = failing_test(last.get("detail"))
        sha = t.get("start_sha")
        if run_untouched and test and sha and (test in guards or test in green or last.get("gate") == "broke"):
            k = (tid, test, sha)
            if k not in _done:
                _done[k] = None
                tmp = None
                try:
                    tmp = untouched_copy(ws, sha, links)
                    ok, tail = run_test(py, tmp, test)
                    if not ok:                               # once more: a single bad run could be the machine being busy
                        ok, tail = run_test(py, tmp, test)
                    if not ok:
                        _done[k] = {"task": tid, "test": test, "kind": "fails-untouched", "certain": True, "when": time.strftime("%Y-%m-%d %H:%M"),
                                    "why": f"`{test}` must already pass before {tid} starts, and it fails on the code as it was "
                                           f"before the builder touched it (tried twice). The builder cannot fix this: the test "
                                           f"or this machine is at fault.", "tail": tail[:600]}
                except Exception as e:
                    _done[k] = None
                    print(f"suspect check for {tid} could not run: {e}")
                finally:
                    if tmp:
                        remove_copy(tmp, links)
            if _done.get(k):
                found.append(_done[k])
                continue
        if len(fails) >= 2 and signature(fails[-1]) == signature(fails[-2]) and signature(fails[-1])[2]:
            says = {hashlib.md5(" ".join(str(a.get("reply") or "").split())[:400].encode()).hexdigest() for a in fails[-2:]}
            nothing = all("Nothing was changed at all" in str(a.get("detail") or "") for a in fails[-2:])
            if len(says) > 1 and not nothing:
                same = sum(1 for a in fails if signature(a) == signature(fails[-1]))
                found.append({"task": tid, "test": test, "kind": "same-failure", "certain": False, "when": time.strftime("%Y-%m-%d %H:%M"),
                              "why": f"{same} attempts failed exactly the same checks of `{test}` although the builder reported "
                                     f"different work each time. Read the failing lines of the test next to the brief before "
                                     f"spending more attempts.", "tail": "\n".join(signature(fails[-1])[2])[:600]})
    sd = ws / ".studio"
    if sd.is_dir():
        (sd / "suspects.json").write_text(json.dumps(found, indent=1, ensure_ascii=False), encoding="utf-8")
    return found


def watch(ws, stop, log=print, every=60):
    """Runs beside the foreman (a thread). A certain finding asks the foreman to stop after the current task."""
    told = set()
    while not stop.wait(every):
        try:
            for f in check(ws):
                k = (f["task"], f["kind"])
                if k in told:
                    continue
                told.add(k)
                log(f"SUSPECT TEST ({'certain' if f['certain'] else 'likely'}) in {f['task']}: {f['why']}")
                if f["certain"]:
                    (Path(ws) / ".foreman" / "STOP").write_text("suspect test: " + f["why"], encoding="utf-8")
                    log("asked the foreman to stop after the current task (.foreman/STOP)")
        except Exception as e:
            log(f"suspect watch error: {e}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "check":
        res = check(sys.argv[2])
        for f in res:
            print(f"{'CERTAIN' if f['certain'] else 'likely '} {f['task']} {f['test']}: {f['why']}\n{f['tail']}\n")
        print(f"{len(res)} suspect test(s)")
    else:
        sys.exit(__doc__)
