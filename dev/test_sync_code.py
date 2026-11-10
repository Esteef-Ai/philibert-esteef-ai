"""Tests for dev/sync_code.py: the Philibert Code build refuses anything personal, unbranded or missing.

    python dev/test_sync_code.py          fake-source checks (fast) + a real build check from ND3 (read-only)
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_app  # noqa: E402
import sync_code as sc  # noqa: E402

results = []


def check(label, ok, got=""):
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f" - got {got!r}"[:300]))


def fake(files):
    """A throwaway ND-like folder read as a worktree Source."""
    root = Path(tempfile.mkdtemp(prefix="fake_nd_"))
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return root, sc.Source(worktree=True, root=root)


RULES = [("app.py", r'PRODUCT = "NeuralDock"', 'PRODUCT = "Philibert Code"', 1),
         ("ui.html", sc.WORD, "Philibert Code", 2)]
GOOD = {"app.py": 'PRODUCT = "NeuralDock"\nCONFIG = "neuraldock_config.json"\nRUN = "NeuralDock_launcher.py"\n',
        "ui.html": "<title>NeuralDock</title><p>NeuralDock is running. Start NeuralDock_launcher.py</p>",
        "live/static/a.js": "x = 1\n", "live/static/font.woff2": b"\x00\x01binary"}


def run(files, rules=RULES, listed=("app.py", "ui.html"), dirs=("live",)):
    root, src = fake(files)
    out = Path(tempfile.mkdtemp(prefix="fake_out_")) / "app"
    (out / "old.txt").parent.mkdir(parents=True)
    (out / "old.txt").write_text("previous build")
    try:
        ok, lines = sc.build(src, out, files=list(listed), dirs=list(dirs), rules=rules)
        built = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
        return ok, lines, built
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(out.parent, ignore_errors=True)


# -- a clean source builds, brands what users see and keeps identifiers --------------------------
ok, lines, built = run(GOOD)
check("a clean source builds", ok, lines)
app = built.get("app.py", b"").decode()
ui = built.get("ui.html", b"").decode()
check("the product name is rebranded", 'PRODUCT = "Philibert Code"' in app, app)
check("visible text is rebranded", "<title>Philibert Code</title>" in ui and "Philibert Code is running" in ui, ui)
check("identifiers keep their names", "neuraldock_config.json" in app and "NeuralDock_launcher.py" in app
      and "NeuralDock_launcher.py" in ui, (app, ui))
check("a folder is copied whole, binary files untouched", built.get("live/static/font.woff2") == b"\x00\x01binary"
      and "live/static/a.js" in built, sorted(built))
check("the previous build is replaced, not merged", "old.txt" not in built, sorted(built))
check("BUILD.json records the source", b'"Philibert Code"' in built.get("BUILD.json", b""), built.get("BUILD.json"))

ok, lines, built = run(dict(GOOD, **{"app.py": GOOD["app.py"].replace("\n", "\r\n")}),
                      rules=[("app.py", sc.L('PRODUCT = "NeuralDock"\nCONFIG'), 'PRODUCT = "Philibert Code"\nCONFIG', 1)])
check("rules written with \\n match a CRLF file, which keeps CRLF", ok and b'PRODUCT = "Philibert Code"\r\nCONFIG'
      in built.get("app.py", b"") and b"\n" not in built["app.py"].replace(b"\r\n", b""), (lines, built.get("app.py")))

# -- personal data stops the build and nothing is written -----------------------------------------
bad = dict(GOOD, **{"app.py": GOOD["app.py"] + "VAULT = r'G:\\!!Obsidian\\notes'\nOWNER = 'Steve'\n"})
ok, lines, built = run(bad)
check("a personal name stops the build", not ok and any("personal" in x and "Steve" in x for x in lines), lines)
check("a refused build leaves the previous one alone", built.get("old.txt") == b"previous build", sorted(built))
scrubbed = sync_app.scrub("p = r'G:\\EsteefAi\\ComfyUI'")
check("known developer folders are scrubbed, not refused", "EsteefAi" not in scrubbed
      and not sync_app.PERSONAL.search(scrubbed), scrubbed)
ok, lines, _ = run(dict(GOOD, **{"app.py": GOOD["app.py"] + "MAIL = 'someone@gmail.com'\n"}))
check("an email address stops the build", not ok and any("gmail" in x for x in lines), lines)

# -- the brand guard ------------------------------------------------------------------------------
ok, lines, _ = run(dict(GOOD, **{"ui.html": GOOD["ui.html"] + "<b>NeuralDock</b>"}))
check("a new visible 'NeuralDock' in ND3 stops the build (count changed)", not ok
      and any("expected 2" in x and "found 3" in x for x in lines), lines)
ok, lines, _ = run(dict(GOOD, **{"app.py": 'PRODUCT = "ND"\n'}))
check("a moved product line stops the build", not ok and any("expected 1" in x for x in lines), lines)

# -- what is never shipped, and missing files -----------------------------------------------------
ok, lines, _ = run(dict(GOOD, **{"temp/notes.py": "x"}), listed=("app.py", "ui.html", "temp/notes.py"))
check("temp/ is never shipped even if listed", not ok and any("never shipped: temp/notes.py" in x for x in lines), lines)
for rel in ("neuraldock_config.json", "neuraldock_memory.json", "chat_session.json", "chats/a.json", "bench/t3.py"):
    check(f"never shipped: {rel}", bool(sc.NEVER.search(rel)))
ok, lines, built = run(GOOD, listed=("app.py", "ui.html", "nd_extra.py"))
check("a listed file nothing uses may be absent (skipped, noted)", ok and any("skipped nd_extra.py" in x for x in lines), lines)
ok, lines, _ = run(dict(GOOD, **{"app.py": GOOD["app.py"] + "import nd_extra\n"}), listed=("app.py", "ui.html", "nd_extra.py"))
check("a missing file that the build uses stops it", not ok and any("used by app.py" in x for x in lines), lines)

# -- the real build from ND3 (read-only), into a scratch folder ------------------------------------
if sc.ND.is_dir():
    out = Path(tempfile.mkdtemp(prefix="pc_real_")) / "app"
    try:
        ok, lines = sc.build(sc.Source(), out)
        check("the real build from ND3's last commit passes", ok, lines)
        if ok:
            launcher = (out / "NeuralDock_launcher.py").read_text(encoding="utf-8")
            check("the launcher is Philibert Code", 'else "Philibert Code"' in launcher)
            raw_l = (out / "NeuralDock_launcher.py").read_bytes()
            check("the launcher keeps its CRLF line endings (no churn)", raw_l.count(b"\r\n") > 1000
                  and raw_l.count(b"\n") == raw_l.count(b"\r\n"), raw_l.count(b"\n") - raw_l.count(b"\r\n"))
            check("phase 2: the inside-Philibert switch and the drop lists are in",
                  "IN_PHILIBERT = (not PORTABLE)" in launcher and "CODE_DROP_TOOLS = {" in launcher
                  and "CODE_BLOCKED_API = (" in launcher)
            check("phase 2: remote-device tools are never offered", "DEVICE_TOOL_SCHEMAS if device_snapshot()" not in launcher)
            check("phase 2: device/pairing/Heretic endpoints are refused", "if path.startswith(CODE_BLOCKED_API):" in launcher)
            check("phase 2: Philibert's and Philibert Code's program folders are protected",
                  '"code/app", "code/tools", "code/pylib"' in launcher and "(PORTABLE or IN_PHILIBERT) and name in" in launcher)
            check("phase 2: the shared notes vault is Philibert's", 'Path(os.environ["PHILIBERT_ROOT"]) / "data"' in launcher)
            ui_t = (out / "NeuralDock_ui.html").read_text(encoding="utf-8")
            check("phase 2: the Heretic and device panels are hidden", "Philibert Code: not included" in ui_t)
            check("phase 3: the chat-reference module and script ship (from shared/)",
                  (out / "nd_chatref.py").is_file() and (out / "live" / "static" / "chatref.js").is_file())
            check("phase 3: the /api/chatref route sits after the sign-in check",
                  launcher.index('if path == "/api/chatref":') > launcher.index("if path not in AUTH_EXEMPT and not self.authed():"))
            check("phase 3: the main window has the button and loads the script",
                  'id="chatref-btn"' in ui_t and "ChatRef.attach(document.getElementById('chatref-btn')" in ui_t)
            el_t = (out / "elena_ui.html").read_text(encoding="utf-8")
            check("phase 3: the chat page has the button too", 'id="refbtn"' in el_t and "ChatRef.attach" in el_t)
            have = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
            check("coding ships: worker, foreman, playbooks", {"opencode_worker.py", "nd_foreman.py",
                  "prompts/foreman_worker_opencode.md"} <= have, sorted(have)[:10])
            check("no data, settings or scratch in the build", not any(sc.NEVER.search(p) for p in have),
                  [p for p in have if sc.NEVER.search(p)])
            import py_compile
            bad = []
            for p in out.rglob("*.py"):
                try:
                    py_compile.compile(str(p), doraise=True, cfile=str(Path(tempfile.gettempdir()) / "pc_compile.pyc"))
                except py_compile.PyCompileError as e:
                    bad.append(f"{p.name}: {e.msg[:80]}")
            check("every built .py compiles", not bad, bad)
            left = [f"{p.name}" for p in out.rglob("*") if p.is_file() and p.suffix in sync_app.TEXT
                    and sync_app.PERSONAL.search(p.read_text(encoding="utf-8", errors="replace"))]
            check("a final sweep finds nothing personal", not left, left)
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)

passed = sum(results)
print(f"{passed} passed, {len(results) - passed} failed")
sys.exit(0 if passed == len(results) else 1)
