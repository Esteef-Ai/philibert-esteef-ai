"""NeuralDock's own browser — a private, persistent Chrome it drives over CDP.

Why this exists, and why it is not run_shell + chrome:

  * It is SEPARATE from the user's Chrome. Its own --user-data-dir means it runs
    as its own instance and does not fight the 29 tabs the user already has open.
  * It STAYS LOGGED IN. The profile persists, so a site the user signs into once
    inside this browser (Gmail, Calendar, a dashboard) stays signed in for ND.
    This is the whole reason web_fetch is not enough — web_fetch has no session.
  * It is INVISIBLE by default. The window is parked off-screen, so work happens
    without anything moving on the user's screen. It can be brought on-screen, or
    streamed (see start_screencast), only when the user wants to watch.
  * It reads the DOM AS TEXT, over CDP, not pixels through a vision model. Faster,
    cheaper, and it cannot misread a letter.

The transport is the Chrome DevTools Protocol over a websocket. We attach to one
page target with flatten=true and address it by sessionId, so every call —
navigate, read, click, type, screenshot, screencast — rides the one connection.

This module knows nothing about NeuralDock's tools or tiers; the launcher wraps
it. That keeps it testable on its own and keeps the blast radius small.
"""
import json
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

try:
    from websockets.sync.client import connect as _ws_connect
except Exception:                       # pragma: no cover - surfaced by available()
    _ws_connect = None


_BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome(explicit=""):
    """Locate a Chromium-family binary: explicit path, then PATH, then the usual
    install locations. Same order as the design reviewer, on purpose."""
    if explicit and Path(explicit).exists():
        return explicit
    for name in ("chrome", "msedge", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    for c in _BROWSER_CANDIDATES:
        if Path(c).exists():
            return c
    return ""


def _free_port_is_taken(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


class NDBrowser:
    """One managed Chrome, driven over CDP. All public methods return a short
    string (or a dict for screenshots) meant to be handed straight to the model;
    none of them raise — a failure comes back as text the model can read."""

    def __init__(self, profile_dir, port=9333, chrome_path="", headless=False,
                 log=None):
        self.profile_dir = str(profile_dir)
        self.port = int(port)
        self.chrome_path = chrome_path or find_chrome()
        self.headless = bool(headless)
        self._log = log or (lambda *a, **k: None)
        self._proc = None
        self._ws = None
        self._session_id = None
        self._target_id = None
        self._msg_id = 0
        self._lock = threading.RLock()
        # Screencast state (used by start_screencast / latest_frame).
        self._cast = False
        self._frame = None            # (jpeg_b64, ts)
        self._reader = None
        self._reader_stop = False

    # ── lifecycle ────────────────────────────────────────────────────────────
    def available(self):
        if _ws_connect is None:
            return "the 'websockets' package is not installed in this environment"
        if not self.chrome_path:
            return "no Chrome or Edge was found to drive"
        return ""

    def _http_json(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=4) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def _launch(self):
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        args = [self.chrome_path,
                f"--remote-debugging-port={self.port}",
                f"--user-data-dir={self.profile_dir}",
                "--remote-allow-origins=*",
                "--no-first-run", "--no-default-browser-check",
                "--disable-features=Translate,OptimizationHints",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--window-size=1280,900"]
        if self.headless:
            args.append("--headless=new")
            args.append("--disable-gpu")
        else:
            # Off-screen, so nothing moves on the user's screen, but the window
            # is real — it renders, it can log in, and it can be brought forward
            # or streamed when the user wants to watch.
            args.append("--window-position=-32000,-32000")
        self._log(f"Launching managed browser on port {self.port} "
                  f"({'headless' if self.headless else 'off-screen'})", "info")
        self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
        # Wait for the debugger to answer.
        for _ in range(50):
            try:
                self._http_json("/json/version")
                return True
            except Exception:
                time.sleep(0.2)
        return False

    def _ensure_running(self):
        if not _free_port_is_taken(self.port):
            if not self._launch():
                return "the managed browser did not come up on its debug port"
        # (Re)connect the websocket and make sure we have a page target attached.
        if self._ws is None or self._session_id is None:
            return self._attach()
        return ""

    def _attach(self):
        try:
            ver = self._http_json("/json/version")
            burl = ver["webSocketDebuggerUrl"]
            self._ws = _ws_connect(burl, open_timeout=6, max_size=40 * 1024 * 1024)
        except Exception as e:
            self._ws = None
            return f"could not connect to the browser debugger: {e}"
        # Find an existing page target, or create one.
        try:
            targets = self._http_json("/json")
            page = next((t for t in targets if t.get("type") == "page"), None)
            if page:
                self._target_id = page["id"]
            else:
                r = self._send_browser("Target.createTarget", {"url": "about:blank"})
                self._target_id = r.get("targetId")
            r = self._send_browser("Target.attachToTarget",
                                    {"targetId": self._target_id, "flatten": True})
            self._session_id = r.get("sessionId")
        except Exception as e:
            return f"could not attach to a page: {e}"
        # Page + Runtime domains on, so navigation and evaluation work.
        for dom in ("Page.enable", "Runtime.enable", "DOM.enable"):
            try: self._send(dom, {})
            except Exception: pass
        return ""

    def close(self):
        self._reader_stop = True
        with self._lock:
            try:
                if self._ws: self._ws.close()
            except Exception: pass
            self._ws = self._session_id = None
            try:
                if self._proc: self._proc.terminate()
            except Exception: pass
            self._proc = None

    # ── CDP plumbing ─────────────────────────────────────────────────────────
    def _send_browser(self, method, params=None, timeout=20):
        return self._rpc(method, params, None, timeout)

    def _send(self, method, params=None, timeout=30):
        return self._rpc(method, params, self._session_id, timeout)

    def _rpc(self, method, params, session_id, timeout):
        """One request/response over the shared ws. Events and messages for other
        ids that arrive first are set aside (screencast frames are handled by the
        reader thread when one is running; here we just skip what is not ours)."""
        with self._lock:
            if self._ws is None:
                raise RuntimeError("no debugger connection")
            self._msg_id += 1
            mid = self._msg_id
            msg = {"id": mid, "method": method, "params": params or {}}
            if session_id:
                msg["sessionId"] = session_id
            self._ws.send(json.dumps(msg))
            deadline = time.time() + timeout
            while time.time() < deadline:
                remaining = max(0.1, deadline - time.time())
                try:
                    raw = self._ws.recv(timeout=remaining)
                except TimeoutError:
                    break
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                if data.get("id") == mid:
                    if "error" in data:
                        raise RuntimeError(str(data["error"].get("message", data["error"])))
                    return data.get("result", {}) or {}
                # Not our reply. If it is a screencast frame, stash it.
                if data.get("method") == "Page.screencastFrame":
                    self._take_frame(data.get("params", {}))
            raise TimeoutError(f"{method} timed out after {timeout}s")

    def _eval(self, expression, timeout=30):
        r = self._send("Runtime.evaluate",
                       {"expression": expression, "returnByValue": True,
                        "awaitPromise": True, "timeout": int(timeout * 1000)}, timeout)
        if r.get("exceptionDetails"):
            ex = r["exceptionDetails"]
            raise RuntimeError(ex.get("exception", {}).get("description")
                               or ex.get("text", "evaluation error"))
        return (r.get("result") or {}).get("value")

    # ── the actions the launcher exposes ──────────────────────────────────────
    def open(self, url):
        err = self._ensure_running()
        if err:
            return "[browser] " + err
        url = (url or "").strip()
        if url and not re.match(r"^[a-z]+://", url, re.I):
            url = "https://" + url
        try:
            self._send("Page.navigate", {"url": url})
            # Give the page a moment to settle, then read title/url.
            time.sleep(1.2)
            info = self._eval(
                "({t:document.title, u:location.href, "
                " login:/sign[- ]?in|log[- ]?in|accounts\\.google\\.com/i"
                "   .test(location.href+' '+document.title+' '+(document.body?document.body.innerText.slice(0,400):''))})")
            if not isinstance(info, dict):
                info = {}
            out = f"[browser] Opened {info.get('u', url)}\n  Title: {info.get('t') or '(none)'}"
            if info.get("login"):
                out += ("\n  This page looks like it needs a sign-in. NeuralDock's browser only "
                        "has sessions you have signed into inside it before. If you have not, ask "
                        "the user to sign in once (bring the window on-screen), then try again.")
            out += "\n  Use browser_read to read it, or browser_find to see what is clickable."
            return out
        except Exception as e:
            return f"[browser] Could not open that: {e}"

    def read(self, max_chars=8000):
        err = self._ensure_running()
        if err:
            return "[browser] " + err
        try:
            txt = self._eval(
                "(function(){var m=document.querySelector('main,article,[role=main]');"
                "var t=(m&&m.innerText&&m.innerText.length>200)?m.innerText:"
                "(document.body?document.body.innerText:'');return t||'';})()")
            txt = (txt or "").strip()
            if not txt:
                return "[browser] The page has no readable text yet (still loading, or blank)."
            clipped = len(txt) > max_chars
            return ("[browser] " + txt[:max_chars]
                    + ("\n[… page text truncated]" if clipped else ""))
        except Exception as e:
            return f"[browser] Could not read the page: {e}"

    def find(self, query=""):
        err = self._ensure_running()
        if err:
            return "[browser] " + err
        q = (query or "").strip().lower().replace("'", " ")
        try:
            js = ("(function(){var q='" + q + "';"
                  "var els=[].slice.call(document.querySelectorAll("
                  "'a,button,input,textarea,select,[role=button],[role=link],[role=tab]'));"
                  "var out=[];var n=0;"
                  "for(var i=0;i<els.length;i++){var e=els[i];"
                  "var r=e.getBoundingClientRect();if(r.width<2||r.height<2)continue;"
                  "var lbl=(e.innerText||e.value||e.placeholder||e.getAttribute('aria-label')||e.name||'').trim().replace(/\\s+/g,' ').slice(0,80);"
                  "if(!lbl)continue;"
                  "if(q&&lbl.toLowerCase().indexOf(q)<0)continue;"
                  "n++;e.setAttribute('data-nd-ref','r'+n);"
                  "out.push('r'+n+'  ['+e.tagName.toLowerCase()+(e.type?(':'+e.type):'')+']  '+lbl);"
                  "if(n>=40)break;}"
                  "return out.join('\\n')||'(nothing matched)';})()")
            res = self._eval(js)
            return ("[browser] Elements you can act on (ref · kind · label):\n" + (res or "(none)")
                    + "\n  Click one with browser_click ref='rN', or type into one with browser_type.")
        except Exception as e:
            return f"[browser] Could not scan the page: {e}"

    def click(self, ref="", text=""):
        err = self._ensure_running()
        if err:
            return "[browser] " + err
        ref = (ref or "").strip()
        text = (text or "").strip()
        try:
            if ref:
                ref_js = ref.replace("'", "")
                ok = self._eval(
                    "(function(){var e=document.querySelector(\"[data-nd-ref='" + ref_js + "']\");"
                    "if(!e)return false;e.scrollIntoView({block:'center'});e.click();return true;})()")
                what = "ref " + ref
            else:
                t = text.replace("\\", " ").replace('"', " ")
                ok = self._eval(
                    '(function(){var t="' + t + '".toLowerCase();'
                    "var els=[].slice.call(document.querySelectorAll('a,button,[role=button],[role=link],input[type=submit]'));"
                    "for(var i=0;i<els.length;i++){var e=els[i];"
                    "var lbl=(e.innerText||e.value||e.getAttribute('aria-label')||'').trim().toLowerCase();"
                    "if(lbl&&lbl.indexOf(t)>=0){e.scrollIntoView({block:'center'});e.click();return true;}}"
                    "return false;})()")
                what = "text '" + text + "'"
            if not ok:
                return f"[browser] Nothing matched {what}. Run browser_find first to see the real refs."
            time.sleep(0.8)
            return f"[browser] Clicked {what}. Use browser_read to see what changed."
        except Exception as e:
            return f"[browser] Could not click: {e}"

    def type(self, text="", ref="", selector="", enter=False):
        err = self._ensure_running()
        if err:
            return "[browser] " + err
        text = text or ""
        sel = ""
        if ref:
            sel = "[data-nd-ref='" + ref.strip().replace("'", "") + "']"
        elif selector:
            sel = selector
        try:
            if sel:
                sel_js = sel.replace("\\", "\\\\").replace("'", "\\'")
                val_js = json.dumps(text)
                ok = self._eval(
                    "(function(){var e=document.querySelector('" + sel_js + "');if(!e)return false;"
                    "e.focus();var set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value');"
                    "try{if(set&&set.set){set.set.call(e," + val_js + ");}else{e.value=" + val_js + ";}}catch(x){e.value=" + val_js + ";}"
                    "e.dispatchEvent(new Event('input',{bubbles:true}));"
                    "e.dispatchEvent(new Event('change',{bubbles:true}));return true;})()")
                if not ok:
                    return "[browser] No input matched that ref/selector. Run browser_find first."
            else:
                # No target: type into whatever is focused, via real key events.
                self._send("Input.insertText", {"text": text})
            if enter:
                for t in ("keyDown", "keyUp"):
                    self._send("Input.dispatchKeyEvent",
                               {"type": t, "key": "Enter", "code": "Enter",
                                "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13})
                time.sleep(0.8)
            return f"[browser] Typed {len(text)} char(s)" + (" and pressed Enter." if enter else ".")
        except Exception as e:
            return f"[browser] Could not type: {e}"

    def screenshot(self, max_width=1280):
        err = self._ensure_running()
        if err:
            return {"error": err}
        try:
            r = self._send("Page.captureScreenshot",
                           {"format": "jpeg", "quality": 65, "captureBeyondViewport": False})
            return {"image_b64": r.get("data", ""), "mime": "image/jpeg"}
        except Exception as e:
            return {"error": str(e)}

    def set_visible(self, on=True):
        """Bring the off-screen window on-screen (or send it back). Used when the
        user actually wants to watch, or needs to sign in."""
        err = self._ensure_running()
        if err:
            return "[browser] " + err
        try:
            wr = self._send_browser("Browser.getWindowForTarget", {"targetId": self._target_id})
            wid = wr.get("windowId")
            bounds = ({"left": 80, "top": 60, "width": 1280, "height": 900,
                       "windowState": "normal"} if on
                      else {"left": -32000, "top": -32000, "windowState": "normal"})
            self._send_browser("Browser.setWindowBounds", {"windowId": wid, "bounds": bounds})
            return "[browser] Window is now " + ("on-screen." if on else "hidden off-screen.")
        except Exception as e:
            return f"[browser] Could not move the window: {e}"

    # ── screencast (used by the launcher's /api/browser_frame) ────────────────
    def _take_frame(self, params):
        data = params.get("data")
        sid = params.get("sessionId")
        if data:
            self._frame = (data, time.time())
        if sid is not None:
            try:
                self._send("Page.screencastFrameAck", {"sessionId": sid}, timeout=5)
            except Exception:
                pass

    def start_screencast(self, every_nth=1, quality=55, max_width=900):
        err = self._ensure_running()
        if err:
            return "[browser] " + err
        if self._cast:
            return "[browser] Already streaming."
        try:
            self._send("Page.startScreencast",
                       {"format": "jpeg", "quality": int(quality),
                        "maxWidth": int(max_width), "everyNthFrame": int(every_nth)})
            self._cast = True
            self._reader_stop = False
            self._reader = threading.Thread(target=self._drain, daemon=True)
            self._reader.start()
            return "[browser] Streaming started."
        except Exception as e:
            return f"[browser] Could not start the stream: {e}"

    def stop_screencast(self):
        if not self._cast:
            return "[browser] Not streaming."
        self._reader_stop = True
        try:
            self._send("Page.stopScreencast", {})
        except Exception:
            pass
        self._cast = False
        return "[browser] Streaming stopped."

    def _drain(self):
        """While streaming, the frames arrive as unsolicited events. Read them off
        the ws so they do not pile up in front of a real reply."""
        while self._cast and not self._reader_stop:
            with self._lock:
                if self._ws is None:
                    break
                try:
                    raw = self._ws.recv(timeout=0.5)
                except TimeoutError:
                    continue
                except Exception:
                    break
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                if data.get("method") == "Page.screencastFrame":
                    self._take_frame(data.get("params", {}))

    def latest_frame(self):
        return self._frame
