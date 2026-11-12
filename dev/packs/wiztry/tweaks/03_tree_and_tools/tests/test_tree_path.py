"""T11: the folder tree cascades from the scanned folder down, and a clicked block shows the whole path to its file."""
import faulthandler
import os
import time

faulthandler.dump_traceback_later(90, exit=True)
from _t import FIXTURE, FIXTURE_BIG, check, finish  # noqa: E402

try:
    from wiztry.app import App, bar
except Exception as e:                                  # noqa: BLE001
    check("wiztry.app imports", False, e)
    finish()


def pump(app, secs):
    end = time.time() + secs
    while time.time() < end:
        app.update()
        time.sleep(0.01)


def scan(app, path):
    app.start_scan(path)
    end = time.time() + 60
    while app.busy and time.time() < end:
        app.update()
        time.sleep(0.02)
    pump(app, 0.3)


def chain(app, iid):
    """The row texts from the top of the tree down to this row."""
    out = []
    while iid:
        out.append(app.tree.item(iid, "text"))
        iid = app.tree.parent(iid)
    return out[::-1]


def find(node, *names):
    for name in names:
        node = next(c for c in node.children if c.name == name)
    return node


def open_row(app, iid):
    """What a click on a row's arrow does."""
    app.tree.focus(iid)
    app.tree.item(iid, open=True)
    app.tree.event_generate("<<TreeviewOpen>>")
    pump(app, 0.1)


errors = []
app = App(FIXTURE)
app.report_callback_exception = lambda exc, val, tb: errors.append(repr(val))
app.geometry("1200x800+-4000+-4000")                    # a real, mapped window, kept off the desktop
pump(app, 0.6)
scan(app, FIXTURE)
tree = app.tree
top = app.top

roots = tree.get_children("")
check("the tree has one row at the top: the scanned folder", len(roots) == 1 and tree.item(roots[0], "text") == "fixture",
      [tree.item(i, "text") for i in roots])
root = roots[0] if roots else ""
check("app.items maps a Node's id() to its row", getattr(app, "items", {}).get(id(top)) == root, type(getattr(app, "items", None)))

# every folder that holds something can be opened: it has a child row (a placeholder until it is opened)
kids = tree.get_children(root)
folders = [i for i in kids if app.nodes[i].is_dir and app.nodes[i].children]
check("the top folder shows folders with something inside", len(folders) >= 4, len(folders))
check("every such folder has an arrow to open it (a child row)", all(tree.get_children(i) for i in folders),
      [tree.item(i, "text") for i in folders if not tree.get_children(i)])
check("folders start closed", not any(tree.item(i, "open") for i in folders), [tree.item(i, "text") for i in folders if tree.item(i, "open")])
empty = next((i for i in kids if tree.item(i, "text") == "empty_folder"), None)
check("an empty folder has no arrow", empty is not None and not tree.get_children(empty), empty and tree.get_children(empty))

# opening a folder shows its real contents, largest first, and only once
code = next(i for i in kids if tree.item(i, "text") == "code")
code_node = app.nodes[code]
open_row(app, code)
shown = [tree.item(i, "text") for i in tree.get_children(code)]
check("opening a folder shows its contents, largest first", shown == [c.name for c in code_node.children], shown)
check("every row shown is in app.nodes with its Node", all(app.nodes.get(i) is c for i, c in zip(tree.get_children(code), code_node.children)))
tree.item(code, open=False)
open_row(app, code)
again = [tree.item(i, "text") for i in tree.get_children(code)]
check("closing and opening it again does not repeat rows", again == [c.name for c in code_node.children], again)

# % of Parent is the share of the row's own parent, drawn with bar()
src = find(top, "code", "src")
src_row = next(i for i in tree.get_children(code) if app.nodes[i] is src)
want = bar(src.size / code_node.size * 100)
check("% of Parent is the share of the row's parent, as bar(pct)", tree.item(src_row, "values")[0] == want,
      (tree.item(src_row, "values")[0], want))
check("the top row is 100% of itself", tree.item(root, "values")[0] == bar(100.0), tree.item(root, "values")[0])

# select_node on a file four folders down: the whole path opens, in place
deep = find(top, "code", "build", "level0", "level1")
while deep.is_dir:
    deep = deep.children[0]
rel = os.path.relpath(deep.path, FIXTURE).split(os.sep)
iid = app.select_node(deep)
pump(app, 0.2)
check("the test file is at least five levels down", len(rel) >= 5, rel)
check("select_node returns the file's row and selects it", bool(iid) and tree.selection() == (iid,) and app.nodes.get(iid) is deep,
      (iid, tree.selection()))
check("the row's ancestors are the file's real path, from the scanned folder down", chain(app, iid) == ["fixture"] + rel, chain(app, iid))
up, closed = tree.parent(iid), []
while up:
    if not tree.item(up, "open"):
        closed.append(tree.item(up, "text"))
    up = tree.parent(up)
check("every folder on the way is open", not closed, closed)
check("the file's row is scrolled into view", bool(tree.bbox(iid)), tree.bbox(iid))
check("the tree still has one row at the top", len(tree.get_children("")) == 1, [tree.item(i, "text") for i in tree.get_children("")])
check("select_node on the same file again gives the same row", app.select_node(deep) == iid)
lvl0 = tree.parent(tree.parent(iid))
check("the folders it opened hold all their contents, once", [tree.item(i, "text") for i in tree.get_children(lvl0)]
      == [c.name for c in app.nodes[lvl0].children], [tree.item(i, "text") for i in tree.get_children(lvl0)])

# a click on a treemap block does the same, also while the treemap is zoomed into a folder
music = find(top, "music")
app.zoom(music)
pump(app, 0.3)
item, node = next((i, n) for i, n in app.blocks.items())
x0, y0, x1, y1 = app.canvas.coords(item)
app.canvas.event_generate("<Button-1>", x=int((x0 + x1) / 2), y=int((y0 + y1) / 2))
pump(app, 0.2)
sel = tree.selection()
check("clicking a block selects that file's row", len(sel) == 1 and app.nodes.get(sel[0]) is node, sel)
check("with the treemap zoomed in, the row's path still starts at the scanned folder",
      bool(sel) and chain(app, sel[0]) == ["fixture"] + os.path.relpath(node.path, FIXTURE).split(os.sep), sel and chain(app, sel[0]))
check("clicking a block does not change what the treemap shows", app.view is music, app.view and app.view.name)
check("and the tree still has one row at the top", len(tree.get_children("")) == 1, len(tree.get_children("")))

# double-click on a folder row zooms the treemap into it
app.zoom_top()
check("the tree answers double-clicks", bool(tree.bind("<Double-1>")), tree.bind())
app.zoom_row(code)
pump(app, 0.2)
check("zoom_row(folder row) zooms the treemap into that folder", app.view is code_node, app.view and app.view.name)
app.zoom_row(iid)
check("zoom_row(file row) changes nothing", app.view is code_node, app.view and app.view.name)
app.zoom_top()

# a scan after a scan starts the tree again
scan(app, FIXTURE)
check("a second scan leaves one row at the top", len(tree.get_children("")) == 1, len(tree.get_children("")))
check("and app.nodes only holds rows that exist", all(tree.exists(i) for i in app.nodes), sum(1 for i in app.nodes if not tree.exists(i)))

# 50,000 files: finding a row must not search every row
scan(app, FIXTURE_BIG)
big = app.top
far = big
while far.is_dir:
    far = far.children[-1]
t = time.perf_counter()
for _ in range(20):
    fid = app.select_node(far)
secs = time.perf_counter() - t
check("select_node 20 times in a 50,000-file tree takes under half a second", secs < 0.5, f"{secs:.2f} s")
check("its path is right there too", chain(app, fid) == [big.name] + os.path.relpath(far.path, FIXTURE_BIG).split(os.sep), chain(app, fid)[:6])
check("only the opened folders were filled (under 3,000 rows for 50,000 files)", len(app.nodes) < 3000, len(app.nodes))

check("nothing raised an error", not errors, errors[:3])
app.destroy()
finish()
