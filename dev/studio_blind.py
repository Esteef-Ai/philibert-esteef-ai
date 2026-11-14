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


def stage(pack, ws):
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
    for n in (".gitignore", ".gitattributes"):
        if (d / n).is_file():
            shutil.copy(d / n, ws / n)
    (ws / ".studio").mkdir()
    (ws / ".studio" / "pack.json").write_text(json.dumps({**m, "pack_dir": str(d), "blind": True, "planner_got": gets,
                                                         "laid_out": time.strftime("%Y-%m-%d %H:%M")}, indent=1), encoding="utf-8")
    (ws / "opencode.json").write_text(json.dumps(Q.OPENCODE_PROJECT, indent=1), encoding="utf-8")
    gi = ws / ".gitignore"
    have = gi.read_text(encoding="utf-8") if gi.exists() else ""
    gi.write_text(have.rstrip() + "".join(f"\n{x}" for x in (".venv/", ".foreman/", "__pycache__/", "*.pyc", ".nd_backups/") if x not in have) + "\n",
                  encoding="utf-8")
    P.git(ws, "init", "-q")
    P.journal(ws, "studio_blind", f"blind trial staged from pack {m['name']}: the app, the spec and {len(gets)} helper file(s); no plan, no tests")
    P.git(ws, "add", "-A")
    P.git(ws, "commit", "-q", "-m", f"{m['title']}: blind planner trial, nothing planned yet")
    subprocess.run([P.BASE_PY, "-m", "venv", ".venv"], cwd=str(ws), check=True)
    for pkg in (m.get("python") or {}).get("pip") or []:
        subprocess.run([str(ws / ".venv" / "Scripts" / "python.exe"), "-m", "pip", "install", "-q", pkg], cwd=str(ws), capture_output=True)
    me = f'"{sys.executable}" "{Path(__file__).resolve()}"'
    print(f"staged: {ws}\nnext (you run these; they call the local model):\n  {me} plan \"{ws}\"\n  {me} tests \"{ws}\"\n  {me} check \"{ws}\"\n"
          f"  \"{sys.executable}\" \"{Path(P.__file__).resolve()}\" build \"{ws}\"\n  {me} grade \"{ws}\"")


def call(ws, stage_name, prompt, model, think, dry):
    sd = Path(ws) / ".studio"
    (sd / f"{stage_name}.prompt.txt").write_text(prompt, encoding="utf-8")
    if dry:
        print(f"  {stage_name}: prompt written ({len(prompt)} chars), no model called (--dry)")
        return None
    import nd_studio as S
    print(f"[{time.strftime('%H:%M:%S')}] {stage_name}: asking {model} ({len(prompt)} chars) ...", flush=True)
    text, secs, info = S.call_model(model, prompt, think=think)
    (sd / f"{stage_name}.reply.txt").write_text(text, encoding="utf-8")
    with open(sd / "log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"stage": stage_name, "model": model, "seconds": secs, **info, "at": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
    print(f"  {secs} s, {info.get('eval_count')} tokens out", flush=True)
    return text


def kind_rules(m):
    src = json.loads((P.PACKS / "BUILDER_RULES.json").read_text(encoding="utf-8"))
    return "\n".join(f"- {r}" for r in (src.get("kinds") or {}).get(m.get("kind"), []))


def plan(ws, model, think, dry):
    ws = Path(ws)
    m = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8"))
    tree, source = source_view(ws)
    prompt = PLAN.format(kind=m.get("kind"), kind_rules=kind_rules(m), tree=tree, source=source,
                         spec=(ws / "SPEC.md").read_text(encoding="utf-8"), helpers=helpers_view(ws))
    text = call(ws, "blind_plan", prompt, model, think, dry)
    if text is None:
        return
    import nd_studio as S
    pl = S.extract_json(text)
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
    for t in pl.get("tasks") or []:
        if isinstance(t.get("tests"), list):
            t["tests"] = t["tests"][0] if t["tests"] else None
        t["tests"] = t.get("tests") or f"tests/test_{str(t.get('id', 'tx')).lower()}.py"
        t.setdefault("depends_on", [])
        t["context"] = [t["tests"]]
        t["done_when"] = [f"{t['tests']} prints 0 failed"]
    pl.update({"workspace": ".", "model": "opencode/q36c-nd128k", "opencode_think": False, "alt_model": None,
               "defaults": {"attempts": 3, "minutes": 40}, "planned_by": model})
    (ws / "plan.json").write_text(json.dumps(pl, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    P.builder_rules(ws, m)
    for t in pl.get("tasks") or []:
        print(f"  {t.get('id')} {t.get('title')}: {', '.join(t.get('files') or [])} -> {t.get('tests')} ({len(t.get('brief') or '')} chars)")
    P.journal(ws, "studio_blind", f"plan written by {model}: {len(pl.get('tasks') or [])} task(s)")
    P.git(ws, "add", "-A")
    P.git(ws, "commit", "-q", "-m", f"blind trial: the plan, by {model}")


def tests(ws, model, think, dry, only=None):
    ws = Path(ws)
    pl = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
    _, source = source_view(ws, budget=30_000, whole=3_000)
    summary = "\n".join(f"  {t['id']} {t['title']} -> {t['tests']}" for t in pl["tasks"])
    wrote = 0
    for t in pl["tasks"]:
        if only and t["id"] != only:
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
    if wrote:
        P.journal(ws, "studio_blind", f"{wrote} test file(s) written by {model}")
        P.status(ws)
        P.git(ws, "add", "-A")
        P.git(ws, "commit", "-q", "-m", f"blind trial: the tests, by {model}")


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
    names = [t.get("tests") for t in pl.get("tasks") or []]
    if len(set(names)) != len(names):
        bad.append("two tasks share a test file")
    for t in pl.get("tasks") or []:
        for dep in t.get("depends_on") or []:
            if dep not in ids:
                bad.append(f"{t['id']} depends on {dep}, which is not in the plan")
        if not t.get("files"):
            bad.append(f"{t['id']} may change no files")
        if len(t.get("brief") or "") < 300:
            bad.append(f"{t['id']}: the brief is {len(t.get('brief') or '')} characters; the programmer knows only what it says")
        f = ws / str(t.get("tests"))
        if not f.is_file():
            bad.append(f"{t['id']}: {t.get('tests')} was not written")
            continue
        p, fl, ok, tail = P.run_test(py, ws, t["tests"], 300)
        print(f"  {t['tests']:36} on the app as it is: {p} passed, {fl} failed")
        if ok:
            bad.append(f"{t['tests']} passes before anything is built: it checks nothing new")
        elif fl < 0:
            bad.append(f"{t['tests']} crashes or prints no summary instead of failing cleanly: {tail[-200:]}")
    spec = (ws / "SPEC.md").read_text(encoding="utf-8")
    briefs = " ".join(str(t.get("brief")) for t in pl.get("tasks") or [])
    for name in sorted(set(re.findall(r"`([^`\n]{3,60})`", spec))):
        if name not in briefs:
            bad.append(f"the spec names `{name}` and no brief mentions it")
    print(("NOT READY (do not build: the foreman will refuse this plan; run `plan` again or mend plan.json):\n" + "\n".join("  - " + b for b in bad)) if bad else "READY: the plan is well formed and every test fails cleanly on the app as it is.")
    (ws / ".studio" / "blind_check.json").write_text(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M"), "problems": bad}, indent=1), encoding="utf-8")
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
        local = [t["tests"] for t in pl["tasks"] if (ws / str(t.get("tests"))).is_file()]
        # 1. the pack's hidden tests on what was built
        built = scratch / "built"
        shutil.copytree(ws, built, ignore=shutil.ignore_patterns(".venv", ".foreman", ".git", "__pycache__", ".studio", "tests", *links))
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
            mm = re.search(r"(\d+) passed, (\d+) failed\s*$", out.strip())
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
        if local and m.get("reference") and (d / m["reference"]).is_dir():
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
    (ws / ".studio" / "blind_grade.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    s = res["score"]
    P.journal(ws, "studio_blind", ("graded" if res["built"] else "graded, but NOTHING WAS BUILT") + f": new work {s['new_work_pass']} of "
              f"{s['new_work_checks']} hidden checks, guards {s['guards_pass']} of {s['guards_checks']}; local tests sound: "
              f"{res.get('local_tests_sound', 'not judged')}")
    print(f"\nwritten: {ws / '.studio' / 'blind_grade.json'}")
    return res


def main(a):
    model = opt(a, "--model", "q36c-nd64k")
    dry, think = "--dry" in a, "--no-think" not in a
    a = [x for x in a if x not in ("--dry", "--no-think")]
    if len(a) < 2:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "stage" and len(a) == 3:
        stage(a[1], a[2])
    elif cmd == "plan":
        plan(a[1], model, think, dry)
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
