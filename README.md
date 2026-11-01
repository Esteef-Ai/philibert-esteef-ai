# Philibert by Esteef.Ai

A private, general-purpose AI assistant that runs entirely from a USB drive:
answers, writing, notes, files and folders, pictures, a browser and simple coding,
with apps you add from its App Store (a Band Manager for people in a band among them). Nothing is installed on the computer you plug it into, and it
works offline - the Internet is used only when you turn it on.

## Set up a drive (once)

You need: a USB drive formatted **exFAT** (works on Windows and Mac), with at least
**25 GB** free (more if you want the bigger models), and an Internet connection for
the first start.

This repository is private. You need a GitHub account that has been invited to it
(accept the invite from the email or github.com/notifications), and **git**:
- **Windows**: install [Git for Windows](https://git-scm.com/download/win). The first
  `git clone` opens a GitHub sign-in window; sign in once and updates work from then on.
- **Mac**: run `git --version` in Terminal; if git is missing macOS offers to install
  it. For the sign-in, install the [GitHub CLI](https://cli.github.com) and run
  `gh auth login` once, then `gh auth setup-git`.

1. Make a folder on the drive, e.g. `Philibert`.
2. Put this repository in it - either:
   - **with git** (makes updating quickest): open a terminal in that folder and run
     ```
     git clone https://github.com/Esteef-Ai/philibert-esteef-ai.git .
     ```
     (the `.` at the end means "into this folder"; the folder must be empty).
     You never need git again after this - the **UPDATE** button does it. If you do
     run git yourself on Windows and it says *dubious ownership*, that is exFAT
     having no file owners; run `git config --global --add safe.directory "*"` once.
   - **without git**: on GitHub click **Code > Download ZIP**, and unzip it so that
     `Start-Windows.bat` sits directly inside your folder. Note that such a drive
     cannot update itself (the repository is private) - to update, download the ZIP
     again and unzip it over the folder.
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

## Your other computers and your phone (Tailscale)

A laptop can use the models of a bigger computer you own (the "home PC"), keep its
notes and app data in step with it, and your phone can chat with Philibert on it. All
of it goes over **Tailscale**, a free private link between your own devices: nothing
is opened to the Internet and nothing passes through anyone's server.

**1. Install Tailscale on every device** - the home PC, the laptop and the phone - from
<https://tailscale.com/download> (Windows, Mac, iPhone and Android all have it), and sign
in with **the same account** on each. Leave it running (on a phone, the switch in the app
must be on).

**2. On the home PC:** open Philibert > **Models** > *Your other computers* >
**SHARE THIS COMPUTER'S MODELS**, and copy the address it shows
(`http://100.x.y.z:11500/k-...`).
- **Windows:** if Windows asks whether Python may use the network, allow it on
  **Private** networks. If it never asks and the other devices cannot connect, open
  PowerShell **as administrator** and allow it yourself, for Tailscale addresses only
  (*How to set it up* in the Models panel shows this command with your drive's path filled in):
  ```powershell
  New-NetFirewallRule -DisplayName "Philibert model sharing (Tailscale only)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 11500 -RemoteAddress 100.64.0.0/10 -Program "E:\Philibert\runtime\win-x64\python\python.exe" -Profile Private
  ```
  (`E:` is the drive Philibert is on.)
- **Mac:** allow incoming connections when macOS asks.
- Philibert must be running on the home PC for the others to use it.

**3. On the laptop:** Philibert > **Models** > paste the address > **USE ITS MODELS**. It
says *Connected now* when it works. From then on the laptop uses the home PC's models
(chat and pictures) whenever it is on, and its own when it is not - by itself.

**4. Notes and app data (optional):** on the home PC, **ALSO SHARE NOTES AND APP DATA**;
on the laptop, **KEEP NOTES AND APP DATA IN STEP**. Notes, Philibert's memory, Yo Teach
and Band Manager then sync both ways every 5 minutes while both are on.

**5. Your phone:** on the home PC, **OPEN A PHONE CHAT**, and get the address it shows to
your phone (email or message it to yourself). Open it in the phone's browser with
Tailscale on, and use *Add to Home Screen* so it opens like an app. The phone can chat,
look things up in your notes, Yo Teach and Band Manager, and draw pictures - it cannot
change anything.

**Someone else's device** (on their own Tailscale account): don't sign them in to yours,
which would show them all your devices. In the Tailscale admin page (Machines > your home
PC > *Share...*), share just that one computer with them.

**If it does not connect:** Tailscale on and signed in on both? Philibert running on the
home PC with sharing on? The Windows firewall (step 2)? Another VPN running at the same
time can block Tailscale. **Keep the address private**; **NEW ADDRESS** makes the old one
stop working.

## What lives where

| Folder     | What                                        | In git? |
|------------|---------------------------------------------|---------|
| `app/`     | the program                                 | yes     |
| `setup/`   | first-start and launch scripts              | yes     |
| `models.json` | the models the list offers               | yes     |
| `runtime/` | Python and Ollama, per type of computer     | no - downloaded on first start |
| `models/`  | the downloaded AI models                    | no - downloaded when picked |
| `speech/`  | listening (Whisper) and speaking (voices)   | no - downloaded on first start |
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

The code is written and tested in NeuralDock (the `ND3` folder beside this repo). `python dev/sync_app.py`
copies the files Philibert uses into `app/`; review, commit, push. See
`dev/DESIGN.md` for the design.
