"""The Notes app's backend: the vault as plain Markdown files, read and written.

Everything is a .md file inside the vault, laid out the way Obsidian lays it
out, so the same folder opens in Obsidian unchanged:

  - notes are <vault>/<folder>/<title>.md; [[wikilinks]] resolve by title
  - deleting moves the note to <vault>/.trash (Obsidian's own trash folder);
    nothing is ever deleted for good from here, and every trashed note can be
    put back where it was
  - templates are the notes in <vault>/Templates; {{title}}, {{date}} and
    {{time}} are filled in, as Obsidian's core Templates plugin does
  - renaming a note rewrites the [[links]] that point at it

Folders and files whose name starts with "." (.obsidian, .trash) are never
listed as notes. No path ever resolves outside the vault.

Entry point: handle(body, vault, on_event) -> dict, one JSON request per call.
`on_event(op, path)` is told about every write so the vault view can light up.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

TEMPLATES = "Templates"
TRASH = ".trash"
TRASH_INDEX = ".philibert-trash.json"
MAX_NOTE = 2_000_000                    # bytes; a note bigger than this is refused
_lock = threading.Lock()

_BAD_CHARS = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}
_LINK = re.compile(r"\[\[([^\]|#]+)")
_FRONT = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n?", re.DOTALL)


class NoteError(Exception):
    pass


# --- paths ---------------------------------------------------------------------
def clean_title(title):
    """A title that is safe as a file name on Windows, Mac and in Obsidian."""
    t = _BAD_CHARS.sub(" ", str(title or ""))
    t = re.sub(r"\s+", " ", t).strip().strip(".")
    t = t[:120].strip()
    if not t:
        t = "Untitled"
    if t.lower() in _RESERVED:
        t += " note"
    return t


def clean_folder(folder):
    parts = []
    for p in re.split(r"[\\/]+", str(folder or "")):
        p = p.strip()
        if not p or p in (".", ".."):
            continue
        parts.append(clean_title(p))
    return "/".join(parts)


def _inside(vault, rel):
    """vault/rel resolved, refused if it leaves the vault or touches a hidden part."""
    root = Path(vault).resolve()
    rel = str(rel or "").replace("\\", "/")
    if any(part.startswith(".") for part in rel.split("/") if part):
        raise NoteError("hidden folders are not notes")
    p = (root / rel).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise NoteError("outside the vault")
    return p


def _note_path(vault, note_id):
    p = _inside(vault, note_id)
    if p.suffix.lower() != ".md":
        raise NoteError("not a note")
    return p


def _rel(vault, p):
    return Path(p).resolve().relative_to(Path(vault).resolve()).as_posix()


def _visible(vault, p):
    rel = _rel(vault, p)
    return not any(part.startswith(".") for part in rel.split("/"))


def _all_notes(vault):
    root = Path(vault)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for f in sorted(filenames):
            if f.lower().endswith(".md") and not f.startswith("."):
                out.append(Path(dirpath) / f)
    return out


def _unique(path):
    """path, or "path 2", "path 3" ... when it is taken."""
    if not path.exists():
        return path
    for i in range(2, 1000):
        q = path.with_name(f"{path.stem} {i}{path.suffix}")
        if not q.exists():
            return q
    raise NoteError("too many notes with that name")


def _read(p):
    data = p.read_bytes()
    return data.decode("utf-8", errors="replace")


def digest(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _write(p, text):
    """Write atomically: a crash or a pulled drive never leaves half a note."""
    data = text.encode("utf-8")
    if len(data) > MAX_NOTE:
        raise NoteError("this note is too big to save (2 MB)")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.saving")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


# --- the requests ----------------------------------------------------------------
def tree(vault):
    root = Path(vault)
    notes, folders = [], set()
    for p in _all_notes(vault):
        rel = _rel(vault, p)
        st = p.stat()
        folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
        notes.append({"id": rel, "title": p.stem, "folder": folder,
                      "mtime": st.st_mtime, "size": st.st_size})
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for d in dirnames:
            folders.add(_rel(vault, Path(dirpath) / d))
    return {"notes": notes, "folders": sorted(folders, key=str.lower)}


def _by_title(vault):
    """lower-case title -> note path; the shallowest one wins, as in Obsidian."""
    m = {}
    for p in sorted(_all_notes(vault), key=lambda q: (len(q.parts), str(q).lower())):
        m.setdefault(p.stem.lower(), p)
    return m


def links_of(text):
    return [n.strip().split("/")[-1] for n in _LINK.findall(text or "") if n.strip()]


def read(vault, note_id):
    p = _note_path(vault, note_id)
    if not p.is_file():
        raise NoteError("no such note")
    text = _read(p)
    titles = _by_title(vault)
    me = p.stem.lower()
    backlinks, outgoing = [], []
    for name in dict.fromkeys(links_of(text)):
        q = titles.get(name.lower())
        outgoing.append({"name": name, "id": _rel(vault, q) if q else None})
    for q in _all_notes(vault):
        if q == p:
            continue
        try:
            body = _read(q)
        except OSError:
            continue
        if any(n.lower() == me for n in links_of(body)):
            backlinks.append(_rel(vault, q))
    return {"id": _rel(vault, p), "title": p.stem, "body": text, "hash": digest(text),
            "mtime": p.stat().st_mtime, "backlinks": backlinks, "outgoing": outgoing}


def save(vault, note_id, body, base_hash=None, on_event=None):
    p = _note_path(vault, note_id)
    with _lock:
        if p.exists() and base_hash:
            now = _read(p)
            if digest(now) != base_hash and now != body:
                # changed on the drive since it was opened (Obsidian, the assistant,
                # another PC): hand both back instead of overwriting either
                return {"ok": False, "conflict": True, "body": now, "hash": digest(now)}
        _write(p, body)
    if on_event:
        on_event("update", p)
    return {"ok": True, "id": _rel(vault, p), "hash": digest(body), "mtime": p.stat().st_mtime}


def fill_template(text, title, now=None):
    now = now or time.localtime()

    def fmt(spec, default):
        spec = spec or default
        for a, b in (("YYYY", "%Y"), ("MM", "%m"), ("DD", "%d"), ("HH", "%H"), ("mm", "%M"),
                     ("ddd", "%a"), ("dddd", "%A")):
            spec = spec.replace(a, b)
        return time.strftime(spec, now)

    text = re.sub(r"\{\{\s*title\s*\}\}", lambda m: title, text)
    text = re.sub(r"\{\{\s*date(?::([^}]+))?\s*\}\}", lambda m: fmt(m.group(1), "YYYY-MM-DD"), text)
    text = re.sub(r"\{\{\s*time(?::([^}]+))?\s*\}\}", lambda m: fmt(m.group(1), "HH:mm"), text)
    return text


def templates(vault):
    d = Path(vault) / TEMPLATES
    if not d.is_dir():
        return []
    return [{"id": _rel(vault, p), "title": p.stem}
            for p in sorted(d.glob("*.md"), key=lambda q: q.stem.lower())]


def create(vault, folder="", title="", template=None, body=None, on_event=None):
    title = clean_title(title or "Untitled")
    folder = clean_folder(folder)
    text = body if body is not None else ""
    if template:
        tp = _note_path(vault, template)
        if not tp.is_file():
            raise NoteError("no such template")
        text = fill_template(_read(tp), title)
    with _lock:
        p = _unique(_inside(vault, (folder + "/" if folder else "") + title + ".md"))
        _write(p, text)
    if on_event:
        on_event("write", p)
    return {"ok": True, "id": _rel(vault, p), "title": p.stem}


def mkdir(vault, folder):
    folder = clean_folder(folder)
    if not folder:
        raise NoteError("give the folder a name")
    p = _inside(vault, folder)
    p.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "folder": _rel(vault, p)}


def _relink(vault, old, new, skip=None):
    """Point [[old]], [[old|alias]], [[old#heading]] and [[path/old]] at `new`."""
    pat = re.compile(r"\[\[(?:[^\]|#]*/)?" + re.escape(old) + r"(?=\s*[\]|#])", re.IGNORECASE)
    changed = []
    for q in _all_notes(vault):
        if skip is not None and q == skip:
            continue
        try:
            text = _read(q)
        except OSError:
            continue
        new_text = pat.sub("[[" + new, text)
        if new_text != text:
            _write(q, new_text)
            changed.append(_rel(vault, q))
    return changed


def rename(vault, note_id, title=None, folder=None, relink=True, on_event=None):
    p = _note_path(vault, note_id)
    if not p.is_file():
        raise NoteError("no such note")
    new_title = clean_title(title) if title is not None else p.stem
    here = _rel(vault, p)
    new_folder = clean_folder(folder) if folder is not None else (here.rsplit("/", 1)[0] if "/" in here else "")
    with _lock:
        rel = (new_folder + "/" if new_folder else "") + new_title + ".md"
        _inside(vault, rel)                         # the checks only: resolve() would
        dest = Path(vault).resolve() / rel          # undo a case-only rename on Windows
        if str(dest) == str(p):
            return {"ok": True, "id": _rel(vault, p), "title": p.stem, "relinked": []}
        if dest.exists() and dest.resolve() != p.resolve():
            # a case-only rename on Windows/Mac resolves to the same file - allowed
            raise NoteError(f'"{new_title}" already exists there')
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(p, dest)
        relinked = _relink(vault, p.stem, dest.stem, skip=None) if relink and dest.stem != p.stem else []
    if on_event:
        on_event("update", dest)
    return {"ok": True, "id": _rel(vault, dest), "title": dest.stem, "relinked": relinked}


def _trash_index(vault):
    f = Path(vault) / TRASH / TRASH_INDEX
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_trash_index(vault, idx):
    _write(Path(vault) / TRASH / TRASH_INDEX, json.dumps(idx, indent=1))


def trash(vault, note_id):
    p = _note_path(vault, note_id)
    if not p.is_file():
        raise NoteError("no such note")
    with _lock:
        d = Path(vault) / TRASH
        d.mkdir(exist_ok=True)
        origin = _rel(vault, p)
        dest = _unique(d / p.name)
        os.replace(p, dest)
        idx = _trash_index(vault)
        idx[dest.name] = {"from": origin, "at": time.time()}
        _save_trash_index(vault, idx)
    return {"ok": True, "trashed": dest.name}


def trash_list(vault):
    d = Path(vault) / TRASH
    idx = _trash_index(vault)
    items = []
    if d.is_dir():
        for p in sorted(d.glob("*.md"), key=lambda q: q.stat().st_mtime, reverse=True):
            info = idx.get(p.name, {})
            items.append({"name": p.name, "title": p.stem, "from": info.get("from") or p.name,
                          "at": info.get("at") or p.stat().st_mtime})
    return {"items": items}


def restore(vault, name):
    d = (Path(vault) / TRASH).resolve()
    p = (d / str(name)).resolve()
    if p.parent != d or p.suffix.lower() != ".md" or not p.is_file():
        raise NoteError("not in the trash")
    with _lock:
        idx = _trash_index(vault)
        orig = (idx.get(p.name) or {}).get("from") or p.name
        try:
            dest = _unique(_note_path(vault, orig))
        except NoteError:
            dest = _unique(Path(vault).resolve() / p.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(p, dest)
        idx.pop(p.name, None)
        _save_trash_index(vault, idx)
    return {"ok": True, "id": _rel(vault, dest)}


def purge(vault, name=None):
    """Delete from the trash for good: one note, or all of them (name None)."""
    d = (Path(vault) / TRASH).resolve()
    with _lock:
        idx = _trash_index(vault)
        targets = [p for p in d.glob("*.md")] if name is None and d.is_dir() else []
        if name is not None:
            p = (d / str(name)).resolve()
            if p.parent != d or p.suffix.lower() != ".md" or not p.is_file():
                raise NoteError("not in the trash")
            targets = [p]
        for p in targets:
            p.unlink()
            idx.pop(p.name, None)
        if d.is_dir():
            _save_trash_index(vault, idx)
    return {"ok": True, "deleted": len(targets)}


def search(vault, q, limit=60):
    words = [w for w in str(q or "").lower().split() if w]
    if not words:
        return {"results": []}
    hits = []
    for p in _all_notes(vault):
        try:
            text = _read(p)
        except OSError:
            continue
        low, title = text.lower(), p.stem.lower()
        if not all(w in low or w in title for w in words):
            continue
        score = sum(3 for w in words if w in title) + sum(min(low.count(w), 5) for w in words)
        fm = _FRONT.match(text)                 # the snippet starts after the front matter
        if fm:
            text, low = text[fm.end():], low[fm.end():]
        i = min([low.find(w) for w in words if w in low] or [0])
        a = max(0, i - 60)
        snip = re.sub(r"\s+", " ", text[a:i + 120]).strip()
        hits.append({"id": _rel(vault, p), "title": p.stem, "snippet": ("…" if a else "") + snip,
                     "score": score, "mtime": p.stat().st_mtime})
    hits.sort(key=lambda h: (-h["score"], -h["mtime"]))
    return {"results": hits[:limit]}


# --- Obsidian, when it is on this computer -------------------------------------------
def obsidian_installed():
    if sys.platform == "win32":
        try:
            import winreg
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "obsidian"))
            return True
        except OSError:
            return False
    if sys.platform == "darwin":
        return any(Path(d, "Obsidian.app").exists()
                   for d in ("/Applications", os.path.expanduser("~/Applications")))
    return False


def open_in_obsidian(vault, note_id=None):
    if not obsidian_installed():
        return {"ok": False, "msg": "Obsidian is not installed on this computer."}
    target = _note_path(vault, note_id) if note_id else Path(vault).resolve()
    uri = "obsidian://open?path=" + urllib.parse.quote(str(target), safe="")
    try:
        if sys.platform == "win32":
            os.startfile(uri)
        else:
            subprocess.Popen(["open", uri])
    except OSError as e:
        return {"ok": False, "msg": f"Obsidian did not open ({e})."}
    return {"ok": True, "vault": str(Path(vault).resolve()),
            "hint": "If Obsidian says it does not know this vault, choose "
                    "\"Open folder as vault\" and pick the folder shown here once."}


# --- one request -------------------------------------------------------------------------
def handle(body, vault, on_event=None):
    op = (body or {}).get("op", "")
    if not vault or not Path(vault).is_dir():
        return {"ok": False, "msg": "There is no notes folder yet."}
    try:
        if op == "info":
            return {"ok": True, "vault": str(Path(vault).resolve()), "obsidian": obsidian_installed(),
                    "templates": templates(vault)}
        if op == "tree":
            return {"ok": True, **tree(vault)}
        if op == "read":
            return {"ok": True, **read(vault, body.get("id"))}
        if op == "save":
            return save(vault, body.get("id"), str(body.get("body") or ""), body.get("hash"), on_event)
        if op == "create":
            return create(vault, body.get("folder", ""), body.get("title", ""), body.get("template"),
                          body.get("body"), on_event)
        if op == "mkdir":
            return mkdir(vault, body.get("folder"))
        if op == "rename":
            return rename(vault, body.get("id"), body.get("title"), body.get("folder"),
                          body.get("relink", True), on_event)
        if op == "trash":
            return trash(vault, body.get("id"))
        if op == "trash_list":
            return {"ok": True, **trash_list(vault)}
        if op == "restore":
            return restore(vault, body.get("name"))
        if op == "purge":
            return purge(vault, body.get("name"))
        if op == "search":
            return {"ok": True, **search(vault, body.get("q"))}
        if op == "obsidian":
            return open_in_obsidian(vault, body.get("id"))
        return {"ok": False, "msg": f"unknown op {op!r}"}
    except NoteError as e:
        return {"ok": False, "msg": str(e)}
    except OSError as e:
        return {"ok": False, "msg": f"The drive said no: {e.strerror or e}"}
