"""Update Philibert Code (dev/PHILIBERT_CODE.md, phase 5) - run by code\\Update-Philibert-Code.bat.

Gets the latest Philibert repository (the same one Philibert updates from, named in philibert.json) and runs
Philibert Code's own Setup engine from it over this install: the program is replaced, OpenCode, Git and the
Python packages only when their pinned versions changed, the coding model only if it was installed and is
missing. data\\code (settings, chats) is never touched. If the repository is private it signs in to GitHub
the same way Philibert does (a code to type on github.com); the sign-in is never saved.
Philibert Code must be closed first. If Philibert itself is too old, the Setup engine says so (update
Philibert first with its UPDATE button).
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

CODE = Path(__file__).resolve().parent
ROOT = CODE.parent
sys.path.insert(0, str(ROOT / "app"))         # Philibert's nd_github (GitHub sign-in)


def say(msg=""):
    print(msg, flush=True)


def running():
    try:
        url = json.loads((ROOT / "data" / "code" / "run.json").read_text(encoding="utf-8-sig"))["url"]
        urllib.request.urlopen(url + "/api/status", timeout=3).read()
        return url
    except Exception:
        return ""


def sign_in(repo, client_id):
    """A GitHub token that can read `repo`: PHILIBERT_GITHUB_TOKEN, or GitHub's device sign-in. Memory only."""
    import nd_github
    token = os.environ.get("PHILIBERT_GITHUB_TOKEN", "")
    if token and nd_github.check(repo, token)["ok"]:
        return token
    if not client_id:
        raise SystemExit("This Philibert is private and has no GitHub sign-in set up. Update with Philibert Code Setup instead.")
    d = nd_github.start(client_id, "repo")
    say(f"\nPhilibert Code is shared privately. Sign in to GitHub:\n  1. A page opens: {d['verification_uri']}\n"
        f"  2. Type this code there:  {d['user_code']}\n")
    try:
        webbrowser.open(d["verification_uri"])
    except Exception:
        pass
    every = max(1, int(d.get("interval") or 5))
    end = time.time() + int(d.get("expires_in") or 900)
    while time.time() < end:
        time.sleep(every)
        r = nd_github.poll(client_id, d["device_code"])
        if r["state"] == "ok":
            chk = nd_github.check(repo, r["token"])
            if not chk["ok"]:
                raise SystemExit(chk["message"])
            say(f"Signed in as {chk['user']}.")
            return r["token"]
        if r["state"] == "slow_down":
            every += 5
        elif r["state"] != "pending":
            raise SystemExit("Signing in did not work: " + (r.get("message") or r["state"]))
    raise SystemExit("The code ran out. Run the update again.")


def download(repo, branch, token):
    if token:
        url, hdr = f"https://api.github.com/repos/{repo}/zipball/{branch}", {"Authorization": f"Bearer {token}",
                                                                              "Accept": "application/vnd.github+json"}
    else:
        url, hdr = f"https://codeload.github.com/{repo}/zip/refs/heads/{branch}", {}
    req = urllib.request.Request(url, headers={"User-Agent": "Philibert-Code-update", **hdr})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def main():
    say("Updating Philibert Code in " + str(ROOT))
    url = running()
    if url:
        say(f"\nPhilibert Code is running ({url}). Close its window, then run the update again.")
        return 1
    info = json.loads((ROOT / "philibert.json").read_text(encoding="utf-8"))
    repo, branch = info["repo"], info.get("branch", "main")
    token = ""
    try:
        if os.environ.get("PC_UPDATE_ZIP"):                 # tests: a zip of the repo instead of GitHub
            data = Path(os.environ["PC_UPDATE_ZIP"]).read_bytes()
        else:
            data = download(repo, branch, "")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            say(f"Could not download the update: {e}")
            return 1
        token = sign_in(repo, info.get("github_client_id", ""))       # private: GitHub answers 404 to strangers
        data = download(repo, branch, token)
    except OSError as e:
        say(f"Could not reach GitHub: {e}")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="philibert_code_update_"))
    try:
        zipfile.ZipFile(io.BytesIO(data)).extractall(tmp)
        src = next(p for p in tmp.iterdir() if p.is_dir())
        setup = src / "installer" / "code_setup.py"
        if not setup.is_file():
            say("The download has no Philibert Code Setup in it - nothing was changed.")
            return 1
        had_model = True
        try:
            had_model = bool(json.loads((CODE / "install.json").read_text(encoding="utf-8")).get("model"))
        except (OSError, ValueError):
            pass
        args = [sys.executable, str(setup), str(ROOT), "--local", str(src), "--accept-slow"] + ([] if had_model else ["--no-model"])
        return subprocess.run(args).returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    code = main()
    if os.environ.get("PC_UPDATE_NO_PAUSE") != "1":
        input("\nPress Enter to close this window.")
    sys.exit(code)
