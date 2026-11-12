"""T01: the scanner finds the right sizes and counts, follows no junctions, changes nothing, and is fast."""
import os
import time

from _t import EXPECTED, FIXTURE, FIXTURE_BIG, check, finish, listing

try:
    from wiztry.scanner import Node, ext_of, scan, summary, timed_scan
except Exception as e:                                  # noqa: BLE001
    check("wiztry.scanner imports", False, e)
    finish()

check("ext_of: lower-case with the dot", ext_of("Report.PDF") == ".pdf", ext_of("Report.PDF"))
check("ext_of: no extension", ext_of("Makefile") == "(none)", ext_of("Makefile"))
check("ext_of: only the last part", ext_of("a.tar.gz") == ".gz", ext_of("a.tar.gz"))

before = listing(FIXTURE)
top, skipped = scan(FIXTURE)
check("scan returns (Node, skipped)", isinstance(top, Node) and skipped == 0, (type(top), skipped))
check("total size", top.size == EXPECTED["total_size"], top.size)
check("file count", top.files == EXPECTED["files"], top.files)
check("folder count (the junction is not a folder)", top.folders == EXPECTED["folders"], top.folders)
names = [c.name for c in top.children]
check("the junction is neither followed nor listed", "link_to_music" not in names, names)
check("the empty folder is listed with size 0",
      any(c.name == "empty_folder" and c.is_dir and c.size == 0 for c in top.children), names)
check("children are sorted largest first", [c.size for c in top.children] == sorted((c.size for c in top.children), reverse=True))
music = next((c for c in top.children if c.name == "music"), None)
check("a folder's size is everything inside it", music is not None and music.size == 20_500_000 and music.files == 4
      and music.folders == 1, music and (music.size, music.files, music.folders))
check("parents are linked", music is not None and music.parent is top and all(c.parent is music for c in music.children))
f = music.children[0] if music else None
check("a file has its path, size and mtime", f is not None and not f.is_dir and f.path == os.path.join(FIXTURE, "music", "c.flac")
      and f.size == 9_000_000 and f.mtime > 0, f and (f.path, f.size))
hidden = next((c for c in top.children if c.name == ".config"), None)
check("hidden files count", hidden is not None and hidden.files == 1)
check("names that are not ASCII work", any(c.name.startswith("unicode ü") for c in top.children), names)

rep = summary(top, skipped, 1.23456)
for key in ("total_size", "files", "folders", "by_ext", "top_level"):
    check(f"summary: {key}", rep.get(key) == EXPECTED[key], rep.get(key))
check("summary: root, skipped, seconds", rep.get("root") == os.path.abspath(FIXTURE) and rep.get("skipped") == 0
      and rep.get("seconds") == 1.235, (rep.get("root"), rep.get("skipped"), rep.get("seconds")))
check("the scan changed nothing on disk", listing(FIXTURE) == before)

seen = []
top_big, _ = scan(FIXTURE_BIG, progress=seen.append)
check("progress is reported every 2,000 files", len(seen) == 25 and seen[0] == 2000, seen[:3])
check("big fixture counts", top_big.files == 50_000 and top_big.folders == 1_050, (top_big.files, top_big.folders))
stop = scan(FIXTURE_BIG, cancel=lambda: True)[0]
check("cancel stops the scan", stop.files < 50_000, stop.files)
missing = scan(os.path.join(FIXTURE, "no such folder"))
check("an unreadable folder is skipped and counted", missing[1] == 1 and missing[0].files == 0, missing[1])
r = timed_scan(FIXTURE)
check("timed_scan adds the seconds", len(r) == 3 and r[2] >= 0, r[1:])


def best(fn, n):
    out = 9e9
    for _ in range(n):
        t = time.perf_counter()
        fn()
        out = min(out, time.perf_counter() - t)
    return out


def naive():                                            # os.walk + an lstat per file: the slow way
    for d, _dirs, files in os.walk(FIXTURE_BIG):
        for x in files:
            os.lstat(os.path.join(d, x))


fast, slow = best(lambda: scan(FIXTURE_BIG), 3), best(naive, 2)
# Labels stay the same every run (the foreman tracks checks by label); the measured numbers go in `got`.
check("speed: 50,000 files in under 0.6 s", fast < 0.6, f"{fast:.2f} s")
check("speed: at least 4x faster than os.walk + lstat", slow / fast >= 4, f"{slow / fast:.1f}x")
finish()
