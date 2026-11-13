"""T17: a calmer file-type palette (no neon, no pastel) and the Esteef.Ai brand names, in wiztry/theme.py."""
import faulthandler
import itertools
import re
import tkinter as tk
from tkinter import ttk

faulthandler.dump_traceback_later(60, exit=True)
from _t import check, finish  # noqa: E402

try:
    from wiztry import filetypes, theme as T
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


def strength(h):                                        # how vivid a color is (Lab chroma): neon is 60 and up
    _l, a, b = lab(h)
    return (a * a + b * b) ** 0.5


OLD_BRIGHT = {"#38bdf8", "#f472b6", "#a3e635", "#fbbf24", "#a78bfa", "#34d399", "#fb923c", "#3b82f6", "#f87171", "#2dd4bf",
              "#e879f9", "#c2410c", "#94a3b8", "#16a34a", "#fda4af", "#0e7490", "#be185d", "#d4a373", "#7c3aed", "#fef08a"}
P = list(getattr(T, "PALETTE", []))
check("PALETTE has 20 colors, all different, lower-case #rrggbb", len(P) == 20 and len(set(P)) == 20
      and all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in P), P[:3])
if len(P) != 20 or not all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in P):
    finish()
check("none of the old bright colors is left", not (set(P) & OLD_BRIGHT), sorted(set(P) & OLD_BRIGHT))
neon = [(c, round(strength(c))) for c in P if strength(c) > 55]
check("no color is neon (Lab chroma at most 55)", not neon, neon)
pale = [(c, round(lab(c)[0])) for c in P if lab(c)[0] > 75]
check("no color is pastel (Lab lightness at most 75)", not pale, pale)
murky = [(c, round(lab(c)[0])) for c in P if lab(c)[0] < 38]
check("no color is too dark to see (Lab lightness at least 38)", not murky, murky)
dull = [(c, round(contrast(c, T.CANVAS), 2)) for c in P if contrast(c, T.CANVAS) < 3]
check("every color shows on the treemap's background (contrast at least 3)", not dull, dull)
close = sorted((round(apart(a, b), 1), a, b) for a, b in itertools.combinations(P, 2))[:3]
check("no two colors look alike (Lab distance at least 15)", close[0][0] >= 15, close)
near = [c for c in P if apart(c, T.OTHER) < 15 or apart(c, T.FOLDER_FILL) < 15]
check("OTHER and the folder fill are not mistaken for a palette color", not near, near)
check("OTHER still shows on the treemap's background (contrast at least 2)", contrast(T.OTHER, T.CANVAS) >= 2, round(contrast(T.OTHER, T.CANVAS), 2))
check("OTHER is a quiet gray-blue, not a color of its own (chroma at most 20)", strength(T.OTHER) <= 20, round(strength(T.OTHER)))
check("the accents stay out of the palette", T.ACCENT not in P and T.ACCENT2 not in P)
check("the first color, used for the largest file type, is a blue", rgb(P[0])[2] > rgb(P[0])[0] and rgb(P[0])[2] > rgb(P[0])[1], P[0])
check("filetypes still takes its colors from the theme", list(filetypes.PALETTE) == P and filetypes.OTHER == T.OTHER)

# the brand
check("the app and brand names", (getattr(T, "APP_NAME", None), getattr(T, "BRAND", None)) == ("WizTry", "Esteef.Ai"),
      (getattr(T, "APP_NAME", None), getattr(T, "BRAND", None)))
check("the window title is 'WizTry - Esteef.Ai'", getattr(T, "TITLE", None) == "WizTry - Esteef.Ai", getattr(T, "TITLE", None))
check("the byline is 'by Esteef.Ai'", getattr(T, "BYLINE", None) == "by Esteef.Ai", getattr(T, "BYLINE", None))
root = tk.Tk()
root.withdraw()
T.apply(root)
st = ttk.Style(root)
got = (str(st.lookup("By.TLabel", "background")).lower(), str(st.lookup("By.TLabel", "foreground")).lower())
check("the By.TLabel style is DIM text on the bar", got == (T.DEEP, T.DIM), got)
check("the older styles are still there", str(st.lookup("Brand.TLabel", "foreground")).lower() == T.ACCENT
      and str(st.lookup("Treeview", "background")).lower() == T.PANEL)
root.destroy()
finish()
