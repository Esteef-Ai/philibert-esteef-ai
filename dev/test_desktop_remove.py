"""Philibert's desktop: removing icons (dev/patching.py DESKTOP_REMOVE, shared/desktop_remove.js).

Serves app/live/static with the real desktop backend (app/nd_retro_desktop.py) on a scratch drive, and drives
a headless Edge (no window) with real mouse and key events: right-click > Remove from desktop, a box to
select several, a right-button box, a drag onto the Trash, the Delete key, icons Philibert keeps, and a
plain drag that still moves and remembers an icon.

    python dev/test_desktop_remove.py
"""
import http.server
import json
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"
STATIC = APP / "live" / "static"
sys.path.insert(0, str(APP))
import nd_retro_desktop as rd  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _edge import Edge  # noqa: E402

results = []


def check(label, ok, got=""):
    results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + label + ("" if ok else f" - got {got!r}"[:400]))


drive = Path(tempfile.mkdtemp(prefix="desk_remove_"))
data, apps_dir = drive / "data", drive / "Apps"
(apps_dir / "mytool").mkdir(parents=True)
(apps_dir / "mytool" / "index.html").write_text("<!doctype html><title>My Tool</title><p>My Tool</p>", encoding="utf-8")
(apps_dir / "mytool" / "app.json").write_text(json.dumps({"name": "My Tool", "entry": "index.html", "source": "nd"}), encoding="utf-8")
# an app still on the desktop whose previous version waits in .trash (publishing keeps it): never in the Trash window
for d in (apps_dir / "other", apps_dir / ".trash" / "other-20261101-120000"):
    d.mkdir(parents=True)
    (d / "index.html").write_text("<p>Other</p>", encoding="utf-8")
    (d / "app.json").write_text(json.dumps({"name": "Other", "entry": "index.html", "source": "nd"}), encoding="utf-8")
# known places for the icons the test boxes in; everything else keeps its default place down the left
PLACES = {"models": [600, 100], "band": [600, 176], "app:mytool": [840, 100], "control": [840, 176], "board": [400, 400]}
rd.save_settings(data, {"theme": "win95", "boot": False, "sounds": False, "screensaver": False, "icons": {"taskbar": PLACES}})


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/live/"):
            f = (STATIC / path[len("/live/"):]).resolve()
            if f.is_file() and STATIC.resolve() in f.parents:
                types = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml"}
                return self.send(200, f.read_bytes(), types.get(f.suffix, "application/octet-stream"))
        self.send(404, b"", "text/plain")

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        out = rd.handle(body, data, apps_dir) if self.path == "/api/desktop" else {"ok": True}
        self.send(200, json.dumps(out).encode(), "application/json")


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_port}/live/desktop.html"


ICONS = "[].map.call(document.querySelectorAll('#icons .dicon'), function(e){return e.dataset.id;})"
SEL = "[].map.call(document.querySelectorAll('#icons .dicon.sel'), function(e){return e.dataset.id;})"
MENU = ("(function(){var f=document.getElementById('flyout'); if(!f||f.hidden) return null; return [].map.call(f.querySelectorAll('.mi'),"
        " function(e){return {t:e.textContent, off:e.classList.contains('off')};});})()")


def centre(br, sel):
    r = br.js(f"(function(){{var e=document.querySelector({json.dumps(sel)}); if(!e) return null; var q=e.getBoundingClientRect();"
              "return [q.left+q.width/2, q.top+q.height/2];})()")
    return r


def icon(br, aid):
    return centre(br, f'#icons .dicon[data-id="{aid}"] .img')


def menu_item(br, text):
    """Click the open menu's item whose text starts with `text`. -> True if it was there and on."""
    return br.js("(function(t){var f=document.getElementById('flyout'); var m=[].find.call(f.querySelectorAll('.mi'),"
                 " function(e){return e.textContent.indexOf(t)===0;}); if(!m||m.classList.contains('off')) return false;"
                 " m.click(); return true;})(" + json.dumps(text) + ")")


def installed():
    """The App Store apps on the drive's desktop (None in the settings means every one)."""
    return rd.installed(data)


br = Edge()
try:
    br.cmd("Page.navigate", url=URL)
    ok = br.wait(f"{ICONS}.length > 10 && document.getElementById('boot').hidden !== false", 15)
    start = br.js(ICONS) or []
    check("the desktop loads with its icons", ok and "notes" in start and "app:mytool" in start and "trash" in start, start)

    # 1. right-click one icon > Remove from desktop
    x, y = icon(br, "notes")
    br.click(x, y, "right")
    m = br.js(MENU) or []
    check("right-click an App Store app: the menu has Remove from desktop", any(i["t"] == "Remove from desktop" and not i["off"] for i in m), m)
    check("... and it worked", menu_item(br, "Remove from desktop"))
    br.wait(f"{ICONS}.indexOf('notes') < 0", 5)
    check("Notes is off the desktop", "notes" not in (br.js(ICONS) or []))
    check("... and off the drive's App Store list (comes back from the App Store)", "notes" not in (installed() or []), installed())
    check("a message says where it went", br.wait("(document.querySelector('.notify')||{}).textContent||''", 3) and
          "App Store" in br.js("document.querySelector('.notify').textContent"), br.js("(document.querySelector('.notify')||{}).textContent"))

    # 2. icons Philibert keeps
    for keep in ("control", "trash"):
        x, y = icon(br, keep)
        br.click(x, y, "right")
        m = br.js(MENU) or []
        rm = [i for i in m if i["t"].startswith("Remove")]
        check(f"right-click {keep}: no live Remove item", all(i["off"] for i in rm), m)
        br.key("Escape", 27)
        br.click(1200, 40)

    # 3. a box selects several; right-click one of them removes them all
    br.drag((570, 70), (700, 250))
    check("a box over Models and Band selects exactly those two", sorted(br.js(SEL) or []) == ["band", "models"], br.js(SEL))
    x, y = icon(br, "band")
    br.click(x, y, "right")
    m = br.js(MENU) or []
    check("right-click in the selection: Remove 2 from desktop", any(i["t"] == "Remove 2 from desktop" for i in m), m)
    menu_item(br, "Remove 2 from desktop")
    br.wait(f"{ICONS}.indexOf('band') < 0 && {ICONS}.indexOf('models') < 0", 5)
    left = br.js(ICONS) or []
    check("Models and Band are both off the desktop", "band" not in left and "models" not in left, left)
    check("... and off the App Store list", not ({"band", "models"} & set(installed() or [])), installed())

    # 4. a right-button box opens the menu for what it selected; a kept icon stays
    br.click(1200, 40)
    br.drag((810, 70), (940, 250), button="right")
    check("a right-button box selects My Tool and Control Panel", sorted(br.js(SEL) or []) == ["app:mytool", "control"], br.js(SEL))
    m = br.js(MENU) or []
    check("... and opens the menu by itself: Remove 1 of 2", any(i["t"] == "Remove 1 of 2 from desktop" and not i["off"] for i in m), m)
    menu_item(br, "Remove 1 of 2 from desktop")
    br.wait(f"{ICONS}.indexOf('app:mytool') < 0", 5)
    left = br.js(ICONS) or []
    check("My Tool (published) is off the desktop, Control Panel stays", "app:mytool" not in left and "control" in left, left)
    trash = list((apps_dir / ".trash").glob("mytool-*"))
    check("My Tool's files are kept in Apps/.trash, not deleted", len(trash) == 1 and (trash[0] / "index.html").is_file(), trash)

    # 4b. the Trash shows it: Put back, then Delete forever
    ROWS = "[].map.call(document.querySelectorAll('#trash-rows .row'), function(e){return e.innerText;})"
    br.js("document.querySelectorAll('.notify').forEach(function(n){n.remove();})")
    x, y = icon(br, "trash")
    br.click(x, y)
    br.key("Enter", 13)
    rows = br.wait(f"{ROWS}.length && {ROWS}", 8) or []
    check("the Trash lists My Tool, from Desktop apps", any("My Tool" in r and "Desktop apps" in r for r in rows), rows)
    check("... and not the old version of an app that is still on the desktop", not any("Other" in r for r in rows), rows)
    br.js("[].find.call(document.querySelectorAll('#trash-rows .row'), function(e){return /My Tool/.test(e.innerText);})"
          ".dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))")
    back = br.wait(f"{ICONS}.indexOf('app:mytool') >= 0", 20)
    check("Put back: My Tool is on the desktop again", back and (apps_dir / "mytool" / "index.html").is_file(), br.js(ICONS))
    check("... and gone from the Trash list", not any("My Tool" in r for r in (br.wait(f"!{ROWS}.some(function(r){{return /My Tool/.test(r);}}) && {ROWS}", 5) or [])))
    rd.handle({"op": "app_remove", "id": "mytool"}, data, apps_dir)
    br.js("window.confirm = function () { return true; }")
    br.js("document.getElementById('trash-empty').click()")
    br.wait("false", 1.5)
    check("Empty Trash deletes the removed app for good", not list((apps_dir / ".trash").glob("mytool-*")),
          list((apps_dir / ".trash").iterdir()))
    check("... and leaves the old version of the app still on the desktop alone",
          (apps_dir / ".trash" / "other-20261101-120000" / "index.html").is_file() and (apps_dir / "other").is_dir())
    br.js("document.querySelectorAll('.win').forEach(function(w){ if(w.dataset.id === 'trash') w.querySelector('[data-act=close]').click(); })")
    br.wait("false", 0.6)

    # 5. drag onto the Trash
    a, t = icon(br, "files"), icon(br, "trash")
    br.drag(tuple(a), tuple(t))
    br.wait(f"{ICONS}.indexOf('files') < 0", 5)
    check("dragging Files onto the Trash takes it off the desktop", "files" not in (br.js(ICONS) or []), br.js(ICONS))
    check("... the Trash is no longer lit up as a target", not br.js("!!document.querySelector('.dicon.drop-target')"))
    a, t = icon(br, "control"), icon(br, "trash")
    before = br.js("(function(e){return [e.offsetLeft,e.offsetTop];})(document.querySelector('.dicon[data-id=\"control\"]'))")
    br.drag(tuple(a), tuple(t))
    time.sleep(0.4)
    after = br.js("(function(e){return [e.offsetLeft,e.offsetTop];})(document.querySelector('.dicon[data-id=\"control\"]'))")
    check("dragging Control Panel onto the Trash: it stays, back where it was", after == before and "control" in (br.js(ICONS) or []),
          (before, after))
    check("... and a message says Philibert needs it", "needs" in (br.js("(document.querySelector('.msgbox, .win.msg, .dialog')||document.body).innerText") or ""))
    br.js("document.querySelectorAll('.win').forEach(function(w){ if(/needs/.test(w.innerText)) w.remove(); })")

    # 6. Delete key
    x, y = icon(br, "board")
    br.click(x, y)
    br.key("Delete", 46)
    br.wait(f"{ICONS}.indexOf('board') < 0", 5)
    check("select Group Board and press Delete: it comes off", "board" not in (br.js(ICONS) or []), br.js(ICONS))

    # 7. a plain drag still moves an icon and remembers it
    x, y = icon(br, "feedback")
    br.drag((x, y), (x + 300, y + 10))
    time.sleep(0.5)
    pos = (rd.settings(data).get("icons") or {}).get("taskbar", {}).get("feedback")
    check("a plain drag moves Feedback Shooter and the place is saved", pos and pos[0] > 200, pos)
    check("... it is still on the desktop", "feedback" in (br.js(ICONS) or []))

    # 8. Ctrl+click adds to the selection
    br.click(1200, 40)
    a, b = icon(br, "feedback"), icon(br, "store")
    br.click(*a)
    br.click(*b, mods=2)
    check("Ctrl+click adds a second icon to the selection", sorted(br.js(SEL) or []) == ["feedback", "store"], br.js(SEL))

    check("the page raised no JavaScript errors", not br.errors, br.errors[:3])
finally:
    br.stop()
    srv.shutdown()
    shutil.rmtree(drive, ignore_errors=True)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
