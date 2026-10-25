"""Feedback Shooter: a person sends the maker a message about Philibert - an idea, something
that's wrong, a change they want. Each message becomes an issue on Philibert's (public)
GitHub repository, so the maker reads them all in one place and can answer there.

Messages are written to data/feedback/ first (the outbox): with the Internet switch off
they wait there and go out when it is on. Sending needs a GitHub sign-in - the same
device sign-in as updates (nd_philibert), asking only for public repositories, and
kept in memory only. Nothing is sent that the person has not seen in the preview.

    handle(body, data_dir, online) -> dict      ops: status, system, list, save, send, delete, refresh
"""
import json
import platform
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
KINDS = {"idea": "Idea", "bug": "Something's wrong", "change": "Change request", "praise": "Praise"}
PARTS = ["Chat", "Desktop", "App Store", "Notes", "Files", "Models", "Image Generation", "Retro Vault",
         "Band Manager", "Setup / Update", "Something else"]


def _dir(data_dir):
    d = Path(data_dir) / "feedback"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _items(data_dir):
    out = []
    for f in _dir(data_dir).glob("*.json"):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return sorted(out, key=lambda x: -x.get("at", 0))


def _write(data_dir, item):
    (_dir(data_dir) / f"{item['id']}.json").write_text(json.dumps(item, indent=1), encoding="utf-8")


def _gh():
    import nd_philibert
    return nd_philibert, nd_philibert._GH


def system(data_dir):
    """The computer details a message may carry - shown to the person before sending."""
    import nd_philibert
    try:
        info = json.loads((Path(data_dir) / "install.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    try:
        import psutil
        ram = f"{round(psutil.virtual_memory().total / 2**30)} GB"
    except Exception:
        ram = "?"
    gpu = nd_philibert.gpu_gb()
    return {"Philibert": nd_philibert.version(), "Edition": info.get("edition", "?"),
            "System": f"{platform.system()} {platform.release()}", "Chip": platform.machine(),
            "Memory": ram, "Graphics memory": f"{gpu} GB" if gpu else "none found"}


def _title(item):
    return f"[{KINDS.get(item['kind'], 'Feedback')}] {item['title']}"[:120]


def _body(item):
    lines = [f"**Kind:** {KINDS.get(item['kind'], item['kind'])}  \n**Part of Philibert:** {item['part']}", "",
             item["message"].strip(), ""]
    if item.get("system"):
        lines += ["<details><summary>Computer details</summary>", ""]
        lines += [f"- {k}: {v}" for k, v in item["system"].items()]
        lines += ["", "</details>", ""]
    lines.append("_Sent with Philibert's Feedback Shooter._")
    return "\n".join(lines)


def preview(item):
    return {"title": _title(item), "body": _body(item)}


def _post_issue(repo, token, item):
    req = urllib.request.Request(f"{API}/repos/{repo}/issues", method="POST",
                                 data=json.dumps({"title": _title(item), "body": _body(item)}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "Philibert-Feedback", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def send(data_dir, online, only=None):
    """Send what waits in the outbox. -> {sent, need_signin, offline, error}"""
    nd_philibert, gh = _gh()
    repo = nd_philibert._repo()[0]
    waiting = [i for i in _items(data_dir) if i["status"] in ("queued", "failed") and (only is None or i["id"] == only)]
    if not waiting:
        return {"sent": 0}
    if not online:
        return {"sent": 0, "offline": True}
    if not repo:
        return {"sent": 0, "error": "This copy has no repository to send to (philibert.json)."}
    if not gh.get("token"):
        return {"sent": 0, "need_signin": True}
    sent = 0
    for item in reversed(waiting):                       # oldest first
        try:
            d = _post_issue(repo, gh["token"], item)
            item.update(status="sent", sent_at=time.time(), number=d.get("number"), url=d.get("html_url"),
                        by=gh.get("user", ""), error="")
            sent += 1
        except urllib.error.HTTPError as e:
            item.update(status="failed", error=f"GitHub said {e.code}: {e.reason}")
            if e.code in (401, 403):
                gh["token"] = ""                          # a stale sign-in: ask again
                _write(data_dir, item)
                return {"sent": sent, "need_signin": True, "error": item["error"]}
        except Exception as e:
            item.update(status="failed", error=f"Could not reach GitHub: {e}")
        _write(data_dir, item)
    return {"sent": sent}


def refresh(data_dir, online):
    """Sent messages: is the issue still open, and has anyone answered?"""
    if not online:
        return {"ok": False, "offline": True}
    nd_philibert, _ = _gh()
    repo = nd_philibert._repo()[0]
    for item in _items(data_dir):
        if item["status"] != "sent" or not item.get("number"):
            continue
        try:
            req = urllib.request.Request(f"{API}/repos/{repo}/issues/{item['number']}",
                                         headers={"Accept": "application/vnd.github+json", "User-Agent": "Philibert-Feedback"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read())
            item.update(state=d.get("state"), replies=d.get("comments", 0), checked=time.time())
            _write(data_dir, item)
        except Exception:
            pass
    return {"ok": True}


def handle(body, data_dir, online):
    body = body or {}
    op = body.get("op", "")
    try:
        if op == "status":
            nd_philibert, gh = _gh()
            return {"ok": True, "online": bool(online), "signed_in": bool(gh.get("token")), "user": gh.get("user", ""),
                    "repo": nd_philibert._repo()[0], "kinds": KINDS, "parts": PARTS,
                    "waiting": sum(1 for i in _items(data_dir) if i["status"] in ("queued", "failed"))}
        if op == "system":
            return {"ok": True, "system": system(data_dir)}
        if op == "list":
            return {"ok": True, "items": _items(data_dir)}
        if op == "preview":
            item = _new(body, data_dir)
            return {"ok": True, **preview(item)}
        if op == "save":
            item = _new(body, data_dir)
            _write(data_dir, item)
            r = send(data_dir, online, item["id"]) if body.get("send", True) else {}
            return {"ok": True, "item": json.loads((_dir(data_dir) / f"{item['id']}.json").read_text(encoding="utf-8")), **r}
        if op == "send":
            return {"ok": True, **send(data_dir, online, body.get("id"))}
        if op == "delete":
            f = _dir(data_dir) / f"{str(body.get('id', '')).replace('/', '').replace('..', '')}.json"
            if f.is_file():
                item = json.loads(f.read_text(encoding="utf-8"))
                if item["status"] == "sent":
                    return {"ok": False, "msg": "That one is already on GitHub - it stays in your list."}
                f.unlink()
            return {"ok": True}
        if op == "refresh":
            return refresh(data_dir, online)
    except ValueError as e:
        return {"ok": False, "msg": str(e)}
    return {"ok": False, "msg": f"unknown op {op!r}"}


def _new(body, data_dir):
    kind = body.get("kind") if body.get("kind") in KINDS else "idea"
    part = body.get("part") if body.get("part") in PARTS else "Something else"
    title = " ".join(str(body.get("title") or "").split())[:100]
    message = str(body.get("message") or "").strip()[:8000]
    if not title or not message:
        raise ValueError("Give it a short title and say what you'd like.")
    return {"id": time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}", "at": time.time(),
            "kind": kind, "part": part, "title": title, "message": message,
            "system": system(data_dir) if body.get("include_system", True) else None,
            "status": "queued", "error": ""}
