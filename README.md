# Philibert by Esteef.Ai

A private AI assistant for musicians that runs entirely from a USB drive: gigs,
venues, tours, merch, budget and reminders, plus files, folders, a browser and
simple coding. Nothing is installed on the computer you plug it into, and it
works offline - the Internet is used only when you turn it on.

## Set up a drive (once)

You need: a USB drive formatted **exFAT** (works on Windows and Mac), with at least
**25 GB** free (more if you want the bigger models), and an Internet connection for
the first start.

1. Make a folder on the drive, e.g. `Philibert`.
2. Put this repository in it - either:
   - **with git** (makes updating quickest): open a terminal in that folder and run
     ```
     git clone https://github.com/sskrobe/philibert.git .
     ```
     (the `.` at the end means "into this folder"; the folder must be empty)
   - **without git**: on GitHub click **Code > Download ZIP**, and unzip it so that
     `Start-Windows.bat` sits directly inside your folder.
3. Start it:
   - **Windows**: double-click `Start-Windows.bat`
   - **Mac**: double-click `Start-Mac.command`. If macOS says it cannot be opened,
     right-click it, choose **Open**, then **Open** again (only needed once).

The first start downloads what the drive needs - Python, Ollama (which runs the AI
models) and a model chosen for that computer's graphics card - into the folder
itself. Expect 15-60 minutes depending on your connection and drive. Every start
after that is offline and quick (a large model still takes a minute or two to load
from a USB drive).

## Using it

- **Model list** (top right): the models this drive has, plus the ones it can
  download (marked with an arrow). Pick one to switch; pick a ⬇ one to download it.
- **INTERNET: OFF / ON**: whether Philibert may search the web, read web pages or
  drive a browser. Off by default.
- **UPDATE**: gets the newest Philibert - new features, fixes and new models in the
  list. Your chats, notes and downloaded models are never touched.
- **Full view**: every tool and setting. `Start-Full-Windows.bat` /
  `Start-Full-Mac.command` open it directly.

## What lives where

| Folder     | What                                        | In git? |
|------------|---------------------------------------------|---------|
| `app/`     | the program                                 | yes     |
| `setup/`   | first-start and launch scripts              | yes     |
| `models.json` | the models the list offers               | yes     |
| `runtime/` | Python and Ollama, per type of computer     | no - downloaded on first start |
| `models/`  | the downloaded AI models                    | no - downloaded when picked |
| `data/`    | your settings, notes and chat history       | no - yours |
| `secrets/` | passwords you add later (encrypted)         | no - yours |

One drive works on both Windows and Mac: each keeps its own `runtime/` folder,
and they share `models/` and `data/`.

## Adding a model (maintainers)

Add an entry to `models.json` and push. `tag` is what `ollama pull` accepts: a name
from [ollama.com/library](https://ollama.com/library), or
`hf.co/<user>/<repo>:<quant>` for a GGUF on Hugging Face. Every drive lists it after
its next **UPDATE** and downloads it when someone picks it.

The models themselves are not stored in this repository: GitHub caps a single file
at 2 GB with Git LFS (5 GB on Enterprise), and these are 3-14 GB. They come straight from Ollama's
library or Hugging Face instead - for a model of your own, upload the GGUF to a
Hugging Face repo and use its `hf.co/...` tag.

## Developing

The code is written and tested in NeuralDock (`G:\!Ai\ND3`). `python dev/sync_app.py`
copies the files Philibert uses into `app/`; review, commit, push. See
`dev/DESIGN.md` for the design.
