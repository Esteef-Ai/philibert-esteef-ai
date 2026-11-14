# Notes for whoever works on this pack

## What it is
The first pack of the kind `android-app`: the Lackluster Plus+ Fire TV app (a WebView wrapper, one Java class),
built with the Android SDK tools alone. `reference/` is the app Claude wrote by hand on 2026-11-14 and the owner
installed on a TCL Fire TV (model AFTDEC012E, Fire OS 8). The base (`C:\PCodeTest\_bases\lackluster_firetv_kit`)
holds what a builder is given and must not change: `build_apk.py`, `make_art.py` and the artwork.

## Two kinds of check, and why
- **Always (58 checks):** the app builds; what a TV reads from the APK is right (id, name, wide icon, leanback
  entry, no touch screen needed, one permission); and names in the Java source. The source checks are the weak
  part: they prove a name is used, not that the behaviour is right.
- **On the TV (22 checks):** the real thing. Set `LP_DEVICE=<ip>:5555` and the tests install a TEST copy
  (`ai.esteef.lacklusterplus.test`, made by `build_apk.py --test-id`) beside the real app, wipe only the test
  copy's data, press real remote keys with `adb shell input keyevent`, read the native screen with
  `uiautomator dump`, and point the app at a stand-in page on this PC through `adb reverse` (the TV's own
  127.0.0.1, so no firewall and no network setting is involved). The page reports every load (user agent, width),
  every key it receives and every call of `window.tvBack()`. The test copy is removed at the end.
- Without `LP_DEVICE` the TV checks print `SKIP` and do not count. A build judged without a TV has only been
  judged by the weak half: say so when you report it.

## On the TV: proven 2026-11-14
- All three tests were run on the reference with `LP_DEVICE=192.168.0.48:5555` (TCL AFTDEC012E, Fire OS 8, awake):
  83 checks, of which 25 on the TV, all pass. Typing with `input text`, `uiautomator dump` and
  `KEYCODE_MEDIA_PLAY_PAUSE` all work as the tests assume; no on-screen keyboard gets in the way.
- **The first run found a real fault in the hand-written app.** `failed()` loads `about:blank`; that blank page's
  `onPageStarted` cleared `loadFailed` and its `onPageFinished` hid the "Cannot reach" screen, so a dead address left
  a blank screen. Fixed in the app (v1.3), the reference and T02's brief: the blank page is ignored in both
  callbacks. No source check could have seen this; only the TV did.
- When the box is empty, `uiautomator dump` reports the box's HINT as its text (`http://192.168.0.10:9191`).
- Chromium refuses port 9 itself; any closed port gives the same result.

## NOT PROVEN YET
- The tasks were not proven one at a time in order (T01 alone, then T01+T02); only the whole reference was.
- No local model has built this pack.
- `studio_pack.py verify` runs without the TV: it proves the 58 static checks only.

## What was learned on the real TV (by hand, before the pack)
- A Fire TV reports 960 x 540 to a page (density 2 at 1920 x 1080): everything is twice too big. The app draws a
  larger frame reduced (`fitPage`).
- Fire TV draws the app's **icon** in its wide home tile and ignores the leanback banner for an app installed by
  hand: a square icon sits between grey bars. The icon is the wide picture.
- The home screen keeps the old tile picture after an update until the TV restarts (it is a protected app:
  `am force-stop` is refused).
- `adb connect` answers "actively refused" until ADB debugging is on, and `unauthorized` until the box on the TV
  is accepted; a TV that is asleep times out.
