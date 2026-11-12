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
