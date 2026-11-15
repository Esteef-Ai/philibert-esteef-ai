"""T02: the guide with a remote, part 1 of 3: along a channel's programmes, and up and down the channels in a column.

Split from test_remote_guide.py on 2026-11-15 (the checks are unchanged): one task of 31 checks was more than the local
builder could finish in 40 minutes, so the guide is now three tasks: moving (this file), staying on screen, keeping
its place."""
import faulthandler

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


br.press("down")
a0 = active()
check("the first arrow highlights what is on now on channel 1", is_cell(a0, "c1") and "show 1" in a0.get("text", ""), a0)

# ── along one channel ───────────────────────────────────────────────────────
br.press("right")
a1 = active()
check("Right goes to the next programme on the same channel", is_cell(a1, "c1") and "show 2" in a1.get("text", ""), a1)
br.press("right")
a2 = active()
check("Right again goes to the one after", is_cell(a2, "c1") and "show 3" in a2.get("text", ""), a2)
br.press("left", "left")
check("Left twice comes back to what is on now", "show 1" in active().get("text", "") and is_cell(active(), "c1"), active())
br.press("left")
check("Left from the first programme goes to the channel's logo", is_logo(active(), "c1"), active())
br.press("left")
check("Left from the logo stays there while the Browse column is hidden", is_logo(active(), "c1"), active())
br.press("down")
check("Down from a logo goes to the next channel's logo", is_logo(active(), "c2"), active())
br.press("up")
check("Up comes back", is_logo(active(), "c1"), active())
br.press("right")
check("Right from the logo goes to the first programme", is_cell(active(), "c1") and "show 1" in active().get("text", ""), active())

# ── up and down keep the column ─────────────────────────────────────────────
br.press("right", "right")                                 # channel 1, show 3: starts 40 minutes from now
start = active()
br.press("down")
b = active()
check("Down from a programme goes to the programme at the same time on the next channel", is_cell(b, "c2")
      and "Channel 2 show 1" in b.get("text", ""), b)       # channel 2's first two-hour film is still running then
br.press("down")
c = active()
check("Down again: channel 3's programme at that time", is_cell(c, "c3") and "Channel 3 show 2" in c.get("text", ""), c)
br.press("down")
d = active()
check("Down again: channel 4's programme at that time", is_cell(d, "c4") and "Channel 4 show 1" in d.get("text", ""), d)
br.press("down")
e = active()
check("a channel with nothing scheduled gets its logo highlighted", is_logo(e, "c5"), e)
br.press("down")
f = active()
check("... and the column is not lost: the next channel is highlighted at the same time again", is_cell(f, "c6")
      and "Channel 6 show 2" in f.get("text", ""), f)
br.press("up", "up", "up", "up", "up")
back = active()
check("Up five times returns to the SAME programme it started from (the column does not drift)", is_cell(back, "c1")
      and back.get("text") == start.get("text"), (start.get("text"), back.get("text")))

# ── rows that a filter hid are skipped ──────────────────────────────────────
br.js("document.querySelector('.guide-row[data-row=\"c2\"]').classList.add('row-hidden')")
br.press("down")
check("Down skips a channel the filter has hidden", active().get("row") == "c3", active())
br.press("up")
check("... and so does Up", active().get("row") == "c1", active())
br.js("document.querySelector('.guide-row[data-row=\"c2\"]').classList.remove('row-hidden')")

bad = [e for e in br.errors if "cast" not in e.lower()]
check("the page raised no JavaScript errors", not bad, bad[:3])
br.stop()
gw.stop()
finish()
