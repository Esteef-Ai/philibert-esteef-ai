"""T15: wiztry/theme.py - the dark house look in one place: colors that can be read, a palette that can be told apart,
and ttk styles that use them."""
import faulthandler
import itertools
import re
import tkinter as tk
import tkinter.font
from tkinter import ttk

faulthandler.dump_traceback_later(60, exit=True)
from _t import check, finish  # noqa: E402

try:
    from wiztry import filetypes, theme
except Exception as e:                                  # noqa: BLE001
    check("wiztry.theme imports", False, e)
    finish()


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum(h):
    def c(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb(h)
    return 0.2126 * c(r) + 0.7152 * c(g) + 0.0722 * c(b)


def contrast(a, b):
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def lab(h):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(v) for v in rgb(h))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def g2(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    return 116 * g2(y) - 16, 500 * (g2(x) - g2(y)), 200 * (g2(y) - g2(z))


def apart(a, b):
    return sum((p - q) ** 2 for p, q in zip(lab(a), lab(b))) ** 0.5


NAMES = ("BG", "DEEP", "PANEL", "RAISE", "LINE", "TEXT", "DIM", "FAINT", "ACCENT", "ACCENT2", "SELECT", "SELECT_TEXT",
         "CANVAS", "FOLDER_FILL", "FOLDER_LINE", "OTHER", "GOOD", "WARN", "BAD")
missing = [n for n in NAMES if not re.fullmatch(r"#[0-9a-f]{6}", str(getattr(theme, n, "")))]
check("theme has every named color as lower-case #rrggbb", not missing, missing)
if missing:
    finish()
T = theme

# the house look (Philibert Setup and the Coma Toast shirts): dark navy, one cyan accent, pink as the rare second
check("the surface is the house navy and the accents the house cyan and pink",
      (T.BG, T.ACCENT, T.ACCENT2) == ("#0f172a", "#00e5ff", "#ff2e88"), (T.BG, T.ACCENT, T.ACCENT2))
check("every surface is dark", all(lum(c) < 0.05 for c in (T.BG, T.DEEP, T.PANEL, T.RAISE, T.CANVAS, T.FOLDER_FILL)),
      [(n, round(lum(getattr(T, n)), 3)) for n in ("BG", "DEEP", "PANEL", "RAISE", "CANVAS", "FOLDER_FILL")])
check("depth comes from shades of one hue: DEEP is darker than BG, PANEL and RAISE lighter, LINE lightest",
      lum(T.DEEP) < lum(T.BG) < lum(T.PANEL) < lum(T.RAISE) < lum(T.LINE),
      [round(lum(c), 4) for c in (T.DEEP, T.BG, T.PANEL, T.RAISE, T.LINE)])
low = {f"{a} on {b}": round(contrast(getattr(T, a), getattr(T, b)), 2)
       for a, b, need in (("TEXT", "PANEL", 7), ("TEXT", "BG", 7), ("TEXT", "RAISE", 7), ("TEXT", "DEEP", 7), ("DIM", "PANEL", 4.5),
                          ("DIM", "DEEP", 4.5), ("FAINT", "PANEL", 3), ("ACCENT", "BG", 4.5), ("ACCENT", "DEEP", 4.5),
                          ("SELECT_TEXT", "SELECT", 7), ("FOLDER_LINE", "CANVAS", 3), ("OTHER", "CANVAS", 2))
       if contrast(getattr(T, a), getattr(T, b)) < need}
check("text can be read on every surface it sits on (contrast: 7 for text, 4.5 for dim text and accents)", not low, low)
check("a selected row stands out from the list", contrast(T.SELECT, T.PANEL) >= 1.5 and T.SELECT != T.PANEL, round(contrast(T.SELECT, T.PANEL), 2))

# the file-type palette
P = list(getattr(T, "PALETTE", []))
check("PALETTE has 20 colors, all different, all lower-case #rrggbb", len(P) == 20 and len(set(P)) == 20
      and all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in P), len(P))
if len(P) == 20:
    dull = [c for c in P if contrast(c, T.CANVAS) < 3]
    check("every palette color shows on the treemap's background (contrast at least 3)", not dull, dull)
    close = sorted((round(apart(a, b), 1), a, b) for a, b in itertools.combinations(P, 2))[:3]
    check("no two palette colors look alike (Lab distance at least 15)", close[0][0] >= 15, close)
    near = [c for c in P if apart(c, T.OTHER) < 15 or apart(c, T.FOLDER_FILL) < 15]
    check("OTHER and the folder fill are not mistaken for a palette color", not near, near)
    check("the accents are kept for the window, not spent on file types", T.ACCENT not in P and T.ACCENT2 not in P)
check("filetypes uses the theme's palette", list(filetypes.PALETTE) == P and filetypes.OTHER == T.OTHER, (filetypes.PALETTE[:2], filetypes.OTHER))
rows = filetypes.ext_rows({f".e{i:02d}": {"size": 1000 - i, "files": 1} for i in range(25)})
check("the 20 largest types get the palette in order, the rest OTHER", [r["color"] for r in rows] == P + [T.OTHER] * 5,
      [r["color"] for r in rows][:3])

# fonts: three roles, each a family this computer has
root = tk.Tk()
root.withdraw()
fams = {f.lower() for f in tkinter.font.families(root)}
fonts = [getattr(T, n, None) for n in ("FONT_UI", "FONT_BRAND", "FONT_MONO")]
check("FONT_UI, FONT_BRAND and FONT_MONO are (family, size, ...) tuples", all(isinstance(f, tuple) and len(f) >= 2 and isinstance(f[1], int) for f in fonts), fonts)
if all(isinstance(f, tuple) and len(f) >= 2 for f in fonts):
    check("each font family is installed here", all(str(f[0]).lower() in fams for f in fonts), [f[0] for f in fonts])
    check("the brand font is bold and the data font is a fixed-width one", "bold" in fonts[1] and tkinter.font.Font(root=root, font=fonts[2]).metrics("fixed") == 1,
          (fonts[1], fonts[2]))

# apply(root): the ttk styles
theme.apply(root)
st = ttk.Style(root)


def look(style, opt):
    return str(st.lookup(style, opt)).lower()


check("apply() uses the clam ttk theme (the Windows themes ignore colors)", st.theme_use() == "clam", st.theme_use())
check("the window itself is BG", str(root.cget("bg")).lower() == T.BG, root.cget("bg"))
want = {("TFrame", "background"): T.BG, ("TLabel", "background"): T.BG, ("TLabel", "foreground"): T.TEXT,
        ("TButton", "background"): T.RAISE, ("TButton", "foreground"): T.TEXT,
        ("TEntry", "fieldbackground"): T.DEEP, ("TEntry", "foreground"): T.TEXT,
        ("Treeview", "background"): T.PANEL, ("Treeview", "fieldbackground"): T.PANEL, ("Treeview", "foreground"): T.TEXT,
        ("Treeview.Heading", "background"): T.RAISE, ("Treeview.Heading", "foreground"): T.DIM,
        ("TPanedwindow", "background"): T.LINE, ("Vertical.TScrollbar", "troughcolor"): T.DEEP,
        ("Vertical.TScrollbar", "background"): T.RAISE,
        ("Bar.TFrame", "background"): T.DEEP, ("Bar.TLabel", "background"): T.DEEP, ("Bar.TLabel", "foreground"): T.DIM,
        ("Brand.TLabel", "background"): T.DEEP, ("Brand.TLabel", "foreground"): T.ACCENT,
        ("Title.TLabel", "background"): T.BG, ("Title.TLabel", "foreground"): T.FAINT}
wrong = {f"{s} {o}": look(s, o) for (s, o), v in want.items() if look(s, o) != v}
check("the ttk styles carry the theme's colors", not wrong, wrong)
sel = dict((tuple(k[:-1]) if len(k) > 2 else k[0], k[-1]) for k in st.map("Treeview", "background"))
check("a selected row is SELECT with SELECT_TEXT", str(sel.get("selected", "")).lower() == T.SELECT
      and any(str(v).lower() == T.SELECT_TEXT for *_s, v in st.map("Treeview", "foreground")), (st.map("Treeview", "background"), st.map("Treeview", "foreground")))
hot = [str(v).lower() for *_s, v in st.map("TButton", "background")]
check("a button changes when the pointer is on it and when it is disabled", len(st.map("TButton", "background")) >= 1
      and any("disabled" in s for s in map(str, st.map("TButton", "foreground"))), (st.map("TButton", "background"), st.map("TButton", "foreground")))
check("rows are tall enough to read (24 px or more)", int(st.lookup("Treeview", "rowheight") or 0) >= 24, st.lookup("Treeview", "rowheight"))
check("dark_title_bar(root) answers True or False and raises nothing", theme.dark_title_bar(root) in (True, False))
check("apply() twice is harmless", theme.apply(root) is None and look("Treeview", "background") == T.PANEL)
root.destroy()
finish()
