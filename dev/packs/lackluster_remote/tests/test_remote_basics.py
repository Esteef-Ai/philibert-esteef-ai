"""T01: a TV remote can reach everything: arrow keys move a visible highlight, OK presses it."""
import faulthandler
import json
import time

faulthandler.dump_traceback_later(540, exit=True)
import requests  # noqa: E402

from _t import ACTIVE, TV_UA, WS, FakePlex, Gateway, check, finish, signed_in, visible  # noqa: E402

page = (WS / "public" / "index.html").read_text(encoding="utf-8")
check("public/tvnav.js exists", (WS / "public" / "tvnav.js").is_file())
check("index.html loads it once, with <script src=\"/tvnav.js\"></script>", page.count('<script src="/tvnav.js"></script>') == 1,
      page.count("tvnav.js"))
check("... as the last script, just before </body>", page.rstrip().endswith('<script src="/tvnav.js"></script>\n</body>\n</html>'),
      page.rstrip()[-80:])

fake = FakePlex()
gw = Gateway(fake)
check("the gateway starts", gw.up, gw.tail())
if not gw.up:
    finish()
r = requests.get(gw.url + "/tvnav.js", timeout=20)
check("GET /tvnav.js answers 200 with JavaScript", r.status_code == 200 and "javascript" in r.headers.get("content-type", ""),
      (r.status_code, r.headers.get("content-type")))
br = signed_in(fake, gw)


def active():
    return br.js(ACTIVE) or {}


def quit_all():
    bad = [e for e in br.errors if "cast" not in e.lower()]
    check("the page raised no JavaScript errors", not bad, bad[:3])
    br.stop()
    gw.stop()
    finish()


check("window.tvNav exists (tvnav.js ran)", br.js("typeof window.tvNav === 'object' && typeof window.tvNav.isOn === 'function'"))
if not br.js("typeof window.tvNav === 'object'"):
    quit_all()
check("on a computer nothing changes until an arrow key is pressed: remote mode is off", br.js("window.tvNav.isOn()") is False
      and not active().get("on"), active())

# ── the first arrow key ─────────────────────────────────────────────────────
br.press("down")
a = active()
check("the first arrow key turns remote mode on (body gets the class tv-nav)", a.get("on") and br.js("window.tvNav.isOn()") is True, a)
check("... and highlights what is on now on the first channel", "prog-cell" in a.get("cls", "") and "on-now" in a.get("cls", "")
      and a.get("row") == "c1", a)
ring = br.js("(function(){var c=getComputedStyle(document.activeElement); return [c.outlineStyle, parseFloat(c.outlineWidth)];})()") or ["", 0]
check("the highlight is visible: a solid outline at least 3 px wide", ring[0] == "solid" and ring[1] >= 3, ring)
check("the highlight is real keyboard focus on that element", br.js("document.activeElement.classList.contains('prog-cell')"))

# ── everything can be reached ───────────────────────────────────────────────
# Walk the screen the way a person with a remote would: from every highlighted thing, try all four arrows.
MARK = ("(function(){var e=document.activeElement; if(!e||e===document.body) return ''; if(!e.dataset.tvk){window.__tvk=(window.__tvk||0)+1;"
        "e.dataset.tvk=String(window.__tvk);} return e.dataset.tvk;})()")
DESCRIBE = ("(function(k){var e=document.querySelector('[data-tvk=\"'+k+'\"]'); if(!e) return ''; var r=e.closest('.guide-row');"
            "return (e.id?'#'+e.id+' ':'')+(typeof e.className==='string'?e.className:'')+' | '+(e.getAttribute('onclick')||'')+' | '"
            "+(e.innerText||'').trim().slice(0,30)+(r?' | row '+r.dataset.row:'');})")
seen, todo, stuck = {}, [br.js(MARK)], []
t_end = time.time() + 240
while todo and time.time() < t_end and len(seen) < 90:
    k = todo.pop(0)
    if k in seen or not k:
        continue
    seen[k] = br.js(f"{DESCRIBE}({json.dumps(k)})")
    for d in ("up", "down", "left", "right"):
        br.js(f"document.querySelector('[data-tvk=\"{k}\"]').focus({{preventScroll:true}})")
        br.press(d, pause=0.05)
        n = br.js(MARK)
        if not n:
            stuck.append((seen[k], d))
        elif n not in seen and n not in todo:
            todo.append(n)
found = "\n".join(seen.values())
check("walking with the arrows never loses the highlight", not stuck, stuck[:3])
for what, needle in (("the Browse button", "#btn-browse"), ("the search box", "#search-input"), ("Play Now", "openPlayNow()"),
                     ("zoom out", "guideZoom(-1)"), ("zoom in", "guideZoom(1)"), ("guide Back", "guideScroll(-1)"),
                     ("Now", "guideJumpNow()"), ("guide Forward", "guideScroll(1)"), ("the options button", "icon-btn"),
                     ("the avatar", "#avatar"), ("a channel logo", "logo-tile"), ("a programme", "prog-cell")):
    check(f"arrows alone reach {what}", needle in found, sorted(seen.values())[:40] if needle not in found else "")
check("arrows never land on a link that opens another window", "brand-sub" not in found and "github" not in found.lower())
check("arrows never land on the favourite stars (they stay a mouse and touch feature)", "chan-fav" not in found)
check("arrows never land inside the closed info drawer", "watchCurrent()" not in found and "detail-close" not in found)

# ── OK presses things that are not real buttons ─────────────────────────────
br.focus('.icon-btn')
check("the options button (a div) can hold the highlight", "icon-btn" in active().get("cls", ""), active())
br.press("ok")
check("OK on it opens the options", br.wait("document.getElementById('options-dropdown').classList.contains('open')", 3))
inside = set()
for d in ("down", "down", "down", "down", "down", "up", "left", "right", "down", "down"):
    br.press(d)
    inside.add(br.js("!!document.activeElement.closest('#options-dropdown')"))
check("while the options are open the arrows stay inside them", inside == {True}, inside)
got = set()
br.focus("#quality-pref")
for _ in range(6):
    got.add(br.js("document.activeElement.id || document.activeElement.className"))
    br.press("down")
got.add(br.js("document.activeElement.id || document.activeElement.className"))
check("... and reach both pickers, the checkbox and Sign out", {"quality-pref", "subtitle-pref", "force-subs", "signout"} <= got, got)
check("an arrow on a picker moves the highlight, it does not change the choice", br.js("document.getElementById('quality-pref').value") == "auto",
      br.js("document.getElementById('quality-pref').value"))
br.js("toggleOptions()")

br.focus("#btn-browse")
br.press("ok")                                             # a real button: Enter works by itself
check("OK on Browse opens the Browse column", br.wait("!document.querySelector('.guide-layout').classList.contains('sb-collapsed')", 3))
time.sleep(0.5)
br.press("left")
a = active()
check("Left from Browse goes into the column", "fs-item" in a.get("cls", ""), a)
br.focus('.fs-item[data-filter="all"]')
br.press("down")
a = active()
check("Down moves to the next entry (Movies)", a.get("text") == "Movies", a)
br.press("ok")
check("OK on Movies (a div) chooses it", br.js("document.querySelector('.fs-item.active').dataset.filter") == "movies",
      br.js("document.querySelector('.fs-item.active').dataset.filter"))
br.js("document.querySelector('.fs-item[data-filter=\"all\"]').click(); toggleBrowse();")

# ── a text box keeps its own Left and Right ─────────────────────────────────
br.js("var i=document.getElementById('search-input'); i.focus(); i.value='abc'; i.setSelectionRange(3,3);")
br.press("left")
check("in the search box Left moves the caret, not the highlight", br.js("document.activeElement.id") == "search-input"
      and br.js("document.getElementById('search-input').selectionStart") == 2,
      (br.js("document.activeElement.id"), br.js("document.getElementById('search-input').selectionStart")))
br.press("down")
check("... and Down leaves the box", br.js("document.activeElement.id") != "search-input", active())
br.js("document.getElementById('search-input').value=''; applyFilters();")

# ── the mouse still works as before ─────────────────────────────────────────
br.js("document.querySelector('.guide-row[data-row=\"c3\"] .prog-cell.on-now').click()")
check("a mouse click on a programme still opens its info", br.wait("document.getElementById('detail-drawer').classList.contains('open') && "
      "document.getElementById('dd-title').textContent", 3) == "Channel 3 show 1", br.js("document.getElementById('dd-title').textContent"))
br.stop()

# ── a TV browser: remote mode from the start ────────────────────────────────
br = signed_in(fake, gw, ua=TV_UA, path="/")
check("on a TV browser remote mode is on without pressing anything", br.js("window.tvNav.isOn()") is True and active().get("on"), active())
check("the sign-in screen is gone and the guide shows", br.js(visible("#guide-rows")))
quit_all()
