r"""Put this repo's shipping files onto a test drive, as an install would.

    python dev/deploy_local.py K:\Philibert

Copies only what a user gets (app, setup, launchers, catalog, README, final
brand files). Never touches the drive's data\, models\, runtime\, secrets\ or
Entertainment\, and never copies dev\ notes, design rounds or git history.
Runs the same personal-data check as sync_app.py over everything it copies.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_app import PERSONAL  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHIP = ["app", "setup", "brand/final", "Start-Windows.bat", "Start-Full-Windows.bat",
        "Start-Mac.command", "Start-Full-Mac.command", "models.json", "philibert.json", "README.md"]
TEXT = {".py", ".ps1", ".sh", ".bat", ".command", ".json", ".md", ".html", ".js", ".svg", ".txt"}
# The repo's address, which Update needs. It names the developer's GitHub account
# until the repo moves to an Esteef.Ai organization - then delete this allowance.
REPO_ADDRESS = "sskrobe/philibert-esteef-ai"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    dst = Path(sys.argv[1])
    dst.mkdir(parents=True, exist_ok=True)
    problems, allowed, n, busy = [], set(), 0, []
    for item in SHIP:
        src = REPO / item
        files = [src] if src.is_file() else [p for p in src.rglob("*") if p.is_file()]
        for f in files:
            if "__pycache__" in f.parts:
                continue
            rel = f.relative_to(REPO)
            if f.suffix.lower() in TEXT:
                text = f.read_text(encoding="utf-8", errors="replace")
                for m in PERSONAL.finditer(text):
                    if text[m.start():m.start() + len(REPO_ADDRESS)] == REPO_ADDRESS:
                        allowed.add(str(rel))
                        continue
                    problems.append(f"{rel}: {m.group(0)}")
            out = dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.is_file() and out.read_bytes() == f.read_bytes():
                continue                  # unchanged: leave it (a running Philibert may hold it open)
            try:
                shutil.copy2(f, out)
            except PermissionError:
                busy.append(str(rel))
                continue
            n += 1
    for d in ("data", "models", "Entertainment/Cartridges"):
        (dst / d).mkdir(parents=True, exist_ok=True)
    print(f"copied {n} files to {dst}")
    if busy:
        print("IN USE, not copied (close Philibert on that drive and deploy again): " + ", ".join(busy))
    if allowed:
        print(f"note: the repo address {REPO_ADDRESS} (a personal GitHub account) is still in: "
              + ", ".join(sorted(allowed)) + " - move the repo to the Esteef.Ai organization")
    if problems:
        print("PERSONAL DATA in shipped files:")
        for p in problems:
            print("  " + p)
        sys.exit(1)


if __name__ == "__main__":
    main()
