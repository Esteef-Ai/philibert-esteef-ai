"""Helpers for the Fire TV app's tests (do not edit).

Two kinds of check:
  - always:      the app builds (build_apk.py), and what is IN the APK and the source is right.
  - (on the TV): the app is installed on a real Fire TV and driven with real remote keys. These run only when the
                 environment variable LP_DEVICE names a TV that adb can reach (e.g. 192.168.0.48:5555); otherwise
                 they are printed as SKIP and do not count. They use a TEST copy of the app
                 (ai.esteef.lacklusterplus.test) installed beside the real one, so the real one's sign-in and
                 address are never touched, and they remove it when done.
The TV reaches the test's stand-in page through adb's reverse tunnel (the TV's own 127.0.0.1:<port>), so nothing
on the network or the firewall is involved.
"""
import http.server
import importlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
JAVA = WS / "app" / "src" / "ai" / "esteef" / "lacklusterplus" / "MainActivity.java"
SDK = Path(os.environ.get("ANDROID_SDK_ROOT") or Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk")
AAPT2 = SDK / "build-tools" / "36.0.0" / "aapt2.exe"
ADB = SDK / "platform-tools" / "adb.exe"
DEVICE = os.environ.get("LP_DEVICE", "").strip()
PKG = "ai.esteef.lacklusterplus"
TEST_PKG = PKG + ".test"
_results = []
_skipped = 0
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def check(label, ok, got=""):
    _results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + label + ("" if ok or got == "" else f" - got {str(got)[:300]}"), flush=True)
    return bool(ok)


def skip(label):
    global _skipped
    _skipped += 1
    print("SKIP (on the TV) " + label, flush=True)


def finish():
    if _skipped:
        print(f"({_skipped} checks need a real Fire TV and were skipped: set LP_DEVICE=<ip>:5555 to run them)")
    p, f = sum(_results), len(_results) - sum(_results)
    print(f"{p} passed, {f} failed")
    sys.exit(1 if f or not p else 0)


def build(test_id=False):
    """Build the app with the project's own build_apk.py. -> (apk path or None, the build's error text)."""
    sys.path.insert(0, str(WS))
    try:
        mod = importlib.import_module("build_apk")
        return mod.build(test_id=test_id, quiet=True), ""
    except Exception as e:                                    # BuildError carries the compiler's own words
        return None, str(e)[-1500:]


def tool(*cmd, timeout=120):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")


def badging(apk):
    """What a TV reads from the APK: its id, name, icon, launcher entries, permissions, features."""
    return tool(AAPT2, "dump", "badging", apk)


def manifest(apk):
    return tool(AAPT2, "dump", "xmltree", apk, "--file", "AndroidManifest.xml")


def source():
    return JAVA.read_text(encoding="utf-8") if JAVA.is_file() else ""


def code_only(src):
    """Java without its comments (a name in a comment is not the name in use). Strings are kept whole."""
    src = re.sub(r"/[*].*?[*]/", "", src, flags=re.S)
    return re.sub(r'"(?:[^"\\\n]|\\.)*"|//[^\n]*', lambda m: m.group(0) if m.group(0).startswith('"') else "", src)


# ── the TV ───────────────────────────────────────────────────────────────────

class Tv:
    """A real Fire TV over adb. Every call names the device, so nothing else that is plugged in is touched."""

    def __init__(self, serial=DEVICE):
        self.serial = serial

    def adb(self, *args, timeout=60):
        return tool(ADB, "-s", self.serial, *args, timeout=timeout)

    def sh(self, cmd, timeout=60):
        return self.adb("shell", cmd, timeout=timeout)

    def ready(self):
        if not self.serial:
            return False
        if ":" in self.serial:
            tool(ADB, "connect", self.serial, timeout=20)
        return self.adb("get-state", timeout=15).strip() == "device"

    def install(self, apk):
        return self.adb("install", "-r", str(apk), timeout=180)

    def fresh(self):
        self.sh(f"pm clear {TEST_PKG}")                       # the TEST copy only

    def start(self):
        self.sh(f"am start -n {TEST_PKG}/{PKG}.MainActivity")
        time.sleep(3)

    def stop(self):
        self.sh(f"am force-stop {TEST_PKG}")

    def focus(self):
        """The package that has the screen."""
        m = re.search(r"mCurrentFocus=Window\{\S+ \S+ ([\w.]+)/", self.sh("dumpsys window | grep mCurrentFocus"))
        return m.group(1) if m else ""

    def key(self, *codes, pause=0.5):
        for c in codes:
            self.sh(f"input keyevent {c}")
            time.sleep(pause)

    def type(self, text):
        self.sh("input text " + text.replace(" ", "%s"))
        time.sleep(0.5)

    def ui(self):
        """The native screen as XML (every view's text, class and whether it has the highlight)."""
        self.sh("uiautomator dump /sdcard/lp_ui.xml")
        x = self.sh("cat /sdcard/lp_ui.xml")
        self.sh("rm -f /sdcard/lp_ui.xml")
        return x

    def nodes(self):
        return [dict(re.findall(r'([\w-]+)="([^"]*)"', n)) for n in re.findall(r"<node [^>]*>", self.ui())]

    def reverse(self, port):
        return self.adb("reverse", f"tcp:{port}", f"tcp:{port}")

    def clean_up(self, port=None):
        self.stop()
        self.adb("uninstall", TEST_PKG)
        if port:
            self.adb("reverse", "--remove", f"tcp:{port}")


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>stand-in</title></head><body style="background:#0A0C10;color:#F4F5F9;font:24px sans-serif">
<h1 id="h">Lackluster Plus+ stand-in</h1><button id="b1">one</button><button id="b2">two</button>
<script>
var backs = 0;
function say(o){ var q = []; for(var k in o) q.push(encodeURIComponent(k) + '=' + encodeURIComponent(o[k])); (new Image()).src = '/e?' + q.join('&') + '&r=' + Math.random(); }
window.tvBack = function(){ backs++; say({t: 'back', n: backs}); return backs <= 1; };   // something to close once, then nothing
document.addEventListener('keydown', function(e){ say({t: 'key', key: e.key}); });
say({t: 'load', ua: navigator.userAgent, w: window.innerWidth, h: window.innerHeight});
</script></body></html>"""


class Page:
    """A stand-in for the Lackluster page on this PC. It records what the app does to it: every load (with the user
    agent and the page's width), every key the page receives, every call of window.tvBack()."""

    def __init__(self):
        self.events = []
        page = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                if u.path == "/e":
                    page.events.append({k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()})
                    body, kind = b"", "image/gif"
                else:
                    body, kind = PAGE.encode(), "text/html; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def wait(self, want, secs=15, after=0):
        """The first event from index `after` on that `want` (a function) accepts, or None after `secs`."""
        end = time.time() + secs
        while time.time() < end:
            for e in self.events[after:]:
                if want(e):
                    return e
            time.sleep(0.2)
        return None

    def count(self, kind):
        return len([e for e in self.events if e.get("t") == kind])

    def stop(self):
        self.srv.shutdown()


def dump(obj):
    return json.dumps(obj, ensure_ascii=False)[:300]
