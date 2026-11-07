"""Philibert's icon: which picture its desktop shortcut wears.

The pictures live in <drive>/Philibert/setup/assets/icons (icons.json lists them in
order; "classic" is the original philibert.ico). The choice is kept in
data/install.json as "icon". Setup picks one; Control Panel > Icon changes it.

Only the Windows desktop shortcut (Desktop\\Philibert.lnk) shows it. A shortcut that
starts a Philibert on a different drive or folder is left alone.

With the shortcut comes a philibert:// link (HKCU, this user only), so a web page can
start Philibert - the Boof Launcher's Philibert tile uses it. It goes and comes with the
shortcut: whoever made one asked for Philibert on this computer.
"""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
_NO_WINDOW = 0x08000000 if IS_WIN else 0
DEFAULT = "classic"


def icons_dir(root):
    return Path(root) / "setup" / "assets" / "icons"


def icons(root, folder=None):
    """[{id, name, ico, png}] in the order they're offered. `folder` reads another copy
    (Setup reads the one inside itself before the drive has any)."""
    d = Path(folder) if folder else icons_dir(root)
    try:
        return json.loads((d / "icons.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [{"id": DEFAULT, "name": "Philibert (classic)", "ico": "../philibert.ico", "png": "classic.png"}]


def with_pictures(items, folder):
    """The same list with each preview as a data: URL, for a page that can't reach the files."""
    out = []
    for it in items:
        p = Path(folder) / it.get("png", "")
        img = ""
        try:
            img = "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode("ascii")
        except OSError:
            pass
        out.append({"id": it["id"], "name": it["name"], "img": img})
    return out


def ico_path(root, icon_id):
    for it in icons(root):
        if it["id"] == icon_id:
            p = (icons_dir(root) / it["ico"]).resolve()
            if p.exists():
                return p
    return (Path(root) / "setup" / "assets" / "philibert.ico").resolve()


def _info_file(root):
    return Path(root) / "data" / "install.json"


def current(root):
    try:
        got = json.loads(_info_file(root).read_text(encoding="utf-8")).get("icon") or DEFAULT
    except (OSError, ValueError):
        got = DEFAULT
    return got if any(it["id"] == got for it in icons(root)) else DEFAULT


def remember(root, icon_id):
    f = _info_file(root)
    try:
        info = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    info["icon"] = icon_id
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.part")
    tmp.write_text(json.dumps(info, indent=2), encoding="utf-8")
    os.replace(tmp, f)


# One PowerShell script for every case; the values come in through the environment, so
# no path is ever pasted into the script. The REAL desktop: %USERPROFILE%\Desktop is
# wrong when OneDrive (or a policy) moved it.
_PS = r"""
$d=[Environment]::GetFolderPath('Desktop'); if ($env:PH_DESKTOP) { $d=$env:PH_DESKTOP }   # tests
$l=Join-Path $d 'Philibert.lnk'
$w=New-Object -ComObject WScript.Shell
if (Test-Path -LiteralPath $l) {
  $s=$w.CreateShortcut($l); $t=[string]$s.TargetPath
  $root=$env:PH_ROOT.TrimEnd('\') + '\'
  if (-not $t.ToLower().StartsWith($root.ToLower())) {
    if ($env:PH_CREATE -ne '1') { 'OTHER ' + $t; exit }
    $s.TargetPath=$env:PH_TARGET; $s.WorkingDirectory=$env:PH_ROOT    # Setup: this drive now
  }
} elseif ($env:PH_CREATE -ne '1') { 'NONE ' + $l; exit }
else {
  $s=$w.CreateShortcut($l); $s.TargetPath=$env:PH_TARGET; $s.WorkingDirectory=$env:PH_ROOT
  $s.WindowStyle=7; $s.Description='Philibert'
}
if ($env:PH_ICO) { $s.IconLocation=$env:PH_ICO + ',0'; $s.Save() }
if (Test-Path -LiteralPath $l) { 'OK ' + $l } else { 'MISSING ' + $l }
"""


def shortcut(root, icon_id=None, create=False):
    """Desktop\\Philibert.lnk on this computer. With icon_id: give it that picture. create
    (Setup) makes the shortcut, or points one at another drive to this one. Returns {state: ok|none|other|missing|error|not_windows, detail}."""
    if not IS_WIN:
        return {"state": "not_windows", "detail": ""}
    root = Path(root).resolve()
    env = {**os.environ, "PH_ROOT": str(root), "PH_TARGET": str(root / "Start-Windows.bat"),
           "PH_CREATE": "1" if create else "0", "PH_ICO": str(ico_path(root, icon_id)) if icon_id else ""}
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _PS],
                           capture_output=True, text=True, env=env, timeout=60, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return {"state": "error", "detail": str(e)[:300]}
    out = (r.stdout or "").strip().splitlines()
    line = out[-1] if out else (r.stderr or "").strip()[:300]
    word, _, rest = line.partition(" ")
    state = {"OK": "ok", "NONE": "none", "OTHER": "other", "MISSING": "missing"}.get(word, "error")
    if state == "ok" and icon_id:
        register_protocol(root)          # the philibert:// link follows the shortcut (and its icon)
    return {"state": state, "detail": rest if state != "error" else line}


PROTOCOL_KEY = r"Software\Classes\philibert"


def register_protocol(root, key=None):
    """philibert:// starts this drive's Philibert (what the desktop shortcut starts)."""
    if not IS_WIN:
        return False
    import winreg
    root = Path(root).resolve()
    key = key or os.environ.get("PH_PROTOCOL_KEY") or PROTOCOL_KEY       # tests use their own key
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:Philibert")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\DefaultIcon") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(ico_path(root, current(root))) + ",0")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, '"' + str(root / "Start-Windows.bat") + '"')
        return True
    except OSError:
        return False


def handle(body, root):
    """/api/desktop ops for Control Panel > Icon."""
    op = body.get("op")
    if op == "icons":
        sc = shortcut(root)
        return {"ok": True, "icons": with_pictures(icons(root), icons_dir(root)), "current": current(root),
                "shortcut": sc["state"], "windows": IS_WIN}
    if op == "icon_set":
        icon_id = str(body.get("id") or "")
        if not any(it["id"] == icon_id for it in icons(root)):
            return {"ok": False, "message": "That icon isn't on this drive."}
        remember(root, icon_id)
        sc = shortcut(root, icon_id, create=bool(body.get("create")))
        msg = {"ok": "The desktop shortcut has the new icon.",
               "none": "Saved. There's no Philibert shortcut on this computer's desktop.",
               "other": "Saved. The Philibert shortcut on this desktop starts a different drive, so it was left alone.",
               "not_windows": "Saved. The icon is used by the Windows desktop shortcut."}.get(
                   sc["state"], "Saved, but the desktop shortcut couldn't be changed: " + sc["detail"])
        return {"ok": True, "current": icon_id, "shortcut": sc["state"], "message": msg}
    return {"ok": False, "message": "unknown op"}
