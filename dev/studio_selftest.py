"""Self-test of the studio tools around the builder: the look step, suspect tests, the fast lane, the blind planner
trial and the bench. No model is called and no build is started. It uses the built workspace C:\PCodeTest\lackluster2.

    python dev/studio_selftest.py [look] [suspect] [quick] [blind] [bench]      (all five without arguments; about 8 minutes)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEV = Path(__file__).resolve().parent
sys.path.insert(0, str(DEV))
import studio_look as LK  # noqa: E402
import studio_pack as P  # noqa: E402
import studio_suspect as SU  # noqa: E402

WS2 = Path(r"C:\PCodeTest\lackluster2")
PY2 = str(WS2 / ".venv" / "Scripts" / "python.exe")
ok_all = []


def check(label, ok, got=""):
    ok_all.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + label + ("" if ok or got == "" else f" - got {str(got)[:400]}"), flush=True)


def git(ws, *a):
    return subprocess.run(["git", *a], cwd=str(ws), capture_output=True, text=True, encoding="utf-8", errors="replace")


def section(s):
    print(f"\n== {s} ==", flush=True)


which = set(sys.argv[1:]) or {"look", "suspect", "quick", "blind", "bench"}
tmp = Path(tempfile.mkdtemp(prefix="studio_selftest_"))
try:
    if "look" in which:
        section("look: a planted fault is found, and only that")
        app = tmp / "planted"
        shutil.copytree(WS2, app, ignore=shutil.ignore_patterns(".venv", ".foreman", ".git", "__pycache__", ".studio", "node_modules"))
        subprocess.run(["cmd", "/c", "mklink", "/J", str(app / "node_modules"), str((WS2 / "node_modules").resolve())], capture_output=True)
        page = app / "public" / "index.html"
        t = page.read_text(encoding="utf-8")
        page.write_text(t.replace("</head>", "<style>.btn-playnow{position:relative; left:120px;}</style>\n</head>", 1), encoding="utf-8")
        driver = P.PACKS / "lackluster_remote" / "tests" / "_look.py"
        r = subprocess.run([PY2, str(DEV / "studio_look.py"), "run", str(app), str(tmp / "planted_out"), "--driver", str(driver)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=P.ENV)
        after = json.loads((tmp / "planted_out" / "look.json").read_text(encoding="utf-8"))
        before = json.loads((WS2 / ".studio" / "look_base" / "look.json").read_text(encoding="utf-8"))
        new, gone, _ = LK.compare(before, after)
        check("the run reached every screen", not after["not_reached"] and len(after["screens"]) == 18, after["not_reached"][:2])
        check("a button pushed 120 px off the right edge produces a new finding", bool(new), new[:3])
        check("... of the right kind: something cut off, or a screen that now scrolls sideways", {f["kind"] for f in new} <= {"cut-off", "page-wider"},
              sorted({f["kind"] for f in new}))
        check("... at every size where it happens (960 wide at least)", any(f["size"] == "960x540" for f in new), sorted({f["size"] for f in new}))
        print("   new:", sorted({(f["kind"], f["where"][:40]) for f in new}))
        os.rmdir(app / "node_modules")

        section("look: the same app looked at twice gives nothing new (a false alarm on blind1, 2026-11-14)")
        same = []
        for n in ("same_a", "same_b"):
            subprocess.run([PY2, str(DEV / "studio_look.py"), "run", str(WS2), str(tmp / n), "--driver", str(driver)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env=P.ENV)
            same.append(json.loads((tmp / n / "look.json").read_text(encoding="utf-8")))
        check("every look walks the app more than once", all(s.get("passes", 1) >= 2 for s in same), [s.get("passes") for s in same])
        for a_, b_, label in ((0, 1, "first as before, second as after"), (1, 0, "second as before, first as after")):
            new, gone, _ = LK.compare(same[a_], same[b_])
            check(f"an unchanged app, {label}: 0 new findings", not new, [LK.key(f) for f in new][:4])
        print("   findings that did not show on every walk (not counted):", [len(s.get("unstable") or []) for s in same])

    if "suspect" in which:
        section("suspect tests")
        ws = tmp / "sus"
        (ws / "tests").mkdir(parents=True)
        (ws / ".studio").mkdir()
        (ws / ".foreman").mkdir()
        (ws / "app.txt").write_text("one\n")
        (ws / "tests" / "test_guard.py").write_text("print('FAIL the browser has one tab - got 2')\nprint('3 passed, 1 failed')\nraise SystemExit(1)\n")
        (ws / "tests" / "test_ok.py").write_text("print('PASS fine')\nprint('1 passed, 0 failed')\n")
        (ws / ".gitignore").write_text(".foreman/\n")
        (ws / ".studio" / "pack.json").write_text(json.dumps({"guard_tests": ["tests/test_guard.py", "tests/test_ok.py"], "base_links": []}))
        git(ws, "init", "-q")
        git(ws, "add", "-A")
        git(ws, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "start")
        sha = git(ws, "rev-parse", "HEAD").stdout.strip()
        SU_py = SU.check.__globals__

        def state(tasks):
            (ws / ".foreman" / "state.json").write_text(json.dumps({"tasks": tasks, "green": {}}))
            SU._done.clear()

        # no .venv in this synthetic workspace: use this Python
        (ws / ".venv" / "Scripts").mkdir(parents=True)
        shutil.copy(sys.executable, ws / ".venv" / "Scripts" / "python.exe") if False else None
        real_run = SU.run_test
        SU.run_test = lambda py, folder, name, timeout=600: real_run(sys.executable, folder, name, timeout)
        fail = lambda test, reply, lines="FAIL the browser has one tab - got 2": {"verdict": "fail", "gate": "tests", "reply": reply,  # noqa: E731
                                                                               "detail": f"`{test}` does not pass (3 passed, 1 failed):\n{lines}"}
        state({"T01": {"status": "running", "start_sha": sha, "attempts": [fail("tests/test_guard.py", "I rewrote the file")]}})
        f = SU.check(ws)
        check("a guard test that fails on untouched code is a CERTAIN suspect after one attempt", len(f) == 1 and f[0]["certain"] and f[0]["kind"] == "fails-untouched", f)
        check("... and the finding is written to .studio/suspects.json", json.loads((ws / ".studio" / "suspects.json").read_text())[0]["task"] == "T01")
        state({"T01": {"status": "running", "start_sha": sha, "attempts": [fail("tests/test_ok.py", "I rewrote the file", "FAIL something real")]}})
        f = SU.check(ws)
        check("a guard test that passes on untouched code is not a suspect (the builder broke it)", f == [], f)
        state({"T02": {"status": "stuck", "start_sha": sha, "attempts": [fail("tests/test_new.py", "first I tried A", "FAIL speed (took 0.20 s)"),
                                                                        fail("tests/test_new.py", "then a different approach B", "FAIL speed (took 0.31 s)")]}})
        f = SU.check(ws)
        check("the same failing checks twice with different work is a LIKELY suspect (numbers in the lines ignored)",
              len(f) == 1 and not f[0]["certain"] and f[0]["kind"] == "same-failure", f)
        state({"T02": {"status": "stuck", "start_sha": sha, "attempts": [fail("tests/test_new.py", "same", "FAIL a"), fail("tests/test_new.py", "same", "FAIL a")]}})
        check("the same failure with the same reply twice is not flagged (the builder repeated itself)", SU.check(ws) == [])
        state({"T02": {"status": "stuck", "start_sha": sha, "attempts": [fail("tests/test_new.py", "x", "FAIL a"), fail("tests/test_new.py", "y", "FAIL b")]}})
        check("different failures are not flagged", SU.check(ws) == [])
        state({"T02": {"status": "passed", "start_sha": sha, "attempts": [fail("tests/test_guard.py", "x"), {"verdict": "pass"}]}})
        check("a task that passed in the end is not flagged", SU.check(ws) == [])
        SU.run_test = real_run
        # the handoff shows it
        state({"T01": {"status": "stuck", "start_sha": sha, "attempts": [fail("tests/test_guard.py", "I rewrote the file")]}})
        SU.run_test = lambda py, folder, name, timeout=600: real_run(sys.executable, folder, name, timeout)
        SU.check(ws)
        SU.run_test = real_run

    if "quick" in which:
        section("quick: the fast lane on a clone of the built workspace")
        q = tmp / "q"
        subprocess.run(["git", "clone", "-q", str(WS2), str(q)], capture_output=True)
        (q / ".foreman").mkdir(exist_ok=True)
        shutil.copy(WS2 / ".foreman" / "state.json", q / ".foreman" / "state.json")
        git(q, "config", "user.name", "selftest")
        git(q, "config", "user.email", "selftest@example.invalid")
        r = subprocess.run([sys.executable, str(DEV / "studio_pack.py"), "quick", str(q), "Make the Play Now button say Watch Now. Only its label changes.",
                            "--files", "public/index.html"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        plan = json.loads((q / "plan.json").read_text(encoding="utf-8"))
        t = plan["tasks"][-1]
        check("a task Q01 is added to the plan", t["id"] == "Q01" and t["files"] == ["public/index.html"], out[-400:])
        check("... limited to 2 attempts and 20 minutes, with the request in its brief", t.get("attempts") == 2 and t.get("minutes") == 20 and "Watch Now" in t["brief"])
        qt = q / "tests" / "test_q01_changed.py"
        check("its change-proof test is written", qt.is_file())
        r1 = subprocess.run([sys.executable, str(qt)], cwd=str(q), capture_output=True, text=True)
        check("the test fails while nothing has changed", r1.returncode == 1 and "FAIL at least one of the named files was changed" in r1.stdout, r1.stdout[-300:])
        page = q / "public" / "index.html"
        page.write_text(page.read_text(encoding="utf-8").replace("Play Now", "Watch Now"), encoding="utf-8")
        r2 = subprocess.run([sys.executable, str(qt)], cwd=str(q), capture_output=True, text=True)
        check("... and passes once the file is changed and still whole", r2.returncode == 0 and r2.stdout.strip().endswith("2 passed, 0 failed"), r2.stdout[-300:])
        check("the workspace was committed (only my simulated edit is uncommitted)", git(q, "status", "--porcelain").stdout.split() == ["M", "public/index.html"],
              git(q, "status", "--porcelain").stdout)
        check("the handoff names Q01 as waiting", "Q01" in (q / ".studio" / "HANDOFF.md").read_text(encoding="utf-8"))
        r3 = subprocess.run([sys.executable, str(DEV / "studio_pack.py"), "quick", str(q), "another", "--files", "tests/test_x.py"], capture_output=True, text=True)
        check("a quick change is refused while the workspace has uncommitted changes", r3.returncode != 0 and "uncommitted" in (r3.stdout + r3.stderr))

    if "blind" in which:
        section("blind planner trial: stage, prompts, grade")
        b = tmp / "blind"
        r = subprocess.run([sys.executable, str(DEV / "studio_blind.py"), "stage", "lackluster_remote", str(b)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        check("stage makes the workspace", (b / "SPEC.md").is_file() and (b / "public" / "index.html").is_file(), (r.stdout + r.stderr)[-400:])
        check("... with the helpers and NOTHING else of the pack: no plan, no tests, no notes, no look driver",
              sorted(p.name for p in (b / "tests").iterdir()) == ["_t.py"] and not (b / "plan.json").exists() and not (b / ".studio" / "PACK_NOTES.md").exists(),
              sorted(p.name for p in (b / "tests").iterdir()))
        check("... and the new file the plan would create is not there", not (b / "public" / "tvnav.js").exists())
        r = subprocess.run([sys.executable, str(DEV / "studio_blind.py"), "plan", str(b), "--dry"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        prompt = (b / ".studio" / "blind_plan.prompt.txt").read_text(encoding="utf-8") if (b / ".studio" / "blind_plan.prompt.txt").is_file() else ""
        check("plan --dry writes the planner's prompt and calls no model", 5000 < len(prompt) < 120_000, (len(prompt), (r.stdout + r.stderr)[-300:]))
        check("the prompt carries the spec, the file list and the helpers' interface", "public/tvnav.js" in prompt and "public/index.html" in prompt and "class Browser" in prompt)
        hidden = [n for n in ("test_remote_basics", "walking with the arrows never loses the highlight", "anchorX") if n in prompt]
        check("the prompt holds nothing from the pack's plan or tests", not hidden, hidden)
        print(f"   planner prompt: {len(prompt)} characters")
        # a perfect build: the pack's reference laid over the staged app; the grade must be full marks
        d, m = P.load("lackluster_remote")
        shutil.copytree(d / m["reference"], b, dirs_exist_ok=True)
        (b / "plan.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")
        r = subprocess.run([sys.executable, str(DEV / "studio_blind.py"), "grade", str(b)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        print("   " + "\n   ".join((r.stdout + r.stderr).strip().splitlines()[-9:]))
        g = json.loads((b / ".studio" / "blind_grade.json").read_text(encoding="utf-8")) if (b / ".studio" / "blind_grade.json").is_file() else {}
        sc = g.get("score") or {}
        check("grading the pack's own reference gives every hidden check", sc.get("checks", 0) >= 200 and sc.get("checks_pass") == sc.get("checks"), sc)
        P.unlink_base(m, b)

        section("blind planner trial, plan-only: the pack's tests judge, the planner sees labels and no code")
        b = tmp / "blind_po"
        r = subprocess.run([sys.executable, str(DEV / "studio_blind.py"), "stage", "lackluster_remote", str(b), "--plan-only"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        have = sorted(p.name for p in (b / "tests").glob("*.py")) if (b / "tests").is_dir() else []
        check("stage --plan-only brings the pack's tests, and still no plan and no look driver",
              "test_remote_basics.py" in have and "test_signin_api.py" in have and "_look.py" not in have and not (b / "plan.json").exists(), have)
        subprocess.run([sys.executable, str(DEV / "studio_blind.py"), "plan", str(b), "--dry"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        prompt = (b / ".studio" / "blind_plan.prompt.txt").read_text(encoding="utf-8") if (b / ".studio" / "blind_plan.prompt.txt").is_file() else ""
        check("the planner is told each test file and its checks in plain words",
              "TEST FILE 1: tests/test_remote_basics.py" in prompt and "walking with the arrows never loses the highlight" in prompt
              and "EXACTLY 3 tasks" in prompt)
        leaked = [n for n in ("anchorX", "br.press(", "def active(", "DESCRIBE =") if n in prompt.split("THE TESTS ALREADY EXIST")[-1]]
        check("... and none of their code", not leaked, leaked)
        r = subprocess.run([sys.executable, str(DEV / "studio_blind.py"), "tests", str(b), "--dry"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        check("the tests step refuses: nothing is written by the model in this trial", r.returncode != 0 and "plan-only" in (r.stdout + r.stderr))
        good = json.loads((d / "plan.json").read_text(encoding="utf-8"))          # the pack's own plan is a well-formed answer
        (b / "plan.json").write_text(json.dumps(good), encoding="utf-8")
        r = subprocess.run([sys.executable, str(DEV / "studio_blind.py"), "check", str(b)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        check("check accepts a plan with one task per test file, in order", r.returncode == 0 and "READY" in r.stdout, (r.stdout + r.stderr)[-500:])
        good["tasks"] = good["tasks"][:2]
        (b / "plan.json").write_text(json.dumps(good), encoding="utf-8")
        r = subprocess.run([sys.executable, str(DEV / "studio_blind.py"), "check", str(b)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        check("... and refuses one that leaves a test file without a task", r.returncode != 0 and "NOT READY" in r.stdout, (r.stdout + r.stderr)[-300:])
        P.unlink_base(m, b)

    if "bench" in which:
        section("bench: the two Lackluster builds that exist, adopted")
        name = "_selftest"
        shutil.rmtree(P.ROOT / "bench" / name, ignore_errors=True)
        r = subprocess.run([sys.executable, str(DEV / "studio_bench.py"), "adopt", name, r"C:\PCodeTest\lackluster1", str(WS2)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        r = subprocess.run([sys.executable, str(DEV / "studio_bench.py"), "report", name], capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        print("   " + "\n   ".join(out.strip().splitlines()[-9:]))
        res = json.loads((P.ROOT / "bench" / name / "results.json").read_text(encoding="utf-8"))
        tt = res["totals"] or {}
        check("the report counts both builds and their 5 tasks, all passed", tt.get("builds") == 2 and tt.get("tasks") == 5 and tt.get("passed") == 5, tt)
        check("... and judges them now: every check of both packs passes on the built workspaces", tt.get("checks_fail") == 0 and tt.get("checks_pass", 0) >= 200, tt)
        shutil.rmtree(P.ROOT / "bench" / name, ignore_errors=True)
finally:
    for link in tmp.rglob("node_modules"):
        try:
            os.rmdir(link)
        except OSError:
            pass
    shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{sum(ok_all)} passed, {len(ok_all) - sum(ok_all)} failed")
