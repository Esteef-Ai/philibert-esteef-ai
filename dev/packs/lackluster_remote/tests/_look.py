"""The look step's driver for Lackluster Plus+ (see dev/studio_look.py): how to start the app and reach its screens.

Not a test: it prints no PASS or FAIL. It uses the same stand-ins as the tests (a pretend Plex and Tunarr, the real
gateway, a headless browser) and walks the screens a person sees on a TV, at three sizes. The steps use clicks and
the page's own functions, not the remote, so the same driver works on the app before and after a change.
"""
import time
from types import SimpleNamespace

from _t import IN, TV_UA, Browser, FakePlex, Gateway

SIZES = [(1920, 1080), (1280, 720), (960, 540)]              # a desktop / the Fire TV app, a TV browser, a small TV browser


def start(w, h):
    fake = FakePlex()
    gw = Gateway(fake)
    if not gw.up:
        raise RuntimeError("the gateway did not start: " + gw.tail()[-200:])
    br = Browser()
    br.user_agent(TV_UA)
    br.size(w, h)
    br.go(gw.url + "/")
    return SimpleNamespace(fake=fake, gw=gw, br=br)


def stop(ctx):
    ctx.br.stop()
    ctx.gw.stop()


def sign_in_code(ctx):
    return bool(ctx.br.wait("(document.getElementById('link-code')||{}).textContent", 12))


def guide(ctx):
    ctx.fake.authorise(ctx.fake.last_pin(), "tok-viewer")
    ctx.br.wait(IN, 12)
    ok = ctx.br.wait("document.querySelectorAll('#guide-rows .guide-row').length >= 12", 12)
    time.sleep(0.6)
    return bool(ok)


def info_drawer(ctx):
    ctx.br.js("document.querySelector('.guide-row[data-row=\"c3\"] .prog-cell.on-now').click()")
    return bool(ctx.br.wait("document.getElementById('detail-drawer').classList.contains('open')", 4))


def player(ctx):
    ctx.br.js("watchCurrent()")
    ok = ctx.br.wait("document.getElementById('player-modal').classList.contains('open')", 6)
    time.sleep(0.8)
    return bool(ok)


def options(ctx):
    ctx.br.js("closePlayer(); closeDetail();")
    time.sleep(0.4)
    ctx.br.js("if(!document.getElementById('options-dropdown').classList.contains('open')) toggleOptions();")
    return bool(ctx.br.wait("document.getElementById('options-dropdown').classList.contains('open')", 3))


def browse(ctx):
    ctx.br.js("toggleOptions(); document.getElementById('btn-browse').click();")
    ok = ctx.br.wait("!document.querySelector('.guide-layout').classList.contains('sb-collapsed') && "
                     "document.getElementById('filter-sidebar').getBoundingClientRect().width >= 170", 6)
    time.sleep(0.4)
    return bool(ok)


SCREENS = [("sign-in code", sign_in_code), ("guide", guide), ("info drawer", info_drawer), ("player", player),
           ("options", options), ("browse column", browse)]
