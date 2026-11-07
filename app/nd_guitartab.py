"""TabCrafter: a solo guitar recording (.wav / .mp3 / .flac / .ogg) to tablature.

  runtime/<plat>/guitartab/site-py<ver>   its packages (Basic Pitch, librosa, onnxruntime - about
                                         500 MB), set up on first use; the app's own Python runs them
  data/guitartab/<id>/                   one transcription: the recording, meta.json, notes.json
                                         (the notes found - a new BPM or tuning skips finding them
                                         again) and tab.json (the tab, with the person's edits)
  data/guitartab/.trash/<id>             deleted ones

The work is done by nd_guitartab_engine.py in its own process (written and scored on GuitarSet
in the GuitarTab project): it finds the notes, follows the beat from the BPM the person gives
(typed or tapped), and picks a string and fret for every note the way a hand would play it.

Entry points: handle(body, root, data_dir, internet) for /api/guitartab;
audio_file(data_dir, id) for the page's player.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

IS_WIN = os.name == "nt"
_NO_WINDOW = 0x08000000 if IS_WIN else 0
ENGINE = Path(__file__).resolve().parent / "nd_guitartab_engine.py"
PACKAGES = ["numpy==1.26.4", "scipy==1.13.1", "onnxruntime==1.31.1", "librosa==0.11.0", "soundfile==0.14.0",
            "resampy==0.4.2", "pretty-midi==0.2.11.post0", "mir-eval==0.8.2", "scikit-learn==1.9.1",
            "typing-extensions"]
NO_DEPS = ["basic-pitch==0.4.0"]          # its own list pulls in TensorFlow (1.2 GB), which it doesn't need
AUDIO = {".wav", ".mp3", ".flac", ".ogg"}
MAX_AUDIO = 200 * 2**20
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B", "Fb": "E"}
TUNINGS = [            # (id, label, low to high)
    ("standard", "Standard (E A D G B E)", "E A D G B E"),
    ("dropd", "Drop D (D A D G B E)", "D A D G B E"),
    ("halfstep", "Half step down (Eb Ab Db Gb Bb Eb)", "Eb Ab Db Gb Bb Eb"),
    ("dstandard", "D standard (D G C F A D)", "D G C F A D"),
    ("dropc", "Drop C (C G C F A D)", "C G C F A D"),
    ("openg", "Open G (D G D G B D)", "D G D G B D"),
    ("opend", "Open D (D A D F# A D)", "D A D F# A D"),
    ("dadgad", "DADGAD", "D A D G A D"),
    ("7standard", "7-string standard (B E A D G B E)", "B E A D G B E"),
    ("7dropa", "7-string drop A (A E A D G B E)", "A E A D G B E"),
    ("8standard", "8-string standard (F# B E A D G B E)", "F# B E A D G B E"),
    ("8dropE", "8-string drop E (E B E A D G B E)", "E B E A D G B E"),
]
_ID = re.compile(r"^[a-f0-9]{12}$")
_install = {"state": "idle", "line": "", "progress": 0.0, "error": ""}
_jobs = {}                                  # id -> {"state", "step", "error"} while a tab is written
_lock = threading.Lock()


def plat():
    if IS_WIN:
        return "win-x64"
    import platform
    return "mac-arm64" if platform.machine() in ("arm64", "aarch64") else "mac-x64"


def site_dir(root):
    v = sys.version_info
    return Path(root) / "runtime" / plat() / "guitartab" / f"site-py{v.major}{v.minor}"


def installed(root):
    return (site_dir(root) / ".philibert-ready").is_file()


# --- tunings -------------------------------------------------------------------------------
def parse_tuning(text):
    """'E A D G B E' (low to high), 'E2 A2 ...' or a preset id -> MIDI numbers, or None.
    Without octaves the lowest string goes at or below A2 (7 strings: E2, 8: B1) and each next
    string is the nearest pitch above the one before (the engine's rule)."""
    text = next((t[2] for t in TUNINGS if t[0] == text), text or "")
    toks = re.findall(r"([A-Ga-g])([#b]?)(-?\d)?", text)
    if not 4 <= len(toks) <= 9:
        return None
    lowest = 45 - 5 * max(0, len(toks) - 6)
    out = []
    for letter, acc, octv in toks:
        name = FLATS.get(letter.upper() + acc, letter.upper() + acc)
        pc = NAMES.index(name)
        if octv:
            m = 12 * (int(octv) + 1) + pc
        elif not out:
            m = 36 + pc
            while m > lowest:
                m -= 12
        else:
            m = out[-1] + 1
            while m % 12 != pc:
                m += 1
        out.append(m)
    if any(b <= a for a, b in zip(out, out[1:])) or out[0] < 23 or out[-1] > 76:
        return None
    return out


def note_name(m):
    return NAMES[m % 12] + str(m // 12 - 1)


# --- setting up ----------------------------------------------------------------------------
def _env(tmp=None):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env.update(PYTHONNOUSERSITE="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONIOENCODING="utf-8")
    if tmp:
        env.update(TEMP=str(tmp), TMP=str(tmp), TMPDIR=str(tmp))
    return env


def install(root, say=lambda line, frac=-1: print(line, flush=True)):
    """The packages, into this add-on's own folder (never the app's); safe to run again."""
    site = site_dir(root)
    site.mkdir(parents=True, exist_ok=True)
    tmp = site.parent / "_tmp"
    tmp.mkdir(exist_ok=True)
    pip = [sys.executable, "-s", "-m", "pip", "install", "--no-cache-dir", "--no-warn-script-location",
           "--progress-bar", "off", "--upgrade", "--target", str(site)]
    steps = [(PACKAGES, "Getting the note finder's building blocks", 0.05, 0.8), (["--no-deps"] + NO_DEPS, "Getting the note finder", 0.85, 0.1)]
    for pkgs, label, base, span in steps:
        say(label, base)
        p = subprocess.Popen(pip + pkgs, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=_env(tmp),
                             encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
        n, tail = 0, []
        for line in p.stdout:
            line = line.strip()
            tail = (tail + [line])[-6:]
            if line.startswith(("Collecting", "Downloading", "Installing collected")):
                n += 1
                say(line[:90], base + span * min(0.95, n / 40))
        if p.wait():
            raise RuntimeError("The note finder did not install. Check the Internet connection and try again."
                               + (" (" + tail[-1][:160] + ")" if tail else ""))
    shutil.rmtree(tmp, ignore_errors=True)
    say("Checking it works", 0.97)
    r = _engine(root, "check", {}, timeout=300)
    if not r.get("ok"):
        raise RuntimeError("The note finder installed but does not start: " + r.get("msg", ""))
    (site / ".philibert-ready").write_text(json.dumps({"packages": PACKAGES + NO_DEPS, "when": time.strftime("%Y-%m-%d %H:%M")}),
                                           encoding="utf-8")
    say("TabCrafter is ready.", 1.0)


def install_async(root, internet=True):
    if not internet:
        return {"ok": False, "msg": "Setting up TabCrafter downloads about 150 MB (500 MB on the drive): turn the INTERNET switch on first."}
    with _lock:
        if _install["state"] == "running":
            return {"ok": True}
        _install.update(state="running", line="Starting", progress=0.0, error="")

    def say(line, frac=-1):
        _install["line"] = line
        if frac >= 0:
            _install["progress"] = frac

    def go():
        try:
            install(root, say)
            _install["state"] = "done"
        except Exception as e:
            _install.update(state="error", error=str(e))
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True}


# --- the engine ----------------------------------------------------------------------------
def _engine(root, cmd, job, timeout=900, step=None):
    """Run nd_guitartab_engine.py in app mode; its last line is the JSON answer."""
    args = [sys.executable, "-s", str(ENGINE), "--site", str(site_dir(root)), "app", cmd, json.dumps(job)]
    try:
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=_env(),
                             cwd=str(ENGINE.parent), encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    except OSError as e:
        return {"ok": False, "msg": str(e)}
    last, tail = None, []
    timer = threading.Timer(timeout, p.kill)
    timer.start()
    try:
        for line in p.stdout:
            line = line.strip()
            if line.startswith("STEP ") and step:
                step(line[5:])
            elif line.startswith("{"):
                last = line
            elif line:
                tail = (tail + [line])[-4:]
        p.wait()
    finally:
        timer.cancel()
    try:
        return json.loads(last) if last else {"ok": False, "msg": (tail[-1] if tail else "no answer")[:300]}
    except ValueError:
        return {"ok": False, "msg": "unreadable answer"}


# --- transcriptions ------------------------------------------------------------------------
def _dir(data_dir, tid):
    if not isinstance(tid, str) or not _ID.match(tid):
        return None
    d = Path(data_dir) / "guitartab" / tid
    return d if d.is_dir() else None


def _meta(d):
    try:
        return json.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_meta(d, m):
    (d / "meta.json").write_text(json.dumps(m, indent=1), encoding="utf-8")


def audio_file(data_dir, tid):
    d = _dir(data_dir, tid)
    if not d:
        return None
    return next((f for f in d.iterdir() if f.stem == "recording" and f.suffix.lower() in AUDIO), None)


def _public(d):
    m = _meta(d)
    tid = d.name
    job = _jobs.get(tid)
    return {**m, "id": tid, "has_tab": (d / "tab.json").is_file(),
            "job": dict(job) if job else None}


def listing(data_dir):
    base = Path(data_dir) / "guitartab"
    out = [_public(d) for d in base.iterdir() if d.is_dir() and _ID.match(d.name)] if base.is_dir() else []
    return sorted(out, key=lambda m: m.get("created", ""), reverse=True)


def create(data_dir, name, ext, data_b64):
    ext = "." + str(ext or "").lower().lstrip(".")
    if ext not in AUDIO:
        return {"ok": False, "msg": "TabCrafter reads .wav, .mp3, .flac and .ogg recordings."}
    try:
        data = base64.b64decode(data_b64 or "", validate=True)
    except ValueError:
        return {"ok": False, "msg": "The recording did not arrive whole - try again."}
    if not data:
        return {"ok": False, "msg": "That file is empty."}
    if len(data) > MAX_AUDIO:
        return {"ok": False, "msg": "That recording is over 200 MB - trim it or save it as an .mp3 first."}
    tid = uuid.uuid4().hex[:12]
    d = Path(data_dir) / "guitartab" / tid
    d.mkdir(parents=True)
    (d / ("recording" + ext)).write_bytes(data)
    name = re.sub(r"\s+", " ", str(name or "Untitled")).strip()[:80] or "Untitled"
    _save_meta(d, {"name": name, "file": name + ext, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "strings": 6, "tuning": "standard", "tuning_notes": parse_tuning("standard"),
                   "bpm": None, "time": [4, 4], "edited": False})
    return {"ok": True, "id": tid, "item": _public(d)}


def transcribe(root, data_dir, tid, settings):
    d = _dir(data_dir, tid)
    if not d:
        return {"ok": False, "msg": "That recording is gone."}
    if not installed(root):
        return {"ok": False, "msg": "TabCrafter isn't set up on this computer yet."}
    tuning = parse_tuning(str(settings.get("tuning") or ""))
    if not tuning:
        return {"ok": False, "msg": "That tuning can't be read: give 4 to 9 notes, low string first, e.g. D A D G B E."}
    try:
        bpm = float(settings.get("bpm"))
    except (TypeError, ValueError):
        bpm = 0
    if not 30 <= bpm <= 300:
        return {"ok": False, "msg": "Give the tempo first: type the BPM (30-300) or tap it."}
    ts = settings.get("time") or [4, 4]
    try:
        num, den = int(ts[0]), int(ts[1])
    except (TypeError, ValueError, IndexError):
        num, den = 4, 4
    if not (1 <= num <= 12 and den in (2, 4, 8)):
        return {"ok": False, "msg": "That time signature isn't one TabCrafter writes (try 4/4, 3/4 or 6/8)."}
    with _lock:
        if any(j["state"] == "running" for j in _jobs.values()):
            return {"ok": False, "msg": "Another tab is being written - this one can start when it's done."}
        _jobs[tid] = {"state": "running", "step": "notes", "error": ""}
    m = _meta(d)
    m.update(strings=len(tuning), tuning=str(settings.get("tuning")), tuning_notes=tuning, bpm=round(bpm, 2),
             time=[num, den], steady=bool(settings.get("steady")))
    _save_meta(d, m)
    audio = audio_file(data_dir, tid)
    job = {"audio": str(audio), "tuning": tuning, "bpm": bpm, "time": [num, den], "steady": bool(settings.get("steady")),
           "cache": str(d / "notes.json"), "out": str(d / "tab.new.json")}

    def go():
        try:
            r = _engine(root, "transcribe", job, step=lambda s: _jobs[tid].update(step=s))
            if r.get("ok"):
                (d / "tab.new.json").replace(d / "tab.json")
                m2 = _meta(d)
                m2.update(edited=False, written=time.strftime("%Y-%m-%d %H:%M:%S"))
                _save_meta(d, m2)
                _jobs.pop(tid, None)
            else:
                _jobs[tid] = {"state": "error", "step": "", "error": r.get("msg") or "The tab could not be written."}
        except Exception as e:
            _jobs[tid] = {"state": "error", "step": "", "error": str(e)}
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True, "item": _public(d)}


def _clean_items(items, n_strings):
    """The page's edited tab: only the shape it sent us, with frets on real strings."""
    out = []
    if not isinstance(items, list) or len(items) > 50000:
        return None
    for it in items:
        if not isinstance(it, dict) or it.get("kind") not in ("note", "rest", "tie"):
            return None
        try:
            tick, ticks = int(it["tick"]), int(it["ticks"])
            frets = [[int(s), int(f)] for s, f in (it.get("frets") or [])]
        except (KeyError, TypeError, ValueError):
            return None
        if tick < 0 or not 1 <= ticks <= 96 or any(not (0 <= s < n_strings and 0 <= f <= 30) for s, f in frets):
            return None
        if len({s for s, _ in frets}) != len(frets):
            return None
        out.append({"tick": tick, "ticks": ticks, "kind": it["kind"], "sym": str(it.get("sym", ""))[:4], "frets": frets})
    return out


def handle(body, root, data_dir, internet=True):
    op = str(body.get("op") or "")
    if op == "status":
        return {"ok": True, "installed": installed(root), "install": dict(_install), "internet": bool(internet),
                "tunings": [{"id": i, "label": label, "notes": parse_tuning(t)} for i, label, t in TUNINGS]}
    if op == "install":
        return install_async(root, internet)
    if op == "list":
        return {"ok": True, "items": listing(data_dir)}
    if op == "create":
        return create(data_dir, body.get("name"), body.get("ext"), body.get("data"))
    if op == "tuning":
        t = parse_tuning(str(body.get("text") or ""))
        return {"ok": bool(t), "notes": t, "names": [note_name(m) for m in t] if t else []}
    tid = body.get("id")
    d = _dir(data_dir, tid)
    if op in ("get", "estimate", "transcribe", "save", "rename", "delete") and not d:
        return {"ok": False, "msg": "That recording is gone."}
    if op == "get":
        tab = None
        try:
            tab = json.loads((d / "tab.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        return {"ok": True, "item": _public(d), "tab": tab}
    if op == "estimate":
        if not installed(root):
            return {"ok": False, "msg": "TabCrafter isn't set up on this computer yet."}
        r = _engine(root, "estimate", {"audio": str(audio_file(data_dir, tid))}, timeout=180)
        return r if r.get("ok") else {"ok": False, "msg": "Couldn't hear a steady beat - tap the tempo instead."}
    if op == "transcribe":
        return transcribe(root, data_dir, tid, body)
    if op == "save":
        m = _meta(d)
        try:
            tab = json.loads((d / "tab.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"ok": False, "msg": "There's no tab to save yet."}
        items = _clean_items(body.get("items"), len(tab.get("tuning") or []))
        if items is None:
            return {"ok": False, "msg": "That edit couldn't be saved."}
        tab["items"] = items
        tmp = d / "tab.json.tmp"
        tmp.write_text(json.dumps(tab), encoding="utf-8")
        tmp.replace(d / "tab.json")
        m["edited"] = True
        _save_meta(d, m)
        return {"ok": True}
    if op == "rename":
        m = _meta(d)
        m["name"] = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()[:80] or m.get("name", "Untitled")
        _save_meta(d, m)
        return {"ok": True, "item": _public(d)}
    if op == "delete":
        if _jobs.get(tid, {}).get("state") == "running":
            return {"ok": False, "msg": "Wait for the tab to finish, then delete it."}
        trash = Path(data_dir) / "guitartab" / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        d.replace(trash / tid)
        return {"ok": True}
    return {"ok": False, "msg": "unknown op"}
