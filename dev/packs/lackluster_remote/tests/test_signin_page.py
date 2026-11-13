"""T02: the sign-in page, in a real (headless) browser: no popup, a code for TVs, a same-tab sign-in."""
import faulthandler
import time
import urllib.parse

faulthandler.dump_traceback_later(420, exit=True)
from _t import TV_UA, WS, Browser, FakePlex, Gateway, check, finish, visible  # noqa: E402

page = (WS / "public" / "index.html").read_text(encoding="utf-8")
check("index.html never calls window.open (a TV browser cannot handle a popup)", "window.open" not in page, page.count("window.open"))

fake = FakePlex()
gw = Gateway(fake)
check("the gateway starts", gw.up, gw.tail())
if not gw.up:
    finish()
br = Browser()
GATE = "!document.getElementById('gate').classList.contains('hidden')"
IN = "document.getElementById('gate').classList.contains('hidden') && document.getElementById('app').classList.contains('visible')"
CODE = "(document.getElementById('link-code')||{}).textContent"
STATUS = "document.getElementById('gate-status').textContent"


def sign_out():
    br.js("fetch('/auth/logout', {method:'POST'}).then(function(){return true;})")


def quit_all():
    br.stop()
    gw.stop()
    finish()


# ── on a computer or phone: two choices, nothing starts by itself ───────────
br.go(gw.url + "/")
check("computer: the sign-in screen shows", br.wait(GATE))
check("computer: the button 'Sign in with Plex' (id btn-signin) is visible", br.wait(visible("#btn-signin"), 5)
      and "Sign in with Plex" in str(br.js("document.getElementById('btn-signin').textContent")))
check("computer: a second button for a code (id btn-code) is visible", br.js(visible("#btn-code")))
if not br.js("!!document.getElementById('btn-code') && !!document.getElementById('link-panel')"):
    check("the page has #btn-code and #link-panel", False)
    quit_all()
check("computer: the code panel (id link-panel) is not visible yet", not br.js(visible("#link-panel")))
check("computer: no code was asked for until a button is pressed", len(fake.pin_posts()) == 0, fake.pin_posts())
check("computer: 'Sign in with Plex' has the focus (Enter or a remote's OK presses it)", br.js("document.activeElement.id") == "btn-signin",
      br.js("document.activeElement.id"))

# ── the code way, pressed by hand ───────────────────────────────────────────
br.click("#btn-code")
pin = None
code = br.wait(f"{visible('#link-panel')} && {CODE}", 8)
pin = fake.last_pin()
check("code: pressing the code button shows the panel with Plex's code", pin is not None and code == fake.pins[pin]["code"], code)
if pin is None:
    quit_all()
check("code: it was a short pin (no strong=true)", fake.pin_posts() == ["/api/v2/pins"], fake.pin_posts())
text = str(br.js("document.getElementById('link-panel').innerText"))
check("code: the panel says where to type it: plex.tv/link", "plex.tv/link" in text, text[:200])
check("code: the code is big enough to read from a sofa (64 px or more)",
      (br.js("parseFloat(getComputedStyle(document.getElementById('link-code')).fontSize)") or 0) >= 64,
      br.js("getComputedStyle(document.getElementById('link-code')).fontSize"))
check("code: the two sign-in buttons are hidden while the code shows", not br.js(visible("#btn-signin")) and not br.js(visible("#btn-code")))
qr = br.wait(f"{visible('#link-qr')} && document.getElementById('link-qr').naturalWidth > 0", 6)
check("code: the QR picture from Plex (id link-qr) is shown and loaded", qr
      and br.js("document.getElementById('link-qr').src") == f"{fake.url}/qr/{fake.pins[pin]['code']}", br.js("(document.getElementById('link-qr')||{}).src"))
check("code: a Back button (id btn-back) is visible and has the focus", br.js(visible("#btn-back")) and br.js("document.activeElement.id") == "btn-back",
      br.js("document.activeElement.id"))
check("code: still one tab, no popup", br.pages() == 1, br.pages())

br.key("Enter")                                            # Back, by keyboard (what a remote's OK sends)
check("code: Enter on Back returns to the two buttons", br.wait(f"{visible('#btn-signin')} && !{visible('#link-panel')}", 5))
polls = len([1 for m, p, _h in fake.requests if m == "GET" and p.startswith("/api/v2/pins/")])
time.sleep(4.5)
check("code: after Back the page stops asking about the old code",
      len([1 for m, p, _h in fake.requests if m == "GET" and p.startswith("/api/v2/pins/")]) <= polls + 1)

br.click("#btn-code")
br.wait(f"{visible('#link-panel')} && {CODE} && {CODE} !== {code!r}", 8)
pin = fake.last_pin()
fake.authorise(pin, "tok-viewer")
check("code: when the code is entered at Plex, the page signs in by itself within 8 seconds", br.wait(IN, 8), br.js(STATUS))
check("code: still one tab", br.pages() == 1, br.pages())

# ── a TV: the code is simply there ──────────────────────────────────────────
sign_out()
br.user_agent(TV_UA)
before = len(fake.pin_posts())
br.go(gw.url + "/")
code = br.wait(f"{visible('#link-panel')} && {CODE}", 10)
pin = fake.last_pin()
check("TV: on a TV browser the code appears without pressing anything", len(fake.pin_posts()) == before + 1 and code == fake.pins[pin]["code"],
      (code, fake.pin_posts()[before:]))
INSIDE = ("(function(){var w=innerWidth,h=innerHeight,bad=[];"
          "['#gate .mark','#gate h1','#link-url','#link-code','#link-qr','#btn-back','#gate-status'].forEach(function(s){"
          "var e=document.querySelector(s); if(!e){bad.push(s+' missing');return;} var r=e.getBoundingClientRect();"
          "if(r.top<0||r.left<0||r.bottom>h||r.right>w) bad.push(s+' '+Math.round(r.top)+'..'+Math.round(r.bottom));});"
          "return bad.join('; ') || 'ok';})()")
for w, h in ((1280, 720), (960, 540)):
    br.size(w, h)
    time.sleep(0.6)
    got = br.js(INSIDE)
    check(f"TV: at {w}x{h} the logo, the name, plex.tv/link, the code, the QR, Back and the status line are all on screen", got == "ok", got)
br.size(1280, 720)
fake.expire(pin)
new = br.wait(f"{CODE} !== {code!r} && {CODE}", 10)
pin2 = fake.last_pin()
check("TV: when the code runs out, a new one replaces it by itself", pin2 != pin and new == fake.pins[pin2]["code"], (code, new))
check("TV: the panel is still showing", br.js(visible("#link-panel")))
fake.authorise(pin2, "tok-stranger")
err = br.wait("document.getElementById('gate-status').classList.contains('error') && " + STATUS, 8)
check("TV: an account without access is told why, in the status line", "access" in str(err), err)
check("TV: ... and the buttons are back, with the focus on the code button", br.wait(visible("#btn-code"), 4)
      and br.js("document.activeElement.id") == "btn-code", br.js("document.activeElement.id"))
check("TV: ... and the sign-in screen is still up", br.js(GATE))

br.user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36")
before = len(fake.pin_posts())
br.go(gw.url + "/?tv=1")
code = br.wait(f"{visible('#link-panel')} && {CODE}", 10)
check("any browser opened at /?tv=1 gets the code straight away too", len(fake.pin_posts()) == before + 1 and bool(code), code)

# ── sign in on this device: same tab, there and back ────────────────────────
br.go(gw.url + "/")
br.wait(visible("#btn-signin"), 8)
before = len(fake.pin_posts())
br.key("Enter")                                            # the focused button, by keyboard
at = br.wait(f"location.href.indexOf({(fake.url + '/auth/')!r}) === 0 && location.href", 10)
pin = fake.last_pin()
check("same tab: Enter on 'Sign in with Plex' takes THIS tab to Plex's sign-in page", bool(at), br.url())
check("same tab: it used a strong pin", fake.pin_posts()[before:] == ["/api/v2/pins?strong=true"], fake.pin_posts()[before:])
check("same tab: still one tab, no popup", br.pages() == 1, br.pages())
back = urllib.parse.parse_qs(str(at).split("#!?", 1)[-1]).get("forwardUrl", [""])[0]
check("same tab: Plex is told to come back to <this site>/?signin=return", back == gw.url + "/?signin=return", back)
if back:
    fake.authorise(pin, "tok-boss")
    br.go(back)
    check("same tab: back from Plex, the page finishes the sign-in by itself", br.wait(IN, 10), br.js(STATUS))
    check("same tab: ... and takes signin=return out of the address", "signin" not in str(br.url()), br.url())
    check("same tab: the admin link shows for the admin", br.js("document.getElementById('admin-link').classList.contains('visible')"))

# coming back without having signed in must not leave a dead screen
sign_out()
br.go(gw.url + "/?signin=return")
got = br.wait(f"{visible('#btn-signin')} && document.getElementById('gate-status').classList.contains('error')", 8)
check("coming back with nothing in progress shows the buttons again and says so", got, br.js(STATUS))

bad = [e for e in br.errors if "cast" not in e.lower()]
check("the page raised no JavaScript errors", not bad, bad[:3])
quit_all()
