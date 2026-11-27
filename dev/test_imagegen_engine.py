"""The picture engine and the phone help (shared/nd_imagegen_engine.py, shared/images_engine.js, shared/nd_phone_help.py,
dev/patching.py IMAGEGEN_ENGINE and PHONE_HELP).

A fake ComfyUI on a local port stands in for the real one (no models, no graphics card): its 400 answers are read
out, one picture at a time, STOP ends a waiting picture and clears the queue, UNLOAD, TURN OFF never stops a process
that is not the drive's own engine. Then the relay (nd_modelshare) on 127.0.0.1: a browser gets a page saying why,
a program still gets the plain refusal. Then a headless Edge (no window): the ENGINE button and its panel, STOP,
the fixed seed not remembered, a second window's settings taken up, the chosen style sent; the Models panel's
phone checklist.

    python dev/test_imagegen_engine.py
"""
import http.server
import ipaddress
import json
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"
STATIC = APP / "live" / "static"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import nd_imagegen as ig  # noqa: E402
import nd_imagegen_engine as eng  # noqa: E402
import nd_modelshare as ms  # noqa: E402
from _edge import Edge  # noqa: E402

results = []


def check(label, ok, got=""):
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f" - got {got!r}"[:400]))


class Fake:
    mode, prompts, posts, hold, interrupted, pending, n = "ok", [], [], False, False, 0, 0


BAD = {"error": {"type": "prompt_outputs_failed_validation", "message": "Prompt outputs failed validation",
                 "details": "", "extra_info": {}},
       "node_errors": {"4": {"errors": [{"type": "value_not_in_list", "message": "Value not in list",
                                         "details": "ckpt_name: 'juggernaut.safetensors' not in ['sdxl.safetensors']"}],
                             "class_type": "CheckpointLoaderSimple"}}}


class Comfy(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/system_stats":
            return self.send(200, {"devices": [{"name": "Test card", "vram_total": 16e9, "vram_free": 6e9,
                                                "torch_vram_total": 9.5e9, "torch_vram_free": 0.3e9}]})
        if self.path == "/queue":
            run = [[1, "p", {}, {}, []]] if Fake.hold and not Fake.interrupted else []
            return self.send(200, {"queue_running": run, "queue_pending": [[2, "q", {}, {}, []]] * Fake.pending})
        if self.path.startswith("/history/"):
            pid = self.path.split("/")[-1]
            if Fake.interrupted:
                return self.send(200, {pid: {"status": {"status_str": "error", "messages": [["execution_interrupted", {}]]}}})
            if Fake.hold:
                return self.send(200, {})
            return self.send(200, {pid: {"status": {"status_str": "success", "completed": True},
                                         "outputs": {"9": {"images": [{"filename": "Philibert_00001_.png", "subfolder": ""}]}}}})
        self.send(404, {})

    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        Fake.posts.append((self.path, d))
        if self.path == "/prompt":
            Fake.prompts.append(d)
            if Fake.mode == "bad" or (Fake.mode == "bad_once" and len(Fake.prompts) == 1):
                return self.send(400, BAD)
            Fake.n += 1
            return self.send(200, {"prompt_id": f"pid{Fake.n}", "number": Fake.n})
        if self.path == "/queue":
            if d.get("clear"):
                Fake.pending = 0
            return self.send(200, {})
        if self.path == "/interrupt":
            Fake.interrupted = True
            return self.send(200, {})
        if self.path == "/free":
            return self.send(200, {})
        self.send(404, {})


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Comfy)
threading.Thread(target=srv.serve_forever, daemon=True).start()
ig.URL = f"http://127.0.0.1:{srv.server_port}"
ig.PORT = srv.server_port
root = Path(tempfile.mkdtemp(prefix="imgeng_"))
WF = {"5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
      "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "Philibert"}}}


def reset(mode="ok"):
    Fake.mode, Fake.prompts, Fake.posts, Fake.hold, Fake.interrupted, Fake.pending = mode, [], [], False, False, 0


print("ComfyUI's own reasons")
reset("bad")
try:
    ig._run_prompt(WF, 10)
    msg = ""
except RuntimeError as e:
    msg = str(e)
check("a 400 says what ComfyUI said, not 'HTTP Error 400'", "Value not in list" in msg and "juggernaut.safetensors" in msg
      and "CheckpointLoaderSimple" in msg and "HTTP Error" not in msg, msg)
r = ig.handle({"op": "engine"}, root)
check("... and the engine is free again afterwards", r.get("ok") and r.get("drawing") is False, r)
reset("bad_once")
eng.seen_root(root)                                          # start(root) remembers it; the fake is already running
try:
    out = ig._run_prompt(WF, 10)
except RuntimeError as e:
    out = str(e)
check("a model the engine has not seen: it is started again once, and the picture comes", isinstance(out, list) and len(out) == 1
      and len(Fake.prompts) == 2, (out, len(Fake.prompts)))
reset("bad")
try:
    ig._run_prompt(WF, 10)
except RuntimeError:
    pass
check("... only once: a second refusal is told, not retried for ever", len(Fake.prompts) == 2, len(Fake.prompts))

print("One picture at a time, STOP")
reset()
Fake.hold, Fake.pending = True, 2
res = {}


def first():
    t0 = time.time()
    try:
        res["a"] = ig._run_prompt(WF, 60)
    except RuntimeError as e:
        res["a"] = str(e)
    res["took"] = time.time() - t0


th = threading.Thread(target=first)
th.start()
time.sleep(1.0)
try:
    ig._run_prompt(WF, 5)
    second = "it ran"
except RuntimeError as e:
    second = str(e)
check("a second picture while one is drawn is told so", "being drawn already" in second and "STOP" in second, second)
check("... and never reaches ComfyUI's queue", len(Fake.prompts) == 1, len(Fake.prompts))
s = ig.handle({"op": "engine"}, root)
check("ENGINE says it is drawing a picture, with ComfyUI's queue and the card", s.get("drawing") and s.get("what") == "a picture"
      and s.get("running_n") == 1 and s.get("waiting_n") == 2 and (s.get("card") or {}).get("engine_gb") == 9.2, s)
check("... and that this engine is not one Philibert started (the fake)", s.get("ours") is False, s.get("ours"))
u = ig.handle({"op": "unload"}, root)
check("UNLOAD while drawing asks for STOP first", u.get("ok") is False and "STOP" in u.get("msg", ""), u)
h = ig.handle({"op": "halt"}, root)
th.join(10)
check("STOP: the waiting request ends with 'Stopped.'", res.get("a") == "Stopped." and res.get("took", 99) < 8, res)
check("... it said so, with the queue it cleared", h.get("stopped") and h.get("cleared") == 2 and "Stopped" in h.get("msg", ""), h)
paths = [p for p, _d in Fake.posts]
check("... ComfyUI was told to clear its queue and interrupt", "/interrupt" in paths and ("/queue", {"clear": True}) in Fake.posts, paths)
reset()
out = ig._run_prompt(WF, 10)
check("the next picture after a STOP is drawn normally", isinstance(out, list) and len(out) == 1, out)
h = ig.handle({"op": "halt"}, root)
check("STOP with nothing drawn says so", h.get("stopped") is False and "Nothing" in h.get("msg", ""), h)

print("UNLOAD and TURN OFF")
reset()
u = ig.handle({"op": "unload"}, root)
check("UNLOAD asks ComfyUI to unload its models and free the memory",
      u.get("ok") and ("/free", {"unload_models": True, "free_memory": True}) in Fake.posts, (u, Fake.posts))
ig._proc = None
t = ig.handle({"op": "engine_stop"}, root)
check("TURN OFF leaves a process alone that is not the drive's own engine", t.get("ok") is False and "left it alone" in t.get("msg", "")
      and ig.running(), t)
check("the 4x enlargement and variations are named in ENGINE", eng._what({"1": {"class_type": "ImageUpscaleWithModel", "inputs": {}}}) == "a 4x enlargement"
      and eng._what({"5": {"class_type": "EmptySD3LatentImage", "inputs": {"batch_size": 4}}}) == "4 pictures", "")

print("The relay's pages for a browser")


class Owner:
    phone = None


def relay():
    h = type("Relay", (ms._Relay,), {"local": "http://127.0.0.1:9", "key": "k-good", "owner": Owner})
    s = ms.ThreadingHTTPServer(("127.0.0.1", 0), h)
    s.daemon_threads = True
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


rs = relay()
BASE = f"http://127.0.0.1:{rs.server_port}"


def get(path, html=True, method="GET"):
    req = urllib.request.Request(BASE + path, method=method, data=b"{}" if method == "POST" else None,
                                 headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"} if html else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


c, b = get("/k-good/phone/")
check("not over Tailscale: 403 and a page saying it only opens over Tailscale", c == 403 and "only opens over Tailscale" in b
      and "Connected" in b, (c, b[:200]))
ms.TAILNET = ipaddress.ip_network("127.0.0.0/8")             # the test's own address counts as a Tailscale one now
c, b = get("/k-old/phone/")
check("an old or cut address: 404 and a page saying so, with where to copy the new one", c == 404 and "does not work any more" in b
      and "/phone/" in b, (c, b[:200]))
c, b = get("/k-good/phone/")
check("phone chat off: a page saying it is off and how to turn it on", c == 404 and "turned off" in b and "OPEN A PHONE CHAT" in b, (c, b[:200]))
c, b = get("/k-good/")
check("the laptop address opened on a phone: a page pointing to the phone one", c == 404 and "other computers" in b, (c, b[:200]))
c, b = get("/k-old/api/tags", html=False)
check("a program (no text/html) still gets the plain empty refusal", c == 404 and b == "", (c, b[:80]))
c, b = get("/k-old/phone/", method="POST")
check("a POST still gets the plain refusal", c == 404 and b == "", (c, b[:80]))
Owner.phone = lambda method, sub, data: (200, "text/html; charset=utf-8", b"<html>the phone chat</html>")
c, b = get("/k-good/phone/")
check("with phone chat on, the real page is served as before", c == 200 and "the phone chat" in b, (c, b[:80]))
rs.shutdown()

print("The pages, in a headless Edge")


class Api:
    engine = {"ok": True, "running": True, "drawing": False, "what": "", "seconds": 0, "running_n": 0, "waiting_n": 0,
              "card": {"name": "Test card", "total_gb": 16.0, "free_gb": 12.0, "engine_gb": 3.2}, "ours": True}
    calls = []
    share = {"ok": True, "sharing": True, "address": "http://100.64.1.2:11500/k-test", "tailscale_ip": "100.64.1.2", "port": 11500,
             "phone": True, "phone_address": "http://100.64.1.2:11500/k-test/phone/", "sync_share": False, "sync_with": False,
             "host": "", "using_host": False, "windows": True, "python_exe": "python.exe"}


STATUS = {"ok": True, "installed": True, "running": True, "rating": "green", "why": "", "platform": "win-x64",
          "setup": {}, "download": {"state": "idle"}, "editor": "http://127.0.0.1:8199/", "default_model": "zimage",
          "models": [{"id": "zimage", "name": "Z-Image Turbo", "kind": "zimage", "installed": True, "about": "fast", "fit": "green", "size": 1}],
          "styles": [{"id": "none", "name": "None"}, {"id": "noir", "name": "Noir"}, {"id": "s2", "name": "Second"}],
          "more_styles": [], "defaults": {"zimage": {"steps": 8}, "sdxl": {"steps": 28, "cfg": 6}}, "zimage_takes_negative": False,
          "sizes": {"square": [1024, 1024], "poster": [832, 1216], "banner": [1344, 768], "story": [768, 1344]}}
PIC = {"name": "Philibert_00001_.png", "prompt": "a red guitar", "seed": 777, "style": "noir", "model_id": "zimage", "w": 1024, "h": 1024,
       "model": "Z-Image Turbo"}


class Pages(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, ctype, b):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = self.path.split("?")[0]
        path = {"/images": "/live/images.html", "/models": "/live/modelmgr.html"}.get(path, path)
        if path.startswith("/api/images/file"):
            return self.send(200, "image/png", b"")
        if path.startswith("/live/"):
            f = (STATIC / path[len("/live/"):]).resolve()
            if f.is_file() and STATIC.resolve() in f.parents:
                ct = {".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml"}.get(f.suffix, "application/octet-stream")
                return self.send(200, ct + "; charset=utf-8", f.read_bytes())
        self.send(404, "text/plain", b"")

    def do_POST(self):
        d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/images":
            Api.calls.append(d)
            op = d.get("op")
            out = (STATUS if op == "status" else {"ok": True, "images": [PIC]} if op == "list" else Api.engine if op == "engine"
                   else {"ok": True, "stopped": True, "msg": "Stopped."} if op == "halt"
                   else {"ok": True, "images": [dict(PIC, prompt=d.get("prompt"))], **PIC} if op == "generate" else {"ok": True})
        elif self.path == "/api/modelshare":
            out = Api.share
        else:
            out = {"ok": True}
        self.send(200, "application/json", json.dumps(out).encode())


pg = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Pages)
threading.Thread(target=pg.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{pg.server_port}"
br = Edge()
try:
    br.cmd("Page.navigate", url=URL + "/live/images.html")       # the origin first, to plant last session's settings
    br.wait("document.readyState === 'complete'", 10)
    br.js("localStorage.setItem('img.form', JSON.stringify({style:'noir', seed:'4242', prompt:'old words', count:1, size:'square'}))")
    br.cmd("Page.navigate", url=URL + "/images")
    ok = br.wait("(document.getElementById('eng')||{}).textContent !== 'ENGINE' && document.getElementById('eng').textContent", 10)
    check("the header shows ENGINE: READY and what the engine holds", ok == "ENGINE: READY · 3.2 GB", ok)
    check("last session's seed is not brought back", br.wait("document.getElementById('f-seed') && document.getElementById('f-seed').value === ''", 5)
          and not br.js("!!document.getElementById('seed-note')"), br.js("document.getElementById('f-seed') && document.getElementById('f-seed').value"))
    check("... but its style is (chosen styles are remembered)", br.js("document.querySelector('.chip.on[data-style]').dataset.style") == "noir",
          br.js("document.querySelector('.chip.on[data-style]').dataset.style"))
    Api.engine = dict(Api.engine, drawing=True, what="a picture", seconds=7, running_n=1, waiting_n=2)
    ok = br.wait("document.getElementById('eng').textContent.indexOf('DRAWING') === 0 && !document.getElementById('eng-stop').hidden", 12)
    check("while a picture is drawn: DRAWING, its waiting count, and a STOP button in the header", ok,
          (br.js("document.getElementById('eng').textContent"), br.js("document.getElementById('eng-stop').hidden")))
    br.js("document.getElementById('eng').click()")
    ok = br.wait("!document.getElementById('eng-pop').hidden && document.getElementById('eng-pop').innerText", 5)
    check("the ENGINE panel says what it is drawing, the queue and the card", ok and "drawing a picture" in ok and "1 drawing, 2 waiting" in ok
          and "9.2" not in ok and "3.2 GB" in ok, ok)
    check("... UNLOAD is off while drawing; STOP and TURN OFF are on",
          br.js("[document.querySelector('[data-eng=halt]').disabled, document.querySelector('[data-eng=unload]').disabled,"
                " document.querySelector('[data-eng=engine_stop]').disabled].join()") == "false,true,false", "")
    n = len([c for c in Api.calls if c.get("op") == "halt"])
    br.js("document.getElementById('eng-stop').click()")
    ok = br.wait(f"true", 1) and br.wait("document.getElementById('toast').textContent", 5)
    check("STOP in the header asks Philibert to halt, and says what happened", len([c for c in Api.calls if c.get("op") == "halt"]) == n + 1
          and ok == "Stopped.", (ok, n))
    Api.engine = dict(Api.engine, drawing=False, what="", seconds=0, running_n=0, waiting_n=0)
    br.js("document.body.click()")
    # USE THIS PROMPT AGAIN fixes the seed for this window: a note says so, and it is not saved
    br.js("document.querySelector('#recent figure[data-name]').click()")
    br.wait("document.getElementById('lb').classList.contains('on')", 5)
    br.js("document.getElementById('lb-again').click()")
    ok = br.wait("(document.getElementById('seed-note')||{}).textContent", 5)
    check("USE THIS PROMPT AGAIN: a note says the seed is fixed", ok and "Seed 777 is fixed" in ok, ok)
    check("... and the saved settings hold no seed", br.js("JSON.parse(localStorage.getItem('img.form')).seed") == "",
          br.js("localStorage.getItem('img.form')"))
    br.js("document.getElementById('seed-clear').click()")
    check("Random again clears it", br.wait("!document.getElementById('seed-note') && document.getElementById('f-seed').value === ''", 5), "")
    br.js("dispatchEvent(new StorageEvent('storage', {key: 'img.form', newValue: JSON.stringify({style: 's2', seed: '99'})}))")
    check("another window chose a style: this one takes it up (and not its seed)",
          br.wait("document.querySelector('.chip.on[data-style]').dataset.style === 's2'", 5) and br.js("document.getElementById('f-seed').value") == "",
          br.js("document.querySelector('.chip.on[data-style]').dataset.style"))
    br.js("document.querySelector('[data-style=noir]').click()")
    br.js("var p=document.getElementById('f-prompt'); p.value='a blue piano'; p.dispatchEvent(new Event('input'));")
    br.js("document.getElementById('make').click()")
    br.wait("false", 1.5)
    g = [c for c in Api.calls if c.get("op") == "generate"]
    check("MAKE IT sends the style chosen last, and no old seed", g and g[-1].get("style") == "noir" and g[-1].get("seed") is None
          and g[-1].get("prompt") == "a blue piano", g[-1:] if g else g)
    check("the image page raised no JavaScript errors", not br.errors, br.errors[:3])
    br.cmd("Page.navigate", url=URL + "/models")
    ok = br.wait("(document.querySelector('details.phone-help')||{}).innerText", 10)
    check("Models: THE PHONE DOES NOT OPEN IT? lists what to check", ok and "THE PHONE DOES NOT OPEN IT?" in ok, ok)
    br.js("document.querySelector('details.phone-help').open = true")
    t = br.js("document.querySelector('details.phone-help').innerText")
    check("... Tailscale on the phone, Safari, the whole address, another VPN, the firewall", all(w in t for w in (
        "Connected", "Open in Safari", "/phone/", "VPN", "firewall")), t)
    check("... and a link to try the phone address on this computer", br.js(
        "document.querySelector('details.phone-help a').getAttribute('href')") == Api.share["phone_address"], "")
finally:
    br.stop()
    pg.shutdown()
    srv.shutdown()
    shutil.rmtree(root, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
