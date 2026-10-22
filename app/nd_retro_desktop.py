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
    ("win311", "Windows 3.11", "win"), ("win95", "Windows 95", "win"), ("win98", "Windows 98", "win"),
    ("winme", "Windows ME", "win"), ("winxp", "Windows XP", "win"),
    ("sys7", "Mac System 7", "mac"), ("os8", "Mac OS 8", "mac"), ("os9", "Mac OS 9.2", "mac"),
]
READY = {t[0] for t in THEMES}      # all eight are built
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
    out = []
    for tid, name, fam in THEMES:
        if tid not in chosen:
            continue
        opt = chosen[tid] or {}
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
    if s["theme"] not in READY:
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
                if shell not in ("taskbar", "progman", "menubar") or not isinstance(pos, dict):
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
                "now": time.time()}
    if op == "save":
        return {"ok": True, "settings": save_settings(data_dir, body.get("settings"))}
    if op == "shutdown":
        if shutdown is None:
            return {"ok": False, "msg": "Close the window to shut down."}
        shutdown()
        return {"ok": True}
    return {"ok": False, "msg": f"unknown op {op!r}"}
