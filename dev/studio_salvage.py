"""Salvage: a failed attempt's work is the next attempt's starting point, when it got further.

The foreman undoes every failed attempt (git reset + clean), so the next one starts from nothing. On blind4
(2026-11-15) task T02 reached 29 of 31 checks after 40 minutes; that work was thrown away and the four attempts
after it got less far. This module rebuilds what an attempt left in the files it was allowed to change, from the
builder's own transcript (.foreman/opencode/<task>_a<n>.jsonl: every write and edit, in order), runs the task's
test and every test that must keep passing on a copy, and when the best attempt passes more of the task's checks
than the workspace does now and breaks nothing that must keep passing, commits that work as the task's starting
point. A `foreman retry` then starts the next attempt from it (the foreman takes the task's start from HEAD).

Nothing here edits the foreman (G:\\!Ai\\ND3 is the owner's copy) and nothing calls a model.

    python dev/studio_salvage.py <workspace> <task id> [--apply]      without --apply: only says what it would keep
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "dev"))
import studio_pack as P  # noqa: E402

MAX_LOST = 2        # older checks a kept attempt may break (the next attempt must mend them)
MIN_GAIN = 5        # own checks it must gain to be allowed to break any
SKIP = (".git", ".venv", ".foreman", ".studio", "node_modules", "__pycache__", ".nd_backups")


def rel_of(ws, p):
    """A path from the transcript (absolute or relative) -> the workspace-relative form with forward slashes."""
    p = str(p).replace("\\", "/")
    w = str(Path(ws).resolve()).replace("\\", "/")
    if p.lower().startswith(w.lower() + "/"):
        p = p[len(w) + 1:]
    return p.lstrip("./")


def at_commit(ws, sha, rel):
    r = subprocess.run(["git", "-C", str(ws), "show", f"{sha}:{rel}"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else ""


def replay(ws, transcript, allowed, start_sha):
    """-> {rel: content} of the allowed files as the attempt left them, or None when the replay does not hold
    (an edit whose old text is not in the file: then the reconstruction would be a guess)."""
    files = {}
    for ln in Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        part = e.get("part") or {}
        tool, st = part.get("tool"), part.get("state") or {}
        if tool not in ("write", "edit") or st.get("status") != "completed":
            continue
        inp = st.get("input") or {}
        rel = rel_of(ws, inp.get("filePath") or inp.get("path") or "")
        if rel not in allowed:
            continue                                          # out of scope: the foreman would refuse it anyway
        if rel not in files:
            files[rel] = at_commit(ws, start_sha, rel)
        if tool == "write":
            files[rel] = inp.get("content") or ""
            continue
        old, new = inp.get("oldString"), inp.get("newString")
        if old is None or new is None:
            return None
        cur = files[rel].replace("\r\n", "\n")
        old, new = old.replace("\r\n", "\n"), new.replace("\r\n", "\n")
        if old == "":
            files[rel] = new
        elif old in cur:
            files[rel] = cur.replace(old, new) if inp.get("replaceAll") else cur.replace(old, new, 1)
        else:
            span = trimmed_span(cur, old) or anchored_span(cur, old)   # OpenCode's edit forgives both; so must the replay
            if span is None:
                return None
            lines = cur.split("\n")
            files[rel] = "\n".join(lines[:span[0]] + new.split("\n") + lines[span[1]:])
    return files


def trimmed_span(text, old):
    """The one run of whole lines in `text` equal to `old` line by line once each line is stripped -> (first, end),
    or None when there is no such run or more than one (a guess is worse than giving up)."""
    want = [ln.strip() for ln in old.strip("\n").split("\n")]
    have = [ln.strip() for ln in text.split("\n")]
    hits = [i for i in range(len(have) - len(want) + 1) if have[i:i + len(want)] == want]
    return (hits[0], hits[0] + len(want)) if len(hits) == 1 else None


def anchored_span(text, old):
    """OpenCode's block-anchor match: a block of 3+ lines whose first and last lines (stripped) equal those of `old`,
    the middle allowed to differ. One candidate is taken as is; of several, the one whose middle is most alike, when at
    least 30% alike (OpenCode's own thresholds). blind6 T02_a2 (2026-11-18): the builder's edit #69 replaced a function
    that had gained a line, OpenCode applied it, and the replay gave up on the attempt that reached 19 of 19."""
    import difflib
    want = [ln.strip() for ln in old.strip("\n").split("\n")]
    if len(want) < 3:
        return None
    have = [ln.strip() for ln in text.split("\n")]
    cands = []
    for i, h in enumerate(have):
        if h != want[0]:
            continue
        for j in range(i + 2, len(have)):
            if have[j] == want[-1]:
                cands.append((i, j + 1))
                break
    if len(cands) == 1:
        return cands[0]
    best, score = None, 0.3
    for a, b in cands:
        s = difflib.SequenceMatcher(None, "\n".join(have[a + 1:b - 1]), "\n".join(want[1:-1])).ratio()
        if s >= score:
            best, score = (a, b), s
    return best


def copy_of(ws, dest, links):
    shutil.copytree(ws, dest, ignore=shutil.ignore_patterns(*SKIP))
    for n in links:
        if (ws / n).exists():
            subprocess.run(["cmd", "/c", "mklink", "/J", str(dest / n), str((ws / n).resolve())], capture_output=True)


def unlink(dest, links):
    for n in links:
        try:
            (dest / n).rmdir()                                 # a junction: removes the link, never its target
        except OSError:
            pass


def must_pass(ws, plan, state, tid):
    """The tests that must still pass: those of every passed task and every guard, apart from this task's own."""
    task = next(t for t in plan["tasks"] if t["id"] == tid)
    own = task["tests"] if isinstance(task["tests"], list) else [task["tests"]]
    out = []
    for t in plan["tasks"]:
        if t["id"] == tid or (state["tasks"].get(t["id"]) or {}).get("status") != "passed":
            continue
        out += t["tests"] if isinstance(t["tests"], list) else [t["tests"]]
    out += own[1:]                                            # the guard tests ride on a task's list after its own file
    return own[0], list(dict.fromkeys(x for x in out if x != own[0]))


def judge(ws, files, own, keep, links, log):
    """Lay `files` over a copy of the workspace -> (own passed, own failed, every keep test ok, failures)."""
    py = str(ws / ".venv" / "Scripts" / "python.exe")
    tmp = Path(tempfile.mkdtemp(prefix="salvage_"))
    try:
        app = tmp / "app"
        copy_of(ws, app, links)
        for rel, text in (files or {}).items():
            (app / rel).parent.mkdir(parents=True, exist_ok=True)
            (app / rel).write_text(text, encoding="utf-8", newline="")
        p, f, ok, tail = P.run_test(py, app, own, 900)
        broke, lost = [], 0
        for t in keep:
            kp, kf, kok, ktail = P.run_test(py, app, t, 900)
            if not kok:
                broke.append(f"{t}: {kp} passed, {kf} failed")
                lost += kf if kf > 0 else 99                     # a crash counts as breaking everything
        return p, f, lost, broke
    finally:
        unlink(app, links)
        shutil.rmtree(tmp, ignore_errors=True)


def keep_rounds(ws, tid):
    """The foreman names its transcripts by attempt only (<tid>_a1..a3), so a fresh round overwrote the last one's:
    blind5's T05 round 3 reached 40 of 54 player checks and nobody looked. Set this round's aside as <tid>_r<k>_a<n>."""
    d = Path(ws) / ".foreman" / "opencode"
    k = 1 + max([int(m.group(1)) for p in d.glob(f"{tid}_r*_a*.jsonl") for m in [re.match(rf"{tid}_r(\d+)_a", p.name)] if m] or [0])
    moved = []
    for p in sorted(d.glob(f"{tid}_a*.jsonl")):
        dst = d / p.name.replace(f"{tid}_a", f"{tid}_r{k}_a", 1)
        p.rename(dst)
        moved.append(dst.name)
    return moved


def salvage(ws, tid, apply=False, log=print):
    """-> a dict saying what was found and whether it was kept."""
    ws = Path(ws)
    plan = json.loads((ws / "plan.json").read_text(encoding="utf-8"))
    state = json.loads((ws / ".foreman" / "state.json").read_text(encoding="utf-8"))
    m = json.loads((ws / ".studio" / "pack.json").read_text(encoding="utf-8")) if (ws / ".studio" / "pack.json").is_file() else {}
    links = list(m.get("base_links") or [])
    guards = set(m.get("guard_tests") or [])
    task = next(t for t in plan["tasks"] if t["id"] == tid)
    allowed = {rel_of(ws, f) for f in task.get("files") or []}
    own, keep = must_pass(ws, plan, state, tid)
    head = subprocess.run(["git", "-C", str(ws), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    base = judge(ws, {}, own, keep, links, log)
    log(f"salvage {tid}: the workspace now: {own} {base[0]} passed, {base[1]} failed")
    best = None
    # every round's attempts: <tid>_a<n> (the last round) and <tid>_r<k>_a<n> (earlier rounds, set aside by keep_rounds)
    for tr in sorted((ws / ".foreman" / "opencode").glob(f"{tid}_*.jsonl")):
        files = replay(ws, tr, allowed, head)
        if not files:
            log(f"  {tr.name}: nothing to rebuild (no edits in the allowed files, or the edits do not replay)")
            continue
        p, f, lost, broke = judge(ws, files, own, keep, links, log)
        log(f"  {tr.name}: {p} passed, {f} failed" + (f"; breaks {lost} older check(s): {'; '.join(broke)[:200]}" if lost else ""))
        # Worth keeping: it breaks nothing older, or at most MAX_LOST older checks while gaining at least MIN_GAIN of its
        # own. The foreman's "broke" gate then makes the next attempt mend what it broke, and says which checks.
        # NEVER a guard (the parts of the app that worked before this pack, e.g. sign-in): blind6 (2026-11-17) kept a
        # T01 at 41/42 that made Enter fire twice and broke 2 sign-in checks; every later attempt started broken, the
        # suspect check then blamed the test, and the night was lost. MAX_LOST is for checks of earlier tasks only.
        guard_broken = [b for b in broke if b.split(":", 1)[0] in guards]
        if guard_broken:
            log(f"  {tr.name}: not kept, it breaks a guard test ({'; '.join(guard_broken)[:160]})")
            continue
        gain = p - max(base[0], 0)
        if f >= 0 and (lost == 0 or (lost <= MAX_LOST and gain >= MIN_GAIN)):
            score = p - lost
            if best is None or score > best["score"]:
                best = {"transcript": tr.name, "passed": p, "failed": f, "older_broken": lost, "score": score, "files": files}
    res = {"task": tid, "now": {"passed": base[0], "failed": base[1]}, "best": None, "kept": False}
    if not best or best["passed"] <= max(base[0], 0):
        log(f"salvage {tid}: no attempt got further than the workspace has now: nothing kept")
        return res
    res["best"] = {k: v for k, v in best.items() if k != "files"}
    if not apply:
        log(f"salvage {tid}: would keep {best['transcript']} ({best['passed']} passed, {best['failed']} failed) - run with --apply")
        return res
    for rel, text in best["files"].items():
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text(text, encoding="utf-8", newline="")
    msg = (f"salvage: {tid}'s best failed attempt ({best['transcript']}: {best['passed']} of {best['passed'] + best['failed']} checks"
           + (f", breaks {best['older_broken']} older check(s) the next attempt must mend" if best["older_broken"] else "")
           + ") kept as the starting point")
    subprocess.run(["git", "-C", str(ws), "add", "-A", *best["files"].keys()], capture_output=True)
    subprocess.run(["git", "-C", str(ws), "commit", "-q", "-m", msg], capture_output=True)
    P.journal(ws, "studio_salvage", msg)
    res["kept"] = True
    log(msg)
    return res


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    salvage(a[0], a[1], apply="--apply" in a)
