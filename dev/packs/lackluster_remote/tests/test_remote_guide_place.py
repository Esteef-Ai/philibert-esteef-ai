"""T04: the guide with a remote, part 3 of 3: the highlight keeps its place when the guide redraws; out of the guide and back.

Split from test_remote_guide.py on 2026-11-15 (the checks are unchanged). Moving in the guide is test_remote_guide_moves.py,
staying on screen is test_remote_guide_screen.py."""
import faulthandler
import time

faulthandler.dump_traceback_later(420, exit=True)
from _t import ACTIVE, FakePlex, Gateway, check, finish, signed_in  # noqa: E402

fake = FakePlex()
gw = Gateway(fake)
check("the gateway starts", gw.up, gw.tail())
if not gw.up:
    finish()
br = signed_in(fake, gw)
if not br.js("typeof window.tvNav === 'object'"):
    check("tvnav.js is loaded (window.tvNav)", False)
    br.stop()
    gw.stop()
    finish()


def active():
    return br.js(ACTIVE) or {}


def is_cell(a, row=None):
    return "prog-cell" in a.get("cls", "") and (row is None or a.get("row") == row)


def is_logo(a, row=None):
    return "logo-tile" in a.get("cls", "") and (row is None or a.get("row") == row)


br.press("down")                                           # the first arrow turns remote mode on
if not is_cell(active(), "c1"):
    check("set-up: the first arrow highlights a programme on channel 1 (test_remote_guide_moves.py)", False, active())

# ── the guide redraws itself every minute ───────────────────────────────────
br.focus('.guide-row[data-row="c3"] .prog-cell.on-now')
br.press("right")
before = active()
br.js("renderGrid()")
time.sleep(0.8)
after = active()
check("when the guide redraws, the highlight is put back on the same programme", is_cell(after, "c3") and after.get("text") == before.get("text")
      and br.js("document.activeElement.isConnected"), (before.get("text"), after))
br.focus('.guide-row[data-row="c4"] .logo-tile')
br.press("down", "up")
br.js("renderGrid()")
time.sleep(0.8)
check("... and on the same logo, when a logo was highlighted", is_logo(active(), "c4"), active())

# ── out of the guide and back in ────────────────────────────────────────────
br.js("document.getElementById('guide-scroll').scrollTop = 0; document.getElementById('guide-scroll').scrollLeft = 0;")
br.focus('.guide-row[data-row="c1"] .prog-cell.on-now')
br.press("left", "right", "up")
a = active()
check("Up from the first channel leaves the guide for the buttons above it", a.get("row") == "" and a.get("tag") in ("BUTTON", "INPUT"), a)
br.press("down")
a = active()
check("Down from there comes back into the guide", a.get("row") != "" and (is_cell(a) or is_logo(a)), a)

bad = [e for e in br.errors if "cast" not in e.lower()]
check("the page raised no JavaScript errors", not bad, bad[:3])
br.stop()
gw.stop()
finish()
