# Philibert Code Studio — design (draft, 2026-11-10)

The end-user face of Philibert Code: describe an app in a few sentences, get a plan you can read and
approve, and watch Philibert Code build it task by task, checking each step. It is a NEW page beside the
current window (which stays, as "Classic"), built from repo-owned files in `shared/studio/`, so ND3 is
not edited and nothing that works today is touched.

## 1. Layout (like Claude Code)

| Left | Middle | Right |
|---|---|---|
| Projects (a folder each) and their chats / builds | The chat, the plan, the build conveyor | Environment, connectors, outputs |

- **Left:** projects = ND's existing projects (name, folder, standing instructions). Under each: its chats
  and its builds (a build = a plan run), newest first. New project = pick or create a folder.
- **Middle:** one conversation. It moves through stages, shown as a strip at the top:
  `Describe -> Questions -> Spec -> Plan -> Build -> Check -> Done`.
- **Right:** *Environment* (folder, model, GPU memory, Ollama, autonomy, mode), *Connectors* (git,
  OpenCode, browser for screenshots, GitHub when signed in), *Outputs* (files changed, test results,
  screenshots, the built program, the report).

## 2. The pipeline

1. **Describe.** "Make an app in this folder that works like WizTree and shows a treemap like this"
   (+ an optional picture, used only if the model can read images).
2. **Questions.** A fixed checklist the chat must cover, so nothing is skipped: what it runs on, how it
   is started, what it must do (3-6 must-haves), how it should look, test data, what "done" means.
   The chat asks only what the description left open.
3. **Spec.** SPEC.md written into the folder; the user edits or approves it.
4. **Plan.** Tasks T01..Tn, each: title, the files it may touch, its test file, a brief, "done when".
   Shown as cards (like the WizTry plan). Saved as `.foreman/plan.json`. The user edits/approves.
5. **Tests first.** One task writes the tests for every task before any code. The foreman's `check`
   proves each test fails on an empty project and runs cleanly. The user can read them (step mode stops here).
6. **Build.** The foreman runs the tasks through OpenCode, exactly as today: scope, lint, the task's
   tests, nothing that passed before breaks; pass = commit, fail = undo and retry, then "stuck".
7. **Check (new, between tasks).** See 3.
8. **Done.** A last "make it presentable" task (README, icon, consistent look, the .exe if asked), the
   final checks, and a report with screenshots.

**Modes:** *Autopilot* (runs to the end, stops only when stuck) or *Step by step* (stops after each task
with its diff, test results and screenshot: Continue / Fix this... / Undo / Stop). Switchable mid-run;
STOP always works (the foreman's STOP file).

## 3. The quality check (where it goes and what it does)

After the foreman's gates pass and before the next task:
- **It starts.** Run the program (or its CLI) headless with a timeout: no crash, no traceback.
- **It shows something.** For a window or a page: a screenshot (hidden window / headless browser), and
  the checks that caught WizTry's bugs: not blank, the expected parts visible, nothing painted over.
- **A second look (advisory).** Another model reads the diff against the brief and lists concerns.
  Shown to the user, never a gate on its own (the design-review lesson: green tests + an eager reviewer
  drove out-of-scope edits).
- **The user (step mode).** Sees all of it and decides.

A failed "starts" or "shows" check is a gate: it becomes a retry with the problem shown.

## 4. Showing the work

- The Philibert Code robot face sits above the conveyor and reacts to REAL events only: reading files
  (eyes scan), planning (thinking dots), writing (code lines stream past), testing (a meter), passed
  (green), failed / retrying (frown, then back at it), waiting for you (looks at the chat).
- The OpenCode feed stays and grows: the current task and file, each tool call as a line, test counts
  as they run, a mini diff of the file being written, elapsed time per task, a heartbeat so a quiet
  model never looks frozen.
- No fake progress: every movement comes from the worker's or foreman's own events.

## 5. Risks (honest)

- **The plan and the tests are the hard part.** WizTry worked because a strong model wrote the plan and
  the tests; the local model only filled them in. Whether the local model can write a plan and tests that
  good is unmeasured. Measure it FIRST (phase A) before building the UI around it.
- Model-written tests can be weak (pass on anything). Mitigations: must fail on an empty project, must
  cover each "done when", the user can read them, an advisory second look.
- Reading a reference picture needs a model that can see images.
- Big apps still need many small tasks; one build is hours on one GPU.

## 6. Phases

A. **Plan-quality test (no UI).** `nd_studio.py` prompts: questions -> spec -> plan -> tests. Run them on
   the WizTry one-liner, compare with the hand-written plan, then build it with the foreman.
B. **Backend.** `/api/studio`: stages, plan file, start / step / pause / stop, an event stream.
C. **The page.** Three panes, `?mock=1` design preview first (screenshots for review), then wired up.
D. **Quality check** (section 3).
E. **Animation and the live feed** (section 4).
F. **Philibert chat handoff** ("open this coding job in Philibert Code").
