"""Headless click-test for a Tkinter app. Run by NeuralDock, not by hand.

    python nd_gui_smoke.py <script.py> [test_input_file]

Builds the app with every window withdrawn, presses every button, and prints
what happened as one JSON line prefixed ND_GUI_REPORT:.

WHY THIS EXISTS. Measured 2026-09-21/22: the user asked six times for the
buttons in a Tk app to be fixed, pasting the traceback each time. ND's only test
was run_script, which starts the mainloop and waits until the 60s timeout kills
it -- "Exit -1, timed out", six times. An idle GUI waiting for a click looks
exactly like a GUI that works, and the model had no way to press a button.

Two faithfulness rules, both deliberate:

  1. tkinter.filedialog / messagebox / simpledialog are imported here only to
     stub them, then REMOVED from the tkinter namespace again. The bug that
     started this was `import tkinter as tk` then `tk.filedialog.askopenfilename`
     -- filedialog is a submodule and is only an attribute of tkinter once
     something imports it. Leaving it imported here would mask that exact bug.

  2. Dialogs return a real input (the user's test file) or a path in a temp
     folder, so a button that saves writes nowhere that matters.

It also flags the quieter half of "I click and nothing happens": a button wired
to a handler whose body is only `pass`. That raises nothing, so no exception-
based test would ever catch it.
"""
import ast
import inspect
import json
import os
import runpy
import sys
import tempfile
import textwrap
import traceback

target = os.path.abspath(sys.argv[1])
test_input = sys.argv[2] if len(sys.argv) > 2 else ""
report = {"target": target, "windows": 0, "buttons": [], "startup_error": "",
          "dialogs": []}

import tkinter
_before = set(vars(tkinter))
import tkinter.filedialog as _fd
import tkinter.messagebox as _mb
import tkinter.simpledialog as _sd
from tkinter import ttk

TMP = tempfile.mkdtemp(prefix="nd_gui_")
_current = [""]
_errors = []


def _note(kind, *a):
    report["dialogs"].append((kind + " " + " | ".join(str(x) for x in a if x)).strip()[:160])


def _open(*a, **k):
    _note("askopenfilename")
    return test_input


def _opens(*a, **k):
    _note("askopenfilenames")
    return (test_input,) if test_input else ()


def _save(*a, **k):
    _note("asksaveasfilename")
    return os.path.join(TMP, "output" + (k.get("defaultextension") or ".sav"))


_fd.askopenfilename = _open
_fd.askopenfilenames = _opens
_fd.asksaveasfilename = _save
_fd.askdirectory = lambda *a, **k: (_note("askdirectory"), TMP)[1]
for _n in ("showinfo", "showwarning", "showerror"):
    setattr(_mb, _n, (lambda n: lambda *a, **k: (_note(n, *a), "ok")[1])(_n))
for _n in ("askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel"):
    setattr(_mb, _n, (lambda n: lambda *a, **k: (_note(n, *a), True)[1])(_n))
for _n in ("askstring", "askinteger", "askfloat"):
    setattr(_sd, _n, (lambda n: lambda *a, **k: (_note(n, *a), None)[1])(_n))

# Rule 1: put the namespace back exactly as a fresh `import tkinter` leaves it.
_hidden = {}
for _k in set(vars(tkinter)) - _before:
    try:
        _hidden[_k] = getattr(tkinter, _k)
        delattr(tkinter, _k)
    except Exception:
        pass

# ...and then behave like real Python when the APP imports one. In a fresh
# interpreter, `from tkinter import filedialog` (or `import tkinter.filedialog`)
# loads the submodule and makes it an attribute of tkinter, so a later
# `tk.filedialog.askopenfilename` works. Because we loaded it first, the app's
# import would find it in sys.modules and skip that step -- and the harness
# would report a failure the real app does not have. Measured: exactly that,
# six false "no attribute 'filedialog'" failures after a correct fix.
import builtins as _bi
_real_import = _bi.__import__


def _import(name, globals=None, locals=None, fromlist=(), level=0):
    mod = _real_import(name, globals, locals, fromlist, level)
    try:
        if level == 0:
            if name.startswith("tkinter."):
                sub = name.split(".")[1]
                if sub in _hidden:
                    setattr(tkinter, sub, _hidden[sub])
            elif name == "tkinter" and fromlist:
                for sub in fromlist:
                    if sub in _hidden:
                        setattr(tkinter, sub, _hidden[sub])
    except Exception:
        pass
    return mod


_bi.__import__ = _import

# Keep every window hidden, never block, and route callback errors to us.
_roots = []
_orig_tk_init = tkinter.Tk.__init__
_orig_top_init = tkinter.Toplevel.__init__


def _tk_init(self, *a, **k):
    _orig_tk_init(self, *a, **k)
    self.withdraw()
    _roots.append(self)


def _top_init(self, *a, **k):
    _orig_top_init(self, *a, **k)
    try:
        self.withdraw()
    except Exception:
        pass


def _callback_error(self, exc, val, tb):
    _errors.append((_current[0], "".join(traceback.format_exception(exc, val, tb))))


tkinter.Tk.__init__ = _tk_init
tkinter.Toplevel.__init__ = _top_init
tkinter.Tk.report_callback_exception = _callback_error
tkinter.Misc.mainloop = lambda self, n=0: None
tkinter.Misc.wait_window = lambda self, window=None: None


# Remember the Python callable behind each button, so a `pass` stub can be named.
def _remember(cls):
    orig_init, orig_conf = cls.__init__, cls.configure

    def init(self, *a, **k):
        orig_init(self, *a, **k)
        if callable(k.get("command")):
            self._nd_cmd = k["command"]

    def conf(self, cnf=None, **k):
        if callable(k.get("command")):
            self._nd_cmd = k["command"]
        return orig_conf(self, cnf, **k)

    cls.__init__ = init
    cls.configure = cls.config = conf


_remember(tkinter.Button)
_remember(ttk.Button)


def _user_frames(tb_text):
    """Keep the frames in the user's own code; tkinter internals are noise."""
    out, skipping = [], False
    for ln in tb_text.splitlines():
        s = ln.strip().lower()
        if s.startswith('file "'):
            skipping = ("\\lib\\" in s or "/lib/" in s or "site-packages" in s)
            if skipping:
                continue
        elif skipping and ln.startswith("    "):
            continue
        else:
            skipping = False
        out.append(ln)
    return "\n".join(out[-10:]).strip()


def _is_stub(fn):
    """True if a handler's body is only `pass`, a docstring or `...`."""
    fn = getattr(fn, "__func__", fn)
    try:
        node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    except Exception:
        return False
    body = [b for b in getattr(node, "body", [])
            if not (isinstance(b, ast.Expr) and isinstance(getattr(b, "value", None), ast.Constant))]
    return not body or all(isinstance(b, ast.Pass) for b in body)


def _walk(w):
    yield w
    try:
        for c in w.winfo_children():
            yield from _walk(c)
    except Exception:
        return


def _label(w):
    try:
        return str(w.cget("text") or "").strip() or w.winfo_class()
    except Exception:
        return w.winfo_class()


sys.path.insert(0, os.path.dirname(target))
os.chdir(os.path.dirname(target))
try:
    g = runpy.run_path(target, run_name="__main__")
    if not _roots and callable(g.get("main")):
        g["main"]()
except SystemExit:
    pass
except Exception:
    report["startup_error"] = _user_frames(traceback.format_exc())

report["windows"] = len(_roots)
for root in list(_roots):
    try:
        root.update()
    except Exception:
        continue
    for w in list(_walk(root)):
        if not isinstance(w, (tkinter.Button, ttk.Button)):
            continue
        name = _label(w)
        handler = getattr(w, "_nd_cmd", None)
        entry = {"button": name, "handler": getattr(handler, "__name__", ""), "result": "ok"}
        try:
            has_cmd = bool(str(w.cget("command")).strip())
        except Exception:
            has_cmd = handler is not None
        if not has_cmd:
            entry["result"] = "no command attached — the button is not wired to anything"
            report["buttons"].append(entry)
            continue
        if name.lower().split(" ")[0] in ("quit", "exit", "close"):
            entry["result"] = "skipped (would close the app)"
            report["buttons"].append(entry)
            continue
        n_err, n_dlg = len(_errors), len(report["dialogs"])
        _current[0] = name
        try:
            w.invoke()
            root.update()
        except Exception:
            _errors.append((name, traceback.format_exc()))
        if len(_errors) > n_err:
            entry["result"] = "error"
            entry["error"] = _user_frames(_errors[-1][1])
        elif handler is not None and _is_stub(handler):
            entry["result"] = ("does nothing — %s() is an empty stub (its body is only `pass`)"
                               % entry["handler"])
        elif len(report["dialogs"]) > n_dlg:
            entry["result"] = "ok — " + report["dialogs"][-1][:70]
        report["buttons"].append(entry)

print("ND_GUI_REPORT:" + json.dumps(report))
