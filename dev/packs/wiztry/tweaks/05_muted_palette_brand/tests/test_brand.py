"""T18: the window carries the Esteef.Ai brand: the title, a byline in the toolbar, the name in the status bar."""
import faulthandler
import time

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


def labels(app, text):
    return [w for w in walk(app) if w.winfo_class() in ("TLabel", "Label") and str(w.cget("text")) == text]


errors = []
app = App(FIXTURE)
app.report_callback_exception = lambda exc, val, tb: errors.append(repr(val))
app.geometry("1200x800+-4000+-4000")                    # a real, mapped window, kept off the desktop
pump(app, 0.8)

check("the window title is theme.TITLE", app.title() == "WizTry - Esteef.Ai" == T.TITLE, app.title())

name = labels(app, "WIZTRY")
by = labels(app, "by Esteef.Ai")
check("the toolbar has the byline 'by Esteef.Ai' once, in the By style", len(by) == 1 and str(by[0].cget("style")) == "By.TLabel",
      [str(b.cget("style")) for b in by])
entry = next((w for w in walk(app) if w.winfo_class() == "TEntry"), None)
if name and by and entry is not None:
    n, b = name[0], by[0]
    check("the byline is in the toolbar, right after the name and before the path box",
          b.master is n.master and n.winfo_rootx() + n.winfo_width() <= b.winfo_rootx() + 1
          and b.winfo_rootx() + b.winfo_width() <= entry.winfo_rootx() + 1,
          (n.winfo_rootx(), n.winfo_width(), b.winfo_rootx(), b.winfo_width(), entry.winfo_rootx()))
    check("the byline sits on the name's baseline (its bottom within 4 px of the name's)",
          abs((b.winfo_rooty() + b.winfo_height()) - (n.winfo_rooty() + n.winfo_height())) <= 4,
          (n.winfo_rooty() + n.winfo_height(), b.winfo_rooty() + b.winfo_height()))

mark = labels(app, "Esteef.Ai")
stat = [w for w in walk(app) if w.winfo_class() in ("TLabel", "Label") and str(w.cget("textvariable")) == str(app.status)]
check("the status bar shows 'Esteef.Ai' once, in the By style", len(mark) == 1 and str(mark[0].cget("style")) == "By.TLabel",
      [str(m.cget("style")) for m in mark])
if mark and stat:
    m, s = mark[0], stat[0]
    bar = s.master
    check("it is in the status bar, at the right end", m.master is bar
          and (bar.winfo_rootx() + bar.winfo_width()) - (m.winfo_rootx() + m.winfo_width()) <= 16,
          (bar.winfo_rootx() + bar.winfo_width(), m.winfo_rootx() + m.winfo_width()))
    check("the status line is still at the left end", s.winfo_rootx() - bar.winfo_rootx() <= 16, (s.winfo_rootx(), bar.winfo_rootx()))

# the new palette reaches the treemap and the list
app.start_scan(FIXTURE)
end = time.time() + 30
while app.busy and time.time() < end:
    app.update()
    time.sleep(0.02)
pump(app, 0.4)
ok_fills = {p.lower() for p in T.PALETTE} | {T.OTHER}
odd = {str(app.canvas.itemcget(i, "fill")).lower() for i in app.blocks} - ok_fills
check("every file block uses the theme's palette", bool(app.blocks) and not odd, sorted(odd)[:5])
first = getattr(app, "swatches", [None])[0]
want = tuple(int(T.PALETTE[0][i:i + 2], 16) for i in (1, 3, 5))
check("the largest file type's swatch is the first palette color", first is not None and tuple(first.get(1, 1)) == want,
      first is not None and first.get(1, 1))
check("the status line still reports the scan", "91 files" in app.status.get(), app.status.get())

check("nothing raised an error", not errors, errors[:3])
app.destroy()
finish()
