"""The blind planner trial: how far is "fully local"?

Today a cloud model (Claude) writes every plan and every test; the local model only builds. This trial hands the
local model the planner's job too, and grades the result with tests it has never seen:

    1. stage   a workspace with the app as it is, SPEC.md and the test helpers. No plan, no tests, no notes, no
               reference build from the pack: nothing the cloud planner wrote except the spec.
    2. plan    the local model writes plan.json from the spec and the app's source.
    3. tests   the local model writes one test file per task.
    4. check   mechanical: the plan is well formed, every test runs and FAILS on the app as it is.
    5. build   the usual unattended build (studio_pack.py build), from the local plan and the local tests.
    6. grade   the pack's own tests - hidden until now - are run on what was built. That is the score.
               The local tests are graded too: do they pass on the pack's reference build, and fail on the old app?

    python dev/studio_blind.py stage <pack> <workspace>
    python dev/studio_blind.py plan  <workspace> [--model q36c-nd64k] [--no-think]     (a model call: YOU run it)
    python dev/studio_blind.py tests <workspace> [--model q36c-nd64k] [T02]            (model calls: YOU run it)
    python dev/studio_blind.py check <workspace>
    python dev/studio_blind.py grade <workspace>
--dry on plan/tests writes the prompt to .studio/ and calls no model.

THE PLAN-ONLY TRIAL (stage A of the handover, added 2026-11-14 after two full trials died on the local tests):
    python dev/studio_blind.py stage <pack> <workspace> --plan-only
The workspace also gets the pack's own tests. The local model writes only the plan: one task per test file, told
each file's name and the plain-words labels of its checks, never its code. There is no `tests` step; instead `briefs <workspace>` (model calls: YOU run it) rewrites each task's short brief
into a detailed one: parts in order, the deciding algorithms written out, a table from every check to the part that
satisfies it. The build is
judged by the same tests a cloud-planned build is judged by, so `grade` (and the replay bench) compare like with like:
what changes is who wrote the briefs.

Read the grade with its limits: the hidden tests check ids, names and strings the cloud plan chose. The spec has to
carry every such name, or a correct build fails the grade for a name it could not know. `grade` reports that as
"contract misses" where it can tell (a check that fails with "is not there" or "exists").
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "dev"))
sys.path.insert(0, str(REPO / "shared"))
import studio_pack as P  # noqa: E402

TEXT = {".js", ".mjs", ".ts", ".py", ".html", ".htm", ".css", ".json", ".md", ".java", ".xml", ".txt", ".yml", ".yaml", ".toml", ".bat", ".ps1"}
SKIP_DIRS = {"node_modules", ".git", ".venv", "__pycache__", "vendor", ".foreman", ".studio", "tests", "build", "out", "signing"}
OUTLINE = re.compile(r"^\s*(export\s+)?(async\s+)?(function\s+\w+|class\s+\w+|def\s+\w+|const\s+\w+\s*=\s*(async\s*)?\(|app\.(get|post|put|delete)\(|"
                     r"fastify\.(get|post|put|delete)\()|\bid=\"[\w-]+\"")

PLAN = """You are the planner of Philibert Code, a local coding assistant. An app ALREADY EXISTS and works. A change to it \
is described in the SPEC below. Turn the spec into a build plan for a careful but literal programmer (a local AI model). \
The programmer sees ONE task at a time, with its brief, the files it may change and its test. It knows nothing you do \
not write in the brief.

KIND OF APP: {kind}
{kind_rules}

THE APP'S FILES (path, lines):
{tree}

SOURCE (small files whole; for a big file only its outline: functions and element ids, with line numbers):
{source}

THE SPEC:
{spec}

TEST HELPERS that already exist in tests/ (the tests you plan will import them; you write the tests in the next step):
{helpers}

Write the plan as ONE JSON object and nothing else:
{{
 "project": "...", "goal": "two or three sentences: what exists, what changes, what must not change",
 "rules": ["rules that hold for every task: what must never change, exact names that are fixed, ..."],
 "conventions": ["code style of THIS app as seen in its source", "how to run a task's test: .venv\\\\Scripts\\\\python.exe tests\\\\<file>.py"],
 "tasks": [
  {{"id": "T01", "title": "...", "depends_on": [], "files": ["every file this task may create or change"],
    "tests": "tests/test_<what>.py", "minutes": 40,
    "brief": "Everything the programmer needs: what exists now (exact file, function names, ids), what to add or change, \
exact names, ids and strings from the spec, the order to do it in, and what NOT to touch. Long is fine; vague is not."}}
 ]
}}

Rules for the plan:
- 2 to 5 tasks. Each task leaves the app working. A later task builds on an earlier one (depends_on).
- A task is a SLICE OF THE APP'S OWN CODE that one programmer finishes in about 40 minutes: the first task makes the smallest thing that works (the new file exists, is loaded, its entry points exist); each later task adds one group of behaviours from the spec. Never put the whole spec into one task.
- EVERY task changes the app: its "files" names at least one file that is NOT under tests/. A task with an empty "files" list is refused and the whole plan with it.
- NEVER make a task whose job is to write, extend or run tests. The tests are written by the test writer in the next step, one file per task; the programmer never writes them.
- Use only ids, class names and function names you can SEE in the source outline above or in the spec. Do not guess an id; if you need one that does not exist, the brief says to add it and under which name.
- Where the spec does not fix a detail (a class name, the exact text of a tag), do not present your choice as a requirement: say "for example" so the test writer does not demand that exact spelling.
- Prefer a NEW file the programmer owns over scattered edits in a big existing file; a big file gets the smallest edit.
- Never list a file under tests/ in "files". One test file per task; give each a different name.
- Every exact name the spec gives (file names, function names, ids, class names, strings) must appear in a brief, \
spelled exactly as in the spec.
- Do not invent features the spec does not ask for.
"""

TESTS = """You are the test writer of Philibert Code. Write the test file {test} for ONE task of a plan. The programmer's \
work on this task is judged by this file alone, so it must check what the task and the spec ask for, and it must be \
able to pass.

THE SPEC:
{spec}

THE PLAN (titles only):
{summary}

THE TASK THIS FILE JUDGES:
{task}

THE HELPERS (tests/_t.py and friends; import from them, never copy or change them):
{helpers}

THE APP'S SOURCE (outline, as the planner saw it):
{source}

Rules for the file:
- It is a plain script run as: python {test}  (the working folder is the project). No pytest.
- Every check goes through the helpers' check(label, ok, got) and the file ends with finish(), which prints \
"N passed, M failed" and sets the exit code. A label says what a user would see or what must hold, in plain words.
- It must FAIL on the app as it is today (the task is not done yet) and PASS once the task is done as briefed. Start \
with a check that the new file, function or id exists, and stop early (finish()) when it does not.
- Check behaviour through the real app (start it with the helpers, drive the real page or call the real endpoint), \
not by reading the source for a string, except for "this exact line is in this file" facts the brief fixes.
- Never sleep for a fixed time to wait for the app: use the helpers' wait functions.
- At least 10 checks. Close everything you start (browser, server), also when a check fails.
- CHECK ONLY WHAT THE SPEC STATES. A second programmer who built the spec correctly, without reading this brief, must also pass. So never demand an exact spelling the spec does not give (the text of a script tag, a class name, a private helper's name, an exact return value): check the BEHAVIOUR instead (the file is served by the app, the function exists, the focus moved to another element, the drawer closed). A check that a correct build can fail is worse than no check: it blocks the programmer for good.
- Use only helper functions that are listed above, with the arguments shown there. Use only ids and selectors you can see in the source outline or the spec.
Reply with the complete file in one ```python block and nothing else.
"""


def opt(a, name, default=None):
    return P.opt(a, name, default)


def text_files(folder):
    out = []
    for f in sorted(Path(folder).rglob("*")):
        rel = f.relative_to(folder)
        if not f.is_file() or f.suffix.lower() not in TEXT or SKIP_DIRS & set(rel.parts[:-1]) or f.name in ("package-lock.json", "opencode.json"):
            continue
        try:
            out.append((rel.as_posix(), f.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            pass
    return out


def source_view(folder, budget=70_000, whole=9_000):
    """What the planner reads: the file list, small files whole, big files as an outline. -> (tree, source)."""
    files = text_files(folder)
    tree = "\n".join(f"  {rel}  ({len(t.splitlines())} lines)" for rel, t in files) or "  (no files yet: a new app)"
    parts, used = [], 0
    for rel, t in sorted(files, key=lambda x: len(x[1])):
        if rel in ("SPEC.md", "plan.json") or rel.endswith(".md"):
            continue
        if len(t) <= whole and used + len(t) < budget:
            body = t
        else:
            lines = [f"{i:5}: {ln.strip()[:150]}" for i, ln in enumerate(t.splitlines(), 1) if OUTLINE.search(ln)]
            body = "(outline only)\n" + "\n".join(lines[:260])
            if used + len(body) > budget:
                body = "(outline only, cut)\n" + "\n".join(lines[:60])
        used += len(body)
        parts.append(f"--- {rel} ---\n{body}")
    return tree, "\n\n".join(parts)


def helpers_view(ws, full=False):
    out = []
    for f in sorted((Path(ws) / "tests").glob("_*.py")):
        t = f.read_text(encoding="utf-8")
        if full:
            out.append(f"--- tests/{f.name} ---\n{t}")
        else:                                                  # the planner needs the interface, not the bodies
            keep = [ln for ln in t.splitlines() if re.match(r"\s*(def |class )", ln) or re.match(r"[A-Z_]+ = ", ln)]
            out.append(f"--- tests/{f.name} (interface) ---\n" + (t.split('"""')[1].strip() + "\n" if t.startswith('"""') else "") + "\n".join(keep))
    return "\n\n".join(out) or "(none: write plain scripts that print PASS/FAIL lines and 'N passed, M failed')"


def stage(pack, ws, plan_only=False):
    d, m = P.load(pack)
    ws = Path(ws)
    if ws.exists():
        sys.exit(f"{ws} already exists")
    import studio_overnight as Q
    P.lay_base(m, ws)
    shutil.copy(d / "SPEC.md", ws / "SPEC.md")
    (ws / "tests").mkdir(exist_ok=True)
    gets = m.get("planner_gets")
    if gets is None:
        gets = [f"tests/{f.name}" for f in sorted((d / "tests").glob("_*.py")) if f.name != "_look.py"]
    for rel in gets:
        shutil.copy(d / rel, ws / rel)
    if plan_only:                                             # the pack's tests judge the build; the planner sees their labels only
        for f in sorted((d / "tests").glob("*.py")):
            if f.name != "_look.py":
                shutil.copy(f, ws / "tests" / f.name)
    for n in (".gitignore", ".gitattributes"):
        if (d / n).is_file():
            shutil.copy(d / n, ws / n)
    (ws / ".studio").mkdir()
    (ws / ".studio" / "pack.json").write_text(json.dumps({**m, "pack_dir": str(d), "blind": True, "plan_only": bool(plan_only), "planner_got": gets,
                                                         "laid_out": time.strftime("%Y-%m-%d %H:%M")}, indent=1), encoding="utf-8")
    (ws / "opencode.json").write_text(json.dumps(Q.OPENCODE_PROJECT, indent=1), encoding="utf-8")
    gi = ws / ".gitignore"
    have = gi.read_text(encoding="utf-8") if gi.exists() else ""
    gi.write_text(have.rstrip() + "".join(f"\n{x}" for x in (".venv/", ".foreman/", "__pycache__/", "*.pyc", ".nd_backups/") if x not in have) + "\n",
                  encoding="utf-8")
    P.git(ws, "init", "-q")
    P.journal(ws, "studio_blind", f"blind trial staged from pack {m['name']}: the app, the spec and {len(gets)} helper file(s); "
              + ("no plan; the pack's own tests (plan-only trial)" if plan_only else "no plan, no tests"))
    P.git(ws, "add", "-A")
    P.git(ws, "commit", "-q", "-m", f"{m['title']}: blind planner trial, nothing planned yet")
    subprocess.run([P.BASE_PY, "-m", "venv", ".venv"], cwd=str(ws), check=True)
    for pkg in (m.get("python") or {}).get("pip") or []:
        subprocess.run([str(ws / ".venv" / "Scripts" / "python.exe"), "-m", "pip", "install", "-q", pkg], cwd=str(ws), capture_output=True)
    me = f'"{sys.executable}" "{Path(__file__).resolve()}"'
    print(f"staged: {ws}" + (" (plan-only: the pack's tests judge the build)" if plan_only else "")
          + f"\nnext (you run these; they call the local model):\n  {me} plan \"{ws}\"\n"
          + (f"  {me} briefs \"{ws}\"\n" if plan_only else f"  {me} tests \"{ws}\"\n") + f"  {me} check \"{ws}\"\n"
          f"  \"{sys.executable}\" \"{Path(P.__file__).resolve()}\" build \"{ws}\"\n  {me} grade \"{ws}\"")


CALL_LIMIT = 3 * 3600      # seconds one model call may take
MAX_TOKENS = 32000         # call_model's cap on tokens out (thinking included)
RETRY_NOTE = ("\n\nNOTE: your last answer to this spent its whole budget thinking and wrote nothing. Think for a few "
              "thousand tokens at most, decide, and then write the answer itself. A plain answer that follows the "
              "rules beats a perfect one that is never written.")


def call(ws, stage_name, prompt, model, think, dry):
    sd = Path(ws) / ".studio"
    (sd / f"{stage_name}.prompt.txt").write_text(prompt, encoding="utf-8")
    if dry:
        print(f"  {stage_name}: prompt written ({len(prompt)} chars), no model called (--dry)")
        return None
    import nd_studio as S
    print(f"[{time.strftime('%H:%M:%S')}] {stage_name}: asking {model} ({len(prompt)} chars) ...", flush=True)
    t0 = time.time()
    try:                                                      # blind2 lost two test files to the default 1-hour limit
        text, secs, info = S.call_model(model, prompt, think=think, timeout=CALL_LIMIT)
        (sd / f"{stage_name}.thinking.txt").write_text(S.LAST_THINKING, encoding="utf-8")
        if not S.strip_think(text).strip() and (info.get("eval_count") or 0) >= MAX_TOKENS:
            # blind5 (2026-11-15): the planner thought for all 32,000 tokens (84K characters) and wrote nothing. One more
            # try, told so; its first thinking is kept beside the reply to see whether it went round in circles.
            (sd / f"{stage_name}.thinking1.txt").write_text(S.LAST_THINKING, encoding="utf-8")
            print(f"  {stage_name}: it thought for all {info.get('eval_count')} tokens ({secs} s) and wrote nothing. "
                  "Asking once more, told to keep its thinking short.", flush=True)
            with open(sd / "log.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"stage": stage_name, "model": model, "seconds": secs, **info, "empty": True,
                                    "at": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
            text, secs, info = S.call_model(model, prompt + RETRY_NOTE, think=think, timeout=CALL_LIMIT)
            (sd / f"{stage_name}.thinking.txt").write_text(S.LAST_THINKING, encoding="utf-8")
            if not S.strip_think(text).strip():
                print(f"  {stage_name}: NO ANSWER again: {info.get('eval_count')} tokens, all thinking. Its thinking is in "
                      f"{sd / (stage_name + '.thinking.txt')}", flush=True)
    except Exception as e:
        why = f"{type(e).__name__}: {e}"[:300]
        mins = round((time.time() - t0) / 60)
        print(f"  {stage_name}: NO ANSWER after {mins} min ({why})", flush=True)
        with open(sd / "log.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"stage": stage_name, "model": model, "failed": why, "minutes": mins, "at": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
        P.journal(ws, "studio_blind", f"{stage_name}: no answer from {model} after {mins} min ({why})")
        return None
    (sd / f"{stage_name}.reply.txt").write_text(text, encoding="utf-8")
    with open(sd / "log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"stage": stage_name, "model": model, "seconds": secs, **info, "at": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
    rate = (info.get("eval_count") or 0) / secs if secs else 0
    print(f"  {secs} s, {info.get('eval_count')} tokens out, {rate:.1f} tokens a second", flush=True)
    if 0 < rate < 15:
        print(f"  SLOW: this model gives about 50 tokens a second on a free machine. At {rate:.1f} something else is using the\n"
              "  graphics card or the model does not fit on it (check `ollama ps`: it should say 100% GPU).", flush=True)
    return text


def kind_rules(m):
    src = json.loads((P.PACKS / "BUILDER_RULES.json").read_text(encoding="utf-8"))
    return "\n".join(f"- {r}" for r in (src.get("kinds") or {}).get(m.get("kind"), []))


def own(task):
    """A task's own test file (the first; the rest of a list are older tests it must keep passing)."""
    ts = task.get("tests")
    return (ts[0] if ts else None) if isinstance(ts, list) else ts


def acceptance(ws, m):
    """Plan-only trial: -> (the new test files in the pack's order, the guard files, the text the planner is shown:
    each file's name and the labels of its checks, in plain words; never the code)."""
    d = Path(m["pack_dir"])
    guards = [g for g in m.get("guard_tests") or []]
    files = [x for x in P.tests_of(d) if x not in guards]
    out = []
    for n, name in enumerate(files, 1):
        src = (Path(ws) / name).read_text(encoding="utf-8", errors="replace")
        labels = []
        for lab in re.findall(r"""check\(\s*f?(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""", src):
            lab = (lab[0] or lab[1]).replace('\\"', '"').replace("\\'", "'")
            if lab not in labels:
                labels.append(lab)
        out.append(f"TEST FILE {n}: {name}   ({len(labels)} checks)\n" + "\n".join("   - " + x for x in labels))
    text = "\n\n".join(out)
    if guards:
        text += ("\n\nOLDER TESTS THAT ALREADY PASS AND MUST KEEP PASSING after every task (do not plan a task for them): "
                 + ", ".join(guards))
    return files, guards, text


PLAN_ONLY = """
THE TESTS ALREADY EXIST. You do not write tests and you do not see their code. Each task of your plan is judged by ONE
of the test files below, as it is. For each file you are given the label of every check in it, in the order they run.
A label is what must be true for the check to pass; together they are the exact acceptance list of that task.

{acceptance}

Extra rules because the tests exist:
- EXACTLY {n} tasks, one per test file, in the order given: T01 is judged by test file 1, T02 by test file 2, and so \
on. Each task's "tests" is that file's name, spelled exactly.
- A task's brief must make EVERY label of its file come true, and must not need anything a LATER file checks. Read \
the labels as the specification of the task: where a label gives an exact name, text or number, the brief repeats it.
- After each task the older tests and every earlier test file still pass.
"""


def plan(ws, model, think, dry):
    ws = Path(ws)
    m = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8"))
    tree, source = source_view(ws)
    accept_files = None
    if m.get("plan_only"):
        accept_files, _, acc = acceptance(ws, m)
    prompt = PLAN.format(kind=m.get("kind"), kind_rules=kind_rules(m), tree=tree, source=source,
                         spec=(ws / "SPEC.md").read_text(encoding="utf-8"), helpers=helpers_view(ws))
    if accept_files is not None:
        prompt += PLAN_ONLY.format(acceptance=acc, n=len(accept_files))
    text = call(ws, "blind_plan", prompt, model, think, dry)
    if text is None:
        return
    import nd_studio as S
    try:
        pl = S.extract_json(text)
    except ValueError:
        print(f"  NO PLAN: the reply holds no JSON (it is in {Path(ws) / '.studio' / 'blind_plan.reply.txt'}). Nothing was "
              "written; run `plan` again.", flush=True)
        P.journal(ws, "studio_blind", f"plan by {model}: no JSON in the reply, nothing written")
        return 1
    for t in pl.get("tasks") or []:
        t["files"] = [x for x in t.get("files") or [] if not str(x).replace("\\", "/").startswith("tests/")]
    empty = [t.get("id") for t in pl.get("tasks") or [] if not t["files"]]
    if empty:                                                # a "write the tests" task: not the builder's job, and the foreman refuses it
        print(f"  dropped {', '.join(map(str, empty))}: no app file to change (the planner made a task out of testing)")
        P.journal(ws, "studio_blind", f"plan by {model}: dropped task(s) {', '.join(map(str, empty))} that change no app file")
        pl["tasks"] = [t for t in pl["tasks"] if t.get("id") not in empty]
        for t in pl["tasks"]:
            t["depends_on"] = [d for d in t.get("depends_on") or [] if d not in empty]
        pl["dropped_tasks"] = empty
    if accept_files is not None:                              # one task per test file, in order: by name, else by position
        tasks = pl.get("tasks") or []
        named = [str(t.get("tests") if not isinstance(t.get("tests"), list) else (t["tests"] or [""])[0]).replace("\\", "/") for t in tasks]
        if sorted(named) != sorted(accept_files):
            if len(tasks) == len(accept_files):
                print("  the plan's test names did not match the pack's files: set by position")
                for t, name in zip(tasks, accept_files):
                    t["tests"] = name
            else:
                pl["plan_only_problem"] = f"the plan has {len(tasks)} task(s) for {len(accept_files)} test file(s)"
                print(f"  NOT USABLE: {pl['plan_only_problem']} (run `plan` again)")
    for t in pl.get("tasks") or []:
        if isinstance(t.get("tests"), list):
            t["tests"] = t["tests"][0] if t["tests"] else None
        t["tests"] = t.get("tests") or f"tests/test_{str(t.get('id', 'tx')).lower()}.py"
        t.setdefault("depends_on", [])
        t["context"] = [t["tests"]]
        t["done_when"] = [f"{t['tests']} prints 0 failed"]
    if accept_files is not None and pl.get("tasks") and not pl.get("plan_only_problem"):
        guards = [g for g in m.get("guard_tests") or [] if (ws / g).is_file()]
        if guards:
            first = pl["tasks"][0]
            first["tests"] = [first["tests"], *guards]
            first["done_when"] = [f"{x} prints 0 failed" for x in first["tests"]]
    pl.update({"workspace": ".", "model": "opencode/q36c-nd128k", "opencode_think": False, "alt_model": None,
               "defaults": {"attempts": 3, "minutes": 40}, "planned_by": model})
    (ws / "plan.json").write_text(json.dumps(pl, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    P.builder_rules(ws, m)
    for t in pl.get("tasks") or []:
        print(f"  {t.get('id')} {t.get('title')}: {', '.join(t.get('files') or [])} -> {own(t)} ({len(t.get('brief') or '')} chars)")
    P.journal(ws, "studio_blind", f"plan written by {model}: {len(pl.get('tasks') or [])} task(s)")
    P.git(ws, "add", "-A")
    P.git(ws, "commit", "-q", "-m", f"blind trial: the plan, by {model}")


BRIEF = """You are the planner of Philibert Code. A plan exists. Its briefs are too short: the programmer (a careful \
but literal local AI model) sees ONE task at a time, knows nothing you do not write, has about 40 minutes, and starts \
from nothing again if it fails. A brief that only says WHAT must be true leaves the programmer to invent HOW, and it \
runs out of time. Rewrite the brief of ONE task so that the programmer can type it in.

THE SPEC:
{spec}

THE PLAN (every task, short):
{summary}

THE TASK TO REWRITE:
{task}

WHAT JUDGES IT (the label of every check, in the order they run; all must come true):
{labels}

WHAT MUST KEEP PASSING (the checks of the earlier tasks, already true when this task starts; code this task replaces \
or adds must leave every one of them true):
{kept}

BRIEFS ALREADY REWRITTEN for earlier tasks (this task builds on that code; reuse its names, never redefine them):
{earlier}

THE APP'S SOURCE (outline, with line numbers):
{source}

Write the new brief as plain text (no JSON, no code fence around the whole thing). It must have these parts, in order:
A. One paragraph: what exists, what this task adds, and what is left for LATER tasks (so the programmer does not \
write it now).
B. For every file the task may change: the exact change. For an existing big file: the exact line to find and the \
exact line to add, and "read nothing else in it". For a new file: its outer shape (for a browser script: one \
function wrapping everything, plain var and function, no modules). NEVER give a new function the name of one the \
app already has (look in THE APP'S SOURCE): a second `function isTvBrowser()` replaces the page's own, and whatever \
relied on it breaks. Where the spec says "the page's own X", CALL X; do not write it. OK is the Enter key, and a \
focused button or link ALREADY clicks itself on Enter: code that calls .click() on Enter must call e.preventDefault() \
first, or every OK fires twice (Sign in asked for two pins and broke). Every id and class your code looks up must be \
one THE APP'S SOURCE really has, or one this task or an earlier one creates: never a likely-sounding name (the guide's \
logos are `.logo-tile`; a brief that said `.channel-logo` found nothing and its checks failed). Code that replaces \
or wraps an earlier task's must keep doing everything WHAT MUST KEEP PASSING needs: at the edge of a new walk, hand \
the key on to the old behaviour, never just `return` (blind6: a guide walk that stopped at the top row trapped the \
highlight in the guide and broke ten checks of the task before).
C. The code in numbered parts, in the order to write them. For each part: the function's name, what it takes and \
returns, and its rules as precisely as you can state them: which elements (by the ids and classes you can SEE in \
the outline), which conditions, which order of checks. Where the choice of an algorithm decides whether the checks \
pass (for example: which element is "nearest" in a direction, what counts as hidden, what is in or out of reach while \
something is open), WRITE THE FUNCTION OUT in code, complete, 10 to 40 lines, and say "use exactly this".
D. A table "check -> part": every label from the list above, and the part of C that makes it come true. A label with \
no part means the brief is not finished: add the part.
E. "Do not": the things this task must leave alone.
F. "When a check fails": two or three hints on how to find the cause (what to print, which element to look at).
Aim for 4,000 to 8,000 characters. Exact names beat prose. Never name an id, class or function that is neither in \
the outline, the spec, nor defined by a brief.
"""


def check_labels(src):
    """The label of every check(...) in a test file, in order, once each."""
    labels = []
    for lab in re.findall(r"""check\(\s*f?(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""", src):
        lab = (lab[0] or lab[1]).replace('\\"', '"').replace("\\'", "'")
        if lab not in labels:
            labels.append(lab)
    return labels


def briefs(ws, model, think, dry, only=None):
    """Plan-only trial, second pass: each task's short brief becomes a detailed one (the first plan-only build stuck
    on briefs of 1,500 characters where the cloud plan's, for the same tests, had 7,000 and a tuned algorithm)."""
    ws = Path(ws)
    m = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8"))
    pl = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
    _, source = source_view(ws, budget=30_000, whole=3_000)
    summary = "\n".join(f"  {t['id']} {t['title']} (files: {', '.join(t.get('files') or [])}; test: {own(t)})" for t in pl["tasks"])
    done, wrote = [], 0
    for t in pl["tasks"]:
        if only and t["id"] != only:
            done.append(t)
            continue
        if not only and not dry and t.get("brief_short"):
            print(f"  {t['id']}: already rewritten, kept (to do it again: briefs <workspace> {t['id']})")
            done.append(t)
            continue
        src = (ws / str(own(t))).read_text(encoding="utf-8", errors="replace") if m.get("plan_only") and (ws / str(own(t))).is_file() else ""
        labels = check_labels(src)
        kept = []
        for x in done:                                         # blind6 T02 broke T01's checks in every attempt
            f = ws / str(own(x))
            if m.get("plan_only") and f.is_file():
                kept += [f"  - ({x['id']}) " + lab for lab in check_labels(f.read_text(encoding="utf-8", errors="replace"))]
        task = (f"{t['id']} {t['title']}\nFiles it may change: {', '.join(t.get('files') or [])}\nAfter: "
                f"{', '.join(t.get('depends_on') or []) or 'nothing'}\nThe short brief:\n{t.get('brief_short') or t.get('brief')}")
        earlier = "\n\n".join(f"--- {x['id']} {x['title']} ---\n{x.get('brief')}" for x in done) or "(none: this is the first task)"
        prompt = BRIEF.format(spec=(ws / "SPEC.md").read_text(encoding="utf-8"), summary=summary, task=task, source=source,
                              labels="\n".join("  - " + x for x in labels) or "  (the spec is the only judge)", earlier=earlier[-24_000:],
                              kept="\n".join(kept)[-6_000:] or "  (none: this is the first task)")
        text = call(ws, f"blind_brief_{t['id']}", prompt, model, think, dry)
        if text:
            import nd_studio as S
            new = S.strip_think(text).strip()
            faults = brief_faults(ws, {"brief": new}, done)
            # blind5: redefined isTvBrowser(); blind6: OK fired twice, names the app lacks. Up to two more asks, each told
            # every fault seen so far (blind6 T04, 2026-11-18: three runs of one re-ask each all kept closePlayer()).
            seen = list(faults)
            for k in range(2):
                if not faults:
                    break
                print(f"  {t['id']}: the rewrite has {len(faults)} fault(s): {'; '.join(f[:90] for f in faults)}; asking again ({k + 1} of 2)", flush=True)
                again = call(ws, f"blind_brief_{t['id']}", prompt + (
                    "\n\nNOTE: your earlier briefs for this task had these faults, each of which broke the app in an earlier "
                    "build:\n" + "\n".join("- " + f for f in dict.fromkeys(seen)) + "\nWrite the whole brief again without them."),
                    model, think, dry)
                if not again:
                    break
                cand = S.strip_think(again).strip()
                cf = brief_faults(ws, {"brief": cand}, done)
                if len(cf) < len(faults):
                    new, faults = cand, cf
                seen += cf
            if faults:
                print(f"  {t['id']}: the best rewrite still has {len(faults)} fault(s); `check` will say NOT READY", flush=True)
            if len(new) < len(t.get("brief_short") or t.get("brief") or "") or len(new) < 1500:
                print(f"  {t['id']}: the rewrite is {len(new)} characters, no better than the short brief: kept the short one")
            else:
                t["brief_short"] = t.get("brief_short") or t.get("brief")
                t["brief"] = new
                wrote += 1
                print(f"  {t['id']}: {len(t['brief_short'])} -> {len(new)} characters")
                (ws / "plan.json").write_text(json.dumps(pl, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                P.git(ws, "add", "-A")
                P.git(ws, "commit", "-q", "-m", f"blind trial: {t['id']}'s brief rewritten in detail, by {model}")
        done.append(t)
    if wrote:
        P.journal(ws, "studio_blind", f"{wrote} brief(s) rewritten in detail by {model}")


def tests(ws, model, think, dry, only=None):
    ws = Path(ws)
    if json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8")).get("plan_only"):
        sys.exit("this is a plan-only trial: the pack's own tests judge the build, the local model writes none. Next: check, then build.")
    pl = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
    _, source = source_view(ws, budget=30_000, whole=3_000)
    summary = "\n".join(f"  {t['id']} {t['title']} -> {t['tests']}" for t in pl["tasks"])
    wrote = 0
    for t in pl["tasks"]:
        if only and t["id"] != only:
            continue
        if not only and not dry and (ws / t["tests"]).is_file():    # run again after a failure: keep what is there
            print(f"  {t['tests']}: already written, kept (to write it again: tests <workspace> {t['id']})")
            continue
        task = (f"{t['id']} {t['title']}\nFiles it may change: {', '.join(t.get('files') or [])}\nAfter: {', '.join(t.get('depends_on') or []) or 'nothing'}\n"
                f"Brief:\n{t.get('brief')}")
        prompt = TESTS.format(test=t["tests"], spec=(ws / "SPEC.md").read_text(encoding="utf-8"), summary=summary, task=task,
                              helpers=helpers_view(ws, full=True), source=source)
        text = call(ws, f"blind_tests_{t['id']}", prompt, model, think, dry)
        if text is None:
            continue
        import nd_studio as S
        try:
            code = S.extract_python(text)
            compile(code, t["tests"], "exec")
        except (ValueError, SyntaxError) as e:
            print(f"  {t['tests']}: NOT WRITTEN ({e})")
            continue
        (ws / t["tests"]).write_text(code, encoding="utf-8")
        wrote += 1
        print(f"  {t['tests']}: {code.count('check(')} check calls")
        P.git(ws, "add", "-A")                                 # one commit per file: a later failure loses nothing
        P.git(ws, "commit", "-q", "-m", f"blind trial: {t['tests']}, by {model}")
    if wrote:
        P.journal(ws, "studio_blind", f"{wrote} test file(s) written by {model}")
        P.status(ws)
        P.git(ws, "add", "-A")
        P.git(ws, "commit", "-q", "-m", f"blind trial: the tests, by {model}")


DEFINES = (r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(",           # function name(
           r"`([A-Za-z_$][\w$]*)\([^`]*\)`\s+takes\b")             # `name()` takes ...: how the briefs step describes a part


def clashes(ws, task):
    """-> [(name, file)] for each function the brief would declare that the app as it was before the build already
    declares (blind5, 2026-11-16: T01's brief wrote its own isTvBrowser(), the page's own was replaced, and six sign-in
    checks broke in every attempt)."""
    ws = Path(ws)
    root = subprocess.run(["git", "-C", str(ws), "rev-list", "--max-parents=0", "HEAD"], capture_output=True, text=True).stdout.split()
    if not root:
        return []
    ls = subprocess.run(["git", "-C", str(ws), "ls-tree", "-r", "--name-only", root[-1]], capture_output=True, text=True).stdout.split("\n")
    have = {}
    for rel in ls:
        if (rel.endswith((".html", ".js")) and not rel.startswith(("tests/", "node_modules/", "dist/"))
                and "/vendor/" not in "/" + rel and not rel.endswith(".min.js")):   # a library's insides are not the page's names
            src = subprocess.run(["git", "-C", str(ws), "show", f"{root[-1]}:{rel}"], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace").stdout
            for n in re.findall(DEFINES[0], src):
                have.setdefault(n, rel)
    brief = str(task.get("brief") or "")
    mine = {n for pat in DEFINES for n in re.findall(pat, brief)}
    return sorted((n, have[n]) for n in mine if n in have)


def double_ok(task):
    """-> the brief's Enter branches that call .click() with no preventDefault(). A focused button already clicks
    itself on Enter, so such code fires every OK twice (blind6, 2026-11-17: T01's brief said `currentFocus.click()` on
    Enter; Sign in asked Plex for two pins, the code screen never signed in, and every good attempt broke sign-in)."""
    brief = str(task.get("brief") or "")
    out = []
    for mt in re.finditer(r"""key\s*===?\s*['"]Enter['"]|case\s+['"]Enter['"]""", brief):
        rest = brief[mt.end():mt.end() + 900]
        nxt = re.search(r"""key\s*===?\s*['"]|case\s+['"]|\n\s*\n""", rest)       # the next key's branch ends this one
        branch = rest[:nxt.start()] if nxt else rest
        if ".click()" in branch and "preventDefault" not in branch:
            out.append(brief[mt.start():mt.end() + len(branch)].strip()[:160])
    return out


_USES = (r"""getElementById\(\s*['"]([\w-]+)['"]""",                                   # -> id
          r"""(?:querySelector(?:All)?|closest|matches)\(\s*['"]([^'"]+)['"]""",          # -> a selector
          r"""classList\.(?:contains|remove)\(\s*['"]([\w-]+)['"]""")                    # -> class
_MAKES = (r"""classList\.(?:add|toggle)\(\s*['"]([\w-]+)['"]""", r"""\.(?:id|className)\s*=\s*['"]([\w -]+)['"]""",
          r"""\b(?:id|class)\s*=\s*\\?["']([\w -]+)\\?["']""", r"""setAttribute\(\s*['"](?:id|class)['"]\s*,\s*['"]([\w -]+)['"]""")
_known_cache = {}


def _known_text(ws):
    """The app as staged (its .html/.js/.css), the spec and the pack's tests: where a page part's name may come from."""
    ws = Path(ws)
    root = subprocess.run(["git", "-C", str(ws), "rev-list", "--max-parents=0", "HEAD"], capture_output=True, text=True).stdout.split()
    key = (str(ws), root[-1] if root else "")
    if key in _known_cache:
        return _known_cache[key]
    parts = []
    if root:
        ls = subprocess.run(["git", "-C", str(ws), "ls-tree", "-r", "--name-only", root[-1]], capture_output=True, text=True).stdout.split("\n")
        for rel in ls:
            if rel.endswith((".html", ".js", ".css", ".py")) and not rel.startswith(("node_modules/", "dist/", ".")) \
                    and "/vendor/" not in "/" + rel and not rel.endswith(".min.js") and (rel.startswith("tests/") or not rel.endswith(".py")):
                parts.append(subprocess.run(["git", "-C", str(ws), "show", f"{root[-1]}:{rel}"], capture_output=True, text=True,
                                            encoding="utf-8", errors="replace").stdout)
    for f in [ws / "SPEC.md", *sorted((ws / "tests").glob("*.py"))]:
        try:
            parts.append(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    _known_cache[key] = "\n".join(parts)
    return _known_cache[key]


def ghost_names(ws, task, earlier=()):
    """-> ['#id' / '.class'] the brief's code looks up that exist nowhere: not in the app as staged, the spec or the
    tests, and not made by this brief or an earlier one (blind6, 2026-11-17: T02-T04 said "use exactly this" over code
    that looked up `.channel-logo` (the app's is `.logo-tile`) and `#chat-panel` (no such element); the logo checks failed)."""
    brief = str(task.get("brief") or "")
    used = set()
    for i, pat in enumerate(_USES):
        for v in re.findall(pat, brief):
            if i == 0:
                used.add("#" + v)
            elif i == 2:
                used.add("." + v)
            else:
                used |= set(re.findall(r"[#.][A-Za-z_][\w-]*", v))
    made = set()
    for b in [brief, *[str(x.get("brief") or "") for x in earlier]]:
        for pat in _MAKES:
            for v in re.findall(pat, b):
                made |= set(v.split())
    known = _known_text(ws)
    out = []
    for s in sorted(used):
        n = s[1:]
        if n in made or re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", known):
            continue
        out.append(s)
    return out


def _root_file(ws, rel):
    root = subprocess.run(["git", "-C", str(ws), "rev-list", "--max-parents=0", "HEAD"], capture_output=True, text=True).stdout.split()
    if not root:
        return ""
    return subprocess.run(["git", "-C", str(ws), "show", f"{root[-1]}:{rel}"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def app_function(ws, rel, name):
    """-> ', line N: `function name(...){ first lines }`' of the app's own function, so the model can see what to call."""
    lines = _root_file(ws, rel).split("\n")
    for i, ln in enumerate(lines):
        if re.search(r"\bfunction\s+" + re.escape(name) + r"\s*\(", ln):
            body = " ".join(x.strip() for x in lines[i:i + 4])
            return f", line {i + 1}: `{body[:220]}`"
    return ""


def ghost_hints(ws, ghosts):
    """-> {ghost: ' (the app has ...)'}: the element whose visible text holds the ghost's words (`#media-view` -> the
    button that says "Media view", `#theater-toggle`), else ids/classes sharing a word with it (`.channel-logo` ->
    `.logo-tile`)."""
    ws = Path(ws)
    root = subprocess.run(["git", "-C", str(ws), "rev-list", "--max-parents=0", "HEAD"], capture_output=True, text=True).stdout.split()
    if not root:
        return {}
    ls = subprocess.run(["git", "-C", str(ws), "ls-tree", "-r", "--name-only", root[-1]], capture_output=True, text=True).stdout.split("\n")
    src = "\n".join(_root_file(ws, r) for r in ls if r.endswith(".html") and not r.startswith(("tests/", "node_modules/", "dist/")))
    ids = set(re.findall(r'\bid="([\w-]+)"', src))
    classes = {c for v in re.findall(r'\bclass="([^"]+)"', src) for c in v.split()}
    out = {}
    for g in ghosts:
        words = [w for w in re.split(r"[-_]", g[1:].lower()) if len(w) > 2]
        found = []
        if len(words) >= 2:
            pat = r"\W+".join(map(re.escape, words))
            for mt in re.finditer(r"<(\w+)[^>]*\bid=\"([\w-]+)\"[^>]*>([^<]{0,80})", src):
                if re.search(pat, mt.group(3), re.I):
                    found.append(f"`#{mt.group(2)}`, the {mt.group(1)} that says \"{mt.group(3).strip()[:40]}\"")
        if not found:
            pool = ids if g[0] == "#" else classes
            near = sorted(n for n in pool if any(w in n.lower().split("-") for w in words))
            found = [f"`{g[0]}{n}`" for n in near[:4]]
        if found:
            out[g] = " (the app has " + ", ".join(found[:3]) + ")"
    return out


def brief_faults(ws, task, earlier=()):
    """-> [message] for what a brief would surely break, each also said to the model when it is asked again."""
    out = [f"the brief declares `{n}()`, which the app already has ({w}{app_function(ws, w, n)}): a second declaration "
           "replaces the app's own and breaks what uses it (blind5: the sign-in page). The code must CALL it and never "
           "declare one of that name; to add to it, write a function with a NEW name that calls it"
           for n, w in clashes(ws, task)]
    ghosts = ghost_names(ws, task, earlier)
    if ghosts:
        hints = ghost_hints(ws, ghosts)
        out.append(f"the brief's code looks up {', '.join('`' + g + '`' + hints.get(g, '') for g in ghosts)}, which the app does not have and no "
                   "task makes (blind6: `.channel-logo` where the app's logos are `.logo-tile`; the logo checks failed). Use "
                   "only ids and classes from the source shown above, or have the brief create the element first")
    out += [f"the brief's Enter (OK) branch calls .click() without e.preventDefault(): a focused button already clicks "
            f"itself on Enter, so every OK fires twice (blind6: Sign in asked for two pins, sign-in broke). Call "
            f"e.preventDefault() before .click(), and leave Enter alone while remote mode is off. The branch: {b}"
            for b in double_ok(task)]
    return out


def check(ws):
    """Mechanical, no model: is the local plan buildable and do its tests fail on the app as it is?"""
    ws = Path(ws)
    bad = []
    pl = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
    py = str(ws / ".venv" / "Scripts" / "python.exe")
    ids = [t.get("id") for t in pl.get("tasks") or []]
    if not ids:
        bad.append("the plan has no tasks")
    if len(set(ids)) != len(ids):
        bad.append("two tasks share an id")
    try:
        fst = json.loads((ws / ".foreman" / "state.json").read_text(encoding="utf-8"))
        # passed, or worked on (a salvage may have made its test pass: blind6 T03, 2026-11-18)
        done_ids = {k for k, v in (fst.get("tasks") or {}).items() if v.get("status") == "passed" or v.get("attempts")}
    except (OSError, ValueError):
        done_ids = set()
    names = [own(t) for t in pl.get("tasks") or []]
    if len(set(names)) != len(names):
        bad.append("two tasks share a test file")
    for i, t in enumerate(pl.get("tasks") or []):
        for dep in t.get("depends_on") or []:
            if dep not in ids:
                bad.append(f"{t['id']} depends on {dep}, which is not in the plan")
        if not t.get("files"):
            bad.append(f"{t['id']} may change no files")
        if len(t.get("brief") or "") < 300:
            bad.append(f"{t['id']}: the brief is {len(t.get('brief') or '')} characters; the programmer knows only what it says")
        tn = own(t)
        f = ws / str(tn)
        if not f.is_file():
            bad.append(f"{t['id']}: {tn} was not written")
            continue
        p, fl, ok, tail = P.run_test(py, ws, tn, 300)
        print(f"  {tn:36} on the app as it is: {p} passed, {fl} failed")
        if ok and t["id"] not in done_ids:                    # a task the foreman passed may pass (a rebuild after briefs)
            bad.append(f"{tn} passes before anything is built: it checks nothing new")
        elif fl < 0:
            bad.append(f"{tn} crashes or prints no summary instead of failing cleanly: {tail[-200:]}")
        for fault in brief_faults(ws, t, (pl.get("tasks") or [])[:i]):
            bad.append(f"{t['id']}: {fault}. Run `briefs` again for this task, or mend the brief")
    m = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8"))
    if m.get("plan_only"):
        want, _, _ = acceptance(ws, m)
        if pl.get("plan_only_problem"):
            bad.append(pl["plan_only_problem"])
        elif [own(t) for t in pl.get("tasks") or []] != want:
            bad.append(f"plan-only trial: the tasks' tests must be {want}, in that order")
    spec = (ws / "SPEC.md").read_text(encoding="utf-8")
    briefs = " ".join(str(t.get("brief")) for t in pl.get("tasks") or [])
    missing = [name for name in sorted(set(re.findall(r"`([^`\n]{3,60})`", spec))) if name not in briefs]
    if missing:                                               # worth reading, not a reason to refuse the build
        print(f"  note: {len(missing)} name(s) the spec gives appear in no brief: " + ", ".join("`" + x + "`" for x in missing[:12]))
    print(("NOT READY (do not build: the foreman will refuse this plan; run `plan` again or mend plan.json):\n" + "\n".join("  - " + b for b in bad)) if bad else "READY: the plan is well formed and every test fails cleanly on the app as it is.")
    (ws / ".studio" / "blind_check.json").write_text(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M"), "problems": bad,
                                                                 "spec_names_in_no_brief": missing}, indent=1), encoding="utf-8")
    return 1 if bad else 0


def grade(ws):
    ws = Path(ws)
    m = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8"))
    d = Path(m["pack_dir"])
    py = P.pack_python(m)
    links = set(m.get("base_links") or [])
    scratch = Path(tempfile.mkdtemp(prefix="blind_grade_"))
    res = {"when": time.strftime("%Y-%m-%d %H:%M"), "pack": m["name"], "hidden": {}, "local_tests": {}}
    try:
        pl = json.loads((ws / "plan.json").read_text(encoding="utf-8")) if (ws / "plan.json").is_file() else {"tasks": []}
        local = [own(t) for t in pl["tasks"] if own(t) and (ws / str(own(t))).is_file()]
        # 1. the pack's hidden tests on what was built
        built = scratch / "built"
        shutil.copytree(ws, built, ignore=shutil.ignore_patterns(".venv", ".foreman", ".git", "__pycache__", ".studio", "tests", *links))
        # Only committed work is built work: a run cut off mid-attempt leaves edits lying in the folder (blind5).
        st = subprocess.run(["git", "-C", str(ws), "status", "--porcelain", "--untracked-files=all"], capture_output=True,
                            text=True, encoding="utf-8", errors="replace").stdout
        loose = [ln[3:].strip().strip('"').split(" -> ")[-1] for ln in st.splitlines() if ln.strip()]
        loose = [p for p in loose if not p.startswith((".studio/", "tests/"))]
        for rel in loose:
            dst = built / rel
            head = subprocess.run(["git", "-C", str(ws), "show", f"HEAD:{rel}"], capture_output=True)
            if head.returncode == 0:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(head.stdout)
            elif dst.is_file():
                dst.unlink()
        if loose:
            print(f"   (graded the last commit: {len(loose)} uncommitted file(s) in the workspace were left out: {', '.join(loose[:5])})")
        res["uncommitted_ignored"] = loose
        for n in links:
            if (ws / n).is_dir():
                subprocess.run(["cmd", "/c", "mklink", "/J", str(built / n), str((ws / n).resolve())], capture_output=True)
        shutil.copytree(d / "tests", built / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        print("1. The pack's own tests (never shown to the local planner) on what was built:")
        tp = tf = 0
        misses = 0
        guards = set(m.get("guard_tests") or [])               # they pass on the old app: keeping them is no credit
        np_ = nf = 0
        sf = ws / ".foreman" / "state.json"
        try:
            done = [k for k, v in json.loads(sf.read_text(encoding="utf-8")).get("tasks", {}).items() if v.get("status") == "passed"]
        except (OSError, ValueError):
            done = []
        res["built"] = bool(done)
        if not done:
            print("   NOTHING WAS BUILT in this workspace (no task passed). What follows is the app as it was staged,\n"
                  "   so it only shows where the old app already stands.")
        for t in P.tests_of(d):
            r = subprocess.run([py, t], cwd=str(built), capture_output=True, text=True, encoding="utf-8", errors="replace", env=P.ENV, timeout=900)
            out = (r.stdout or "") + (r.stderr or "")
            mm = ([None] + list(re.finditer(r"(?m)^\s*(\d+) passed, (\d+) failed\s*$", out)))[-1]
            p, f = (int(mm.group(1)), int(mm.group(2))) if mm else (0, -1)
            fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("FAIL")]
            miss = [ln for ln in fails if re.search(r"exists|is not there|not found|loads it", ln)]
            misses += len(miss)
            res["hidden"][t] = {"passed": p, "failed": f, "fails": fails[:12]}
            tp, tf = tp + p, tf + max(f, 0)
            if t not in guards:
                np_, nf = np_ + p, nf + max(f, 0) + (1 if f < 0 else 0)
            print(f"   {t:36} {p} passed, {'crashed' if f < 0 else str(f) + ' failed'}" + (f"   first: {fails[0][:110]}" if fails else ""))
        total = tp + tf
        res["score"] = {"checks_pass": tp, "checks": total, "share": round(tp / total, 3) if total else 0, "contract_misses": misses,
                        "new_work_pass": np_, "new_work_checks": np_ + nf, "guards_pass": tp - np_, "guards_checks": total - np_ - nf}
        print(f"   THE NEW WORK: {np_} of {np_ + nf} checks pass. Older work still standing (guard tests, no credit): "
              f"{tp - np_} of {total - np_ - nf}." + ("" if done else "  NOTHING WAS BUILT."))
        print(f"   SCORE: {tp} of {total} hidden checks pass ({res['score']['share']:.0%}); {misses} failing check(s) look like a name the spec "
              f"may not have carried (a file, id or function 'not there')")
        # 2. the local tests: sound? (pass on the pack's reference, fail on the old app)
        if m.get("plan_only"):
            res["local_tests_sound"] = "none written (plan-only trial)"
            print("\n2. Plan-only trial: the local model wrote no tests; the pack's own judged the build.")
        elif local and m.get("reference") and (d / m["reference"]).is_dir():
            print("\n2. The local planner's own tests, judged like any test writer's:")
            ref, old = scratch / "ref", scratch / "old"
            P.lay_out(d, m, ref, reference=True)
            P.lay_base(m, old)
            for folder in (ref, old):
                (folder / "tests").mkdir(exist_ok=True)
                for rel in m.get("planner_got") or []:
                    if (ws / rel).is_file():
                        shutil.copy(ws / rel, folder / rel)
                for t in local:
                    shutil.copy(ws / t, folder / t)
            sound = 0
            for t in local:
                pr, fr, okr, _ = P.run_test(py, ref, t, 600)
                po, fo, oko, _ = P.run_test(py, old, t, 300)
                good = okr and not oko
                sound += good
                res["local_tests"][t] = {"on_reference": f"{pr} passed, {fr} failed", "on_old_app": f"{po} passed, {fo} failed", "sound": bool(good)}
                print(f"   {t:36} on the reference build: {pr} passed, {fr} failed; on the old app: {'passes (checks nothing)' if oko else 'fails, as it must'}"
                      f"  -> {'sound' if good else 'NOT sound'}")
            res["local_tests_sound"] = f"{sound} of {len(local)}"
            print(f"   {sound} of {len(local)} local test files are sound (a test that fails on a GOOD build would have blocked the builder)")
            P.unlink_base(m, ref)
            P.unlink_base(m, old)
        st = P.status(ws)
        res["build"] = {k: sum(1 for v in st.values() if v.get("status") == k) for k in {v.get("status") for v in st.values()}} if st else {}
    finally:
        P.unlink_base(m, scratch / "built")
        shutil.rmtree(scratch, ignore_errors=True)
        try:
            import studio_overnight as Q                       # a test that crashed leaves its gateway and Edge behind
            Q.close_test_servers(print)
        except Exception as e:
            print(f"   (could not check for leftover test servers: {e})")
    (ws / ".studio" / "blind_grade.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    s = res["score"]
    P.journal(ws, "studio_blind", ("graded" if res["built"] else "graded, but NOTHING WAS BUILT") + f": new work {s['new_work_pass']} of "
              f"{s['new_work_checks']} hidden checks, guards {s['guards_pass']} of {s['guards_checks']}; local tests sound: "
              f"{res.get('local_tests_sound', 'not judged')}")
    print(f"\nwritten: {ws / '.studio' / 'blind_grade.json'}")
    return res


def main(a):
    try:                                                      # a hint can quote the page ("🖥 Media view"); cmd.exe is cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    model = opt(a, "--model", "q36c-nd64k")
    dry, think, plan_only = "--dry" in a, "--no-think" not in a, "--plan-only" in a
    a = [x for x in a if x not in ("--dry", "--no-think", "--plan-only")]
    if len(a) < 2:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "stage" and len(a) == 3:
        stage(a[1], a[2], plan_only)
    elif cmd == "plan":
        plan(a[1], model, think, dry)
    elif cmd == "briefs":
        briefs(a[1], model, think, dry, a[2] if len(a) > 2 else None)
    elif cmd == "tests":
        tests(a[1], model, think, dry, a[2] if len(a) > 2 else None)
    elif cmd == "check":
        sys.exit(check(a[1]))
    elif cmd == "grade":
        grade(a[1])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
