"""T03: the remote (OK, Back, Play/Pause, Menu) and the TV's screen size."""
import re
import time

from _t import DEVICE, TEST_PKG, Page, Tv, build, check, code_only, dump, finish, skip, source

apk, err = build()
check("build_apk.py builds the app", apk is not None, err)
if apk is None:
    finish()
src = code_only(source())
check("the app takes the remote's keys first: dispatchKeyEvent is overridden", bool(re.search(r"public boolean dispatchKeyEvent\(KeyEvent \w+\)", src)))
if "dispatchKeyEvent" not in src:
    finish()
check("Back is offered to the page: window.tvBack() is called through evaluateJavascript", "window.tvBack" in src and "evaluateJavascript" in src)
check("... and only the answer true keeps the app from counting it", '"true".equals(' in src)
check("leaving takes a second Back within 2.5 seconds, after: Press Back again to leave", '"Press Back again to leave"' in src and "2500" in src)
check("OK reaches the page as Enter (KEYCODE_DPAD_CENTER becomes KEYCODE_ENTER)", "KEYCODE_DPAD_CENTER" in src and "KEYCODE_ENTER" in src)
check("Play/Pause reaches the page as the key MediaPlayPause", "KEYCODE_MEDIA_PLAY_PAUSE" in src and '"MediaPlayPause"' in src)
check("... sent once per press, not once per repeat", "getRepeatCount() == 0" in src)
check("Menu opens the list", "KEYCODE_MENU" in src and "AlertDialog" in src)
for item in ("Reload", "Size of everything on screen", "Change server address", "Leave the app", "Cancel"):
    check(f"the list has: {item}", f'"{item}"' in src)
check("the page is laid out 1280 wide by default (a Fire TV reports 960)", bool(re.search(r"getInt\(KEY_WIDTH, 1280\)", src)))
check("... by drawing a larger frame reduced (setScaleX and setScaleY from the top left)", all(x in src for x in ("setScaleX(", "setScaleY(", "setPivotX(0)", "setPivotY(0)")))
check("... on a TV only", bool(re.search(r"void fitPage\(int \w+\)\s*\{\s*if \(!isTv\(\)\) return;", src)))
check("the three sizes are 960, 1280 and 1600, named Large, Normal and Small", bool(re.search(r"\{\s*960,\s*1280,\s*1600\s*\}", src))
      and all(f'"{n}"' in src for n in ("Large", "Normal", "Small")))
check("a full-screen video from the page is shown and can be left: onShowCustomView and onHideCustomView", "onShowCustomView" in src and "onHideCustomView" in src)

# ── on the TV ────────────────────────────────────────────────────────────────
tv = Tv()
labels = ["the page is told it is on a TV (LacklusterPlusTV/1.0 in the user agent)", "the page is 1280 wide", "Down reaches the page as ArrowDown",
          "OK reaches the page as Enter", "Play/Pause reaches the page as MediaPlayPause, once", "Menu opens the list with its five entries",
          "Back closes the list", "Back asks the page first (window.tvBack is called)", "... and the app stays while the page had something to close",
          "one more Back does not leave yet", "a second Back right after it leaves the app"]
if not DEVICE or not tv.ready():
    for label in labels:
        skip(label)
    finish()
test_apk, err = build(test_id=True)
check("(on the TV) the test copy builds", test_apk is not None, err)
if test_apk is None:
    finish()
page = Page()


def keys(after):
    return [e.get("key") for e in page.events[after:] if e.get("t") == "key"]


try:
    tv.install(test_apk)
    tv.reverse(page.port)
    tv.fresh()
    tv.start()
    tv.key("KEYCODE_DPAD_UP", "KEYCODE_MOVE_END")             # the address screen: point the app at the stand-in page
    tv.sh("input keyevent " + " ".join(["KEYCODE_DEL"] * 60))
    tv.type(f"127.0.0.1:{page.port}")
    tv.key("KEYCODE_DPAD_DOWN", "KEYCODE_DPAD_CENTER")
    load = page.wait(lambda e: e.get("t") == "load", 20) or {}
    check("(on the TV) the page loads", bool(load), dump(page.events[-3:]))
    check("(on the TV) the page is told it is on a TV (LacklusterPlusTV/1.0 in the user agent)", "LacklusterPlusTV/1.0" in load.get("ua", ""), load.get("ua"))
    check("(on the TV) the page is 1280 wide", load.get("w") == "1280", (load.get("w"), load.get("h")))
    time.sleep(1)
    n = len(page.events)
    tv.key("KEYCODE_DPAD_DOWN")
    page.wait(lambda e: e.get("key") == "ArrowDown", 6, after=n)
    check("(on the TV) Down reaches the page as ArrowDown", "ArrowDown" in keys(n), keys(n))
    n = len(page.events)
    tv.key("KEYCODE_DPAD_CENTER")
    page.wait(lambda e: e.get("key") == "Enter", 6, after=n)
    check("(on the TV) OK reaches the page as Enter", "Enter" in keys(n), keys(n))
    n = len(page.events)
    tv.key("KEYCODE_MEDIA_PLAY_PAUSE")
    page.wait(lambda e: e.get("key") == "MediaPlayPause", 6, after=n)
    time.sleep(1)
    check("(on the TV) Play/Pause reaches the page as MediaPlayPause, once", keys(n).count("MediaPlayPause") == 1, keys(n))
    tv.key("KEYCODE_MENU")
    time.sleep(1)
    t = [x.get("text", "") for x in tv.nodes()]
    check("(on the TV) Menu opens the list with its five entries", all(i in t for i in ("Reload", "Size of everything on screen", "Change server address",
                                                                                     "Leave the app", "Cancel")), dump(t))
    backs = page.count("back")
    tv.key("KEYCODE_BACK")
    time.sleep(1)
    t = [x.get("text", "") for x in tv.nodes()]
    check("(on the TV) Back closes the list", "Reload" not in t and tv.focus() == TEST_PKG and page.count("back") == backs, dump(t))
    tv.key("KEYCODE_BACK")                                    # the stand-in answers true to the first call: it "closed something"
    page.wait(lambda e: e.get("t") == "back", 6)
    check("(on the TV) Back asks the page first (window.tvBack is called)", page.count("back") == backs + 1, page.count("back") - backs)
    time.sleep(1)
    check("(on the TV) ... and the app stays while the page had something to close", tv.focus() == TEST_PKG, tv.focus())
    time.sleep(3)                                             # well past the 2.5 seconds, so the next Back is a first one
    tv.key("KEYCODE_BACK", pause=0.3)                         # the page answers false now: nothing left to close
    check("(on the TV) one more Back does not leave yet", tv.focus() == TEST_PKG, tv.focus())
    tv.key("KEYCODE_BACK", pause=1.5)
    check("(on the TV) a second Back right after it leaves the app", tv.focus() != TEST_PKG, tv.focus())
finally:
    tv.clean_up(page.port)
    page.stop()
finish()
