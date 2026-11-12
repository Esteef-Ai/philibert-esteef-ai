# Philibert Code Studio: the roadmap (read this first)

Last updated 2026-11-12. This file is the plan of record. Any agent or person picking the work up starts
here, then reads the HANDOFF.md of the workspace in play.

## The goal
A local coding app as useful as Claude Code for how the owner works: describe a new app (websites, Windows
apps, web apps, networking tools), have it built, then edit and tweak it. Speed is not the priority; a build
may take a night. Long term everything runs locally. For now Claude may write the plans and tests.

## What is proven (measured, do not re-litigate without new numbers)
| Piece | Result |
|---|---|
| Builder: OpenCode + Qwen3.6 35B (`opencode/q36c-nd128k`, thinking off) | 8.27/9 on the feature-add benchmark, n=15. ND's own agent loop with the same model: 5.0 |
| Foreman + a plan and tests written by Claude | ChordShift 12/12; WizTry 6/6 (with some help: see `dev/packs/wiztry/NOTES.md`) |
| Local model writes the plan | Usable. gpt-oss:120b is the better architect; the 35B is faster |
| Local model writes the tests before the code | 10 runs (wiztry2..wiztry10), no finished app. A new kind of broken test every night |

Conclusion: the builder and the foreman are sound. The weak link is tests written by a local model for code
that does not exist yet.

## The two tracks

### Track 1: useful now (Claude plans, local builds)
1. DONE 2026-11-12: plan packs. `dev/studio_pack.py` (verify / new / build / status / note), first pack
   `dev/packs/wiztry/`.
2. DONE 2026-11-12: the clean baseline. `C:\PCodeTest\wiztry11`: 6 of 6 tasks on the first attempt, 32 minutes,
   no help, report 5 of 5. But the owner found the exe unusable in the first minute (Browse dead, "C:" scanned
   the wrong folder, File Types list 1 pixel wide): green tests are not a working app. The scorer's probe now
   catches all three kinds (button errors, pane sizes, a folder picked before Scan).
3. DONE 2026-11-12: tweak mode. A tweak is a folder in the pack (`tweaks/<name>/`: tweak.json + tests) holding
   new tasks; `studio_pack.py tweak <workspace> <name>` adds them to a built workspace and the foreman builds
   only those, with every old test still guarding. Two tweaks done on wiztry11 from the owner's reports
   (01_usable_window: 3 minutes; 02_big_folders: 38 minutes), both folded into the pack: 10 tasks, 181 checks,
   93% of planted bugs caught. The loop that works: the owner uses the exe and says what is wrong; Claude
   measures the cause, writes tests that fail for that cause, proves them on a patched scratch copy (each task
   alone, in order), writes the tasks; the local builder builds; the owner tries again.
   Rules this taught: test every algorithm at the size real use gives it, with a time limit and a watchdog;
   window tests use a mapped off-screen window and collect button errors; the scorer and the tests must never
   import a module on the app's behalf.
4. Packs for the owner's other app kinds: a website, a web app (server + page), a networking tool. Each new
   kind needs its own acceptance check (a page: load it headless and look at the DOM; a server: start it and
   call it). `studio_score.py` is WizTry-specific today (fixture, expected.json): generalize it from
   PACK.json's `acceptance` block when the second pack arrives.
5. Studio window: import a pack, show the build, show the handoff. (Design: `dev/PHILIBERT_CODE_STUDIO.md`.)

### Track 2: toward fully local
Every pack is also an answer key: a good plan, good tests and a good build for a real app.
1. Fast grading, DONE as a tool: `studio_pack.py verify <pack>` answers in minutes, with no model and no
   build: do the tests pass on the reference build, fail on an empty project, and what share of planted small
   bugs do they catch. Claude's WizTry tests: 109 checks pass, 53% of bugs caught. To grade a local model's
   tests, put them in a copy of the pack and verify it.
2. NEXT: `studio_trial.py` writes tests into a pack copy so that grading is one command; then try the changes
   below one at a time, each judged by the grader over several samples (cheap now), not by a night's build.
3. Hand over in stages: the local model takes the plan first (Claude's tests stay), then tests written AFTER
   each task's code exists, and tests-first last, if ever.
4. Changes waiting for the grader: tests after code; the window probe (`studio_score.py`) as the acceptance
   check in place of model-written window tests; the most similar finished pack given to the planner as a
   worked example; a dispute path so the builder can say "this test is wrong" without editing it (today it
   edits protected files and burns its attempts).

## How the whole machine is used
RTX 5070 Ti 16 GB, Ryzen 7 9800X3D (16 threads), 64 GB RAM (125 GB commit), big disks, a second PC on the network.

| Resource | Job |
|---|---|
| The graphics card | The builder, alone. One model stays loaded for a whole phase; phases are batched so models swap rarely (each swap costs minutes) |
| RAM + CPU | The slow thinker: gpt-oss:120b (about 16 tokens a second, also takes 14 GB of the card). It cannot run beside the builder, so work goes in shifts: a build shift, then a review shift (read each stuck task and the diff, write a diagnosis into the handoff) |
| CPU threads | The judge, which needs no model: tests, lint, the planted-bug check (8 at a time), the window probe |
| The disk | Memory between sprints: packs, reference builds, HANDOFF.md and the journal per workspace, the foreman's lessons, every model reply under `.studio/`. A growing pack library is also the local planner's set of worked examples |
| Time | Quality. Tests are the judge, so more tries are safe: `build --rounds N` gives stuck tasks fresh attempts. Later: build a task two or three times and keep the best |
| The second PC (EsteefServer, 4 GB card) | Not used yet. 4 GB is too small for a reviewer worth trusting (a 4B model at most). Its jobs: the clean machine for "the exe runs with no Python", and later a small embedding model to find the most similar pack for the planner |
| A second graphics card (on the shopping list) | The largest single step: the reviewer or planner loaded beside the builder, no more shifts |
| Claude | The architect, in sprints: writes packs, reads handoffs, fixes wrong tests in the pack. Every sprint leaves the pack better |

## Rules that hold for every sprint
- `G:\!Ai\ND3` is the owner's dev copy: read-only from here. The foreman is used from there, never edited.
- Unattended builds (foreman, OpenCode, queues) are launched by the owner, never by an agent.
- Nothing is pushed without the owner's OK. Philibert ships nothing personal.
- The builder's shell stays restricted (`opencode.json` in each workspace; proven before every build).
- A wrong test is fixed in the pack, with a line in its NOTES.md, never in a workspace alone.
- Do not rank setups on one run. Use the grader for many cheap samples; for full builds use 3 and trust only
  large differences.

## Where things are
| What | Where |
|---|---|
| Pack tool | `dev/studio_pack.py` |
| Packs | `dev/packs/<name>/` (PACK.json, SPEC.md, plan.json, tests/, NOTES.md, reference/, VERIFY.json) |
| Local-planner pipeline (track 2) | `dev/studio_trial.py`, prompts in `shared/nd_studio.py` |
| Scoring a build | `dev/studio_score.py` |
| The old overnight queue (local planners) | `dev/studio_overnight.py`; results `C:\PCodeTest\overnight\` |
| Workspaces | `C:\PCodeTest\wiztryN`; each pack build has `.studio/HANDOFF.md` and `.studio/journal.jsonl` |
| WizTry fixtures and the first reference | `G:\WIZTRY\fixture`, `fixture_big`, `G:\WIZTRY\foreman` |
| Foreman, OpenCode worker | `G:\!Ai\ND3\nd_foreman.py`, `opencode_worker.py` |
