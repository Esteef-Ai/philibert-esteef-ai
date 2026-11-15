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
