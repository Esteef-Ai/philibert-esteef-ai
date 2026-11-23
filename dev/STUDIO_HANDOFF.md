# Philibert Code Studio: handoff (written 2026-11-14 by Claude, for whoever continues)

Read this file first, then `STUDIO_ROADMAP.md` (the plan of record, older and longer), then the `NOTES.md` of the
pack you will touch and the `.studio/HANDOFF.md` of the workspace in play. Everything below is what I know, what I
measured, what I only believe, and what I would do next and why. Where I say "believe" I have no measurement.

---

## 1. The goal, in the owner's words

"Create a local coding app that is as useful as Claude Code." The owner describes an app (a website, a Windows app,
a web app, a networking tool, now a TV app), a local model builds it, and the owner then asks for changes. Speed is
not a priority: a build may take a night. The long-term goal is that nothing but local models is involved. For now a
cloud model (Claude) may write the plans and the tests.

Everything the studio makes carries the brand **Esteef.Ai** (title, byline, exe properties), a dark theme, and muted
traditional colours (never neon, never pastel).

## 2. The rules of working with this owner (these are not optional)

- **The owner launches every unattended model run.** That means `studio_pack.py build`, the foreman, OpenCode,
  `studio_bench.py run`, `studio_blind.py plan` and `tests`. An assistant prepares the workspace, prints the exact
  command, and stops. An assistant may run anything that calls no model: `verify`, `status`, `look`, `grade`,
  `check`, `report`, `stage`, `--dry`, the self-test.
- **Commands are given for cmd.exe**, one per line, as `"C:\Heretic\venv\Scripts\python.exe" "<script>" ...`,
  never with a leading `&` (that is PowerShell and fails in cmd).
- **`G:\!Ai\ND3` is read-only.** It is the owner's development copy. The foreman (`nd_foreman.py`) lives there. If a
  change to the foreman is needed, describe it and let the owner or the linked foreman session make it.
- **Nothing is pushed** without the owner saying so. Philibert has about 37 local commits ahead of its remote.
- **Philibert ships nothing personal.** No history, memory, vault, config or personal paths. See section 9 for one
  open item.
- **Never read out or copy** Lackluster's `gateway\.env` or `gateway-data` (they hold a session secret and people's
  Plex tokens). Changes to the live server copy (`N:\LacklusterPlus`) and service restarts need the owner's yes.
- No registry or system-setting changes without permission. No windows popped onto the owner's screen. Confirm
  permanent deletions first. Scratch files go in a scratch folder, not in the repos.
- Write for a reader who was not there: plain words, numbers with their n, and always say what was NOT proven.
- **Never rank a model or a setting on fewer than 5 runs.** This project has been fooled by n=2 more than once.
- **Measure the baseline before calling anything a regression.**

## 3. How the machine works (one paragraph each)

- **Plan pack** (`dev/packs/<name>/`): a fixed job with fixed judges. `PACK.json` (kind, base, guard tests, look,
  device), `SPEC.md` (what the app must be), `plan.json` (tasks: id, files it may change, its test, a long brief),
  `tests/` (plain Python scripts printing `PASS`/`FAIL` lines and `N passed, M failed`), `reference/` (a build known
  to be good), `NOTES.md`. `BUILDER_RULES.json` holds the working rules per app kind.
- **Workspace** (`C:\PCodeTest\<name>`): made from a pack by `studio_pack.py new`. A git repo. `.studio/` holds the
  journal, the handoff and the look pictures; `.foreman/` holds the foreman's state.
- **Foreman** (`G:\!Ai\ND3\nd_foreman.py`): gives one task at a time to the builder, runs four gates (`scope`: only
  allowed files changed; `lint`; `tests`: the task's test; `broke`: no older test broke), commits a pass, undoes and
  retries a fail. It looks for a `STOP` file only between tasks.
- **Builder**: OpenCode with the local model `opencode/q36c-nd128k` (Qwen3.6 35B, thinking off). Its shell is
  restricted by `opencode.json`; `build` proves those restrictions hold before it starts.
- **Bases are frozen.** A pack that changes an existing app points at a frozen copy of that app as it was BEFORE the
  pack's change (`C:\PCodeTest\_bases\..._before_<x>`). Never refresh a base from the live app: I did once and it
  silently broke two packs (the "old app" already contained the new feature, so tests that must fail passed).

## 4. What is measured (do not re-argue these without new numbers)

| Claim | Evidence |
|---|---|
| The builder is good when the plan and tests are good | T3 feature-add: 8.27/9 over 15 runs in OpenCode. Same model in ND's own loop: 5.0 |
| Claude plans + local builds works on real apps | ChordShift 12/12; WizTry 6/6 first try in 32 min; Lackluster sign-in and remote: 5/5 tasks first try, 281 checks |
| Green tests are not a working app | WizTry passed everything and was unusable in the first minute (dead Browse button, 1-pixel pane) |
| A test can be the thing at fault | The Edge build burned six attempts on a test that failed on untouched code |
| On-device tests find what source checks cannot | Fire TV pack, first run on the real TV: found a blank screen after a dead address (see section 6) |
| A local model cannot yet write the plan and tests | 10 nights of WizTry (wiztry2..10), plus the two blind trials of 2026-11-14 (section 7) |

**The conclusion that drives the plan:** the builder and the foreman are sound. The weak link is the planner and,
above all, the test writer. Every tool built on 2026-11-14 is aimed at that link or at "green is not working".

## 5. The six tools built on 2026-11-14 (commit eccce62 and after)

All in `G:\!Ai\Philibert\dev\`. `studio_selftest.py` proves the first five with no model (about 8 minutes; it uses
`C:\PCodeTest\lackluster2`).

| Tool | Command | State |
|---|---|---|
| **Look step** `studio_look.py` | `studio_pack.py look <ws>`; runs by itself at the end of `build` | Works. Photographs every screen at 3 sizes, audits layout in the page, reports only findings that are NEW against the app before the change. **Open fault: it is not deterministic** (section 8, item 1) |
| **Fast lane** | `studio_pack.py quick <ws> "<request>" --files a,b` | Workspace side proven. **No model has built a quick change yet.** Its own test is weak by design (files changed and still parse); the older tests and the look step are the real judges |
| **Replay bench** `studio_bench.py` | `new <bench> --packs a,b [--model m] [--n 3]`, then the owner runs `run <bench>`, then `report` | Adoption and reporting proven on the existing builds. **No fresh bench has been run.** `C:\PCodeTest\bench` is empty |
| **Suspect tests** `studio_suspect.py` | runs beside `build`; result in `status` | Proven on 7 made-up cases. "Certain" = a must-pass test fails on a clean copy of the start commit. "Likely" = the same failure twice from different replies. It cannot stop the task in flight (the foreman only reads STOP between tasks) |
| **Blind planner trial** `studio_blind.py` | `stage`, `plan`, `tests`, `check`, (build), `grade` | Works as a measuring tool. Two real runs, both failed before the build (section 7) |
| **Android kind** | pack `lackluster_firetv` | Reference proven on the real TV: 83 checks, 25 on the TV. **No model has built the pack**, and its 3 tasks were never proven one at a time in order |

## 6. Lackluster Plus+ on Fire TV (the product side, for context)

- The web app is live on EsteefServer (`N:\LacklusterPlus`; the real source is `gateway\dist` and
  `public\index.html`). TV sign-in by code and full remote navigation (`public/tvnav.js`) are deployed.
- The Fire TV app is a one-class WebView wrapper built without Gradle: `C:\PCodeTest\lackluster_firetv`
  (`build_apk.py`, output `out\LacklusterPlus-FireTV.apk`). **The signing key `signing\lacklusterplus.jks` must be
  kept**: without it no update can be installed over the app.
- The owner's TV: TCL, model AFTDEC012E, Fire OS 8, `192.168.0.48:5555` over adb. It has **v1.2** installed.
  **v1.3 is built but not installed**; it fixes a blank screen after typing an address nothing answers at. Install:
  `"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" -s 192.168.0.48:5555 install -r "C:\PCodeTest\lackluster_firetv\out\LacklusterPlus-FireTV.apk"`
- Not yet confirmed by the owner: the wide home-screen tile (the TV caches the old picture until it restarts), and
  Back / Play-Pause with a real stream playing.
- Facts learned on the TV are in `packs/lackluster_firetv/NOTES.md`. The important ones: a Fire TV reports 960x540 to
  a page, so the app draws a larger frame scaled down; Fire TV shows the app ICON (not the leanback banner) in its
  wide tile for a sideloaded app.
- To run the on-TV checks: lay the reference out as a workspace (base + `reference/` + `tests/`), set
  `LP_DEVICE=192.168.0.48:5555`, run the three tests. They install a TEST copy (`ai.esteef.lacklusterplus.test`)
  beside the real app and remove it afterwards. `studio_pack.py verify` does NOT use the TV: it proves the 58
  static checks only.

## 7. The blind planner trials: the most important open experiment

The question: how far is "fully local"? The local model (`q36c-nd64k`) gets the spec, the app's source and the test
helpers, and writes the plan and the tests. The pack's own tests, which it never sees, grade the build.

**Run 1, `C:\PCodeTest\blind1`.** Plan: 2 tasks; the whole remote in task 1, and task 2 was "write the end-to-end
test" with no files. The foreman refused the plan. Nothing was built. Both test files fail on the known-good
reference (1 of 2 and 6 of 11 checks), so a correct build would have been rejected anyway. Time: 28 min for the
plan, 26 and 38 min for the tests.

**Changes after run 1** (commits bce6f8d, 3ee091a): the planner prompt demands 2 to 5 slices, at least one app file
per task, no testing tasks, only names seen in the source or spec; the test-writer prompt says check only what the
spec states, behaviour not spelling; file-less tasks are dropped with a journal line; `grade` separates new work
from guard tests and says plainly when nothing was built; `build` says plainly when the foreman refuses a plan.

**Run 2, `C:\PCodeTest\blind2`.** The plan is much better in shape: 3 slices (foundation; guide; player, fade and
Back), each naming `public/tvnav.js`, 19 minutes. Then:
- The test for T01 took **58 minutes** and is again not sound by reading: it demands a global called `tvnav` and a
  function `tvnav.isTV()`, neither of which is in the spec (the pack's real names are `window.tvNav` and
  `window.tvBack`), and it never signs in before driving the page.
- The tests for T02 and T03 **were never written**. Cause found afterwards (section 11): one model call may take
  an hour by default, T01's took 58 minutes, T02's ran over and the exception ended the whole run.
- `check` therefore says NOT READY, correctly. **Do not build blind2 as it stands.**

**What the two runs say (n=2, one model, one pack: a direction, not a ranking):**
1. Prompt rules fix the *shape* of a plan. That part moved in one step.
2. The test writer invents names. With nothing but a spec in prose, it has no way to know the contract.
3. One test file costs 25 to 60 minutes of model time and is usually wrong. This is the same wall WizTry hit for
   ten nights.
4. Part of the fault is mine: the spec does not carry the contract. `window.tvNav` and the path `/tvnav.js` are in
   the hidden tests and in no document the planner sees. `grade` counts these as "contract misses".

## 8. What I would do next, in order, and why

**Items 1, 2, 4 and stage A of item 5 are DONE: see section 11. Start at item 3, then the plan-only trial in section 11.**

Each item says what "done" looks like. Items 1 to 3 are small and unblock the rest.

1. **Make the look step deterministic.** On blind1 it reported one NEW fault (a covered channel logo at 1280x720,
   browse column) and 2 "gone" on an app nobody had changed. Until this is fixed every look report is suspect.
   Likely causes: the guide's content depends on the clock, or a screen is photographed before layout settles.
   Fix idea: run the audit twice per screen and keep only findings present both times; freeze the clock in the
   driver; and add to the self-test "the same app twice gives 0 new and 0 gone". Done = that self-test passes 5
   times in a row.
2. **Find why blind2's T02 and T03 tests were not written** (see section 7), then make `tests` say why a file was
   not written and continue with the next task.
3. **Install v1.3 on the TV** (the owner runs the command in section 6) and get the owner's word on the tile, Back
   and Play/Pause with a real stream.
4. **Put the contract in the spec.** Every pack's `SPEC.md` gets a short section "Names that are fixed": files,
   globals, ids, routes, exactly as the tests use them. Add a `verify` check: every quoted name a test demands to
   exist must appear in `SPEC.md`. This is fair to a local planner and to a human reader, and it removes the
   "contract misses" from the blind grade. Done = `verify` fails a pack whose tests name something the spec lacks.
5. **Stop asking the local model for tests before the code exists.** This is the roadmap's long-standing
   conclusion and both blind runs confirm it. The staged handover I believe in:
   - Stage A (try next): local model writes the PLAN only; the pack's own tests judge each task. This needs the
     tasks of the local plan mapped onto the pack's test files; simplest is to tell the planner the test file
     names and what each one covers (not their content) and have it plan one task per file. Done = a blind build
     where `grade` shows the new-work score, 3 runs.
   - Stage B: tests written AFTER each task's code exists, by a second model call that sees the code, and judged
     for soundness on the spot (must pass on the new code, must fail on the code before the task: both can be
     checked mechanically with `git stash` or a worktree). A test that fails that double check is thrown away, not
     given to the builder.
   - Stage C, last and maybe never: tests first.
6. **Run the first real bench** so there is a number for the builder on real packs, not only T3. The owner runs:
   `studio_bench.py new first --packs lackluster_tv_login,lackluster_remote --n 3`, then `run first`. Done =
   `BENCH.md` with 6 builds. After that, a bench is how every change to the builder, the rules or the model is
   judged (context size, a second GPU, a new model).
7. **Use the fast lane for real.** Pick three small real requests on Lackluster or WizTry and build each with
   `quick`. Measure: minutes, attempts, and whether the look step and old tests caught anything. This is the mode
   the owner will use daily if the studio is to feel like Claude Code. I believe the weak change-proof test is
   acceptable because the guards carry the weight; that belief has no evidence yet.
8. **A dispute path for the builder.** Today a builder facing a wrong test edits protected files or burns its
   attempts. Let it reply `DISPUTE: <test>, <line>, <why>`; the foreman records it and moves on; the suspect
   detector checks it. Needs a small foreman change (owner's copy: ask).
9. **Let the foreman check STOP inside a task**, so a "certain" suspect finding ends the attempt at once instead of
   after it. Same: owner's copy.
10. **Build the Android pack with the local model** (the owner runs `new` and `build` on `lackluster_firetv`, with
    `LP_DEVICE` set and the TV awake). Before that, prove its tasks one at a time in order (T01 alone must pass
    T01's test and fail the others).
11. **Vision in the look step.** `--vision <model>` is written and has never run. Worth trying only after item 1.
12. **The Studio window** (`dev/PHILIBERT_CODE_STUDIO.md`): import a pack, watch the build, read the handoff, press
    "quick change". All the parts it would show now exist as commands.

### Ideas I have not started (my opinion, unmeasured)
- **Record-and-replay for acceptance.** The owner uses the app once while a recorder captures clicks, keys and
  screenshots; that recording becomes a test. It turns "the owner found it unusable in a minute" into a permanent
  check without anyone writing test code. I think this is the single most valuable idea on this list.
- **Packs as worked examples.** Give the planner the most similar finished pack (spec, plan, one test) as an
  example. Cheap to try once Stage A exists.
- **A second builder model as reviewer of the diff**, not of the tests: "does this diff do what the brief says, and
  nothing else?" The foreman notes say green tests on pages are not enough and that a design review once gave a
  false positive, so this needs the bench to judge it.
- **An "explain this app" step** after each build: a short generated map of the code kept in the workspace, so a
  later quick change starts from a map instead of reading every file.

## 9. Open items and warnings

- **A home-network address is in the repo.** `http://192.168.0.184:9191` (the owner's server) is in
  `packs/lackluster_firetv/reference/app/res/values/strings.xml` and in that pack's plan. Harmless while the repo is
  local. Before any push, replace it with a placeholder (and the test that reads `default_server` still passes,
  since it reads the value from the file).
- `brand/round3/painted/` is untracked in Philibert. I did not make it and did not touch it.
- `C:\PCodeTest\blind1` and `blind2` are failed trials kept as evidence. Do not build either.
- The scratch scripts I used live in a temp folder that will be cleaned. Nothing there is needed: the tools are in
  the repo.
- Git Bash heredocs halve backslashes and have corrupted patches here several times. Write patch scripts to a
  file with an editor tool, then run them.
- `NeuralDock_launcher.py`, `NeuralDock_ui.html` and `elena_mark.js` are CRLF: never `sed -i` them.

## 10. Where things are

| What | Where |
|---|---|
| The tools | `G:\!Ai\Philibert\dev\studio_*.py` |
| Packs | `G:\!Ai\Philibert\dev\packs\` (wiztry, lackluster_tv_login, lackluster_remote, lackluster_firetv) |
| The plan of record | `G:\!Ai\Philibert\dev\STUDIO_ROADMAP.md` (its last section describes the six tools in more detail) |
| Workspaces, bases, benches | `C:\PCodeTest\` (`_bases\`, `bench\`, `lackluster1`, `lackluster2`, `blind1`, `blind2`, `wiztry*`) |
| The build log | `C:\PCodeTest\overnight\overnight.log` |
| The foreman (read-only) | `G:\!Ai\ND3\nd_foreman.py` |
| The Fire TV app | `C:\PCodeTest\lackluster_firetv\` |
| The live web app | `N:\LacklusterPlus` (EsteefServer) |
| Recent commits | eccce62 (the six tools), 9441620 (TV checks proven, app fix), bce6f8d and 3ee091a (blind trial fixes) |

## 11. Progress after this file was first written (same day, evening)

Done, each proven without a model, all committed locally:

- **Item 1, the look step is stable.** Every app is now walked twice (`PASSES = 2` in `studio_look.py`). A finding
  counts only when every walk shows it; one that comes and goes is kept apart as `unstable`, never counts as new,
  and still counts as "was there before". Measured: the same app looked at 3 times gave 28 findings each time and 0
  new between any two runs; the self-test now holds that as a check (look: 7 of 7). I could not make the original
  false alarm happen again, so the cause is not known, only guarded against. A look takes twice as long (about 80 s
  per app on Lackluster).
- **Item 2, why blind2 lost two tests.** `call_model` allows 3600 s. T01's test took 3474 s; T02's ran over, and the
  uncaught exception ended the run before T01 was even journalled. Now: 3 hours per call, a failed call is logged
  and journalled and the next task goes on, each test file is committed as it is written, `tests` run again keeps
  what exists.
- **The local model was far too slow in both trials, and that is a finding of its own.** 3.6 and 6.6 tokens a
  second, where this model gives about 50 on a free machine (measured 2026-11-02). Either something else was using
  the graphics card (Discord, the x265 worker) or `q36c-nd64k` does not fit on it at a 64K window and ran partly on
  the processor. `studio_blind.py` now prints tokens a second and says so when it is under 15. **Before the next
  trial: close what uses the card, start the plan, and look at `ollama ps`; it must say 100% GPU.** If it does not,
  try `--model q36c-nd32k` (the planner prompt is about 23,000 tokens and needs room for its thinking, so 32K is
  tight but may do).
- **Item 4, the spec carries the contract.** `studio_pack.py verify` has a step 4: a global (`window.x`), an element
  id, a data- attribute or a served file that a non-guard test needs, that the app before the change lacks, and
  that `SPEC.md` never gives, makes the pack NOT SOUND (`contract_gaps` in `studio_pack.py`). It found
  `window.tvNav` missing from the remote spec and seven ids missing from the sign-in spec. Both specs gained a
  section "Names that are fixed". All four packs now report no gap. Write that section in every new pack.
- **A fragile parser, fixed.** A test's summary was read as the END of stdout+stderr. A stand-in server's thread
  printing "connection reset" after the summary turned a 38-of-38 pass into "crashed". The parsers in
  `studio_pack.py`, `studio_suspect.py` and `studio_blind.py` now take the last LINE that is a summary, and the
  stand-in servers in the three Lackluster packs no longer print that noise. **Not checked: the foreman's own parser
  (`G:\!Ai\ND3\nd_foreman.py`, read-only). If a build ever shows a test "crashing" with all PASS lines above it,
  look there first.**
- **Item 5, stage A: the plan-only trial.** `studio_blind.py stage <pack> <ws> --plan-only`. The workspace gets the
  pack's own tests. The planner is shown each test file's name and the plain-words label of every check, never the
  code, and must write exactly one task per test file, in order. There is no `tests` step. The guard tests ride on
  the first task, as in a cloud plan. `check` refuses a plan whose tasks do not match the files. The build is judged
  by the same tests as a cloud-planned build, so it compares like with like: only the briefs differ. Self-test:
  blind 13 of 13.

**Waiting for the owner to launch** (`C:\PCodeTest\blind3` is staged, plan-only, from `lackluster_remote`):

    "C:\Heretic\venv\Scripts\python.exe" "G:\!Ai\Philibert\dev\studio_blind.py" plan "C:\PCodeTest\blind3"
    "C:\Heretic\venv\Scripts\python.exe" "G:\!Ai\Philibert\dev\studio_blind.py" check "C:\PCodeTest\blind3"
    "C:\Heretic\venv\Scripts\python.exe" "G:\!Ai\Philibert\dev\studio_pack.py" build "C:\PCodeTest\blind3"
    "C:\Heretic\venv\Scripts\python.exe" "G:\!Ai\Philibert\dev\studio_blind.py" grade "C:\PCodeTest\blind3"

How to read the result. The number to compare with is the cloud-planned build of the same pack
(`C:\PCodeTest\lackluster2`): 3 of 3 tasks on the first attempt, 204 of 204 checks. In `grade`, "THE NEW WORK"
is the score (127 checks when all three test files run to the end); the 77 guard checks are no credit. One run is
an anecdote: three or more before saying what a local planner can do. If the plan is refused or a task sticks,
read the brief of that task next to the pack's own brief for the same test file (`packs/lackluster_remote/plan.json`):
the difference is what the planner prompt lacks. My expectation, unmeasured: the acceptance labels give the planner
the names it used to invent, so the plan will be buildable, and the first task (31 checks, the most rules) is where
it will stick.

Still open from section 8, in order: 3 (install v1.3, the owner), the plan-only run above, 5 stage B (tests written
after the code, checked mechanically), 6 (first bench), 7 (three real quick changes), 8 and 9 (foreman changes, the
owner's copy), 10 (local build of the Android pack), 11 (vision), 12 (the Studio window).

## 12. The first plan-only run (blind3, night of 2026-11-14) and what was built from it

**Result: a valid plan, nothing built.** `C:\PCodeTest\blind3`, planner `q36c-nd64k`, builder `q36c-nd128k`.
- The plan took 165 s (45 tokens a second: the card was free) and `check` said READY. Three tasks, one per test
  file, real names from the spec and the labels (`window.tvNav`, `tv-nav`, `#options-dropdown`, `isTvBrowser()`).
  This is the first local plan the foreman accepted. The plan's SHAPE is solved.
- T01 stuck after 6 attempts (3, then one fresh round of 3); T02 and T03 were skipped. Four attempts ran out of
  their 40 minutes. Best: 27 of 42 checks, twice. In both, every "arrows alone reach X" check failed with the
  highlight still on the first programme: the builder never got "nearest element in a direction" right.
- The builder's model ran 47% on the processor (`ollama ps`), so each attempt was slower than usual.

**Why, by comparison with the build that passed.** Same tests, same builder, same 40 minutes. The cloud plan's brief
for T01 is 7,117 characters: lettered parts, the scope rules, and the `nearest()` function WRITTEN OUT ("use exactly
this, it was tuned against the real page"). The local brief is 1,508 characters and says what must be true, not how.
So the missing thing is not the builder's ability; it is that the cloud planner had solved the hard part before
writing the brief. Mine was tuned by running it. A planner that only writes cannot tune.

**Built in answer (no model run yet):** `studio_blind.py briefs <workspace>` (plan-only trials). A second pass, one
call per task: the model sees the spec, the plan, the task's check labels, the earlier rewritten briefs and the
source outline, and must write a brief with fixed parts: the exact file edits, the code in numbered parts with the
deciding algorithms written out in code, a table from every check label to the part that satisfies it, a "do not"
list, and debugging hints. A rewrite shorter than the original is thrown away. The short brief is kept as
`brief_short`. Also fixed: the foreman swept `.studio/suspects.json` away as a stray file; it is now git-excluded.

**Staged for the owner: `C:\PCodeTest\blind4`** (plan-only). Order: `plan`, `briefs`, `check`, `build`, `grade`.
Compare with blind3 (0 of 3, best 27 of 42 on T01) and with the cloud plan (3 of 3 first try).

**What I expect and what to do with each outcome (unmeasured):**
- Longer briefs with an untuned algorithm may still stick on the same checks. If T01 gets further than 27 of 42 but
  sticks, the next lever is NOT a better prompt. It is one of these, in the order I would try them:
  1. **Keep a failed attempt's work.** The foreman undoes everything on a fail, so 27 of 42 after 40 minutes is thrown
     away and the next attempt starts from nothing. A "continue from the best attempt" mode (keep the diff when the
     attempt raised the number of passing checks and broke nothing older; give the next attempt only the failing
     checks) would have turned six restarts into one long climb. This is a foreman change: the owner's copy
     (`G:\!Ai\ND3\nd_foreman.py`, `undo()` at the three places it is called after a failed gate).
  2. **Smaller tasks.** One task per test file is my rule, made for like-for-like grading. T01 carries 42 checks.
     Splitting a test file into two or three (basics: file, script line, mode on/off, first highlight; then moving;
     then options and Browse) gives the builder steps it can finish. Needs the pack's tests split the same way.
  3. **A planner that tunes.** Let the planner run code: a "spike" step where the model writes the deciding
     function, runs it against the real page with the test helpers, and only then writes the brief. This is what I
     did by hand, and it is the honest description of what "planning" this task took.
  4. More time per attempt (60 or 90 minutes) while the builder is half on the processor. Cheap to try, but it
     changes two things at once if tried together with the briefs step.
- If blind4 passes all three: run it twice more before believing it, then try the same on `lackluster_tv_login` and
  `lackluster_firetv`.


## 13. blind4 (night of 2026-11-15): the first task a local planner planned was built

`C:\PCodeTest\blind4`, plan-only, with the `briefs` step. Planner `q36c-nd64k`, builder `q36c-nd128k`.
- Plan 11.6 min; briefs 5-7 min each, growing 1,914 -> 7,819, 1,614 -> 9,643 and 1,781 -> 9,304 characters.
- **T01 PASSED on attempt 2** (42 of 42, guards held). First task ever planned by the local model and built.
  Blind3, the same setup without the briefs step, stuck on T01 after six attempts (best 27 of 42).
- T02 stuck after six attempts; five ran out of 40 minutes, two of them because the builder also edited
  `public/index.html` (out of scope). Best: 29 of 31. T03 skipped. Grade: new work 71 of 127.
- The look step found NEW "covered" findings at 1280x720 (programmes under `#guide-ruler` in the browse column):
  seen on both walks, so likely real, from T01's code scrolling the guide. Not checked against the pictures yet.
- n=1. The briefs step is the only change from blind3, so it is the likely cause of T01 passing, not a proven one.

**Built in answer: salvage (`dev/studio_salvage.py`).** The foreman threw away T02's 29-of-31 attempt. Salvage
rebuilds what an attempt left in its allowed files from the builder's transcript (`.foreman/opencode/<task>_a<n>.jsonl`,
every write and edit in order; indentation slips forgiven as OpenCode's edit forgives them; anything that will not
replay exactly is dropped, never guessed), runs the task's test and every must-pass test on a copy, and commits the
best attempt as the task's new start when it gains checks and breaks at most 2 older ones (then only if it gains 5 or
more; the foreman's broke gate makes the next attempt mend them). `build` now does this before every fresh round.
No foreman change needed: `retry` takes the task's start from HEAD. Self-test: salvage 4 of 4. On blind4 it rebuilds
T02_a3 and reproduces the foreman's number exactly (29 passed, 2 failed). a1 and a2 do not replay.
One older check (`arrows alone reach Play Now`) failed once and passed once with a3's code: flaky with that code,
steady (42 of 42 twice) without it.

**Next for the owner:** run blind4's build again with two rounds; T02 then continues from 29 of 31:
    "C:\Heretic\venv\Scripts\python.exe" "G:\!Ai\Philibert\dev\studio_pack.py" build "C:\PCodeTest\blind4" --rounds 2
    "C:\Heretic\venv\Scripts\python.exe" "G:\!Ai\Philibert\dev\studio_blind.py" grade "C:\PCodeTest\blind4"

## 14. Smaller tasks (2026-11-15, afternoon)

**blind4 rerun with salvage, two rounds:** salvage worked (T02 started from 29 of 31), but six more attempts did not
close the last two checks: one about scrolling, one about redrawing. Round 2 ran with the model 47% on the processor
(the card was full of other programs) and managed 0-6 steps per 40 minutes, so round 2 says little.

**Built in answer:** the remote pack's guide test is split in three (moves 19, screen 10, place 6 passing checks),
and the cloud plan's T02 into T02-T04 to match (the player is T05). Verify says SOUND; the reference cut back to
each task's own work passes that task's file and fails the next (proof the split is fair). See the pack's NOTES.md.

**Staged: `C:\PCodeTest\blind5`** (plan-only, same as blind4 apart from the split). Order: `plan`, `briefs`,
`check`, `build --rounds 2`, `grade`. Free the card first (`ollama ps` must say 100% GPU) or the timing means
nothing. Compare with blind4: T01 passed, T02 stuck at 29 of 31, T03 skipped; grade 71 of 127.

## 15. blind5 (night of 2026-11-15): the split, planned locally; nothing built, and why

- Plan: the first call thought for all 32,000 tokens and wrote nothing; the new automatic second call (told to keep
  its thinking short) wrote a valid 5-task plan in 11 minutes. Briefs: all five rewritten (6-12K characters).
- Build: T01 stuck, 3 attempts, best 21 of 42 (blind4's T01 passed on attempt 2). The two fresh rounds never ran:
  the suspect check called T01's test suspect and that stopped them.
- Cause: T01's brief told the builder to write its OWN `isTvBrowser()`. The page already has one (index.html), the
  sign-in page uses it, and a second declaration replaces it: six sign-in checks broke in every attempt, so salvage
  rightly kept nothing either. The spec said "the page's own isTvBrowser()"; the planner misread it.
- Fixed (no model run): `check` refuses a brief that declares a function the app already has (vendor and .min.js
  files skipped); the briefs step checks its own rewrite and asks once more, naming the clash; the BRIEF prompt
  says so; a redo of one brief compares with the short brief, not the long one; in plan-only trials a suspect test
  is a warning only (the pack's tests are proven on the reference). Self-test 14/14.
- Lesson: a local planner can write a fine plan and still give the builder one wrong instruction that dooms the
  task. Mechanical checks on the brief (names, clashes) are cheap and catch what retries cannot.

## 16. blind5, second build (2026-11-16): 98 of 131, the best yet; and a build that was cut off

- With T01's brief redone (the clash check said READY), T01 passed on attempt 1, T02 after a fresh round,
  T03 on attempt 3. T04 and T05 were not reached.
- Graded on the T03 pass: basics 42/42, guide moves 19/19, screen 10/10, place 5/6, player 22/54. New work
  98 of 131 (blind4: 94), guards 77/77. Everything the local model planned, briefed and built.
- The first grade said 63 of 131. That was wrong, for three reasons:
  1. The foreman checks `--max-hours` only between tasks, and one task can take 3 x 40 min. The outer timeout was
     the limit + 15 min, so it killed the foreman mid T04 attempt 2 (overnight.log: TIMED OUT after 11700 s).
  2. `subprocess.run` killed only the foreman. Its OpenCode carried on editing the folder.
  3. The handoff commit (`git add -A`) took the half-done `tvnav.js` and four debug scripts (943b8a3), and the
     grade copied the folder as it was.
- Fixed: `Q.sh` kills the whole process tree on a timeout. The foreman's outer timeout is the limit plus a whole
  task (`TASK_MARGIN`, 2.5 h). After every foreman run, `Q.settle` puts anything uncommitted outside `.studio/` into
  a git stash, so nothing commits it. The grade judges committed work only (it prints what it left out).
  Self-test 42/42; tree kill and settle were tested on throwaway folders.
- blind5 repaired by hand: the app is back at the T03 pass (c0f5eec), and the leftovers are in `git stash` there.
  The next `build` resumes at T04.
- Orphaned test servers (2026-11-16): a pack test that crashes or is killed leaves its `node dist/server.js` gateway
  and its headless Edge (`lp_edge_` profile) running; 13 pairs had piled up since 11/14 (stopped by hand).
  `Q.close_test_servers` now stops them whenever their parent is gone (a live parent means a test still running,
  or someone's own server: never touched). It runs with `close_leftovers` (before and after every foreman run, at
  the end of a build) and at the end of `grade`. Tested: an orphan is stopped, one with a live parent is kept.
  The cause is in the pack's `_t.py`: no `atexit` stop, so a crash skips `gw.stop()`. Not changed (pack tests).

## 17. blind5, third build (2026-11-16 evening): T04 passed; T05 kept at 40 of 54

- T04 passed on attempt 3. T05 (the player, 54 checks, a 23-26K brief) got stuck in all three rounds: all 9
  attempts ran out the 40 min, at 80-200 steps each. The foreman's grade: 99 of 131.
- Lost work: the foreman names transcripts `<task>_a1..a3`, so each fresh round overwrote the last. And salvage ran
  only BEFORE a round, so the last round was never weighed. A dry salvage afterwards: round 3's a1 reached 40 of 54
  and broke nothing (a2 reached 48 but broke 5 basics checks).
- Fixed: `studio_salvage.keep_rounds` renames a stuck task's transcripts to `<task>_r<k>_a<n>` before the retry,
  and salvage weighs every round. After the last round, the build salvages each stuck task once more and keeps the
  best as the next build's start. Self-test 42/42.
- Done by hand on blind5: a1 kept (2d1c5b2). Graded 117 of 131 new checks, guards 77/77. The other 14 player checks:
  channel wrap with Up/Down on the video, the player's button row (Right to Close, Left/Right along it), Back
  closing chat and then the drawer, the video filling a TV screen, the dialog's type buttons, and Back on the
  sign-in code screen.
- Counting: 99 is what passed the foreman's gates; 117 includes salvaged work that broke nothing. Report both.

## 18. blind5, fourth build (2026-11-17 night): ALL FIVE TASKS PASSED - 131 of 131

- Starting T05 from its salvaged 40 of 54, T05 passed on attempt 2 (39 min). Grade: new work 131 of 131, guards
  77 of 77, 208 of 208 hidden checks. The look step found nothing new; the guide and the full-screen player look
  right at 1280x720. Only the allowed files changed (public/tvnav.js +1024 lines, index.html +1 line). The
  orphan cleanup stopped 1 leftover gateway at the end.
- This is the first whole feature where the local models did all of it: q36c-nd64k planned it from the spec alone
  (plan-only, it never saw the pack's plan or tests) and wrote the briefs; q36c-nd128k built it. Claude only fixed
  tooling between runs. Four builds, about 18 hours of machine time.
- What made it work, in order of weight: tests split small (section 14), salvage carrying a failed attempt's work
  forward (and across rounds, section 17), the brief clash check (section 15), and a build runner that cannot leak
  a half attempt (section 16).
- n=1. Before calling this repeatable, run a fresh blind trial (blind6) with the current tools from the start.

## 19. blind6 (2026-11-17): the straight-through repeat did NOT repeat

- Fresh plan-only trial with all the fixes above. Plan (4 min) and briefs (8 min) went fine; T01 stuck through all
  three rounds and nothing else ran. The grade said 80 of 131 and 2 sign-in guards broken, all of it salvaged T01 work.
- Cause 1, the brief: T01's Enter branch said `currentFocus.click()` without `e.preventDefault()`. A focused
  button already clicks itself on Enter, so every OK fired twice: Sign in asked Plex for two pins, and the code
  screen never signed in. The spec said only "OK does what a click does". blind5's brief happened not to do this.
- Cause 2, the tools: salvage kept a 41/42 attempt that broke 2 sign-in checks (MAX_LOST allowed 2). Every later
  attempt started with sign-in broken; round 2's a2 failed on ONLY those 2. The suspect check then called the test
  "certain" at fault, because it failed "before the builder touched it". That was the salvage.
- Fixed: salvage never keeps an attempt that breaks a guard test (MAX_LOST is for earlier tasks' checks only).
  `brief_faults` = the clash check + `double_ok` (an Enter branch with .click() and no preventDefault); `check`
  refuses either, `briefs` re-asks once naming them, and the BRIEF prompt says it. The suspect check says
  "salvage-broke" (likely, not certain, no STOP) when a salvage commit lies between the last pass and the start.
  The pack's SPEC.md has the sentence now: one press, one click; Sign in asks for one code. Self-test 43/43.
  `double_ok` flags blind6's T01 and nothing in blind4, blind5, blind6's other tasks or the pack's own plan.
- blind6 repaired: salvage reverted, spec sentence added. Its plan and the other four briefs are the local model's,
  unchanged.
- Read honestly: n=2 plan-only trials, 1 finished. Each failure so far was ONE wrong line in a brief that broke an
  unrelated, already-working part (sign-in), twice. Guard-breaking is the pattern to watch.

## 20. blind6 rebuild (2026-11-17/18): T01 passed; briefs name page parts that do not exist
- After the T01 brief redo, T01 passed on attempt 3 (22:53) from the salvaged 4/7 start. T02 failed attempt 1 at 8/19
  (logo and Up/Down moves); the build was still running at midnight.
- Cause found in the briefs: code marked "use exactly this" looks up `.channel-logo` (the app's logos are `.logo-tile`)
  and `#chat-panel` (no such element). T02-T05 of blind6 all had one; blind4 and blind5 had them too (`.fav-star`,
  `.channel-name`), and blind5 still finished, so the builder sometimes works round them. The pack's own plan has none.
- New: `ghost_names` in studio_blind.py (commit 0ba766c). `check` says NOT READY for a brief whose code looks up an
  id/class that is not in the staged app, the spec or the tests, and that this or an earlier brief does not create;
  `briefs` re-asks once. The brief prompt says it too. Self-test 44/44. blind6 itself was left alone while it builds.

## 21. blind6 rebuild result (2026-11-18): T01 passed, T02 stuck, graded 75/131 (guards 77/77)
- T02's own test reached 19/19 in three attempts (r1_a2, a1, a2), and every one broke 10-16 of T01's checks
  ("arrows alone reach the Browse button ..."). The brief's "use exactly this" walk did `if (nextR < 0) return` at the
  top row: the highlight was trapped in the guide. Leaving the guide upward was only in T03's brief. The planner wrote
  a task that undoes the one before; the foreman's broke gate said so, and 40 minutes was not enough to mend it.
- a2 also lost to the scope gate: it debugged by editing the hidden test 38 times and left `tests/debug_test.py`
  (its rm/del did not take). Its code replayed only after salvage learnt OpenCode's block-anchor edit match
  (`anchored_span`); it was 19/19 and broke the same 10 checks, so salvage rightly kept nothing.
- Fixes (eb461ff, 8f5393e): the brief prompt lists every earlier task's check labels under WHAT MUST KEEP PASSING,
  with a rule to hand the key on at the edge of a new walk; salvage replays block-anchor edits; `check` lets a task
  the foreman already passed pass. Self-test 45/45.
- blind6 now: `check` NOT READY only for the ghost names in T02-T05 (section 20). Redo those four briefs, then build.

## 22. blind6 third build (2026-11-18 evening): T02 passed, T03 stuck, graded 94/131 (guards 77/77)
- Built while `check` said NOT READY (T04's brief re-declares openPlayNow/closePlayNow/closePlayer). New gate:
  `studio_pack.py build` refuses a blind trial unless the last `check` said READY after plan.json last changed
  (`--force` overrides).
- T02 passed on its first attempt of round 2. T03: three attempts reached 10/10 of its own test, each breaking T01's
  "arrows alone reach ..." checks (best: 4). The new brief had T01's labels under WHAT MUST KEEP PASSING and the edge
  rule, and still wrote "Up from the top row returns #avatar", skipping Browse/search/zoom. The prompt rule alone does
  not hold; the planner keeps writing fixed jumps at the guide's edge.
- Salvage: a FINISHED attempt (all own checks pass) may break up to MAX_LOST_FINISHED=5 older checks, never a guard.
  Applied to blind6 (af3bd3d): T03 starts at 10/10 with 4 T01 checks to mend. Self-test 45/45.
- (later, 2026-11-18 night) T04's brief failed `check` after three `briefs` runs: it kept declaring closePlayer()
  (the outline sent to the planner is cut to fit, so it never sees the app's own) and looked up `#media-view` (the
  app's is `#theater-toggle`, a button labelled "Media view"). Now (b58ecba + this commit): fault messages quote the
  app's own function (file, line, first lines) and name the real element a ghost meant (by its visible words, else a
  shared word); `briefs` re-asks up to twice and keeps the least-faulty; `check` exempts tasks the foreman worked on
  (the T03 salvage made its test pass); studio_blind prints UTF-8 (a hint quoted an emoji and crashed cmd.exe).

## 23. A salvage start must say what it broke (2026-11-20)
blind6's two builds on 11-20 gave T03 twelve attempts of about 100 s each, all `no files were changed`. The salvage start (af3bd3d) passes T03's 10 checks but breaks 4 of T01's, and the foreman's prompt lists test_remote_basics under 'these still pass (they pass now)'. The builder saw them fail before touching anything and called them pre-existing. studio_salvage now writes a START HERE section at the top of the task's brief (marked, so it is replaced or removed on the next run) listing the broken checks as this task's job; --apply does it itself, and `--mend` does it for a start already kept. Applied to blind6 (50447b2); check READY.


## 24. Splitting a task that runs out of time (2026-11-21)
blind6 T05 stuck at 41 of 54 player checks: six attempts over two rounds, five out of time. `studio_blind.py split <ws> T05` (a model call: the user runs it) runs the task's test, groups its failing checks (a "..." check stays with the one before), and asks the planner which groups go first. Part 1 (T05a) is judged by tests/part_T05a_<file>.py, written by the tooling: it runs the pack's file and counts only the checks that pass now plus part 1's groups. Part 2 (T05b) is judged by the whole file. The old T05 record moves to state.json "split_tasks" so it is not counted or retried as stuck; `check` lets part 1 stand for its file in the plan-only order. Both briefs are then rewritten as `briefs` does. grade is unchanged: it runs the pack's own tests.

## 25. A stuck task is briefed on what is left (2026-11-22)
blind6 T05b started two rounds from a salvage at 52 of 54, but its brief still described all its work; five of six attempts were cut off writing the file in one reply too long to save, or ran out of time. `briefs <ws> <tid>` for a task the foreman tried and did not pass now runs its test first: the prompt lists the checks ALREADY TRUE and the ones STILL TO DO (with what each gets now), asks for small edits only, and 1,500 to 4,000 characters.

## 26. A stuck brief that ignores what is left is refused; a slow machine shows in the handoff (2026-11-22, d77cc9f)
- blind6 T05b, build after the stuck-aware brief (section 25): the planner was told 52 of 54 checks pass and to brief the
  2 left in 1,500-4,000 characters. It wrote 5,814, told the builder to "add" `applyTvStyles()`,
  `startTvControlsTimer()` and `handleMediaKey()` (all already in tvnav.js) and listed every check in part D.
- `left_faults()` in studio_blind: over 4,500 characters, an "add/write/append/define" sentence naming a
  `function x(` that already exists in the task's files ("Find `function x(`" is fine), or more than 2 passing check
  labels in the brief. `briefs` re-asks with these (up to 2 more asks); `check` says NOT READY on them.
- The same build ran its attempts at 12-32 tokens a second against a workspace median of 73 (from ~14:00 on); two
  attempts changed nothing in 40 minutes. `studio_pack status` now writes a "Builder speed" section and flags attempts
  under half the median. Free the machine before reading anything into such attempts.
- Third stuck brief (blind6 16fc554, 3,355 chars) passed `check` but was not built: it read "got ('0', '0')" (two
  opacities) as a position at (0,0), and rewrote the three fade functions to toggle classes on `#player-diag` only,
  while the test reads `#player-modal > div:last-child` and `.player-info` and the fade checks that pass now go through
  `updateTvControlsVisibility()`. It would most likely break the passing fade check and not fix the two failing ones. The local
  planner cannot diagnose this failure from the test output; `check` cannot see a wrong diagnosis. blind6 ends 129/131.

## 27. Salvage reads OpenCode's own snapshot (2026-11-23)
- blind7 T02 stuck after 6 attempts. Attempt 2 (last round) had reached 19 of 19 with nothing older broken; it failed
  only the scope gate for leaving `tests/debug_guide.py`. Salvage said "1 passed, 1 failed" for it: the builder had
  changed tvnav.js OUTSIDE its edit tool (a PowerShell find-and-replace, git stash/checkout/apply), so replaying the
  edit tool calls rebuilt broken JavaScript.
- OpenCode keeps a git store per project at `~/.local/share/opencode/snapshot/<repo's first commit>/<id>/` and puts a
  tree hash (`part.snapshot`) on every step. `snapshot_files()` reads the allowed files from the attempt's last
  snapshot; the edit replay is now the fallback only. With it T02_a2 judged 19/19, nothing broken, and was kept
  (blind7 070a3cc). Several other attempts that "did not replay" now do.
- The ND3 foreman is read-only to us, so it still fails a finished attempt for a scratch file in tests/; salvage is
  what recovers it.
