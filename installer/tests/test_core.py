"""Philibert Setup: the rules the wizard relies on. Run: python installer/tests/test_core.py"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import core      # noqa: E402
import engine    # noqa: E402

REPO = HERE.parent.parent
fails = []


def check(label, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + label + ("" if ok else f"   ({detail})"))
    if not ok:
        fails.append(label)


# -- drive formats against the computers picked --------------------------------
V = core.format_verdict
check("exFAT works for both", V("exFAT", ["windows", "mac"])["ok"])
check("NTFS works for Windows only", V("NTFS", ["windows"])["ok"] and not V("NTFS", ["windows", "mac"])["ok"])
check("NTFS refused for a Mac-only drive", not V("NTFS", ["mac"])["ok"])
check("APFS works for Mac only", V("apfs", ["mac"])["ok"] and not V("apfs", ["windows"])["ok"])
check("Mac OS Extended works for Mac only", V("hfs", ["mac"])["ok"] and not V("hfs", ["windows", "mac"])["ok"])
check("FAT32 refused everywhere (files over 4 GB)", not V("FAT32", ["windows"])["ok"] and not V("msdos", ["mac"])["ok"])
check("an unknown format is refused with a reason", not V("zfs", ["windows"])["ok"] and "zfs" in V("zfs", ["windows"])["message"])
check("a refusal says how to fix it", "exFAT" in V("NTFS", ["windows", "mac"])["message"])

# -- model ratings ---------------------------------------------------------------
gpu16 = {"fast_gb": 15.9, "ram_gb": 61.4}
cpu8 = {"fast_gb": 0, "ram_gb": 8}
mac36 = {"fast_gb": 25.2, "ram_gb": 36}
m = lambda size: {"size_gb": size}
check("13.7 GB 27B is green on a 16 GB card (measured: loads as 14 GB)", core.rate(m(13.7), gpu16)[0] == "green")
check("15.7 GB 27B is yellow on a 16 GB card (measured: 16% on the processor)", core.rate(m(15.7), gpu16)[0] == "yellow")
check("25.9 GB 27B is yellow with lots of RAM", core.rate(m(25.9), gpu16)[0] == "yellow")
check("no graphics card + 8 GB RAM: 4B runs (yellow), 14B does not (red)",
      core.rate(m(3.3), cpu8)[0] == "yellow" and core.rate(m(9.3), cpu8)[0] == "red")
check("a 36 GB Apple Silicon Mac runs the 15.7 GB 27B at full speed", core.rate(m(15.7), mac36)[0] == "green")
check("every catalog model gets a rating", all(x["rating"] in ("green", "yellow", "red")
                                                 for x in core.rated_catalog(gpu16, REPO / "models.json")))
check("required models are locked on", all(x["locked"] for x in core.rated_catalog(gpu16, REPO / "models.json")
                                         if x.get("required")))
check("the vision model is required", any(x.get("vision") and x.get("required")
                                          for x in core.catalog(REPO / "models.json")))

# -- pins: one set of versions everywhere ------------------------------------------------
pins = json.loads((REPO / "setup" / "pins.json").read_text(encoding="utf-8"))
w = (REPO / "setup" / "windows.ps1").read_text(encoding="utf-8")
mac = (REPO / "setup" / "mac.sh").read_text(encoding="utf-8")
check("windows.ps1 uses the pinned Python, Ollama and window",
      pins["python"]["win-x64"] in w and pins["ollama"]["win-x64"] in w and pins["chromium"]["win-x64"] in w)
check("windows.ps1 installs exactly the pinned packages", all('"' + p + '"' in w for p in pins["packages"]["windows"]))
mp = re.search(r'PKGS="([^"]+)"', mac).group(1).split()
check("mac.sh installs exactly the pinned packages", mp == pins["packages"]["mac"], mp)
check("mac.sh uses the pinned Ollama and window versions",
      f'OL_VER="{pins["ollama"]["version"]}"' in mac and f'CR_VER="{pins["chromium"]["version"]}"' in mac)
check("every platform has every runtime", all(set(pins[k]) >= {"win-x64", "mac-arm64", "mac-x64"}
                                              for k in ("python", "ollama", "chromium")))

# -- the engine's plan --------------------------------------------------------------
check("'both' means Windows and both Mac chips",
      engine.platforms_for(["windows", "mac"]) == ["win-x64", "mac-arm64", "mac-x64"])
check("what ships matches the dev deploy list",
      engine.SHIP == __import__("importlib").import_module("deploy_local", package=None).SHIP
      if (sys.path.insert(0, str(REPO / "dev")) or True) else False)
check("mac.sh looks for pre-downloaded archives where the installer puts them",
      'DL="$ROOT/runtime/_download/$CRP"' in mac)

# -- "Retro Vault only": no Ollama, no models, the games on the Full desktop -----------
import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    ins = engine.Installer({"dest": tmp, "pcs": ["windows", "mac"], "edition": "retro", "models": ["qwen3:8b"],
                            "shortcut": False}, lambda s: None)
    ran = []
    for name in dir(ins):
        if name.startswith("step_"):
            setattr(ins, name, (lambda n: lambda *a: ran.append(n))(name[5:]))
    ins.run()
    check("retro-only becomes the Full desktop with Retro Vault and no models",
          ins.plan["edition"] == "full" and ins.retro_only and ins.plan["models"] == []
          and ins.plan["full"]["retro_vault"] and not ins.plan["full"]["image_gen"], ins.plan)
    check("retro-only skips the AI models but gets the game players",
          "models" not in ran and "games" in ran and "data" in ran, ran)
check("windows.ps1 skips Ollama on a retro-only drive",
      "$cfg.NoAI = [bool]" in w and "-not $cfg.NoAI -and" in w and 'if ($cfg.NoAI) { Log "Retro Vault only' in w)
check("mac.sh skips Ollama on a retro-only drive", 'NOAI=1' in mac and 'if [ "$NOAI" = 1 ]; then' in mac)
ui = (REPO / "installer" / "ui" / "setup.js").read_text(encoding="utf-8")
check("the wizard offers Retro Vault only and skips the models page for it",
      'data-ed="retro"' in (REPO / "installer" / "ui" / "index.html").read_text(encoding="utf-8")
      and "MODELS_PAGE && noAi()" in ui)

print("PASS" if not fails else f"FAIL ({len(fails)})")
sys.exit(1 if fails else 0)
