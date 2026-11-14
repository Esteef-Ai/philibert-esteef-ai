# Lackluster Plus+: the Fire TV app

Lackluster Plus+ (Philibert TV, by Esteef.Ai) is a web app: a channel guide and a player in one page, served by a
gateway on the home network. On a Fire TV stick or a TCL Fire TV it is awkward in the TV's browser. This is a small
Android app that IS that page, full screen, driven by the TV remote. It is built with the Android SDK tools alone
(`build_apk.py`, no Gradle); the build tools and the artwork are already in the project.

## What a person gets
- **A tile on the TV.** The app is listed on a Fire TV (it needs no touch screen), named `Lackluster Plus+`, with
  the wide picture `@drawable/banner` as its icon and its banner.
- **First launch asks where the server is.** A dark screen with the app's name, `Philibert TV, by Esteef.Ai`, an
  address box that already holds the address from `res/values/strings.xml` (`default_server`), and a `Connect`
  button that has the highlight. OK connects. The address is remembered; later launches go straight to the page.
- **A bad address is explained.** If the server cannot be reached the same screen returns, says `Cannot reach` and
  the address, and lets the person correct it. An address typed without `http://` gets it.
- **The page knows it is on a TV.** On a TV the app adds `LacklusterPlusTV/1.0` to the browser's user agent (the
  page then signs in with a code and turns its remote mode on), and lays the page out 1280 wide, because a Fire TV
  otherwise reports 960 x 540 and everything is far too big.
- **The remote works.** The arrows reach the page as arrow keys and OK as `Enter`. Play/Pause reaches the page as
  the key `MediaPlayPause`. Back is offered to the page first: the app calls the page's `window.tvBack()`, and
  only when that answers false does Back count towards leaving; a second Back within 2.5 seconds leaves the app
  (after `Press Back again to leave`). Menu opens a small list: `Reload`, `Size of everything on screen`,
  `Change server address`, `Leave the app`, `Cancel`.
- **It keeps the sign-in.** Cookies are saved when the app is left, and sound and picture stop.

## What it is made of
- `app/AndroidManifest.xml`: package `ai.esteef.lacklusterplus`, one activity `.MainActivity`, min SDK 22.
- `app/res/values/strings.xml` and `styles.xml`.
- `app/src/ai/esteef/lacklusterplus/MainActivity.java`: everything else, one class, no libraries.
- Colours: background `#0A0C10`, the highlight `#4CE0E8`, the button `#3B6CFF`. Dark; no bright or pastel colours.
