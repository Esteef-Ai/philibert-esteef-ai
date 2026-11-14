"""The replay bench: the packs already built are the benchmark.

A plan pack is a fixed job with fixed judges: the same spec, plan and tests every time. Building it again on another
model, another context size or another builder setting, and counting attempts, time and passes, measures that choice
on the work this studio really does (T3 measures one small Python task in another harness).

    python dev/studio_bench.py new <bench> --packs lackluster_tv_login,lackluster_remote [--model opencode/q36c-nd128k] [--n 1]
                                            fresh workspaces under C:\\PCodeTest\\bench\\<bench>\\ (nothing is built)
    python dev/studio_bench.py run <bench> [--max-hours 6]      build every workspace, one after another (YOU launch it)
    python dev/studio_bench.py adopt <bench> <workspace> [...]  count builds that already exist (the history)
    python dev/studio_bench.py report <bench> [<bench> ...]     BENCH.md per bench; several benches side by side

What a row says: tasks passed, how many passed on the first attempt, attempts used, the builder's minutes, and
"judged now": every test of the pack run again on the finished workspace, today. Never rank on one build: the
report says how many builds stand behind each number.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "dev"))
import studio_pack as P  # noqa: E402

HOME = P.ROOT / "bench"
ME = f'"{sys.executable}" "{Path(__file__).resolve()}"'


def bench_file(name):
    return HOME / name / "bench.json"


def load(name):
    f = bench_file(name)
    if not f.is_file():
        sys.exit(f"no bench called {name} ({f} is missing)")
    return json.loads(f.read_text(encoding="utf-8"))


def save(name, b):
    bench_file(name).parent.mkdir(parents=True, exist_ok=True)
    bench_file(name).write_text(json.dumps(b, indent=1, ensure_ascii=False), encoding="utf-8")


def new(name, packs, model=None, n=1):
    if bench_file(name).exists():
        sys.exit(f"bench {name} already exists")
    b = {"name": name, "made": time.strftime("%Y-%m-%d %H:%M"), "model": model, "runs": []}
    for pack in packs:
        d, m = P.load(pack)
        for i in range(1, n + 1):
            ws = HOME / name / f"{m['name']}_{i}"
            r = subprocess.run([sys.executable, str(Path(P.__file__).resolve()), "new", str(d), str(ws)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode != 0 or not (ws / "plan.json").is_file():
                sys.exit(f"could not make {ws}: {(r.stdout + r.stderr)[-400:]}")
            if model:                                          # the one thing a bench changes: who builds
                plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
                plan["model"] = model
                (ws / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                P.journal(ws, "studio_bench", f"bench {name}: the builder is {model}")
                P.git(ws, "add", "-A")
                P.git(ws, "commit", "-q", "-m", f"bench {name}: builder {model}")
            b["runs"].append({"pack": m["name"], "ws": str(ws), "adopted": False})
            print(f"  made {ws}")
    save(name, b)
    print(f"\nbench {name}: {len(b['runs'])} workspace(s). Nothing is built yet. Start it yourself:\n  {ME} run {name}")


def adopt(name, workspaces):
    b = load(name) if bench_file(name).exists() else {"name": name, "made": time.strftime("%Y-%m-%d %H:%M"), "model": None, "runs": []}
    for w in workspaces:
        ws = Path(w)
        pj = ws / ".studio" / "pack.json"
        if not pj.is_file():
            sys.exit(f"{ws} was not made from a pack")
        if str(ws) not in [r["ws"] for r in b["runs"]]:
            b["runs"].append({"pack": json.loads(pj.read_text(encoding="utf-8"))["name"], "ws": str(ws), "adopted": True})
    save(name, b)
    print(f"bench {name}: {len(b['runs'])} workspace(s)")


def run(name, max_hours=6.0):
    b = load(name)
    for r in b["runs"]:
        ws = Path(r["ws"])
        if r.get("adopted") or r.get("built"):
            continue
        print(f"[{time.strftime('%H:%M')}] building {ws} ...", flush=True)
        t0 = time.time()
        subprocess.run([sys.executable, str(Path(P.__file__).resolve()), "build", str(ws), "--max-hours", str(max_hours)])
        r["built"], r["wall_min"] = time.strftime("%Y-%m-%d %H:%M"), round((time.time() - t0) / 60, 1)
        save(name, b)
    report([name])


def measure(r, judge=True):
    """One workspace -> its row. Reads the foreman's state; runs the pack's tests on the workspace as it is now."""
    ws = Path(r["ws"])
    out = {"pack": r["pack"], "ws": ws.name, "adopted": r.get("adopted", False), "wall_min": r.get("wall_min")}
    try:
        plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
        st = json.loads((ws / ".foreman" / "state.json").read_text(encoding="utf-8")).get("tasks", {})
    except (OSError, ValueError):
        return {**out, "built": False}
    tasks = plan["tasks"]
    att = [(st.get(t["id"]) or {}).get("attempts") or [] for t in tasks]
    passed = [(st.get(t["id"]) or {}).get("status") == "passed" for t in tasks]
    models = sorted({a.get("model_used") or a.get("model") for al in att for a in al if a.get("model_used") or a.get("model")})
    out.update({"built": True, "model": ", ".join(models) or plan.get("model"), "tasks": len(tasks), "passed": sum(passed),
                "first_try": sum(1 for p, al in zip(passed, att) if p and len(al) == 1 and al[0].get("verdict") == "pass"),
                "attempts": sum(len(al) for al in att),
                "builder_min": round(sum(float(a.get("secs") or 0) for al in att for a in al) / 60, 1),
                "gates": {}})
    for al in att:
        for a in al:
            if a.get("gate"):
                out["gates"][a["gate"]] = out["gates"].get(a["gate"], 0) + 1
    for name_, key in (("suspects.json", "suspects"),):
        try:
            out[key] = len(json.loads((ws / ".studio" / name_).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            out[key] = 0
    try:
        lk = json.loads((ws / ".studio" / "look" / "summary.json").read_text(encoding="utf-8"))
        out["look_new"] = len(lk["new"])
    except (OSError, ValueError):
        out["look_new"] = None
    if judge:                                               # by the pack's tests as they are today, on a copy
        res = P.judge(ws)
        out["judged"] = {"checks_pass": sum(r["passed"] for r in res.values()),
                         "checks_fail": sum(max(r["failed"], 0) + (1 if r["failed"] < 0 else 0) for r in res.values()),
                         "files_ok": sum(1 for r in res.values() if r["ok"]), "files": len(res),
                         "fails": [f for r in res.values() for f in r["fails"]][:10]}
    return out


def table(rows):
    L = ["| Pack | Workspace | Builder | Tasks passed | First try | Attempts | Builder min | Judged now (checks) | Suspect tests | Look: new |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r.get("built"):
            L.append(f"| {r['pack']} | {r['ws']} | | not built yet | | | | | | |")
            continue
        j = r.get("judged")
        L.append(f"| {r['pack']} | {r['ws']}{' (adopted)' if r['adopted'] else ''} | {r['model']} | {r['passed']}/{r['tasks']} | "
                 f"{r['first_try']}/{r['tasks']} | {r['attempts']} | {r['builder_min']} | "
                 + (f"{j['checks_pass']} pass, {j['checks_fail']} fail ({j['files_ok']}/{j['files']} files)" if j else "not run")
                 + f" | {r['suspects']} | {'' if r['look_new'] is None else r['look_new']} |")
    return L


def totals(rows):
    b = [r for r in rows if r.get("built")]
    if not b:
        return None
    t = sum(r["tasks"] for r in b)
    return {"builds": len(b), "tasks": t, "passed": sum(r["passed"] for r in b), "first_try": sum(r["first_try"] for r in b),
            "attempts": sum(r["attempts"] for r in b), "builder_min": round(sum(r["builder_min"] for r in b), 1),
            "checks_pass": sum((r.get("judged") or {}).get("checks_pass", 0) for r in b),
            "checks_fail": sum((r.get("judged") or {}).get("checks_fail", 0) for r in b)}


def report(names, judge=True):
    allrows = {}
    for name in names:
        b = load(name)
        rows = [measure(r, judge) for r in b["runs"]]
        allrows[name] = rows
        tt = totals(rows)
        L = [f"# Bench {name}", "", f"Written {time.strftime('%Y-%m-%d %H:%M')} by `studio_bench.py report`. Builder asked for: "
             f"`{b.get('model') or 'each pack own'}`.", "", *table(rows), ""]
        if tt:
            L += [f"**Totals over {tt['builds']} build(s):** {tt['passed']}/{tt['tasks']} tasks passed, {tt['first_try']}/{tt['tasks']} on the "
                  f"first attempt, {tt['attempts']} attempts, {tt['builder_min']} builder minutes; judged now: {tt['checks_pass']} checks "
                  f"pass, {tt['checks_fail']} fail.", "",
                  "Read it with care: " + ("one build per pack is an anecdote, not a ranking. Build each pack 3 times or more "
                                           "(`--n 3`) before preferring one builder to another." if tt["builds"] <= len({r["pack"] for r in rows})
                                           else "several builds per pack: compare the spread, not only the totals."),
                  "An adopted build keeps only the attempts its foreman state still holds; a task that was reset after a "
                  "test fault shows fewer attempts than were really spent."]
        (HOME / name).mkdir(parents=True, exist_ok=True)
        (HOME / name / "BENCH.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        (HOME / name / "results.json").write_text(json.dumps({"rows": rows, "totals": tt}, indent=1, ensure_ascii=False), encoding="utf-8")
        print("\n".join(L))
    if len(names) > 1:
        print("\n## Side by side\n\n| Bench | Builds | Tasks passed | First try | Attempts | Builder min | Checks pass / fail |\n|---|---|---|---|---|---|---|")
        for name in names:
            tt = totals(allrows[name])
            if tt:
                print(f"| {name} | {tt['builds']} | {tt['passed']}/{tt['tasks']} | {tt['first_try']}/{tt['tasks']} | {tt['attempts']} | "
                      f"{tt['builder_min']} | {tt['checks_pass']} / {tt['checks_fail']} |")


def main(a):
    if len(a) < 2:
        sys.exit(__doc__)
    cmd, name = a[0], a[1]
    if not re.fullmatch(r"[\w.-]+", name):
        sys.exit("a bench name is letters, digits, _ . -")
    if cmd == "new":
        packs = [p for p in P.opt(a, "--packs", "").split(",") if p]
        if not packs:
            sys.exit("name the packs: --packs lackluster_tv_login,lackluster_remote")
        new(name, packs, P.opt(a, "--model", None), int(P.opt(a, "--n", 1)))
    elif cmd == "adopt":
        adopt(name, a[2:])
    elif cmd == "run":
        run(name, float(P.opt(a, "--max-hours", 6)))
    elif cmd == "report":
        judge = "--no-judge" not in a
        report([x for x in a[1:] if not x.startswith("--")], judge)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
