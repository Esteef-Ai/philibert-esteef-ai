"""Clear NeuralDock's scratch folder (temp/) - the housekeeping half of "every throwaway file
goes in temp/ so it can be deleted in one go".

What goes:
  * the known big scratch folders, whatever their age: test installs and downloads
    (imagegen_drive, retro_art*, hf_gguf), caches (mypy_cache, __pycache__), the headless
    browser profiles (ndb_*_prof) - all re-created when needed;
  * anything else in temp/ untouched for `days` days (logs, run output, screenshots,
    applied patch scripts, launcher backups...).
What stays:
  * files git tracks (they are tiny, and deleting them only makes noise in `git status`);
  * KEEP - the reusable tools and records (benchmark runners, screenshot helpers, the
    Elena Live builds, mirror scripts...), whatever their age.

    python nd_cleanup.py              # report only: what would go, and how much
    python nd_cleanup.py --apply      # delete it
    python nd_cleanup.py --days 30    # a different age

The launcher runs `prune(apply=True)` quietly a minute after it starts (config
`temp_cleanup_days`, default 14; 0 turns it off) and logs what it freed.
"""
import fnmatch
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ND = Path(__file__).resolve().parent
TEMP = ND / "temp"
# Big scratch: re-created when needed, so it goes whatever its age.
ALWAYS = ["imagegen_drive", "retro_art*", "hf_gguf", "mypy_cache", "__pycache__", "ndb_*_prof", "store_root", "mactest"]
# Tools and records worth keeping, whatever their age.
KEEP = ["viz_runs", "viz_notes", "viz_msgs", "head_backup",
        "t3_*.py", "t1_*.py", "t2_*.py", "queue_*.sh", "bench*.py", "run_suite.py",
        "shot_*.py", "viz_*.py", "accuracy_launcher.py", "model_quiz.py", "hf_mirror*.py", "find_models.py",
        "devstral_*.py", "ctx_sweep.py", "t3_dsh_arm.py", "foreman_run.py", "ctx_split_probe.py", "prefill_test.py",
        "prompt_size_probe.py", "overnight", "opencode_arm", "overnight2", "t3_opencode_arm.py", "model_speed_check.py", "coding_mode.json", "coding_mode.log"]


def _size(p):
    if p.is_file() or p.is_symlink():
        try:
            return p.lstat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                st = os.stat(os.path.join(root, f))
                # a hard link to a file kept elsewhere (a test install linking ComfyUI's models)
                # frees nothing when deleted - don't count it
                if st.st_nlink <= 1:
                    total += st.st_size
            except OSError:
                pass
    return total


def _newest(p):
    """When anything inside was last changed (a folder's own time misses edits deep in it)."""
    t = p.stat().st_mtime
    if p.is_dir():
        for root, _dirs, files in os.walk(p):
            for f in files[:200]:
                try:
                    t = max(t, os.path.getmtime(os.path.join(root, f)))
                except OSError:
                    pass
    return t


def _tracked():
    try:
        out = subprocess.run(["git", "ls-files", "temp"], cwd=ND, capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return None                  # no git: keep nothing back for being tracked
    return {line.split("/", 2)[1] for line in out.splitlines() if line.count("/") >= 1}


def _match(name, pats):
    return any(fnmatch.fnmatch(name.lower(), p.lower()) for p in pats)


def plan(days=14):
    """[(path, bytes, why)] of what would go."""
    if not TEMP.is_dir():
        return []
    tracked = _tracked() or set()
    cutoff = time.time() - days * 86400
    out = []
    for p in TEMP.iterdir():
        n = p.name
        if _match(n, KEEP):
            continue
        if _match(n, ALWAYS):
            out.append((p, _size(p), "scratch, re-created when needed"))
            continue
        if n in tracked:
            continue
        if days > 0 and _newest(p) < cutoff:
            out.append((p, _size(p), f"untouched for {days}+ days"))
    return sorted(out, key=lambda x: -x[1])


def prune(days=14, apply=False, log=None):
    items = plan(days)
    freed = 0
    for p, size, _why in items:
        if not apply:
            freed += size
            continue
        try:
            shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
            freed += size
        except OSError:
            pass
    if log and apply and items:
        log(f"Cleaned temp/: {len(items)} items, {freed / 1e9:.2f} GB freed", "ok")
    return {"items": len(items), "bytes": freed}


if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 14
    apply = "--apply" in sys.argv
    items = plan(days)
    for p, size, why in items[:40]:
        print(f"{size / 1e9:9.3f} GB  {p.name:<50} {why}")
    if len(items) > 40:
        print(f"   ... and {len(items) - 40} more small items")
    r = prune(days, apply)
    print(f"\n{'Deleted' if apply else 'Would delete'}: {r['items']} items, {r['bytes'] / 1e9:.2f} GB"
          + ("" if apply else "   (run with --apply to delete)"))
