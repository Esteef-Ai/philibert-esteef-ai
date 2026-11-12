"""T05: the window scans in the background and fills the tree, file types and treemap."""
import os
import time

from _t import EXPECTED, FIXTURE, FIXTURE_BIG, check, finish, listing

try:
    from wiztry.app import App, bar, shade
    from wiztry.scanner import scan
except Exception as e:                                  # noqa: BLE001
    check("wiztry.app imports", False, e)
    finish()

check("bar(50)", bar(50) == "█" * 5 + "░" * 5 + "  50.0%", bar(50))
check("bar(100) and bar(0)", bar(100).startswith("█" * 10) and bar(0).startswith("░" * 10), (bar(100), bar(0)))
check("shade lighter and darker", shade("#808080", 0.5) == "#404040" and shade("#808080", 1.5) == "#bfbfbf",
      (shade("#808080", 0.5), shade("#808080", 1.5)))

before = listing(FIXTURE)
app = App(FIXTURE)
app.withdraw()                                          # tested without showing a window
check("the path box starts with the folder given", app.path_var.get() == FIXTURE, app.path_var.get())
app.start_scan(FIXTURE)
check("scanning runs in the background", app.busy)
end = time.time() + 30
while app.busy and time.time() < end:
    app.update()
    time.sleep(0.02)
check("the scan finishes", not app.busy)
check("the status line reports files and time", "91 files" in app.status.get() and " s" in app.status.get(), app.status.get())

roots = app.tree.get_children("")
check("the tree has the scanned folder at the top", len(roots) == 1 and app.tree.item(roots[0], "text") == "fixture",
      [app.tree.item(i, "text") for i in roots])
kids = app.tree.get_children(roots[0]) if roots else ()
check("the top folder is open with its contents, largest first",
      [app.tree.item(i, "text") for i in kids] == [t["name"] for t in EXPECTED["top_level"]],
      [app.tree.item(i, "text") for i in kids])
vals = app.tree.item(roots[0], "values") if roots else ()
check("columns: % of parent, size, items, files, folders, modified",
      len(vals) == 6 and "100.0%" in str(vals[0]) and str(vals[1]) == "44.2 MB" and str(vals[3]) == "91", vals)
check("columns are named like WizTree's", [app.tree.heading(c)["text"] for c in ("#0",) + tuple(app.tree["columns"])]
      == ["Name", "% of Parent", "Size", "Items", "Files", "Folders", "Modified"])

types = app.types.get_children("")
check("one file-type row per extension", len(types) == len(EXPECTED["by_ext"]), len(types))
check("the largest type first", types and app.types.item(types[0], "text").strip() == ".cr2",
      types and app.types.item(types[0], "text"))

check("the treemap has a block per visible file (800x300 when hidden)", len(app.blocks) >= 40, len(app.blocks))
check("draw_treemap() exists and redraws", callable(getattr(app, "draw_treemap", None)))
outlines = [i for i in app.canvas.find_all() if app.canvas.type(i) == "rectangle"
            and app.canvas.itemcget(i, "fill") == "" and app.canvas.itemcget(i, "outline").lower() == "#707070"]
check("folders are drawn as #707070 outlines (the nesting shows)", len(outlines) >= 5, len(outlines))
def _box(i):
    return app.canvas.coords(i)
_fold = {}
for i in outlines:
    x0_, y0_, x1_, y1_ = _box(i)
    _fold.setdefault("all", []).append((x0_, y0_, x1_, y1_))
_inside = 0
for i, n in list(app.blocks.items())[:60]:
    if n.parent is app.view:
        continue
    bx0, by0, bx1, by1 = _box(i)
    if any(fx0 - 0.5 <= bx0 and fy0 - 0.5 <= by0 and bx1 <= fx1 + 0.5 and by1 <= fy1 + 0.5
           for fx0, fy0, fx1, fy1 in _fold.get("all", [])):
        _inside += 1
check("files inside folders sit inside a folder outline", _inside >= 10, _inside)
item, node = next(iter(app.blocks.items()))
x0, y0, x1, y1 = app.canvas.coords(item)
cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
check("node_at finds the block under a point", app.node_at(cx, cy) is node)
tip = app.tooltip_text_at(cx, cy)
check("the tooltip shows the full path and size", node.path in tip and ("MB" in tip or "KB" in tip or "bytes" in tip), tip)
check("no tooltip over empty space", app.tooltip_text_at(-50, -50) == "")
check("a block's color is its extension's", app.canvas.itemcget(item, "fill") == app.colors.get(os.path.splitext(node.name)[1].lower(), ""))

deep = next(n for n in app.blocks.values() if n.parent is not None and n.parent.parent is not None)
iid = app.select_node(deep)
check("select_node opens the folders and selects the file", app.tree.selection() == (iid,)
      and app.tree.item(iid, "text") == deep.name, app.tree.selection())
music = next(n for n in app.top.children if n.name == "music")
app.zoom(music)
check("zoom shows only that folder", app.blocks and all(n.path.startswith(music.path) for n in app.blocks.values()))
app.zoom_top()
check("Top goes back to the whole scan", app.view is app.top and len(app.blocks) >= 40)

# -- found in review: the cushion was hidden under the fill, small files left white holes, and a
#    single click on a file row made the view a file (the next resize then drew nothing)
c = app.canvas
order = {i: k for k, i in enumerate(c.find_all())}


def _cushion_on_top(item, node):
    x0, y0, x1, y1 = c.coords(item)
    light = shade(app.colors.get(os.path.splitext(node.name)[1].lower(), ""), 1.45)
    return any(c.type(i) == "line" and c.itemcget(i, "fill") == light and order[i] > order[item]
               for i in c.find_overlapping(x0 + 1, y0, x1 - 1, y0 + 0.5))


_big = [(i, n) for i, n in app.blocks.items() if (lambda b: b[2] - b[0] > 6 and b[3] - b[1] > 6)(c.coords(i))]
_shown = sum(_cushion_on_top(i, n) for i, n in _big)
check("the cushion's light edge is drawn on top of the fill (it shows)", _big and _shown == len(_big),
      f"{_shown} of {len(_big)} blocks")


def _coverage():
    W, H = (c.winfo_width(), c.winfo_height()) if c.winfo_width() >= 10 else (800, 300)
    pts = [(W * (i + 0.5) / 60, H * (j + 0.5) / 30) for i in range(60) for j in range(30)]
    hit = sum(any(c.type(k) == "rectangle" and c.itemcget(k, "fill") not in ("", "white", "#ffffff")
                  for k in c.find_overlapping(x, y, x, y)) for x, y in pts)
    return hit / len(pts)


cov = _coverage()
check("no white holes: filled blocks cover the canvas", cov >= 0.97, f"{cov:.0%} covered")


def _hidden_blocks():
    """File blocks whose centre is covered by another filled rectangle drawn later (e.g. a folder's gray)."""
    bad = []
    for item, node in app.blocks.items():
        x0, y0, x1, y1 = c.coords(item)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        top_fill = [k for k in c.find_overlapping(cx, cy, cx, cy)
                    if c.type(k) == "rectangle" and c.itemcget(k, "fill") not in ("",)]
        if top_fill and top_fill[-1] != item:
            bad.append(node.name)
    return bad


_hid = _hidden_blocks()
check("file blocks are visible: no folder fill is drawn over them", not _hid, f"{len(_hid)} hidden, e.g. {_hid[:4]}")
big_top, _ = scan(FIXTURE_BIG)
app.zoom(big_top)
app.update()
cov = _coverage()
check("no white holes with 50,000 files either", cov >= 0.97, f"{cov:.0%} covered")
check("50,000 files stay within the 20,000-block cap", 0 < len(app.blocks) <= 20000, len(app.blocks))
app.zoom_top()
_f = next(n for n in app.blocks.values() if n.parent is not None and n.parent.parent is not None)
app.tree.focus(app.select_node(_f))
for _seq in ("<Button-1>", "<ButtonRelease-1>", "<<TreeviewSelect>>"):
    app.tree.event_generate(_seq, x=5, y=5)
app.update()
check("clicking a file row keeps the treemap's view on a folder", app.view is not None and app.view.is_dir,
      app.view and app.view.name)
check("nothing on disk changed", listing(FIXTURE) == before)
app.destroy()
finish()
