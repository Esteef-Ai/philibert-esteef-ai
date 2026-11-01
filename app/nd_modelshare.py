"""Model sharing between one person's computers, over Tailscale.

A laptop too small for a good model (the case that started this, 2026-10-31: Intel HD 520
graphics and 8 GB of RAM) can use the models on the same person's bigger computer at home:

  the big computer  "Share my models" - a small relay listens on this computer's
                    Tailscale address only (100.x.y.z, never the local network or the
                    internet), port 11500, and passes requests on to its own Ollama.
                    The address it gives out carries a secret key:
                        http://100.101.102.103:11500/k-3f9a.../
                    Without the key every request is refused, and with it only running
                    and listing models is allowed: never downloading, deleting or
                    changing them.
  the small one     "Use models from my other computer" - paste that address. While it
                    answers, the chat, Yo Teach and the rest use the big computer's models;
                    when it does not (the big one is off, no Tailscale), they use this
                    computer's own models again, by themselves. Checked every 30 s.

Notes and app data (nd_sync) ride on the same address when the big computer also turns on
"Share my notes and app data": /<key>/sync/<step> goes to Share.sync instead of Ollama.
Pictures (nd_imagegen) come with the models: /<key>/images/<step> goes to Share.images.

Stdlib + psutil (already in Philibert). Tailscale itself is installed by the person.
"""
import http.client
import ipaddress
import json
import secrets
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 11500
SYNC_MAX = 64 * 1024 * 1024                    # one sync request (a 20 MB file, base64)
TAILNET = ipaddress.ip_network("100.64.0.0/10")
ALLOWED = {"/api/chat", "/api/generate", "/api/tags", "/api/show", "/api/embed", "/api/embeddings",
           "/api/ps", "/api/version"}


def tailscale_ip():
    """This computer's Tailscale IPv4 address, or ""."""
    try:
        import psutil
        import socket
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET:
                    try:
                        if ipaddress.ip_address(a.address) in TAILNET:
                            return a.address
                    except ValueError:
                        continue
    except Exception:
        pass
    return ""


def new_key():
    return "k-" + secrets.token_hex(12)


class _Relay(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    local = ""                                  # the local Ollama, set on the class by start()
    key = ""
    owner = None                                # the Share: .sync answers /sync/, .images /images/ (None = refused)

    def log_message(self, *a):
        pass

    def _refuse(self, code=404):
        # the request body was not read: close, so its bytes are not taken for the next request
        self.close_connection = True
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def _route(self):
        parts = urllib.parse.urlparse(self.path).path.split("/", 2)       # "", key, rest
        if len(parts) < 3 or not secrets.compare_digest(parts[1], self.key):
            return None
        path = "/" + parts[2]
        return path if path in ALLOWED or path.startswith(("/sync/", "/images/")) else None

    def _forward(self, method):
        try:
            if ipaddress.ip_address(self.client_address[0]) not in TAILNET:
                return self._refuse(403)        # only the person's own devices, over Tailscale
        except ValueError:
            return self._refuse(403)
        path = self._route()
        if not path:
            return self._refuse(404)
        n = int(self.headers.get("Content-Length") or 0)
        if n > SYNC_MAX:
            return self._refuse(413)
        body = self.rfile.read(n) if n else None
        if path.startswith("/sync/"):
            return self._sync(path[6:], body, "sync")
        if path.startswith("/images/"):
            return self._sync(path[8:], body, "images")
        u = urllib.parse.urlparse(self.local)
        conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=1800)
        try:
            conn.request(method, path, body=body, headers={"Content-Type": self.headers.get("Content-Type") or "application/json"})
            r = conn.getresponse()
            self.send_response(r.status)
            self.send_header("Content-Type", r.getheader("Content-Type") or "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:                          # streamed replies stay streamed
                chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
                if not chunk:
                    break
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
        except (OSError, http.client.HTTPException):
            try:
                self._refuse(502)
            except OSError:
                pass
        finally:
            conn.close()

    def _sync(self, step, body, what):
        fn = getattr(self.owner, what, None) if self.owner else None
        if not fn or method_not_post(self.command):
            return self._refuse(404)
        try:
            out = fn(step, json.loads(body.decode()) if body else {})
        except Exception as e:                  # the laptop shows why, and tries again later
            out = {"ok": False, "msg": f"{type(e).__name__}: {e}"}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._forward("GET")

    def do_POST(self):
        self._forward("POST")

    def do_HEAD(self):
        self._refuse(405)


def method_not_post(m):
    return m != "POST"


class Share:
    """The relay on the big computer. sync / images = fn(step, body) -> dict to also serve
    nd_sync and nd_imagegen."""

    def __init__(self):
        self.srv = None
        self.ip = ""
        self.sync = None
        self.images = None

    def start(self, local_url, key, port=PORT):
        self.stop()
        ip = tailscale_ip()
        if not ip:
            return {"ok": False, "msg": "Tailscale is not running on this computer, so there is nothing to share over. "
                                        "Install Tailscale, sign in, and try again."}
        handler = type("Relay", (_Relay,), {"local": local_url.rstrip("/"), "key": key, "owner": self})
        try:
            self.srv = ThreadingHTTPServer((ip, port), handler)
        except OSError as e:
            return {"ok": False, "msg": f"Could not listen on {ip}:{port} ({e})."}
        self.srv.daemon_threads = True
        self.ip = ip
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return {"ok": True, "address": self.address(key)}

    def address(self, key):
        return f"http://{self.ip}:{PORT}/{key}" if self.ip else ""

    def stop(self):
        if self.srv:
            try:
                self.srv.shutdown()
                self.srv.server_close()
            except Exception:
                pass
        self.srv, self.ip = None, ""

    @property
    def on(self):
        return self.srv is not None


def clean_address(raw):
    """What the person pasted -> http://100.x.y.z:11500/k-..., or "" if it is not one."""
    s = str(raw or "").strip().rstrip("/")
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    u = urllib.parse.urlparse(s)
    key = u.path.strip("/").split("/")[0]
    if u.scheme != "http" or not u.hostname or not key.startswith("k-"):
        return ""
    return f"http://{u.hostname}:{u.port or PORT}/{key}"


def probe(address, timeout=3.0):
    """The models the other computer offers, or None when it does not answer."""
    try:
        with urllib.request.urlopen(address.rstrip("/") + "/api/tags", timeout=timeout) as r:
            return [m.get("name") for m in json.loads(r.read().decode()).get("models", [])]
    except Exception:
        return None
