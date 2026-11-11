"""Overnight queue: plan and build the same WizTry request with each planner, unattended, then score each build.

    python dev/studio_overnight.py [--only 4,5] [--dry]

Results: C:\\PCodeTest\\overnight\\REPORT.md (rewritten after every step) and overnight.log.
To stop: create C:\\PCodeTest\\overnight\\STOP (checked between stages), or close this window.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "dev"))
import studio_score  # noqa: E402

ROOT = Path(r"C:\PCodeTest")
HOME = ROOT / "overnight"
SOURCE = ROOT / "wiztry2"                  # the same request, answers and spec for every planner
FOREMAN = r"G:\!Ai\ND3\nd_foreman.py"      # read-only use of the developer's copy
TRIAL = REPO / "dev" / "studio_trial.py"
BASE_PY = r"C:\Python311_base\python.exe"
TRAILER = "\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
CLARIFY = """
## Clarifications
- In `top_level`, each entry's `size`, `files` and `folders` include everything beneath that entry, at every level; a folder does not count itself.
- A plain file directly inside `root` is an entry too, with its own `size`, `files` = 1, `folders` = 0.
"""
REFEREE = "q36c-nd64k"
RUNS = [
    {"n": 4, "ws": ROOT / "wiztry4", "name": "Qwen3.6 35B as planner", "model": "q36c-nd64k", "plan": [], "rest": []},
    {"n": 5, "ws": ROOT / "wiztry5", "name": "gpt-oss:120b as planner", "model": "gpt-oss:120b",
     "plan": ["--think", "high", "--ctx", "65536", "--max", "60000"], "rest": ["--think", "medium", "--ctx", "65536", "--max", "40000"]},
]
DRY = "--dry" in sys.argv
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
results = {}
started = time.strftime("%Y-%m-%d %H:%M")


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(HOME / "overnight.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Stop(Exception):
    pass


def check_stop():
    if (HOME / "STOP").exists():
        raise Stop()


def sh(cmd, cwd, timeout=7200, name=""):
    """Run a command; everything it prints goes to the log. -> (exit code, output)"""
    log(f"$ {name or ' '.join(str(c) for c in cmd)[:220]}")
    if DRY:
        return 0, ""
    try:
        r = subprocess.run([str(c) for c in cmd], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=ENV)
        out = (r.stdout or "") + (r.stderr or "")
        code = r.returncode
    except subprocess.TimeoutExpired as e:
        out, code = f"TIMED OUT after {timeout} s: {str(e.stdout or '')[-1500:]}", 124
    with open(HOME / "overnight.log", "a", encoding="utf-8") as f:
        f.write(out[-12000:] + "\n")
    return code, out


def commit(ws, msg):
    if DRY:
        return
    subprocess.run(["git", "add", "-A"], cwd=str(ws), capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", msg + TRAILER], cwd=str(ws), capture_output=True)


def unload():
    """Free the GPU and RAM: the planner and the builder are different models."""
    if DRY:
        return
    try:
        ps = json.loads(urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=15).read())
        for m in ps.get("models") or []:
            body = json.dumps({"model": m["name"], "keep_alive": 0}).encode()
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                                          headers={"Content-Type": "application/json"}), timeout=120).read()
            log(f"unloaded {m['name']}")
        time.sleep(5)
    except Exception as e:
        log(f"unload: {e}")


def stage(run, st, *args, rest=None, retries=1, timeout=5400, model=None):
    check_stop()
    extra = (run["rest"] if rest is None else rest)
    cmd = [sys.executable, TRIAL, st, run["ws"], *args, "--model", model or run["model"], *([] if model else extra)]
    for attempt in range(retries + 1):
        code, out = sh(cmd, REPO, timeout=timeout, name=f"{st} {' '.join(args)} ({model or run['model']})")
        if code == 0:
            return out
        log(f"{st} failed (exit {code}): {out[-500:]}")
        if attempt < retries:
            time.sleep(30)
    raise RuntimeError(f"stage {st} failed")


def setup(run):
    ws = run["ws"]
    if DRY:
        return
    if ws.exists():
        raise RuntimeError(f"{ws} already exists")
    (ws / ".studio").mkdir(parents=True)
    shutil.copy(SOURCE / ".gitignore", ws / ".gitignore")
    for n in ("request.txt", "answers.md", "questions.md"):
        shutil.copy(SOURCE / ".studio" / n, ws / ".studio" / n)
    (ws / "SPEC.md").write_text((SOURCE / "SPEC.md").read_text(encoding="utf-8").rstrip() + "\n" + CLARIFY, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(ws), check=True)
    commit(ws, f"WizTry {run['n']}: Studio v2, {run['name']}")
    subprocess.run([BASE_PY, "-m", "venv", ".venv"], cwd=str(ws), check=True)
    subprocess.run([str(ws / ".venv" / "Scripts" / "python.exe"), "-m", "pip", "install", "-q", "pyinstaller==6.22.3"], cwd=str(ws), capture_output=True)


def foreman(run, *args, timeout=4 * 3600 + 900):
    check_stop()
    unload()
    commit(run["ws"], f"before the foreman: {' '.join(args) or 'run'}")
    return sh([sys.executable, FOREMAN, "run", run["ws"] / "plan.json", *args], r"G:\!Ai\ND3", timeout=timeout, name=f"foreman run {' '.join(args)}")


def state(run):
    if DRY:
        return {}
    return json.loads((run["ws"] / ".foreman" / "state.json").read_text(encoding="utf-8"))


def stuck(run):
    return [k for k, v in state(run).get("tasks", {}).items() if v.get("status") == "stuck"]


def counts(run):
    c = {}
    for v in state(run).get("tasks", {}).values():
        c[v.get("status")] = c.get(v.get("status"), 0) + 1
    return c


def build(run):
    ws = run["ws"]
    results[run["n"]] = {"phase": "setting up"}
    report()
    setup(run)
    t0 = time.time()

    results[run["n"]]["phase"] = "planning"
    report()
    stage(run, "plan", rest=run["plan"], timeout=7200)
    commit(ws, "plan v1")
    for i in (1, 2):
        stage(run, "review", rest=run["plan"], timeout=7200)
        commit(ws, f"plan review {i}")
    if not DRY:
        plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
        ids = [t["id"] for t in plan["tasks"]]
    else:
        ids = ["T01"]
    stage(run, "tests")
    commit(ws, "tests")
    stage(run, "accept")
    commit(ws, "acceptance tests")
    stage(run, "lint-tests")
    stage(run, "review-tests")
    stage(run, "lint-tests")
    commit(ws, "tests reviewed")
    out = stage(run, "check", rest=[], retries=0, model=REFEREE)
    results[run["n"]]["check"] = out[-1500:]
    for p in (ws.iterdir() if not DRY else []):   # tests must not leave anything behind in the project
        if p.name not in (".git", ".studio", ".venv", ".foreman", ".gitignore", "SPEC.md", "plan.json", "tests"):
            log(f"removing what a test left behind: {p.name}")
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    results[run["n"]]["planning_hours"] = round((time.time() - t0) / 3600, 1)

    results[run["n"]]["phase"] = "building the engine"
    report()
    engine = (json.loads((ws / "plan.json").read_text(encoding="utf-8")).get("engine_task") or ids[0]) if not DRY else "T01"
    foreman(run, "--only", engine, "--max-hours", "2")
    if engine in stuck(run):
        referee(run, engine)
        foreman(run, "--only", engine, "--max-hours", "2")
    others = [i for i in ids if i != engine]
    if others:                                 # the tests were written before any code: check them against it
        stage(run, "review-tests", ",".join(others))
        stage(run, "lint-tests")
        commit(ws, "tests rechecked against the engine")

    results[run["n"]]["phase"] = "building"
    report()
    foreman(run, "--max-hours", "4")
    for round_ in (1, 2):
        s = stuck(run)
        if not s:
            break
        log(f"referee round {round_}: {s}")
        for tid in s:
            referee(run, tid)
        foreman(run, "--max-hours", "3")
    results[run["n"]]["phase"] = "finished"
    results[run["n"]]["hours"] = round((time.time() - t0) / 3600, 1)
    results[run["n"]]["tasks"] = counts(run)


def referee(run, tid):
    try:
        unload()
        stage(run, "dispute", tid, rest=[], model=REFEREE, timeout=3600)
    except RuntimeError as e:
        log(f"referee on {tid}: {e}")
    commit(run["ws"], f"referee on {tid}")
    if not DRY:
        sh([sys.executable, FOREMAN, "retry", run["ws"] / "plan.json", tid], r"G:\!Ai\ND3", timeout=120, name=f"foreman retry {tid}")


def scored(run):
    if DRY:
        return
    r = studio_score.score(run["ws"])
    results[run["n"]]["score"] = r
    (HOME / f"score_{run['n']}.json").write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")


def report():
    L = [f"# Overnight Studio runs (started {started}, updated {time.strftime('%Y-%m-%d %H:%M')})", ""]
    for run in RUNS:
        r = results.get(run["n"])
        L += [f"## Run {run['n']}: {run['name']}  ({run['ws']})", ""]
        if not r:
            L += ["Not started.", ""]
            continue
        L.append(f"- phase: {r.get('phase')}")
        if r.get("error"):
            L.append(f"- ERROR: {r['error']}")
        for k in ("planning_hours", "hours", "tasks"):
            if k in r:
                L.append(f"- {k}: {r[k]}")
        s = r.get("score")
        if s:
            kit = s.get("kit") or {}
            L.append(f"- kit (numbers on the fixture): {kit.get('score')} of {kit.get('of')}  {kit.get('detail') or kit.get('error')}")
            w = s.get("window") or {}
            L.append(f"- window: opened={w.get('opened')} started_with={w.get('started_with')} error={str(w.get('error'))[:300]}")
            L.append(f"  - trees: {w.get('trees')}")
            L.append(f"  - canvases: {w.get('canvases')}")
            L.append(f"  - labels: {w.get('labels')}")
            for k, v in (s.get("tests") or {}).items():
                L.append(f"  - {k}: {v}")
        L.append("")
    (HOME / "REPORT.md").write_text("\n".join(L), encoding="utf-8")


def main():
    HOME.mkdir(parents=True, exist_ok=True)
    only = None
    if "--only" in sys.argv:
        only = set(int(x) for x in sys.argv[sys.argv.index("--only") + 1].split(","))
    import ctypes
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # no sleep while this process runs (ends with it)
    log(f"overnight queue started (pid {os.getpid()})" + (" DRY RUN" if DRY else ""))
    for run in RUNS:
        if only and run["n"] not in only:
            continue
        try:
            build(run)
        except Stop:
            results.setdefault(run["n"], {})["phase"] = "stopped (STOP file)"
            log("STOP file found")
            report()
            break
        except Exception as e:
            results.setdefault(run["n"], {}).update(phase="failed", error=f"{e}")
            log(traceback.format_exc())
        finally:
            try:
                scored(run)
            except Exception as e:
                log(f"scoring failed: {e}")
            report()
            unload()
    log("overnight queue finished")
    report()


if __name__ == "__main__":
    main()
