"""T02: the guide with a remote: along a channel's programmes, up and down the channels, always on screen."""
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


# Where the highlight sits compared with the part of the guide a person can see.
SEEN = ("(function(){var e=document.activeElement, sc=document.getElementById('guide-scroll').getBoundingClientRect();"
        "var ru=document.querySelector('.guide-ruler-row').getBoundingClientRect(), r=e.getBoundingClientRect();"
        "var cc=e.closest('.guide-row').querySelector('.chan-cell').getBoundingClientRect();"
        "return {top:r.top>=ru.bottom-1, bottom:r.bottom<=Math.min(sc.bottom, innerHeight)+1, "
        "start:e.classList.contains('logo-tile') || (r.right>cc.right+30 && r.left<sc.right-30)};})()")

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

# ── the highlight is always on screen ───────────────────────────────────────
bad, rows = [], []
for _ in range(11):
    br.press("down")
    a, s = active(), br.js(SEEN) or {}
    rows.append(a.get("row"))
    if not (s.get("top") and s.get("bottom") and s.get("start")):
        bad.append((a.get("row"), s))
check("Down through all twelve channels visits each in order", rows == [f"c{i}" for i in range(2, 13)], rows)
check("... and the highlight is never under the time ruler or below the guide", not bad, bad[:3])
br.press("down")
check("Down on the last channel stays there", active().get("row") == "c12", active())
bad = []
for _ in range(11):
    br.press("up")
    s = br.js(SEEN) or {}
    if not (s.get("top") and s.get("bottom")):
        bad.append((active().get("row"), s))
check("Up back to the first channel keeps the highlight on screen too", active().get("row") == "c1" and not bad, (active().get("row"), bad[:3]))

x0 = br.js("document.getElementById('guide-scroll').scrollLeft")
br.press("left", "left", "left", "left")                   # back to the logo, then out along the day
bad, titles = [], []
for _ in range(14):
    br.press("right")
    a, s = active(), br.js(SEEN) or {}
    titles.append(a.get("text", "")[-8:])
    if not s.get("start"):
        bad.append((a.get("text"), a.get("left")))
check("Right fourteen times walks fourteen programmes into the day", is_cell(active(), "c1") and "show 14" in active().get("text", ""), titles[-3:])
check("... the guide scrolls along so the highlighted programme's start is always visible", not bad, bad[:3])
x1 = br.js("document.getElementById('guide-scroll').scrollLeft")
check("... because the guide itself has scrolled on through the day", x1 > x0 + 500, (x0, x1))

# ── OK, and Back to the same place ──────────────────────────────────────────
here = active()
br.press("ok")
check("OK on a programme opens its info", br.wait("document.getElementById('detail-drawer').classList.contains('open') && "
      "document.getElementById('dd-title').textContent", 3) == "Channel 1 show 14", br.js("document.getElementById('dd-title').textContent"))

# ── the guide redraws itself every minute ───────────────────────────────────
br.js("closeDetail()")
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
