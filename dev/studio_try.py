"""Try a built Lackluster workspace by hand: start its real gateway against the test fakes and sign you in.

    python dev/studio_try.py C:\\PCodeTest\\blind7

It starts FakePlex (plex.tv, the Plex server and Tunarr: 12 fake channels, no real video) and the workspace's
gateway (node dist/server.js) on a free local port, and prints the address. Open it in any browser. Every sign-in
code the page shows is approved within a second, as viewer1. Add ?tv=1 to the address to get the TV remote mode,
then use the arrow keys, Enter as OK and Backspace or Escape as Back. Press Enter or Ctrl+C here to stop it.
Nothing touches the live server or the network; the gateway's database lives in a temp folder.
"""
import sys
import threading
import time
from pathlib import Path

if len(sys.argv) < 2:
    sys.exit(__doc__)
ws = Path(sys.argv[1]).resolve()
if not (ws / "dist" / "server.js").is_file() or not (ws / "tests" / "_t.py").is_file():
    sys.exit(f"{ws} is not a built Lackluster workspace (needs dist/server.js and tests/_t.py)")
sys.path.insert(0, str(ws / "tests"))
import _t  # noqa: E402

fake = _t.FakePlex()
gw = _t.Gateway(fake)
if not gw.up:
    sys.exit("the gateway did not start:\n" + gw.tail())


def approve():
    while True:
        for pid, p in list(fake.pins.items()):
            if p["state"] == "pending":
                fake.authorise(pid, "tok-viewer")
        time.sleep(0.5)


threading.Thread(target=approve, daemon=True).start()
print(f"\nLackluster Plus+ from {ws}\n")
print(f"  as a TV (remote mode):  {gw.url}/?tv=1")
print(f"  as a computer:          {gw.url}/\n")
print("Sign-in codes are approved automatically. The 12 channels are fake and have no video.")
print("Press Enter here to stop.\n")
try:
    input()
except (KeyboardInterrupt, EOFError):
    pass
gw.stop()
print("stopped")
