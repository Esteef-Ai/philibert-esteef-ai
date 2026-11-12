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
    {"n": 9, "ws": ROOT / "wiztry9", "name": "gpt-oss:120b as planner (resumed: planned 2026-11-11)", "model": "gpt-oss:120b",
     "plan": ["--think", "high", "--ctx", "65536", "--max", "60000"], "rest": ["--think", "medium", "--ctx", "65536", "--max", "40000"],
     "resume": True},
    {"n": 10, "ws": ROOT / "wiztry10", "name": "Qwen3.6 35B as planner", "model": "q36c-nd64k", "plan": [], "rest": []},
]
DRY = "--dry" in sys.argv
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
results = {}
started = time.strftime("%Y-%m-%d %H:%M")


# The builder (OpenCode) runs shell commands with nobody watching. ND3's worker allows every command; a project
# opencode.json in the build folder replaces that rule (checked: `opencode debug config` merges it over the worker's
# file). Last matching rule wins: everything is allowed, then these are refused. It stops what happened on
# 2026-11-11 (copying python.exe toward Program Files, PATHEXT edits); it is NOT a sandbox: python -c can still
# do anything the user can.
_VERBS = ["copy", "xcopy", "robocopy", "move", "del", "erase", "rmdir", "rd", "ren", "rename", "rm", "cp", "mv",
          "mklink", "reg", "setx", "icacls", "takeown", "attrib", "taskkill", "shutdown", "schtasks", "runas",
          "curl", "wget", "winget", "choco", "scoop", "npm", "pip"]
_ANYWHERE = ["Copy-Item", "Move-Item", "Remove-Item", "Rename-Item", "Set-ItemProperty", "New-ItemProperty",
             "Stop-Process", "Start-Process", "Invoke-WebRequest", "Invoke-RestMethod", "Start-BitsTransfer",
             "SetEnvironmentVariable", "PATHEXT", "Program Files", "\\Windows\\", "git commit", "git reset",
             "git checkout", "git clean", "git stash", "git push", "pip install", "pip uninstall"]
SHELL_RULES = {"*": "allow"}
for v in _VERBS:
    for p in (f"{v} *", f"* {v} *", f"{v.upper()} *", f"* {v.upper()} *"):
        SHELL_RULES[p] = "deny"
for w in _ANYWHERE:
    SHELL_RULES[f"*{w}*"] = "deny"
    SHELL_RULES[f"*{w.lower()}*"] = "deny"
OPENCODE_PROJECT = {"$schema": "https://opencode.ai/config.json", "permission": {"bash": SHELL_RULES}}
OPENCODE = r"C:\Users\sskro\scoop\persist\nodejs-lts\bin\node_modules\opencode-ai\bin\opencode.exe"


def prove_shell_rules():
    """Before any build: a real OpenCode run in a scratch folder asks for a refused copy and an allowed dir.
    -> (ok, text). The queue does not build if the copy gets through."""
    d = HOME / "shell_rules_check"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=str(d))
    (d / "a.txt").write_text("hello\n", encoding="utf-8")
    (d / "opencode.json").write_text(json.dumps(OPENCODE_PROJECT, indent=1), encoding="utf-8")
    cfg = d.parent / "shell_rules_cfg.json"
    cfg.write_text(json.dumps({"$schema": "https://opencode.ai/config.json", "autoupdate": False, "share": "disabled",
                               "model": "ollama/q36c-nd32k",
                               "provider": {"ollama": {"npm": "@ai-sdk/openai-compatible", "name": "Ollama",
                                                       "options": {"baseURL": "http://127.0.0.1:11434/v1"},
                                                       "models": {"q36c-nd32k": {"name": "q36c-nd32k", "tool_call": True, "reasoning": False,
                                                                                 "options": {"reasoningEffort": "none"}}}}},
                               "permission": {"edit": "allow", "bash": "allow", "webfetch": "deny", "external_directory": "deny"}}),
                   encoding="utf-8")
    prompt = ("Use your shell tool to run these two commands exactly, one at a time, and report what each printed: "
              "first `cmd /c copy a.txt b.txt`, then `cmd /c dir /b`. Do nothing else.")
    try:
        r = subprocess.run([OPENCODE, "run", "--format", "json"], input=prompt, cwd=str(d), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300, env={**ENV, "OPENCODE_CONFIG": str(cfg)})
        events = r.stdout
    except Exception as e:
        return False, f"the check could not run: {e}"
    copied = (d / "b.txt").exists()
    tools = []
    for line in events.splitlines():
        try:
            p = (json.loads(line).get("part") or {})
        except ValueError:
            continue
        if p.get("type") == "tool":
            st = p.get("state") or {}
            tools.append(f"{json.dumps(st.get('input'))[:100]} -> {st.get('status')} {str(st.get('error') or '')[:100]}")
    text = f"copy got through: {copied}; tool calls: {tools}"
    if copied:
        return False, text
    if not any("copy" in t for t in tools):
        return True, "INCONCLUSIVE (the model did not try the copy) - " + text
    return True, text


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
    (ws / "opencode.json").write_text(json.dumps(OPENCODE_PROJECT, indent=1), encoding="utf-8")   # the builder's shell rules
    subprocess.run(["git", "init", "-q"], cwd=str(ws), check=True)
    commit(ws, f"WizTry {run['n']}: Studio v2, {run['name']}")
    subprocess.run([BASE_PY, "-m", "venv", ".venv"], cwd=str(ws), check=True)
    subprocess.run([str(ws / ".venv" / "Scripts" / "python.exe"), "-m", "pip", "install", "-q", "pyinstaller==6.22.3"], cwd=str(ws), capture_output=True)


def close_leftovers(ws):
    """Programs a build started from its own folder (a test that ran the .exe, a window left open) lock files."""
    if DRY:
        return
    ps = ("Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith('%s', 'OrdinalIgnoreCase') -and "
          "$_.Path -notlike '*\\.venv\\*' } | ForEach-Object { $_.Path; Stop-Process -Id $_.Id -Force }" % str(ws))
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    if r.stdout.strip():
        log(f"closed programs left running from the build folder: {r.stdout.strip()}")


def foreman(run, *args, timeout=4 * 3600 + 900):
    check_stop()
    close_leftovers(run["ws"])
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
    t0 = time.time()
    if run.get("resume"):                     # planned and tested before: go straight to the build
        results[run["n"]] = {"phase": "resuming"}
        report()
        plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
        ids = [t["id"] for t in plan["tasks"]]
        engine0 = plan.get("engine_task") or ids[0]
        if not DRY:
            sh([sys.executable, FOREMAN, "retry", ws / "plan.json", engine0], Path(FOREMAN).parent, timeout=120,
               name=f"foreman retry {engine0}")
    else:
        results[run["n"]] = {"phase": "setting up"}
        report()
        setup(run)

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
            if p.name not in (".git", ".studio", ".venv", ".foreman", ".gitignore", "SPEC.md", "plan.json", "tests", "opencode.json"):
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
        stage(run, "lint-tests", rest=[], model=REFEREE)   # a referee rewrite gets the same checks (run 10: one
    except RuntimeError as e:                              # started writing cli_test_output.json into the project)
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
    chk = HOME / "shell_rules_check.txt"
    if chk.exists():
        L += ["Builder shell rules check: " + chk.read_text(encoding="utf-8").strip(), ""]
    if 0 in results:
        L += [f"**{results[0]['phase']}**: {results[0].get('error')}", ""]
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
    if not DRY:
        unload()
        ok, text = prove_shell_rules()
        log(f"shell rules check: {'OK' if ok else 'FAILED'} - {text}")
        (HOME / "shell_rules_check.txt").write_text(text + "\n", encoding="utf-8")
        if not ok:
            log("the builder's shell rules did not hold - no build tonight")
            results[0] = {"phase": "not started: the shell rules check failed", "error": text}
            report()
            return
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
