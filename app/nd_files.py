"""File Manager: the files in Philibert's folder on the drive, and nowhere else.

Everything is a path relative to the drive's Philibert folder (root). Philibert's own
program folders are read-only (the same list the chat may never write into); deleting
moves a file to data/.trash/files, where the desktop Trash lists it and puts it back.

Entry point: handle(body, root) -> dict, and file_for(root, rel) for the GET route.
"""
import json
import os
import shutil
import time
from pathlib import Path

READ_ONLY = ("app", "setup", "runtime", "models", "installer", "brand", "Entertainment/emulator", "data/.trash")
IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


class FilesError(Exception):
    pass


def _root(root):
    return Path(root).resolve()


def resolve(root, rel):
    """A path inside root, or FilesError - '..', drive letters and links out are refused."""
    r = _root(root)
    rel = str(rel or "").replace("\\", "/").strip("/")
    if ":" in rel:
        raise FilesError("only paths inside Philibert's folder")
    q = (r / rel).resolve()
    if q != r and r not in q.parents:
        raise FilesError("only paths inside Philibert's folder")
    return q


def rel_of(root, p):
    return Path(p).resolve().relative_to(_root(root)).as_posix()


def read_only(root, p):
    """The read-only folder p is in, or ''."""
    r = _root(root)
    q = Path(p).resolve()
    if q == r:
        return "."                                  # the top: no new files beside Start-Windows.bat
    for d in READ_ONLY:
        b = (r / d).resolve()
        if q == b or b in q.parents:
            return d
    return ""


def _writable(root, p, what="change"):
    ro = read_only(root, p)
    if ro:
        raise FilesError(f"{ro if ro != '.' else 'The top of the drive'} is Philibert's own - it can't {what} there."
                         if ro != "." else f"The top of Philibert's folder is its own - {what} inside a folder like data.")


def listing(root, rel=""):
    d = resolve(root, rel)
    if not d.is_dir():
        raise FilesError("no such folder")
    items = []
    for e in sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if e.name.startswith(".") and e.name not in (".trash",):
            continue
        # a picture's .json card (its prompt and seed) travels with it: show the picture only
        if e.suffix.lower() == ".json" and e.with_suffix(".png").exists():
            continue
        try:
            st = e.stat()
        except OSError:
            continue
        items.append({"name": e.name, "path": rel_of(root, e), "dir": e.is_dir(), "size": 0 if e.is_dir() else st.st_size,
                      "mtime": st.st_mtime, "image": e.suffix.lower() in IMAGE,
                      "card": e.suffix.lower() == ".png" and e.with_suffix(".json").exists()})
    return {"path": rel_of(root, d) if d != _root(root) else "", "items": items[:2000],
            "read_only": bool(read_only(root, d)), "parent": rel_of(root, d.parent) if d != _root(root) else None}


def _unique(p):
    if not p.exists():
        return p
    stem, suf, n = p.stem, p.suffix, 2
    while True:
        q = p.with_name(f"{stem} ({n}){suf}")
        if not q.exists():
            return q
        n += 1


def mkdir(root, rel, name):
    d = resolve(root, rel)
    _writable(root, d / "x", "make a folder")
    name = str(name or "").strip()
    if not name or any(c in name for c in '\\/:*?"<>|') or name.startswith("."):
        raise FilesError("that folder name won't work")
    q = _unique(d / name)
    q.mkdir(parents=True)
    return {"path": rel_of(root, q)}


def rename(root, rel, new):
    p = resolve(root, rel)
    _writable(root, p, "rename")
    new = str(new or "").strip()
    if not new or any(c in new for c in '\\/:*?"<>|') or new.startswith("."):
        raise FilesError("that name won't work")
    q = p.with_name(new)
    if q.exists():
        raise FilesError("something already has that name")
    p.rename(q)
    _sidecar(p, q, move=True)
    return {"path": rel_of(root, q)}


def _sidecar(src, dst, move):
    """A picture's .json (its prompt and seed) goes where the picture goes."""
    if src.suffix.lower() == ".png":
        s, d = src.with_suffix(".json"), dst.with_suffix(".json")
        if s.exists() and not d.exists():
            (shutil.move if move else shutil.copy2)(str(s), str(d))


def transfer(root, rels, dest, move):
    d = resolve(root, dest)
    if not d.is_dir():
        raise FilesError("no such folder")
    _writable(root, d / "x", "put files")
    done = []
    for rel in rels or []:
        p = resolve(root, rel)
        if not p.exists():
            continue
        if move:
            _writable(root, p, "move")
        if p.is_dir() and (d == p or p in d.parents):
            raise FilesError("a folder can't go inside itself")
        q = _unique(d / p.name)
        if move:
            shutil.move(str(p), str(q))
        elif p.is_dir():
            shutil.copytree(p, q)
        else:
            shutil.copy2(p, q)
        _sidecar(p, q, move)
        done.append(rel_of(root, q))
    return {"done": done}


def _trash_dir(root):
    return _root(root) / "data" / ".trash" / "files"


def _index(root):
    f = _trash_dir(root) / "index.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_index(root, idx):
    f = _trash_dir(root) / "index.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(idx, indent=1), encoding="utf-8")


def trash(root, rels):
    idx = _index(root)
    n = 0
    for rel in rels or []:
        p = resolve(root, rel)
        if not p.exists():
            continue
        _writable(root, p, "delete")
        key = f"{int(time.time() * 1000)}-{n}"
        dst = _trash_dir(root) / key / p.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dst))
        if p.suffix.lower() == ".png" and p.with_suffix(".json").exists():
            shutil.move(str(p.with_suffix(".json")), str(dst.with_suffix(".json")))
        idx.append({"id": key, "name": p.name, "from": rel_of(root, p.parent) if p.parent != _root(root) else "",
                    "at": time.time(), "dir": dst.is_dir()})
        n += 1
    _save_index(root, idx)
    return {"trashed": n}


def trash_list(root):
    return {"items": sorted(_index(root), key=lambda x: -x["at"])}


def restore(root, key):
    idx = _index(root)
    it = next((x for x in idx if x["id"] == key), None)
    if not it:
        raise FilesError("not in the Trash")
    src = _trash_dir(root) / key / it["name"]
    back = resolve(root, it["from"])
    back.mkdir(parents=True, exist_ok=True)
    q = _unique(back / it["name"])
    shutil.move(str(src), str(q))
    if src.with_suffix(".json").exists():
        shutil.move(str(src.with_suffix(".json")), str(q.with_suffix(".json")))
    shutil.rmtree(_trash_dir(root) / key, ignore_errors=True)
    _save_index(root, [x for x in idx if x["id"] != key])
    return {"path": rel_of(root, q)}


def file_for(root, rel):
    """A file to show or download (GET), or None."""
    try:
        p = resolve(root, rel)
    except FilesError:
        return None
    return p if p.is_file() else None


def handle(body, root):
    body = body or {}
    op = body.get("op", "")
    try:
        if op == "list":
            return {"ok": True, **listing(root, body.get("path", ""))}
        if op == "mkdir":
            return {"ok": True, **mkdir(root, body.get("path", ""), body.get("name"))}
        if op == "rename":
            return {"ok": True, **rename(root, body.get("path", ""), body.get("name"))}
        if op in ("copy", "move"):
            return {"ok": True, **transfer(root, body.get("paths") or [], body.get("dest", ""), op == "move")}
        if op == "trash":
            return {"ok": True, **trash(root, body.get("paths") or [])}
        if op == "trash_list":
            return {"ok": True, **trash_list(root)}
        if op == "restore":
            return {"ok": True, **restore(root, str(body.get("id") or ""))}
        return {"ok": False, "msg": f"unknown op {op!r}"}
    except FilesError as e:
        return {"ok": False, "msg": str(e)}
    except OSError as e:
        return {"ok": False, "msg": f"The drive said no: {e.strerror or e}"}
