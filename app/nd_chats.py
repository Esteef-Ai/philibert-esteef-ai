"""Saved chats for Philibert's chat history panel: one JSON file per chat.

  <data>/chats/<id>.json        {id, title, folder, created, updated, messages, refs}
  <data>/chats/_folders.json    the folder names, so an empty folder survives
  <data>/chats/.trash/          deleted chats (put back from there; never erased here)

A message is {role: "user" | "assistant", content, t, steps?, hidden?}. `hidden`
messages are context the model sees but the transcript does not show - the
summary of an earlier chat the user chose to reference.

Entry point: handle(body, root) -> dict, one JSON request per call.
"""
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

MAX_CHAT = 4_000_000          # bytes on disk per chat
REF_CHARS = 6000              # how much of a referenced chat goes into a new one
_ID = re.compile(r"^c[0-9a-z\-]{6,40}$")
_lock = threading.Lock()


class ChatError(Exception):
    pass


def _clean(s, n=80):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:n].strip()


def _path(root, cid):
    if not _ID.match(str(cid or "")):
        raise ChatError("no such chat")
    return Path(root) / f"{cid}.json"


def _load(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ChatError("no such chat")


def _write(p, obj):
    data = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
    if len(data) > MAX_CHAT:
        raise ChatError("this chat is too long to save - start a new one")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.saving")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def _folders(root):
    try:
        names = json.loads((Path(root) / "_folders.json").read_text(encoding="utf-8"))
        return sorted({_clean(n, 60) for n in names if _clean(n, 60)}, key=str.lower)
    except (OSError, ValueError):
        return []


def _save_folders(root, names):
    _write(Path(root) / "_folders.json", sorted(set(names), key=str.lower))


def auto_title(messages):
    for m in messages or []:
        if m.get("role") == "user" and not m.get("hidden") and str(m.get("content") or "").strip():
            t = _clean(m["content"], 60)
            return t if len(str(m["content"]).strip()) <= 60 else t.rsplit(" ", 1)[0] + "…"
    return "New chat"


def _summary(c):
    shown = [m for m in c.get("messages") or [] if not m.get("hidden")]
    last = next((m for m in reversed(shown) if m.get("role") == "assistant"), None)
    return {"id": c["id"], "title": c.get("title") or "New chat", "folder": c.get("folder") or "",
            "created": c.get("created", 0), "updated": c.get("updated", 0), "count": len(shown),
            "preview": _clean((last or {}).get("content", ""), 90)}


# --- requests ---------------------------------------------------------------------------
def list_chats(root):
    out = []
    for p in Path(root).glob("c*.json"):
        try:
            out.append(_summary(_load(p)))
        except ChatError:
            continue
    out.sort(key=lambda c: -c["updated"])
    folders = set(_folders(root)) | {c["folder"] for c in out if c["folder"]}
    return {"chats": out, "folders": sorted(folders, key=str.lower)}


def get(root, cid):
    return {"chat": _load(_path(root, cid))}


def save(root, chat):
    chat = dict(chat or {})
    msgs = []
    for m in chat.get("messages") or []:
        if m.get("role") not in ("user", "assistant"):
            continue
        k = {"role": m["role"], "content": str(m.get("content") or ""), "t": m.get("t") or time.time()}
        if m.get("steps"):
            k["steps"] = [_clean(s, 200) for s in m["steps"]][:40]
        if m.get("hidden"):
            k["hidden"] = True
        msgs.append(k)
    now = time.time()
    with _lock:
        cid = chat.get("id")
        if cid:
            p = _path(root, cid)
            old = _load(p) if p.exists() else {}
        else:
            cid = "c" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
            p, old = _path(root, cid), {}
        title = _clean(chat.get("title") or old.get("title") or "", 80)
        if not title or title == "New chat":
            title = auto_title(msgs)
        rec = {"id": cid, "title": title, "folder": _clean(chat.get("folder", old.get("folder", "")), 60),
               "created": old.get("created") or now, "updated": now, "messages": msgs,
               "refs": [r for r in (chat.get("refs") or old.get("refs") or []) if _ID.match(str(r))][:8]}
        _write(p, rec)
    return {"ok": True, **_summary(rec)}


def rename(root, cid, title):
    title = _clean(title, 80)
    if not title:
        raise ChatError("give the chat a name")
    with _lock:
        p = _path(root, cid)
        c = _load(p)
        c["title"] = title
        _write(p, c)
    return {"ok": True, "title": title}


def move(root, cid, folder):
    folder = _clean(folder, 60)
    with _lock:
        p = _path(root, cid)
        c = _load(p)
        c["folder"] = folder
        _write(p, c)
        if folder and folder not in _folders(root):
            _save_folders(root, _folders(root) + [folder])
    return {"ok": True, "folder": folder}


def delete(root, cid):
    with _lock:
        p = _path(root, cid)
        if not p.exists():
            raise ChatError("no such chat")
        d = Path(root) / ".trash"
        d.mkdir(exist_ok=True)
        os.replace(p, d / p.name)
    return {"ok": True}


def restore(root, cid):
    with _lock:
        src = Path(root) / ".trash" / _path(root, cid).name
        if not src.exists():
            raise ChatError("not in the trash")
        os.replace(src, _path(root, cid))
    return {"ok": True}


def trash_list(root):
    d = Path(root) / ".trash"
    items = []
    if d.is_dir():
        for p in d.glob("c*.json"):
            try:
                items.append(_summary(_load(p)))
            except ChatError:
                continue
    items.sort(key=lambda c: -c["updated"])
    return {"chats": items}


def folder_create(root, name):
    name = _clean(name, 60)
    if not name:
        raise ChatError("give the folder a name")
    with _lock:
        _save_folders(root, _folders(root) + [name])
    return {"ok": True, "folder": name}


def folder_rename(root, old, new):
    old, new = _clean(old, 60), _clean(new, 60)
    if not old or not new:
        raise ChatError("give the folder a name")
    with _lock:
        for p in Path(root).glob("c*.json"):
            try:
                c = _load(p)
            except ChatError:
                continue
            if c.get("folder") == old:
                c["folder"] = new
                _write(p, c)
        _save_folders(root, [n for n in _folders(root) if n != old] + [new])
    return {"ok": True, "folder": new}


def folder_delete(root, name):
    """The folder goes; its chats move to the top level (nothing is deleted)."""
    name = _clean(name, 60)
    with _lock:
        for p in Path(root).glob("c*.json"):
            try:
                c = _load(p)
            except ChatError:
                continue
            if c.get("folder") == name:
                c["folder"] = ""
                _write(p, c)
        _save_folders(root, [n for n in _folders(root) if n != name])
    return {"ok": True}


def context(root, ids):
    """Earlier chats, condensed, for a new chat that references them: the newest
    exchanges are kept when a chat is longer than REF_CHARS."""
    blocks = []
    for cid in (ids or [])[:4]:
        try:
            c = _load(_path(root, cid))
        except ChatError:
            continue
        lines = []
        for m in c.get("messages") or []:
            if m.get("hidden"):
                continue
            who = "User" if m["role"] == "user" else "Assistant"
            lines.append(f"{who}: {str(m.get('content') or '').strip()}")
        text = "\n".join(lines)
        if len(text) > REF_CHARS:
            text = "…" + text[-REF_CHARS:]
        blocks.append({"id": c["id"], "title": c.get("title") or "New chat",
                       "text": f'Earlier chat "{c.get("title") or "untitled"}":\n{text}'})
    return {"refs": blocks}


def search(root, q):
    words = [w for w in str(q or "").lower().split() if w]
    if not words:
        return {"chats": []}
    hits = []
    for p in Path(root).glob("c*.json"):
        try:
            c = _load(p)
        except ChatError:
            continue
        hay = (c.get("title") or "").lower() + "\n" + "\n".join(
            str(m.get("content") or "").lower() for m in c.get("messages") or [] if not m.get("hidden"))
        if all(w in hay for w in words):
            hits.append(_summary(c))
    hits.sort(key=lambda c: -c["updated"])
    return {"chats": hits[:80]}


def handle(body, root):
    body = body or {}
    op = body.get("op", "")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        if op == "list":
            return {"ok": True, **list_chats(root)}
        if op == "get":
            return {"ok": True, **get(root, body.get("id"))}
        if op == "save":
            return save(root, body.get("chat"))
        if op == "rename":
            return rename(root, body.get("id"), body.get("title"))
        if op == "move":
            return move(root, body.get("id"), body.get("folder", ""))
        if op == "delete":
            return delete(root, body.get("id"))
        if op == "restore":
            return restore(root, body.get("id"))
        if op == "trash_list":
            return {"ok": True, **trash_list(root)}
        if op == "folder_create":
            return folder_create(root, body.get("name"))
        if op == "folder_rename":
            return folder_rename(root, body.get("old"), body.get("new"))
        if op == "folder_delete":
            return folder_delete(root, body.get("name"))
        if op == "context":
            return {"ok": True, **context(root, body.get("ids"))}
        if op == "search":
            return {"ok": True, **search(root, body.get("q"))}
        return {"ok": False, "msg": f"unknown op {op!r}"}
    except ChatError as e:
        return {"ok": False, "msg": str(e)}
    except OSError as e:
        return {"ok": False, "msg": f"The drive said no: {e.strerror or e}"}
