"""Feedback Shooter replies (shared/nd_feedback_replies.py, shared/feedback_replies.js, dev/patching.py FEEDBACK_REPLIES).

A fake GitHub and a fake feedback relay on one local port stand in for the real ones; nothing goes on the
Internet. First the backend: the relay's reply key is kept, only the maker's comments count, GitHub is not
asked again within 20 minutes, seen/answer/offline/closed. Then a headless Edge (no window): the thread
under a message in Feedback Shooter, answering from it, and the desktop's pop-up and badge.

    python dev/test_feedback_replies.py
"""
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"
STATIC = APP / "live" / "static"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))
fake_np = types.ModuleType("nd_philibert")              # nd_feedback asks this for the repo and the GitHub sign-in
fake_np._GH = {"token": "", "user": ""}
fake_np._repo = lambda: ("o/r", "main")
fake_np.version = lambda: "test"
fake_np.gpu_gb = lambda: 0
sys.modules["nd_philibert"] = fake_np
import nd_feedback as fb  # noqa: E402
import nd_feedback_replies as fr  # noqa: E402
import nd_retro_desktop as rd  # noqa: E402
from _edge import Edge  # noqa: E402

results = []


def check(label, ok, got=""):
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f" - got {got!r}"[:400]))


class Fake:
    issues, hits, posted = {}, [], []


class GH(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")

    def do_GET(self):
        Fake.hits.append(self.path)
        parts = self.path.split("?")[0].strip("/").split("/")      # repos o r issues N [comments]
        n = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        it = Fake.issues.get(n)
        if not it:
            return self.send(404, {"message": "Not Found"})
        if len(parts) == 6:
            return self.send(200, it["comments"])
        return self.send(200, {"number": n, "state": it["state"], "comments": len(it["comments"])})

    def do_POST(self):
        d = self.body()
        Fake.posted.append((self.path, dict(self.headers), d))
        if self.path == "/send":
            n = len(Fake.issues) + 1
            Fake.issues[n] = {"state": "open", "comments": [], "title": d.get("title")}
            return self.send(201, {"number": n, "url": f"https://github.com/o/r/issues/{n}", "key": f"K{n}"})
        if self.path == "/reply":
            n = int(d.get("number") or 0)
            if d.get("key") != f"K{n}":
                return self.send(403, {"error": "wrong key"})
            c = {"id": 9000 + len(Fake.posted), "author_association": "OWNER", "user": {"login": "maker"},   # the relay posts as the maker
                 "body": "**The sender answered** (from Philibert, through the feedback relay):\n\n" + d["message"],
                 "created_at": "2026-11-25T10:00:00Z"}
            Fake.issues[n]["comments"].append(c)
            return self.send(201, {"id": c["id"]})
        parts = self.path.strip("/").split("/")
        if len(parts) == 6 and parts[5] == "comments":           # signed in: under the person's own name
            c = {"id": 8000 + len(Fake.posted), "author_association": "NONE", "user": {"login": "someone"}, "body": d["body"],
                 "created_at": "2026-11-25T11:00:00Z"}
            Fake.issues[int(parts[4])]["comments"].append(c)
            return self.send(201, c)
        self.send(404, {})


gh = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GH)
threading.Thread(target=gh.serve_forever, daemon=True).start()
FAKE = f"http://127.0.0.1:{gh.server_port}"
fb.API = FAKE
fb._relay_url = lambda: FAKE + "/send"


def comment(n, who, assoc, body, cid):
    Fake.issues[n]["comments"].append({"id": cid, "author_association": assoc, "user": {"login": who}, "body": body,
                                       "created_at": "2026-11-25T09:00:00Z"})


def item(data, iid):
    return next(i for i in fb._items(data) if i["id"] == iid)


drive = Path(tempfile.mkdtemp(prefix="fb_replies_"))
data = drive / "data"
data.mkdir()
try:
    # ---------------- the backend ----------------
    r = fb.handle({"op": "save", "kind": "idea", "part": "Desktop", "title": "Pin chats", "message": "Let me pin chats.",
                   "include_system": False}, data, True)
    one = r["item"]
    check("a message sent through the relay keeps the relay's reply key", one.get("status") == "sent" and one.get("reply_key") == "K1", one)
    r = fr.check(data, True, force=True)
    check("no replies yet: nothing unread, nothing new", r["unread"] == 0 and r["new"] == [], r)

    comment(1, "maker", "OWNER", "Good idea - coming in the next update.", 501)
    comment(1, "random", "NONE", "spam spam https://bad.example", 502)
    r = fr.check(data, True, force=True)
    check("the maker's reply is new and unread; a stranger's comment is not counted", r["unread"] == 1 and len(r["new"]) == 1
          and r["new"][0]["by"] == "maker" and r["new"][0]["title"] == "Pin chats", r)
    th = item(data, one["id"]).get("thread", [])
    check("... and only the maker's reply is in the thread", [c["id"] for c in th] == [501], th)
    before = len(Fake.hits)
    r = fr.check(data, True)
    check("asked again within 20 minutes: GitHub is not asked, the reply is not announced twice",
          len(Fake.hits) == before and r["new"] == [] and r["unread"] == 1, (len(Fake.hits) - before, r))
    r = fr.check(data, False, force=True)
    check("Internet off: GitHub is not asked, the unread count still comes back", len(Fake.hits) == before and r["unread"] == 1, r)
    fb.handle({"op": "seen", "id": one["id"]}, data, True)
    check("seen: nothing unread", fr.check(data, True)["unread"] == 0)

    r = fb.handle({"op": "answer", "id": one["id"], "message": "Thanks! Also folders?"}, data, True)
    check("answering without a GitHub account goes through the relay with the key", r.get("ok") and
          Fake.posted[-1][0] == "/reply" and Fake.posted[-1][2].get("key") == "K1", (r, Fake.posted[-1][0]))
    r = fr.check(data, True, force=True)
    th = item(data, one["id"])["thread"]
    check("the person's own answer is in the thread as theirs, not as a maker reply", [c.get("mine", False) for c in th] == [False, True]
          and r["unread"] == 0 and r["new"] == [], (th, r))
    r = fb.handle({"op": "answer", "id": one["id"], "message": "   "}, data, True)
    check("an empty answer is refused", not r["ok"], r)
    r = fb.handle({"op": "answer", "id": one["id"], "message": "x"}, data, False)
    check("an answer with the Internet off says so", not r["ok"] and r.get("offline"), r)

    old = dict(item(data, one["id"]))
    old.update(id="old-1", reply_key="", number=1)
    fb._write(data, old)
    r = fb.handle({"op": "answer", "id": "old-1", "message": "hello"}, data, True)
    check("a message from before answers existed (no key): asks to sign in to GitHub", not r["ok"] and r.get("need_signin"), r)
    (fb._dir(data) / "old-1.json").unlink()
    fake_np._GH.update(token="tok-person", user="someone")
    r = fb.handle({"op": "answer", "id": one["id"], "message": "Signed in now."}, data, True)
    last = Fake.posted[-1]
    check("signed in: the answer goes to GitHub under their name", r.get("ok") and last[0] == "/repos/o/r/issues/1/comments"
          and last[1].get("Authorization") == "Bearer tok-person", (r, last[0]))
    fake_np._GH.update(token="", user="")
    r = fr.check(data, True, force=True)
    check("... and is not mistaken for a maker reply", r["unread"] == 0, r)

    Fake.issues[1]["state"] = "closed"
    comment(1, "maker", "OWNER", "Done in 1.4 - closing.", 503)
    r = fr.check(data, True, force=True)
    check("the maker's closing reply is still read", r["unread"] == 1 and item(data, one["id"]).get("final"), r)
    before = len(Fake.hits)
    fr.check(data, True, force=True)
    check("a closed issue is not asked about again", len(Fake.hits) == before, Fake.hits[before:])
    fb.handle({"op": "seen", "id": one["id"]}, data, True)

    # ---------------- the pages ----------------
    rd.save_settings(data, {"theme": "win95", "boot": False, "sounds": False, "screensaver": False})
    r = fb.handle({"op": "save", "kind": "bug", "part": "Desktop", "title": "Icons jump", "message": "They jump.",
                   "include_system": False}, data, True)
    two = r["item"]
    comment(2, "maker", "OWNER", "Which theme? See https://github.com/o/r/issues/2 for more.", 601)

    class Pages(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def out(self, code, b, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/feedback":
                path = "/live/feedback.html"
            if path.startswith("/live/"):
                f = (STATIC / path[len("/live/"):]).resolve()
                if f.is_file() and STATIC.resolve() in f.parents:
                    types_ = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml"}
                    return self.out(200, f.read_bytes(), types_.get(f.suffix, "application/octet-stream"))
            self.out(404, b"", "text/plain")

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if self.path == "/api/feedback":
                res = fb.handle(body, data, True)
            elif self.path == "/api/desktop":
                res = rd.handle(body, data, drive / "Apps")
            else:
                res = {"ok": True}
            self.out(200, json.dumps(res).encode(), "application/json")

    pg = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Pages)
    threading.Thread(target=pg.serve_forever, daemon=True).start()
    URL = f"http://127.0.0.1:{pg.server_port}"
    br = Edge()
    try:
        br.cmd("Page.navigate", url=URL + "/feedback")
        ok = br.wait("document.querySelectorAll('.thread .reply.maker').length >= 1", 15)
        check("Feedback Shooter shows the maker's reply under the message", ok, br.js("document.getElementById('list').innerText"))
        txt = br.js("document.getElementById('list').innerText") or ""
        check("... marked NEW, with a link made clickable, and no stranger's comment",
              "NEW" in txt and br.js("!!document.querySelector('.reply.maker a[href=\"https://github.com/o/r/issues/2\"]')")
              and "spam" not in txt, txt[:300])
        br.wait("false", 1.5)
        check("showing it marks it seen", fr.check(data, True)["unread"] == 0, item(data, two["id"]).get("seen"))
        br.js("document.querySelector('[data-answer-text=\"%s\"]').value = 'Windows 95, after a restart.'" % two["id"])
        br.js("document.querySelector('[data-answer=\"%s\"]').click()" % two["id"])
        ok = br.wait("[].some.call(document.querySelectorAll('.thread .reply.mine .body'), function (e) {"
                     " return e.textContent === 'Windows 95, after a restart.'; })", 8)
        check("answering from the page: the answer shows as 'You' and went through the relay",
              ok and "Windows 95, after a restart." in (br.js("document.getElementById('list').innerText") or "")
              and Fake.posted[-1][0] == "/reply", (ok, br.js("document.getElementById('list').innerHTML")[-900:]))
        check("the page raised no JavaScript errors", not br.errors, br.errors[:3])
        if os.environ.get("FEEDBACK_SHOT"):              # a picture of the thread, to look at by eye
            import base64
            br.js("document.querySelector('.thread').scrollIntoView()")
            png = br.cmd("Page.captureScreenshot", format="png")["data"]
            Path(os.environ["FEEDBACK_SHOT"]).write_bytes(base64.b64decode(png))

        comment(2, "maker", "OWNER", "Fixed, thanks!", 602)
        s = fr._state(data)
        s["fetched"] = 0                                   # as if 20 minutes had passed
        fr._save_state(data, s)
        br.cmd("Page.navigate", url=URL + "/live/desktop.html")
        ok = br.wait("(document.querySelector('.notify')||{}).innerText", 20)
        check("the desktop pops up the new reply", ok and "maker replied to" in ok and "Icons jump" in ok, ok)
        check("... and the Feedback Shooter icon has a badge of 1",
              br.js("(document.querySelector('[data-id=\"feedback\"] .img .badge')||{}).textContent") == "1",
              br.js("(document.querySelector('[data-id=\"feedback\"] .img .badge')||{}).textContent"))
        br.js("document.querySelector('.notify').click()")
        ok = br.wait("!!document.querySelector('.win[data-id=\"feedback\"]')", 5)
        check("clicking the pop-up opens Feedback Shooter", ok)
        ok = br.wait("!document.querySelector('[data-id=\"feedback\"] .img .badge')", 10)
        check("once the replies are shown, the badge goes", ok)
        check("the desktop raised no JavaScript errors", not br.errors, br.errors[:3])
    finally:
        br.stop()
        pg.shutdown()
finally:
    gh.shutdown()
    shutil.rmtree(drive, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
