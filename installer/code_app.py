"""Philibert Code Setup - the window (dev/PHILIBERT_CODE.md, phase 4).

    python installer/code_app.py                   (from the repo: installs from this folder)
    Philibert Code Setup.exe                       (built by: python installer/build.py --code)

The wizard is installer/code_ui (HTML, with Philibert Setup's look); this is its bridge to code_engine.
It reuses Philibert Setup's Api for GitHub sign-in, the install's progress and cancelling, and where the
files come from (PHILIBERT_SOURCE, this repo from source, else the repository in philibert.json).
"""
import os
import shutil
import sys
import threading
from pathlib import Path

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(HERE))
import app as philibert_setup  # noqa: E402  (also trusts Mozilla's certificate list for downloads)
import code_engine as ce  # noqa: E402
import core  # noqa: E402

MODEL_GB = 22.0          # qwen3.6:35b-a3b-coding as Ollama stores it
PROGRAM_GB = 0.6         # code\app, OpenCode, Git, the Python packages


def _pins():
    import json
    for p in (HERE / "bundle" / "code_pins.json", Path(__file__).resolve().parent.parent / "code" / "pins.json"):
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    raise RuntimeError("Philibert Code's pins.json is missing from Setup.")


class CodeApi(philibert_setup.Api):
    """GitHub sign-in, progress() and cancel() come from Philibert Setup's Api."""

    def installs(self):
        """Philibert installs this computer can see, each with what Philibert Code finds there."""
        out = []
        for root in ce.find_philibert():
            out.append(self._describe(root))
        return out

    def _describe(self, root):
        root = Path(root)
        ver = ""
        try:
            ver = (root / "VERSION").read_text(encoding="utf-8").strip()[:80]
        except OSError:
            pass
        code = None
        rec = root / "code" / "install.json"
        if rec.is_file():
            import json
            try:
                code = json.loads(rec.read_text(encoding="utf-8")).get("installed", "yes")
            except (OSError, ValueError):
                code = "yes"
        return {"path": str(root), "version": ver, "code_installed": code}

    def choose_folder(self):
        import webview
        r = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not r:
            return None
        f = Path(r[0])
        if ce.philibert_problem(f) and ce.philibert_problem(f / "Philibert") is None:
            f = f / "Philibert"
        return self._describe(f) | {"problem": ce.philibert_problem(f)}

    def check(self, root, with_model=True):
        """Everything page 3 shows for one Philibert: is it usable, its Ollama, this computer, space."""
        root = Path(root)
        pins = _pins()
        problem = ce.philibert_problem(root)
        res = {"path": str(root), "problem": problem}
        if problem:
            return res
        inst = ce.CodeInstaller({"philibert": str(root)}, lambda s: None, log_path=root / "data" / "code" / "logs" / "setup.log")
        have = inst.ollama_version()
        res["ollama"] = {"have": have, "need": pins["ollama_min"],
                         "ok": ce.version_tuple(have) >= ce.version_tuple(pins["ollama_min"])}
        info = self.survey()
        ok, msg = ce.hardware_verdict(info, pins["hardware"])
        best = max((g for g in info.get("gpus", []) if core.gpu_role(g)), key=lambda g: g["vram_gb"], default=None)
        res["hardware"] = {"ok": ok, "message": msg, "gpu": best["name"] if best else "none the models can use",
                           "vram_gb": info.get("fast_gb", 0), "ram_gb": info.get("ram_gb", 0)}
        free = shutil.disk_usage(root).free / 2**30
        need = PROGRAM_GB + (MODEL_GB if with_model else 0)
        res["space"] = {"free_gb": round(free, 1), "need_gb": round(need, 1), "ok": free >= need + 1}
        res["code_installed"] = self._describe(root)["code_installed"]
        return res

    def start_install(self, plan):
        plan = {"philibert": str(plan["philibert"]), "accept_slow": bool(plan.get("accept_slow")),
                "model": bool(plan.get("model", True)), "shortcut": bool(plan.get("shortcut"))}
        plan["source"] = philibert_setup.source()
        if plan["source"].get("repo") and self._token:
            plan["source"]["token"] = self._token
        self._state = {"steps": [], "step": 0, "step_pct": 0, "overall": 0, "detail": "Starting", "done": False,
                       "error": "", "warnings": []}

        def report(s):
            self._state = s
        self._installer = ce.CodeInstaller(plan, report)
        threading.Thread(target=self._installer.run, daemon=True).start()
        return True

    def open_code(self, root):
        bat = Path(root) / "code" / "Start-Philibert-Code.bat"
        if core.IS_WIN and bat.is_file():
            os.startfile(str(bat))
            return True
        return False


def main():
    import webview
    api = CodeApi()
    api._window = webview.create_window(
        "Philibert Code Setup", url=str(HERE / "code_ui" / "index.html"), js_api=api,
        width=1040, height=720, min_size=(940, 660), background_color="#0f172a")
    webview.start(gui="edgechromium" if core.IS_WIN else None, private_mode=True)


if __name__ == "__main__":
    main()
