"""Shared bits for the Lackluster Plus+ sign-in tests.

Nothing here talks to the real Plex: FakePlex stands in for plex.tv, for app.plex.tv, for the Plex server and
for Tunarr. Gateway starts the real gateway (node dist/server.js) pointed at it, on a free port, with its
database in the temp folder. Browser drives a real, headless Edge (no window) over its debugging port.
"""
import base64
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
TV_UA = "Mozilla/5.0 (SMART-TV; Linux; Tizen 7.0) AppleWebKit/537.36 (KHTML, like Gecko) 94.0 TV Safari/537.36"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEklEQVR4nGP8z4AdMOEQH6wSAMVfAQ+gW1VLAAAAAElFTkSuQmCC")
_results = []


def check(label, ok, got=""):
    _results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f" - got {got!r}"[:400]), flush=True)


def finish():
    passed = sum(_results)
    print(f"{passed} passed, {len(_results) - passed} failed", flush=True)
    sys.stdout.flush()
    os._exit(0 if passed == len(_results) else 1)          # server threads and child processes must not keep us alive


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class FakePlex:
    """plex.tv + app.plex.tv + the Plex server + Tunarr, on one local port.

    people: token -> {"id", "username", "email", "access"}.  pins: id -> {"code", "strong", "state", "token"}.
    A test moves a pin along with authorise(pin_id, token) and expire(pin_id)."""

    def __init__(self):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.pins = {}
        self.requests = []                                  # (method, path with query, headers)
        self.people = {
            "tok-viewer": {"id": 501, "username": "viewer1", "email": "viewer1@example.com", "access": True},
            "tok-boss": {"id": 502, "username": "boss", "email": "boss@example.com", "access": True},
            "tok-stranger": {"id": 503, "username": "stranger", "email": "stranger@example.com", "access": False},
        }
        self._codes = iter(["K7QM", "R2XD", "W9TB", "H4NC", "P6LF", "Z3GV", "M8JY", "T5SA"] * 20)
        self._next = 9000
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)

            def pin_json(self, pid):
                p = fake.pins[pid]
                return {"id": pid, "code": p["code"], "product": "x", "trusted": False, "qr": f"{fake.url}/qr/{p['code']}",
                        "clientIdentifier": p["client"], "expiresIn": 900,
                        "authToken": p["token"] if p["state"] == "ok" else None}

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n:
                    self.rfile.read(n)
                fake.requests.append(("POST", self.path, dict(self.headers)))
                u = urllib.parse.urlparse(self.path)
                if u.path == "/api/v2/pins":
                    strong = urllib.parse.parse_qs(u.query).get("strong") == ["true"]
                    fake._next += 7
                    code = ("s" + next(fake._codes).lower() * 6) if strong else next(fake._codes)
                    fake.pins[fake._next] = {"code": code, "strong": strong, "state": "pending", "token": None,
                                             "client": self.headers.get("X-Plex-Client-Identifier")}
                    return self.send(201, self.pin_json(fake._next))
                self.send(404, {"error": "not found"})

            def do_GET(self):
                fake.requests.append(("GET", self.path, dict(self.headers)))
                u = urllib.parse.urlparse(self.path)
                parts = u.path.strip("/").split("/")
                if u.path.startswith("/api/v2/pins/") and parts[-1].isdigit():
                    pid = int(parts[-1])
                    p = fake.pins.get(pid)
                    if not p or p["state"] == "expired" or self.headers.get("X-Plex-Client-Identifier") != p["client"]:
                        return self.send(404, {"errors": [{"code": 1020, "message": "Code not found or expired"}]})
                    return self.send(200, self.pin_json(pid))
                if u.path == "/api/v2/user":
                    who = fake.people.get(self.headers.get("X-Plex-Token"))
                    if not who:
                        return self.send(401, {"error": "unauthorized"})
                    return self.send(200, {"id": who["id"], "username": who["username"], "email": who["email"], "thumb": None})
                if u.path == "/identity":
                    who = fake.people.get(self.headers.get("X-Plex-Token"))
                    return self.send(200 if who and who["access"] else 401, {"MediaContainer": {}})
                if u.path.startswith("/qr/"):
                    return self.send(200, PNG, "image/png")
                if u.path.startswith("/auth"):
                    return self.send(200, "<!doctype html><title>Fake Plex sign-in</title><h1 id='fake-plex'>Fake Plex sign-in</h1>",
                                     "text/html")
                self.send(404, {"error": "not found"})

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def authorise(self, pin_id, token):
        self.pins[pin_id].update(state="ok", token=token)

    def expire(self, pin_id):
        self.pins[pin_id]["state"] = "expired"

    def last_pin(self):
        return max(self.pins) if self.pins else None

    def pin_posts(self):
        return [p for m, p, _h in self.requests if m == "POST" and p.startswith("/api/v2/pins")]


class Gateway:
    """The real gateway, started from this project folder, talking to a FakePlex."""

    def __init__(self, fake):
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.data = tempfile.mkdtemp(prefix="lp_gateway_")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PLEX_", "TUNARR_", "SESSION_", "ADMIN_", "DATA_", "EXTERNAL_"))}
        env.update(EXTERNAL_PORT=str(self.port), DATA_DIR=self.data, PLEX_SERVER_URL=fake.url, PLEX_TV_URL=fake.url,
                   PLEX_AUTH_APP_URL=fake.url + "/auth/", TUNARR_INTERNAL_URL=fake.url, ADMIN_PLEX_USERNAMES="boss",
                   SESSION_SECRET="test-secret-0123456789abcdef0123456789abcdef", BORDERS_DIR=self.data)
        self.log = open(os.path.join(self.data, "gateway.log"), "w", encoding="utf-8")
        self.proc = subprocess.Popen(["node", "dist/server.js"], cwd=str(WS), env=env, stdout=self.log, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.up = False
        end = time.time() + 30
        while time.time() < end and self.proc.poll() is None:
            try:
                urllib.request.urlopen(self.url + "/favicon.svg", timeout=2).read()
                self.up = True
                break
            except Exception:
                time.sleep(0.25)

    def tail(self):
        self.log.flush()
        return open(self.log.name, encoding="utf-8", errors="replace").read()[-600:]

    def stop(self):
        self.proc.kill()
        self.proc.wait(10)
        self.log.close()
        shutil.rmtree(self.data, ignore_errors=True)


class Browser:
    """A headless Edge, driven over its debugging port. No window ever appears."""

    def __init__(self):
        import websocket
        self.profile = tempfile.mkdtemp(prefix="lp_edge_")
        port = free_port()
        self.proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={self.profile}",
                                      "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--window-size=1280,720",
                                      # A new profile is NOT empty by itself: Edge signs in the Windows account and syncs the
                                      # person's extensions into it. Their welcome tabs look like popups and their scripts run
                                      # inside the page under test. These switches give a browser with nothing of the person's.
                                      "--disable-extensions", "--disable-sync", "--disable-default-apps",
                                      "--disable-component-extensions-with-background-pages", "--disable-background-networking",
                                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.http = f"http://127.0.0.1:{port}"
        page = None
        end = time.time() + 30
        while time.time() < end and page is None:
            try:
                page = next(t for t in self.targets() if t["type"] == "page" and t["url"].startswith("about:"))
            except Exception:
                time.sleep(0.25)
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
        self.n = 0
        self.errors = []
        for m in ("Page.enable", "Runtime.enable"):
            self.cmd(m)
        self.size(1280, 720)

    def targets(self):
        return json.loads(urllib.request.urlopen(self.http + "/json", timeout=5).read())

    def pages(self):
        """How many tabs and windows are open. A popup would make this 2."""
        return len([t for t in self.targets() if t["type"] == "page" and not t["url"].startswith(("edge:", "chrome-extension:"))])

    def cmd(self, method, **params):
        self.n += 1
        me = self.n
        self.ws.send(json.dumps({"id": me, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("method") == "Runtime.exceptionThrown":
                d = m["params"]["exceptionDetails"]
                self.errors.append(str((d.get("exception") or {}).get("description") or d.get("text"))[:200])
            if m.get("id") == me:
                return m.get("result") or {}

    def js(self, expr):
        r = self.cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return (r.get("result") or {}).get("value")

    def user_agent(self, ua):
        self.cmd("Emulation.setUserAgentOverride", userAgent=ua)

    def size(self, w, h):
        """The page's size in CSS pixels. A TV browser is usually 960x540 or 1280x720."""
        self.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)

    def go(self, url, settle=1.5):
        self.cmd("Page.navigate", url=url)
        time.sleep(settle)

    def url(self):
        return self.js("location.href")

    def wait(self, expr, secs=12):
        """Poll a JavaScript expression until it is truthy. -> its value, or the last falsy value."""
        end = time.time() + secs
        v = None
        while time.time() < end:
            try:
                v = self.js(expr)
            except Exception as e:                           # mid-navigation
                v = None
                self.last_error = e
            if v:
                return v
            time.sleep(0.25)
        return v

    def click(self, selector):
        return self.js(f"(function(){{var e=document.querySelector({json.dumps(selector)}); if(!e) return false; e.click(); return true;}})()")

    def key(self, key, code=13):
        for kind in ("keyDown", "keyUp"):
            self.cmd("Input.dispatchKeyEvent", type=kind, key=key, code=key, windowsVirtualKeyCode=code,
                     nativeVirtualKeyCode=code, text="\r" if key == "Enter" and kind == "keyDown" else "")

    def stop(self):
        try:
            self.ws.close()
        except Exception:
            pass
        self.proc.kill()
        time.sleep(0.5)
        shutil.rmtree(self.profile, ignore_errors=True)


VISIBLE = ("(function(s){var e=document.querySelector(s); if(!e) return false; var r=e.getBoundingClientRect(); "
           "var c=getComputedStyle(e); return r.width>0 && r.height>0 && c.visibility!=='hidden' && c.display!=='none';})")


def visible(selector):
    return f"{VISIBLE}({json.dumps(selector)})"
