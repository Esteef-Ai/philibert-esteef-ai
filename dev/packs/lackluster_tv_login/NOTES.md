# Notes for whoever works on this pack

## What is different about this pack
- It is the first pack for an **existing app** and the first that is **not Python**. `PACK.json` has `base`
  (the app as it runs today, copied into every new workspace) and `base_links` (`node_modules`, linked with a
  junction instead of copied). "Fails on an empty project" becomes "fails on the app as it is today".
- The base is `C:\PCodeTest\_bases\lackluster_gateway`: a copy of the gateway folder from the server
  (`dist`, `public`, `node_modules`, `package.json`), taken 2026-11-12. **Never copy `.env` or `gateway-data`
  into it**: they hold the session secret and people's Plex tokens.
- The server's `src/` (TypeScript) is older than its `dist/` (features were added straight into `dist`), so
  `dist/*.js` is the real source. There is no build step.
- `reference/` holds only the four files the plan changes; verify lays them over the base.
- Planted-bug scoring (mutation) is Python-only and is skipped here.

## How the tests work
- `tests/_t.py` has `FakePlex` (plex.tv, app.plex.tv, the Plex server and Tunarr on one local port), `Gateway`
  (the real `node dist/server.js` on a free port, database in the temp folder) and `Browser` (headless Edge over
  its debugging port; `websocket-client`). No window appears; nothing talks to the real Plex.
- The seam that makes this possible is task T01's first step: `PLEX_TV_URL` and `PLEX_AUTH_APP_URL`. On the
  untouched base the gateway ignores them, so `test_signin_api.py` there asks the real plex.tv for one pin
  (harmless, no account involved) and then fails, as it must.

## Facts checked against the real Plex (2026-11-12)
- `POST https://plex.tv/api/v2/pins` without `strong=true` answers a 4-character `code`, `expiresIn: 900` and
  `qr: https://plex.tv/api/v2/pins/qr/<code>` (a PNG, 200).
- Not checked, because it needs a real sign-in: that Plex's sign-in page honours `forwardUrl` when the address
  uses `#!?` (the app's existing form) and sends the browser back. The owner tries this on the real server.

## Lessons
- 2026-11-12: all checks passed on the first reference and the code screen still ran off the top and bottom of
  a 720-line screen. A screenshot found it; the check "everything is on screen at 960x540" was added after.
  Look at the page, then write the check for what you saw.

## Deploying (the owner does this, or says so)
The four changed files go to the server's `LacklusterPlus\gateway` (keep a dated `.bak` of each, as the folder
already does), then restart the service `LacklusterPlusGateway`. `public/index.html` alone takes effect at once,
but it needs the new routes, so copy `dist` first and restart before the page.

## 2026-11-12/13: built and live
- The local builder (q36c-nd128k) passed T01 and T02 on the first attempt, 5 minutes in all. Diff read, tests rerun,
  screenshot compared: nothing to fix. `reference/` is now that build.
- Deployed to the server on 2026-11-12 (backups end `.bak-20261112-tvlogin`); the owner restarted the gateway and
  reported it looks good. The base snapshot (`C:\PCodeTest\_bases\lackluster_gateway`) was updated to match the
  live app, so the NEXT pack for this app starts from the new sign-in. This pack's own "fails on the app as it is
  today" check no longer holds against that base; it is finished work, kept as a record.
