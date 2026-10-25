"""Signing in to GitHub for a private Philibert repository: from Philibert Setup,
and from the Update button on a drive (nd_philibert.py).

GitHub's device flow: Setup shows a short code, opens github.com/login/device in
the browser, the person types the code and approves, and Setup gets a token -
no password ever passes through Setup. It needs the client ID of an OAuth app
with "Enable Device Flow" ticked (philibert.json "github_client_id"; a client
ID is not a secret). As a fallback, a person can paste a token they made.

The token lives in memory only (this install, this session); it is never written to disk.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
UA = {"User-Agent": "Philibert-Setup", "Accept": "application/json"}


def _post(url, data, timeout=20):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(url, token=None, timeout=20):
    h = dict(UA, Accept="application/vnd.github+json")
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {}


def repo_needs_signin(repo):
    """True when the repository is not public (GitHub answers 404 to strangers)."""
    try:
        code, _ = _get(f"{API}/repos/{repo}")
    except OSError:
        return None                       # offline: Setup says so elsewhere
    return code != 200


def start(client_id, scope="repo"):
    """-> {user_code, verification_uri, device_code, interval, expires_in}
    scope: "repo" to read a private repository, "public_repo" when it is public (updates
    need nothing then; Feedback Shooter needs it to open an issue)."""
    d = _post("https://github.com/login/device/code", {"client_id": client_id, "scope": scope})
    if "user_code" not in d:
        raise RuntimeError(d.get("error_description") or d.get("error") or "GitHub did not give a code")
    return d


def poll(client_id, device_code):
    """-> {"state": "pending" | "slow_down" | "ok" | "denied" | "expired" | "error", "token"?}"""
    d = _post("https://github.com/login/oauth/access_token",
              {"client_id": client_id, "device_code": device_code,
               "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    if d.get("access_token"):
        return {"state": "ok", "token": d["access_token"]}
    err = d.get("error", "")
    return {"state": {"authorization_pending": "pending", "slow_down": "slow_down",
                      "expired_token": "expired", "access_denied": "denied"}.get(err, "error"),
            "message": d.get("error_description", "")}


def check(repo, token):
    """-> {"ok": bool, "user": login, "message": str} - can this token read the repository?"""
    try:
        code, me = _get(f"{API}/user", token)
        if code != 200:
            return {"ok": False, "message": "GitHub did not accept that sign-in."}
        code, _ = _get(f"{API}/repos/{repo}", token)
    except OSError:
        return {"ok": False, "message": "Could not reach GitHub. Check the Internet connection."}
    if code != 200:
        return {"ok": False, "user": me.get("login", ""),
                "message": f"Signed in as {me.get('login', '?')}, but that account has not been invited to "
                           f"Philibert yet. Ask for an invitation, accept it on GitHub, then try again."}
    return {"ok": True, "user": me.get("login", ""), "message": ""}
