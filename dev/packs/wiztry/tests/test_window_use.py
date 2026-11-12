"""T08: the window works as a person opens it: every pane shows, Browse works, the path box is never a silent dead end."""
import os
import sys
import time

from _t import FIXTURE, check, finish

try:
    from wiztry.app import App
except Exception as e:                                  # noqa: BLE001
    check("wiztry.app imports", False, e)
    finish()

# tk.filedialog only exists once somebody has imported tkinter.filedialog; the app must do that itself.
check("the app imports tkinter.filedialog itself", "tkinter.filedialog" in sys.modules)
import tkinter.filedialog as fd  # noqa: E402


def pump(app, secs):
    end = time.time() + secs
    while time.time() < end:
        app.update()
        time.sleep(0.01)


def wait_idle(app, secs=30):
    end = time.time() + secs
    while app.busy and time.time() < end:
        app.update()
        time.sleep(0.02)


def buttons(w):
    out = []
    for c in w.winfo_children():
        if c.winfo_class() in ("TButton", "Button"):
            out.append(c)
        out += buttons(c)
    return out


errors = []
app = App()                                             # as a double-click starts it: no folder given
app.report_callback_exception = lambda exc, val, tb: errors.append(repr(val))
app.geometry("1200x800+-4000+-4000")                    # a real, mapped window, kept off the desktop
pump(app, 0.8)

drive = os.environ.get("SystemDrive", "C:").upper() + "\\"
check("with no folder given, the path box starts with the system drive", app.path_var.get().upper() == drive, app.path_var.get())

# every pane has room at the start (the File Types list once started 1 pixel wide)
check("the File Types list shows, at least 250 px wide", bool(app.types.winfo_ismapped()) and app.types.winfo_width() >= 250,
      (app.types.winfo_ismapped(), app.types.winfo_width()))
check("the folder tree shows, at least 500 px wide", bool(app.tree.winfo_ismapped()) and app.tree.winfo_width() >= 500,
      (app.tree.winfo_ismapped(), app.tree.winfo_width()))
check("the tree is the wider of the two top panes", app.tree.winfo_width() > app.types.winfo_width(),
      (app.tree.winfo_width(), app.types.winfo_width()))
check("the treemap shows, at least 250 px high", bool(app.canvas.winfo_ismapped()) and app.canvas.winfo_height() >= 250,
      (app.canvas.winfo_ismapped(), app.canvas.winfo_height()))
check("the lists show, at least 150 px high", app.tree.winfo_height() >= 150, app.tree.winfo_height())

# the Scan button and the path box
app.path_var.set("   ")
app.scan_btn.invoke()
pump(app, 0.2)
check("Scan with an empty path box starts nothing", not app.busy)
check("and the status line asks for a folder", "folder" in app.status.get().lower(), app.status.get())

missing = os.path.join(FIXTURE, "no_such_folder_xyz")
app.path_var.set(missing)
app.scan_btn.invoke()
pump(app, 0.2)
check("Scan on a folder that does not exist starts nothing", not app.busy)
check("and the status line says it was not found", "not found" in app.status.get().lower(), app.status.get())

app.path_var.set('  "' + FIXTURE.replace("\\", "/") + '/"  ')
app.scan_btn.invoke()
check("Scan accepts a quoted path with forward slashes", app.busy)
check("and shows the cleaned path in the box", app.path_var.get() == FIXTURE, app.path_var.get())
wait_idle(app)
check("that scan finishes with the 91 files", "91 files" in app.status.get(), app.status.get())

# Browse
fd.askdirectory = lambda *a, **k: ""                     # the person pressed Cancel
before = app.path_var.get()
app.browse()
pump(app, 0.2)
check("Cancel in the Browse dialog changes nothing", app.path_var.get() == before and not app.busy, (app.path_var.get(), app.busy))

app.path_var.set("")
fd.askdirectory = lambda *a, **k: FIXTURE.replace("\\", "/")   # the dialog answers with forward slashes
app.browse()
check("browse() puts the chosen folder in the path box, with backslashes", app.path_var.get() == FIXTURE, app.path_var.get())
check("browse() starts the scan at once", app.busy)
wait_idle(app)
check("the scan from browse() finishes with the 91 files", "91 files" in app.status.get(), app.status.get())

named = [b for b in buttons(app) if str(b.cget("text")).startswith("Browse")]
check("there is one Browse... button", len(named) == 1, [str(b.cget("text")) for b in buttons(app)])
app.path_var.set("")
if named:
    named[0].invoke()
check("the Browse... button does the same as browse()", app.path_var.get() == FIXTURE and app.busy, (app.path_var.get(), app.busy))
wait_idle(app)
pump(app, 0.3)

check("no button raised an error", not errors, errors[:3])
app.destroy()
finish()
