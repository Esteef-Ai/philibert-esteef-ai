"""T01: the app builds, a Fire TV lists it, and it opens."""
import re
import zipfile

from _t import DEVICE, PKG, TEST_PKG, WS, Tv, badging, build, check, code_only, finish, manifest, skip, source

for rel in ("app/AndroidManifest.xml", "app/res/values/strings.xml", "app/res/values/styles.xml",
            "app/src/ai/esteef/lacklusterplus/MainActivity.java"):
    check(f"{rel} exists", (WS / rel).is_file())
apk, err = build()
check("build_apk.py builds the app (resources, Java, dex, signature)", apk is not None, err)
if apk is None:
    finish()

b = badging(apk)
check("the package is ai.esteef.lacklusterplus", f"package: name='{PKG}'" in b, b[:160])
check("it runs on Fire OS 5 and later (min SDK 22)", "minSdkVersion:'22'" in b, re.findall(r"minSdkVersion:'\d+'", b))
check("its name is Lackluster Plus+", "application-label:'Lackluster Plus+'" in b, re.findall(r"application-label:'[^']*'", b))
check("a TV lists it: MainActivity is a leanback launcher entry", f"leanback-launchable-activity: name='{PKG}.MainActivity'" in b,
      re.findall(r"leanback-launchable-activity[^\n]*", b))
check("a phone or tablet lists it too (ordinary launcher entry)", f"launchable-activity: name='{PKG}.MainActivity'" in b)
check("it does not need a touch screen", "uses-feature-not-required: name='android.hardware.touchscreen'" in b,
      re.findall(r"uses-feature[^\n]*", b))
check("the only permission is INTERNET", re.findall(r"uses-permission: name='([^']+)'", b) == ["android.permission.INTERNET"],
      re.findall(r"uses-permission: name='([^']+)'", b))
app = re.search(r"application: label='[^']*' icon='([^']*)'(?: banner='([^']*)')?", b)
check("the icon is the wide picture (a Fire TV draws the ICON in its wide tile)", bool(app) and "banner.png" in app.group(1), app and app.group(1))
check("the banner is the wide picture too", bool(app) and "banner.png" in (app.group(2) or ""), app and app.group(2))
m = manifest(apk)
check("plain http is allowed (the server is on the home network): usesCleartextTraffic is true",
      bool(re.search(r"usesCleartextTraffic[^\n]*=true", m)), re.findall(r"usesCleartextTraffic[^\n]*", m))
check("the activity survives the TV changing its mode: configChanges is set", "configChanges" in m)
with zipfile.ZipFile(apk) as z:
    names = z.namelist()
    dex = z.read("classes.dex") if "classes.dex" in names else b""
check("the APK holds the compiled class ai.esteef.lacklusterplus.MainActivity", b"Lai/esteef/lacklusterplus/MainActivity;" in dex)
strings = (WS / "app" / "res" / "values" / "strings.xml").read_text(encoding="utf-8")
check("strings.xml has default_server, an http address", bool(re.search(r'<string name="default_server">https?://[^<]+</string>', strings)))
check("strings.xml has the byline: Philibert TV, by Esteef.Ai", "Philibert TV, by Esteef.Ai" in strings)
src = code_only(source())
check("MainActivity extends Activity (no libraries)", bool(re.search(r"public class MainActivity extends Activity\b", src)))
check("nothing from AndroidX or the support library is used", "androidx." not in src and "android.support." not in src)
check("the page is told it is on a TV: the user agent gains LacklusterPlusTV/1.0", '"LacklusterPlusTV/1.0"' in src and "setUserAgentString" in src)
check("JavaScript and page storage are on", "setJavaScriptEnabled(true)" in src and "setDomStorageEnabled(true)" in src)
check("video may start without a tap", "setMediaPlaybackRequiresUserGesture(false)" in src)
check("the sign-in is kept when the app is left: cookies are flushed in onPause", bool(re.search(r"onPause\(\)\s*\{[^}]*flush\(\)", src, re.S)))

# ── on the TV ────────────────────────────────────────────────────────────────
tv = Tv()
if not DEVICE or not tv.ready():
    skip("the test copy installs on the TV")
    skip("it starts and has the screen")
    finish()
test_apk, err = build(test_id=True)
check("(on the TV) the test copy builds under its own id", test_apk is not None, err)
if test_apk is None:
    finish()
try:
    out = tv.install(test_apk)
    check("(on the TV) the test copy installs", "Success" in out, out[-200:])
    tv.fresh()
    tv.start()
    check("(on the TV) it starts and has the screen", tv.focus() == TEST_PKG, tv.focus())
    check("(on the TV) it is still there after five seconds (no crash on start)", (__import__("time").sleep(5) or tv.focus()) == TEST_PKG, tv.focus())
finally:
    tv.clean_up()
finish()
