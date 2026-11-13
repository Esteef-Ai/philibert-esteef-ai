"""T16: the window wears the theme: dark everywhere, a toolbar and a status bar, titled panes, an empty state,
a working tooltip. What cannot be judged here (whether it looks good) is for a person to say."""
import faulthandler
import time
from tkinter import ttk

faulthandler.dump_traceback_later(90, exit=True)
from _t import FIXTURE, check, finish  # noqa: E402

try:
    from wiztry import theme as T
    from wiztry.app import App
except Exception as e:                                  # noqa: BLE001
    check("wiztry.app and wiztry.theme import", False, e)
    finish()


def pump(app, secs):
    end = time.time() + secs
    while time.time() < end:
        app.update()
        time.sleep(0.01)


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


errors = []
app = App(FIXTURE)
app.report_callback_exception = lambda exc, val, tb: errors.append(repr(val))
app.geometry("1200x800+-4000+-4000")                    # a real, mapped window, kept off the desktop
pump(app, 0.8)
st = ttk.Style(app)


def lum(color):
    def c(v):
        v /= 65535
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = app.winfo_rgb(color)
    return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b)


def style_of(w):
    s = str(w.cget("style"))
    if s:
        return s
    cls = w.winfo_class()
    return (str(w.cget("orient")).capitalize() + ".TScrollbar") if cls == "TScrollbar" else cls


def surface(w):
    """The color a widget paints itself with."""
    cls = w.winfo_class()
    if cls.startswith("T") and cls != "Toplevel" and cls != "Tk":
        return str(st.lookup(style_of(w), "fieldbackground" if cls in ("TEntry", "Treeview") else "background"))
    return str(w.cget("bg"))


def light_ones():
    out = []
    for w in walk(app):
        try:
            col = surface(w)
            if not col or lum(col) >= 0.2:
                out.append((w.winfo_class(), col))
        except Exception as e:                          # noqa: BLE001
            out.append((w.winfo_class(), repr(e)[:60]))
    return out


def labels(text):
    return [w for w in walk(app) if w.winfo_class() in ("TLabel", "Label") and str(w.cget("text")) == text]


def canvas_texts():
    c = app.canvas
    return [(str(c.itemcget(i, "text")), str(c.itemcget(i, "fill")).lower(), c.coords(i)) for i in c.find_all() if c.type(i) == "text"]


# 1. dark everywhere, before anything is scanned
check("the window uses the theme (clam, BG)", st.theme_use() == "clam" and str(app.cget("bg")).lower() == T.BG, (st.theme_use(), app.cget("bg")))
check("no widget has a light background", not light_ones(), light_ones()[:6])
check("the treemap's background is CANVAS", str(app.canvas.cget("bg")).lower() == T.CANVAS, app.canvas.cget("bg"))
m = app.menu
check("the right-click menu is dark too", (str(m.cget("bg")).lower(), str(m.cget("fg")).lower(), str(m.cget("activebackground")).lower(),
                                           str(m.cget("activeforeground")).lower()) == (T.RAISE, T.TEXT, T.SELECT, T.SELECT_TEXT),
      (m.cget("bg"), m.cget("fg"), m.cget("activebackground"), m.cget("activeforeground")))

# 2. the toolbar: brand at the left, then the path box and the buttons
brand = labels("WIZTRY")
check("the toolbar shows the name WIZTRY once, in the Brand style", len(brand) == 1 and str(brand[0].cget("style")) == "Brand.TLabel",
      [str(b.cget("style")) for b in brand])
if brand:
    b = brand[0]
    check("the name is at the left of the toolbar, level with Scan", b.winfo_rootx() < app.scan_btn.winfo_rootx()
          and abs((b.winfo_rooty() + b.winfo_height() / 2) - (app.scan_btn.winfo_rooty() + app.scan_btn.winfo_height() / 2)) <= 12,
          (b.winfo_rootx(), b.winfo_rooty(), app.scan_btn.winfo_rootx(), app.scan_btn.winfo_rooty()))
    check("the toolbar is a Bar (DEEP) across the whole window", str(b.master.cget("style")) == "Bar.TFrame"
          and b.master.winfo_width() >= app.winfo_width() - 4, (str(b.master.cget("style")), b.master.winfo_width(), app.winfo_width()))
check("the toolbar is above the lists", app.scan_btn.winfo_rooty() + app.scan_btn.winfo_height() <= app.tree.winfo_rooty(),
      (app.scan_btn.winfo_rooty(), app.tree.winfo_rooty()))

# 3. the status bar: at the bottom, across the window
stat = [w for w in walk(app) if w.winfo_class() in ("TLabel", "Label") and str(w.cget("textvariable")) == str(app.status)]
check("the status line is one label in the Bar style", len(stat) == 1 and str(stat[0].cget("style")) == "Bar.TLabel", len(stat))
check("before a scan it says Ready", app.status.get() == "Ready", app.status.get())
if stat:
    s = stat[0]
    check("the status bar is below the treemap", s.winfo_rooty() >= app.canvas.winfo_rooty() + app.canvas.winfo_height() - 2,
          (s.winfo_rooty(), app.canvas.winfo_rooty() + app.canvas.winfo_height()))
    check("the status bar is a Bar across the whole window", str(s.master.cget("style")) == "Bar.TFrame"
          and s.master.winfo_width() >= app.winfo_width() - 4, (str(s.master.cget("style")), s.master.winfo_width()))
    check("the status bar ends at the bottom of the window", abs((s.master.winfo_rooty() + s.master.winfo_height())
                                                                  - (app.winfo_rooty() + app.winfo_height())) <= 2,
          (s.master.winfo_rooty() + s.master.winfo_height(), app.winfo_rooty() + app.winfo_height()))

# 4. each pane has a small title above it
for text, below in (("TREE VIEW", app.tree), ("FILE TYPES", app.types), ("TREEMAP", app.canvas)):
    found = labels(text)
    ok = len(found) == 1 and str(found[0].cget("style")) == "Title.TLabel"
    check(f"the pane title {text} is there once, in the Title style", ok, [str(f.cget("style")) for f in found])
    if found:
        t = found[0]
        check(f"{text} sits above its pane, at its left edge", t.winfo_rooty() + t.winfo_height() <= below.winfo_rooty() + 1
              and abs(t.winfo_rootx() - below.winfo_rootx()) <= 16, (t.winfo_rootx(), t.winfo_rooty(), below.winfo_rootx(), below.winfo_rooty()))

# 5. numbers line up on the right
anchors = {c: str(app.tree.column(c, "anchor")) for c in ("size", "items", "files", "folders")}
anchors.update({"types." + c: str(app.types.column(c, "anchor")) for c in ("size", "pct", "files")})
check("number columns are right-aligned in both lists", set(anchors.values()) == {"e"}, anchors)
check("names and the % of Parent bar stay left-aligned", str(app.tree.column("#0", "anchor")) == "w" and str(app.tree.column("pct", "anchor")) == "w",
      (str(app.tree.column("#0", "anchor")), str(app.tree.column("pct", "anchor"))))

# 6. the empty state: the treemap says what to do
texts = canvas_texts()
check("before a scan the treemap shows one hint in DIM text", len(texts) == 1 and texts[0][1] == T.DIM, texts)
check("the hint says to pick a folder and press Scan", bool(texts) and "folder" in texts[0][0].lower() and "Scan" in texts[0][0], [t[0] for t in texts])
if texts:
    x, y = texts[0][2][:2]
    w, h = app.canvas.winfo_width(), app.canvas.winfo_height()
    check("the hint is in the middle of the treemap", 0.4 * w <= x <= 0.6 * w and 0.3 * h <= y <= 0.7 * h, (x, y, w, h))

# 7. the loading state, then the result
app.start_scan(FIXTURE)
texts = canvas_texts()
check("while scanning the treemap says Scanning...", len(texts) == 1 and texts[0][0].startswith("Scanning"), [t[0] for t in texts])
end = time.time() + 30
while app.busy and time.time() < end:
    app.update()
    time.sleep(0.02)
pump(app, 0.4)
check("after the scan the hint is gone", not canvas_texts(), [t[0] for t in canvas_texts()])
c = app.canvas
rect = [i for i in c.find_all() if c.type(i) == "rectangle"]
fills = {str(c.itemcget(i, "fill")).lower() for i in rect}
check("folders are filled with FOLDER_FILL, not the old light gray", T.FOLDER_FILL in fills and "#c8c8c8" not in fills, sorted(fills)[:8])
ok_fills = {p.lower() for p in T.PALETTE} | {T.OTHER}
odd = {str(c.itemcget(i, "fill")).lower() for i in app.blocks} - ok_fills
check("every file block is a palette color", bool(app.blocks) and not odd, sorted(odd)[:5])
lines = {str(c.itemcget(i, "outline")).lower() for i in rect if str(c.itemcget(i, "fill")) == ""}
check("folder outlines are FOLDER_LINE", lines == {T.FOLDER_LINE}, lines)
first = getattr(app, "swatches", [None])[0]
want = tuple(int(T.PALETTE[0][i:i + 2], 16) for i in (1, 3, 5))
check("the largest file type's swatch is the first palette color", first is not None and tuple(first.get(1, 1)) == want,
      first is not None and first.get(1, 1))

# 8. the tooltip appears (it never did: the old code returned before making it)
item, node = next(iter(app.blocks.items()))
x0, y0, x1, y1 = c.coords(item)
c.event_generate("<Motion>", x=int((x0 + x1) / 2), y=int((y0 + y1) / 2))
pump(app, 0.3)
tips = [w for w in walk(app) if w.winfo_class() in ("Label", "TLabel") and node.path in str(w.cget("text")) and w.winfo_ismapped()]
check("moving over a block shows a tooltip with the file's path", len(tips) == 1, len(tips))
if tips and tips[0].winfo_class() == "Label":
    check("the tooltip is RAISE with TEXT", (str(tips[0].cget("bg")).lower(), str(tips[0].cget("fg")).lower()) == (T.RAISE, T.TEXT),
          (tips[0].cget("bg"), tips[0].cget("fg")))
c.event_generate("<Leave>")
pump(app, 0.2)
left = [w for w in walk(app) if w.winfo_class() in ("Label", "TLabel") and node.path in str(w.cget("text")) and w.winfo_ismapped()]
check("the tooltip goes away when the pointer leaves the treemap", not left, len(left))

check("still no widget with a light background", not light_ones(), light_ones()[:6])
check("nothing raised an error", not errors, errors[:3])
app.destroy()
finish()
