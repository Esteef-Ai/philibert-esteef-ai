r"""Build Philibert Code's app (code/app/) from the NeuralDock source - read-only.

    python dev/sync_code.py               build from ND3's last commit (HEAD)
    python dev/sync_code.py --worktree    build from ND3's working files instead (uncommitted edits too)
    python dev/sync_code.py --check       build into a scratch folder only; report, write nothing here

Philibert Code is NeuralDock rebranded (dev/PHILIBERT_CODE.md). The developer's ND3 folder is
their own dev copy and is NEVER written to: this script only reads it (`git show`, `git ls-tree`,
plain file reads). The rebrand happens here, in the copy.

Like dev/sync_app.py (whose file list, scrub table and personal-data guard it reuses), it:
  1. copies an explicit list of code files - never data, config, memory, chats, temp/ or bench/;
  2. scrubs the developer's folder names and REFUSES if anything personal is left;
  3. applies the brand swaps, each with the exact number of hits it expects, so a change in ND3
     that moves or adds a string stops the build instead of shipping it half-branded.
Everything is staged first; code/app/ is only replaced when all three pass.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_app  # noqa: E402  - Philibert's own build: FILES, DIRS, TEXT, scrub(), PERSONAL
import patching  # noqa: E402  - counted edits + repo-owned files (shared/), used by both builds

REPO = sync_app.REPO
ND = sync_app.ND
OUT = REPO / "code" / "app"

# Philibert's files, plus what only Philibert Code runs: the hidden-desktop automation, temp clean-up,
# the model-store index, and coding (the OpenCode worker, the foreman and their playbooks).
CODE_ONLY = ["nd_desktop.py", "nd_cleanup.py", "blob_index.py", "opencode_worker.py", "nd_foreman.py",
             "prompts/foreman_worker.md", "prompts/foreman_worker_opencode.md"]
FILES = list(dict.fromkeys(sync_app.FILES + CODE_ONLY))
DIRS = list(sync_app.DIRS)
# Never shipped, whatever a list says: data, settings, history, memory and scratch.
NEVER = re.compile(r"(^|/)(temp|bench|experiments|chats|chat_jobs|projects|bands|modelfiles|opencode|"
                   r"\.nd_backups|__pycache__)/|neuraldock_(config|memory)\.json$|chat_session\.json$|"
                   r"nd_(usage|session_ctx|models)\.json$", re.I)

# What the user sees. Identifiers stay: NeuralDock_launcher.py, neuraldock_config.json, the API's
# "app": "NeuralDock" answer and the model-facing "[NeuralDock: ...]" notes are matched by code.
WORD = r"(?<![\w.\\/])NeuralDock(?![\w.])"
BRAND = [
    # (file, pattern, replacement, expected hits)
    ("NeuralDock_launcher.py", r'PRODUCT  = "Philibert" if PORTABLE else "NeuralDock"',
     'PRODUCT  = "Philibert" if PORTABLE else "Philibert Code"', 1),
    ("NeuralDock_launcher.py", r'"You are NeuralDock AI,', '"You are Philibert Code AI,', 1),
    ("NeuralDock_launcher.py", r'log\("ESTEEF\.AI // NeuralDock v3\.0 starting\.\.\.", "info"\)',
     'log(f"{PRODUCT} // Esteef.Ai starting...", "info")', 1),
    ("NeuralDock_launcher.py", r"NEURALDOCK  //  POWERED BY ESTEEF\.AI", "PHILIBERT CODE  //  POWERED BY ESTEEF.AI", 1),
    ("NeuralDock_ui.html", r"ESTEEF\.AI // NeuralDock", "Philibert Code // Esteef.Ai", 3),
    ("NeuralDock_ui.html", r"ESTEEF\.AI // NEURALDOCK", "PHILIBERT CODE // ESTEEF.AI", 2),
    ("NeuralDock_ui.html", WORD, "Philibert Code", 14),
]


L = re.escape
# Phase 2: what Philibert Code leaves out, and how it runs inside a Philibert install. Applied after
# BRAND, with the same exact-count rule. ND3 is not edited for this - these edits exist only in the copy.
PATCHES = [
    # the switches the edits below use
    ("NeuralDock_launcher.py", L('PRODUCT  = "Philibert" if PORTABLE else "Philibert Code"\n'),
     'PRODUCT  = "Philibert" if PORTABLE else "Philibert Code"\n'
     "# Philibert Code inside a Philibert install (code\\start.ps1 sets PHILIBERT_ROOT): Philibert's\n"
     "# models, runtime and notes vault, its own data in data\\code, and Philibert's program protected.\n"
     'IN_PHILIBERT = (not PORTABLE) and bool(os.environ.get("PHILIBERT_ROOT"))\n'
     "# Not part of Philibert Code: other devices (remote control) and Heretic.\n"
     'CODE_DROP_TOOLS = {"device_action", "list_devices"}\n'
     'CODE_BLOCKED_API = ("/api/device/", "/api/devices", "/api/pair_", "/api/heretic")\n', 1),
    # remote devices: never offered to the model, refused if called anyway, never asked about
    ("NeuralDock_launcher.py", r"\n[ \t]+\+ \(DEVICE_TOOL_SCHEMAS if device_snapshot\(\) else \[\]\)\)", ")", 1),
    ("NeuralDock_launcher.py", L("        if PORTABLE and name in portable_drop():\n"),
     "        if name in CODE_DROP_TOOLS:\n"
     '            return f"[NOT AVAILABLE] {name} is not part of {PRODUCT} - do not call it again."\n'
     "        if PORTABLE and name in portable_drop():\n", 1),
    ("NeuralDock_launcher.py", L('if PORTABLE and c["name"] in portable_drop():'),
     'if (PORTABLE and c["name"] in portable_drop()) or c["name"] in CODE_DROP_TOOLS:', 1),
    # their endpoints (devices, pairing, Heretic) answer "not here"
    ("NeuralDock_launcher.py", L("        path   = self.path\n"),
     "        path   = self.path\n"
     "        if path.startswith(CODE_BLOCKED_API):\n"
     '            self.send_json({"ok": False, "error": "not part of Philibert Code"}, 404)\n'
     "            return\n", 1),
    # inside Philibert: Philibert's program (and Philibert Code's own) is never written to
    ("NeuralDock_launcher.py", L('PROTECTED_DIRS = ("app", "setup", "runtime", "models", "installer", "brand", "Entertainment/emulator")'),
     'PROTECTED_DIRS = ("app", "setup", "runtime", "models", "installer", "brand", "Entertainment/emulator",\n'
     '                  "code/app", "code/tools", "code/pylib")', 1),
    ("NeuralDock_launcher.py", L('if PORTABLE and name in ("write_file", "edit_file", "run_script", "delete_file", "move_file"):'),
     'if (PORTABLE or IN_PHILIBERT) and name in ("write_file", "edit_file", "run_script", "delete_file", "move_file"):', 1),
    # inside Philibert: the one shared notes vault (chats stay separate, in data\code)
    ("NeuralDock_launcher.py", L('    if not PORTABLE:\n        return\n    _config["obsidian_root"] = str(_CONFIG_DIR)\n'),
     "    if IN_PHILIBERT:                       # Philibert Code: Philibert's own notes vault\n"
     '        _config["obsidian_root"] = str(Path(os.environ["PHILIBERT_ROOT"]) / "data")\n'
     '        _config["obsidian_vault"] = "vault"\n'
     '    if not PORTABLE:\n        return\n    _config["obsidian_root"] = str(_CONFIG_DIR)\n', 1),
    # inside Philibert, Ollama is on Philibert's port (ND_OLLAMA_URL, set by the launcher), not 11434
    ("opencode_worker.py", L('OLLAMA = "http://127.0.0.1:11434"\n'),
     'OLLAMA = os.environ.get("ND_OLLAMA_URL") or "http://127.0.0.1:11434"\n', 1),
    ("nd_foreman.py", L('OLLAMA_URL = "http://127.0.0.1:11434"\n'),
     'OLLAMA_URL = os.environ.get("ND_OLLAMA_URL") or "http://127.0.0.1:11434"\n', 1),
    # OpenCode's config and run logs are data: data\code\opencode, not inside the program (an update replaces it)
    ("opencode_worker.py", L('HOME = HERE / "opencode"\n'),
     'HOME = (Path(os.environ["ND_DATA_DIR"]) / "opencode") if os.environ.get("ND_DATA_DIR") else HERE / "opencode"\n', 1),
    # the UI: no Heretic and no device pairing panels
    ("NeuralDock_ui.html", L("</head>"),
     "<style>/* Philibert Code: not included */ .sc:has(#heretic-model-list), .sc:has(#dev-list),"
     " .cr:has(#d-heretic), .cc:has(#cs-heretic) { display: none !important; }</style>\n</head>", 1),
]


def _git(*args):
    return subprocess.run(["git", "--no-optional-locks", "-C", str(ND), *args],
                          capture_output=True, check=True).stdout


class Source:
    """Reads ND3 without writing to it: from the last commit (default) or the working files."""

    def __init__(self, worktree=False, root=ND):
        self.worktree, self.root = worktree, Path(root)

    def read(self, rel):
        if self.worktree:
            return (self.root / rel).read_bytes()
        return _git("show", f"HEAD:{rel}")

    def listdir(self, d):
        if self.worktree:
            return [p.relative_to(self.root).as_posix() for p in sorted((self.root / d).rglob("*")) if p.is_file()]
        return [x for x in _git("ls-tree", "-r", "--name-only", "HEAD", "--", d).decode("utf-8").splitlines() if x]

    def describe(self):
        # never the folder's path: it names the developer's drive layout and ships in BUILD.json
        if self.worktree:
            return {"from": "worktree"}
        return {"from": "commit", "commit": _git("rev-parse", "HEAD").decode().strip()}


RULES = BRAND + PATCHES + patching.CHATREF_BOTH + patching.CHATREF_CODE + patching.AUTONOMY_CODE


def brand(files, rules=BRAND):
    """Apply counted edits to {rel: LF text}; -> list of problems (a wrong hit count is one)."""
    return patching.apply(files, rules)


def build(src, out, files=None, dirs=None, rules=None, shared=None):
    """Stage, scrub, check and brand; replace `out` only when clean. -> (ok, report lines)."""
    if rules is None:
        rules = RULES
    if shared is None:                          # the repo's own files: only for the real build
        shared = patching.shared_files() if files is None else {}
    rels = list(files if files is not None else FILES)
    for d in (dirs if dirs is not None else DIRS):
        rels += [r for r in src.listdir(d) if "__pycache__" not in r]
    rels = list(dict.fromkeys(rels))
    problems, texts, blobs, missing, notes, crlf = [], {}, {}, [], [], set()
    for rel in rels:
        if NEVER.search(rel):
            problems.append(f"never shipped: {rel}")
            continue
        try:
            raw = src.read(rel)
        except (OSError, subprocess.CalledProcessError):
            missing.append(rel)
            continue
        if Path(rel).suffix.lower() not in sync_app.TEXT:
            blobs[rel] = raw
            continue
        text = sync_app.scrub(raw.decode("utf-8"))
        for m in sync_app.PERSONAL.finditer(text):
            problems.append(f"personal: {rel}:{text.count(chr(10), 0, m.start()) + 1}: {m.group(0)}")
        if "\r\n" in text:                      # rules are written with \n; the file keeps its own endings
            crlf.add(rel)
            text = text.replace("\r\n", "\n")
        texts[rel] = text
    # A listed file the source does not have (e.g. still uncommitted in ND3) is fine only when
    # nothing in this build uses it; otherwise the app would break at run time.
    for rel in missing:
        stem = Path(rel).stem
        users = [r for r, t in texts.items() if re.search(rf"\b{re.escape(stem)}\b", t)]
        if users:
            problems.append(f"missing in the source but used by {', '.join(users[:3])}: {rel}")
        else:
            notes.append(f"skipped {rel}: not in the source, and nothing in this build uses it")
    rels = [r for r in rels if r not in missing]
    for rel, text in shared.items():            # owned by this repo, not ND3 - same privacy check
        for m in sync_app.PERSONAL.finditer(text):
            problems.append(f"personal: {rel}: {m.group(0)}")
        texts[rel] = text.replace("\r\n", "\n")
        rels.append(rel)
    problems += brand(texts, rules)
    if problems:
        return False, problems
    stage = Path(tempfile.mkdtemp(prefix="philibert_code_"))
    try:
        for rel, data in list(blobs.items()) + [(r, (t.replace("\n", "\r\n") if r in crlf else t).encode("utf-8"))
                                                for r, t in texts.items()]:
            p = stage / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        info = json.dumps({"product": "Philibert Code", "source": src.describe(), "files": len(rels)}, indent=2)
        if sync_app.PERSONAL.search(info):
            return False, [f"personal: BUILD.json: {sync_app.PERSONAL.search(info).group(0)}"]
        (stage / "BUILD.json").write_text(info + "\n", encoding="utf-8")
        out = Path(out)
        if out.exists():
            shutil.rmtree(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(stage, out)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return True, [f"built {len(rels)} files into {out}, scrubbed, branded, nothing personal left"] + notes


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not ND.is_dir():
        sys.exit(f"NeuralDock source not found at {ND} (set ND_SOURCE)")
    src = Source(worktree="--worktree" in argv)
    out = Path(tempfile.mkdtemp(prefix="philibert_code_check_")) / "app" if "--check" in argv else OUT
    ok, lines = build(src, out)
    print(("" if ok else "NOT BUILT - fix these first:\n  ") + "\n  ".join(lines))
    if ok and "--check" in argv:
        shutil.rmtree(out.parent, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
