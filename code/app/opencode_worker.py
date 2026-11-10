"""ND's OpenCode worker: hand one coding job to OpenCode, watch it, judge the result with plain code.

    python opencode_worker.py run   <workspace> "<task>"      [--task-file F] [--minutes 25]
                                    [--model q36c-nd128k] [--no-shell] [--init] [--json OUT]
    python opencode_worker.py keep  <workspace> <run-id> ["commit message"]
    python opencode_worker.py undo  <workspace> <run-id>
    python opencode_worker.py smoke                               does OpenCode answer at all?

Design: DESIGN_opencode_worker.md. Why: on T3 (same task, scorer and 32K window) OpenCode with
Qwen3.6-35B-A3B coding scored 8.27/9 over 15 runs; ND's own loop with the same model about 5.

run:
  1. preflight - the folder is a git repo with a clean tree (--init makes one); record start_sha;
     run the project's test files (ND's rule: test_*.py, *_test.py; the 6 smallest) -> what passes now
  2. free the GPU (unload every other Ollama model), write ND's own OpenCode config (never into the project)
  3. `opencode run --pure --format json --dir <ws>`, task on STDIN (as an argument its quotes arrive
     as \\" and the npm .cmd shim cuts it at the first line break - both measured 2026-11-08);
     one line per step is printed live; time limit, then the process tree is killed
  4. judge - rerun the tests: a check that passed before and does not now is a REGRESSION; diff stat;
     honest exits (overflow / timeout / crashed / quit early are never "done")
  5. nothing is committed: `keep` commits, `undo` resets to start_sha. The record of every run is
     ND3/opencode/runs/<run-id>.json, its raw events <run-id>.jsonl.

Shell (bash) is allowed unless --no-shell: without it OpenCode cannot run the tests itself, and the
T3 numbers above do not hold. `opencode run` cannot answer a permission prompt, so each permission is
allow or deny, never ask. Files outside the folder: denied. Web fetch: denied.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import nd_foreman as fm  # noqa: E402  (git, run_test, lost_labels: tested, 59 tests)

OLLAMA = "http://127.0.0.1:11434"
HOME = HERE / "opencode"
RUNS = HOME / "runs"
CONFIG = HOME / "opencode.json"
# qwen3.6:35b-a3b-coding at num_ctx 65536. Not 32K: T3 peaks at 24-30K (15 direct runs), so with a 32K
# window any compaction trigger fires on every job - measured 2026-11-09, trigger ~18.7K: 6-9 compactions
# per run, 576-608 s instead of ~190, scores 8/2/4. Its attention is mostly linear, so 64K costs ~0.1 GB
# and no speed (74.6 vs 73.8 tok/s). Compaction stays as the safety net for big jobs, at ~53K.
MODEL = "q36c-nd128k"           # num_ctx 131072: 0.3 GB and ~2% speed more than 64K (85.2 vs 87.1 tok/s)
WINDOW = 131072
# Output per step. Qwen3.6 thinks before it acts and the thinking counts as output: on the WIZTRY treemap
# (real algorithm work) all 3 attempts ended on ONE step of exactly 8192 tokens, reason "length" - cut off
# mid-thought, so OpenCode stopped with nothing (or half a file) written (2026-11-09). At 16384 it thought
# past that too. T3 never came near either.
OUTPUT = 32768
INPUT = WINDOW - OUTPUT         # prompt + output must fit num_ctx
RESERVED = 8000                 # compact when the prompt passes INPUT - RESERVED (~88K; T3 peaks at 31-34K)
OPENCODE_VERSION = "1.19.5"     # compaction and the event format were measured on this version
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git", ".nd_backups", ".foreman"}
MAX_SUITES = 6
QUIT_EARLY_STEPS = 5


def say(m):
    try:
        print(m, flush=True)
    except UnicodeEncodeError:
        print(m.encode("ascii", "replace").decode(), flush=True)


# ── OpenCode itself ──────────────────────────────────────────────────────────

def opencode_exe():
    """The real opencode.exe, not the npm .cmd shim (the shim cuts multi-line input)."""
    env = os.environ.get("ND_OPENCODE_EXE")
    if env and Path(env).exists():
        return Path(env)
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, shell=True).stdout.strip()
    for name in ("opencode.exe", "opencode"):
        p = Path(root) / "opencode-ai" / "bin" / name
        if p.exists():
            return p
    raise SystemExit("OpenCode not found: npm i -g opencode-ai@" + OPENCODE_VERSION)


def write_config(model=MODEL, shell=True, think=True):
    """ND's config for OpenCode. limit.input is what makes compaction.reserved count: without it OpenCode
    compacts at context minus output and a jump past the window kills the run (WIZTRY, 2026-11-09).
    The Ollama tag must carry num_ctx >= WINDOW, or Ollama cuts the prompt before OpenCode compacts.

    think=False sends reasoningEffort "none" (Ollama's OpenAI endpoint ignores `think`; checked: a one-word
    answer took 71 output tokens with thinking, 2 without). Default ON: T3's 8.27/9 was measured with it on.
    Why it exists: on the WIZTRY treemap, Qwen3.6 with thinking re-wrote the whole algorithm in its head
    ~20 times (22K tokens, 26 min in a direct probe), never ran anything, and was still wrong (11/17
    checks); inside OpenCode every attempt was cut off at the output limit before any file was saved."""
    HOME.mkdir(exist_ok=True)
    mcfg = {"name": model, "tool_call": True, "reasoning": False,
            "limit": {"context": WINDOW, "input": INPUT, "output": OUTPUT}}
    if not think:
        mcfg["options"] = {"reasoningEffort": "none"}
    CONFIG.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False, "share": "disabled",
        "model": f"ollama/{model}", "small_model": f"ollama/{model}",
        "provider": {"ollama": {
            "npm": "@ai-sdk/openai-compatible", "name": "Ollama (local)",
            "options": {"baseURL": OLLAMA + "/v1"},
            "models": {model: mcfg}}},
        "compaction": {"auto": True, "prune": True, "reserved": RESERVED, "preserve_recent_tokens": 4000},
        "permission": {"edit": "allow", "bash": "allow" if shell else "deny",
                       "webfetch": "deny", "external_directory": "deny"},
    }, indent=1), encoding="utf-8")


def ollama(path, payload=None, timeout=60):
    if payload is None:
        return json.loads(urllib.request.urlopen(OLLAMA + path, timeout=timeout).read())
    req = urllib.request.Request(OLLAMA + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def free_gpu(keep=None):
    """Unload every model except `keep` (the one OpenCode is about to use: no reload if it is loaded)."""
    try:
        for m in ollama("/api/ps").get("models", []):
            if keep and m["name"].split(":")[0] == keep.split(":")[0]:
                continue
            ollama("/api/generate", {"model": m["name"], "keep_alive": 0}, 120)
    except Exception as e:                                  # Ollama down: OpenCode will say so too
        say(f"  (could not unload models: {e})")


def describe(part, ws=None):
    """One readable line for a tool step (paths relative to the project), or None."""
    tool = part.get("tool")
    if not tool:
        return None
    inp = (part.get("state") or {}).get("input") or {}
    if tool == "invalid":                                    # a call OpenCode refused (e.g. bash with shell off)
        return f"(refused: it tried {inp.get('tool') or 'an unknown tool'})"
    arg = str(inp.get("filePath") or inp.get("path") or inp.get("pattern") or inp.get("command") or inp.get("description") or "")
    if ws:                                                   # before cutting, or a long folder never matches
        for root in (str(ws) + os.sep, str(ws) + "/", str(ws)):
            arg = arg.replace(root, "")
    return f"{tool} {(arg or '.').replace(chr(10), ' ')[:110]}".rstrip()


class Run:
    """One `opencode run`, its events read as they arrive."""

    def __init__(self, ws, task, out, minutes, on_step=say, cancel=None):
        self.ws, self.task, self.out, self.limit, self.on_step = Path(ws), task, Path(out), minutes * 60, on_step
        self.cancel = cancel or threading.Event()
        self.tools, self.steps, self.tok_in, self.tok_out, self.peak = Counter(), 0, 0, 0, 0
        self.last_text, self.errors, self.edits = "", [], 0
        self.session, self.cancelled, self.cut_off = None, False, 0

    def _event(self, line):
        try:
            e = json.loads(line)
        except ValueError:
            return
        self.session = self.session or e.get("sessionID")
        part = e.get("part") or {}
        if e.get("type") == "error" or part.get("type") == "error":
            self.errors.append(json.dumps(e.get("error") or part)[:400])
        if part.get("tool") and (part.get("state") or {}).get("status") in ("completed", "error", None):
            self.tools[part["tool"]] += 1
            if part["tool"] in ("edit", "write", "patch", "multiedit"):
                self.edits += 1
            d = describe(part, self.ws)
            if d:
                self.on_step(f"  {time.time() - self.t0:5.0f}s  {d}")
        if part.get("type") == "step-finish":
            self.steps += 1
            t = part.get("tokens") or {}
            self.tok_in += int(t.get("input") or 0)
            self.tok_out += int(t.get("output") or 0)
            ctx = int(t.get("input") or 0) + int((t.get("cache") or {}).get("read") or 0)
            self.peak = max(self.peak, ctx)
            if part.get("reason") == "length":              # the step hit the output limit mid-answer
                self.cut_off += 1
                self.on_step(f"  {time.time() - self.t0:5.0f}s  (CUT OFF: one step hit the {OUTPUT}-token output limit)")
        if part.get("type") == "text" and part.get("text"):
            self.last_text = part["text"]

    def go(self, model):
        env = dict(os.environ, OPENCODE_CONFIG=str(CONFIG))
        for venv in (self.ws / ".venv" / "Scripts", self.ws / ".venv" / "bin"):
            if venv.exists():                                # the project's python first, as the T3 arm ran it
                env["PATH"] = str(venv) + os.pathsep + env.get("PATH", "")
        self.t0 = time.time()
        with open(self.out, "w", encoding="utf-8") as raw, open(str(self.out) + ".err", "w", encoding="utf-8") as err:
            p = subprocess.Popen([str(opencode_exe()), "run", "--pure", "--format", "json", "--dir", str(self.ws)],
                                 cwd=str(self.ws), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=err, creationflags=NO_WINDOW)
            p.stdin.write(self.task.encode("utf-8"))
            p.stdin.close()

            def pump():
                for b in p.stdout:
                    line = b.decode("utf-8", "replace")
                    raw.write(line)
                    raw.flush()
                    self._event(line)
            th = threading.Thread(target=pump, daemon=True)
            th.start()
            rc, timed_out = None, False
            while rc is None:                                # wait, but stay stoppable (the UI's Stop button)
                try:
                    rc = p.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    over = time.time() - self.t0 > self.limit
                    if over or self.cancel.is_set():
                        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
                        p.wait(30)
                        rc, timed_out, self.cancelled = -9, over, not over
            th.join(10)
        self.secs, self.rc, self.timed_out = round(time.time() - self.t0), rc, timed_out
        self.stderr = Path(str(self.out) + ".err").read_text(encoding="utf-8", errors="replace")
        return self


def stray_processes(ws, since):
    """Kill python/node processes the run left behind in this folder (a dev server started with bash).
    Only processes whose command line names the folder and that started after `since`; never ND, the
    foreman, this process or its parent. Measured 2026-11-09: the foreman's own command line names the
    workspace (`nd_foreman.py run <ws>\\plan.json`), `since` was cut to whole seconds and the foreman had
    started in that same second - it killed itself silently after its first attempt."""
    me = {os.getpid(), os.getppid()}
    ps = ("$t=[datetime]'" + datetime.fromtimestamp(since).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "'; "
          "$me=@(" + ",".join(str(p) for p in me) + "); "
          "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw|node|uvicorn)\\.exe$' -and "
          "$me -notcontains $_.ProcessId -and "
          "$_.CreationDate -gt $t -and $_.CommandLine -like '*" + str(ws).replace("'", "''") + "*' -and "
          "$_.CommandLine -notmatch 'NeuralDock_launcher|opencode_worker|nd_foreman|foreman_run' } | "
          "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; $_.ProcessId } catch {} }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                       timeout=60, creationflags=NO_WINDOW)
    return [x for x in (r.stdout or "").split() if x.isdigit()]


# ── tests before and after ───────────────────────────────────────────────────

def suites(ws):
    """ND's rule (_looks_like_test_file / _project_suites): test_*.py and *_test.py, the 6 smallest."""
    out = []
    for p in Path(ws).rglob("*.py"):
        n = p.name.lower()
        if not (n.startswith("test_") or n.endswith("_test.py")):
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(ws).parts):
            continue
        try:
            out.append((p.stat().st_size, p.relative_to(ws).as_posix()))
        except OSError:
            pass
    return [r for _, r in sorted(out)[:MAX_SUITES]]


def test_snapshot(ws, files):
    plan = {"workspace": str(ws)}
    snap = {}
    for rel in files:
        r = fm.run_test(plan, rel, timeout=300)
        snap[rel] = {"ok": r["ok"], "passed": r["passed"], "failed": r["failed"],
                     "labels": r["labels_pass"], "tail": r["tail"][-1200:]}
    return snap


def regressions(before, after):
    """What passed before and does not now. A suite's OWN new failing tests are listed apart: only
    losing something that already passed counts as breaking the project."""
    broke, new_failing = [], []
    for rel, b in before.items():
        if not b["passed"]:
            continue
        a = after.get(rel) or {"passed": 0, "failed": -1, "labels": [], "tail": "missing"}
        lost = fm.lost_labels(b["labels"], a["labels"]) if b["labels"] else []
        if lost:
            broke.append(f"{rel}: {len(lost)} check(s) that passed now fail: " + "; ".join(lost[:5]))
        elif a["passed"] < b["passed"]:
            broke.append(f"{rel}: {a['passed']} passing (was {b['passed']})" +
                         (f" - {a['tail'].strip().splitlines()[-1][:200]}" if a["tail"].strip() else ""))
        elif a["failed"]:
            new_failing.append(f"{rel}: {a['failed']} failing, all of them new tests")
    return broke, new_failing


# ── git ──────────────────────────────────────────────────────────────────────

def git(ws, *a, check=True, strip=True):
    """git with the REPO'S OWN settings. Not fm.git: that forces core.autocrlf=false, which suits the
    foreman's own repos, but in a user's autocrlf=true repo (LF stored, CRLF on disk) every file a reset
    rewrote then reads as modified - measured 2026-11-09, the bench copy refused run 2 as 'uncommitted'."""
    r = subprocess.run(["git", "-C", str(ws), "-c", "user.name=ND OpenCode worker", "-c", "user.email=nd@localhost", *a],
                       capture_output=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a)}: {(r.stderr or r.stdout).strip()[:400]}")
    return (r.stdout or "").strip() if strip else (r.stdout or "")


def changed(ws):
    """Every path changed, added or deleted since HEAD (untracked included)."""
    out = git(ws, "status", "--porcelain=v1", "-uall", "-z", strip=False)
    paths, parts, i = [], out.split("\0"), 0
    while i < len(parts):
        e = parts[i]
        if len(e) > 3:
            paths.append(e[3:].replace("\\", "/"))
            if e[0] in "RC" and i + 1 < len(parts):      # rename: the old name follows
                i += 1
        i += 1
    return sorted(set(paths))


def undo(ws, sha):
    git(ws, "reset", "-q", "--hard", sha)
    git(ws, "clean", "-q", "-fd")                         # untracked files; ignored ones (.venv) stay


def preflight(ws, init):
    ws = Path(ws)
    if not ws.is_dir():
        raise SystemExit(f"no such folder: {ws}")
    if not (ws / ".git").exists():
        if not init:
            raise SystemExit("not a git repository, so there would be no safe undo. Run again with --init "
                             "(git init + a first commit of the folder as it is).")
        git(ws, "init", "-q")
    if not git(ws, "rev-parse", "--verify", "-q", "HEAD", check=False):
        git(ws, "add", "-A")
        git(ws, "commit", "-q", "--allow-empty", "-m", "snapshot before OpenCode")
    dirty = changed(ws)
    if dirty:
        raise SystemExit("the folder has uncommitted changes (" + ", ".join(dirty[:6]) +
                         (" ..." if len(dirty) > 6 else "") + "). Commit or stash them first, so undo "
                         "cannot touch your own work.")
    return git(ws, "rev-parse", "HEAD")


def diffstat(ws, sha):
    git(ws, "add", "-A", "-N")                              # new files show in the diff, nothing is staged
    stat = git(ws, "diff", "--stat", sha, check=False)
    files = [l for l in git(ws, "diff", "--name-status", sha, check=False).splitlines() if l.strip()]
    git(ws, "reset", "-q", check=False)                     # drop the intent-to-add marks: the index is as it was
    return stat, files


# ── commands ─────────────────────────────────────────────────────────────────

def verdict(run, broke):
    """Honest exits first: none of these may read as 'done'."""
    if getattr(run, "cancelled", False):
        return "stopped", "stopped by you before it finished"
    if run.errors and any("ContextOverflow" in e or "context" in e.lower() for e in run.errors):
        return "overflow", "OpenCode ran out of context window and stopped"
    if run.timed_out:
        return "timeout", f"stopped at the {run.limit // 60}-minute limit"
    if run.rc not in (0, None):
        return "crashed", f"OpenCode exited with code {run.rc}"
    if getattr(run, "cut_off", 0) and (run.edits == 0 or broke):
        return "cut_off", f"the model hit the {OUTPUT}-token output limit in one step and was cut off mid-answer"
    if run.edits == 0 and run.steps <= QUIT_EARLY_STEPS:
        return "quit_early", f"no edits in {run.steps} step(s): it stopped before doing the work"
    if run.edits == 0:
        return "no_changes", "it finished without changing any file"
    if broke:
        return "broke", "finished, but something that passed before now fails"
    return "done", "finished; nothing that passed before is broken"


def job(ws, task, model=MODEL, minutes=25, shell=True, init=False, log=say, cancel=None, run_id=None,
        continue_from=None, think=True):
    """One whole job: preflight, tests before, OpenCode, judge. -> the record (also saved in RUNS).
    A refused preflight returns status 'refused' with the reason instead of raising.
    continue_from: an earlier run's id - work on top of its uncommitted changes (to fix what it broke).
    Its start commit and its tests-before are reused, so undo and 'broke' still mean 'since before both'."""
    ws = Path(ws).resolve()
    RUNS.mkdir(parents=True, exist_ok=True)
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    base = {"run_id": run_id, "workspace": str(ws), "task": task, "model": model, "shell": shell}
    if not (task or "").strip():
        return {**base, "status": "refused", "why": "no task given"}
    log(f"OpenCode job {run_id} in {ws}  (model {model}, limit {minutes:g} min, shell {'on' if shell else 'off'})")
    try:
        if continue_from:
            prev = load_rec(ws, continue_from)
            if not prev.get("start_sha") or git(ws, "rev-parse", "HEAD") != prev["start_sha"]:
                raise SystemExit("the project has moved on since that job (kept or committed?): start a new job")
            start, before = prev["start_sha"], prev["tests_before"]
            base["continues"] = continue_from
            log(f"continuing on top of job {continue_from}")
        else:
            start, before = preflight(ws, init), None
    except SystemExit as e:
        rec = {**base, "status": "refused", "why": str(e)}
        (RUNS / f"{run_id}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
        log("REFUSED: " + str(e))
        return rec
    files = list(before) if before is not None else suites(ws)
    log(f"start {start[:8]}; tests: {', '.join(files) or 'none found'}")
    if before is None:
        before = test_snapshot(ws, files)
    for rel, s in before.items():
        log(f"  {rel}: {s['passed']} passing, {s['failed']} failing" + (" (before the first job)" if continue_from else ""))
    write_config(model, shell=shell, think=think)
    free_gpu(keep=model)
    log("running OpenCode ..." + ("" if think else " (thinking off)"))
    run = Run(ws, task, RUNS / f"{run_id}.jsonl", minutes, on_step=log, cancel=cancel).go(model)
    killed = stray_processes(ws, run.t0)
    log("checking the tests again ...")
    after = test_snapshot(ws, files)
    broke, new_failing = regressions(before, after)
    stat, changed_files = diffstat(ws, start)
    status, why = verdict(run, broke)
    rec = {**base, "start_sha": start, "status": status, "why": why, "secs": run.secs, "rc": run.rc,
           "timed_out": run.timed_out, "steps": run.steps, "edits": run.edits, "tools": dict(run.tools),
           "tokens_in": run.tok_in, "tokens_out": run.tok_out, "context_peak": run.peak, "errors": run.errors,
           "reply": run.last_text[-3000:], "changed": changed_files, "diffstat": stat,
           "tests_before": before, "tests_after": after, "regressions": broke, "new_tests_failing": new_failing,
           "killed_processes": killed, "session": run.session, "stderr_tail": run.stderr[-1500:]}
    (RUNS / f"{run_id}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def summary_lines(rec):
    out = [f"RESULT: {rec['status'].upper()} - {rec['why']}"]
    if rec["status"] == "refused":
        return out
    out.append(f"  {rec['secs']}s, {rec['steps']} steps, {rec['edits']} edits, {rec['tokens_out']} tokens out, "
               f"context peak {rec['context_peak']}")
    out.append(f"  changed: {', '.join(rec['changed']) or 'nothing'}")
    for rel, b in rec["tests_before"].items():
        f = rec["tests_after"].get(rel) or {}
        out.append(f"  tests {rel}: {b['passed']}/{b['failed']} -> {f.get('passed')}/{f.get('failed')} (passing/failing)")
    out += ["  BROKE: " + x for x in rec["regressions"]]
    out += ["  new tests failing: " + x for x in rec["new_tests_failing"]]
    if rec["killed_processes"]:
        out.append(f"  stopped {len(rec['killed_processes'])} process(es) it left running")
    if rec["reply"]:
        out.append("  OpenCode says: " + rec["reply"].strip()[-800:].replace("\n", "\n    "))
    return out


def cmd_run(a):
    task = Path(a.task_file).read_text(encoding="utf-8") if a.task_file else a.task
    rec = job(a.workspace, task, a.model, a.minutes, shell=not a.no_shell, init=a.init,
              log=lambda m: say(m if m.startswith(" ") else "  " + m), think=not a.no_think)
    if a.json:
        Path(a.json).write_text(json.dumps(rec, indent=1), encoding="utf-8")
    say("")
    for line in summary_lines(rec):
        say(line)
    if rec["status"] != "refused":
        say("")
        say(f"Nothing is committed. Keep: opencode_worker.py keep \"{rec['workspace']}\" {rec['run_id']}   "
            f"Undo: opencode_worker.py undo \"{rec['workspace']}\" {rec['run_id']}")
    return 0 if rec["status"] == "done" else 1


# ── for ND's launcher: one job at a time, in a thread, polled by the UI ──────

class Jobs:
    """POST /api/opencode_job {op, ...}. One job at a time: the model needs the whole graphics card.
        start  {workspace, task, shell, minutes?, init?}  -> {ok, run_id}
        status {run_id, since}                             -> {ok, state, lines[since:], n, rec?}
        cancel {run_id}    keep {run_id, message?}    undo {run_id}    diff {run_id}    last {}
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.cur = None                                   # {run_id, lines, state, rec, cancel, workspace}

    def start(self, workspace, task, shell, minutes=25, init=False, model=MODEL, continue_from=None):
        with self.lock:
            if self.cur and self.cur["state"] == "running":
                return {"ok": False, "msg": "an OpenCode job is already running", "run_id": self.cur["run_id"]}
            ws = str(workspace or "").strip()
            if not ws or not Path(ws).is_dir():
                return {"ok": False, "msg": "set a project folder first (the workspace bar)"}
            if not str(task or "").strip():
                return {"ok": False, "msg": "no task"}
            try:
                opencode_exe()
            except SystemExit as e:
                return {"ok": False, "msg": str(e)}
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            cur = {"run_id": run_id, "lines": [], "state": "running", "rec": None, "cancel": threading.Event(),
                   "workspace": ws, "t0": time.time()}
            self.cur = cur

        def body():
            try:
                cur["rec"] = job(ws, task, model, minutes, shell=shell, init=init, log=cur["lines"].append,
                                 cancel=cur["cancel"], run_id=run_id, continue_from=continue_from)
            except Exception as e:                          # a bug here must still end the job visibly
                cur["rec"] = {"run_id": run_id, "workspace": ws, "task": task, "status": "error",
                              "why": f"{type(e).__name__}: {e}"}
                cur["lines"].append(f"ERROR: {type(e).__name__}: {e}")
            cur["state"] = "finished"
        threading.Thread(target=body, daemon=True, name="opencode-job").start()
        return {"ok": True, "run_id": run_id}

    def status(self, run_id, since=0):
        cur = self.cur
        if not cur or cur["run_id"] != run_id:
            p = RUNS / f"{run_id}.json"                      # finished in an earlier ND session
            if p.exists():
                return {"ok": True, "state": "finished", "lines": [], "n": 0, "rec": json.loads(p.read_text(encoding="utf-8"))}
            return {"ok": False, "msg": "no such job"}
        lines = cur["lines"]
        return {"ok": True, "state": cur["state"], "lines": lines[since:], "n": len(lines),
                "secs": round(time.time() - cur["t0"]), "rec": cur["rec"]}

    def handle(self, body, shell_allowed):
        op = str(body.get("op") or "")
        run_id = str(body.get("run_id") or "")
        try:
            if op == "start":
                shell = bool(body.get("shell", True)) and shell_allowed
                return self.start(body.get("workspace"), body.get("task"), shell,
                                  float(body.get("minutes") or 25), bool(body.get("init")),
                                  continue_from=str(body.get("continue_from") or "") or None)
            if op == "status":
                return self.status(run_id, int(body.get("since") or 0))
            if op == "last":
                cur = self.cur
                return {"ok": True, "run_id": cur["run_id"] if cur else None, "state": cur["state"] if cur else None}
            if op == "cancel":
                if self.cur and self.cur["run_id"] == run_id:
                    self.cur["cancel"].set()
                    return {"ok": True}
                return {"ok": False, "msg": "that job is not running"}
            if self.cur and self.cur["run_id"] == run_id and self.cur["state"] == "running":
                return {"ok": False, "msg": "wait for the job to finish first"}
            rec = json.loads((RUNS / f"{run_id}.json").read_text(encoding="utf-8")) if (RUNS / f"{run_id}.json").exists() else None
            if not rec or not rec.get("start_sha"):
                return {"ok": False, "msg": "no finished job with that id"}
            ws = rec["workspace"]
            if op == "diff":
                git(ws, "add", "-A", "-N")
                d = git(ws, "diff", rec["start_sha"], check=False, strip=False)
                git(ws, "reset", "-q", check=False)
                return {"ok": True, "diff": d[:200000], "cut": len(d) > 200000}
            if op == "keep":
                if not changed(ws):
                    return {"ok": False, "msg": "nothing to commit (already kept or undone?)"}
                msg = str(body.get("message") or "").strip() or ("OpenCode: " + rec["task"].strip().splitlines()[0][:70])
                git(ws, "add", "-A")
                git(ws, "commit", "-q", "-m", msg)
                return {"ok": True, "commit": git(ws, "rev-parse", "--short", "HEAD"), "message": msg}
            if op == "undo":
                if git(ws, "rev-parse", "HEAD") != rec["start_sha"]:
                    return {"ok": False, "msg": "the project has new commits since this job (kept?): undo it with git"}
                undo(ws, rec["start_sha"])
                return {"ok": True, "msg": f"back at {rec['start_sha'][:8]}"}
            return {"ok": False, "msg": f"unknown op {op!r}"}
        except Exception as e:
            return {"ok": False, "msg": f"{type(e).__name__}: {e}"}


JOBS = Jobs()


def load_rec(ws, run_id):
    p = RUNS / f"{run_id}.json"
    if not p.exists():
        raise SystemExit(f"no record for run {run_id}")
    rec = json.loads(p.read_text(encoding="utf-8"))
    if Path(rec["workspace"]).resolve() != Path(ws).resolve():
        raise SystemExit(f"run {run_id} was in {rec['workspace']}, not {ws}")
    return rec


def cmd_keep(a):
    rec = load_rec(a.workspace, a.run_id)
    msg = a.message or ("OpenCode: " + rec["task"].strip().splitlines()[0][:70])
    git(a.workspace, "add", "-A")
    git(a.workspace, "commit", "-q", "-m", msg)
    say(f"committed {git(a.workspace, 'rev-parse', '--short', 'HEAD')}: {msg}")


def cmd_undo(a):
    rec = load_rec(a.workspace, a.run_id)
    undo(a.workspace, rec["start_sha"])                 # reset --hard + clean -fd (ignored files stay)
    say(f"back at {rec['start_sha'][:8]}: everything OpenCode changed or added is gone")


def cmd_smoke(a):
    d = HOME / "smoke"
    d.mkdir(parents=True, exist_ok=True)
    (d / "hello.txt").write_text("The secret word is marmalade.\n", encoding="utf-8")
    write_config(a.model, shell=False)
    free_gpu(keep=a.model)
    run = Run(d, 'Read hello.txt.\nReply with only the secret word, without "quotes".', HOME / "smoke.jsonl", 5).go(a.model)
    ok = "marmalade" in run.last_text.lower()
    say(f"smoke {'OK' if ok else 'FAILED'}: {run.secs}s, rc {run.rc}, reply {run.last_text.strip()[:80]!r}")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("workspace")
    r.add_argument("task", nargs="?", default="")
    r.add_argument("--task-file")
    r.add_argument("--minutes", type=float, default=25)
    r.add_argument("--model", default=MODEL)
    r.add_argument("--no-shell", action="store_true")
    r.add_argument("--no-think", action="store_true", help="switch Qwen3.6's thinking off (reasoningEffort none)")
    r.add_argument("--init", action="store_true")
    r.add_argument("--json")
    k = sub.add_parser("keep")
    k.add_argument("workspace")
    k.add_argument("run_id")
    k.add_argument("message", nargs="?")
    u = sub.add_parser("undo")
    u.add_argument("workspace")
    u.add_argument("run_id")
    s = sub.add_parser("smoke")
    s.add_argument("--model", default=MODEL)
    a = ap.parse_args(argv)
    return {"run": cmd_run, "keep": cmd_keep, "undo": cmd_undo, "smoke": cmd_smoke}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
