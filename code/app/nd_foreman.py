"""The Foreman: runs a written plan through ND's coding agent, one small task at a time.

A strong model (or a person) plans once: the tasks, their order, the files each may change
and a test for every task - all written BEFORE the run. The foreman is plain code with no
model in it, so a confident reply can never pass a task. It hands ND one task, then judges:

    scope    only the task's files changed; nothing protected (tests, plan) touched
    lint     no syntax errors / undefined names in the changed Python (ruff, when present)
    tests    the task's own test files pass
    broke    every test file that passed at the last good commit still passes, label by label

Pass -> git commit, next task. Fail -> undo (git reset + clean), retry with the failure shown,
the last try on the other model (a different model fails differently), then "stuck": its
dependants are skipped and independent tasks carry on. State is saved after every step, so a
crash, a reboot or a STOP resumes where it was (run the same command again).

The builder's RULEBOOK is a folder of markdown notes (Obsidian-friendly; point notes_dir at a
vault folder to read and edit them there). Every task prompt is built from them, re-read
before each task, so a rule added mid-run applies from the next task on:
    Foreman - <project>.md   index: the goal, live status table, links
    00 Rules.md              the planner's rules for this project
    10 Conventions.md        code style for this project
    20 Lessons.md            what went wrong so far - the foreman appends on every failure
    tasks/<id>.md            each task's brief and attempt history
    Foreman Report.md        the morning report
plus prompts/foreman_worker.md: how to execute a task in ND (the same for every project).

    python nd_foreman.py check  <plan.json> [--reference DIR]  validate the plan, test the tests
    python nd_foreman.py run    <plan.json> [--only T03] [--max-hours 10]
    python nd_foreman.py status <plan.json>
    python nd_foreman.py report <plan.json>
    python nd_foreman.py notes  <plan.json>                    write / refresh the rulebook
    python nd_foreman.py retry  <plan.json> T07                stuck -> pending (and its dependants)

Stop between tasks: create <workspace>/.foreman/STOP (deleted when the next run starts).
ND turns use req_id "bench_fm_...": ND treats them as unattended (ask_user answers itself)
and keeps the requested model over the code-model pin - both needed for a fair, unattended run.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAYBOOK = HERE / "prompts" / "foreman_worker.md"
PLAYBOOK_OC = HERE / "prompts" / "foreman_worker_opencode.md"
# A model written "opencode/<ollama tag>" runs through OpenCode (opencode_worker.py) instead of ND's
# own loop - on T3, OpenCode + Qwen3.6 coding 8.27/9 (n=15) vs ~5 for ND with the same model. Plain
# names still go to ND, so old plans are unchanged and alt_model can switch WORKER as well as model.
OPENCODE = "opencode/"
ND_URL = "http://127.0.0.1:7788"
OLLAMA_URL = "http://127.0.0.1:11434"
FM = ".foreman"
PROMPT_BUDGET = 30000          # chars (~8K tokens) - leaves room in a 32K window for the work
FILE_CAP = 9000                # one shown file at most; longer ones are cut with a note
LESSONS_SHOWN = 10             # other tasks' lessons shown (this task's are always shown)
AUTO_MARK = "<!-- the foreman adds lessons below this line -->"
_COUNT_RE = re.compile(r"(\d+)\s+passed(?:\s*,\s*(\d+)\s+failed)?", re.I)
_FAILED_ONLY_RE = re.compile(r"(\d+)\s+failed", re.I)
_LABEL_RE = re.compile(r"^\s*(PASS|FAIL|ok|FAILED)\s+(.+?)\s*$")


class Blocked(Exception):
    """The run cannot go on without a person (ND parked on a permission, ND gone)."""


# ── plan ─────────────────────────────────────────────────────────────────────

def _rel(p):
    s = str(p).replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s


def _as_list(x):
    return [x] if isinstance(x, str) else list(x or [])


def load_plan(path):
    """Read and normalise a plan; raises ValueError listing every problem at once."""
    path = Path(path).resolve()
    plan = json.loads(path.read_text(encoding="utf-8"))
    plan["_path"] = str(path)
    ws = Path(plan.get("workspace") or path.parent)
    if not ws.is_absolute():
        ws = (path.parent / ws).resolve()
    plan["workspace"] = str(ws)
    d = plan.setdefault("defaults", {})
    d.setdefault("attempts", 3)
    d.setdefault("minutes", 25)
    plan.setdefault("model", "qwen3.8-27b-defiance:iq4_xs")
    plan.setdefault("alt_model", None)
    plan.setdefault("nd_url", ND_URL)
    plan.setdefault("protected", ["tests/"])
    try:
        plan_rel = _rel(path.relative_to(ws))
        plan["protected"] = list(dict.fromkeys(plan["protected"] + [plan_rel]))
    except ValueError:
        pass                                              # plan kept outside the workspace
    probs, ids = [], set()
    for t in plan.get("tasks") or []:
        t["depends_on"] = _as_list(t.get("depends_on"))
        t["files"] = [_rel(f) for f in _as_list(t.get("files"))]
        t["context"] = [_rel(f) for f in _as_list(t.get("context"))]
        t["tests"] = [_rel(f) for f in _as_list(t.get("tests"))]
        t["done_when"] = _as_list(t.get("done_when"))
        t.setdefault("attempts", d["attempts"])
        t.setdefault("minutes", d["minutes"])
        tid = t.get("id")
        if not tid or not re.fullmatch(r"[A-Za-z0-9_.-]+", str(tid)):
            probs.append(f"a task has no usable id: {t.get('title')!r}")
            continue
        if tid in ids:
            probs.append(f"{tid}: duplicate id")
        ids.add(tid)
        if not t.get("title") or not t.get("brief"):
            probs.append(f"{tid}: needs a title and a brief")
        if not t["files"]:
            probs.append(f"{tid}: lists no files it may change")
        if not t["tests"]:
            probs.append(f"{tid}: has no tests - nothing could decide when it is done")
        for f in t["files"] + t["context"] + t["tests"]:
            if f.startswith("../") or Path(f).is_absolute() or ".." in Path(f).parts:
                probs.append(f"{tid}: {f} is outside the workspace")
        for f in t["files"]:
            if _protected(plan, f):
                probs.append(f"{tid}: {f} is protected (tests/plan) and cannot be a task file")
        for f in t["tests"]:
            if not (ws / f).exists():
                probs.append(f"{tid}: test file {f} does not exist - write the tests before the run")
    if not plan.get("tasks"):
        probs.append("the plan has no tasks")
    for t in plan.get("tasks") or []:
        for dep in t["depends_on"]:
            if dep not in ids:
                probs.append(f"{t.get('id')}: depends on unknown task {dep}")
    if not probs:
        try:
            order(plan)
        except ValueError as e:
            probs.append(str(e))
    if probs:
        raise ValueError("The plan has problems:\n  - " + "\n  - ".join(probs))
    return plan


def order(plan):
    """Tasks in a dependency-respecting order (the plan's own order where it can)."""
    done, out, tasks = set(), [], list(plan["tasks"])
    while tasks:
        ready = [t for t in tasks if all(d in done for d in t["depends_on"])]
        if not ready:
            raise ValueError("the plan's dependencies go in a circle: " + ", ".join(t["id"] for t in tasks))
        t = ready[0]
        out.append(t)
        done.add(t["id"])
        tasks.remove(t)
    return out


def _protected(plan, rel):
    rel = _rel(rel)
    for p in plan["protected"]:
        p = _rel(p)
        if rel == p.rstrip("/") or (p.endswith("/") and rel.startswith(p)):
            return True
    return rel.startswith(FM + "/")


def plan_hash(plan):
    keep = {k: v for k, v in plan.items() if not k.startswith("_")}
    return hashlib.sha1(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:12]


# ── git ──────────────────────────────────────────────────────────────────────

def git(ws, *args, check=True, strip=True):
    r = subprocess.run(["git", "-C", str(ws), "-c", "user.name=Foreman", "-c", "user.email=foreman@localhost",
                        "-c", "core.autocrlf=false", *args],
                       capture_output=True, encoding="utf-8", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[:400]}")
    # status lines start with a space (" M file"): stripping would eat it, and a letter of the name
    return (r.stdout or "").strip() if strip else (r.stdout or "")


def ensure_repo(ws):
    """A git repository with .foreman/ and ND's .nd_backups/ kept out of it; the first commit if there is none.
    ND copies a file into .nd_backups/ before every edit - measured 2026-10-31, ChordShift T02
    failed scope on those copies, which are ND's, not the model's."""
    ws = Path(ws)
    if not (ws / ".git").exists():
        git(ws, "init", "-q")
    ex = ws / ".git" / "info" / "exclude"
    ex.parent.mkdir(parents=True, exist_ok=True)
    for name in (FM + "/", ".nd_backups/"):
        cur = ex.read_text(encoding="utf-8") if ex.exists() else ""
        if name not in cur.split():
            ex.write_text(cur.rstrip("\n") + ("\n" if cur.strip() else "") + name + "\n", encoding="utf-8")
    if not git(ws, "rev-parse", "--verify", "-q", "HEAD", check=False):
        git(ws, "add", "-A")
        git(ws, "commit", "-q", "--allow-empty", "-m", "foreman: the project as planned")
    return head(ws)


def head(ws):
    return git(ws, "rev-parse", "HEAD")


def changed(ws):
    """Every path changed, added or deleted since HEAD (untracked included), posix-relative."""
    out = git(ws, "status", "--porcelain=v1", "-uall", "-z", strip=False)
    paths, parts, i = [], out.split("\0"), 0
    while i < len(parts):
        e = parts[i]
        if len(e) > 3:
            paths.append(_rel(e[3:]))
            if e[0] in "RC" and i + 1 < len(parts):      # rename: the old name follows
                i += 1
                paths.append(_rel(parts[i]))
        i += 1
    return sorted(set(p for p in paths if p and not p.startswith(FM + "/")))


def undo(ws, sha):
    git(ws, "reset", "-q", "--hard", sha)
    git(ws, "clean", "-q", "-fd")                         # untracked files; ignored ones (.venv, .foreman) stay


def sweep_scratch(plan, task):
    """Delete NEW files outside the task's list (a model's own check scripts) -> their names.
    Measured 2026-10-31: ChordShift T01 attempt 2 wrote both allowed files and was failed
    for a _t01_check.py it left behind. Edits to existing files outside the list still fail."""
    ws, allowed = plan["workspace"], set(task["files"])
    out = git(ws, "ls-files", "--others", "--exclude-standard", "-z", strip=False)
    gone = []
    for p in (_rel(x) for x in out.split("\0") if x):
        if p in allowed or p.startswith(FM + "/") or _protected(plan, p):
            continue
        try:
            (Path(ws) / p).unlink()
            gone.append(p)
        except OSError:
            pass
    return gone


# ── running tests ────────────────────────────────────────────────────────────

def project_python(plan):
    if plan.get("python"):
        return plan["python"]
    ws = Path(plan["workspace"])
    for p in (ws / ".venv" / "Scripts" / "python.exe", ws / ".venv" / "bin" / "python"):
        if p.exists():
            return str(p)
    return sys.executable


def is_pytest_file(src):
    """pytest style = top-level `def test_...` functions and no __main__ block. Everything else (ND's
    suites, scripts that check at import and print their own summary) is run directly."""
    return bool(re.search(r"^def test_\w*\(", src, re.M)) and "__main__" not in src


_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")


def norm_label(label):
    """A check label with its numbers replaced by '#'. Labels that carry a measurement
    ('speed (took 0.20 s)') change every run; the broke gate must still see them as the same check."""
    return _NUM_RE.sub("#", label)


def lost_labels(before, now):
    """Labels that passed before and do not pass now, compared after norm_label (old states
    saved raw labels, so both sides are normalised)."""
    return sorted({norm_label(x)[:120] for x in before} - {norm_label(x)[:120] for x in now})


def run_test(plan, rel, timeout=600):
    """Run one test file. -> {ok, passed, failed, labels_pass, labels_fail, tail}

    ND's own suites print 'PASS label' / 'FAIL label' lines and 'N passed, M failed'; a pytest-style
    file (is_pytest_file) is run with pytest instead. ok = exit code 0 AND nothing failed AND
    something passed (a file that prints nothing proves nothing)."""
    ws, f = Path(plan["workspace"]), Path(plan["workspace"]) / rel
    if not f.exists():
        return {"ok": False, "passed": 0, "failed": 0, "labels_pass": [], "labels_fail": [],
                "tail": f"{rel} does not exist"}
    src = f.read_text(encoding="utf-8", errors="replace")
    py = project_python(plan)
    cmd = [py, "-m", "pytest", "-q", "-rf", "--no-header", str(f)] if is_pytest_file(src) else [py, str(f)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run(cmd, cwd=str(ws), capture_output=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out, rc = (r.stdout or "") + (r.stderr or ""), r.returncode
    except subprocess.TimeoutExpired:
        return {"ok": False, "passed": 0, "failed": 0, "labels_pass": [], "labels_fail": [],
                "tail": f"{rel} did not finish in {timeout}s (an endless loop?)"}
    passed = failed = None
    for line in out.splitlines():                          # the LAST summary line wins
        if _LABEL_RE.match(line):
            continue
        mp, mf = re.search(r"(\d+)\s+passed", line, re.I), _FAILED_ONLY_RE.search(line)
        if mp or mf:
            passed, failed = int(mp.group(1)) if mp else 0, int(mf.group(1)) if mf else 0
    lp, lf = [], []
    for line in out.splitlines():
        m = _LABEL_RE.match(line)
        if m:
            (lp if m.group(1) in ("PASS", "ok") else lf).append(norm_label(m.group(2))[:120])
    ok = rc == 0 and (failed or 0) == 0 and (passed or 0) > 0
    return {"ok": ok, "passed": passed or 0, "failed": failed if failed is not None else (0 if ok else -1),
            "labels_pass": lp, "labels_fail": lf, "tail": failure_tail(out, rc)}


def failure_tail(out, rc, limit=2400):
    """What a fixer needs: the FAIL lines, then the last traceback, then the summary line."""
    lines = (out or "").splitlines()
    fails = [l.rstrip() for l in lines if _LABEL_RE.match(l) and _LABEL_RE.match(l).group(1) in ("FAIL", "FAILED")]
    tb = []
    for i, l in enumerate(lines):
        if l.startswith("Traceback (most recent call last)") or l.startswith("E   ") or l.startswith("_____"):
            tb = lines[i:i + 40]
            if l.startswith("Traceback"):
                break
    summary = [l.strip() for l in lines if _COUNT_RE.search(l) or re.search(r"\d+ failed", l)][-1:]
    text = "\n".join(fails[:25] + ([""] + tb if tb else []) + summary)
    if not text.strip():
        text = "\n".join(l for l in lines[-25:] if l.strip()) or f"(no output, exit code {rc})"
    return text[:limit]


def lint(plan, paths):
    """Syntax errors and undefined names only (ruff E9/F63/F7/F82). None when ruff is absent."""
    py = [p for p in paths if p.endswith(".py") and (Path(plan["workspace"]) / p).exists()]
    if not py:
        return None
    for cmd in ([sys.executable, "-m", "ruff"], [shutil.which("ruff")] if shutil.which("ruff") else None):
        if not cmd:
            continue
        try:
            r = subprocess.run(cmd + ["check", "--no-cache", "--select", "E9,F63,F7,F82", "--output-format", "concise", *py],
                               cwd=plan["workspace"], capture_output=True, encoding="utf-8", errors="replace", timeout=120,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            continue
        if r.returncode not in (0, 1):
            continue                                       # no ruff here, or ruff itself failed
        return "" if r.returncode == 0 else ((r.stdout or "") + (r.stderr or "")).strip()[:1500]
    return None


# ── the rulebook (notes) ─────────────────────────────────────────────────────

class Notes:
    def __init__(self, plan):
        self.plan = plan
        d = plan.get("notes_dir")
        self.dir = Path(d) if d else Path(plan["workspace"]) / FM / "notes"
        if not self.dir.is_absolute():
            self.dir = Path(plan["workspace"]) / self.dir
        self.index = self.dir / f"Foreman - {plan.get('project') or 'project'}.md"

    def path(self, name):
        return self.dir / name

    def ensure(self):
        """Write the notes that don't exist yet (never overwrites what a person edited)."""
        (self.dir / "tasks").mkdir(parents=True, exist_ok=True)
        p = self.plan
        seed = {
            # "> " lines are notes for people; prompts leave them out (Notes.body)
            "00 Rules.md": "# Rules\n\n> The planner's rules for this project. Every task prompt includes this note, "
                           "re-read before each task - edit it during a run and the next task follows it.\n\n"
                           + "\n".join(f"- {r}" for r in p.get("rules") or ["Keep each change small and complete."]) + "\n",
            "10 Conventions.md": "# Conventions\n\n> Code style for this project - included in every task prompt.\n\n"
                                 + "\n".join(f"- {c}" for c in p.get("conventions") or [
                                     "Python 3.11, standard library only unless a task says otherwise.",
                                     "Type hints on public functions; a one-line docstring each.",
                                     "Bad input raises ValueError with a clear message."]) + "\n",
            "20 Lessons.md": "# Lessons\n\n> What went wrong so far. Add your own lessons as bullets above the line - "
                             "every task sees them. The foreman adds one below for every failed attempt.\n\n"
                             + AUTO_MARK + "\n",
        }
        for name, text in seed.items():
            if not self.path(name).exists():
                self.path(name).write_text(text, encoding="utf-8")
        for t in p["tasks"]:
            f = self.dir / "tasks" / f"{t['id']}.md"
            if not f.exists():
                f.write_text(f"# {t['id']} - {t['title']}\n\n{t['brief']}\n\n"
                             + ("**Done when**\n" + "\n".join(f"- {x}" for x in t["done_when"]) + "\n\n" if t["done_when"] else "")
                             + f"Files: {', '.join(t['files'])}  \nTests: {', '.join(t['tests'])}  \n"
                             + (f"After: {', '.join(t['depends_on'])}\n" if t["depends_on"] else "")
                             + "\n## Attempts\n", encoding="utf-8")

    def read(self, name):
        try:
            return self.path(name).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def body(self, name):
        """A note for the prompt: without its title and its "> " lines (those are for people)."""
        lines = [l for l in self.read(name).splitlines() if not l.startswith(">")]
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
        return "\n".join(lines).replace(AUTO_MARK, "").strip()

    def lessons_for(self, tid):
        """The person's lessons, every lesson about this task, and the latest others."""
        txt = self.read("20 Lessons.md")
        mine_top, _, auto = txt.partition(AUTO_MARK)
        mine = [l for l in mine_top.splitlines() if l.strip().startswith(("-", "*"))]
        entries = [l for l in auto.splitlines() if l.strip().startswith("-")]
        this = [l for l in entries if l.startswith(f"- [{tid} ")]
        other = [l for l in entries if not l.startswith(f"- [{tid} ")][-LESSONS_SHOWN:]
        return "\n".join(mine + other + this).strip()

    def add_lesson(self, tid, n, gate, text):
        f = self.path("20 Lessons.md")
        cur = f.read_text(encoding="utf-8") if f.exists() else "# Lessons\n\n" + AUTO_MARK + "\n"
        if AUTO_MARK not in cur:
            cur = cur.rstrip("\n") + "\n\n" + AUTO_MARK + "\n"
        line = f"- [{tid} a{n}] {gate}: " + re.sub(r"\s+", " ", text).strip()[:300]
        f.write_text(cur.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")

    def task_attempt(self, tid, a):
        f = self.dir / "tasks" / f"{tid}.md"
        with f.open("a", encoding="utf-8") as fh:
            fh.write(f"\n### Attempt {a['n']} - {a['verdict'].upper()} ({a['model']}, {a['secs']}s, {a['when']})\n"
                     + (f"Gate: **{a['gate']}**\n\n```\n{a['detail'][:1500]}\n```\n" if a.get("gate") else "")
                     + (f"Commit: `{a['commit'][:10]}`\n" if a.get("commit") else ""))

    def write_index(self, state, report_md):
        p = self.plan
        rows = "\n".join(f"| {t['id']} | {t['title']} | {state['tasks'][t['id']]['status']} | "
                         f"{len(state['tasks'][t['id']]['attempts'])} | [[tasks/{t['id']}]] |" for t in p["tasks"])
        self.index.write_text(
            f"# Foreman - {p.get('project')}\n\n{p.get('goal', '')}\n\n"
            f"Workspace: `{p['workspace']}`  \nModel: `{p['model']}`" + (f" (last try: `{p['alt_model']}`)" if p.get("alt_model") else "")
            + f"  \nRun: **{state.get('phase', 'not started')}** - updated {datetime.now():%Y-%m-%d %H:%M}\n\n"
            "Rulebook: [[00 Rules]] - [[10 Conventions]] - [[20 Lessons]] - report: [[Foreman Report]]\n\n"
            "| Task | Title | Status | Attempts | Note |\n|---|---|---|---|---|\n" + rows + "\n", encoding="utf-8")
        self.path("Foreman Report.md").write_text(report_md, encoding="utf-8")


# ── the prompt for one task ──────────────────────────────────────────────────

def _show(ws, rel, cap, mine=True):
    f = Path(ws) / rel
    if not f.exists():
        # only a task's own files are the worker's to create
        return f"### {rel}\n" + ("(does not exist yet - create it)\n" if mine else "(does not exist - not yours to create)\n")
    try:
        txt = f.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"### {rel}\n(could not be read: {e})\n"
    cut = ""
    if len(txt) > cap:
        txt, cut = txt[:cap], f"\n... (cut at {cap} of {f.stat().st_size} bytes - read_file for the rest)"
    fence = "```" + {".py": "python", ".js": "javascript", ".html": "html", ".json": "json", ".md": "markdown",
                     ".css": "css"}.get(f.suffix, "")
    return f"### {rel}\n{fence}\n{txt.rstrip()}\n```{cut}\n"


def test_cmd(plan, rel):
    src = (Path(plan["workspace"]) / rel)
    py = project_python(plan)
    try:
        pyt = is_pytest_file(src.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        pyt = False
    return f'"{py}" -m pytest -q {rel}' if pyt else f'"{py}" {rel}'


def is_opencode(model):
    return str(model or "").startswith(OPENCODE)


def build_prompt(plan, task, notes, failure=None, n=1, of=1, green=(), opencode=False):
    """The task prompt. opencode=True: OpenCode's playbook and NO pasted files - it reads files itself,
    and 30K characters of pasted files would only eat the window it works in."""
    ws = plan["workspace"]
    tasks = order(plan)
    pos = next(i for i, t in enumerate(tasks) if t["id"] == task["id"]) + 1
    book = PLAYBOOK_OC if opencode else PLAYBOOK
    play = book.read_text(encoding="utf-8").strip() if book.exists() else ""
    lessons = notes.lessons_for(task["id"])
    head_ = [f"# Task {task['id']}: {task['title']}",
             f"(task {pos} of {len(tasks)} in the project \"{plan.get('project')}\" - attempt {n} of {of})", ""]
    if plan.get("goal"):
        head_ += ["## The project (big picture - for context only, do not build the rest)", plan["goal"].strip(), ""]
    head_ += ["## How to work", play, ""]
    for title, name in (("## Project rules", "00 Rules.md"), ("## Conventions", "10 Conventions.md")):
        b = notes.body(name)
        if b:
            head_ += [title, b, ""]
    if lessons:
        head_ += ["## Lessons from earlier attempts (do not repeat these)", lessons, ""]
    done = [f"- `{test_cmd(plan, t)}` prints 0 failed" for t in task["tests"]] + [f"- {x}" for x in task["done_when"]]
    others = sorted(set(green) - set(task["tests"]))
    if others:
        done.append("- these still pass (they pass now): " + ", ".join(f"`{test_cmd(plan, t)}`" for t in others))
    exist = lambda f: "exists" if (Path(ws) / f).exists() else "NEW - create it"  # noqa: E731
    body = ["## Your task", task["brief"].strip(), "", "## Done when", *done, "",
            "## You may change ONLY these files", *[f"- {f} ({exist(f)})" for f in task["files"]], "",
            "Do not change anything else - not the tests, not other files, no new helper files."]
    if failure:
        body += ["", "## Your previous attempt failed - it has been UNDONE (files are back as shown below)",
                 f"Why: **{failure['gate']}**", "```", failure["detail"].strip()[:2400], "```",
                 "Fix the cause. Do not repeat the same change."]
    tail = ["", "## Before you finish",
            "1. Run each test command above and read its output.",
            "2. Only the listed files are changed.",
            "3. Reply with what you changed and each test command's last line, copied exactly."]
    if opencode:
        if failure:
            body[body.index("## Your previous attempt failed - it has been UNDONE (files are back as shown below)")] = \
                "## Your previous attempt failed - it has been UNDONE (the files are back as they were)"
        read = list(dict.fromkeys(task["tests"] + task["context"]))
        return "\n".join(head_ + body + ["", "## Read these first", *[f"- {f}" for f in read]] + tail)
    fixed = "\n".join(head_ + body + tail)
    room = max(4000, PROMPT_BUDGET - len(fixed))
    shown, listed = [], []
    for rel in list(dict.fromkeys(task["files"] + task["tests"] + task["context"])):
        part = _show(ws, rel, min(FILE_CAP, room), rel in task["files"])
        if len(part) <= room:
            shown.append(part)
            room -= len(part)
        else:
            listed.append(rel)
    files = ["", "## Files (as they are now)", *shown]
    if listed:
        files.append("Not shown (no room) - read them with read_file: " + ", ".join(listed))
    return "\n".join(head_ + body + files + tail)


# ── ND (the worker) ──────────────────────────────────────────────────────────

class NDWorker:
    """One ND coding turn per attempt, driven like bench.py's run_nd."""

    def __init__(self, url=ND_URL, log=print):
        self.url, self.log = url.rstrip("/"), log

    def post(self, path, payload, timeout=60):
        req = urllib.request.Request(self.url + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def alive(self):
        try:
            self.post("/api/ping", {}, timeout=5)
            return True
        except Exception:
            return False

    def cancel(self, rid):
        for _ in range(36):
            try:
                self.post("/api/chat_cancel", {"job_id": rid}, timeout=10)
                if self.post("/api/chat_result", {"job_id": rid}, timeout=10).get("status") not in ("running", "queued"):
                    return
            except Exception:
                pass
            time.sleep(5)

    def run(self, prompt, workspace, model, minutes, label):
        if not self.alive():
            return {"status": "nd_down", "reply": "", "secs": 0}
        rid = f"bench_fm_{label}_{int(time.time())}"
        self.post("/api/chat", {"model": model, "req_id": rid, "session_id": rid, "workspace": str(workspace),
                                "messages": [{"role": "user", "content": prompt}],
                                "allow_all": False, "approved_tools": []})
        t0, beat, parked, rounds = time.time(), time.time(), None, 0
        while time.time() - t0 < minutes * 60:
            try:
                st = self.post("/api/chat_status", {"req_id": rid, "stream_from": 0}, timeout=30)
                res = self.post("/api/chat_result", {"job_id": rid}, timeout=30)
            except Exception:
                if not self.alive():
                    return {"status": "nd_down", "reply": "", "secs": round(time.time() - t0)}
                time.sleep(5)
                continue
            rounds = max(rounds, st.get("round", 0) or 0)
            if st.get("awaiting_permission") or st.get("awaiting_question"):
                parked = parked or time.time()
                if time.time() - parked > 90:
                    self.cancel(rid)
                    return {"status": "blocked", "secs": round(time.time() - t0),
                            "reply": "ND is waiting for a person (a permission or a question). Set ND's "
                                     "agent autonomy to 'autonomous' for unattended runs."}
            else:
                parked = None
            if res.get("status") not in ("running", "unknown", "queued"):
                return {"status": "done" if res.get("status") in ("done", "ok", "complete", "completed") else res.get("status") or "done",
                        "reply": str(res.get("reply") or res.get("text") or res.get("content") or "")[:4000],
                        "secs": round(time.time() - t0), "rounds": rounds, "model_used": res.get("model")}
            if time.time() - beat >= 120:
                beat = time.time()
                el = int(time.time() - t0)
                self.log(f"      ... {el // 60}m{el % 60:02d}s, round {rounds or 1}, {st.get('stage', '?')}")
            time.sleep(2)
        self.cancel(rid)
        return {"status": "timeout", "reply": "", "secs": round(time.time() - t0), "rounds": rounds}


class OpenCodeWorker:
    """One `opencode run` per attempt (opencode_worker.Run: config, stdin, events, time limit). The
    foreman does the judging, git and undo itself, exactly as for ND - only the worker differs."""

    def __init__(self, log=print, shell=True, think=True):
        self.log, self.shell, self.think = log, shell, think

    def alive(self):
        return True

    def run(self, prompt, workspace, model, minutes, label):
        import opencode_worker as ow
        tag = model[len(OPENCODE):] if is_opencode(model) else model
        ow.write_config(tag, shell=self.shell, think=self.think)
        ow.free_gpu(keep=tag)
        out = Path(workspace) / FM / "opencode" / f"{label}.jsonl"   # .foreman/ is outside git
        out.parent.mkdir(parents=True, exist_ok=True)
        r = ow.Run(workspace, prompt, out, minutes, on_step=lambda m: self.log("    " + m.strip())).go(tag)
        killed = ow.stray_processes(workspace, r.t0)
        reply = r.last_text or ""
        if r.errors:
            reply = "OpenCode error: " + "; ".join(r.errors)[:600] + "\n" + reply
        if killed:
            reply += f"\n(the foreman stopped {len(killed)} process(es) it left running)"
        if r.cut_off:
            reply += f"\n(OpenCode: {r.cut_off} step(s) hit the {ow.OUTPUT}-token output limit and were cut off mid-answer)"
        self.log(f"      OpenCode: {r.steps} steps, {r.edits} edits, context peak {r.peak}, {r.secs}s"
                 + (", TIMED OUT" if r.timed_out else "") + (f", rc {r.rc}" if r.rc else "")
                 + (f", CUT OFF {r.cut_off}x at the output limit" if r.cut_off else ""))
        return {"status": "timeout" if r.timed_out else "done", "reply": reply[:4000], "secs": r.secs,
                "rounds": r.steps, "model_used": model, "cut_off": r.cut_off}


class Workers:
    """Sends each attempt to ND or OpenCode by its model name (OPENCODE prefix)."""

    def __init__(self, nd, oc):
        self.nd, self.oc = nd, oc

    def alive(self):
        return self.nd.alive()

    def run(self, prompt, workspace, model, minutes, label):
        return (self.oc if is_opencode(model) else self.nd).run(prompt, workspace, model, minutes, label)


def unload(model):
    """Free the card before the other model loads (Ollama keeps the last one resident)."""
    model = model[len(OPENCODE):] if is_opencode(model) else model
    try:
        req = urllib.request.Request(OLLAMA_URL + "/api/generate", data=json.dumps({"model": model, "keep_alive": 0}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60).read()
    except Exception:
        pass


def notify(plan, title):
    """A phone alert through ntfy (titles only - nothing from the code)."""
    topic = (plan.get("notify") or {}).get("ntfy_topic")
    if not topic:
        return
    try:
        req = urllib.request.Request("https://ntfy.sh/" + topic, data=title.encode("utf-8"),
                                     headers={"Title": f"Foreman: {plan.get('project')}"}, method="POST")
        urllib.request.urlopen(req, timeout=15).read()
    except Exception:
        pass


# ── state ────────────────────────────────────────────────────────────────────

def fm_dir(plan):
    d = Path(plan["workspace"]) / FM
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_state(plan):
    f = fm_dir(plan) / "state.json"
    st = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    st.setdefault("tasks", {})
    st.setdefault("green", {})
    st.setdefault("events", [])
    for t in plan["tasks"]:
        st["tasks"].setdefault(t["id"], {"status": "pending", "attempts": []})
    return st


def save_state(plan, st):
    f = fm_dir(plan) / "state.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.replace(tmp, f)


class Lock:
    def __init__(self, plan):
        self.f = fm_dir(plan) / "lock"

    def __enter__(self):
        if self.f.exists():
            try:
                pid = int(self.f.read_text().strip() or 0)
            except ValueError:
                pid = 0
            if pid and pid != os.getpid() and _pid_alive(pid):
                raise Blocked(f"another foreman run is going (process {pid}); stop it or delete {self.f}")
        self.f.write_text(str(os.getpid()))
        return self

    def __exit__(self, *a):
        self.f.unlink(missing_ok=True)


def _pid_alive(pid):
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


# ── judging an attempt ───────────────────────────────────────────────────────

def judge(plan, task):
    """-> (verdict "pass"|"fail", gate, detail, results). Nothing here trusts the reply."""
    ws = plan["workspace"]
    ch = changed(ws)
    allowed = set(task["files"])
    outside = [p for p in ch if p not in allowed]
    prot = [p for p in ch if _protected(plan, p)]
    if prot:
        return "fail", "scope", ("You changed protected files: " + ", ".join(prot) +
                                 ". Tests and the plan are how your work is judged - never edit them; fix the code instead."), {}
    if outside:
        return "fail", "scope", ("You changed files this task does not allow: " + ", ".join(outside) +
                                 ". Allowed: " + ", ".join(task["files"]) + ". Put the code in the allowed files; "
                                 "create no helper or scratch files."), {}
    lint_out = lint(plan, ch)
    if lint_out:
        return "fail", "lint", "The code has syntax errors or undefined names:\n" + lint_out, {}
    results = {}
    for t in task["tests"]:
        results[t] = r = run_test(plan, t)
        if not r["ok"]:
            nothing = "" if ch else "Nothing was changed at all.\n"
            return "fail", "tests", f"{nothing}`{t}` does not pass ({r['passed']} passed, {r['failed']} failed):\n{r['tail']}", results
    st_green = load_state(plan)["green"]
    for t, before in sorted(st_green.items()):
        if t in results:
            continue
        results[t] = r = run_test(plan, t)
        lost = lost_labels(before.get("labels", []), r["labels_pass"])
        if not r["ok"] or lost:
            what = (f"these checks passed before and fail now: {', '.join(lost[:12])}" if lost else
                    f"it passed before ({before.get('passed')} passed) and now does not")
            return "fail", "broke", f"Your change broke `{t}` - {what}.\n{r['tail']}", results
    return "pass", "", "", results


# ── the run ──────────────────────────────────────────────────────────────────

def _say(plan, msg, st=None):
    line = f"{datetime.now():%H:%M:%S}  {msg}"
    try:
        print(line, flush=True)
    except Exception:
        print(line.encode("ascii", "replace").decode(), flush=True)
    try:
        with (fm_dir(plan) / "run.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _models(plan, task):
    n = max(1, int(task["attempts"]))
    main = task.get("model") or plan["model"]
    alt = task.get("alt_model") or plan.get("alt_model")
    return [main] * (n - 1) + [alt or main] if n > 1 else [main]


def _skip_dependants(plan, st, tid, why):
    for t in plan["tasks"]:
        if tid in t["depends_on"] and st["tasks"][t["id"]]["status"] == "pending":
            st["tasks"][t["id"]]["status"] = "skipped"
            st["tasks"][t["id"]]["why"] = why
            _skip_dependants(plan, st, t["id"], f"after {t['id']} ({why})")


def run_task(plan, st, task, worker, notes, log):
    ws, tid = plan["workspace"], task["id"]
    ts = st["tasks"][tid]
    if ts.get("status") != "running" or not ts.get("start_sha"):
        ts["start_sha"] = head(ws)
    ts["status"] = "running"
    save_state(plan, st)
    models = _models(plan, task)
    failure = None
    if ts["attempts"]:
        last = ts["attempts"][-1]
        failure = {"gate": last.get("gate"), "detail": last.get("detail", "")} if last.get("gate") else None
    prev_model = None
    while len(ts["attempts"]) < len(models):
        n = len(ts["attempts"]) + 1
        model = models[n - 1]
        undo(ws, ts["start_sha"])
        if prev_model and prev_model != model:
            unload(prev_model)
        prev_model = model
        prompt = build_prompt(plan, task, notes, failure, n, len(models), st["green"].keys(), opencode=is_opencode(model))
        (fm_dir(plan) / "prompts").mkdir(exist_ok=True)
        (fm_dir(plan) / "prompts" / f"{tid}_a{n}.md").write_text(prompt, encoding="utf-8")
        log(f"{tid} attempt {n}/{len(models)} on {model} ({len(prompt)} chars) ...")
        r = worker.run(prompt, ws, model, task["minutes"], f"{tid}_a{n}")
        if r["status"] == "nd_down":
            log("ND is not answering - waiting for it (up to 30 min) ...")
            for _ in range(60):
                time.sleep(30)
                if getattr(worker, "alive", lambda: True)():
                    break
            else:
                raise Blocked("ND stopped answering for 30 minutes")
            continue                                        # not an attempt: nothing was tried
        if r["status"] == "blocked":
            undo(ws, ts["start_sha"])
            raise Blocked(r["reply"])
        swept = sweep_scratch(plan, task)
        if swept:
            log(f"{tid} removed scratch files the task does not list: {', '.join(swept)}")
        verdict, gate, detail, results = judge(plan, task)
        if verdict == "fail" and r["status"] == "timeout":
            detail = f"(you ran out of time: {task['minutes']} min)\n" + detail
        if verdict == "fail" and r.get("cut_off"):
            detail = ("(you were cut off: one reply ran past the output limit before any code was saved - "
                      "think briefly, then write the file, then refine it with edits)\n") + detail
        used = r.get("model_used") or model
        if used != model:
            log(f"{tid} attempt {n} WARNING: asked for {model}, ND ran {used}")
        a = {"n": n, "model": model, "model_used": used, "secs": r.get("secs", 0), "verdict": verdict, "gate": gate, "detail": detail,
             "worker": r["status"], "reply": (r.get("reply") or "")[:1500], "when": f"{datetime.now():%Y-%m-%d %H:%M}"}
        if verdict == "pass":
            git(ws, "add", "-A")
            git(ws, "commit", "-q", "--allow-empty", "-m", f"{tid}: {task['title']} (attempt {n}, {used})")
            a["commit"] = ts["commit"] = head(ws)
            for t, res in results.items():
                st["green"][t] = {"passed": res["passed"], "labels": res["labels_pass"]}
            ts["attempts"].append(a)
            ts["status"] = "passed"
            notes.task_attempt(tid, a)
            save_state(plan, st)
            log(f"{tid} PASSED on attempt {n} ({a['secs']}s) -> {a['commit'][:10]}")
            return "passed"
        ts["attempts"].append(a)
        notes.task_attempt(tid, a)
        notes.add_lesson(tid, n, gate, detail.split("\n")[0] + (" " + detail.split("\n")[1] if "\n" in detail else ""))
        save_state(plan, st)
        log(f"{tid} attempt {n} FAILED - {gate}: {detail.splitlines()[0][:160] if detail else ''}")
        failure = {"gate": gate, "detail": detail}
        undo(ws, ts["start_sha"])
    ts["status"] = "stuck"
    _skip_dependants(plan, st, tid, f"{tid} is stuck")
    save_state(plan, st)
    notify(plan, f"{tid} stuck after {len(ts['attempts'])} attempts")
    log(f"{tid} STUCK after {len(ts['attempts'])} attempts")
    return "stuck"


def run(plan_path, worker=None, only=None, max_hours=None, log=None):
    plan = load_plan(plan_path)
    ws = Path(plan["workspace"])
    log = log or (lambda m: _say(plan, m))
    worker = worker or Workers(NDWorker(plan["nd_url"], log), OpenCodeWorker(log, shell=plan.get("opencode_shell", True),
                                                                        think=plan.get("opencode_think", True)))
    notes = Notes(plan)
    with Lock(plan):
        (ws / FM / "STOP").unlink(missing_ok=True)
        ensure_repo(ws)
        dirt = changed(ws)
        st = load_state(plan)
        if dirt and not any(v["status"] == "running" for v in st["tasks"].values()):
            raise Blocked("the workspace has uncommitted changes (" + ", ".join(dirt[:8]) + ") - commit or undo them first")
        if st.get("plan_hash") and st["plan_hash"] != plan_hash(plan):
            log("note: the plan changed since the last run - finished tasks stay finished")
        st["plan_hash"] = plan_hash(plan)
        st.setdefault("base", head(ws))
        st.setdefault("started", f"{datetime.now():%Y-%m-%d %H:%M}")
        notes.ensure()
        if not st["green"]:                                  # tests already passing at the start (rare)
            for t in plan.get("baseline_tests") or []:
                r = run_test(plan, _rel(t))
                if r["ok"]:
                    st["green"][_rel(t)] = {"passed": r["passed"], "labels": r["labels_pass"]}
        st["phase"] = "running"
        save_state(plan, st)
        notes.write_index(st, report(plan, st))
        notify(plan, "started")
        deadline = time.time() + max_hours * 3600 if max_hours else None
        log(f"Foreman: {plan.get('project')} - {len(plan['tasks'])} tasks, model {plan['model']}")
        try:
            while True:
                if (ws / FM / "STOP").exists():
                    st["phase"] = "stopped (STOP file)"
                    log("STOP file found - stopping between tasks")
                    break
                if deadline and time.time() > deadline:
                    st["phase"] = "stopped (time limit)"
                    log("time limit reached - stopping between tasks")
                    break
                nxt = None
                for t in order(plan):
                    s = st["tasks"][t["id"]]["status"]
                    if only and t["id"] not in only:
                        continue
                    if s in ("pending", "running") and all(st["tasks"][d]["status"] == "passed" for d in t["depends_on"]):
                        nxt = t
                        break
                if not nxt:
                    st["phase"] = "finished"
                    break
                run_task(plan, st, nxt, worker, notes, log)
                notes.write_index(st, report(plan, st))
        except Blocked as e:
            st["phase"] = f"paused: {e}"
            log(f"PAUSED - {e}")
            notify(plan, "paused - needs you")
        finally:
            save_state(plan, st)
            rep = report(plan, st)
            (ws / FM / "REPORT.md").write_text(rep, encoding="utf-8")
            notes.write_index(st, rep)
        c = counts(st)
        if st["phase"] == "finished":
            notify(plan, f"finished: {c['passed']}/{len(plan['tasks'])} passed, {c['stuck']} stuck")
        log(f"{st['phase']} - passed {c['passed']}, stuck {c['stuck']}, skipped {c['skipped']}, "
            f"left {c['pending'] + c['running']}")
        return st


def counts(st):
    c = {k: 0 for k in ("passed", "stuck", "skipped", "pending", "running")}
    for v in st["tasks"].values():
        c[v["status"]] = c.get(v["status"], 0) + 1
    return c


# ── report ───────────────────────────────────────────────────────────────────

def report(plan, st):
    c = counts(st)
    tasks = order(plan)
    first = sum(1 for t in tasks if st["tasks"][t["id"]]["status"] == "passed" and len(st["tasks"][t["id"]]["attempts"]) == 1)
    secs = sum(a.get("secs", 0) for v in st["tasks"].values() for a in v["attempts"])
    out = [f"# Foreman report - {plan.get('project')}", "",
           f"Run: **{st.get('phase', '?')}** - started {st.get('started', '?')}, updated {datetime.now():%Y-%m-%d %H:%M}  ",
           f"Model: `{plan['model']}`" + (f", last try `{plan['alt_model']}`" if plan.get("alt_model") else ""), "",
           f"**{c['passed']} of {len(tasks)} passed** ({first} on the first try) - {c['stuck']} stuck - "
           f"{c['skipped']} skipped - {c['pending'] + c['running']} not reached. ND worked {secs / 3600:.1f} h.", "",
           "| Task | Title | Status | Attempts | Minutes | Passed on |", "|---|---|---|---|---|---|"]
    for t in tasks:
        v = st["tasks"][t["id"]]
        ok = next((a for a in v["attempts"] if a["verdict"] == "pass"), None)
        out.append(f"| {t['id']} | {t['title']} | {v['status']} | {len(v['attempts'])} | "
                   f"{round(sum(a.get('secs', 0) for a in v['attempts']) / 60)} | {ok['model'] if ok else ''} |")
    stuck = [t for t in tasks if st["tasks"][t["id"]]["status"] == "stuck"]
    if stuck:
        out += ["", "## Stuck - hand these to the planner", ""]
        for t in stuck:
            v = st["tasks"][t["id"]]
            last = v["attempts"][-1]
            out += [f"### {t['id']} - {t['title']}", f"Files: {', '.join(t['files'])} - tests: {', '.join(t['tests'])}",
                    "", "Gates that failed, by attempt: " + ", ".join(f"{a['n']}: {a['gate']}" for a in v["attempts"]), "",
                    "Last failure:", "```", (last.get("detail") or "")[:2000], "```",
                    f"Prompts: `{FM}/prompts/{t['id']}_a*.md` - ND's last reply:", "",
                    "> " + (last.get("reply") or "(none)")[:800].replace("\n", "\n> "), ""]
    skipped = [t for t in tasks if st["tasks"][t["id"]]["status"] == "skipped"]
    if skipped:
        out += ["", "## Skipped (waiting on a stuck task)", ""] + [f"- {t['id']} {t['title']} - {st['tasks'][t['id']].get('why', '')}" for t in skipped]
    gates = {}
    for v in st["tasks"].values():
        for a in v["attempts"]:
            if a.get("gate"):
                gates[a["gate"]] = gates.get(a["gate"], 0) + 1
    if gates:
        out += ["", "## Why attempts failed", ""] + [f"- {g}: {n}" for g, n in sorted(gates.items(), key=lambda x: -x[1])]
    return "\n".join(out) + "\n"


# ── check: validate the plan and test the tests ──────────────────────────────

def check(plan_path, reference=None, log=print):
    """Before a long run: the plan is sound, every task's tests FAIL on the project as it is,
    and (with --reference) every test PASSES on the planner's reference solution."""
    plan = load_plan(plan_path)
    ok = True
    log(f"plan: {len(plan['tasks'])} tasks, order " + " > ".join(t["id"] for t in order(plan)))
    for t in order(plan):
        for f in t["tests"]:
            r = run_test(plan, f, timeout=120)
            if r["ok"] and not t.get("passes_before"):
                ok = False
                log(f"  PROBLEM {t['id']}: {f} already passes on the unbuilt project - it cannot judge the task")
    if reference:
        ref = Path(reference)
        with tempfile.TemporaryDirectory() as d:
            dst = Path(d) / "ws"
            shutil.copytree(plan["workspace"], dst, ignore=shutil.ignore_patterns(".git", FM, ".venv", "__pycache__"))
            for f in ref.rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts:
                    tgt = dst / f.relative_to(ref)
                    tgt.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, tgt)
            p2 = dict(plan, workspace=str(dst))
            if not plan.get("python") and (Path(plan["workspace"]) / ".venv").exists():
                p2["python"] = project_python(plan)
            for t in order(plan):
                for f in t["tests"]:
                    r = run_test(p2, f, timeout=300)
                    if not r["ok"]:
                        ok = False
                        log(f"  PROBLEM {t['id']}: {f} fails on the reference solution:\n    "
                            + r["tail"][:600].replace("\n", "\n    "))
                    else:
                        log(f"  ok {t['id']}: {f} passes on the reference ({r['passed']} checks)")
    models = {plan["model"], plan.get("alt_model")} | {t.get(k) for t in plan["tasks"] for k in ("model", "alt_model")}
    models -= {None, ""}
    if any(not is_opencode(m) for m in models):             # only ND-run models need ND up
        w = NDWorker(plan["nd_url"])
        log("ND: " + ("answering" if w.alive() else "NOT answering (start it before the run)"))
    if any(is_opencode(m) for m in models):
        try:
            import opencode_worker
            log(f"OpenCode: {opencode_worker.opencode_exe()}"
                + ("" if plan.get("opencode_shell", True) else " (shell OFF: it cannot run the tests itself)"))
        except SystemExit as e:
            log(f"OpenCode: NOT FOUND - {e}")
            ok = False
    for m in models:
        tag = m[len(OPENCODE):] if is_opencode(m) else m
        try:
            tags = json.loads(urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=10).read())["models"]
            have = any(x["name"] == tag or x["name"] == tag + ":latest" for x in tags)
            log(f"model {m}: " + ("installed" if have else "NOT INSTALLED"))
            ok = ok and have
        except Exception:
            log("Ollama: not answering")
    log("READY" if ok else "NOT READY - fix the problems above")
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "run", "status", "report", "notes", "retry"])
    ap.add_argument("plan")
    ap.add_argument("task", nargs="?")
    ap.add_argument("--reference")
    ap.add_argument("--only", help="comma-separated task ids")
    ap.add_argument("--max-hours", type=float)
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        if a.cmd == "check":
            return 0 if check(a.plan, a.reference) else 1
        plan = load_plan(a.plan)
        if a.cmd == "run":
            st = run(a.plan, only=set(a.only.split(",")) if a.only else None, max_hours=a.max_hours)
            return 0 if st["phase"] == "finished" else 2
        st = load_state(plan)
        if a.cmd == "notes":
            Notes(plan).ensure()
            Notes(plan).write_index(st, report(plan, st))
            print(Notes(plan).dir)
        elif a.cmd == "retry":
            if not a.task or a.task not in st["tasks"]:
                print("retry needs a task id")
                return 1
            todo = [a.task]
            while todo:
                tid = todo.pop()
                st["tasks"][tid].update(status="pending", attempts=[], start_sha=None)
                st["tasks"][tid].pop("why", None)
                # a reset task's own tests are no longer owed: keeping them in "green" makes every
                # other task's attempt fail the broke gate on checks only this task can fix
                for t in next(x for x in plan["tasks"] if x["id"] == tid)["tests"]:
                    st["green"].pop(_rel(t), None)
                    st["green"].pop(t, None)
                todo += [t["id"] for t in plan["tasks"] if tid in t["depends_on"] and st["tasks"][t["id"]]["status"] == "skipped"]
            save_state(plan, st)
            print(f"{a.task} is pending again")
        elif a.cmd == "report":
            print(report(plan, st))
        else:
            c = counts(st)
            print(f"{plan.get('project')}: {st.get('phase', 'not started')} - " + ", ".join(f"{k} {v}" for k, v in c.items() if v))
            for t in order(plan):
                v = st["tasks"][t["id"]]
                print(f"  {t['id']:6} {v['status']:8} {len(v['attempts'])} att  {t['title']}")
        return 0
    except (ValueError, Blocked, RuntimeError) as e:
        print(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
