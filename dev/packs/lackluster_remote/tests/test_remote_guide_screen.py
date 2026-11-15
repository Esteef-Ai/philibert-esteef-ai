"""T03: the guide with a remote, part 2 of 3: the highlight is always on screen; the guide scrolls along with it.

Split from test_remote_guide.py on 2026-11-15 (the checks are unchanged). Moving in the guide is test_remote_guide_moves.py."""
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


# Where the highlight sits compared with the part of the guide a person can see.
SEEN = ("(function(){var e=document.activeElement, sc=document.getElementById('guide-scroll').getBoundingClientRect();"
        "var ru=document.querySelector('.guide-ruler-row').getBoundingClientRect(), r=e.getBoundingClientRect();"
        "var cc=e.closest('.guide-row').querySelector('.chan-cell').getBoundingClientRect();"
        "return {top:r.top>=ru.bottom-1, bottom:r.bottom<=Math.min(sc.bottom, innerHeight)+1, "
        "start:e.classList.contains('logo-tile') || (r.right>cc.right+30 && r.left<sc.right-30)};})()")

br.press("down")                                           # the first arrow: what is on now on channel 1
if not is_cell(active(), "c1"):
    check("set-up: the first arrow highlights a programme on channel 1 (test_remote_guide_moves.py)", False, active())

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

# ── OK on a programme ───────────────────────────────────────────────────────
br.press("ok")
check("OK on a programme opens its info", br.wait("document.getElementById('detail-drawer').classList.contains('open') && "
      "document.getElementById('dd-title').textContent", 3) == "Channel 1 show 14", br.js("document.getElementById('dd-title').textContent"))

bad = [e for e in br.errors if "cast" not in e.lower()]
check("the page raised no JavaScript errors", not bad, bad[:3])
br.stop()
gw.stop()
finish()
