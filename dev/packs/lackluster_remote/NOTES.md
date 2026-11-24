# Notes for whoever works on this pack

## What it is
The second pack for the existing Lackluster Plus+ gateway (see `lackluster_tv_login/NOTES.md` for the base, the
stand-in for Plex and the headless browser). The base is the app as it runs today, TV sign-in included. The two
sign-in tests are here as **guards** (`PACK.json` `guard_tests`): they pass before and after; verify does not ask
them to fail on the base.

## Design decisions
- **One new file, one new line.** `public/tvnav.js` + a script tag. A 3,000-line page is the worst place for a
  local model to make scattered edits; a new file it owns is the best.
- **Real focus, not a painted cursor.** The page already uses focus (Watch Live gets it; the channel crawl stops
  while the guide has it), and Android's WebView delivers the D-pad as arrow keys to the focused page.
- **Two movement rules.** Everywhere: nearest thing in that direction (`nearest`). In the guide: by row and by
  programme, keeping a screen x (`anchorX`) so Up/Down do not drift across programmes of different lengths.
- **Scope.** The top-most open layer is the only place the highlight can go (`scope`).
- **Back is a function** (`window.tvBack()`), because a Fire TV app receives Back in its own code, not as a key
  in the page. Escape calls the same function, which is how the tests press Back.

## What the tests do
- `tests/_t.py`: the stand-in also plays Tunarr now: 12 channels with programme lengths 30/120/60/90/none/45...
  minutes, all started 20 minutes ago, titled `Channel N show M`. So the test can say exactly which programme is
  under a given time on each channel.
- `br.press("down", "ok", ...)` sends real key events through the browser's debugging port.
- `test_remote_basics.py` walks the screen: from every highlighted thing it tries all four arrows and collects
  what it reaches. The list must contain every control a person needs. This one check replaces dozens.
- Things a headless browser cannot show: a real stream (the stand-in has none, so play/pause is checked by
  counting calls to the video's play() and pause()), and a real Fire TV remote's key codes.

## Mistakes made while writing this (2026-11-13), so they are not made again
- The tests first put the highlight on a div with `el.focus()`. A div without a tabindex cannot take focus, so
  the highlight silently stayed where it was and seven checks failed for the wrong reason. Use `br.focus()`.
- The reference remembered the highlighted cell's x in a `focusin` handler, which runs BEFORE the guide scrolls
  to reveal the cell. After a redraw the highlight came back one programme off. It is remembered again after the
  scroll. Found only because the test scrolled the guide before redrawing.
- At 960x540 the info drawer's title was scrolled out of sight (the page focuses Watch Live). All checks were
  green; a screenshot showed it. Same lesson as the sign-in pack: look, then write the check.

## Proved (2026-11-13, scratch copy, each step alone and in order)
- T01 alone: basics 42 pass; guide and player tests fail. T01+T02: basics 42, guide 31; player fails.
  All three: 42 + 31 + 54, and the sign-in guards 38 + 39.
- On the base all three remote tests fail at "tvnav.js is not there".

## 2026-11-13: the first build stuck on T01, and it was the tests' fault
- Six attempts (2.4 h) failed on `still one tab, no popup - got 2` in the sign-in guard test. Cause: a fresh Edge
  profile is not empty on this PC. Edge signs in the Windows account and syncs the owner's extensions into it;
  their welcome tabs counted as popups and their content scripts raised errors inside the page under test. It
  did not show the day before (sync is slower than a 25-second test, some days).
- Fix in `tests/_t.py` (both Lackluster packs): `--disable-extensions --disable-sync --disable-default-apps
  --disable-component-extensions-with-background-pages --disable-background-networking`; attach to the
  `about:` page; `pages()` ignores `edge:` and `chrome-extension:` pages.
- Also hardened: the Browse column slides open with a CSS transition; the test now waits for its width instead
  of sleeping half a second.
- Also seen: the builder tried to write the whole 180-line file in one reply and was cut off twice. A
  convention now says to write a new file in steps.
- Rule for any pack that drives a browser: **a test browser must be proven empty** (list its tabs after 20
  seconds) before its tab count is used as evidence of anything.

## 2026-11-14: built
- After the test fix the local builder (q36c-nd128k) passed T01, T02 and T03 on the first attempt each, 20 minutes
  in all. It wrote its own file (384 lines), using the functions the briefs gave "exactly" as given. Read line by
  line: no faults. Two small differences from the first reference, both harmless: Play/Pause is ignored until
  remote mode is on, and Escape does nothing while the caret is in a text box. `reference/` is now that build.
- Not yet tried on a real Fire TV remote or with a real stream.

## 2026-11-15: the guide test split in three
- `tests/test_remote_guide.py` (31 checks) is now `test_remote_guide_moves.py` (19: along a channel, the column,
  hidden rows), `test_remote_guide_screen.py` (10: always on screen, scrolling along the day, OK) and
  `test_remote_guide_place.py` (6: back after a redraw, out of the guide and back). The checks are unchanged; each
  new file repeats the sign-in preamble, so there are 35 in all. The plan's T02 is now T02, T03 and T04, each with
  the parts of the old brief it needs; the player is T05.
- Why: on blind4 (a local plan) the old T02 stuck after nine attempts of 40 minutes, best 29 of 31, even when
  salvage let each attempt start from the best one. The two checks left were one about scrolling and one about
  redrawing: two different problems inside one task.
- Proven: verify says SOUND (all fail on the base, 208 pass on the reference). The reference cut back to T02's
  work alone passes moves (19/19) and fails screen and place; cut back to T02+T03, it passes screen as well and
  fails place. Each task passes on its own work, and only on it.

## 2026-11-24: blind7 graded 131/131 (208/208)
- Plan-only blind trial. The local q36c-nd64k wrote the plan and briefs from the spec alone, and q36c-nd128k built it.
  The pack's hidden tests: 131 of 131 new checks and 77 of 77 guard checks. Two builds (6.1 h and 4.5 h), the
  builder ran at 78 to 84 tok/s, and no split was needed.
- What carried it:
  - T02 was rescued by salvage reading OpenCode's own snapshot. Its attempt 2 was a full 19/19 pass, rejected
    only for a scratch file. The old edit replay rebuilt it as broken JS (1/19), because the builder had also
    changed files from the shell.
  - T05 was rescued by a mend note: salvage kept a 53/54 start that broke 1 older check, and the next attempt
    passed first time.
- Score so far: blind5 131/131, blind6 129/131, blind7 131/131 (n=3 plan-only trials since the tools settled).
- The look step flags guide cells under the sticky time ruler on "browse column". That is the look script's
  scroll position (channel 3 half under the header), not a layout fault. blind6's look shot that screen with the
  player open, because the look step is still not deterministic.
