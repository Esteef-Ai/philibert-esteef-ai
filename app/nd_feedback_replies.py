"""Feedback Shooter replies (Philibert only; dev/patching.py FEEDBACK_REPLIES hooks it into nd_feedback.handle).

Each message the person sent is an issue on Philibert's public GitHub repository. This reads the answers
on it back into the app, so the person sees them in Feedback Shooter, gets a pop-up on the desktop, and can
answer in turn without a GitHub account.

  * Only the maker's comments count as replies: GitHub marks each comment's author OWNER, MEMBER or
    COLLABORATOR of the repository. Anyone else's comment on the public issue is never shown.
  * The person's own answers go out the way their message did: under their GitHub name when they are
    signed in, otherwise through the feedback relay's /reply, which needs the key the relay handed back
    for that issue (so nobody can post on someone else's issue through it).
  * GitHub is asked at most every 20 minutes (60 unsigned requests an hour per address), and only about
    open issues; an issue that closes is read once more and then left alone.

    handle(op, body, data_dir, online) -> dict      ops: check_replies, seen, answer
"""
import calendar
import json
import time
import urllib.error
import urllib.request

import nd_feedback as fb

MAKERS = {"OWNER", "MEMBER", "COLLABORATOR"}
EVERY = 20 * 60
MAX_ANSWER = 4000
SENDER_MARK = "**The sender answered** (from Philibert, through the feedback relay):"   # relay/netlify/functions/reply.mts


def _state_file(data_dir):
    return fb._dir(data_dir) / "replies.state"      # not *.json: nd_feedback reads every .json there as a message


def _state(data_dir):
    try:
        return json.loads(_state_file(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(data_dir, s):
    _state_file(data_dir).write_text(json.dumps(s), encoding="utf-8")


def _get(url, token=""):
    h = {"Accept": "application/vnd.github+json", "User-Agent": "Philibert-Feedback"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=15) as r:
        return json.loads(r.read())


def _fetch(data_dir):
    """Ask GitHub about each sent message whose issue is still open. -> problems (strings)."""
    nd_philibert, gh = fb._gh()
    repo = nd_philibert._repo()[0]
    if not repo:
        return ["no repository in philibert.json"]
    token = gh.get("token", "")
    problems = []
    for item in fb._items(data_dir):
        if item.get("status") != "sent" or not item.get("number") or item.get("final"):
            continue
        base = f"{fb.API}/repos/{repo}/issues/{item['number']}"
        try:
            issue = _get(base, token)
            item.update(state=issue.get("state"), replies=issue.get("comments", 0), checked=time.time())
            if issue.get("comments", 0) != item.get("comment_count"):
                comments = _get(base + "/comments?per_page=100", token)
                mine = {c["id"] for c in item.get("thread", []) if c.get("mine")}
                thread = [c for c in item.get("thread", []) if c.get("mine")]
                for c in comments:
                    if c.get("id") in mine:
                        continue
                    body = c.get("body") or ""
                    if body.startswith(SENDER_MARK):    # the person's answer through the relay (posted as the maker)
                        thread.append({"id": c["id"], "by": "", "body": body[len(SENDER_MARK):].strip(),
                                       "at": _when(c.get("created_at")), "mine": True})
                        continue
                    if c.get("author_association") in MAKERS:
                        thread.append({"id": c["id"], "by": (c.get("user") or {}).get("login", ""), "body": c.get("body") or "",
                                       "at": _when(c.get("created_at")), "maker": True})
                item["thread"] = sorted(thread, key=lambda c: c["at"])
                item["comment_count"] = issue.get("comments", 0)
            if issue.get("state") == "closed":
                item["final"] = True             # read once more after closing, then left alone
        except Exception as e:
            problems.append(f"#{item['number']}: {e}")
        fb._write(data_dir, item)
    return problems


def _when(iso):
    try:
        return calendar.timegm(time.strptime(str(iso), "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return time.time()


def check(data_dir, online, force=False):
    """-> {unread, new: [{id, title, by}]} - `new` lists each maker reply once, for the desktop's pop-up."""
    s = _state(data_dir)
    problems = []
    if online and (force or time.time() - s.get("fetched", 0) >= EVERY):
        problems = _fetch(data_dir)
        s["fetched"] = time.time()
    told = set(s.get("told", []))
    unread, new = 0, []
    for item in fb._items(data_dir):
        seen = set(item.get("seen", []))
        for c in item.get("thread", []):
            if not c.get("maker"):
                continue
            if c["id"] not in seen:
                unread += 1
            if c["id"] not in told and c["id"] not in seen:
                new.append({"id": item["id"], "title": item.get("title", ""), "by": c.get("by", "")})
                told.add(c["id"])
    s["told"] = sorted(told)[-500:]
    _save_state(data_dir, s)
    return {"ok": True, "unread": unread, "new": new, "problems": problems}


def seen(data_dir, item_id):
    """The person has looked at this message's replies."""
    for item in fb._items(data_dir):
        if item["id"] == item_id:
            item["seen"] = [c["id"] for c in item.get("thread", []) if c.get("maker")]
            fb._write(data_dir, item)
            return {"ok": True}
    return {"ok": False, "msg": "No such message."}


def _reply_url():
    url = fb._relay_url()
    return url[: -len("/send")] + "/reply" if url.endswith("/send") else ""


def answer(data_dir, online, item_id, text):
    """The person answers the maker on one of their sent messages."""
    text = str(text or "").replace("\r\n", "\n").strip()[:MAX_ANSWER]
    if not text:
        return {"ok": False, "msg": "Write your answer first."}
    item = next((i for i in fb._items(data_dir) if i["id"] == item_id), None)
    if not item or item.get("status") != "sent" or not item.get("number"):
        return {"ok": False, "msg": "That message has not been sent yet."}
    if not online:
        return {"ok": False, "offline": True, "msg": "Turn the Internet on to send your answer."}
    nd_philibert, gh = fb._gh()
    repo = nd_philibert._repo()[0]
    try:
        if gh.get("token"):
            req = urllib.request.Request(f"{fb.API}/repos/{repo}/issues/{item['number']}/comments", method="POST",
                                         data=json.dumps({"body": text}).encode(),
                                         headers={"Authorization": f"Bearer {gh['token']}", "Accept": "application/vnd.github+json",
                                                  "User-Agent": "Philibert-Feedback", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
            cid = d.get("id")
        else:
            url = _reply_url()
            if not url or not item.get("reply_key"):
                return {"ok": False, "need_signin": True,
                        "msg": "This message went out before answers were possible. Sign in to GitHub to answer it, or send a new message."}
            req = urllib.request.Request(url, method="POST", headers={"Content-Type": "application/json", "User-Agent": "Philibert-Feedback"},
                                         data=json.dumps({"number": item["number"], "key": item["reply_key"], "message": text}).encode())
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
            cid = d.get("id")
    except urllib.error.HTTPError as e:
        return {"ok": False, "msg": fb._relay_error(e) if not gh.get("token") else f"GitHub said {e.code}: {e.reason}"}
    except Exception as e:
        return {"ok": False, "msg": f"Could not send your answer: {e}"}
    item.setdefault("thread", []).append({"id": cid or f"local-{int(time.time())}", "by": gh.get("user", ""), "body": text,
                                          "at": time.time(), "mine": True})
    item["comment_count"] = item.get("comment_count", 0) + 1 if cid else item.get("comment_count")
    fb._write(data_dir, item)
    return {"ok": True}


def handle(op, body, data_dir, online):
    if op == "check_replies":
        return check(data_dir, online, bool(body.get("force")))
    if op == "seen":
        return seen(data_dir, str(body.get("id") or ""))
    if op == "answer":
        return answer(data_dir, online, str(body.get("id") or ""), body.get("message"))
    return {"ok": False, "msg": f"unknown op {op!r}"}
