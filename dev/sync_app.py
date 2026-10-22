r"""Copy the ND files Philibert runs on from the NeuralDock source into app/.

NeuralDock (the ND3 folder beside this repo, or ND_SOURCE) is where the code is
written and tested; this repo is what drives get. Run, review `git diff`,
commit, push - then each drive's Update button pulls it.

    python dev/sync_app.py

Privacy: Philibert ships with its branding and nothing else of the developer's.
Every copied file is scrubbed of the developer's own folder names (they only
appear in comments, examples and non-portable defaults), and the sync REFUSES
to finish if anything personal is left - an email, the Windows user name, a
personal drive folder or the vault's name. Memory, chats, notes, the vault,
config and history are never copied: only the code files listed below.
"""
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ND = Path(os.environ.get("ND_SOURCE") or (REPO.parent / "ND3"))
APP = REPO / "app"
FILES = ["NeuralDock_launcher.py", "NeuralDock_ui.html", "elena_ui.html", "elena_mark.js",
         "nd_philibert.py", "nd_browser.py", "nd_build_plan.py", "nd_design_review.py",
         "nd_placement.py", "nd_memory_index.py", "nd_obsidian_memory.py", "nd_gpu.py",
         "nd_reskin.py", "nd_test_probe.py", "nd_gui_smoke.py", "ui_house_style.md"]
DIRS = ["live"]          # Philibert Chat's one-stop page (Elena Live), copied whole
TEXT = {".py", ".html", ".js", ".css", ".svg", ".md", ".json", ".txt"}

# The developer's folders -> neutral placeholders. Each is applied in its \, \\
# and / spellings. Case is kept where code compares paths case-insensitively
# ("G:\TMP" / "g:\tmp" stay a matching pair).
SCRUB = [
    (r"G:\!Ai\ND-Portable", r"D:\Portable"),
    (r"G:\!!Obsidian", r"D:\Obsidian"),
    (r"G:\EsteefAi", r"D:\AI"),
    (r"T:\EsteefAi", r"D:\AI"),
    (r"T:\HereticModel", r"D:\Models"),
    (r"T:\NeuralDock", r"D:\NeuralDock"),
    (r"T:\ComfyUI", r"D:\ComfyUI"),
    (r"G:\AI_Chat_Models", r"D:\Models"),
    (r"G:\GolfItMapMaker", r"D:\Projects\MapMaker"),
    (r"G:\TMP", r"D:\Temp"),
    (r"g:\tmp", r"d:\temp"),
    (r"C:\Heretic", r"C:\Tools\Heretic"),
    ("GolfItMapMaker", "MapMaker"),
    ("golfit_main", "mapmaker_main"),
    ("golfit_gui", "mapmaker_gui"),
    ("!!Obsidian", "Obsidian"),
]

# Anything matching these after the scrub stops the sync.
PERSONAL = re.compile(
    r"sskro\w*|@gmail\.com|Users[\\/]+sskro|!!Obsidian|ClaudeWorks|GolfIt|"
    r"[GT]:[\\/]+(?:EsteefAi|TMP|AI_Chat_Models|!Ai|!!|ComaToast|ElenaLive|Heretic)|"
    r"C:[\\/]+Heretic", re.I)


def spellings(a, b):
    yield a, b
    if "\\" in a:
        yield a.replace("\\", "\\\\\\\\"), b.replace("\\", "\\\\\\\\")   # escaped twice (JSON in a string)
        yield a.replace("\\", "\\\\"), b.replace("\\", "\\\\")
        yield a.replace("\\", "/"), b.replace("\\", "/")


def scrub(text):
    for a, b in SCRUB:
        for x, y in spellings(a, b):
            text = text.replace(x, y)
    return text


def main():
    if not ND.is_dir():
        sys.exit(f"NeuralDock source not found at {ND} (set ND_SOURCE)")
    APP.mkdir(exist_ok=True)
    problems = []
    rels = list(FILES)
    for d in DIRS:
        rels += [p.relative_to(ND).as_posix() for p in sorted((ND / d).rglob("*"))
                 if p.is_file() and "__pycache__" not in p.parts]
    for f in rels:
        dst = APP / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        raw = (ND / f).read_bytes()
        if Path(f).suffix.lower() not in TEXT:
            dst.write_bytes(raw)              # fonts, images: nothing to scrub
            continue
        out = scrub(raw.decode("utf-8"))
        for m in PERSONAL.finditer(out):
            line = out.count("\n", 0, m.start()) + 1
            problems.append(f"{f}:{line}: {m.group(0)}")
        dst.write_bytes(out.encode("utf-8"))
    gone = sorted(p.name for p in APP.iterdir() if p.is_file() and p.name not in FILES)
    if problems:
        print("PERSONAL DATA LEFT - add a SCRUB entry or remove it at the source:")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    print(f"synced {len(rels)} files from {ND}, scrubbed, nothing personal left"
          + (f"; not in the list any more: {gone}" if gone else ""))


if __name__ == "__main__":
    main()
