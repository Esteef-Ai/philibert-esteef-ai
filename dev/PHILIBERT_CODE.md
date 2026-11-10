# Philibert Code by Esteef.Ai — design (draft)

Decided 2026-11-09: NeuralDock is officially **Philibert Code**. It is the coding and power-agent
member of the Philibert family: a separate install that **requires Philibert** and reuses its pieces.
Philibert itself stays the streamlined helper and agent chat; coding work happens in Philibert Code.

## 1. Principles

- **Philibert first.** Philibert Code installs only into an existing Philibert install. It never ships
  its own Python, Ollama, model store, updater or sign-in: it uses Philibert's.
- **The developer's ND3 is not touched.** The ND3 folder beside this repo stays the developer's own dev copy, with its
  memory, vault, history and settings. Philibert Code is *built from* it by a script in this repo
  (like `dev/sync_app.py`), and the rebrand happens in that build, never in ND3.
- **Nothing personal ships.** Same rule and same guard as Philibert: no memory, chats, vault, config,
  history, personal paths, names, emails or tokens. The build refuses to finish if any are left.
- **Brand at the surface only.** Window titles, UI text, docs and installer say "Philibert Code".
  Internal file names (`NeuralDock_launcher.py`, `nd_*.py`) keep their names, because many scripts,
  tests and `sync_app.py` depend on them.

## 2. Where it lives

Philibert Code installs as an add-on folder **inside** the Philibert install it belongs to:

```
<Philibert install>\               (E:\Philibert, K:\Philibert, ...)
  app\  runtime\<os>\  setup\  data\        <- Philibert, unchanged
  code\                                     <- Philibert Code
    app\                                    built from ND3 (rebranded, scrubbed)
    pylib\                                  extra Python packages, on top of Philibert's runtime
    tools\opencode\  tools\git\             pinned third-party tools
    install.json                            version, channel, what was installed
  data\code\                                Philibert Code's own data (see 3)
```

Why inside: sharing becomes plain relative paths; a portable drive keeps working when moved; uninstalling
Philibert Code is deleting `code\` and `data\code\` (with a "keep my data" option).
It is still a **separate install**: its own Setup, its own version and update channel, its own
desktop/Start icon, uninstallable on its own. Setup finds Philibert by looking for
`install.json` in the folder the user picks (or the drives' `\Philibert` folders), never through the registry.

## 3. Shared and separate

| | Shared with Philibert | Philibert Code's own |
|---|---|---|
| Python + Ollama runtimes | yes (`runtime\<os>`) | extra packages in `code\pylib` |
| Model store and model manager | yes; Code adds its entries to the catalogue | — |
| Updater, GitHub sign-in, installer engine | yes | its own update channel |
| **Notes vault** | **yes, one vault** (`data\vault`, edited through nd_notes) | — |
| Chats | no | `data\code\chats` |
| Settings, autonomy, memory, logs | no | `data\code\` |

**Referencing a chat from the other app.** The chat histories stay separate, but the user can pull one in
when it's needed: a "Reference a chat…" button lists the other app's chats (read-only), and the one
picked is added to the current conversation as a quoted, clearly labeled context block. It only happens when
the user asks: neither app reads the other's chats on its own, and nothing is ever written back.
This works both ways (Philibert can reference a Philibert Code chat too).

## 4. What ships

**In:** the full ND agent and chat UI with shell access (asks before changes; autonomy default `ask`), the
OpenCode coding worker and `/code` (KEEP / UNDO / SHOW DIFF / FIX THE REGRESSIONS), the foreman plan
runner, ND's coding guards and lint/tests/browser checks, automation (managed browser, hidden desktop),
notes, files.

**Out:** Heretic / abliteration, the model benchmarks and bench harnesses (T3, overnight runs), remote
control, anything under `temp\`, experiments, and everything personal. Image generation and Retro
Vault stay Philibert features.

**Third-party tools, pinned in `setup\pins.json`:** OpenCode (MIT), MinGit (Git for Windows,
GPL-2.0 binary, unmodified). Downloaded by Setup, never committed. OpenCode's config is written by
Philibert Code (`opencode_worker.write_config`), never the user's own `~/.config/opencode`.

## 5. Models and hardware

- Default coding model: Qwen3.6 35B-A3B coding (`qwen3.6:35b-a3b-coding`, official Ollama library)
  plus a Modelfile that makes the 128K-window tag. Philibert's model manager pulls it and Setup
  creates the tag.
- **Hardware check in Setup:** below 16 GB of video memory or 32 GB of RAM, Setup warns plainly
  ("coding jobs will be very slow or will not load on this computer") and lets the user continue.
- Philibert's own chat models are untouched; Philibert Code can also use them for plain chat.

## 6. Building it (in this repo, read-only from ND3)

`dev/sync_code.py`, modelled on `sync_app.py`:
1. Copy the listed ND3 code files into `code/app/` (an explicit list, like `FILES`; never `temp/`,
   `experiments/`, data or config).
2. Apply the same SCRUB table and the same personal-data guard; refuse on any hit.
3. Apply the brand swaps (`NeuralDock` → `Philibert Code` in visible strings), each with an asserted
   count, so a change in ND3 that moves a string fails the build loudly instead of shipping half-branded.
4. Print a summary; the developer reviews `git diff` and commits. Pushing needs the developer's OK.

## 7. Updates

Same private repo and sign-in as Philibert, `code/` folder, its own version in `code/install.json`.
Philibert's Update button updates Philibert; Philibert Code's own Update button updates `code\` (and
refuses if its required Philibert version is newer than the one installed, telling the user to update
Philibert first).

## 8. Platforms

Windows first. Mac later: OpenCode and Ollama run there, but the worker's process handling
(taskkill, cmd) and the foreman's are Windows-only today and need a platform layer.

## 9. Build phases

1. **Done 2026-11-09.** `dev/sync_code.py` + scrub/brand guard + `dev/test_sync_code.py`.
2. **Done 2026-11-09.** Shared paths: `code\start.ps1` (+ `Start-Philibert-Code.bat`) runs `code\app` on
   Philibert's Python, Ollama (shared when Philibert's is running, else its own, stopped on close), model
   store and notes vault, with its own `data\code\`; refuses to start without Philibert. Left out at
   build time (PATCHES in sync_code.py): remote devices and pairing (tools, endpoints, panel) and
   Heretic (endpoints, panels); Philibert's and Philibert Code's program folders are write-protected.
   `dev/test_code_start.py` runs it from a stand-in install. Extra packages for Setup to put in
   `code\pylib`: `code/requirements.txt` (ruff, pillow, pywin32).
3. **Done 2026-11-09.** "Reference a chat" in both apps: `shared/nd_chatref.py` (read-only; Philibert's
   `data\chats`, Philibert Code's `data\code\chat_session.json` tabs and `data\code\chats`) behind
   `/api/chatref` (after sign-in, same-site only), and `shared/chatref.js`: a ⇄ button (Philibert: beside
   the message box; Philibert Code: "⇄ PHILIBERT CHAT" on the chat toolbar) that puts the picked chat at
   the top of the message box as a labelled, quoted block (newest 6,000 characters), to edit or send.
   It hides itself when the other app is not installed. Repo-owned files and edits live in
   `dev/patching.py`; `sync_app.py` applies them too (`--addons-only` without re-copying ND3). Tests:
   `dev/test_chatref.py`, plus checks in `test_sync_code.py` and `test_code_start.py`.
4. **Done 2026-11-09.** Window: `installer/code_app.py` (CodeApi on Philibert Setup's Api: sign-in, progress,
   cancel) + `installer/code_ui/` (Philibert Setup's look; pages Welcome+sign-in, Which Philibert, Ready to
   install, Installing, Done; `?mock=1` design preview); `python installer/build.py --code [--dev]` ->
   `installer/dist/Philibert Code Setup.exe` (14.5 MB). Tests: `installer/tests/test_code_app.py`.
   Engine: `installer/code_engine.py` (CodeInstaller on
   Philibert's Installer) + `installer/code_setup.py` (console). Steps: check (Philibert set up here;
   hardware warning; Philibert's OWN ollama.exe >= `ollama_min`) -> app (code\app replaced whole, data\code
   never touched) -> tools (OpenCode 1.19.5 and MinGit 2.55.0.3, sha256-pinned in `code/pins.json`) ->
   python (ruff, pillow, pywin32 via pip --target into code\pylib + a sitecustomize.py so pywin32.pth
   runs) -> model (qwen3.6:35b-a3b-coding pulled, q36c-nd128k made via /api/create; reuses Philibert's
   running Ollama) -> code\install.json. start.ps1 puts code\tools on PATH and sets ND_OPENCODE_EXE;
   the build points the worker/foreman at ND_OLLAMA_URL and OpenCode's files at data\code\opencode.
   Tests: `installer/tests/test_code_engine.py`. Philibert's Ollama pin was bumped 0.40.4 -> 0.40.15
   (2026-11-09, setup/pins.json + windows.ps1 + mac.sh) so the coding model runs on Philibert's Ollama;
   a drive picks it up on its first start after an update (the version stamp differs).
5. **Done 2026-11-10.** Update: `code\Update-Philibert-Code.bat` -> `code\update.py` (refuses while
   Philibert Code runs; gets Philibert's repo - GitHub device sign-in if private, never saved - and runs
   the repo's `installer/code_setup.py` over the install; keeps the model choice; data\code untouched).
   One copy at a time: `start.ps1` writes `data\code\run.json`; a second start opens the running one.
   Philibert's retro desktop shows a Philibert Code icon (`shared/philibert-code.svg`) only when it is
   installed (`code\install.json`); opening it starts it or opens a window on it (`shared/nd_codelaunch.py`,
   CODEICON_APP edits). Setup offers an optional desktop shortcut (`Philibert Code.lnk`, `code\philibert-code.ico`).
   Tests: `dev/test_codelaunch.py` + additions to `test_code_engine.py` and `test_code_start.py`.
6. Mac.

## 10. Decided

- **Handoff from Philibert (yes, 2026-11-09).** When Philibert Code is installed, Philibert's chat
  offers "This is a coding job: open it in Philibert Code?". Only the task text is handed over, only
  on the user's click. Built after ND's own coding handoff (build step 4) works, as phase 7.
- **One repo (recommended, 2026-11-09).** `code/` lives in the Philibert repo, with its own version in
  `code/install.json`. Reasons: both are built from the same ND3 commit and share modules (notes,
  chats, model manager), so one commit keeps them in step and the "needs Philibert X or newer" check
  is trivial; one release flow, one set of testers. The extra download for Philibert-only users is a
  few MB of code (tools and models are never committed). Split into a second repo only if the two
  ever need different tester lists or are sold separately.
