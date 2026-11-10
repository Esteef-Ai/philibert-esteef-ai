"""Reference a chat from the other app: Philibert <-> Philibert Code (dev/PHILIBERT_CODE.md, phase 3).

The two apps keep their chats apart. When the user asks for it ("Reference a chat..."), one app lists
the OTHER app's chats and turns the one picked into a quoted, clearly labelled block that goes into the
message box - visible, editable, and sent only when the user sends it. Read-only: nothing here writes.

Where each app's chats are, under the Philibert install <root>:
  Philibert        <root>/data/chats/c*.json                (nd_chats: the chat history panel)
  Philibert Code   <root>/data/code/chat_session.json        (the main window's chat tabs)
                   <root>/data/code/chats/c*.json           (its chat page, if used)

Entry point: handle(body, me, root) -> dict.  me = "philibert" | "code".
This file is owned by the Philibert repo (shared/), not ND3; both builds copy it in.
"""
import json
import re
import time
from pathlib import Path

REF_CHARS = 6000            # how much of a chat goes into the message box (the newest part is kept)
NAMES = {"philibert": "Philibert", "code": "Philibert Code"}
_ID = re.compile(r"^(c|t)[0-9A-Za-z_\-]{1,60}$")


def other(me):
    return "code" if me == "philibert" else "philibert"


def _read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _shown(messages):
    out = []
    for m in messages or []:
        if not isinstance(m, dict) or m.get("hidden") or m.get("role") not in ("user", "assistant"):
            continue
        text = str(m.get("content") or "").strip()
        if text:
            out.append((m["role"], text, m.get("t")))
    return out


def _chats(app, root):
    """{id: {"title", "updated", "messages": [(role, text, t)]}} for one app, newest first."""
    root = Path(root)
    found = {}
    folders = [root / "data" / "chats"] if app == "philibert" else [root / "data" / "code" / "chats"]
    for d in folders:
        for p in d.glob("c*.json") if d.is_dir() else []:
            c = _read_json(p)
            if isinstance(c, dict) and _ID.match(str(c.get("id") or "")):
                msgs = _shown(c.get("messages"))
                if msgs:
                    found[c["id"]] = {"title": str(c.get("title") or "Untitled chat"),
                                      "updated": float(c.get("updated") or p.stat().st_mtime), "messages": msgs}
    if app == "code":
        sess = root / "data" / "code" / "chat_session.json"
        s = _read_json(sess)
        tabs = s.get("tabs") if isinstance(s, dict) else None
        if isinstance(tabs, list):
            when = sess.stat().st_mtime
            for i, t in enumerate(tabs):
                if not isinstance(t, dict):
                    continue
                msgs = _shown(t.get("history"))
                if msgs:
                    tid = "t" + re.sub(r"[^0-9A-Za-z_\-]", "", str(t.get("id") or i))[:59]
                    found[tid] = {"title": str(t.get("name") or f"Chat {i + 1}"), "updated": when, "messages": msgs}
    return dict(sorted(found.items(), key=lambda kv: -kv[1]["updated"]))


def installed(app, root):
    """Is that app on this install at all (so the button is worth showing)?"""
    root = Path(root)
    if app == "code":
        return (root / "code" / "app" / "NeuralDock_launcher.py").is_file() or (root / "data" / "code").is_dir()
    return (root / "app" / "NeuralDock_launcher.py").is_file()


def listing(me, root):
    app = other(me)
    out = []
    for cid, c in _chats(app, root).items():
        last = c["messages"][-1][1]
        out.append({"id": cid, "title": c["title"][:80], "updated": c["updated"], "count": len(c["messages"]),
                    "preview": re.sub(r"\s+", " ", last)[:90]})
    return {"ok": True, "from": NAMES[app], "installed": installed(app, root), "chats": out[:200]}


def block(me, root, cid):
    """The quoted, labelled block for one chat of the other app."""
    app = other(me)
    if not _ID.match(str(cid or "")):
        return {"ok": False, "msg": "no such chat"}
    c = _chats(app, root).get(cid)
    if not c:
        return {"ok": False, "msg": "That chat is not there any more."}
    lines = []
    for role, text, _t in c["messages"]:
        who = "Me" if role == "user" else NAMES[app]
        lines.append(f"{who}: {text}")
    body = "\n".join(lines)
    trimmed = len(body) > REF_CHARS
    if trimmed:
        body = body[-REF_CHARS:]
        body = body[body.find("\n") + 1:] if "\n" in body[:400] else body      # start on a whole line
    day = time.strftime("%Y-%m-%d", time.localtime(c["updated"]))
    head = f'[Referenced chat from {NAMES[app]}: "{c["title"][:80]}" ({day}){" - only its newest part" if trimmed else ""}]'
    quoted = "\n".join("> " + ln if ln else ">" for ln in body.splitlines())
    return {"ok": True, "title": c["title"][:80], "from": NAMES[app], "trimmed": trimmed,
            "text": f"{head}\n{quoted}\n[End of referenced chat]\n\n"}


def handle(body, me, root):
    body = body or {}
    if me not in NAMES:
        return {"ok": False, "msg": "unknown app"}
    op = str(body.get("op") or "list")
    try:
        if op == "list":
            return listing(me, root)
        if op == "get":
            return block(me, root, body.get("id"))
        return {"ok": False, "msg": f"unknown op {op!r}"}
    except OSError as e:
        return {"ok": False, "msg": f"Could not read the chats: {e.strerror or e}"}
