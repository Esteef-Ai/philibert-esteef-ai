"""A headless Edge for the repo's page tests: no window, real mouse and key events over its debugging port."""
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Edge:
    def __init__(self):
        import websocket
        self.profile = tempfile.mkdtemp(prefix="desk_edge_")
        port = free_port()
        self.proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={self.profile}",
                                      "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--disable-extensions",
                                      "--disable-sync", "--disable-default-apps", "--disable-background-networking",
                                      "--window-size=1280,720", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        page, end = None, time.time() + 30
        while time.time() < end and page is None:
            try:
                ts = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5).read())
                page = next(t for t in ts if t["type"] == "page")
            except Exception:
                time.sleep(0.25)
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30, suppress_origin=True)
        self.n, self.errors = 0, []
        for m in ("Page.enable", "Runtime.enable"):
            self.cmd(m)
        self.cmd("Emulation.setDeviceMetricsOverride", width=1280, height=720, deviceScaleFactor=1, mobile=False)

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

    def wait(self, expr, secs=10):
        end, v = time.time() + secs, None
        while time.time() < end:
            v = self.js(expr)
            if v:
                return v
            time.sleep(0.2)
        return v

    def mouse(self, kind, x, y, button="none", buttons=0, mods=0):
        self.cmd("Input.dispatchMouseEvent", type=kind, x=x, y=y, button=button, buttons=buttons, clickCount=1, modifiers=mods)

    def drag(self, a, b, button="left", steps=8):
        bits = 1 if button == "left" else 2
        self.mouse("mouseMoved", *a)
        self.mouse("mousePressed", *a, button=button, buttons=bits)
        for i in range(1, steps + 1):
            self.mouse("mouseMoved", a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps, button=button, buttons=bits)
            time.sleep(0.02)
        self.mouse("mouseReleased", *b, button=button, buttons=0)
        time.sleep(0.4)

    def click(self, x, y, button="left", mods=0):
        bits = 1 if button == "left" else 2
        self.mouse("mouseMoved", x, y)
        self.mouse("mousePressed", x, y, button=button, buttons=bits, mods=mods)
        self.mouse("mouseReleased", x, y, button=button, buttons=0, mods=mods)
        time.sleep(0.3)

    def key(self, key, code):
        for kind in ("keyDown", "keyUp"):
            self.cmd("Input.dispatchKeyEvent", type=kind, key=key, code=key, windowsVirtualKeyCode=code, nativeVirtualKeyCode=code)
        time.sleep(0.3)

    def stop(self):
        try:
            self.ws.close()
        except Exception:
            pass
        self.proc.kill()
        time.sleep(0.5)
        shutil.rmtree(self.profile, ignore_errors=True)
