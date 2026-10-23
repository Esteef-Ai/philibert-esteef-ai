"""Philibert Setup - the window.

    python installer/app.py                       (from the repo: installs from this folder)
    Philibert Setup.exe / Philibert Setup.app     (built by installer/build.py)

The wizard is installer/ui (HTML); this file is its bridge to core.py (survey,
places, ratings) and engine.py (the install). Where the files come from:
PHILIBERT_SOURCE (a local folder), else this repo when run from source, else the
GitHub repository named in the bundled philibert.json.
"""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(HERE))
import core      # noqa: E402
import engine    # noqa: E402
import github_auth  # noqa: E402

REPO = Path(__file__).resolve().parent.parent          # when run from source
BUNDLED = HERE / "bundle"                               # models.json + philibert.json in a build


def _bundle_file(name):
    for p in (BUNDLED / name, REPO / name):
        if p.exists():
            return p
    return None


def source():
    if os.environ.get("PHILIBERT_SOURCE"):
        return {"local": os.environ["PHILIBERT_SOURCE"]}
    dev = _bundle_file("source.json")             # a --dev build: install from the dev's folder
    if dev and getattr(sys, "frozen", False):
        return json.loads(dev.read_text(encoding="utf-8"))
    if not getattr(sys, "frozen", False) and (REPO / "app").is_dir():
        return {"local": str(REPO)}
    info = json.loads(_bundle_file("philibert.json").read_text(encoding="utf-8"))
    return {"repo": info["repo"], "branch": info.get("branch", "main"),
            "token": os.environ.get("PHILIBERT_GITHUB_TOKEN", "")}


def _client_id():
    p = _bundle_file("philibert.json")
    return (json.loads(p.read_text(encoding="utf-8")).get("github_client_id") or "") if p else ""


class Api:
    def __init__(self):
        self._info = None
        self._installer = None
        self._state = None
        self._window = None
        self._token = os.environ.get("PHILIBERT_GITHUB_TOKEN", "")   # in memory only, never saved
        self._user = ""
        self._device = None

    # -- signing in to GitHub (a private repository) ---------------------------------
    def github_status(self):
        src = source()
        if not src.get("repo"):
            return {"needed": False}
        needed = github_auth.repo_needs_signin(src["repo"])
        if needed is None:
            return {"needed": True, "offline": True, "device": bool(_client_id()), "signed_in": False}
        return {"needed": bool(needed), "device": bool(_client_id()),
                "signed_in": bool(self._token and self._user), "user": self._user}

    def github_start(self):
        try:
            d = github_auth.start(_client_id())
        except Exception as e:
            return {"ok": False, "message": f"Could not start signing in: {e}"}
        self._device = d
        import webbrowser
        webbrowser.open(d["verification_uri"])
        return {"ok": True, "user_code": d["user_code"], "uri": d["verification_uri"], "interval": d.get("interval", 5)}

    def github_poll(self):
        if not self._device:
            return {"state": "error", "message": "Start signing in first."}
        try:
            r = github_auth.poll(_client_id(), self._device["device_code"])
        except Exception as e:
            return {"state": "pending", "message": str(e)}
        if r["state"] == "ok":
            return self._accept(r["token"])
        return r

    def github_token(self, token):
        return self._accept(str(token or "").strip())

    def _accept(self, token):
        chk = github_auth.check(source()["repo"], token) if token else {"ok": False, "message": "Paste a token."}
        if chk["ok"]:
            self._token, self._user, self._device = token, chk["user"], None
            return {"state": "ok", "user": chk["user"]}
        return {"state": "denied", "message": chk["message"]}

    # -- facts ---------------------------------------------------------------------
    def survey(self):
        if self._info is None:
            self._info = core.survey()
        return self._info

    def places(self):
        return core.places()

    def catalog(self):
        return core.rated_catalog(self.survey(), _bundle_file("models.json"))

    def default_model(self):
        """The biggest everyday model that runs fully on this computer's graphics card."""
        ok = [m for m in self.catalog() if m.get("auto") and m["rating"] == "green"]
        if not ok:
            ok = [m for m in self.catalog() if m.get("auto")][:1]
        return max(ok, key=lambda m: m["size_gb"])["tag"] if ok else ""

    def imagegen_rating(self):
        """Image Generation on this computer: green / yellow / red, and why."""
        try:
            import nd_imagegen
            return nd_imagegen.rating()
        except Exception as e:
            return {"rating": "red", "backend": None, "why": f"Could not check this computer ({e})."}

    def check_place(self, dest, pcs):
        dest = str(dest)
        mounts = sorted(core.places(), key=lambda p: len(p["path"]), reverse=True)
        place = next((p for p in mounts if dest.upper().startswith(p["path"].upper())), None)
        if not place:
            return {"verdict": {"ok": False, "message": "Setup cannot reach that place."}, "free_gb": 0}
        verdict = core.format_verdict(place["fs"], pcs)
        speed = None
        try:
            speed = core.speed_test(place["path"], 64)
        except Exception:
            pass
        return {**place, "verdict": verdict, "speed": speed}

    def choose_folder(self):
        import webview
        r = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not r:
            return ""
        f = Path(r[0])
        return str(f if f.name.lower() == "philibert" else f / "Philibert")

    def checklist(self):
        items = []
        info = self.survey()
        if core.IS_WIN:
            nvidia = [g for g in info["gpus"] if core.gpu_role(g) == "cuda"]
            if nvidia:
                ver = core._run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"]).strip()
                if ver:
                    items.append({"id": "gpu", "kind": "info", "title": "Graphics driver",
                                  "detail": f"{nvidia[0]['name']} - driver {ver.splitlines()[0]} is installed. Nothing to do."})
                else:
                    items.append({"id": "gpu", "kind": "required", "title": "Graphics driver (yours to install)",
                                  "detail": f"{nvidia[0]['name']} needs NVIDIA's driver to run models fast. Setup does not install "
                                            "drivers - get it from nvidia.com/drivers if you want the speed. Philibert works without it, slowly."})
            else:
                items.append({"id": "gpu", "kind": "info", "title": "Graphics",
                              "detail": "No graphics card the models can use: they run on the processor. Nothing to install."})
            items.append({"id": "shortcut", "kind": "optional", "value": False,
                          "title": "A Philibert shortcut on this computer's desktop",
                          "detail": "Optional - the only thing Setup would put on this computer."})
        elif core.IS_MAC:
            items.append({"id": "macaccess", "kind": "required", "title": "macOS will ask to allow access to the drive",
                          "detail": "The first time Philibert starts from the drive, macOS asks whether it may use files on a "
                                    "removable volume. Click Allow - nothing is installed."})
        return items

    # -- the install -------------------------------------------------------------------
    def start_install(self, plan):
        plan = dict(plan)
        plan["source"] = source()
        if plan["source"].get("repo") and self._token:
            plan["source"]["token"] = self._token
        elif plan["source"].get("repo") and not plan["source"].get("local") \
                and github_auth.repo_needs_signin(plan["source"]["repo"]):
            self._state = {"steps": [{"title": "Copying Philibert onto the drive"}], "step": 0, "step_pct": 0,
                           "overall": 0, "detail": "", "done": False, "warnings": [],
                           "error": "This copy of Philibert is private: sign in to GitHub on Setup's first page "
                                    "(your GitHub account needs to be invited to it) - then start again."}
            return False
        log = Path(plan["dest"]) / "data" / "logs" / "install.log"
        self._state = {"steps": [], "step": 0, "step_pct": 0, "overall": 0, "detail": "Starting", "done": False,
                       "error": "", "warnings": []}

        def report(s):
            self._state = s
        self._installer = engine.Installer(plan, report, log_path=log)
        threading.Thread(target=self._installer.run, daemon=True).start()
        return True

    def progress(self):
        return self._state

    def cancel(self):
        if self._installer:
            self._installer.cancel = True
            if self._installer.child:
                try:
                    self._installer.child.kill()
                except Exception:
                    pass
        return True

    def open_philibert(self, dest):
        d = Path(dest)
        if core.IS_WIN:
            os.startfile(str(d / "Start-Windows.bat"))
        elif core.IS_MAC:
            subprocess.Popen(["open", str(d / "Start-Mac.command")])
        return True

    def close(self):
        if self._window:
            self._window.destroy()
        return True


def main():
    import webview
    api = Api()
    api._window = webview.create_window(
        "Philibert Setup", url=str(HERE / "ui" / "index.html"), js_api=api,
        width=1100, height=740, min_size=(980, 680), background_color="#0f172a")
    webview.start(gui="edgechromium" if core.IS_WIN else None, private_mode=True)


if __name__ == "__main__":
    main()
