"""T10: the window never freezes on a big folder: it counts while it scans and shows the result quickly."""
import re
import faulthandler
import time

faulthandler.dump_traceback_later(60, exit=True)      # a layout that hangs must fail fast, not hang the test
from _t import FIXTURE_BIG, check, finish

try:
    from wiztry.app import App
    from wiztry.filetypes import color_map
    from wiztry.scanner import Node, summary
except Exception as e:                                  # noqa: BLE001
    check("wiztry.app imports", False, e)
    finish()

errors = []
app = App(FIXTURE_BIG)
app.report_callback_exception = lambda exc, val, tb: errors.append(repr(val))
app.geometry("1200x800+-4000+-4000")                    # a real, mapped window, kept off the desktop
end = time.time() + 0.6
while time.time() < end:
    app.update()
    time.sleep(0.01)

# 1. a real scan of 50,000 files: the status line counts, and the window keeps answering
app.start_scan(FIXTURE_BIG)
seen, worst = set(), 0.0
end = time.time() + 60
while app.busy and time.time() < end:
    t = time.perf_counter()
    app.update()
    worst = max(worst, time.perf_counter() - t)
    seen.add(app.status.get())
    time.sleep(0.002)
for _ in range(100):                                    # the half second after: the result is being shown
    t = time.perf_counter()
    app.update()
    worst = max(worst, time.perf_counter() - t)
    time.sleep(0.005)
counts = [s for s in seen if re.fullmatch(r"Scanning\.\.\. [1-9][\d,]* files", s)]
check("while scanning, the status line counts files (Scanning... 12,000 files)", bool(counts), sorted(seen)[:5])
check("the scan of 50,000 files finishes", not app.busy and "50,000 files" in app.status.get(), app.status.get())
check("scanning and showing 50,000 files never freezes the window for 1.5 seconds", worst < 1.5, f"longest freeze {worst:.2f} s")

# 2. every row of the File Types list keeps its color swatch (only the last one used to survive)
alive = set(app.tk.call("image", "names"))
rows = app.types.get_children()
lost = [app.types.item(i, "text") for i in rows if str(app.types.item(i, "image")[0] if app.types.item(i, "image") else "") not in alive]
check("the File Types list has rows", len(rows) >= 1, len(rows))
check("every File Types row still has its swatch image", not lost, lost[:5])

# 3. redrawing the treemap (a resize, a zoom) is quick, and the canvas is not flooded
t = time.perf_counter()
app.draw_treemap()
secs = time.perf_counter() - t
check("redrawing the treemap of 50,000 files takes under half a second", secs < 0.5, f"{secs:.2f} s")
check("the canvas holds at most 60,000 items", len(app.canvas.find_all()) <= 60_000, len(app.canvas.find_all()))
check("the treemap shows file blocks", len(app.blocks) >= 100, len(app.blocks))

# 4. a result as big as a drive (400,000 files in 4,000 folders, made in memory) is shown without a freeze.
#    show_result(top, skipped, seconds, by_ext) is what the main thread runs when the scan thread is done;
#    by_ext comes ready-made from the scan thread, so nothing here walks the whole tree again.
top = Node("drive", "X:\\", True)
for k in range(4_000):
    d = Node(f"d{k}", f"X:\\d{k}", True, parent=top)
    d.children = [Node(f"f{j}.e{j % 40}", f"X:\\d{k}\\f{j}.e{j % 40}", False, size=(k + 1) * 50 + (100 - j), files=1, parent=d)
                  for j in range(100)]
    d.size, d.files = sum(c.size for c in d.children), 100
    top.children.append(d)
top.children.sort(key=lambda c: -c.size)
top.size, top.files, top.folders = sum(c.size for c in top.children), 400_000, 4_000
by_ext = summary(top)["by_ext"]
t = time.perf_counter()
app.show_result(top, 0, 12.3, by_ext)
app.update()
secs = time.perf_counter() - t
check("showing a 400,000-file result takes under 1.5 seconds", secs < 1.5, f"{secs:.2f} s")
check("its status line reports the files, folders and time", "400,000 files" in app.status.get() and "4,000 folders" in app.status.get()
      and "12.3 s" in app.status.get(), app.status.get())
check("its tree has the scanned folder at the top, open", len(app.tree.get_children()) == 1
      and len(app.tree.get_children(app.tree.get_children()[0])) >= 1, len(app.tree.get_children()))
check("its File Types list has the 40 types", len(app.types.get_children()) == 40, len(app.types.get_children()))
check("its colors come from the by_ext it was given", app.colors == color_map(by_ext))
check("its treemap is drawn", len(app.canvas.find_all()) >= 100, len(app.canvas.find_all()))

check("nothing raised an error", not errors, errors[:3])
app.destroy()
finish()
