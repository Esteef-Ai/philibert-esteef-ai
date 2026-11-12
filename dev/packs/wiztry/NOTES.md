# WizTry pack - notes for whoever works on it next

## History
- 2026-11-08: plan and tests written by Claude before any code (6 tasks; 109 checks plus the exe test today).
- 2026-11-09: built by the foreman in `G:\WIZTRY\foreman`. T01, T03, T04 by a 27B model through ND's own
  loop; T02, T05, T06 by OpenCode + Qwen3.6 35B (`opencode/q36c-nd128k`, thinking off). That build is
  `reference\` here.
- That build needed help: two test tightenings (a treemap that did not nest; a window that did not use the
  layout) and two fixes to T05's brief (cushion drawn on top of the fill; folder fill drawn before its
  files). They are all in this pack now. A clean, unhelped run of this pack has not happened yet:
  `wiztry11` is that run.

## Things the build taught us
- T02 (treemap): Qwen3.6 with thinking on out-thought every output limit. Thinking stays off for the builder.
- T05 (window) is the big one: 45 minutes, and the brief spells out drawing order because green tests once
  hid a treemap where every file was painted over.
- Check labels are fixed strings; measured numbers go in `got`. The foreman compares labels between runs.

## Known gaps in the tests
- Nothing checks the look (colors, borders) beyond what the brief states.
- test_build.py takes a minute or two and needs PyInstaller in the workspace venv.
- `studio_pack.py verify wiztry` (2026-11-12): the tests catch 16 of 30 planted small bugs (53%). Real gaps it
  showed: no read-only file in the fixture (a scanner that skipped read-only files would pass), and human()
  is never checked at exactly 1024. Most other misses are pixel paddings in the treemap that change nothing
  a user would notice. Details: VERIFY.json.

## 2026-11-12: the clean baseline (C:\PCodeTest\wiztry11)
- 6 of 6 tasks passed on the first attempt, 32 minutes, no help, restricted builder shell
  (OpenCode + `q36c-nd128k`, thinking off). Report on the fixture 5 of 5; 119 checks pass including the exe.
- The window scans, fills the folder tree and draws the treemap (255 blocks, 9 colors).
- DEFECT the tests do not see, in this build AND in `reference/`: the File Types list starts with no width
  (the tree pane takes the whole row; the list has its 10 rows but is 1 pixel wide until the splitter is
  dragged). Cause: the panes are added without weights. To fix in the pack: T05's brief must give the two top
  panes weights, and test_app.py must check the list's width on a mapped, off-screen window (it tests a
  withdrawn window today, where nothing has a size).

## 2026-11-12: tweak 01_usable_window (tweaks/01_usable_window/)
- The owner opened the wiztry11 exe: Browse did nothing; typing C: and pressing Scan scanned the folder the
  exe was started from. Causes and fixes are in tweak.json ("why"). Two new tasks, T07 and T08, with 33 checks.
- Lesson for every window pack: the tests must (a) check sizes on a mapped, off-screen window, never a
  withdrawn one; (b) collect button errors with report_callback_exception; (c) never import a module on the
  app's behalf before checking the app imported it (tkinter.filedialog).
- When the tweak has built cleanly: fold it into the pack (T01/T04/T05 briefs, the two test files, a new
  reference from wiztry11) and run verify.
