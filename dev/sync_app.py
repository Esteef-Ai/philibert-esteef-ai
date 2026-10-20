r"""Copy the ND files Philibert runs on from ND3 into app/.

ND3 (G:\!Ai\ND3) is where the code is written and tested; this repo is what
drives get. Run, review `git diff`, commit, push - then each drive's Update
button pulls it.

    python dev/sync_app.py
"""
import shutil
from pathlib import Path

ND = Path(r"G:\!Ai\ND3")
APP = Path(__file__).resolve().parent.parent / "app"
FILES = ["NeuralDock_launcher.py", "NeuralDock_ui.html", "elena_ui.html", "elena_mark.js",
         "nd_philibert.py", "nd_browser.py", "nd_build_plan.py", "nd_design_review.py",
         "nd_placement.py", "nd_memory_index.py", "nd_obsidian_memory.py", "nd_gpu.py",
         "nd_reskin.py", "nd_test_probe.py", "nd_gui_smoke.py", "ui_house_style.md"]

APP.mkdir(exist_ok=True)
for f in FILES:
    shutil.copy2(ND / f, APP / f)
gone = sorted(p.name for p in APP.iterdir() if p.is_file() and p.name not in FILES)
print(f"synced {len(FILES)} files from {ND}" + (f"; not in the list any more: {gone}" if gone else ""))
