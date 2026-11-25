"""Removed desktop apps in the Trash (Philibert only; dev/patching.py DESKTOP_TRASH hooks it into
nd_retro_desktop.handle).

Taking a published app off the desktop moves Apps/<id> to Apps/.trash/<id>-<YYYYmmdd-HHMMSS>. Publishing a
new version of an app puts the old one there under the same kind of name. So an entry in .trash is a
removed app only when no Apps/<id> is on the desktop now: the Trash shows the newest such entry per app;
old versions of apps still on the desktop are never shown or touched.

    handle(op, body, apps_dir) -> dict      ops: app_trash_list, app_restore {id}, app_purge {id?}
"""
import json
import os
import re
import shutil
import stat
import time
from pathlib import Path

_ENTRY = re.compile(r"^([a-z0-9][a-z0-9_\-]{1,40})-(\d{8}-\d{6})$")


def _removed(apps_dir):
    """{app id: [its .trash folders, newest first]} for apps that are not on the desktop now."""
    root = Path(apps_dir) if apps_dir else None
    trash = root / ".trash" if root else None
    out = {}
    if not trash or not trash.is_dir():
        return out
    for d in trash.iterdir():
        m = _ENTRY.match(d.name)
        if d.is_dir() and m and not (root / m.group(1)).exists():
            out.setdefault(m.group(1), []).append((m.group(2), d))
    return {aid: [d for _s, d in sorted(v, reverse=True)] for aid, v in out.items()}


def trash_list(apps_dir):
    items = []
    for aid, dirs in _removed(apps_dir).items():
        d = dirs[0]
        try:
            name = str(json.loads((d / "app.json").read_text(encoding="utf-8")).get("name") or aid)[:40]
        except (OSError, ValueError):
            name = aid
        stamp = _ENTRY.match(d.name).group(2)
        try:
            at = time.mktime(time.strptime(stamp, "%Y%m%d-%H%M%S"))
        except ValueError:
            at = d.stat().st_mtime
        items.append({"id": aid, "name": name, "at": at})
    return {"ok": True, "items": sorted(items, key=lambda i: -i["at"])}


def restore(apps_dir, aid):
    dirs = _removed(apps_dir).get(str(aid or ""))
    if not dirs:
        return {"ok": False, "msg": "That app is not in the Trash."}
    dest = Path(apps_dir) / aid
    if dest.exists():
        return {"ok": False, "msg": "An app with that name is on the desktop already."}
    os.replace(dirs[0], dest)
    return {"ok": True, "id": aid}


def _rmtree(p):
    def unlock(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(p, onerror=unlock)


def purge(apps_dir, aid=None):
    """Delete a removed app for good (every copy of it in .trash), or every removed app."""
    removed = _removed(apps_dir)
    if aid is not None and aid not in removed:
        return {"ok": False, "msg": "That app is not in the Trash."}
    n = 0
    for a in ([aid] if aid is not None else list(removed)):
        for d in removed[a]:
            _rmtree(d)
        n += 1
    return {"ok": True, "purged": n}


def handle(op, body, apps_dir):
    if op == "app_trash_list":
        return trash_list(apps_dir)
    if op == "app_restore":
        return restore(apps_dir, str(body.get("id") or ""))
    if op == "app_purge":
        return purge(apps_dir, str(body["id"]) if body.get("id") else None)
    return {"ok": False, "msg": f"unknown op {op!r}"}
