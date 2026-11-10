"""Counted edits and repo-owned files, shared by Philibert's build (sync_app.py) and Philibert Code's
(sync_code.py). ND3 is the developer's own copy and is never edited for packaging: what only the
Philibert family needs is either a file owned by this repo (shared/) or an edit applied to the COPY.

A rule is (file, regex, replacement, expected hits). Rules are applied to LF text; a file keeps its
own line endings. A wrong hit count is reported, never half-applied, so a change in ND3 that moves an
anchor stops the build loudly.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
L = re.escape

# Repo-owned files copied into BOTH apps: {source in this repo: path in the app}
SHARED = {
    "shared/nd_chatref.py": "nd_chatref.py",
    "shared/chatref.js": "live/static/chatref.js",
    "shared/nd_codelaunch.py": "nd_codelaunch.py",
    "shared/philibert-code.svg": "live/static/desktop/philibert-code.svg",
}

# Phase 3 (dev/PHILIBERT_CODE.md): reference a chat from the other app. Both apps.
_CHATREF_ROUTE = (
    '        if path == "/api/chatref":\n'
    "            # Philibert <-> Philibert Code: the OTHER app's chats, read-only (shared/nd_chatref.py)\n"
    '            _origin = self.headers.get("Origin")\n'
    '            if _origin and urllib.parse.urlparse(_origin).netloc != self.headers.get("Host"):\n'
    '                self.send_json({"ok": False, "msg": "refused: another site"}, 403)\n'
    "                return\n"
    "            import nd_chatref\n"
    '            self.send_json(nd_chatref.handle(body, "philibert" if PORTABLE else "code", _drive_root()))\n'
    "            return\n")
_SCRIPT = ('<script src="/live/chatref.js"></script>\n'
           "<script>ChatRef.attach(document.getElementById('{btn}'), document.getElementById('{ta}'));</script>\n"
           "</body>")
CHATREF_BOTH = [
    ("NeuralDock_launcher.py", L('        if path in ("/api/notes", "/api/chats",'),
     _CHATREF_ROUTE + '        if path in ("/api/notes", "/api/chats",', 1),
    # Philibert's chat (and the chat page Philibert Code also ships): a button beside the message box
    ("elena_ui.html", L('    <textarea id="ta" rows="1"'),
     '    <button id="refbtn" class="icon" type="button" hidden title="Reference a chat from the other app"\n'
     '            aria-label="Reference a chat">&#8644;</button>\n'
     '    <textarea id="ta" rows="1"', 1),
    ("elena_ui.html", L("</body>"), _SCRIPT.format(btn="refbtn", ta="ta"), 1),
]
# Philibert Code's main window: a button on the chat toolbar, beside its own tab REF picker
CHATREF_CODE = [
    ("NeuralDock_ui.html", L('    <div style="flex:1"></div>\n    <span style="font-size:9px;color:var(--muted)">REF:</span>'),
     '    <button class="chat-act-btn" id="chatref-btn" hidden>&#8644; PHILIBERT CHAT</button>\n'
     '    <div style="flex:1"></div>\n    <span style="font-size:9px;color:var(--muted)">REF:</span>', 1),
    ("NeuralDock_ui.html", L("</body>"), _SCRIPT.format(btn="chatref-btn", ta="ui"), 1),
]


# Phase 5: Philibert's retro desktop shows a Philibert Code icon when Philibert Code is installed in this
# Philibert; opening it starts it, or opens a window on it if it is running (shared/nd_codelaunch.py).
# Philibert's app only.
CODEICON_APP = [
    ("NeuralDock_launcher.py", L('            if path == "/api/desktop":\n                if body.get("op") == "you":'),
     '            if path == "/api/desktop":\n'
     '                if body.get("op") in ("code_status", "open_code"):   # Philibert Code (shared/nd_codelaunch.py)\n'
     "                    import nd_codelaunch\n"
     '                    if body["op"] == "code_status":\n'
     '                        self.send_json({"ok": True, **nd_codelaunch.status(_drive_root())})\n'
     "                        return\n"
     "                    r = nd_codelaunch.open_code(_drive_root())\n"
     '                    if r.get("url"):          # already running: a window on it, in this drive\'s browser\n'
     "                        try:\n"
     "                            if portable_browser():\n"
     '                                subprocess.Popen(_portable_browser_args(r["url"])[2])\n'
     "                            else:\n"
     '                                webbrowser.open(r["url"])\n'
     "                        except Exception as e:\n"
     '                            r = {"ok": False, "msg": f"Could not open its window: {e}"}\n'
     "                    self.send_json(r)\n"
     "                    return\n"
     '                if body.get("op") == "you":', 1),
    ("live/static/desktop/desktop.js",
     L('    var sh = THEMES[st.settings.theme] ? THEMES[st.settings.theme].shell : "taskbar";\n    if (sh === "phone" || sh === "c64")'),
     '    if (st.code) list.push({ id: "code", name: "Philibert Code", icon: "app", img: "/live/desktop/philibert-code.svg",\n'
     "                             action: openCode });\n"
     '    var sh = THEMES[st.settings.theme] ? THEMES[st.settings.theme].shell : "taskbar";\n    if (sh === "phone" || sh === "c64")', 1),
    ("live/static/desktop/desktop.js", L("  window.PhilDesktop = { open: open, close: close, msgbox: msgbox, startSaver: startSaver };"),
     "  /* Philibert Code, an add-on (open_code: shared/nd_codelaunch.py): its icon shows only when it is installed */\n"
     "  function openCode() {\n"
     '    notify("Philibert Code", "Opening Philibert Code - its own window appears in a moment.");\n'
     '    api("/api/desktop", { op: "open_code" }).then(function (r) {\n'
     '      if (!r || !r.ok) msgbox("Philibert Code", (r && r.msg) || "Philibert Code did not open.", "error");\n'
     '    }).catch(function () { msgbox("Philibert Code", "Philibert Code did not open.", "error"); });\n'
     "  }\n"
     '  api("/api/desktop", { op: "code_status" }).then(function (r) {\n'
     "    if (r && r.installed && !st.code) { st.code = true; renderIcons(); }\n"
     "  }).catch(function () {});\n"
     "  window.PhilDesktop = { open: open, close: close, msgbox: msgbox, startSaver: startSaver };", 1),
]
# sync_app.addons(): each rule set and the word that marks a file it has already edited
APP_ADDONS = [(CHATREF_BOTH, "chatref"), (CODEICON_APP, "nd_codelaunch|openCode")]


def apply(texts, rules):
    """Apply rules to {rel: LF text} in place. -> problems (a missing file or a wrong count is one)."""
    problems = []
    for rel, pat, new, want in rules:
        if rel not in texts:
            problems.append(f"edit: {rel} is not in the build")
            continue
        text, n = re.subn(pat, lambda _m: new, texts[rel])
        if n != want:
            problems.append(f"edit: {rel}: expected {want} hit(s) of {pat[:70]!r}, found {n} - "
                            f"look at what changed in ND3 and update the rule")
            continue
        texts[rel] = text
    return problems


def shared_files():
    """{app path: text} of the repo-owned files."""
    return {dst: (REPO / src).read_text(encoding="utf-8") for src, dst in SHARED.items()}
