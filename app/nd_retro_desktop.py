"""The Full edition's retro desktop: its settings, what the installer put on the
drive, and the apps that sit on the desktop. (Not nd_desktop.py - that one is
the hidden Windows desktop the automation ladder uses.)

  <data>/desktop.json    theme, wallpaper, sounds, screensaver, icon positions -
                         one file for both PCs (the browser profiles differ per OS)
  <data>/install.json    written by Philibert Setup: edition, themes chosen
                         (each with sounds / wallpapers), Retro Vault yes/no
  <drive>/Apps/<id>/     published apps: app.json {name, icon, entry, version,
                         source: "nd" | "git"} + their files, served at /apps/<id>/

Entry point: handle(body, data_dir, apps_dir, shutdown) -> dict.
"""
import json
import os
import re
import time
from pathlib import Path

THEMES = [  # id, name, family - the order the Control Panel lists them
    ("win311", "Windows 3.11", "win"), ("win95", "Windows 95", "win"), ("winxp", "Windows XP", "win"),
    ("win11", "Windows 11", "win"), ("os8", "Mac OS 8", "mac"), ("os9", "Mac OS 9.2", "mac"),
    ("macos", "macOS", "mac"), ("ios", "iOS", "phone"), ("android", "Android", "phone"),
    ("c64", "Commodore 64", "c64"),
]
READY = {t[0] for t in THEMES}
# themes added after a drive was set up: it never had the chance to say no to them
ADDED_LATER = {"win11", "macos", "ios", "android", "c64"}
DEFAULTS = {"theme": "win95", "wallpaper": "teal", "sounds": True, "boot": True,
            "screensaver": True, "saver_minutes": 10, "icons": {}}
_APP_ID = re.compile(r"^[a-z0-9][a-z0-9_\-]{1,40}$")


def install_info(data_dir):
    try:
        return json.loads((Path(data_dir) / "install.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def edition(data_dir):
    return install_info(data_dir).get("edition", "slim")


def themes(data_dir):
    full = install_info(data_dir).get("full") or {}
    chosen = full.get("themes") or {"win95": {"sounds": True, "wallpapers": True}}
    offered = set(full.get("themes_offered") or ())     # what Setup listed (newer installs record it)
    out = []
    for tid, name, fam in THEMES:
        if tid not in chosen and not (tid in ADDED_LATER and tid not in offered):
            continue
        opt = chosen.get(tid) or {}             # a theme added later: its sounds and wallpapers come along
        out.append({"id": tid, "name": name, "family": fam, "ready": tid in READY,
                    "sounds": bool(opt.get("sounds", True)), "wallpapers": bool(opt.get("wallpapers", True))})
    if not any(t["id"] == "win95" for t in out):     # the default is always there
        out.insert(0, {"id": "win95", "name": "Windows 95", "family": "win", "ready": True,
                       "sounds": True, "wallpapers": True})
    return out


def settings(data_dir):
    s = dict(DEFAULTS)
    try:
        s.update(json.loads((Path(data_dir) / "desktop.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        default = (install_info(data_dir).get("full") or {}).get("default_theme")
        if default:
            s["theme"] = default
    if s["theme"] not in READY:                 # a theme since retired (98, ME, System 7)
        s["theme"] = "win95"
    return s


def save_settings(data_dir, changes):
    s = settings(data_dir)
    for k, v in (changes or {}).items():
        if k not in DEFAULTS:
            continue
        if k == "theme" and v not in READY:
            continue
        if k in ("sounds", "boot", "screensaver"):
            v = bool(v)
        if k == "saver_minutes":
            try:
                v = max(1, min(60, int(v)))
            except (TypeError, ValueError):
                continue
        if k == "icons":
            # {shell: {icon id: [x, y]}} - a Mac layout is not a Windows one
            if not isinstance(v, dict):
                continue
            clean = {}
            for shell, pos in list(v.items())[:8]:
                if shell not in ("taskbar", "progman", "menubar", "phone", "c64") or not isinstance(pos, dict):
                    continue
                clean[shell] = {}
                for i, p in list(pos.items())[:200]:
                    try:
                        clean[shell][str(i)[:60]] = [int(p[0]), int(p[1])]
                    except (TypeError, ValueError, IndexError, KeyError):
                        continue
            v = clean
        if k == "wallpaper":
            v = re.sub(r"[^a-z0-9\-]", "", str(v))[:30] or "teal"
        s[k] = v
    p = Path(data_dir) / "desktop.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(".desktop.json.saving")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return s


def apps(apps_dir):
    """Published apps: every Apps/<id>/app.json that names an entry file that exists."""
    out = []
    root = Path(apps_dir) if apps_dir else None
    if not root or not root.is_dir():
        return out
    for d in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not d.is_dir() or not _APP_ID.match(d.name):
            continue
        try:
            meta = json.loads((d / "app.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entry = str(meta.get("entry") or "index.html")
        if ".." in entry or entry.startswith(("/", "\\")) or not (d / entry).is_file():
            continue
        icon = str(meta.get("icon") or "")
        ok_icon = icon and ".." not in icon and not icon.startswith(("/", "\\")) and (d / icon).is_file()
        out.append({"id": d.name, "name": str(meta.get("name") or d.name)[:40],
                    "url": f"/apps/{d.name}/{entry}",
                    "icon": f"/apps/{d.name}/{icon}" if ok_icon else "",
                    "version": str(meta.get("version") or "")[:20],
                    "source": "git" if meta.get("source") == "git" else "nd"})
    return out


_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vscode"}
MAX_APP_FILES, MAX_APP_BYTES = 400, 60_000_000


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:40]
    return s if len(s) >= 2 else "app-" + time.strftime("%H%M%S")


def publish(apps_dir, src, name, entry="", icon="", version=""):
    """Put an app ND built onto the desktop: copy `src` (a folder, or one .html
    file) into Apps/<id>/ with its app.json. An app ND published before is
    updated in place; an app that came with a git update is never overwritten."""
    import shutil
    src = Path(str(src or "")).expanduser()
    if not src.exists():
        return {"ok": False, "msg": f"Nothing at {src}."}
    name = re.sub(r"\s+", " ", str(name or src.stem)).strip()[:40] or "My app"
    aid = slug(name)
    dest = Path(apps_dir) / aid
    meta_old = {}
    if (dest / "app.json").is_file():
        try:
            meta_old = json.loads((dest / "app.json").read_text(encoding="utf-8"))
        except ValueError:
            meta_old = {}
        if meta_old.get("source") == "git":
            return {"ok": False, "msg": f'"{name}" came with a Philibert update; pick another name.'}
    if src.is_file():
        if src.suffix.lower() not in (".html", ".htm"):
            return {"ok": False, "msg": "A one-file app must be an .html page."}
        files, root, entry = [src], src.parent, src.name
    else:
        root, files = src, []
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            files += [Path(dirpath) / f for f in filenames if not f.startswith(".")]
        entry = entry or ("index.html" if (src / "index.html").is_file() else
                          next((f.name for f in sorted(src.glob("*.htm*"))), ""))
        if not entry or not (src / entry).is_file():
            return {"ok": False, "msg": "That folder has no HTML page to open (index.html)."}
    if len(files) > MAX_APP_FILES or sum(f.stat().st_size for f in files) > MAX_APP_BYTES:
        return {"ok": False, "msg": f"Too big for a desktop app ({MAX_APP_FILES} files / 60 MB at most)."}
    tmp = dest.with_name("." + aid + ".publishing")
    shutil.rmtree(tmp, ignore_errors=True)
    for f in files:
        out = tmp / f.relative_to(root)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, out)
    try:
        n = int(str(meta_old.get("version", "0")).split(".")[-1]) + 1 if meta_old else 1
    except ValueError:
        n = 1
    meta = {"name": name, "entry": entry, "version": str(version or f"1.{n}"), "source": "nd",
            "published": time.strftime("%Y-%m-%d %H:%M")}
    if icon and (tmp / icon).is_file():
        meta["icon"] = icon
    (tmp / "app.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if dest.exists():
        old = Path(apps_dir) / ".trash" / f"{aid}-{time.strftime('%Y%m%d-%H%M%S')}"
        old.parent.mkdir(parents=True, exist_ok=True)
        os.replace(dest, old)                  # the previous version is kept, not deleted
    os.replace(tmp, dest)
    return {"ok": True, "id": aid, "name": name, "url": f"/apps/{aid}/{entry}", "version": meta["version"],
            "updated": bool(meta_old)}


def remove(apps_dir, aid):
    """Take an app off the desktop: it moves to Apps/.trash, nothing is deleted."""
    if not _APP_ID.match(str(aid or "")):
        return {"ok": False, "msg": "no such app"}
    d = Path(apps_dir) / aid
    if not d.is_dir():
        return {"ok": False, "msg": "no such app"}
    t = Path(apps_dir) / ".trash" / f"{aid}-{time.strftime('%Y%m%d-%H%M%S')}"
    t.parent.mkdir(parents=True, exist_ok=True)
    os.replace(d, t)
    return {"ok": True}


def app_file(apps_dir, rel):
    """The file behind /apps/<rel>, or None if it is outside Apps/ or missing."""
    try:
        root = Path(apps_dir).resolve()
        p = (root / rel).resolve()
        p.relative_to(root)
    except (ValueError, OSError, TypeError):
        return None
    return p if p.is_file() else None


def handle(body, data_dir, apps_dir, shutdown=None):
    body = body or {}
    op = body.get("op", "")
    if op == "state":
        info = install_info(data_dir)
        return {"ok": True, "settings": settings(data_dir), "themes": themes(data_dir),
                "apps": apps(apps_dir), "edition": info.get("edition", "slim"),
                "retro_vault": bool((info.get("full") or {}).get("retro_vault", False)),
                # every Full desktop: the app sets itself up on each computer (drives set up
                # before the Setup option existed had no icon at all)
                "image_gen": True,
                "now": time.time()}
    if op == "save":
        return {"ok": True, "settings": save_settings(data_dir, body.get("settings"))}
    if op == "app_remove":
        return remove(apps_dir, body.get("id"))
    if op == "shutdown":
        if shutdown is None:
            return {"ok": False, "msg": "Close the window to shut down."}
        shutdown()
        return {"ok": True}
    return {"ok": False, "msg": f"unknown op {op!r}"}
