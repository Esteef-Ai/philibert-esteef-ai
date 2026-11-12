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

## 2026-11-12: tweak 01 folded in; tweak 02_big_folders written
- Tweak 01 built in 3 minutes (T07, T08 first attempt). Folded into the pack: 8 tasks, 152 checks, reference
  refreshed from wiztry11. The owner confirmed Browse works.
- The owner then scanned a drive and the window hung. Cause and numbers are in tweaks/02_big_folders/tweak.json.
  The treemap's squarify, written by the builder in T02, passed every test and was still quadratic and
  produced slivers at scale: the fixture has 91 files, and nothing tested size. Lesson for every pack: test
  each algorithm at the size real use will give it, with a time limit.
- Known and accepted: Tk needs about 0.6 to 0.9 s to paint 8,000 blocks the first time. A pause, not a hang.

## 2026-11-12: tweak 02 folded in
- Built on wiztry11 in 38 minutes: T09 on its second attempt (the first failed two checks of its own test),
  T10 on its first. An earlier launch was stopped: the first cut of the tweak had the block-cap change in
  T10, so T09 could not pass alone. Lesson, now a rule: prove each task of a tweak alone, in order.
- Measured on C:\Windows (199,000 files): the status line counts every 2,000 files; longest freeze 1.5 s
  (was about 7 s); 3,664 file blocks (was 478). The owner tested the exe and asked for the fold.
- The pack now: 10 tasks, 181 checks, reference = wiztry11 at T10. verify: 28 of 30 planted bugs caught (93%;
  it was 53% before the two tweaks added tests at real size and on a mapped window).
- A fresh build from this pack still builds the slow T02 layout first and replaces it in T09. That is the
  proven path; merging the briefs would be cleaner but is unproven.

## 2026-11-12: tweak 03_tree_and_tools written (tweaks/03_tree_and_tools/)
- The owner asked for the whole folder path when a block is clicked, a tree that cascades from the root, and
  one WizTree-style tool of each kind. Reading the code showed the tree had never worked below its first
  level and double-click zoom was never built: test_app.py only called select_node() and zoom() and looked at
  the selection, never at where the row sat or whether a person could get there.
- Tools chosen: Delete to the Recycle Bin (asked, guarded), Show in Explorer, Copy path, Export to CSV.
- This ends "read-only" as a rule: the tweak changes the rule in the plan, in the foreman's notes and in the spec
  (studio_pack.py tweak now does that from "rules", "spec" and "spec_add" in tweak.json).
- Safety of the delete tests: the guard checks run first and the test stops before any real delete if one
  fails; real deletes happen only inside a tempfile.mkdtemp() folder and only through the Recycle Bin
  (each run leaves a few tiny pc_test files there). Explorer is never opened and tk_popup never called.
- Lesson for every pack: test what a person does (open a row, click a block, press a button) and where the
  result lands, not only that a method returns something.
