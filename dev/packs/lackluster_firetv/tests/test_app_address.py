"""T02: first launch asks for the server address, remembers it, and explains one it cannot reach."""
import re
import time

from _t import DEVICE, TEST_PKG, WS, Page, Tv, build, check, code_only, dump, finish, skip, source

apk, err = build()
check("build_apk.py builds the app", apk is not None, err)
if apk is None:
    finish()
src = code_only(source())
check("the address screen exists: showPanel, hidePanel and connect are methods", all(re.search(r"\bvoid " + n + r"\(", src) for n in ("showPanel", "hidePanel", "connect")),
      [n for n in ("showPanel", "hidePanel", "connect") if not re.search(r"\bvoid " + n + r"\(", src)])
if "showPanel" not in src:
    finish()
check("cleanAddress is a static method that returns the tidied address", bool(re.search(r"static String cleanAddress\(String \w+\)", src)))
check("... it adds http:// when the person left it out", bool(re.search(r'"http://"\s*\+', src)))
check("the address is saved under the key \"server\" in the preferences \"lacklusterplus\"", '"lacklusterplus"' in src and '"server"' in src
      and "putString(KEY_SERVER" in src)
check("the box starts with default_server from strings.xml", "R.string.default_server" in src)
check("the box is an EditText made for addresses (TYPE_TEXT_VARIATION_URI)", "EditText" in src and "TYPE_TEXT_VARIATION_URI" in src)
check("the button says Connect", '"Connect"' in src)
check("the highlight is drawn: a StateListDrawable with a focused state", "StateListDrawable" in src and "state_focused" in src)
check("the screen opens with the highlight on the button", bool(re.search(r"connectButton\.requestFocus\(\)", src)))
check("a page that cannot load comes back to the screen: both onReceivedError forms are there",
      len(re.findall(r"void onReceivedError\(", src)) == 2, len(re.findall(r"void onReceivedError\(", src)))
check("... only for the main page, not for a picture that failed", "isForMainFrame()" in src)
check("... with the words Cannot reach", '"Cannot reach "' in src)
check("no layout XML: the screen is made in code", not (WS / "app" / "res" / "layout").exists())

# ── on the TV ────────────────────────────────────────────────────────────────
tv = Tv()
labels = ["first launch shows the address screen, not a page", "the box holds default_server", "the highlight is on Connect",
          "an address nothing answers at brings the screen back with Cannot reach", "a good address typed without http:// loads the page",
          "the address screen is gone", "the app starts again straight on the page (the address was remembered)"]
if not DEVICE or not tv.ready():
    for label in labels:
        skip(label)
    finish()
test_apk, err = build(test_id=True)
check("(on the TV) the test copy builds", test_apk is not None, err)
if test_apk is None:
    finish()
page = Page()
default = re.search(r'<string name="default_server">([^<]+)</string>', (WS / "app" / "res" / "values" / "strings.xml").read_text(encoding="utf-8")).group(1)


def texts():
    return [n.get("text", "") for n in tv.nodes()]


def retype(address):
    """Highlight the box (Up from Connect), empty it, type, go back down to Connect and press OK."""
    tv.key("KEYCODE_DPAD_UP", "KEYCODE_MOVE_END")
    tv.sh("input keyevent " + " ".join(["KEYCODE_DEL"] * 60))
    tv.type(address)
    tv.key("KEYCODE_DPAD_DOWN", "KEYCODE_DPAD_CENTER")


try:
    tv.install(test_apk)
    tv.reverse(page.port)
    tv.fresh()
    tv.start()
    nodes = tv.nodes()
    check("(on the TV) first launch shows the address screen, not a page", any(n.get("text") == "Connect" for n in nodes)
          and page.count("load") == 0, dump([n.get("text") for n in nodes if n.get("text")]))
    box = next((n for n in nodes if n.get("class") == "android.widget.EditText"), {})
    check("(on the TV) the box holds default_server", box.get("text") == default, box.get("text"))
    btn = next((n for n in nodes if n.get("text") == "Connect"), {})
    check("(on the TV) the highlight is on Connect", btn.get("focused") == "true", dump(btn))
    retype("127.0.0.1:9")                                     # nothing listens on port 9
    time.sleep(4)
    t = texts()
    check("(on the TV) an address nothing answers at brings the screen back with Cannot reach", any("Cannot reach http://127.0.0.1:9" in x for x in t), dump(t))
    retype(f"127.0.0.1:{page.port}")
    load = page.wait(lambda e: e.get("t") == "load", 20)
    check("(on the TV) a good address typed without http:// loads the page", load is not None, dump(page.events[-3:]))
    time.sleep(1.5)
    check("(on the TV) the address screen is gone", "Connect" not in texts(), dump(texts()))
    n = len(page.events)
    tv.stop()
    tv.start()
    again = page.wait(lambda e: e.get("t") == "load", 20, after=n)
    check("(on the TV) the app starts again straight on the page (the address was remembered)", again is not None and tv.focus() == TEST_PKG,
          dump(page.events[n:]))
finally:
    tv.clean_up(page.port)
    page.stop()
finish()
