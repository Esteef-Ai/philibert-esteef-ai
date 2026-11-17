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
    python dev/studio_pack.py look <workspace> [--vision MODEL]       pictures at several screen sizes + what is new and wrong
    python dev/studio_pack.py quick <workspace> "<what to change>" --files a,b [--test tests/x.py] [--minutes 20]
                                                                      a small change with no plan pack: one task, every
                                                                      older test guarding, before/after pictures
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
    d = (Path(pack) if Path(pack).is_dir() else PACKS / str(pack)).resolve()   # workspaces keep it: never relative
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


def lay_base(m, dest):
    """The app a pack starts from, and nothing of the pack itself (an empty folder for a new app)."""
    dest.mkdir(parents=True, exist_ok=True)
    if m.get("base"):
        # An EXISTING app to change, not an empty folder to fill: the workspace starts as a copy of it. The big
        # folders nobody edits (node_modules) are linked, not copied: a junction costs nothing and git ignores it.
        base, links = Path(m["base"]), set(m.get("base_links") or [])
        shutil.copytree(base, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", ".git", *links))
        for n in links:
            if (base / n).is_dir() and not (dest / n).exists():
                subprocess.run(["cmd", "/c", "mklink", "/J", str(dest / n), str(base / n)], capture_output=True, check=True)


def unlink_base(m, dest):
    """Take a copy's links away before the copy is deleted, so nothing can follow them into the real folder."""
    for n in m.get("base_links") or []:
        if (Path(dest) / n).exists():
            try:
                os.rmdir(Path(dest) / n)
            except OSError:
                pass


def lay_out(d, m, dest, reference=False):
    """The pack's files as a workspace gets them (placeholders filled). reference=True adds the good build."""
    lay_base(m, dest)
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
    mm = ([None] + list(re.finditer(r"(?m)^\s*(\d+) passed, (\d+) failed\s*$", out)))[-1]   # the last such LINE: stderr noise may follow it
    if not mm:
        return 0, -1, False, out[-500:]
    p, f = int(mm.group(1)), int(mm.group(2))
    fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("FAIL")]
    return p, f, r.returncode == 0 and f == 0 and p > 0, "\n".join(fails[:6])


def judge(ws, timeout=900):
    """Every test of the workspace's pack, AS THE PACK HAS THEM TODAY, run on a copy of what the workspace holds.
    A workspace keeps the tests of the day it was made; a test corrected since would judge old builds unfairly.
    -> {test: {"passed": n, "failed": n (-1: crashed), "ok": bool, "fails": [...]}}"""
    ws = Path(ws)
    m = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8"))
    d = Path(m["pack_dir"])
    links = set(m.get("base_links") or [])
    py = str(ws / ".venv" / "Scripts" / "python.exe")
    scratch = Path(tempfile.mkdtemp(prefix="pack_judge_"))
    out = {}
    try:
        copy = scratch / "built"
        shutil.copytree(ws, copy, ignore=shutil.ignore_patterns(".venv", ".foreman", ".git", "__pycache__", ".studio", "tests", *links))
        for n in links:
            if (ws / n).is_dir():
                subprocess.run(["cmd", "/c", "mklink", "/J", str(copy / n), str((ws / n).resolve())], capture_output=True)
        shutil.copytree(d / "tests", copy / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        for rel in m.get("fill_in") or []:
            if rel.startswith("tests/") and (copy / rel).is_file():
                (copy / rel).write_text(fill((copy / rel).read_text(encoding="utf-8"), m), encoding="utf-8")
        for t in tests_of(d):
            p, f, ok, tail = run_test(py, copy, t, timeout)
            out[t] = {"passed": p, "failed": f, "ok": ok, "fails": tail.splitlines()[:6]}
    finally:
        unlink_base(m, scratch / "built")
        shutil.rmtree(scratch, ignore_errors=True)
    return out


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
    gaps = contract_gaps(d, m)
    print("\n4. Names the tests need (a global, an id, a served file) that the app does not have yet: are they in SPEC.md?")
    if not gaps:
        print("   yes: every such name is given by the spec")
    for name, where in sorted(gaps.items()):
        print(f"   NOT IN THE SPEC: {name}   (needed by {', '.join(sorted(set(where)))})")
        bad.append(f"the spec never gives the name {name}, which {where[0]} needs: add it to SPEC.md under 'Names that are fixed'")
    print()
    if bad:
        print("NOT SOUND:\n" + "\n".join("  - " + b for b in bad))
        return 1
    print("SOUND: the tests fail on an empty project and pass on the reference build (see the catch rate above).")
    return 0


NAME_RE = re.compile(r"""window\.[A-Za-z]\w+|\#[a-z][\w-]{3,}|data-[a-z][a-z-]+|/[\w-]+\.(?:js|css|html)\b""")
TEXT_EXT = {".js", ".mjs", ".html", ".css", ".py", ".json", ".java", ".xml", ".ts", ".md", ".txt"}


def contract_gaps(d, m):
    """Names the pack's tests need that only the tests know: a global (window.x), an element id (#x), a data-
    attribute or a served file (/x.js) that a non-guard test uses, that the app before the change does not have, and
    that SPEC.md never gives. Whoever plans from the spec alone (a local planner, a person) cannot pass such a test:
    two blind trials failed on exactly this (2026-11-14). -> {name: [test files]}"""
    d = Path(d)
    spec = (d / "SPEC.md").read_text(encoding="utf-8") if (d / "SPEC.md").is_file() else ""
    guards = set(m.get("guard_tests") or [])
    helpers = "".join(p.read_text(encoding="utf-8", errors="replace") for p in (d / "tests").glob("_*.py"))
    old = ""
    base = Path(fill(m["base"], m)) if m.get("base") else None
    if base and base.is_dir():
        skip = set(m.get("base_links") or []) | {"node_modules", ".git", "vendor", "tests"}
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in TEXT_EXT and not (set(p.relative_to(base).parts) & skip) and p.stat().st_size < 2_000_000:
                old += p.read_text(encoding="utf-8", errors="replace")
    gaps = {}
    for tname in tests_of(d):
        if tname in guards or not (d / tname).is_file():
            continue
        src = (d / tname).read_text(encoding="utf-8", errors="replace")
        for name in sorted(set(NAME_RE.findall(src))):
            bare = name.split(".", 1)[1] if name.startswith("window.") else name.lstrip("#/")
            if bare.startswith("__") or name in old or bare in old or name in helpers:
                continue                                       # the test's own probe, or already in the app, or a helper's
            if re.search(r"window\." + re.escape(bare) + r"\s*=[^=]", src):
                continue                                       # the test itself sets it
            if name.startswith("#") and re.fullmatch(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8}|rgb|rrggbb)", name):
                continue                                       # a colour, not an element id
            if name.startswith("data-"):
                camel = re.sub(r"-(\w)", lambda g: g.group(1).upper(), name[5:])
                if re.search(r"dataset\." + camel + r"\s*=[^=]", src) or f"setAttribute('{name}'" in src or f'setAttribute("{name}"' in src:
                    continue                                   # the test tags elements with it itself
            if bare not in spec:
                gaps.setdefault(name, []).append(tname)
    return gaps


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


def pack_now(m):
    """The pack's PACK.json as it is today (a workspace keeps the copy from the day it was made)."""
    try:
        return json.loads((Path(m["pack_dir"]) / "PACK.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return {}


def look(ws, vision=None, log=print):
    """The look step (dev/studio_look.py) on a workspace: pictures of every screen at several sizes, and the findings
    that were not there before. "Before" is the pictures a quick change took when it started, else the app the pack
    started from. -> the summary (also .studio/look/summary.json), or None when the pack has no look driver."""
    import studio_look as LK
    ws = Path(ws)
    m = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8"))
    lk = m.get("look") or pack_now(m).get("look") or {}
    driver = ws / lk.get("driver", "-")
    if not driver.is_file():
        driver = Path(m["pack_dir"]) / lk.get("driver", "-")
    if not lk or not driver.is_file():
        return None
    ex = ws / ".git" / "info" / "exclude"                     # pictures stay out of git and out of the builder's diff
    if ex.parent.is_dir() and ".studio/look" not in (ex.read_text(encoding="utf-8") if ex.exists() else ""):
        with open(ex, "a", encoding="utf-8") as h:
            h.write("\n.studio/look/\n.studio/look_before/\n.studio/look_base/\n")
    py = str(ws / ".venv" / "Scripts" / "python.exe")
    tool = str(Path(LK.__file__).resolve())

    def shoot(folder, out, more=()):
        shutil.rmtree(out, ignore_errors=True)
        r = subprocess.run([py, tool, "run", str(folder), str(out), "--driver", str(driver), *more], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=ENV, timeout=1800)
        f = Path(out) / "look.json"
        if not f.is_file():
            raise RuntimeError("the look step did not run: " + ((r.stdout or "") + (r.stderr or ""))[-400:])
        return json.loads(f.read_text(encoding="utf-8"))

    def usable(folder):                                       # pictures judged by the checks as they are today
        try:
            return json.loads((folder / "look.json").read_text(encoding="utf-8")).get("audit") == LK.audit_version()
        except (OSError, ValueError):
            return False

    before_dir, before = ws / ".studio" / "look_before", None
    if not usable(before_dir):
        before_dir = ws / ".studio" / "look_base"
        if not usable(before_dir) and m.get("base"):
            scratch = Path(tempfile.mkdtemp(prefix="look_base_"))
            try:
                log("look: pictures of the app as it was (once per workspace) ...")
                lay_out(Path(m["pack_dir"]), {**m, **{k: v for k, v in pack_now(m).items() if k in ("base", "base_links")}}, scratch / "app")
                shoot(scratch / "app", before_dir)
            finally:
                unlink_base(m, scratch / "app")
                shutil.rmtree(scratch, ignore_errors=True)
    if usable(before_dir):
        before = json.loads((before_dir / "look.json").read_text(encoding="utf-8"))
    log("look: pictures of the app as it is now ...")
    out = ws / ".studio" / "look"
    after = shoot(ws, out, ["--vision", vision] if vision else [])
    new, gone, okd = LK.compare(before, after, lk.get("accept") or [])
    md = LK.report(after, new, gone, okd, out, before_dir if before else None, title=f"{m['title']}: the look step")
    summary = {"when": after["when"], "screens": len(after["screens"]), "new": new, "gone": len(gone), "accepted": len(okd),
               "not_reached": after["not_reached"], "report": str(md), "compared_with": str(before_dir) if before else None}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"look: {summary['screens']} screens, {len(new)} new finding(s), {len(after['not_reached'])} not reached -> {md}")
    return summary


QUICK_TEST = '''"""{tid}: {title}

Written by studio_pack.py quick. It proves only that the named files changed and still parse. Whether the change is
RIGHT is judged by every older test (they must all still pass) and by the before/after pictures of the look step.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
BEFORE = {before}
passed = failed = 0


def check(label, ok, got=""):
    global passed, failed
    passed, failed = passed + bool(ok), failed + (not ok)
    print(("PASS " if ok else "FAIL ") + label + ("" if ok or got == "" else f" - got {{got}}"))


def digest(f):
    p = WS / f
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""


changed = [f for f, h in BEFORE.items() if digest(f) != h]
check("at least one of the named files was changed (" + ", ".join(BEFORE) + ")", bool(changed), "nothing changed")
for f in BEFORE:
    p = WS / f
    if not p.is_file():
        continue
    if p.suffix == ".py":
        try:
            compile(p.read_text(encoding="utf-8"), f, "exec")
            check(f + " is valid Python", True)
        except SyntaxError as e:
            check(f + " is valid Python", False, e)
    elif p.suffix in (".js", ".mjs", ".cjs"):
        r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
        check(f + " is valid JavaScript (node --check)", r.returncode == 0, (r.stderr or "").strip()[-200:])
    elif p.suffix == ".json":
        try:
            json.loads(p.read_text(encoding="utf-8"))
            check(f + " is valid JSON", True)
        except ValueError as e:
            check(f + " is valid JSON", False, e)
    elif p.suffix in (".html", ".htm"):
        t = p.read_text(encoding="utf-8")
        check(f + " still ends with </html> and its <script> tags are closed", t.rstrip().endswith("</html>")
              and t.count("<script") == t.count("</script>"), (t.count("<script"), t.count("</script>")))
print(f"{{passed}} passed, {{failed}} failed")
sys.exit(1 if failed else 0)
'''


def quick(ws, request, files, test=None, minutes=20, context=()):
    """The fast lane: a small change to a built workspace, with no plan pack. One task is added to the plan: the
    request is its brief, the named files are all it may touch, every older test guards it (the foreman's "nothing
    that passed may break" gate), and the look step takes the "before" pictures now. The user starts the build."""
    import hashlib
    ws = Path(ws)
    m = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8"))
    if git(ws, "status", "--porcelain").stdout.strip():
        sys.exit("the workspace has uncommitted changes - commit or undo them first")
    plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
    sf = ws / ".foreman" / "state.json"
    st = json.loads(sf.read_text(encoding="utf-8")).get("tasks", {}) if sf.exists() else {}
    waiting = [t["id"] for t in plan["tasks"] if (st.get(t["id"]) or {}).get("status") != "passed"]
    if waiting:
        sys.exit(f"finish the build first: {', '.join(waiting)} have not passed (a quick change needs a working app to guard)")
    files = [f.replace("\\", "/") for f in files if f]
    if not files:
        sys.exit("name the files the change may touch: --files public/index.html,public/tvnav.js")
    bad = [f for f in files if f.startswith(("tests/", ".foreman/", ".studio/")) or f == "plan.json"]
    if bad:
        sys.exit(f"a change may not touch {', '.join(bad)}")
    n = 1 + sum(1 for t in plan["tasks"] if re.fullmatch(r"Q\d+", t["id"]))
    tid = f"Q{n:02d}"
    title = " ".join(request.split())[:70]
    if test:
        if not (ws / test).is_file():
            sys.exit(f"{test} is not in the workspace (write it there first, or leave --test out)")
        tests = [test]
    else:
        tests = [f"tests/test_{tid.lower()}_changed.py"]
        before = {f: (hashlib.sha256((ws / f).read_bytes()).hexdigest() if (ws / f).is_file() else "") for f in files}
        (ws / tests[0]).write_text(QUICK_TEST.format(tid=tid, title=title.replace('"', "'"), before=json.dumps(before, indent=1)),
                                   encoding="utf-8")
    plan["tasks"].append({
        "id": tid, "title": title, "depends_on": [], "files": files, "context": list(dict.fromkeys([*tests, *context])),
        "tests": tests, "minutes": minutes, "attempts": 2,
        "brief": (f"A small change to the app as it is now. What is wanted:\n\n{request.strip()}\n\n"
                  f"You may change only: {', '.join(files)}. Make the smallest change that does this and nothing else: "
                  "no tidying, no renaming, no reformatting of lines you did not need to touch. Every test already in "
                  "tests/ passes now and must still pass when you finish; run the ones that cover what you touched. "
                  + ("" if test else f"`{tests[0]}` only proves the files changed and still parse; it does not tell you "
                     "the change is right, so read the code around your change and check it does what is asked.")),
        "done_when": [f"{tests[0]} prints 0 failed", "every older test still prints 0 failed"]})
    (ws / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    journal(ws, "studio_pack", f"quick change {tid} added: {title}", files=files)
    status(ws)
    git(ws, "add", "-A")
    git(ws, "commit", "-q", "-m", f"quick change {tid}: {title} (the task, nothing built yet)")
    if m.get("look") or pack_now(m).get("look"):              # the "before" pictures, from the app as it is this minute
        try:
            shutil.rmtree(ws / ".studio" / "look_before", ignore_errors=True)
            s = look(ws)
            if s:
                shutil.copytree(ws / ".studio" / "look", ws / ".studio" / "look_before")
                print(f"before pictures: {ws / '.studio' / 'look_before'}")
        except Exception as e:
            print(f"(no before pictures: {e})")
    print(f"added {tid} to {ws}\nbuild it with:\n  \"{sys.executable}\" \"{Path(__file__).resolve()}\" build \"{ws}\"")


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
    try:
        suspects = json.loads((sd / "suspects.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        suspects = []
    if suspects:
        L += ["", "## Suspect tests (studio_suspect.py): read these before blaming the builder", ""]
        for f in suspects:
            L += [f"- **{f['task']}**, `{f['test']}` ({'certain' if f['certain'] else 'likely'}): {f['why']}", "",
                  "```", str(f.get("tail") or "").strip()[:600], "```", ""]
    try:
        lk = json.loads((sd / "look" / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        lk = None
    if lk:
        L += ["", f"## The look step ({lk['when']}, {lk['screens']} screens)",
              f"Pictures and the full list: `{lk['report']}`. Compared with: `{lk.get('compared_with') or 'nothing (a new app)'}`.", ""]
        L += [f"- NEW {f['size']} {f['screen']}: {f['kind']} `{f['where']}`: {f['why']}" for f in lk["new"][:25]]
        L += [f"- not reached: {n['size']} {n['screen']}: {n['why'][:160]}" for n in lk["not_reached"][:10]]
        if not lk["new"] and not lk["not_reached"]:
            L += ["- nothing new was found by the mechanical checks (open the pictures all the same)"]
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
    import threading
    import studio_overnight as Q
    import studio_score
    import studio_suspect
    watcher_stop = threading.Event()
    Q.HOME.mkdir(parents=True, exist_ok=True)
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)      # no sleep while this runs
    run = {"ws": ws, "n": ws.name}
    m_ws = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8"))
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
        threading.Thread(target=studio_suspect.watch, args=(ws, watcher_stop, Q.log), daemon=True).start()
        # beside the foreman: is a failing test the one at fault? (studio_suspect.py)
        Q.foreman(run, "--max-hours", str(max_hours), timeout=int(max_hours * 3600) + Q.TASK_MARGIN)
        if not (ws / ".foreman" / "state.json").is_file():       # the foreman refused the plan before any task
            Q.log("build not started: the foreman refused the plan (its reasons are just above). Nothing was built.")
            journal(ws, "studio_pack", "build not started: the foreman refused the plan; nothing was built")
            watcher_stop.set()
            Q.unload()
            status(ws)
            return 1
        for r in range(rounds):                                # time is cheap here: stuck tasks get fresh attempts
            suspect = {f["task"] for f in studio_suspect.check(ws)}
            if suspect and m_ws.get("plan_only"):
                # The pack's own tests, proven on the reference build (blind5, 2026-11-16: T01's test, passed by blind4's
                # build, was called suspect and the two fresh rounds never ran). A warning, never a stop.
                Q.log(f"suspect test(s) for {sorted(suspect)}, but these are the pack's proven tests: fresh attempts anyway")
                suspect = set()
            if suspect:
                Q.log(f"no fresh attempts for {sorted(suspect)}: their failing test is suspect (see the handoff)")
                journal(ws, "studio_pack", f"suspect test(s) in {', '.join(sorted(suspect))}: no fresh attempts until someone reads them")
            stuck = [t for t in Q.stuck(run) if t not in suspect]
            if not stuck:
                break
            Q.log(f"round {r + 1}: fresh attempts for {stuck}")
            journal(ws, "studio_pack", f"fresh attempts for stuck tasks {', '.join(stuck)}")
            for tid in stuck:
                try:                                           # the best failed attempt becomes the start (studio_salvage.py)
                    import studio_salvage
                    studio_salvage.salvage(ws, tid, apply=True, log=Q.log)
                except Exception as e:
                    Q.log(f"salvage {tid} failed, the fresh attempts start from the last pass: {e}")
                try:
                    studio_salvage.keep_rounds(ws, tid)        # else the fresh round overwrites these transcripts
                except Exception as e:
                    Q.log(f"could not set {tid}'s transcripts aside: {e}")
                Q.sh([sys.executable, FOREMAN, "retry", ws / "plan.json", tid], Path(FOREMAN).parent, timeout=120, name=f"foreman retry {tid}")
            Q.foreman(run, "--max-hours", str(max_hours / 2), timeout=int(max_hours * 1800) + Q.TASK_MARGIN)
        # The last round's attempts were never weighed (salvage only ran BEFORE a round): keep the best as the start
        # of the next build. blind5's T05: round 3 reached 40 of 54 and the build ended at 22 (2026-11-16).
        for tid in Q.stuck(run):
            try:
                import studio_salvage
                studio_salvage.salvage(ws, tid, apply=True, log=Q.log)
            except Exception as e:
                Q.log(f"final salvage {tid} failed: {e}")
    except Q.Stop:
        Q.log("STOP file found - stopping")
        journal(ws, "studio_pack", "build stopped by the STOP file")
    except Exception as e:
        Q.log(f"build error: {e}")
        journal(ws, "studio_pack", f"build error: {e}")
    watcher_stop.set()
    Q.close_leftovers(ws)
    Q.unload()
    try:
        studio_suspect.check(ws)                               # the last word, written to .studio/suspects.json
    except Exception as e:
        Q.log(f"suspect check failed: {e}")
    try:
        if not Q.DRY:
            look(ws, log=Q.log)                                # pictures and what is new in them, for the handoff
    except Exception as e:
        Q.log(f"look step failed: {e}")
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
    for stream in (sys.stdout, sys.stderr):                    # a page's own text (bullets, emoji) must not crash a Windows console
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
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
    elif cmd == "look":
        vision = opt(a, "--vision", None)
        s = look(a[1], vision)
        if s is None:
            sys.exit("this workspace's pack has no look driver (PACK.json \"look\")")
        status(a[1])
        git(a[1], "add", ".studio")
        git(a[1], "commit", "-q", "-m", f"look step: {len(s['new'])} new finding(s)")
        for f in s["new"]:
            print(f"  NEW {f['size']} {f['screen']}: {f['kind']} {f['where']}: {f['why']}")
        print(s["report"])
    elif cmd == "quick":
        files = opt(a, "--files", "").split(",")
        test, minutes = opt(a, "--test", None), int(opt(a, "--minutes", 20))
        context = [c for c in opt(a, "--context", "").split(",") if c]
        if len(a) < 3:
            sys.exit(__doc__)
        quick(a[1], a[2], files, test, minutes, context)
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
