"""wiztry/theme.py - colors, fonts and styles in one place."""

import ctypes
import tkinter as tk
from tkinter import ttk

# ── colors ────────────────────────────────────────────────────────────────
DEEP: str = "#0a1120"
BG: str = "#0f172a"
PANEL: str = "#111d36"
RAISE: str = "#162544"
LINE: str = "#1e3054"

TEXT: str = "#d7e3f4"
DIM: str = "#8ea3c4"
FAINT: str = "#6f86a8"

ACCENT: str = "#00e5ff"
ACCENT2: str = "#ff2e88"
SELECT: str = "#0d4f68"
SELECT_TEXT: str = "#ffffff"

GOOD: str = "#22c55e"
WARN: str = "#facc15"
BAD: str = "#ff5c5c"

CANVAS: str = DEEP
FOLDER_FILL: str = RAISE
FOLDER_LINE: str = "#707070"
OTHER: str = "#4b5a78"

PALETTE: list[str] = [
    "#38bdf8", "#f472b6", "#a3e635", "#fbbf24", "#a78bfa",
    "#34d399", "#fb923c", "#3b82f6", "#f87171", "#2dd4bf",
    "#e879f9", "#c2410c", "#94a3b8", "#16a34a", "#fda4af",
    "#0e7490", "#be185d", "#d4a373", "#7c3aed", "#fef08a",
]

# ── fonts ─────────────────────────────────────────────────────────────────
FONT_UI: tuple = ("Segoe UI", 10)
FONT_BRAND: tuple = ("Segoe UI", 12, "bold")
FONT_MONO: tuple = ("Consolas", 10)


def apply(root: tk.Tk) -> None:
    """Apply the theme's colors and fonts to root (safe to call twice)."""
    st = ttk.Style(root)
    st.theme_use("clam")
    root.configure(bg=BG)
    root.option_add("*Font", FONT_UI)

    # base widget
    st.configure(".", background=BG, foreground=TEXT,
                 fieldbackground=DEEP, bordercolor=LINE,
                 darkcolor=BG, lightcolor=BG, troughcolor=DEEP,
                 focuscolor=ACCENT, font=FONT_UI)
    st.map(".", background=[("disabled", BG), ("pressed", SELECT), ("active", LINE)],
           focuscolor=[("focus", ACCENT)])

    # frames / labels
    st.configure("TFrame", background=BG)
    st.configure("TLabel", background=BG, foreground=TEXT)

    st.configure("Bar.TFrame", background=DEEP)
    st.configure("Bar.TLabel", background=DEEP, foreground=DIM)
    st.configure("Brand.TLabel", background=DEEP, foreground=ACCENT, font=FONT_BRAND)
    st.configure("Title.TLabel", background=BG, foreground=FAINT, font=("Segoe UI", 8, "bold"))

    # buttons
    st.configure("TButton", background=RAISE, foreground=TEXT,
                 bordercolor=LINE, darkcolor=RAISE, lightcolor=RAISE,
                 padding=(12, 4), relief="flat")
    st.map("TButton",
           background=[("disabled", BG), ("pressed", SELECT), ("active", LINE)],
           foreground=[("disabled", FAINT)],
           bordercolor=[("focus", ACCENT), ("active", ACCENT)])

    # entries
    st.configure("TEntry", fieldbackground=DEEP, foreground=TEXT,
                 insertcolor=ACCENT, bordercolor=LINE,
                 darkcolor=DEEP, lightcolor=DEEP, padding=4)
    st.map("TEntry", bordercolor=[("focus", ACCENT)])

    # treeviews
    st.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                 foreground=TEXT, bordercolor=LINE, borderwidth=0,
                 rowheight=24, font=FONT_UI)
    st.map("Treeview",
           background=[("selected", SELECT)],
           foreground=[("selected", SELECT_TEXT)])

    st.configure("Treeview.Heading", background=RAISE, foreground=DIM,
                 bordercolor=LINE, darkcolor=RAISE, lightcolor=RAISE,
                 relief="flat", padding=(8, 4),
                 font=("Segoe UI", 9, "bold"))
    st.map("Treeview.Heading",
           background=[("active", LINE)],
           foreground=[("active", TEXT)])

    # paned window
    st.configure("TPanedwindow", background=LINE)

    # sash
    st.configure("Sash", sashthickness=5)

    # scrollbars
    for name in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        st.configure(name, troughcolor=DEEP, background=RAISE,
                     bordercolor=DEEP, darkcolor=RAISE, lightcolor=RAISE,
                     arrowcolor=DIM, relief="flat")
        st.map(name,
               background=[("active", LINE)],
               arrowcolor=[("active", ACCENT)])


def dark_title_bar(root: tk.Tk) -> bool:
    """Ask Windows for a dark title bar and return whether it accepted."""
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        on = ctypes.c_int(1)
        return ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20,
                                                          ctypes.byref(on),
                                                          ctypes.sizeof(on)) == 0
    except Exception:
        return False
