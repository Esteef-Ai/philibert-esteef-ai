# TubeLoader guide (for Philibert)

Philibert reads this when it assists with a TubeLoader push. It only gets the sections for the device in
question: General, that device's family (Android or Roku), and Safe fixes. Keep each problem short and
put the fix right after it. Write what is true; Philibert trusts this guide over its own guesses.

## General
- TubeLoader runs on the computer. It reaches the TV over the home network, so the computer and the TV
  must be on the same network. A VPN on the computer is fine (TubeLoader uses the real network card),
  but "guest" Wi-Fi networks often block devices from seeing each other.
- A TV that is asleep or in standby often doesn't answer. Wake it with its remote first.
- Mesh Wi-Fi and some routers stop devices talking to each other ("AP isolation" / "client isolation").
  If nothing on the network answers, that setting is the likely cause; it's in the router's Wi-Fi settings.
- The file is only read. TubeLoader never changes the person's APK or zip; a Roku zip that needs fixing
  is copied, and the copy is fixed.
- Philibert never runs anything on its own. A fix is offered as a button; removing an app asks twice.

## Android (Fire TV, Google TV, Android TV, NVIDIA SHIELD)
How it works: ADB (Google's Android Debug Bridge) connects over Wi-Fi to the TV, usually on port 5555,
sends the APK and installs it. The first time, the TV asks "Allow debugging from this computer?".

Turning debugging on:
- Fire TV: Settings > My Fire TV > Developer options > ADB debugging ON, and Apps from Unknown Sources
  (or Install unknown apps) ON. No Developer options? Settings > My Fire TV > About, click the device
  name 7 times ("You are now a developer").
- Google TV / Android TV: Settings > System > About > click "Android TV OS build" 7 times. Then
  Settings > System > Developer options > USB debugging ON. Many TVs also need "Network debugging" ON.
- Android 11+ "Wireless debugging": it uses a pairing code once. On the TV: Developer options >
  Wireless debugging > Pair device with pairing code. It shows a 6-digit code and an IP:port; the port
  after the colon is the pairing port (it is NOT the connect port, and both change each time).

Problems and fixes:
- "unauthorized" / "failed to authenticate": the TV hasn't allowed this computer. Look at the TV for
  the prompt; tick Always allow; choose Allow. No prompt? Turn ADB debugging off and on, then reconnect.
  If the TV once said no, revoking helps: Developer options > Revoke USB debugging authorizations.
- "connection refused" / "cannot connect" / "10061": nothing listening on 5555 - debugging is off, or
  the TV is asleep, or (Fire TV) it was turned off by a system update. Turn it back on.
- "timed out": the TV is off/asleep, on another network, or the router blocks it. Wake it; check Wi-Fi.
- "offline": connected but not responding - reconnect; if it stays offline, restart ADB on the computer.
- INSTALL_FAILED_UPDATE_INCOMPATIBLE / "signatures do not match": a copy of the app signed by someone
  else is already installed (e.g. a Play Store or Amazon store version). Only fix: remove the old copy
  (this deletes that app's data on the TV), then install.
- INSTALL_FAILED_VERSION_DOWNGRADE: the TV has a newer version. Install over it with the downgrade
  option (keeps data), or use the newer APK.
- INSTALL_FAILED_NO_MATCHING_ABIS: the APK is built for another processor. Fire TV sticks are mostly
  armeabi-v7a (32-bit) - an arm64-only APK will not install on them. Get the build for the TV.
- INSTALL_FAILED_OLDER_SDK: the app needs a newer Android than the TV has. Fire OS 7 = Android 9 (API
  28), Fire OS 8 = Android 11 (API 30). Get an older version of the app.
- INSTALL_FAILED_INSUFFICIENT_STORAGE: the TV is full (Fire TV sticks have ~5 GB free at best). Remove
  unused apps or clear big caches in Settings > Applications.
- INSTALL_PARSE_FAILED_* / "not a valid APK": the file is damaged or unsigned. Download or build again.
- INSTALL_FAILED_USER_RESTRICTED / Play Protect: the TV blocked it. Allow unknown apps; on Google TV,
  choose "Install anyway" if Play Protect asks.
- INSTALL_FAILED_MISSING_SPLIT: only one piece of a split app was given. Use the .apks/.xapk bundle.
- Installed but not on the Home screen: the app has no TV launcher entry (a phone app). It's still in
  Settings > Applications; TubeLoader tries to open it after installing.
- Opens then closes at once: often a phone app that needs a touchscreen or Google services that Fire TV
  doesn't have. Not something an install can fix.

## Roku
How it works: a Roku isn't Android - it can't take an APK. It takes a "dev channel": a .zip of the
channel's files sent to the Roku's own developer installer (a web page on port 80, user name rokudev,
password chosen by the person). Only one dev channel at a time; a new one replaces the old. The Roku's
control port (8060) says whether developer mode is on and opens the channel; its debug console (port
8085) prints compile errors and crashes - TubeLoader reads it during the install and the first seconds
of the run.

Turning developer mode on (the remote code):
- Home 3 times, Up 2 times, Right, Left, Right, Left, Right. The Developer Settings screen opens.
- Choose "Enable installer and restart", agree to the license, set a developer password. The Roku
  restarts. Write the password down - TubeLoader asks for it (user name is always rokudev).
- Forgot the password: do the remote code again; the same screen lets you set a new one.

The zip (TubeLoader checks it before sending):
- The manifest file must be at the TOP of the zip. The usual mistake is zipping the folder instead of
  its contents; TubeLoader repacks a fixed copy automatically.
- The manifest needs title=, and should have major_version=, minor_version=, build_version=.
- The code is in source/*.brs (a BrightScript channel) and, for a SceneGraph channel, components/*.xml.
- Icons named in the manifest (mm_icon_focus_hd, splash_screen_hd, ...) as pkg:/images/... must be in
  the zip, or the Roku shows a blank tile.
- 7-Zip's LZMA/BZip2 zips can't be read by the Roku; TubeLoader repacks them as normal zips.
- Mac "__MACOSX" folders and .DS_Store files are left out of the copy.

Problems and fixes:
- Control port refused (403) or no answer: "Control by mobile apps" is limited or off. On the Roku:
  Settings > System > Advanced system settings > Control by mobile apps > Network access > Default (or
  Permissive). Also check the Roku is awake and on the same network.
- Developer mode off: do the remote code (above).
- Installer (port 80) not answering although developer mode is on: the installer wasn't enabled - do
  the remote code again and choose Enable installer and restart. Or the Roku is asleep.
- HTTP 401: wrong developer password (user name rokudev). Type it again, or set a new one.
- "Install Failure: Compilation Failed": the channel's BrightScript has an error. The debug console
  shows the file and line ("Syntax Error ... (pkg:/source/main.brs(12))"). It must be fixed in the code
  and zipped again - nothing on the Roku fixes it.
- "Error parsing XML component": a SceneGraph components/*.xml file is broken (unclosed tag, wrong
  attribute). The console shows which file.
- Installed, then "BrightScript Micro Debugger" / "Runtime Error" in the console: the channel crashed as
  it started (e.g. "Invalid value for left-side of expression", "Member function not found"). Fix in the
  code. Opening it again just crashes again - but it's useful after the person has changed something.
- "Identical to previous version": that exact zip is already on the Roku - open it, or change it first.
- Roku TVs (TCL, Hisense, onn. with Roku) work exactly like Roku sticks.

## Safe fixes
The only things TubeLoader runs for Philibert, each after the person taps it:
- reconnect - drop and remake the ADB connection.
- restart_adb - restart ADB on the computer, then reconnect (clears a stuck ADB).
- wake_tv - send the wake key to an Android TV that's connected but asleep.
- open_developer_settings - open Developer options on a connected Android TV.
- retry - try the same step again (after the person did something on the TV).
- retry_allow_downgrade - install over a newer version (keeps the app's data).
- uninstall_then_install - remove the old copy, then install. DELETES that app's data on the TV; only
  for a signature mismatch. Asked twice.
- pair - pair with the code shown on an Android 11+ TV (Wireless debugging).
- roku_replace - send the channel again as a replacement.
- roku_launch - open the dev channel on the Roku.
For a problem in the app itself (an error in a Roku channel's code, a broken zip, an APK for another
processor), there is no fix to offer - explain it and what has to change.
