"""Plan packs: a spec, a plan and its tests, written ahead of the build, that the foreman builds from.

A pack is a folder (dev/packs/<name>/): PACK.json, SPEC.md, plan.json, tests/, NOTES.md and, once the app has
been built well, reference/ (a good build, kept OUT of every workspace). Everything an agent needs to carry the
work on is on disk: the pack says what to build and how it is judged; the workspace's .studio/HANDOFF.md says
where the build stands; .studio/journal.jsonl says who did what.

    python dev/studio_pack.py verify <pack> [--full] [--mutants 30]   is the pack sound? (minutes, no model)
    python dev/studio_pack.py new <pack> <workspace>                  a fresh workspace, ready to build
    python dev/studio_pack.py build <workspace> [--max-hours 6] [--rounds 1]   the unattended build (YOU launch it)
    python dev/studio_pack.py tweak <workspace> <tweak>               add a tweak (new tasks + their tests) to a built workspace
    python dev/studio_pack.py rules <workspace>                       add the shared builder rules (packs/BUILDER_RULES.json)
    python dev/studio_pack.py status <workspace>                      rewrite .studio/HANDOFF.md
    python dev/studio_pack.py note <workspace> "<who>" "<what>"       add a line to the journal

verify answers three questions about the tests without building anything:
  - do they pass on the reference build?        (a test that fails there is wrong, or the reference is)
  - do they all fail on an empty project?       (a test that passes there checks nothing)
  - do they notice broken code?                 (small bugs are put into the reference, one at a time; the share
                                                 of bugs the tests catch is the "kill rate")
The same three questions grade tests written by a local model: point verify at a pack whose tests it wrote.
"""
import ast
import concurrent.futures
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKS = REPO / "dev" / "packs"
ROOT = Path(r"C:\PCodeTest")
BASE_PY = r"C:\Python311_base\python.exe"
FOREMAN = r"G:\!Ai\ND3\nd_foreman.py"      # read-only use of the developer's copy
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
sys.path.insert(0, str(REPO / "dev"))
sys.path.insert(0, str(REPO / "shared"))


# ── the pack ─────────────────────────────────────────────────────────────────

def load(pack):
    d = Path(pack) if Path(pack).is_dir() else PACKS / str(pack)
    if not (d / "PACK.json").is_file():
        sys.exit(f"no pack at {d} (PACK.json missing)")
    m = json.loads((d / "PACK.json").read_text(encoding="utf-8"))
    for need in ("SPEC.md", "plan.json", "tests"):
        if not (d / need).exists():
            sys.exit(f"the pack has no {need}")
    return d, m


def fill(text, m, **more):
    for k, v in {**(m.get("fill") or {}), **more}.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def tests_of(d):
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    out = []
    for t in plan["tasks"]:
        ts = t.get("tests") or []
        for n in ([ts] if isinstance(ts, str) else ts):
            if n not in out:
                out.append(n)
    return out


def lay_out(d, m, dest, reference=False):
    """The pack's files as a workspace gets them (placeholders filled). reference=True adds the good build."""
    dest.mkdir(parents=True, exist_ok=True)
    if m.get("base"):
        # An EXISTING app to change, not an empty folder to fill: the workspace starts as a copy of it. The big
        # folders nobody edits (node_modules) are linked, not copied: a junction costs nothing and git ignores it.
        base, links = Path(m["base"]), set(m.get("base_links") or [])
        shutil.copytree(base, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", ".git", *links))
        for n in links:
            if (base / n).is_dir() and not (dest / n).exists():
                subprocess.run(["cmd", "/c", "mklink", "/J", str(dest / n), str(base / n)], capture_output=True, check=True)
    shutil.copytree(d / "tests", dest / "tests", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    for n in ("plan.json", "SPEC.md", ".gitignore", ".gitattributes"):
        if (d / n).is_file():
            shutil.copy(d / n, dest / n)
    for rel in m.get("fill_in") or []:
        f = dest / rel
        text = f.read_text(encoding="utf-8")
        if rel.endswith(".json"):                             # inside JSON a path's backslashes are doubled
            text = fill(text, {"fill": {k: json.dumps(str(v))[1:-1] for k, v in (m.get("fill") or {}).items()}})
            json.loads(text)
        else:
            text = fill(text, m)
        f.write_text(text, encoding="utf-8")
    if reference:
        shutil.copytree(d / m["reference"], dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))


def pack_python(m):
    """A Python with the pack's packages, shared by every verify (not a workspace's own .venv)."""
    v = ROOT / "_pack_venvs" / m["name"]
    py = v / "Scripts" / "python.exe"
    if not py.exists():
        v.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([BASE_PY, "-m", "venv", str(v)], check=True)
        for pkg in (m.get("python") or {}).get("pip") or []:
            subprocess.run([str(py), "-m", "pip", "install", "-q", pkg], capture_output=True)
    return str(py)


def run_test(py, ws, name, timeout=900):
    """-> (passed, failed, ok, last lines). A test that crashes before its summary counts as (0, -1)."""
    try:
        r = subprocess.run([py, name], cwd=str(ws), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=ENV)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 0, -1, False, f"timed out after {timeout} s"
    mm = re.search(r"(\d+) passed, (\d+) failed\s*$", out)
    if not mm:
        return 0, -1, False, out[-500:]
    p, f = int(mm.group(1)), int(mm.group(2))
    fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("FAIL")]
    return p, f, r.returncode == 0 and f == 0 and p > 0, "\n".join(fails[:6])


# ── verify ───────────────────────────────────────────────────────────────────

SWAPS = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
         ast.Add: ast.Sub, ast.Sub: ast.Add, ast.And: ast.Or, ast.Or: ast.And}


def mutants(src):
    """Every small bug this file can get: (line, description, new source). One operator or number each."""
    tree = ast.parse(src)
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and type(node.ops[0]) in SWAPS:
            sites.append((node, "ops"))
        elif isinstance(node, (ast.BinOp, ast.BoolOp)) and type(node.op) in SWAPS:
            if not (isinstance(node, ast.BinOp) and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str)):
                sites.append((node, "op"))
        elif isinstance(node, ast.Constant) and type(node.value) is int and 1 < node.value < 10_000:
            sites.append((node, "int"))
    out = []
    for node, kind in sites:
        if kind == "ops":
            old = node.ops[0]
            node.ops[0] = SWAPS[type(old)]()
            what = f"{type(old).__name__} -> {type(node.ops[0]).__name__}"
        elif kind == "op":
            old = node.op
            node.op = SWAPS[type(old)]()
            what = f"{type(old).__name__} -> {type(node.op).__name__}"
        else:
            old = node.value
            node.value = old + 1
            what = f"{old} -> {old + 1}"
        try:
            out.append((getattr(node, "lineno", 0), what, ast.unparse(tree)))
        except Exception:
            pass
        if kind == "ops":
            node.ops[0] = old
        elif kind == "op":
            node.op = old
        else:
            node.value = old
    return out


def verify(pack, full=False, n_mutants=30):
    d, m = load(pack)
    py = pack_python(m)
    tests = tests_of(d)
    slow = set(m.get("slow_tests") or [])
    fast = [t for t in tests if t not in slow]
    bad = []
    print(f"pack {m['name']}: {len(tests)} test files, {len(json.loads((d / 'plan.json').read_text(encoding='utf-8'))['tasks'])} tasks")
    for need in m.get("needs") or []:
        p = fill(need["path"], m)
        if not Path(p).exists():
            bad.append(f"missing: {p} ({need.get('why')}); make it with: {need.get('make')}")
    for t in tests:
        if not (d / t).is_file():
            bad.append(f"the plan names {t} but the pack has no such file")
    if bad:
        print("\n".join("  PROBLEM " + b for b in bad))
        return 1

    import studio_trial as T                                  # undefined names, wrong use of the helpers
    scratch = Path(tempfile.mkdtemp(prefix="pack_verify_"))
    try:
        ref, empty = scratch / "reference", scratch / "empty"
        lay_out(d, m, empty)
        for t in tests:
            for p in T.static_problems(empty, t):
                bad.append(f"{t}: {p}")
        print("\n1. On " + ("the app as it is today" if m.get("base") else "an empty project") + " (every test must fail):")
        guards = set(m.get("guard_tests") or [])               # older tests kept to guard what already works
        for t in fast:
            p, f, ok, _ = run_test(py, empty, t, 300)
            if t in guards:
                print(f"   {t:34} {'passes: a guard for what already works' if ok else 'A GUARD THAT FAILS TODAY'}")
                if not ok:
                    bad.append(f"{t} is a guard test but fails on the app as it is today")
                continue
            print(f"   {t:34} {'fails, as it must' if not ok else 'PASSES ON NOTHING'}")
            if ok:
                bad.append(f"{t} passes on an empty project: it checks nothing")
        has_ref = bool(m.get("reference")) and (d / m["reference"]).is_dir()
        if not has_ref:
            print("\n(no reference build in this pack yet: the other two questions wait for one)")
        else:
            lay_out(d, m, ref, reference=True)
            print("\n2. On the reference build (every test must pass):")
            checks = 0
            for t in (tests if full else fast):
                t0 = time.time()
                p, f, ok, tail = run_test(py, ref, t)
                checks += p
                print(f"   {t:34} {p} passed, {f} failed  ({time.time() - t0:.0f} s)")
                if not ok:
                    bad.append(f"{t} does not pass on the reference build: {tail[:300]}")
            if not full and slow:
                print(f"   (skipped, slow: {', '.join(sorted(slow))}; --full runs them)")
            print(f"   {checks} checks pass")
            if n_mutants and not [b for b in bad if "reference build" in b]:
                bad += mutation(d, m, py, ref, fast, n_mutants, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print()
    if bad:
        print("NOT SOUND:\n" + "\n".join("  - " + b for b in bad))
        return 1
    print("SOUND: the tests fail on an empty project and pass on the reference build (see the catch rate above).")
    return 0


def mutation(d, m, py, ref, fast, n, scratch):
    skip = set(m.get("mutation_skip") or [])
    refdir = d / m["reference"]
    pool = []
    for f in sorted(refdir.rglob("*.py")):
        rel = f.relative_to(refdir).as_posix()
        if rel in skip or "tests/" in rel:
            continue
        for line, what, src in mutants(f.read_text(encoding="utf-8")):
            pool.append((rel, line, what, src))
    if not pool:
        print("\n3. Broken code: not tried (planted bugs are made for Python only; this pack's code is not Python)")
        return []
    picked = random.Random(11).sample(pool, min(n, len(pool)))
    quick = [t for t in fast if t not in set(m.get("window_tests") or [])]
    print(f"\n3. Broken code ({len(picked)} of {len(pool)} possible small bugs, one at a time; tests: {', '.join(Path(t).name for t in quick)}):")

    def one(i):
        rel, line, what, src = picked[i]
        w = scratch / f"m{i}"
        shutil.copytree(ref, w, ignore=shutil.ignore_patterns("__pycache__", "dist", "build"))
        (w / rel).write_text(src, encoding="utf-8")
        for t in quick:
            if not run_test(py, w, t, 180)[2]:
                shutil.rmtree(w, ignore_errors=True)
                return i, t
        shutil.rmtree(w, ignore_errors=True)
        return i, None

    survived = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(2, (os.cpu_count() or 4) // 2)) as ex:
        for i, by in ex.map(one, range(len(picked))):
            if by is None:
                survived.append(picked[i])
    killed = len(picked) - len(survived)
    rate = killed / max(1, len(picked))
    print(f"   caught {killed} of {len(picked)} ({rate:.0%})")
    for rel, line, what, _ in survived:
        print(f"   not caught: {rel} line {line}: {what}")
    (d / "VERIFY.json").write_text(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M"), "bugs_tried": len(picked), "caught": killed,
                                               "not_caught": [f"{r} line {ln}: {w}" for r, ln, w, _ in survived]}, indent=1), encoding="utf-8")
    # A number to compare test writers by, not a verdict: some planted bugs change nothing a user would see
    # (a 2-pixel gap made 3). Claude's WizTry tests score 53%; only a very low rate fails the pack.
    return [f"the tests catch only {rate:.0%} of small bugs (under 35%)"] if rate < 0.35 else []


# ── a workspace ──────────────────────────────────────────────────────────────

def journal(ws, who, what, **more):
    f = Path(ws) / ".studio" / "journal.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a", encoding="utf-8") as h:
        h.write(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M"), "who": who, "what": what, **more}, ensure_ascii=False) + "\n")


def git(ws, *a):
    return subprocess.run(["git", *a], cwd=str(ws), capture_output=True, text=True, encoding="utf-8", errors="replace")


def new(pack, ws):
    d, m = load(pack)
    ws = Path(ws)
    if ws.exists():
        sys.exit(f"{ws} already exists")
    for need in m.get("needs") or []:
        if not Path(fill(need["path"], m)).exists():
            sys.exit(f"missing: {fill(need['path'], m)}; make it with: {need.get('make')}")
    import studio_overnight as Q
    lay_out(d, m, ws)
    (ws / ".studio").mkdir()
    (ws / ".studio" / "pack.json").write_text(json.dumps({**m, "pack_dir": str(d), "laid_out": time.strftime("%Y-%m-%d %H:%M")},
                                                         indent=1), encoding="utf-8")
    if (d / "NOTES.md").is_file():
        shutil.copy(d / "NOTES.md", ws / ".studio" / "PACK_NOTES.md")
    (ws / "opencode.json").write_text(json.dumps(Q.OPENCODE_PROJECT, indent=1), encoding="utf-8")   # the builder's shell rules
    gi = ws / ".gitignore"
    have = gi.read_text(encoding="utf-8") if gi.exists() else ""
    gi.write_text(have.rstrip() + "".join(f"\n{x}" for x in (".venv/", ".foreman/", "__pycache__/", "*.pyc", "*.spec", ".nd_backups/")
                                          if x not in have) + "\n", encoding="utf-8")
    git(ws, "init", "-q")
    builder_rules(ws, m)
    journal(ws, "studio_pack", f"workspace made from pack {m['name']}")
    git(ws, "add", "-A")
    git(ws, "commit", "-q", "-m", f"{m['title']}: the plan and its tests, from pack {m['name']}")
    subprocess.run([BASE_PY, "-m", "venv", ".venv"], cwd=str(ws), check=True)
    for pkg in (m.get("python") or {}).get("pip") or []:
        subprocess.run([str(ws / ".venv" / "Scripts" / "python.exe"), "-m", "pip", "install", "-q", pkg], cwd=str(ws), capture_output=True)
    status(ws)
    git(ws, "add", "-A")
    git(ws, "commit", "-q", "-m", "handoff: nothing built yet")
    print(f"ready: {ws}\nbuild it with:\n  \"{sys.executable}\" \"{Path(__file__).resolve()}\" build \"{ws}\"")


def builder_rules(ws, m):
    """The shared working rules (packs/BUILDER_RULES.json) -> the workspace's plan conventions and the foreman's
    notes, so every task prompt carries them. Adds only what is missing; returns how many were added."""
    ws = Path(ws)
    src = json.loads((PACKS / "BUILDER_RULES.json").read_text(encoding="utf-8"))
    want = list(src["all"]) + list((src.get("kinds") or {}).get(m.get("kind"), []))
    plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
    conv = plan.setdefault("conventions", [])
    add = [r for r in want if r not in conv]
    if add:
        conv += add
        (ws / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    notes = ws / ".foreman" / "notes" / "10 Conventions.md"      # seeded from the plan once; never rewritten by the foreman
    if notes.exists():
        text = notes.read_text(encoding="utf-8")
        more = [r for r in want if r not in text]
        if more:
            notes.write_text(text.rstrip("\n") + "\n" + "".join(f"- {r}\n" for r in more), encoding="utf-8")
    return len(add)


def tweak(ws, name):
    """Tweak mode: a change to an app that is already built. A tweak is a folder in the pack (tweaks/<name>/:
    tweak.json + tests/) holding new tasks and the tests that judge them. They are added to the workspace's plan;
    the foreman keeps finished tasks finished and builds only the new ones, with every old test still guarding."""
    ws = Path(ws)
    m = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8"))
    td = Path(name) if Path(name).is_dir() else Path(m["pack_dir"]) / "tweaks" / name
    tw = json.loads((td / "tweak.json").read_text(encoding="utf-8"))
    if git(ws, "status", "--porcelain").stdout.strip():
        sys.exit("the workspace has uncommitted changes - commit or undo them first")
    plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
    have = {t["id"] for t in plan["tasks"]}
    clash = [t["id"] for t in tw["tasks"] if t["id"] in have]
    if clash:
        sys.exit(f"the plan already has {', '.join(clash)} (is this tweak applied already?)")
    for rel in tw.get("tests") or []:
        if (ws / rel).exists():
            sys.exit(f"{rel} already exists in the workspace")
        text = (td / rel).read_text(encoding="utf-8")
        (ws / rel).write_text(fill(text, m), encoding="utf-8")
    for rel in tw.get("tests_update") or []:               # an older test the pack has corrected since this workspace was made
        (ws / rel).write_text(fill((Path(m["pack_dir"]) / rel).read_text(encoding="utf-8"), m), encoding="utf-8")
    plan["tasks"] += tw["tasks"]
    # A tweak may change what the app is allowed to do (Delete ended "read-only"). The rules are in three places:
    # the plan, the foreman's notes (seeded from the plan once, then never overwritten) and the spec.
    notes = ws / ".foreman" / "notes" / "00 Rules.md"
    for old, new in tw.get("rules") or []:
        if old not in plan["rules"]:
            sys.exit(f"the plan has no rule: {old[:70]}...")
        plan["rules"][plan["rules"].index(old)] = new
        if notes.exists():
            text = notes.read_text(encoding="utf-8")
            if old not in text:
                sys.exit(f"{notes} does not have the rule: {old[:70]}... (edit it by hand, then run again)")
            notes.write_text(text.replace(old, new), encoding="utf-8")
    spec = (ws / "SPEC.md").read_text(encoding="utf-8")
    for old, new in tw.get("spec") or []:
        if old not in spec:
            sys.exit(f"SPEC.md does not have: {old[:70]}...")
        spec = spec.replace(old, new)
    (ws / "SPEC.md").write_text(spec.rstrip("\n") + "\n" + (tw.get("spec_add") or ""), encoding="utf-8")
    (ws / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    builder_rules(ws, m)
    journal(ws, "studio_pack", f"tweak {tw['name']} added ({', '.join(t['id'] for t in tw['tasks'])}): {tw['title']}", why=tw.get("why"))
    status(ws)
    git(ws, "add", "-A")
    git(ws, "commit", "-q", "-m", f"tweak {tw['name']}: {tw['title']} (tasks and tests, nothing built yet)")
    print(f"added {', '.join(t['id'] for t in tw['tasks'])} to {ws}\nbuild them with:\n  \"{sys.executable}\" \"{Path(__file__).resolve()}\" build \"{ws}\"")


def probe_problems(score):
    """The score, read the way a person would complain: each line is something a user would hit."""
    out = []
    kit = score.get("kit") or {}
    if kit.get("of") and kit.get("score") != kit.get("of"):
        wrong = [k for k, ok in (kit.get("detail") or {}).items() if not ok]
        out.append(f"the report on the fixture is wrong in: {', '.join(wrong) or kit.get('error')}")
    w = score.get("window")
    if w is None:
        return out
    if not w.get("opened"):
        return out + ["the window did not open: " + str(w.get("error") or "")[-300:]]
    for e in w.get("errors") or []:
        out.append(f"a button raised an error (invisible in the exe): {e}")
    if w.get("filedialog_imported") is False:
        out.append("the app never imports tkinter.filedialog: its folder dialog cannot work")
    if not w.get("labels"):
        out.append("no status text appeared after a scan was started")
    for i, t in enumerate(w.get("trees") or [], 1):
        if not t.get("mapped") or t.get("w", 0) < 50 or t.get("h", 0) < 50:
            out.append(f"list {i} is not visible ({t.get('w')}x{t.get('h')} pixels)")
        elif not t.get("rows"):
            out.append(f"list {i} is empty after the scan")
    for i, c in enumerate(w.get("canvases") or [], 1):
        if not c.get("mapped") or c.get("w", 0) < 50 or c.get("h", 0) < 50:
            out.append(f"drawing area {i} is not visible ({c.get('w')}x{c.get('h')} pixels)")
        elif not c.get("items"):
            out.append(f"drawing area {i} is empty after the scan")
    for t, r in (score.get("tests") or {}).items():
        if not str(r).endswith(", 0 failed") or str(r).startswith("0 passed"):
            out.append(f"{t}: {r}")
    return out


def status(ws):
    """Rewrite .studio/HANDOFF.md: everything the next agent (or person) needs to carry on, from the disk alone."""
    ws = Path(ws)
    sd = ws / ".studio"
    m = json.loads((sd / "pack.json").read_text(encoding="utf-8"))
    plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
    sf = ws / ".foreman" / "state.json"
    st = json.loads(sf.read_text(encoding="utf-8")).get("tasks", {}) if sf.exists() else {}
    me = f'"{sys.executable}" "{Path(__file__).resolve()}"'
    L = [f"# {m['title']}: where this build stands", "",
         f"Written {time.strftime('%Y-%m-%d %H:%M')} by `studio_pack.py status`. Do not edit: run it again.", "",
         "## What this is",
         f"- Workspace `{ws}`, made from the plan pack `{m['pack_dir']}`.",
         "- `SPEC.md` is what the app must be. `plan.json` is the tasks. `tests/` is how each task is judged.",
         "- The foreman (`nd_foreman.py`) gives one task at a time to the builder (OpenCode with a local model), runs the "
         "gates (allowed files, lint, the task's tests, nothing else broke), commits a pass, and undoes and retries a fail.",
         f"- Model: `{plan.get('model')}`. The pack's own notes: `.studio/PACK_NOTES.md`.", "",
         "## Tasks", "", "| Task | What | Status | Attempts | Last result |", "|---|---|---|---|---|"]
    stuck = []
    for t in plan["tasks"]:
        s = st.get(t["id"], {})
        att = s.get("attempts") or []
        last = att[-1] if att else {}
        res = "" if not last else ("passed" if last.get("verdict") == "pass" else f"{last.get('gate')}: " + str(last.get("detail") or "").split("\n")[0][:110])
        L.append(f"| {t['id']} | {t['title']} | {s.get('status') or 'not started'} | {len(att)} | {res.replace('|', '/')} |")
        if s.get("status") == "stuck":
            stuck.append((t, att))
    for t, att in stuck:
        L += ["", f"## Stuck: {t['id']} {t['title']}", f"Files it may change: {', '.join(t.get('files') or [])}. Its test: {t.get('tests')}.", ""]
        for a in att[-3:]:
            L += [f"**Attempt {a.get('n')}** ({a.get('model_used') or a.get('model')}, {a.get('secs')} s), failed the `{a.get('gate')}` gate:", "",
                  "```", str(a.get("detail") or "").strip()[:900], "```", "",
                  "The builder said: " + " ".join(str(a.get("reply") or "").split())[:400], ""]
        same = len({(a.get("gate"), str(a.get("detail") or "")[:160]) for a in att[-3:]}) == 1 and len(att) >= 2
        L += ["Reading it: " + ("every attempt failed the same way. Suspect the test or the brief before the builder: read the "
                                "test line that fails next to the brief." if same else
                                "the attempts failed in different ways: the task may be too big for one go; consider splitting it "
                                "in the pack, or a longer time limit."), ""]
    sc = sd / "score.json"
    if sc.exists():
        s = json.loads(sc.read_text(encoding="utf-8"))
        w = s.get("window") or {}
        L += ["", "## Score (studio_score.py)",
              f"- Report on the fixture: {(s.get('kit') or {}).get('score')} of {(s.get('kit') or {}).get('of')} {(s.get('kit') or {}).get('detail') or ''}",
              f"- Window: opened={w.get('opened')}, status after a scan={w.get('labels')}, lists={w.get('trees')}, treemap={w.get('canvases')}",
              "- Tests: " + "; ".join(f"{k} {v}" for k, v in (s.get("tests") or {}).items())]
        found = probe_problems(s)
        L += ["", "### What the scripted run found wrong" if found else "### The scripted run found nothing wrong (it is not a person: open the app too)"]
        L += [f"- {x}" for x in found]
    done = st and all((st.get(t["id"]) or {}).get("status") == "passed" for t in plan["tasks"])
    L += ["", "## Next step"]
    if not st:
        L += ["Nothing is built yet. The user starts the build (agents must not launch unattended builds):", "", f"    {me} build \"{ws}\""]
    elif done:
        L += ["Every task passed. Look at the app itself (run it; the score above is from a scripted run), then record it in "
              "the pack's NOTES.md. If this build is better than the pack's `reference/`, replace that."]
    elif not stuck:
        todo = [t["id"] for t in plan["tasks"] if (st.get(t["id"]) or {}).get("status") != "passed"]
        L += [f"Tasks waiting to be built: {', '.join(todo)}. The user starts the build (agents must not launch unattended builds):", "",
              f"    {me} build \"{ws}\""]
    else:
        L += ["1. Read the stuck sections above and decide: is the test wrong, the brief unclear, or the task too big?",
              f"2. A wrong test or brief is fixed in the PACK (`{m['pack_dir']}`), with a line in its NOTES.md; then copy the "
              "changed file here and commit. Check the pack still holds: " + f"`{me} verify {m['name']}`.",
              "3. Put the task back in the queue and let the user run the build again:", "",
              f"    \"{sys.executable}\" \"{FOREMAN}\" retry \"{ws / 'plan.json'}\" <task id>",
              f"    {me} build \"{ws}\""]
    L += ["", "## Rules for whoever works here",
          "- `tests/` and `plan.json` judge the work. Never change them to make a task pass; change them only when they are wrong, in the pack first.",
          "- The builder's shell is restricted by `opencode.json` (no copy, delete, move, installs or git history changes). Keep it.",
          "- Add a journal line for anything you decide or change: " + f"`{me} note \"{ws}\" \"<who>\" \"<what>\"`.",
          "- Foreman details per attempt: `.foreman/state.json`, `.foreman/run.log`, `.foreman/notes/20 Lessons.md`.", "",
          "## Journal (latest last)"]
    jf = sd / "journal.jsonl"
    if jf.exists():
        for line in jf.read_text(encoding="utf-8").splitlines()[-15:]:
            j = json.loads(line)
            L.append(f"- {j['when']} **{j['who']}**: {j['what']}")
    (sd / "HANDOFF.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return st


def build(ws, max_hours=6.0, rounds=1):
    """The unattended build. Proves the builder's shell rules first; scores and writes the handoff at the end."""
    ws = Path(ws)
    if not (ws / ".studio" / "pack.json").exists():
        sys.exit(f"{ws} was not made from a pack (studio_pack.py new)")
    import ctypes
    import studio_overnight as Q
    import studio_score
    Q.HOME.mkdir(parents=True, exist_ok=True)
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)      # no sleep while this runs
    run = {"ws": ws, "n": ws.name}
    Q.log(f"pack build started: {ws} (pid {os.getpid()})")
    t0 = time.time()
    try:
        Q.unload()
        ok, text = (True, "dry run") if Q.DRY else Q.prove_shell_rules()
        Q.log(f"shell rules check: {'OK' if ok else 'FAILED'} - {text}")
        if not ok:
            journal(ws, "studio_pack", "build not started: the builder's shell rules did not hold", detail=text)
            status(ws)
            return 1
        journal(ws, "studio_pack", f"build started (up to {max_hours} h, {rounds} extra round(s) for stuck tasks)")
        Q.foreman(run, "--max-hours", str(max_hours), timeout=int(max_hours * 3600) + 900)
        for r in range(rounds):                                # time is cheap here: stuck tasks get fresh attempts
            stuck = Q.stuck(run)
            if not stuck:
                break
            Q.log(f"round {r + 1}: fresh attempts for {stuck}")
            journal(ws, "studio_pack", f"fresh attempts for stuck tasks {', '.join(stuck)}")
            for tid in stuck:
                Q.sh([sys.executable, FOREMAN, "retry", ws / "plan.json", tid], Path(FOREMAN).parent, timeout=120, name=f"foreman retry {tid}")
            Q.foreman(run, "--max-hours", str(max_hours / 2), timeout=int(max_hours * 1800) + 900)
    except Q.Stop:
        Q.log("STOP file found - stopping")
        journal(ws, "studio_pack", "build stopped by the STOP file")
    except Exception as e:
        Q.log(f"build error: {e}")
        journal(ws, "studio_pack", f"build error: {e}")
    Q.close_leftovers(ws)
    Q.unload()
    try:
        if Q.DRY:
            raise RuntimeError("dry run")
        kind = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8")).get("kind")
        if kind != "windows-app":
            raise RuntimeError(f"studio_score only knows windows apps (this is a {kind}); the tests are the score")
        score = studio_score.score(ws)
        (ws / ".studio" / "score.json").write_text(json.dumps(score, indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        Q.log(f"scoring failed: {e}")
    c = Q.counts(run)
    journal(ws, "studio_pack", f"build finished after {(time.time() - t0) / 3600:.1f} h: {c}")
    status(ws)
    Q.commit(ws, "handoff after the build")
    Q.log(f"pack build finished: {c}. Read {ws / '.studio' / 'HANDOFF.md'}")
    return 0


def opt(argv, name, default):
    if name in argv:
        i = argv.index(name)
        v = argv[i + 1]
        del argv[i:i + 2]
        return v
    return default


def main():
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "verify":
        full = "--full" in a
        n = int(opt(a, "--mutants", 30))
        sys.exit(verify(a[1], full, n))
    if cmd == "new":
        new(a[1], a[2])
    elif cmd == "build":
        hours, rounds = float(opt(a, "--max-hours", 6)), int(opt(a, "--rounds", 1))
        sys.exit(build(a[1], hours, rounds))
    elif cmd == "tweak":
        tweak(a[1], a[2])
    elif cmd == "rules":
        ws = Path(a[1])
        if git(ws, "status", "--porcelain").stdout.strip():
            sys.exit("the workspace has uncommitted changes - commit or undo them first")
        n = builder_rules(ws, json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8")))
        if n:
            journal(ws, "studio_pack", f"{n} shared builder rules added to the plan (packs/BUILDER_RULES.json)")
            status(ws)
            git(ws, "add", "-A")
            git(ws, "commit", "-q", "-m", f"plan: {n} shared builder rules")
        print(f"{n} rules added")
    elif cmd == "status":
        status(a[1])
        print(Path(a[1]) / ".studio" / "HANDOFF.md")
    elif cmd == "note":
        journal(a[1], a[2], a[3])
        status(a[1])
        git(a[1], "add", ".studio")
        git(a[1], "commit", "-q", "-m", f"journal: {a[3][:60]}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
