# Philibert — installer, Slim/Full editions and the retro desktop

Plan agreed 2026-10-21. "PC" in this project means **both Windows and Mac**.
Test drive: **K:** (1 TB external USB drive, exFAT, label `Philibert`).

## 1. Decisions so far

| Topic | Decision |
|---|---|
| Notes | **Built-in notes app** (tree, Markdown editor with live preview, `[[wikilinks]]`, backlinks, tags, search, the constellation graph). Plain `.md`, Obsidian-compatible folder. An **Open in Obsidian** button appears only if the PC already has Obsidian. Obsidian itself is never installed. |
| Models | Hosted **publicly** on **Hugging Face** under an **Esteef.Ai organization** (owned by the user's account); Ollama pulls `hf.co/...` straight onto the drive. Public repos need no account or login from the end user. Code stays on GitHub. |
| Window | A **portable Chromium on the drive** opens Philibert as a full-screen app window (no browser bars). Same look on every PC. |
| Signing | **Unsigned for now**; testers click through SmartScreen / Gatekeeper once (instructions provided). Buy certificates before a public release. |
| Installer | **Small native app per PC**: `Philibert Setup.exe` / `Philibert Setup.app` (~20-30 MB), one codebase, wizard window. Nothing stays on the PC afterwards. |
| Repo access | **Sign in with GitHub** device code (no password/token typing; user needs an invited GitHub account). Going public later just skips the step. |
| Slim | Opens straight into **Philibert Chat**. Upgrade to Full from Settings (downloads the extra pieces, no reinstall). |
| Full | Everything in Slim + the **retro desktop** launcher. |
| Games | Retro Vault, **local play only**: no netplay server, no phone page, no push-to-talk. **Optional** in the installer (default yes). |
| Themes | **Windows 95 is the default.** The user picks which themes to download, and per theme whether to add its **sounds** and its **wallpapers/backgrounds** (boot screen and screensaver come with the theme). Every box defaults to yes. |
| Branding | Made in-house following the Artwork notes. **Picked (round 2): Esteef.Ai = E3** (ESTEEF + AI in an orbit, node at the bottom left); **Philibert = P1** (boombox mascot, speaker eyes, Soft Pulse mouth). Sheets: `brand/round1`, `brand/round2`. |

## 2. Nothing installed on the PC

Everything runs from the drive: Python, Ollama, Chromium, the app, models, notes,
games. The local server binds **127.0.0.1 only**, so no firewall prompt.

Things the installer **cannot** carry, and lists for the user to confirm
(select each / select all), with plain explanations:

- **Graphics driver (Windows, NVIDIA)**: needed for GPU speed; most PCs have it.
  If missing or too old, the checklist says so and links the vendor page — the
  models still run on the CPU, only slower. We never install drivers.
- **Mac permissions**: macOS asks once to allow access to a removable volume.
  A click, not an install.
- **Optional**: a desktop shortcut on the PC (the only host change we offer).
- **Optional**: pairing a Bluetooth controller (done in the PC's own settings).

If the list is empty the screen says "Nothing needs installing on this PC."

## 3. The installer wizard

1. **Welcome**.
2. **Survey** — OS + chip (Windows x64/ARM, Mac Apple Silicon/Intel), CPU, GPU and
   VRAM (`nvidia-smi` / DXGI on Windows; unified memory on Mac), system RAM.
3. **Sign in with GitHub** (device code).
4. **Which PCs** — *Windows*, *Mac*, or *both* (default: both, so the drive works
   anywhere). Only the runtimes are per-PC (`runtime\win-x64`, `runtime\mac-arm64`,
   `runtime\mac-x64`: Python, Ollama, Chromium, ~0.4-1.7 GB each); the app, the models
   and the user's data are shared, so they are downloaded once either way. Picking one
   PC is not a lock-in: plugging the drive into the other kind of PC later fetches its
   runtime on first start (needs the Internet that once).
5. **Edition** — Slim or Full, with download sizes. Full then shows its options,
   all ticked by default, each with its size:
   - **Themes**: Windows 3.11, 95 (default, always included), 98, ME, XP, System 7,
     OS 8, OS 9.2 — tick the ones wanted; per theme, tick **Sounds** and
     **Wallpapers & backgrounds** separately.
   - **Retro Vault** (games): yes / no. No skips the emulator and the
     Entertainment folders; it can be added later from the Control Panel.
6. **Where** — any drive or folder: an external drive (portable, the usual case)
   or the computer's own disk (e.g. `C:\Philibert`, or a folder on a Mac's internal
   disk). Philibert works the same either way - everything is found relative to its
   own folder; an internal install simply stays with that computer. Shows file system,
   free space and a quick speed test. The **format is checked against the PCs
   picked in step 4**, and a problem is called out in plain words before anything
   is written:

   | Format | Windows | Mac | Verdict |
   |---|---|---|---|
   | exFAT | read/write | read/write | **OK for both** (recommended) |
   | NTFS | read/write | **read-only** | OK for Windows only; blocked for Mac/both |
   | APFS / HFS+ | **cannot read** | read/write | OK for Mac only; blocked for Windows/both |
   | FAT32 | read/write | read/write | **blocked**: files over 4 GB (every model) cannot be stored |
   | other / unknown | — | — | blocked, with the reason |

   Blocked means the Next button stays off and the screen says what to do: back up,
   reformat as exFAT (done by the user in Disk Management / Disk Utility, or later by
   the drive creator with type-the-name confirmation), or change the PC choice.
   The launchers repeat the check on every start: plugging an NTFS drive into a Mac
   says why Philibert cannot save there instead of failing halfway.
7. **Models** — each with size and a **red / yellow / green** rating (section 4).
   **Vision (qwen2.5vl 7B) and nomic-embed are mandatory** (locked on). Offered:
   qwen3.5 4B, qwen3 8B, qwen3 14B, 27B ZB IQ4_XS, 27B Defiance IQ4_XS / Q6_K_P.
   Running total vs free space on the drive.
8. **This PC checklist** — section 2.
9. **Install** — app (git), runtimes (Python, Ollama, Chromium) for the PCs picked in
   step 4, Full extras, then the queued models.
   Resumable: an interrupted download continues from the drive's launcher.
10. **Done** — "Open Philibert now", and how to start it on any PC
   (`Start-Windows.bat` / `Start-Mac.command`).

Builds: GitHub Actions on Windows and macOS runners (the Mac app must be built on
macOS). Mac note: files the installer downloads itself are not quarantined, so
runtimes on the drive start without further Gatekeeper prompts.

## 4. Red / yellow / green

`need` = model weights + KV cache at 32K context. `fast` = VRAM (NVIDIA; AMD where
Ollama supports it), or ~70% of unified memory on Apple Silicon; Intel Macs and
GPU-less PCs have `fast = 0`.

- **Green** — `need <= fast`: runs fully on the GPU.
- **Yellow** — fits with part on the CPU (`need <= fast + half the free RAM`):
  works, noticeably slower (dense models slow down most).
- **Red** — does not fit usefully; selectable, with a warning.

Approximate needs: 4B ~4 GB, 8B ~6.5, vision 7B ~7, 14B ~11, 27B IQ4_XS ~17,
27B Q6_K_P ~27. The drive speed test adds a note on cold-load time (a USB hard
drive at ~30-40 MB/s takes minutes to load a big model).

## 5. Drive layout

```
<drive>\Philibert\
  Start-Windows.bat   Start-Mac.command
  app\                       code from git (updates = git fast-forward)
  runtime\windows\  runtime\mac\   python, ollama, chromium per PC
  models\                    one Ollama store shared by both PCs
  data\  vault\  db\  settings\    notes, band database, preferences
  Apps\<id>\                 desktop apps (section 8)
  Entertainment\
    Cartridges\<system>\...  the user's own ROMs (sub-folders only); default path
    emulator\                EmulatorJS + cores, vendored for offline play
    saves\  art\             save states, cover art
```

## 6. Slim — Philibert Chat, the one-stop shop

The Elena Live view with the **chat built in**: living circuit board + vault
constellation + chat + docked **notes panel** (notes the assistant reads light up),
an **Unload GPU** button, model dropdown and Internet switch. The full ND interface
stays one click away.

## 7. Full — the retro desktop

Themes: **Windows 3.11, Windows 95, Windows 98, Windows ME, Windows XP, Mac System 7, Mac OS 8,
Mac OS 9.2**,
picked in the Control Panel. Our own artwork and look-alike open fonts — no Microsoft
or Apple icons, fonts, logos or sounds are shipped.

- **Icons**: ND Suite, Philibert Chat, Notes, Retro Vault, Band Manager,
  Control Panel, Trash (the drive's recoverable bin), plus published apps (section 8).
- **Classic windows**: draggable, overlapping, title bars, minimise/maximise;
  taskbar + start button (Windows themes) or menu bar (Mac themes).
- **Boot screen per theme**, **original startup sounds** in each era's spirit,
  **period wallpapers**, and a **screensaver** (the vault constellation).
- **Branding — Esteef.Ai and Philibert, in each theme's own idiom:**
  - *Windows 3.11*: "Philibert Program Manager"; a Philibert program group; boot
    splash "Philibert for Workgroups — Esteef.Ai".
  - *Windows 95 / 98*: the Start button becomes a **Philibert** button with its
    logo; vertical band in the start menu reading "Philibert 95/98"; Esteef.Ai in
    the tray clock area and "About Philibert"; boot splash with clouds-style art.
  - *Windows ME*: like 98, with the start-menu band reading "Philibert Me" on ME's
    slate-blue desktop.
  - *Windows XP*: the green start button becomes an italic **philibert**; the start
    menu's user tile is the boombox; the E3 mark in the tray; a rolling-hill wallpaper
    drawn in-house (never the real photo).
  - *System 7*: a Philibert menu in the Apple-menu position; "Welcome to Philibert"
    boot box; "About This Philibert…" with the Esteef.Ai credit.
  - *Mac OS 8 / 9.2*: Platinum-style menu bar with the Philibert menu; boot screen
    "Philibert OS 8 / 9" with Esteef.Ai; Esteef.Ai desktop pattern among the wallpapers.
  - Every theme: an Esteef.Ai wallpaper option and the Philibert name in window
    titles of our own apps.

### Retro Vault (games)

Ported from the Retro Vault app: library browser with box art,
EmulatorJS player, USB + Bluetooth controllers through the Gamepad API (controllers
paired in the PC's own settings). Changes for portable use: EmulatorJS and cores are
**vendored onto the drive** (the original loads them from cdn.emulatorjs.org);
library root fixed to `Entertainment\Cartridges` (only games in sub-folders are
listed); saves and art on the drive; netplay, mobile page and push-to-talk removed.
The installer only creates the Cartridges folder — users bring their own games.

## 8. Apps on the desktop

`Apps\<id>\app.json` (name, icon, entry page, version, source: `nd` | `git`) +
its files. New apps appear as desktop icons automatically.

- **ND publishes apps**: a "publish to desktop" tool lets ND turn something it built
  (an app or a dashboard) into a desktop icon.
- **Git updates** can add apps too. Apps the user or ND made live in the user's
  space and are never overwritten by an update.

## 9. Build order

1. Drive layout + launchers + portable Chromium window + **Slim** Philibert Chat (Windows on K:).
2. **Installer** (Windows): survey, GitHub device sign-in, drive picker, model ratings,
   checklist, resumable downloads; models published to Hugging Face.
3. **Notes app**.
4. **Full**: desktop shell + window manager + first theme (Windows 95), branding,
   boot/sounds/wallpapers/screensaver; then the other five themes.
5. **Retro Vault** port (offline EmulatorJS, controllers, saves).
6. **App publishing** from ND + Band Manager.
7. **Mac** builds and testing.

## 10. Privacy — nothing of the developer's ships

Philibert carries its branding and nothing else from the developer's PC: no chat
or search history, no AI memory, no vault notes, no config, no personal paths.

- `dev/sync_app.py` copies **code files only** (never memory, chats, notes, the
  vault, config, usage or audit logs) and **scrubs** the developer's folder names
  from comments, examples and non-portable defaults; it **refuses to finish** if an
  email, the Windows user name, a personal folder or the vault's name remains.
- On the drive, portable mode always points the vault at `data\vault` and never
  reads the host PC's ND config; every user starts with an empty vault and history.
- The installer creates empty `data\` folders; it never copies anything from the PC
  it runs on.
- **Before the repo goes public:** publish from a fresh repository (or squash the
  history), because older commits of `app/` still contain the developer's folder
  names in comments.

## 11. Still to decide

- Theme icon sets from the P1 / E3 marks.
- Hugging Face: org is **https://huggingface.co/EsteefAi**. Plan: **mirror** the
  chosen GGUFs there, each repo clearly marked as a mirror (original author, link,
  licence, unmodified) with Ollama `template`/`params` files where we use a custom
  template (ZB / Defiance). All current picks are Apache 2.0. **Nothing is uploaded
  until the installer is ready to test on K:** — until then files stay local.
- Mac testing: the user will have a Mac soon (model TBD).
- Whether the code repo also goes public (then the GitHub sign-in step disappears).
