"""T12: the tools: delete to the Recycle Bin (guarded), show in Explorer, export to CSV, and forgetting a deleted item."""
import csv
import faulthandler
import os
import shutil
import tempfile
from pathlib import Path

faulthandler.dump_traceback_later(90, exit=True)
from _t import FIXTURE, WS, check, finish, listing  # noqa: E402

try:
    from wiztry import actions
    from wiztry.actions import can_delete, explorer_args, export_csv, forget, trash
    from wiztry.scanner import scan
except Exception as e:                                  # noqa: BLE001
    check("wiztry.actions imports", False, e)
    finish()

# The only thing in the app that may remove anything is the Recycle Bin call: the module must not know another way.
src = (WS / "wiztry" / "actions.py").read_text(encoding="utf-8")
banned = [w for w in ("os.remove", "os.unlink", "os.rmdir", "rmtree", "os.replace", "os.rename", "shutil.move", ".unlink(", ".rmdir(",
                      "send2trash", "del /", "rd /", "Remove-Item") if w in src]
check("actions.py has no way to delete or move files except the Recycle Bin call", not banned, banned)
check("it deletes through SHFileOperationW with FOF_ALLOWUNDO (the Recycle Bin)", "SHFileOperationW" in src and "FOF_ALLOWUNDO" in src)

fixture_before = listing(FIXTURE)

# a folder of our own to work in: nothing outside it may ever be touched
box = Path(tempfile.mkdtemp(prefix="pc_test_"))
root = box / "scanned"
(root / "keep").mkdir(parents=True)
(root / "junk" / "deep").mkdir(parents=True)
(root / "keep" / "a.txt").write_bytes(b"a" * 100)
(root / "keep" / "b.log").write_bytes(b"b" * 300)
(root / "junk" / "c.bin").write_bytes(b"c" * 1000)
(root / "junk" / "deep" / "d.bin").write_bytes(b"d" * 2000)
(root / "top.dat").write_bytes(b"t" * 50)
(box / "outside.txt").write_bytes(b"o" * 10)
R = str(root)
drive = os.path.splitdrive(R)[0] + "\\"

# 1. the guard: "" means allowed, anything else is the reason
check("a file inside the scanned folder may be deleted", can_delete(str(root / "top.dat"), R) == "", can_delete(str(root / "top.dat"), R))
check("a folder inside the scanned folder may be deleted", can_delete(str(root / "junk"), R) == "", can_delete(str(root / "junk"), R))
check("the scanned folder itself may not", can_delete(R, R) == "the scanned folder itself", can_delete(R, R))
check("the same folder written differently may not either", can_delete(R.upper() + "\\", R) == "the scanned folder itself",
      can_delete(R.upper() + "\\", R))
check("a file outside the scanned folder may not", can_delete(str(box / "outside.txt"), R) == "outside the scanned folder",
      can_delete(str(box / "outside.txt"), R))
check("a path that climbs out with .. may not", can_delete(str(root / "keep" / ".." / ".." / "outside.txt"), R) == "outside the scanned folder",
      can_delete(str(root / "keep" / ".." / ".." / "outside.txt"), R))
check("a folder whose name only starts the same may not", can_delete(R + "2", R) == "outside the scanned folder", can_delete(R + "2", R))
check("the folder above the scanned folder may not", can_delete(str(box), R) == "outside the scanned folder", can_delete(str(box), R))
check("a drive may not, even when a whole drive was scanned", can_delete(drive, drive) == "a drive", can_delete(drive, drive))
check("something that is not there may not", can_delete(str(root / "nope.txt"), R) == "not found", can_delete(str(root / "nope.txt"), R))
check("an empty path may not", can_delete("", R) != "", can_delete("", R))


def refuses(path):
    try:
        trash(path, R)
    except ValueError:
        return True
    except Exception as e:                              # noqa: BLE001
        return repr(e)
    return False


from _t import _results  # noqa: E402
if not all(_results):                                   # never try a real delete with a guard that is wrong
    shutil.rmtree(box, ignore_errors=True)
    finish()

# 2. trash() refuses with ValueError and removes nothing
check("trash() refuses a file outside the scanned folder", refuses(str(box / "outside.txt")) is True and (box / "outside.txt").exists(),
      refuses(str(box / "outside.txt")))
check("trash() refuses the scanned folder itself", refuses(R) is True and root.exists(), refuses(R))
check("trash() refuses what is not there", refuses(str(root / "nope.txt")) is True)

if not all(_results):
    shutil.rmtree(box, ignore_errors=True)
    finish()

# 3. the tree before anything is deleted, and the CSV export of it
top, _skipped = scan(R)
out = box / "export.csv"
n = export_csv(top, str(out))
rows = list(csv.reader(open(out, encoding="utf-8-sig", newline=""))) if out.exists() else []
check("export_csv writes the header", rows[:1] == [["Path", "Type", "Size", "Files", "Folders", "Modified"]], rows[:1])
check("one row for the scanned folder and one for everything in it (9 rows)", n == 9 and len(rows) == 10, (n, len(rows)))
check("the first row is the scanned folder with its totals", len(rows) > 1 and rows[1][:5] == [R, "Folder", "3450", "5", "3"], rows[1:2])
by_path = {r[0]: r for r in rows[1:]}
check("a file's row", by_path.get(str(root / "junk" / "deep" / "d.bin"), [])[1:5] == ["File", "2000", "1", "0"],
      by_path.get(str(root / "junk" / "deep" / "d.bin")))
check("a folder's row", by_path.get(str(root / "junk"), [])[1:5] == ["Folder", "3000", "2", "1"], by_path.get(str(root / "junk")))
when = (by_path.get(str(root / "junk" / "c.bin")) or [""] * 6)[5]
check("a file's Modified is a date and time (2026-11-12 14:05)", len(when) == 16 and when[4] == "-" and when[10] == " " and when[13] == ":", when)
order = [r[0] for r in rows[1:]]
check("folders come with their contents right after them, largest first",
      order[:4] == [R, str(root / "junk"), str(root / "junk" / "deep"), str(root / "junk" / "deep" / "d.bin")], order[:4])
check("export_csv changed nothing in the scanned folder", sorted(p.name for p in root.iterdir()) == ["junk", "keep", "top.dat"])

# 4. Show in Explorer: only the command is checked; no Explorer window is opened by this test
check("explorer_args selects the item in its folder", explorer_args(str(root / "top.dat")) == ["explorer.exe", "/select,", str(root / "top.dat")],
      explorer_args(str(root / "top.dat")))
check("show_in_explorer exists", callable(getattr(actions, "show_in_explorer", None)))

# 5. a real delete of one file, to the Recycle Bin
before_keep = sorted(os.listdir(root / "keep"))
trash(str(root / "top.dat"), R)
check("trash() removes the file", not (root / "top.dat").exists())
check("and nothing else", sorted(os.listdir(root / "keep")) == before_keep and (root / "junk" / "c.bin").exists()
      and (box / "outside.txt").exists(), sorted(os.listdir(root)))

# 6. forget(): the tree in memory follows, all the way up
node = next(c for c in top.children if c.name == "top.dat")
forget(node)
check("forget(file) takes it out of its folder", all(c.name != "top.dat" for c in top.children), [c.name for c in top.children])
check("and lowers the totals above it", (top.size, top.files, top.folders) == (3400, 4, 3), (top.size, top.files, top.folders))

# 7. a real delete of a folder with things inside
junk = next(c for c in top.children if c.name == "junk")
trash(junk.path, R)
check("trash() removes a folder and what is in it", not (root / "junk").exists())
check("and leaves the rest", (root / "keep" / "a.txt").exists() and (root / "keep" / "b.log").exists() and (box / "outside.txt").exists())
forget(junk)
check("forget(folder) lowers size, files and folders (itself and the one inside)",
      (top.size, top.files, top.folders) == (400, 2, 1), (top.size, top.files, top.folders))
again, _ = scan(R)
check("the tree in memory now equals a fresh scan", (again.size, again.files, again.folders) == (top.size, top.files, top.folders),
      (again.size, again.files, again.folders))
deep_keep = next(c for c in top.children if c.name == "keep").children[0]
forget(deep_keep)
check("forget() two levels down lowers every folder above", (top.size, top.files) == (100, 1)
      and next(c for c in top.children if c.name == "keep").size == 100, (top.size, top.files))

check("the fixture was never touched", listing(FIXTURE) == fixture_before)
shutil.rmtree(box, ignore_errors=True)
finish()
