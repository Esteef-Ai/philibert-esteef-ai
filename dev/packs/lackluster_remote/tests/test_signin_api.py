"""T01: the gateway's sign-in routes: a short code for TVs, a same-tab sign-in, and a pin nobody else can poll."""
import faulthandler
import re
import urllib.parse

faulthandler.dump_traceback_later(240, exit=True)
import requests  # noqa: E402

from _t import WS, FakePlex, Gateway, check, finish  # noqa: E402

fake = FakePlex()
gw = Gateway(fake)
check("the gateway starts (node dist/server.js)", gw.up, gw.tail())
if not gw.up:
    finish()

cfg = (WS / "dist" / "config.js").read_text(encoding="utf-8")
check("config.js reads PLEX_TV_URL and falls back to https://plex.tv", "PLEX_TV_URL" in cfg and "'https://plex.tv'" in cfg)
check("config.js reads PLEX_AUTH_APP_URL and falls back to https://app.plex.tv/auth/",
      "PLEX_AUTH_APP_URL" in cfg and "'https://app.plex.tv/auth/'" in cfg)
client = (WS / "dist" / "plexClient.js").read_text(encoding="utf-8")
check("plexClient.js no longer has plex.tv written into it (it uses the config)", "https://plex.tv" not in client
      and "https://app.plex.tv" not in client)


def start(session, mode=None):
    return session.post(gw.url + "/auth/plex/start", **({"json": {"mode": mode}} if mode else {}), timeout=20)


def poll(session, **kw):
    return session.get(gw.url + "/auth/plex/poll", timeout=20, **kw)


def body(r):
    try:
        return r.json()
    except ValueError:
        return {"not json": r.text[:120]}


# ── a short code, for a TV ──────────────────────────────────────────────────
tv = requests.Session()
before = len(fake.pin_posts())
r = start(tv, "link")
b = body(r)
pin = fake.last_pin()
check("link: POST /auth/plex/start {mode: link} answers 200", r.status_code == 200, (r.status_code, r.text[:200]))
posts = fake.pin_posts()[before:]
check("link: it asked Plex for one pin, a SHORT one (no strong=true)", posts == ["/api/v2/pins"], posts)
if pin is None:
    check("link: the stand-in for plex.tv was asked for a pin (PLEX_TV_URL is used)", False, fake.requests[-3:])
    gw.stop()
    finish()
check("link: the answer says mode link", b.get("mode") == "link", b)
check("link: code is Plex's 4-character code", b.get("code") == fake.pins[pin]["code"] and len(str(b.get("code"))) == 4, b.get("code"))
check("link: linkUrl is https://plex.tv/link", b.get("linkUrl") == "https://plex.tv/link", b.get("linkUrl"))
check("link: qrUrl is the QR picture Plex gave for this pin", b.get("qrUrl") == f"{fake.url}/qr/{fake.pins[pin]['code']}", b.get("qrUrl"))
check("link: expiresIn is Plex's 900 seconds", b.get("expiresIn") == 900, b.get("expiresIn"))
check("link: the pin's id is not in the answer", "pinId" not in b and str(pin) not in r.text, b)
jar = r.headers.get("set-cookie") or ""
check("link: the pin is remembered in an HttpOnly cookie lp_pin", "lp_pin=" in jar and "httponly" in jar.lower(), jar[:160])
raw = urllib.parse.unquote(tv.cookies.get("lp_pin") or "")
check("link: the cookie is signed (the pin id, a dot, a signature)", raw.startswith(f"{pin}.") and len(raw) > len(str(pin)) + 20, raw[:60])

r = poll(tv)
check("link: polling before anyone signed in says pending", r.status_code == 200 and body(r).get("status") == "pending", (r.status_code, r.text[:120]))

# the hole this closes: Plex's pin ids are numbers that count up, so a stranger could ask for someone else's
fake.authorise(pin, "tok-viewer")
thief = requests.Session()
r = poll(thief, params={"pinId": pin})
check("a browser that did not start the sign-in gets 400 for ?pinId=<someone's pin>", r.status_code == 400, (r.status_code, r.text[:160]))
check("... and no session cookie", "lp_session" not in (r.headers.get("set-cookie") or "") and not thief.cookies.get("lp_session"))
forged = requests.Session()
forged.cookies.set("lp_pin", f"{pin}.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
r = poll(forged)
check("a made-up lp_pin cookie (wrong signature) gets 400", r.status_code == 400, (r.status_code, r.text[:160]))
plain = requests.Session()
plain.cookies.set("lp_pin", str(pin))
r = poll(plain)
check("an unsigned lp_pin cookie (just the number) gets 400", r.status_code == 400, (r.status_code, r.text[:160]))

r = poll(tv)
b = body(r)
check("link: once Plex has the sign-in, the TV's poll says ok", r.status_code == 200 and b.get("status") == "ok", (r.status_code, r.text[:160]))
check("link: it names the viewer and their role", (b.get("user") or {}).get("username") == "viewer1"
      and (b.get("user") or {}).get("role") == "viewer", b.get("user"))
check("link: the TV now has a session (GET /auth/me is 200)", tv.get(gw.url + "/auth/me", timeout=20).status_code == 200)
check("link: the pin cookie is cleared after sign-in", not tv.cookies.get("lp_pin"), tv.cookies.get("lp_pin"))
r = poll(tv)
check("link: polling again afterwards gets 400 (the pin is used up)", r.status_code == 400, (r.status_code, r.text[:120]))

# ── a code that ran out ─────────────────────────────────────────────────────
old = requests.Session()
start(old, "link")
fake.expire(fake.last_pin())
r = poll(old)
check("an expired code answers 200 {status: expired}, not an error", r.status_code == 200 and body(r).get("status") == "expired",
      (r.status_code, r.text[:160]))
check("... and clears the pin cookie", not old.cookies.get("lp_pin"), old.cookies.get("lp_pin"))
r2 = start(old, "link")
check("... and a new code can be asked for straight away", r2.status_code == 200 and body(r2).get("code") == fake.pins[fake.last_pin()]["code"],
      r2.text[:160])

# ── a Plex account this server is not shared with ───────────────────────────
no = requests.Session()
start(no, "link")
fake.authorise(fake.last_pin(), "tok-stranger")
r = poll(no)
b = body(r)
check("an account without access gets 403 {status: denied} and a reason", r.status_code == 403 and b.get("status") == "denied"
      and "access" in str(b.get("error")), (r.status_code, r.text[:160]))
check("... and no session", no.get(gw.url + "/auth/me", timeout=20).status_code == 401)

# ── sign in on this device, in the same tab ─────────────────────────────────
pc = requests.Session()
before = len(fake.pin_posts())
r = start(pc, "redirect")
b = body(r)
pin = fake.last_pin()
url = str(b.get("authUrl"))
check("redirect: POST /auth/plex/start {mode: redirect} answers 200 with mode redirect", r.status_code == 200 and b.get("mode") == "redirect",
      (r.status_code, r.text[:200]))
check("redirect: it asked Plex for a strong pin", fake.pin_posts()[before:] == ["/api/v2/pins?strong=true"], fake.pin_posts()[before:])
check("redirect: authUrl is Plex's sign-in page (PLEX_AUTH_APP_URL) followed by #!?", url.startswith(fake.url + "/auth/#!?"), url[:80])
check("redirect: authUrl carries this pin's code and clientID=", f"&code={fake.pins[pin]['code']}" in url and "clientID=" in url, url)
want = urllib.parse.quote(f"{gw.url}/?signin=return", safe="")
check("redirect: authUrl ends with &forwardUrl=<this site>/?signin=return, percent-encoded", url.endswith("&forwardUrl=" + want),
      (url[-90:], want))
check("redirect: the pin's id is not in the answer", "pinId" not in b, b)
fake.authorise(pin, "tok-boss")
r = poll(pc)
check("redirect: back from Plex, the poll signs the admin in", r.status_code == 200 and (body(r).get("user") or {}).get("role") == "admin",
      (r.status_code, r.text[:160]))

# ── a page cached before this change ────────────────────────────────────────
legacy = requests.Session()
r = start(legacy)
b = body(r)
pin = fake.last_pin()
check("old page: POST /auth/plex/start with no body still answers pinId and authUrl", r.status_code == 200 and b.get("pinId") == pin
      and "forwardUrl" not in str(b.get("authUrl")) and str(b.get("authUrl")).startswith(fake.url + "/auth/#!?"), r.text[:200])
fake.authorise(pin, "tok-viewer")
r = poll(legacy, params={"pinId": pin})
check("old page: its poll (?pinId=..., plus the cookie it was given) still signs in", r.status_code == 200 and body(r).get("status") == "ok",
      (r.status_code, r.text[:160]))

log = gw.tail()
check("the gateway logged no server errors", not re.search(r'"statusCode":5\d\d|"level":50', log), log[-300:])
gw.stop()
finish()
