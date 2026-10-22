# Philibert by Esteef.Ai — design (draft for discussion)

**Philibert** is a slimmed-down NeuralDock that runs straight from an external drive on Windows
and macOS, offline by default, built as an assistant for working musicians:
booking gigs, routing tours, merch, budget, bills, and reminders.

Status: design only. Nothing built yet. Kept local until it is ready for git.

---

## 1. Principles

- **Runs from the drive.** Nothing is installed on the host. Plug in,
  double-click, work. Settings, data and models travel with the drive.
- **Offline by default.** No network access at all until the user turns the
  Internet switch on. The switch is visible at all times and easy to turn off.
- **Windows and Mac from one drive** (exFAT). Apple Silicon and Intel Macs,
  64-bit Windows.
- **A product for any musician.** No band-specific data shipped; a first-run
  setup asks for the band's name, members, home city and currency.
- **Looks and behaves the same on Windows and Mac.** The interface is one web page
  shown in a native window (WebView2 on Windows, WebKit on Mac), served from the
  same files on the drive. Everything OS-specific — notifications, which browser
  to drive, trash vs. Recycle Bin, the launcher — sits behind one small platform
  layer with a Windows and a Mac implementation, so behaviour matches too.
- **Built from ND's source, not a fork.** A build script assembles the portable
  app from ND3 with features switched off, so every ND improvement carries over.

## 2. Drive layout

```
ND-PORTABLE (exFAT)
├─ Start-Windows.bat          double-click on Windows
├─ Start-Mac.command          double-click on Mac
├─ app/                       the slimmed ND (Python source + UI)
├─ runtime/
│  ├─ win-x64/python/         self-contained Python (python-build-standalone)
│  ├─ mac-arm64/python/
│  ├─ mac-x64/python/
│  ├─ win-x64/ollama/         Ollama for Windows
│  └─ mac/ollama/             Ollama for macOS (universal)
├─ models/                    ONE shared Ollama model store, used by both OSes
├─ data/
│  ├─ band.db                 SQLite: contacts, venues, gigs, tours, merch, budget, bills
│  ├─ vault/                  notes + assistant memory (Obsidian-compatible markdown)
│  ├─ exports/                .ics calendar files, CSV/Excel exports
│  └─ settings.json
└─ secrets/                   email + WhatsApp credentials, encrypted with a passphrase
```

The launcher sets `OLLAMA_MODELS=<drive>/models`, starts Ollama on a private
port, starts the app, and opens it in the host's browser (or a window). On exit
it stops both. If the drive letter or mount point changes, everything is
resolved relative to the launcher, so it still works.

## 3. What is kept and what is removed from ND

Philibert is mostly a pure assistant. Kept:

- Chat agent and tool loop, memory + notes vault, settings, projects.
- **Files and folders:** read, list, search, copy, move, rename, create folders,
  bulk organise. Nothing is ever permanently deleted — "delete" goes to the
  Recycle Bin / Trash. Bulk changes are shown as a plan first ("sort these 140
  files into Photos / Contracts / Setlists"), and every change is logged so
  "undo the last reorganise" restores it.
- **Browser control, web search and fetch** (online only), through ND's managed
  browser using the host's Chrome or Edge.
- **Simple coding:** small Python scripts run with the drive's Python, simple web
  pages (band page, setlist printouts, a merch order form), spreadsheet helpers.
  ND's coding guards come along, including the page, serve and browser checks.
  Basic on the 4B/8B tiers; best on 14B and 2xB.
- Notifications hub and band-manager tools (new).

Removed: image and video generation, ComfyUI, IC-Light/SVD, Heretic, GGUF
conversion and model cloning, benchmarks, device pairing, remote access, the
terminal tab and the shell tool (run_shell) — scripts run through the drive's
Python instead.

## 4. Hardware detection and model tiers

On start, the app reads RAM, GPU and VRAM (or Apple unified memory) and picks
the largest tier that fits, which the user can override.

| Tier | Candidates (to be chosen by our own test) | Fits | Disk (4-bit) |
|---|---|---|---|
| 4B  | Gemma 4 E4B, Qwen3.5-4B | 8 GB RAM | ~3 GB |
| 8–9B | Qwen3.5-9B, qwen3:8b | 16 GB RAM / any Apple Silicon | ~5–6 GB |
| 14B | Qwen3-14B, Ministral 3 14B | 16 GB GPU or 32 GB Mac | ~9 GB |
| 2xB | Qwen3.8-27B | 24 GB+ GPU or 32 GB+ Mac | ~17 GB |

All four together are ~35 GB. Licence check before shipping (Apache-2.0 models
are simplest to redistribute; Gemma has its own terms that must ship with it).

## 5. The Internet switch

One setting, `online`, default **off**. While off, every network tool (web
search, fetch, browser, email, WhatsApp, update check) is refused with a plain
message telling the user how to turn it on — enforced in the tool layer, not
just hidden in the UI. Ollama itself only listens on 127.0.0.1.

## 6. Notifications hub (used by every feature)

One `notify(message, when, channels)` service any task can call — "remind me",
"email me the tour plan", "put the gig in my calendar":

- **In-app:** notification list and a due-soon banner.
- **Desktop:** Windows toast / macOS notification while the app is running.
- **Calendar (.ics):** anything with a date can be exported for the phone or
  computer calendar, so it works when the app is closed.
- **Email (online):** the user's own account over SMTP with an app password.
- **WhatsApp (online):** see open question 2.

A small scheduler checks due items every minute while the app is open, and on
start catches up on anything that fell due while it was closed.

## 7. Band manager

`band.db` (SQLite) with tables: `contacts`, `venues`, `gigs` (status: idea →
pitched → held → confirmed → played → paid), `tours` + `tour_stops`, `merch_items`,
`merch_orders`, `suppliers`, `transactions` (income/expense, category, gig/tour
link), `bills` (amount, due date, repeat, paid), `reminders`.

Assistant tools: look up / add / update records by type; find venues and
promoters (online); draft booking emails and follow-ups; plan a tour leg (dates,
drive times, gaps); merch reorder suggestions from sales; budget summaries and
per-gig profit; bills due and payment reminders. Everything exportable to
CSV/Excel. A simple dashboard: next gigs, bills due, money in/out this month.

## 8. Drive creator ("Create USB media")

From inside the app: pick a drive → show its name, size and current contents →
choose the format:

| Choice | Format | Works on |
|---|---|---|
| Windows only | NTFS | Windows read/write; Mac read-only — the app could not save there |
| Mac only | APFS | Mac only; Windows cannot see it |
| Windows and Mac (recommended) | exFAT | both |

Then a clear "this erases everything on <drive name>" warning; the user types the
drive's name to confirm; the app formats, copies the app, runtimes and the chosen
models, and verifies the copy. Never offered for the system drive.

## 9. Updates

Off unless online. When the Internet switch is on, a manual "Check for updates"
pulls the latest release from git and applies it to `app/` only — data, models
and settings are never touched. Optional model downloads use the same path.

## 10. How we choose the models: a band-manager test

Like T3 for coding, a scored set of tasks run on every candidate model:
add a gig from a pasted email; find three venues in a city (online); plan a
four-date tour leg; log a merch order and reorder point; record a bill and set
a reminder; summarise the month's budget; draft a booking email. Scored on
correct tool calls and correct data in `band.db`, not on prose.

## 11. Build phases

1. **Skeleton on J:** build script, both launchers, runtimes, Ollama with the
   drive model store, the slimmed ND running offline on Windows.
2. **Mac:** the same drive on a Mac.
3. **Notifications hub + Internet switch.**
4. **Band manager:** database, tools, dashboard.
5. **Band-manager test** and final model choice per tier.
6. **Email, WhatsApp, updates, drive creator.**
7. **Git:** repository, releases, update channel.

## 12. Decisions

1. Name: **Philibert**, by **Esteef.Ai**.
2. Mostly a pure assistant; files, folders, browser and simple coding kept, no
   shell (section 3).
3. Email/WhatsApp credentials: passphrase-encrypted file on the drive.
4. Windows first; Mac testing later. Both must look and behave the same.
5. Audience: any musician (generic setup, no band data shipped).
6. Band data: SQLite on the drive. Reminders: all channels, for every feature.
7. Pilot drive: an external USB drive, reformatted exFAT by the user.

## 13. Open questions

1. WhatsApp: official Business Cloud API, click-to-chat links, or both
   (recommended: both — links work out of the box, the API is optional).

## 14. Phase 1 results (2026-10-19)
- Tiers on the drive: qwen3.5:4b, qwen3:8b, qwen3:14b, Qwen3.8-27B (ZB IQ4_XS), nomic-embed-text.
- Default view: the Elena view, branded Philibert, with a model dropdown and the Internet switch.
  The full interface is at /full (Start-Full-Windows.bat, or "Full view" in the header).
- Default model: the biggest that fits the GPU and needs <= 11 GB (14B on a 16 GB card); voice uses the smallest that fits.
- Drive speed matters: the test HDD reads ~31 MB/s, so a cold 14B load takes ~5 min. Recommend a USB 3 port and an SSD/NVMe drive.
  Launcher: OLLAMA_LOAD_TIMEOUT=30m, OLLAMA_NOPRUNE=1, and it stops Ollama's whole process tree on exit.
- Open: when the host GPU is busy the drive's Ollama can crash at CUDA init instead of spilling to CPU - retry on CPU.

## 15. Planned for later (noted 2026-10-21)

1. **Port the Elena Live visuals into Philibert's default view.** They live in
   Elena Live's static/viz.js (+ index.html), not in ND3's elena_ui.html that
   dev/sync_app.py copies today:
   - the interactive vault constellation (folder clusters with nebulae and names,
     small degree-sized glowing notes, curved links, light pulses; drag / pan /
     wheel+pinch zoom / hover card / click focus / double-click reframe / expand);
   - the living layer: the shared lub-dub heartbeat (vault centre and Elena),
     breathing, drift, swaying links, pulsing nebulae;
   - the living board: heartbeat wave out of Elena lighting vias and traces,
     sparks on micro-traces, fading filaments, dust, breathing chips;
   - each vault event lights its note once (the server re-sends its rolling list).
   All motion stays off under prefers-reduced-motion; ambient motion stays dim and
   never rides a main trace (a bright pulse there is always real data).
2. **Obsidian: settled (2026-10-22): optional, never shipped.** Obsidian's terms
   (obsidian.md/terms) forbid redistributing or sharing the software, so it is
   never in the repo, a drive image or a Setup download. A portable copy was
   prototyped and works: the Windows installer holds plain 7z archives that
   Windows' own tar unpacks, and --user-data-dir keeps its profile on the drive.
   It was rejected because every start re-registers the host's obsidian:// handler
   in HKCU, taking it over from an installed Obsidian, which breaks "nothing
   installed on the host". On Mac, an .app copied onto exFAT also loses the
   symlinks its frameworks need. What ships instead:
   - setup/welcome_vault/.obsidian: core plugins, with sync and publish off;
     Templates -> Templates; trash -> the vault's .trash (as Notes uses); dark
     theme. Setup adds it to a vault that has none and never overwrites one;
   - Notes: OPEN IN OBSIDIAN when it is installed, otherwise GET OBSIDIAN, which
     opens obsidian.md/download;
   - Setup's Done page says the vault opens in Obsidian and where to get it.
