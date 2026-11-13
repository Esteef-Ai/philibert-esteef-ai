"""T13: the right-click menu (Show in Explorer, Copy path, Delete to the Recycle Bin) and Export, wired into the window."""
import csv
import faulthandler
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

faulthandler.dump_traceback_later(120, exit=True)
from _t import check, finish  # noqa: E402

try:
    from wiztry import actions
    from wiztry.app import App, bar
    from wiztry.filetypes import human
except Exception as e:                                  # noqa: BLE001
    check("wiztry.app and wiztry.actions import", False, e)
    finish()

# the app must import the dialogs it uses itself (tk.messagebox does not exist until someone imports it)
check("the app imports tkinter.messagebox itself", "tkinter.messagebox" in sys.modules)
import tkinter.filedialog as fd  # noqa: E402
import tkinter.messagebox as mb  # noqa: E402


def pump(app, secs):
    end = time.time() + secs
    while time.time() < end:
        app.update()
        time.sleep(0.01)


def buttons(w):
    out = []
    for c in w.winfo_children():
        if c.winfo_class() in ("TButton", "Button"):
            out.append(c)
        out += buttons(c)
    return out


def child(node, *names):
    for name in names:
        node = next(c for c in node.children if c.name == name)
    return node


def types(app):
    return sorted(app.types.item(i, "text").strip() for i in app.types.get_children())


# a folder of our own; nothing outside it is ever deleted
box = Path(tempfile.mkdtemp(prefix="pc_test_"))
root = box / "scanned"
(root / "keep").mkdir(parents=True)
(root / "junk" / "deep").mkdir(parents=True)
(root / "keep" / "a.txt").write_bytes(b"a" * 100)
(root / "keep" / "b.log").write_bytes(b"b" * 300)
(root / "junk" / "c.bin").write_bytes(b"c" * 1000)
(root / "junk" / "deep" / "d.bin").write_bytes(b"d" * 2000)
(root / "top.dat").write_bytes(b"t" * 50)
R = str(root)

errors = []
app = App(R)
app.report_callback_exception = lambda exc, val, tb: errors.append(repr(val))
app.geometry("1200x800+-4000+-4000")                    # a real, mapped window, kept off the desktop
pump(app, 0.6)
try:
    clip_before = app.clipboard_get()
except Exception:                                       # noqa: BLE001
    clip_before = None
app.start_scan(R)
end = time.time() + 30
while app.busy and time.time() < end:
    app.update()
    time.sleep(0.02)
pump(app, 0.3)
tree, top = app.tree, app.top
top_row = tree.get_children("")[0]

# 1. what is there
menu = getattr(app, "menu", None)
labels = [menu.entrycget(i, "label") for i in range((menu.index("end") or 0) + 1)] if menu is not None else []
check("app.menu has Show in Explorer, Copy path, Delete (Recycle Bin)...", labels == ["Show in Explorer", "Copy path", "Delete (Recycle Bin)..."], labels)
check("the tree and the treemap answer right-clicks", bool(tree.bind("<Button-3>")) and bool(app.canvas.bind("<Button-3>")),
      (tree.bind(), app.canvas.bind()))
check("the Delete key works in the tree", bool(tree.bind("<Delete>")), tree.bind())
check("there is an Export... button", [str(b.cget("text")) for b in buttons(app)].count("Export...") == 1, [str(b.cget("text")) for b in buttons(app)])

# 2. nothing selected: every tool does nothing, quietly
tree.selection_set(())
check("selected_node() is None when no row is selected", app.selected_node() is None)
asked = []
mb.askyesno = lambda *a, **k: asked.append((a, k)) or True
shown = []
actions.show_in_explorer = lambda path: shown.append(path)
for i in range(len(labels)):
    menu.invoke(i)
pump(app, 0.1)
check("with nothing selected the menu does nothing", not asked and not shown and (root / "top.dat").exists(), (asked, shown))

# 3. Copy path and Show in Explorer
dat = child(top, "top.dat")
app.select_node(dat)
check("selected_node() is the selected row's Node", app.selected_node() is dat)
app.copy_path()
check("Copy path puts the full path on the clipboard", app.clipboard_get() == dat.path, app.clipboard_get())
check("and says so in the status line", "copied" in app.status.get().lower(), app.status.get())
menu.invoke(0)
check("Show in Explorer calls actions.show_in_explorer with the path", shown == [dat.path], shown)

# 4. Delete: the question, and No
mb.askyesno = lambda *a, **k: asked.append((a, k)) or False
ok = app.delete_selected()
check("Delete asks first", len(asked) == 1, len(asked))
said = " ".join(str(x) for x in asked[0][0]) + " " + " ".join(str(v) for v in asked[0][1].values()) if asked else ""
check("the question names the path and says Recycle Bin", dat.path in said and "Recycle Bin" in said, said[:200])
check("answering No deletes nothing", ok is False and (root / "top.dat").exists() and app.selected_node() is dat, ok)

# 5. Delete: Yes, a file
mb.askyesno = lambda *a, **k: True
dat_row = app.items[id(dat)]
ok = app.delete_selected()
pump(app, 0.3)
check("answering Yes moves the file to the Recycle Bin", ok is True and not (root / "top.dat").exists(), ok)
check("its row leaves the tree", not tree.exists(dat_row) and dat_row not in app.nodes and id(dat) not in app.items)
check("the totals in memory follow", (top.size, top.files, top.folders) == (3400, 4, 3), (top.size, top.files, top.folders))
vals = tree.item(top_row, "values")
check("the top row shows the new size and counts", vals[1] == human(3400) and str(vals[3]) == "4" and str(vals[4]) == "3", vals)
check("the status line says what went to the Recycle Bin", "Recycle Bin" in app.status.get() and "top.dat" in app.status.get(), app.status.get())
check("the File Types list loses the type that is gone", types(app) == [".bin", ".log", ".txt"], types(app))
check("the treemap no longer shows the file", all(n is not dat for n in app.blocks.values()) and len(app.blocks) == 4, len(app.blocks))

# 6. Delete: Yes, an opened folder, while the treemap is zoomed inside it
junk = child(top, "junk")
deep = child(junk, "deep", "d.bin")
app.select_node(deep)                                   # opens junk and junk\deep in the tree
inside_rows = [app.items[id(deep)], app.items[id(deep.parent)]]
app.zoom(deep.parent)
app.select_node(junk)
ok = app.delete_selected()
pump(app, 0.3)
check("a folder goes to the Recycle Bin with what is in it", ok is True and not (root / "junk").exists() and (root / "keep" / "a.txt").exists(), ok)
check("the rows that were inside it are gone too", not any(tree.exists(i) for i in inside_rows) and all(tree.exists(i) for i in app.nodes),
      [i for i in app.nodes if not tree.exists(i)])
check("no Node of the deleted folder is left in app.items", id(deep) not in app.items and id(junk) not in app.items)
check("the treemap goes back to the scanned folder when its view was deleted", app.view is top, app.view and app.view.name)
check("the totals follow", (top.size, top.files, top.folders) == (400, 2, 1), (top.size, top.files, top.folders))
keep = child(top, "keep")
check("the rows that stay show their new share of the parent", tree.item(app.items[id(keep)], "values")[0] == bar(100.0),
      tree.item(app.items[id(keep)], "values")[0])
check("the File Types list follows", types(app) == [".log", ".txt"], types(app))
check("the treemap shows the two files left", len(app.blocks) == 2, len(app.blocks))

# 7. what may not be deleted, and a delete that fails
asked.clear()
mb.askyesno = lambda *a, **k: asked.append((a, k)) or True
tree.selection_set(top_row)
ok = app.delete_selected()
check("the scanned folder itself is refused without asking", ok is False and not asked and root.exists(), (ok, len(asked)))
check("and the status line says why", "scanned folder itself" in app.status.get(), app.status.get())


def boom(path, root_):
    raise OSError("the disk said no")


real_trash, actions.trash = actions.trash, boom
log = child(keep, "b.log")
app.select_node(log)
ok = app.delete_selected()
pump(app, 0.2)
actions.trash = real_trash
check("when Windows cannot delete, nothing changes in the tree", ok is False and app.selected_node() is log and top.files == 2
      and (root / "keep" / "b.log").exists(), (ok, top.files))
check("and the status line says it could not delete", "could not delete" in app.status.get().lower() and "the disk said no" in app.status.get(),
      app.status.get())

# 8. Export
out = box / "export.csv"
fd.asksaveasfilename = lambda *a, **k: ""
app.export()
check("Cancel in the Export dialog writes nothing", not out.exists())
fd.asksaveasfilename = lambda *a, **k: str(out)
next(b for b in buttons(app) if str(b.cget("text")) == "Export...").invoke()
pump(app, 0.2)
rows = list(csv.reader(open(out, encoding="utf-8-sig", newline=""))) if out.exists() else []
check("Export... writes the CSV of what is in the tree now (4 rows)", len(rows) == 5 and rows[1][0] == R and rows[1][2] == "400", rows[:2])
check("and the status line says where", "Exported 4 rows" in app.status.get() and str(out) in app.status.get(), app.status.get())

check("nothing raised an error", not errors, errors[:3])
try:
    app.clipboard_clear()
    if clip_before is not None:
        app.clipboard_append(clip_before)
        app.update()
except Exception:                                       # noqa: BLE001
    pass
app.destroy()
shutil.rmtree(box, ignore_errors=True)
finish()
