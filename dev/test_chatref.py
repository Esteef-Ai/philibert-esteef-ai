"""Tests for shared/nd_chatref.py: each app sees only the OTHER app's chats, read-only, as a quoted block.

    python dev/test_chatref.py
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
import nd_chatref as cr  # noqa: E402

results = []


def check(label, ok, got=""):
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f" - got {got!r}"[:300]))


def write(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


root = Path(tempfile.mkdtemp(prefix="chatref_"))
try:
    (root / "app").mkdir()
    (root / "app" / "NeuralDock_launcher.py").write_text("#")
    # Philibert: two saved chats (one with a hidden reference message) and an empty one
    write(root / "data" / "chats" / "c20261109-100000-aaaa.json", {
        "id": "c20261109-100000-aaaa", "title": "Gig list for Friday", "updated": 1794200000,
        "messages": [{"role": "user", "content": "Make me a set list"},
                     {"role": "user", "content": "SECRET CONTEXT", "hidden": True},
                     {"role": "assistant", "content": "1. Opener\n2. Ballad"}]})
    write(root / "data" / "chats" / "c20261109-110000-bbbb.json", {
        "id": "c20261109-110000-bbbb", "title": "Long one", "updated": 1794300000,
        "messages": [{"role": "user", "content": f"line {i} " + "x" * 90} for i in range(200)]})
    write(root / "data" / "chats" / "c20261109-120000-cccc.json", {"id": "c20261109-120000-cccc", "title": "Empty",
                                                                   "updated": 1794400000, "messages": []})
    (root / "data" / "chats" / "_folders.json").write_text("[]")
    # Philibert Code: main-window tabs + one chat-page chat
    write(root / "data" / "code" / "chat_session.json", {"active": "c1", "tabs": [
        {"id": "c1_1", "name": "Fix the scanner", "history": [{"role": "user", "content": "why is scan slow"},
                                                              {"role": "assistant", "content": "It builds a tree."}]},
        {"id": "c2_2", "name": "Blank tab", "history": []}]})
    write(root / "data" / "code" / "chats" / "c20261109-130000-dddd.json", {
        "id": "c20261109-130000-dddd", "title": "Code chat page", "updated": 1794500000,
        "messages": [{"role": "user", "content": "hello from the code chat page"}]})

    before = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}

    # -- Philibert Code sees Philibert's chats ---------------------------------------------------------
    r = cr.handle({"op": "list"}, "code", root)
    titles = [c["title"] for c in r.get("chats", [])]
    check("Code lists Philibert's chats, newest first, empty ones left out", r.get("ok") and r.get("from") == "Philibert"
          and titles == ["Long one", "Gig list for Friday"], r)
    check("Code knows Philibert is installed", r.get("installed") is True, r)
    gig = next(c for c in r["chats"] if c["title"] == "Gig list for Friday")
    check("a hidden message is not counted or previewed", gig["count"] == 2 and "SECRET" not in gig["preview"], gig)
    b = cr.handle({"op": "get", "id": gig["id"]}, "code", root)
    t = b.get("text", "")
    check("the block is labelled with the app, title and date", t.startswith('[Referenced chat from Philibert: "Gig list for Friday" (')
          and t.rstrip().endswith("[End of referenced chat]"), t[:120])
    inner = t.strip().splitlines()[1:-1]         # between the label line and the end line
    check("every line of it is quoted", inner and all(ln.startswith(">") for ln in inner), inner)
    check("speakers are named (Me / the app)", "> Me: Make me a set list" in t and "> Philibert: 1. Opener" in t, t)
    check("a multi-line answer stays quoted line by line", "\n> 2. Ballad\n" in t, t)
    check("hidden context never goes into the block", "SECRET" not in t, t)
    big = cr.handle({"op": "get", "id": "c20261109-110000-bbbb"}, "code", root)
    check("a long chat keeps only its newest part, and says so", big.get("trimmed") and "only its newest part" in big["text"]
          and "line 199" in big["text"] and "line 0 " not in big["text"] and len(big["text"]) < cr.REF_CHARS + 600,
          (big.get("trimmed"), len(big.get("text", ""))))
    check("a trimmed block starts on a whole line", big["text"].splitlines()[1].startswith("> Me: line "), big["text"].splitlines()[1][:40])

    # -- Philibert sees Philibert Code's chats -----------------------------------------------------------
    r = cr.handle({"op": "list"}, "philibert", root)
    titles = [c["title"] for c in r.get("chats", [])]
    check("Philibert lists Code's chat-page chats and its main-window tabs", r.get("from") == "Philibert Code"
          and "Code chat page" in titles and "Fix the scanner" in titles and "Blank tab" not in titles, r)
    check("Philibert never lists its own chats here", "Gig list for Friday" not in titles, titles)
    tab = next(c for c in r["chats"] if c["title"] == "Fix the scanner")
    b = cr.handle({"op": "get", "id": tab["id"]}, "philibert", root)
    check("a Code tab becomes a labelled block", b.get("ok") and '[Referenced chat from Philibert Code: "Fix the scanner"' in b["text"]
          and "> Philibert Code: It builds a tree." in b["text"], b)
    check("Code shows as installed once it has data", r.get("installed") is True, r)

    # -- safety ---------------------------------------------------------------------------------------
    for bad in ("../../etc/passwd", "c..\\x", "", None, "x" * 200):
        b = cr.handle({"op": "get", "id": bad}, "code", root)
        check(f"a bad id is refused: {str(bad)[:20]!r}", b.get("ok") is False, b)
    check("an id from its own app is not found from this side",
          cr.handle({"op": "get", "id": "c20261109-130000-dddd"}, "code", root).get("ok") is False)
    check("an unknown op is refused", cr.handle({"op": "save"}, "code", root).get("ok") is False)
    check("an unknown app is refused", cr.handle({"op": "list"}, "other", root).get("ok") is False)
    after = {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()}
    check("nothing was written (read-only)", before == after, set(after) ^ set(before))

    # -- the other app missing ------------------------------------------------------------------------
    lone = Path(tempfile.mkdtemp(prefix="chatref_lone_"))
    (lone / "app").mkdir()
    (lone / "app" / "NeuralDock_launcher.py").write_text("#")
    r = cr.handle({"op": "list"}, "philibert", lone)
    check("Philibert without Philibert Code: not installed, no chats (the button hides)", r.get("ok")
          and r.get("installed") is False and r.get("chats") == [], r)
    shutil.rmtree(lone, ignore_errors=True)
    bad_json = root / "data" / "chats" / "c20261109-140000-eeee.json"
    bad_json.write_text("{not json", encoding="utf-8")
    check("a damaged chat file is skipped, not fatal", cr.handle({"op": "list"}, "code", root).get("ok"))
finally:
    shutil.rmtree(root, ignore_errors=True)

passed = sum(results)
print(f"{passed} passed, {len(results) - passed} failed")
sys.exit(0 if passed == len(results) else 1)
