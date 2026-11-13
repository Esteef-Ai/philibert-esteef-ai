"""T03: Back closes the top-most thing, and the player answers the remote (channel up/down, pause)."""
import faulthandler
import time

faulthandler.dump_traceback_later(420, exit=True)
from _t import ACTIVE, TV_UA, Browser, FakePlex, Gateway, check, finish, signed_in, visible  # noqa: E402

fake = FakePlex()
gw = Gateway(fake)
check("the gateway starts", gw.up, gw.tail())
if not gw.up:
    finish()
br = signed_in(fake, gw)
OPEN = "document.getElementById('{}').classList.contains('open')"


def active():
    return br.js(ACTIVE) or {}


def stop_all():
    bad = [e for e in br.errors if "cast" not in e.lower() and "hls" not in e.lower()]
    check("the page raised no JavaScript errors", not bad, bad[:3])
    br.stop()
    gw.stop()
    finish()


check("window.tvBack is a function (the TV app calls it for the remote's Back button)", br.js("typeof window.tvBack === 'function'"))
if not br.js("typeof window.tvBack === 'function'"):
    stop_all()
check("with nothing open tvBack() answers false (the TV app may then leave)", br.js("window.tvBack()") is False)

# ── a pop-up: Play Now ──────────────────────────────────────────────────────
br.press("down")
br.focus('.btn-playnow')
br.press("ok")
check("OK on Play Now opens it", br.wait(OPEN.format("playnow-modal"), 3))
inside, got = set(), set()
for d in ("down", "right", "right", "down", "left", "down", "right", "up", "up", "left", "down", "down", "down"):
    br.press(d)
    inside.add(br.js("!!document.activeElement.closest('#playnow-modal')"))
    got.add(br.js("(document.activeElement.innerText||'').trim()"))
check("while it is open the arrows stay inside it", inside == {True}, inside)
check("... and reach the type buttons, Surprise Me and Cancel", {"TV", "Movies", "Cancel"} <= got and any("Surprise" in g for g in got), got)
br.press("back")
check("Back closes Play Now", not br.js(OPEN.format("playnow-modal")))
check("... and the highlight returns to the Play Now button", "btn-playnow" in active().get("cls", ""), active())

# ── the options menu ────────────────────────────────────────────────────────
br.focus('.icon-btn')
br.press("ok", "down")
check("the options menu is open and the highlight is in it", br.js(OPEN.format("options-dropdown"))
      and br.js("!!document.activeElement.closest('#options-dropdown')"), active())
check("tvBack() closes it and answers true", br.js("window.tvBack()") is True and not br.js(OPEN.format("options-dropdown")))
check("... and the highlight is back on the guide screen, on something visible",
      br.js("document.getElementById('app').contains(document.activeElement) && !document.activeElement.closest('#options-dropdown')")
      and br.js("document.activeElement.getBoundingClientRect().width > 0"), active())

# ── watching ────────────────────────────────────────────────────────────────
br.js("document.getElementById('guide-scroll').scrollTop = 0;")
br.focus('.guide-row[data-row="c3"] .prog-cell.on-now')
br.press("left", "right", "ok")                            # arrive on it with the arrows, then OK
check("OK on what is on now opens its info, with Watch Live highlighted", br.wait(OPEN.format("detail-drawer"), 3)
      and br.wait("document.activeElement.id === 'dd-watch'", 3), active())
br.size(960, 540)
time.sleep(1.0)
ON_SCREEN = ("(function(id){var r=document.getElementById(id).getBoundingClientRect(); return r.height>0 && r.top>=0 && r.bottom<=innerHeight;})")
check("on a TV-sized screen (960x540) the title of what was opened is on screen", br.js(ON_SCREEN + "('dd-title')"),
      br.js("document.getElementById('dd-title').getBoundingClientRect().top"))
check("... together with the Watch Live button", br.js(ON_SCREEN + "('dd-watch')"), br.js("document.getElementById('dd-watch').getBoundingClientRect().bottom"))
br.size(1280, 720)
VIDEO = "(function(){var r=document.getElementById('player-video').getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height), innerWidth, innerHeight];})()"
br.js("window.__plays=0; window.__pauses=0; var v=document.getElementById('player-video');"
      "v.play=function(){window.__plays++; return Promise.resolve();}; v.pause=function(){window.__pauses++;};")
br.press("ok")
check("OK on Watch Live opens the player", br.wait(OPEN.format("player-modal"), 4))
check("... on that channel", br.js("document.getElementById('pm-channel').textContent") == "Channel 3", br.js("document.getElementById('pm-channel').textContent"))
check("... and the highlight goes to the video", br.wait("document.activeElement.id === 'player-video'", 3), active())
v = br.js(VIDEO)
check("on a computer the player keeps its window size (not the whole screen)", v[0] < v[2] and v[1] < v[3], v)

br.press("down")
check("Down on the video changes to the next channel", br.wait("document.getElementById('pm-channel').textContent === 'Channel 4'", 3),
      br.js("document.getElementById('pm-channel').textContent"))
check("... and the highlight stays on the video", br.js("document.activeElement.id") == "player-video", active())
br.press("up", "up")
check("Up twice changes to the channel before the first one", br.wait("document.getElementById('pm-channel').textContent === 'Channel 2'", 3),
      br.js("document.getElementById('pm-channel').textContent"))
br.press("up", "up")
check("Up past the first channel wraps to the last", br.wait("document.getElementById('pm-channel').textContent === 'Channel 12'", 3),
      br.js("document.getElementById('pm-channel').textContent"))
br.press("down")
check("... and Down from the last wraps to the first", br.wait("document.getElementById('pm-channel').textContent === 'Channel 1'", 3),
      br.js("document.getElementById('pm-channel').textContent"))

n = br.js("window.__plays")
br.press("ok")
check("OK on the video resumes a paused picture (calls play())", br.js("window.__plays") == n + 1, (n, br.js("window.__plays")))
br.js("Object.defineProperty(document.getElementById('player-video'), 'paused', {get:function(){return false;}, configurable:true});")
br.press("ok")
check("OK again pauses it (calls pause())", br.js("window.__pauses") == 1, br.js("window.__pauses"))
br.press("playpause")
check("the remote's Play/Pause button does the same", br.js("window.__pauses") == 2, br.js("window.__pauses"))

br.press("right")
a = active()
check("Right from the video goes to the Close button", a.get("tag") == "BUTTON" and a.get("text") == "Close", a)
seen = set()
for d in ["left"] * 6 + ["right"] * 6:
    br.press(d)
    seen.add(active().get("text", ""))
check("Left and Right move along the player's buttons", "Close" in seen and any("Media view" in s for s in seen)
      and any("Diagnostics" in s for s in seen), seen)
check("... and never leave the player", br.js("!!document.activeElement.closest('#player-modal')"), active())
br.press("up")
check("Up from the buttons returns to the video", br.js("document.activeElement.id") == "player-video", active())

# the chat panel opens over the player in Media view: Back closes it first
br.js("toggleTheaterMode()")
check("Media view opens the chat panel", br.wait(OPEN.format("social-panel"), 3))
br.press("back")
check("Back closes the chat panel first; the player stays", not br.js(OPEN.format("social-panel")) and br.js(OPEN.format("player-modal")))
check("... with the highlight on the video", br.js("document.activeElement.id") == "player-video", active())
br.press("back")
check("Back again closes the player", not br.js(OPEN.format("player-modal")))
a = active()
check("... and the highlight is back on the guide screen, on something visible", br.js("document.getElementById('app').contains(document.activeElement)")
      and br.js("document.activeElement.getBoundingClientRect().width > 0"), a)
check("the info drawer is still open behind it", br.js(OPEN.format("detail-drawer")))
br.press("back")
a = active()
check("Back again closes the info drawer", not br.js(OPEN.format("detail-drawer")))
check("... and the highlight returns to the guide", a.get("row") != "", a)
check("with everything closed tvBack() answers false again", br.js("window.tvBack()") is False)

# ── the channel logo: OK for what is on, OK again to watch ──────────────────
br.focus('.guide-row[data-row="c6"] .logo-tile')
br.press("down", "up", "ok")
check("OK on a channel logo opens what is on there", br.wait(OPEN.format("detail-drawer"), 3)
      and "Channel 6" in str(br.js("document.getElementById('dd-title').textContent")), br.js("document.getElementById('dd-title').textContent"))
br.press("ok")
check("OK again starts that channel", br.wait(OPEN.format("player-modal"), 4)
      and br.js("document.getElementById('pm-channel').textContent") == "Channel 6", br.js("document.getElementById('pm-channel').textContent"))
br.js("window.tvBack(); window.tvBack();")
stop_old = br
bad = [e for e in br.errors if "cast" not in e.lower() and "hls" not in e.lower()]
check("the page raised no JavaScript errors so far", not bad, bad[:3])
stop_old.stop()

# ── on a TV the picture fills the screen ────────────────────────────────────
br = signed_in(fake, gw, ua=TV_UA, path="/")
br.size(960, 540)
check("a TV browser gets the class tv-device on <body>", br.js("document.body.classList.contains('tv-device')"))
br.press("down", "ok")
br.wait("document.activeElement.id === 'dd-watch'", 4)
br.press("ok")
br.wait(OPEN.format("player-modal") + " && document.activeElement.id === 'player-video'", 5)
v = br.js(VIDEO)
check("on a TV the video fills the whole screen", v and v[0] >= v[2] - 1 and v[1] >= v[3] - 1, v)
ROW = "getComputedStyle(document.querySelector('#player-modal > div:last-child')).opacity"
INFO = "getComputedStyle(document.querySelector('#player-modal .player-info')).opacity"
check("the channel line and the buttons lie over the picture", br.js(ROW) == "1" and br.js(INFO) == "1"
      and br.js("(function(){var r=document.querySelector('#player-modal > div:last-child').getBoundingClientRect(); return r.bottom<=innerHeight && r.top>innerHeight/2;})()"),
      (br.js(ROW), br.js(INFO)))
time.sleep(6.2)
check("after five seconds without a key they fade away", br.js(ROW) == "0" and br.js(INFO) == "0", (br.js(ROW), br.js(INFO)))
br.press("right")
time.sleep(0.8)
check("any key brings them back", br.js(ROW) == "1" and br.js(INFO) == "1", (br.js(ROW), br.js(INFO)))
check("... and Right still reaches Close", active().get("text") == "Close", active())
br.press("back")
check("Back closes the player on a TV too", not br.js(OPEN.format("player-modal")))
bad = [e for e in br.errors if "cast" not in e.lower() and "hls" not in e.lower()]
check("the page raised no JavaScript errors on the TV", not bad, bad[:3])
br.stop()

# ── the sign-in screen ──────────────────────────────────────────────────────
br = Browser()
br.go(gw.url + "/")
br.wait(visible("#btn-code"), 8)
br.js("document.getElementById('btn-code').click()")
br.wait(visible("#link-panel"), 8)
br.press("back")
check("sign-in on a computer: Back on the code screen returns to the two buttons", br.wait(f"{visible('#btn-signin')} && !{visible('#link-panel')}", 4))
check("... and tvBack() there answers false (nothing more to close)", br.js("window.tvBack()") is False)
br.user_agent(TV_UA)
br.go(gw.url + "/")
br.wait(visible("#link-panel"), 10)
check("sign-in on a TV: the code screen IS the first screen, so tvBack() answers false and the code stays",
      br.js("window.tvBack()") is False and br.js(visible("#link-panel")))
time.sleep(0.3)
stop_all()
