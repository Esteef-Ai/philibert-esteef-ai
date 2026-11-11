"""Phase A of Philibert Code Studio: can the local model plan an app well enough? (dev/PHILIBERT_CODE_STUDIO.md)

    python dev/studio_trial.py questions <ws> <request.txt>   -> <ws>/.studio/questions.md
    python dev/studio_trial.py spec      <ws> <answers.md>    -> <ws>/SPEC.md
    python dev/studio_trial.py plan      <ws>                 -> <ws>/plan.json (+ problems)
    python dev/studio_trial.py review    <ws>                 a second call maps every spec item to a task and fixes the plan
    python dev/studio_trial.py tests     <ws> [T03]           -> <ws>/tests/test_*.py (+ tests/_t.py)
    python dev/studio_trial.py check     <ws>                 the foreman's plan check + every test fails cleanly unbuilt

Every model call is logged to <ws>/.studio/log.jsonl (stage, seconds, tokens) with the raw reply beside it.
--model TAG (default q36c-nd64k), --no-think, --think LEVEL (low/medium/high, gpt-oss), --ctx N (num_ctx), --max N (output cap, default 32000),
--reuse (parse the saved reply again).
"""
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared"))
import nd_studio as S  # noqa: E402

REUSE = False
CTX = None
MAXTOK = 32000
FOREMAN = REPO / "code" / "app" / "nd_foreman.py"


def opt(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        v = argv[i + 1]
        del argv[i:i + 2]
        return v
    return default


def ask(ws, stage, prompt, model, think):
    sd = ws / ".studio"
    sd.mkdir(exist_ok=True)
    if REUSE and (sd / f"{stage}.reply.txt").exists():      # parse the last reply again, no new call
        return (sd / f"{stage}.reply.txt").read_text(encoding="utf-8")
    print(f"[{time.strftime('%H:%M:%S')}] {stage}: asking {model} (think={think}) ...", flush=True)
    text, secs, info = S.call_model(model, prompt, think=think, num_ctx=CTX, max_tokens=MAXTOK)
    (sd / f"{stage}.prompt.txt").write_text(prompt, encoding="utf-8")
    (sd / f"{stage}.reply.txt").write_text(text, encoding="utf-8")
    with open(sd / "log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"stage": stage, "model": model, "think": think, "seconds": secs, **info,
                            "at": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
    print(f"  {secs} s, {info['eval_count']} tokens out ({info['thinking_chars']} chars of thinking)", flush=True)
    return text


def main(argv):
    model = opt(argv, "--model", "q36c-nd64k")
    level = opt(argv, "--think")
    global REUSE, CTX, MAXTOK
    CTX = int(opt(argv, "--ctx", 0)) or None
    MAXTOK = int(opt(argv, "--max", 32000))
    think, REUSE = "--no-think" not in argv, "--reuse" in argv
    if level:
        think = level
    argv = [a for a in argv if a not in ("--no-think", "--reuse")]
    stage, ws = argv[0], Path(argv[1]).resolve()
    sd = ws / ".studio"
    if stage == "questions":
        req = Path(argv[2]).read_text(encoding="utf-8").strip()
        sd.mkdir(exist_ok=True)
        (sd / "request.txt").write_text(req + "\n", encoding="utf-8")
        q = S.strip_think(ask(ws, "questions", S.QUESTIONS.format(request=req), model, think))
        (sd / "questions.md").write_text(q + "\n", encoding="utf-8")
        print(q)
    elif stage == "spec":
        ans = Path(argv[2]).read_text(encoding="utf-8").strip()
        (sd / "answers.md").write_text(ans + "\n", encoding="utf-8")
        req = (sd / "request.txt").read_text(encoding="utf-8").strip()
        spec = S.strip_think(ask(ws, "spec", S.SPEC.format(request=req, answers=ans), model, think))
        spec = spec.removeprefix("```markdown").removeprefix("```md").removesuffix("```").strip()
        (ws / "SPEC.md").write_text(spec + "\n", encoding="utf-8")
        print(f"SPEC.md: {len(spec)} characters")
    elif stage == "plan":
        spec = (ws / "SPEC.md").read_text(encoding="utf-8")
        plan = S.extract_json(ask(ws, "plan", S.PLAN.format(spec=spec), model, think))
        for t in plan.get("tasks") or []:
            if isinstance(t.get("tests"), list) and len(t["tests"]) == 1:
                t["tests"] = t["tests"][0]
            t["context"] = list(dict.fromkeys(([t["tests"]] if isinstance(t.get("tests"), str) else []) + ["SPEC.md"]))
        plan.update({"workspace": ".", "python": str(ws / ".venv" / "Scripts" / "python.exe"),
                     "model": "opencode/q36c-nd128k", "opencode_think": False, "alt_model": None,
                     "defaults": {"attempts": 3, "minutes": 30}})
        (ws / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        probs = S.plan_problems(plan)
        for t in plan.get("tasks") or []:
            print(f"  {t.get('id')} {t.get('title')}: {', '.join(t.get('files') or [])} -> {t.get('tests')}"
                  f" ({len(t.get('brief') or '')} chars)")
        print("plan problems: " + ("; ".join(probs) if probs else "none"))
    elif stage == "review":
        spec = (ws / "SPEC.md").read_text(encoding="utf-8")
        old = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
        (sd / "plan_v1.json").write_text(json.dumps(old, indent=1, ensure_ascii=False), encoding="utf-8")
        keep = {k: old[k] for k in ("workspace", "python", "model", "opencode_think", "alt_model", "defaults") if k in old}
        bare = {k: v for k, v in old.items() if k not in keep}
        for t in bare.get("tasks") or []:
            t.pop("context", None)
        plan = S.extract_json(ask(ws, "review", S.PLAN_REVIEW.format(spec=spec, plan=json.dumps(bare, indent=1, ensure_ascii=False)),
                                  model, think))
        for t in plan.get("tasks") or []:
            if isinstance(t.get("tests"), list) and len(t["tests"]) == 1:
                t["tests"] = t["tests"][0]
            t["context"] = list(dict.fromkeys(([t["tests"]] if isinstance(t.get("tests"), str) else []) + ["SPEC.md"]))
        plan.update(keep)
        (ws / "plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        for t in plan.get("tasks") or []:
            print(f"  {t.get('id')} {t.get('title')}: {', '.join(t.get('files') or [])} -> {t.get('tests')}"
                  f" ({len(t.get('brief') or '')} chars)")
        for c in plan.get("coverage") or []:
            print(f"    {c.get('task')}: {c.get('item')}")
        probs = S.plan_problems(plan)
        print("plan problems: " + ("; ".join(probs) if probs else "none"))
    elif stage == "tests":
        plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
        only = argv[2] if len(argv) > 2 else None
        (ws / "tests").mkdir(exist_ok=True)
        (ws / "tests" / "_t.py").write_text(S.T_HELPER, encoding="utf-8")
        rules = "\n".join(f"- {r}" for r in plan.get("rules") or [])
        for t in plan["tasks"]:
            if only and t["id"] != only:
                continue
            prompt = S.TESTS.format(test=t["tests"], rules=rules, plan_summary=S.plan_summary(plan), task=S.task_text(t))
            code = S.extract_python(ask(ws, f"tests_{t['id']}", prompt, model, think))
            (ws / t["tests"]).write_text(code, encoding="utf-8")
            try:
                compile(code, t["tests"], "exec")
                print(f"  {t['tests']}: {code.count('check(')} check calls, compiles")
            except SyntaxError as e:
                print(f"  {t['tests']}: SYNTAX ERROR {e}")
    elif stage == "review-tests":
        plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
        only = set(argv[2].split(",")) if len(argv) > 2 else None
        spec = (ws / "SPEC.md").read_text(encoding="utf-8")
        keep = sd / "tests_before_review"
        keep.mkdir(exist_ok=True)
        for t in plan["tasks"]:
            if only and t["id"] not in only:
                continue
            f = ws / t["tests"]
            code = f.read_text(encoding="utf-8")
            (keep / f.name).write_text(code, encoding="utf-8")
            reply = ask(ws, f"testreview_{t['id']}", S.TEST_REVIEW.format(spec=spec, task=S.task_text(t), test=t["tests"],
                                                                          code=code), model, think)
            found = S.strip_think(reply).split("```")[0].strip()
            print(f"  {t['tests']} - reviewer found:\n    " + found.replace("\n", "\n    ")[:2500])
            try:
                new = S.extract_python(reply)
                compile(new, t["tests"], "exec")
            except (ValueError, SyntaxError) as e:
                print(f"    review gave no usable file ({e}) - the test stays as it was")
                continue
            f.write_text(new, encoding="utf-8")
    elif stage == "dispute":
        # A task is stuck: the referee decides whether its test is wrong; if so the test is repaired (and
        # the old one kept in .studio/tests_before_dispute), so the foreman can resume. -> verdict printed.
        tid = argv[2]
        plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
        t = next(x for x in plan["tasks"] if x["id"] == tid)
        state = json.loads((ws / ".foreman" / "state.json").read_text(encoding="utf-8"))
        rep = (ws / ".foreman" / "REPORT.md").read_text(encoding="utf-8")
        m = rep.split(f"### {tid} ", 1)
        failure = (m[1].split("Last failure:", 1)[1].split("Prompts:", 1)[0].strip("`\n ") if len(m) > 1 and
                   "Last failure:" in m[1] else str(state)[:3000])[:6000]
        files = sorted({f for x in plan["tasks"] for f in x.get("files") or [] if (ws / f).is_file()})
        code = "\n\n".join(f"--- {f} ---\n" + (ws / f).read_text(encoding="utf-8", errors="replace") for f in files)
        f = ws / t["tests"]
        old = f.read_text(encoding="utf-8")
        reply = ask(ws, f"dispute_{tid}", S.DISPUTE.format(
            tid=tid, spec=(ws / "SPEC.md").read_text(encoding="utf-8"), plan_summary=S.plan_summary(plan),
            task=S.task_text(t), code=code[:60000], test=t["tests"], test_code=old, failure=failure), model, think)
        body = S.strip_think(reply)
        print(body.split("```")[0].strip()[:2500])
        if "VERDICT: TEST" in body.upper().replace("**", ""):
            try:
                new = S.extract_python(reply)
                compile(new, t["tests"], "exec")
            except (ValueError, SyntaxError) as e:
                print(f"  verdict TEST but no usable file ({e}) - the test stays as it was")
                return
            keep = sd / "tests_before_dispute"
            keep.mkdir(exist_ok=True)
            (keep / f.name).write_text(old, encoding="utf-8")
            f.write_text(new, encoding="utf-8")
            print(f"  {t['tests']} repaired (old copy in {keep})")
    elif stage == "check":
        py = sys.executable
        r = subprocess.run([py, str(FOREMAN), "check", str(ws / "plan.json")], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", cwd=str(FOREMAN.parent))
        print(r.stdout[-4000:], r.stderr[-2000:])
        plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
        vpy = str(ws / ".venv" / "Scripts" / "python.exe")
        for t in plan["tasks"]:
            r = subprocess.run([vpy, t["tests"]], capture_output=True, text=True, encoding="utf-8", errors="replace",
                               cwd=str(ws), timeout=120)
            out = (r.stdout + r.stderr).strip().splitlines()
            print(f"  unbuilt {t['tests']}: exit {r.returncode}; " + (out[-1] if out else "(no output)"))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
