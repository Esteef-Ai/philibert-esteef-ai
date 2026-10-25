"""Group Board: a message board for a band - or any group - shared between their Philibert
drives. The posts live on the board server (philibert.json "board_server", a Netlify
function - see the Philibert repo's board-server/); this drive keeps only its membership:
data/board/membership.json (group, my name, my member key, when I last looked).

Threads with replies, polls, attachments (up to 5 MB), pinning (the group's admin). New
posts reach phones through ntfy (the server sends them to the group's topic) and the
Philibert desktop (it asks for news once a minute while the Internet is on).

    handle(body, data_dir, online) -> dict
    file(data_dir, fid, online) -> (bytes, type, name) | None
"""
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_SERVER = "https://philibert-board.netlify.app/api/"


def _server():
    try:
        import nd_philibert
        url = json.loads(nd_philibert.REPO_FILE.read_text(encoding="utf-8")).get("board_server") or DEFAULT_SERVER
    except Exception:
        url = DEFAULT_SERVER
    return url if url.endswith("/") else url + "/"


def _mf(data_dir):
    return Path(data_dir) / "board" / "membership.json"


def membership(data_dir):
    try:
        return json.loads(_mf(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(data_dir, m):
    f = _mf(data_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(m, indent=1), encoding="utf-8")


class BoardError(Exception):
    pass


def _call(method, path, body=None, token=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    headers = {"Content-Type": ctype, "User-Agent": "Philibert-Board"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(_server() + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            b = r.read()
            if r.headers.get_content_type() == "application/json":
                return json.loads(b)
            return {"_bytes": b, "_type": r.headers.get("Content-Type", "application/octet-stream"),
                    "_disp": r.headers.get("Content-Disposition", "")}
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", "")
        except Exception:
            msg = ""
        if e.code == 429:
            msg = "The board is busy - try again in a minute."
        raise BoardError(msg or f"The board server said {e.code}.")
    except (urllib.error.URLError, OSError) as e:
        raise BoardError(f"Could not reach the board server: {getattr(e, 'reason', e)}")


def _ntfy(topic):
    return {"topic": topic, "web": f"https://ntfy.sh/{topic}", "app": f"ntfy://ntfy.sh/{topic}"} if topic else None


def status(data_dir, online):
    m = membership(data_dir)
    if not m:
        return {"ok": True, "joined": False, "online": bool(online)}
    return {"ok": True, "joined": True, "online": bool(online), "group": m["group"], "member": m["member"],
            "phone": _ntfy(m["group"].get("ntfy")), "seen": m.get("seen", 0)}


def _start(data_dir, d):
    m = {"group": d["group"], "member": d["member"], "token": d["token"], "seen": int(time.time() * 1000),
         "server": _server(), "joined": time.time()}
    _save(data_dir, m)
    return m


def handle(body, data_dir, online):
    body = body or {}
    op = body.get("op", "")
    if op == "status":
        return status(data_dir, online)
    if op == "leave":                         # this drive only: the group goes on without it
        try:
            _mf(data_dir).unlink()
        except OSError:
            pass
        return {"ok": True}
    if not online:
        return {"ok": False, "offline": True, "msg": "The board is online - turn the Internet on to use it."}
    try:
        if op in ("create", "join"):
            if membership(data_dir):
                return {"ok": False, "msg": "This drive is already in a group - leave it first."}
            d = (_call("POST", "groups", {"group_name": body.get("group_name"), "name": body.get("name")}) if op == "create"
                 else _call("POST", "join", {"invite": body.get("invite"), "name": body.get("name")}))
            _start(data_dir, d)
            return status(data_dir, online)
        m = membership(data_dir)
        if not m:
            return {"ok": False, "msg": "Join or start a group first."}
        tok = m["token"]
        tid = urllib.parse.quote(str(body.get("id") or ""), safe="")
        if op == "me":
            return {"ok": True, **_call("GET", "me", token=tok)}
        if op == "threads":
            return {"ok": True, **_call("GET", "threads", token=tok)}
        if op == "thread":
            return {"ok": True, "thread": _call("GET", f"threads/{tid}", token=tok)}
        if op == "new_thread":
            return {"ok": True, **_call("POST", "threads", {k: body.get(k) for k in ("title", "body", "poll", "files")}, token=tok)}
        if op == "reply":
            return {"ok": True, **_call("POST", f"threads/{tid}/posts", {k: body.get(k) for k in ("body", "files")}, token=tok)}
        if op == "vote":
            return {"ok": True, **_call("POST", f"threads/{tid}/vote", {"options": body.get("options") or []}, token=tok)}
        if op == "pin":
            return {"ok": True, **_call("POST", f"threads/{tid}/pin", {}, token=tok)}
        if op == "delete_post":
            pid = urllib.parse.quote(str(body.get("pid") or ""), safe="")
            return {"ok": True, **_call("DELETE", f"threads/{tid}/posts/{pid}", token=tok)}
        if op == "upload":
            data = base64.b64decode(body.get("data") or "")
            q = urllib.parse.urlencode({"name": body.get("name") or "file", "type": body.get("type") or "application/octet-stream"})
            return {"ok": True, "file": _call("POST", f"files?{q}", raw=data, token=tok,
                                               ctype=body.get("type") or "application/octet-stream")}
        if op == "changes":                   # news since I last looked (not my own posts)
            d = _call("GET", f"changes?since={int(m.get('seen', 0))}", token=tok)
            return {"ok": True, "items": d.get("items", []), "now": d.get("now")}
        if op == "seen":
            m["seen"] = int(body.get("now") or time.time() * 1000)
            _save(data_dir, m)
            return {"ok": True}
        # -- the band scheduler (nd_sched does the arithmetic, here on the drive) --
        if op == "avail_get":
            return {"ok": True, **_call("GET", "avail", token=tok)}
        if op == "avail_set":
            return {"ok": True, **_call("POST", "avail", {"weekly": body.get("weekly") or [],
                                                         "blackouts": body.get("blackouts") or [],
                                                         "email": body.get("email") or ""}, token=tok)}
        # -- Google Calendar (the board server holds the band's Google key) --
        if op == "google_status":
            return {"ok": True, **_call("GET", "google/status", token=tok)}
        if op == "google_start":
            return {"ok": True, **_call("POST", "google/start", {"tz": body.get("tz") or ""}, token=tok)}
        if op == "google_disconnect":
            return {"ok": True, **_call("POST", "google/disconnect", {}, token=tok)}
        if op == "events":
            return {"ok": True, **_call("GET", "events", token=tok)}
        if op == "event_save":
            fields = {k: body.get(k) for k in ("kind", "title", "date", "start", "end", "address", "notes", "cancelled")}
            eid = urllib.parse.quote(str(body.get("id") or ""), safe="")
            return {"ok": True, "event": _call("POST", "events/" + eid if eid else "events", fields, token=tok)}
        if op in ("suggest", "check"):
            import nd_sched
            av = _call("GET", "avail", token=tok)["members"]
            ev = _call("GET", "events", token=tok)["events"]
            # everyone's Google Calendar busy times (only when; never what)
            gb = _call("POST", "google/busy", {"from": body.get("from"), "to": body.get("to")}, token=tok)
            busy = {mid: [tuple(x) for x in xs] for mid, xs in (gb.get("busy") or {}).items()}
            unseen = gb.get("unseen") or []
            if op == "check":
                return {"ok": True, "days": nd_sched.check_dates(av, ev, body["from"], body["to"], body.get("start") or None,
                                                                 body.get("end") or None, busy=busy), "unseen": unseen,
                        "google": bool(gb.get("connected"))}
            kw = {k: body[k] for k in ("duration", "earliest", "latest", "required", "min_people", "limit", "kind") if body.get(k)}
            return {"ok": True, "slots": nd_sched.suggest(av, ev, body["from"], body["to"], busy=busy, **kw),
                    "unseen": unseen, "google": bool(gb.get("connected")),
                    "members": [{"id": x["id"], "name": x["name"], "filled": bool(x["weekly"])} for x in av]}
        if op == "ask_band":                  # the top suggestions as a poll on the board
            opts = [str(o)[:100] for o in (body.get("options") or [])][:10]
            return {"ok": True, **_call("POST", "threads", {"title": str(body.get("title") or "When can we practice?")[:120],
                                                            "body": str(body.get("body") or "")[:2000],
                                                            "poll": {"question": "Which works for you?", "options": opts, "multi": True}},
                                         token=tok)}
    except BoardError as e:
        return {"ok": False, "msg": str(e)}
    return {"ok": False, "msg": f"unknown op {op!r}"}


def file(data_dir, fid, online):
    """An attachment, fetched from the board for viewing or saving."""
    m = membership(data_dir)
    if not m or not online:
        return None
    try:
        d = _call("GET", "files/" + urllib.parse.quote(str(fid), safe=""), token=m["token"])
    except BoardError:
        return None
    if "_bytes" not in d:
        return None
    name = urllib.parse.unquote(d["_disp"].split("filename=")[-1].strip('"')) if "filename=" in d["_disp"] else "file"
    return d["_bytes"], d["_type"], name
