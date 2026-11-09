"""Audio File Splitter (in TabCrafter): one long recording - an audiobook, a podcast - cut into
parts that are easier to queue up and keep track of on a playlist.

The parts are copies of the original's own audio, cut without re-encoding (PyAV, which Philibert's
Python already has): no quality is lost and an hour takes seconds. The original file is only ever
read. Parts are named <name>_part1, _part2, ... (_part01 when there are ten or more, so they sort
in order), with the original's tags and cover, the title + " - Part N" and the track number N/total.

  data/audiosplit/inbox/<token>/   a file dropped on the page (the browser can't say where it lives,
                                   so it is copied here first); removed when its parts are done

Entry point: handle(body, data_dir) for the split_* ops of /api/guitartab.
"""
import base64
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

AUDIO = {".mp3", ".m4b", ".m4a", ".mp4", ".aac", ".flac", ".ogg", ".opus", ".oga", ".wav", ".wma", ".mka"}
MIN_PART = 60.0                      # seconds: no part shorter than a minute
MAX_PARTS = 500
CHUNK = 8 * 2**20                    # largest piece of a dropped file per request
_TOKEN = re.compile(r"^[a-f0-9]{16}$")
_uploads = {}                        # token -> {"path", "size", "got"}
_job = {"state": "idle"}             # the one split running (or the last one)
_lock = threading.Lock()


def _av():
    import av                        # ships with Philibert's Python (faster-whisper needs it)
    av.logging.set_level(av.logging.ERROR)
    return av


def clock(sec):
    sec = int(round(sec))
    return f"{sec // 3600}:{sec // 60 % 60:02d}:{sec % 60:02d}"


# --- what the file is ------------------------------------------------------------------------
def probe(path):
    p = Path(str(path or ""))
    if not p.is_file():
        return {"ok": False, "msg": "That file isn't there any more."}
    if p.suffix.lower() not in AUDIO:
        return {"ok": False, "msg": "The splitter reads " + ", ".join(sorted(AUDIO)) + " files."}
    try:
        with _av().open(str(p)) as c:
            if not c.streams.audio:
                return {"ok": False, "msg": "There's no audio in that file."}
            a = c.streams.audio[0]
            dur = c.duration / 1_000_000 if c.duration else (float(a.duration * a.time_base) if a.duration else 0)
            md = {k.lower(): v for k, v in {**a.metadata, **c.metadata}.items()}
            info = {"codec": a.codec_context.name, "rate": a.codec_context.sample_rate, "channels": a.codec_context.channels,
                    "kbps": round((c.bit_rate or a.codec_context.bit_rate or 0) / 1000),
                    "cover": any(s.type == "video" for s in c.streams), "chapters": len(c.chapters() if hasattr(c, "chapters") else [])}
    except Exception as e:
        return {"ok": False, "msg": f"That file can't be read as audio ({str(e)[:120]})."}
    if dur < 1:
        return {"ok": False, "msg": "That file's length can't be read."}
    return {"ok": True, "path": str(p), "name": p.name, "folder": str(p.parent), "size": p.stat().st_size,
            "duration": round(dur, 2), "length": clock(dur), "title": md.get("title", ""), "artist": md.get("artist", ""),
            "album": md.get("album", ""), **info}


# --- planning the parts -------------------------------------------------------------------------
def plan(duration, parts=None, max_minutes=None):
    """-> list of (start, end) seconds, all the same length, or an error string."""
    if parts:
        n = int(parts)
    elif max_minutes:
        n = math.ceil(duration / (float(max_minutes) * 60) - 1e-9)
    else:
        return "Choose how many parts, or the longest a part may be."
    if n < 2:
        return "That's one part - the file is already that short."
    if n > MAX_PARTS or duration / n < MIN_PART:
        return f"That's too many parts: keep each one a minute or longer (at most {min(MAX_PARTS, int(duration // MIN_PART))} parts)."
    step = duration / n
    return [(i * step, duration if i == n - 1 else (i + 1) * step) for i in range(n)]


def part_names(src, n, out_dir):
    src = Path(src)
    width = len(str(n)) if n >= 10 else 1
    return [Path(out_dir) / f"{src.stem}_part{str(i + 1).zfill(width)}{src.suffix}" for i in range(n)]


# --- cutting --------------------------------------------------------------------------------------
def split(src, cuts, outs, progress=lambda frac, i: None):
    """Copy src's audio packets into one file per (start, end); no re-encoding. Writes each part
    as <name>.partial first, so a part only appears under its real name once it is whole."""
    av = _av()
    src, total = Path(src), len(outs)
    with av.open(str(src)) as inp:
        a = inp.streams.audio[0]
        pics = [s for s in inp.streams if s.type == "video" and s.disposition & av.stream.Disposition.attached_pic]
        pic_packets = []
        for s in pics[:1]:                                    # the cover: one picture, stored as a packet
            for pk in inp.demux(s):
                if pk.size:
                    pic_packets.append((s, bytes(pk), pk.pts))
                    break
            inp.seek(0)
        md = {**a.metadata, **inp.metadata}                     # (Ogg's tags are on the stream)
        title = md.get("title") or md.get("TITLE") or src.stem
        tb = a.time_base
        out = part = None
        start_pts = None
        span = [0]                                              # this part's length, in the stream's time units
        i = -1

        def open_part(k):
            o = av.open(str(outs[k]) + ".partial", "w", format=_format(outs[k], inp))
            o.metadata.update({key: v for key, v in md.items() if key.lower() not in ("title", "track", "encoder", "duration")})
            o.metadata["title"] = f"{title} - Part {k + 1}"
            o.metadata["track"] = f"{k + 1}/{total}"
            os_ = o.add_stream_from_template(a)
            if o.format.name == "ogg":                      # Ogg keeps its tags on the stream
                os_.metadata.update(o.metadata)
            ps = []
            for s, _, _ in pic_packets:
                try:
                    vs = o.add_stream_from_template(s)
                except ValueError:                        # a format that can't hold this cover
                    continue
                vs.disposition = av.stream.Disposition.attached_pic
                ps.append(vs)
            return o, os_, ps

        def close_part(k):
            out.close()
            if outs[k].suffix.lower() == ".flac":
                _flac_length(str(outs[k]) + ".partial", round(span[0] * tb * a.codec_context.sample_rate))
            Path(str(outs[k]) + ".partial").replace(outs[k])

        for pk in inp.demux(a):
            if pk.pts is None or pk.size == 0:
                continue
            t = float(pk.pts * tb)
            while i < 0 or (i + 1 < total and t >= cuts[i + 1][0]):
                if out is not None:
                    close_part(i)
                    progress((i + 1) / total, i + 1)
                i += 1
                out, part, pstreams = open_part(i)
                for vs, (_, data, _) in zip(pstreams, pic_packets):
                    pp = av.Packet(data)
                    pp.stream = vs
                    pp.pts = pp.dts = 0
                    out.mux(pp)
                start_pts = pk.pts
                span[0] = 0
            dts = pk.dts if pk.dts is not None else pk.pts
            pk.pts -= start_pts
            pk.dts = dts - start_pts
            pk.stream = part
            span[0] = max(span[0], pk.pts + (pk.duration or 0))
            out.mux(pk)
            if i + 1 < total:
                progress((i + min(1.0, max(0.0, (t - cuts[i][0]) / max(1e-6, cuts[i][1] - cuts[i][0])))) / total, i)
        if out is not None:
            close_part(i)
    progress(1.0, total)
    return [str(o) for o in outs[:i + 1]]


def _flac_length(path, samples):
    """A FLAC part keeps the original's STREAMINFO block, which says how long the whole book is:
    put this part's own length in it (and clear the checksum, which was the whole book's)."""
    with open(path, "r+b") as f:
        head = f.read(42)
        if head[:4] != b"fLaC" or head[4] & 0x7F != 0:
            return
        info = bytearray(head[8:42])
        packed = int.from_bytes(info[10:18], "big")             # rate 20 | channels 3 | bits 5 | samples 36
        packed = (packed & ~((1 << 36) - 1)) | (samples & ((1 << 36) - 1))
        info[10:18] = packed.to_bytes(8, "big")
        info[18:34] = bytes(16)
        f.seek(8)
        f.write(info)


def _format(dest, inp):
    ext = Path(dest).suffix.lower()
    return {".m4b": "mp4", ".m4a": "mp4", ".mp4": "mp4", ".aac": "adts", ".opus": "ogg", ".oga": "ogg",
            ".wma": "asf", ".mka": "matroska"}.get(ext) or inp.format.name.split(",")[0]


# --- the page's ops ---------------------------------------------------------------------------------
def pick_file():
    """This computer's own Open dialog (Philibert runs on the same computer as its window)."""
    pattern = ";".join("*" + e for e in sorted(AUDIO))
    try:
        if sys.platform == "win32":
            ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;Add-Type -AssemblyName System.Windows.Forms;"
                  "$o=New-Object System.Windows.Forms.Form -Property @{TopMost=$true;ShowInTaskbar=$false};"
                  "$d=New-Object System.Windows.Forms.OpenFileDialog;$d.Title='Choose a long audio file to split';"
                  "$d.Filter='Audio files|" + pattern + "|All files|*.*';"
                  "if($d.ShowDialog($o) -eq 'OK'){[Console]::Out.Write($d.FileName)}")
            r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", ps], capture_output=True, text=True,
                               timeout=600, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        elif sys.platform == "darwin":
            r = subprocess.run(["osascript", "-e", 'POSIX path of (choose file with prompt "Choose a long audio file to split")'],
                               capture_output=True, text=True, timeout=600)
        else:
            return ""
    except (OSError, subprocess.SubprocessError):
        return ""
    out = (r.stdout or "").strip()
    return out if out and Path(out).is_file() else ""


def _default_out(info, data_dir):
    if Path(info["path"]).is_relative_to(Path(data_dir) / "audiosplit"):
        dl = Path.home() / "Downloads"
        return str(dl if dl.is_dir() else Path.home())
    return info["folder"]


def start(body, data_dir):
    info = probe(body.get("path"))
    if not info.get("ok"):
        return info
    cuts = plan(info["duration"], body.get("parts"), body.get("max_minutes"))
    if isinstance(cuts, str):
        return {"ok": False, "msg": cuts}
    out_dir = Path(str(body.get("out_dir") or _default_out(info, data_dir)))
    if not out_dir.is_dir():
        return {"ok": False, "msg": "That folder for the parts isn't there."}
    outs = part_names(info["path"], len(cuts), out_dir)
    src = Path(info["path"]).resolve()
    if any(o.resolve() == src for o in outs):
        return {"ok": False, "msg": "A part would have the original's name - rename the original first."}
    there = [o.name for o in outs if o.exists()]
    if there and not body.get("replace"):
        return {"ok": False, "exists": there, "msg": f"{len(there)} of these parts are already in that folder."}
    free = shutil.disk_usage(out_dir).free
    if free < info["size"] * 1.05 + 50 * 2**20:
        return {"ok": False, "msg": f"That drive has {free / 2**30:.1f} GB free; the parts need about {info['size'] / 2**30:.1f} GB."}
    with _lock:
        if _job.get("state") == "running":
            return {"ok": False, "msg": "A split is already running - this one can start when it's done."}
        _job.clear()
        _job.update(state="running", progress=0.0, part=0, total=len(cuts), files=[], folder=str(out_dir), src=info["path"],
                    name=info["name"], error="", started=time.time())

    def say(frac, k):
        _job.update(progress=round(frac, 4), part=min(k + 1, len(cuts)))

    def go():
        try:
            files = split(info["path"], cuts, outs, say)
            _job.update(state="done", files=[{"name": Path(f).name, "length": clock(e - s)} for f, (s, e) in zip(files, cuts)])
            inbox = Path(data_dir) / "audiosplit" / "inbox"
            if src.is_relative_to(inbox.resolve()):
                shutil.rmtree(src.parent, ignore_errors=True)    # our own copy of a dropped file
        except Exception as e:
            for o in outs:
                Path(str(o) + ".partial").unlink(missing_ok=True)
            _job.update(state="error", error=f"The split stopped: {str(e)[:200]}")
    threading.Thread(target=go, daemon=True).start()
    return {"ok": True, "total": len(cuts), "folder": str(out_dir), "names": [o.name for o in outs]}


def handle(body, data_dir):
    op = str(body.get("op") or "")
    if op == "split_pick":
        path = pick_file()
        return probe(path) if path else {"ok": False, "cancelled": True}
    if op == "split_probe":
        return probe(body.get("path"))
    if op == "split_preview":
        info = probe(body.get("path"))
        if not info.get("ok"):
            return info
        cuts = plan(info["duration"], body.get("parts"), body.get("max_minutes"))
        if isinstance(cuts, str):
            return {"ok": False, "msg": cuts}
        out_dir = str(body.get("out_dir") or _default_out(info, data_dir))
        names = part_names(info["path"], len(cuts), out_dir)
        return {"ok": True, "folder": out_dir, "parts": [{"name": n.name, "start": clock(s), "end": clock(e), "length": clock(e - s),
                                                         "exists": n.exists()} for n, (s, e) in zip(names, cuts)]}
    if op == "split_pick_folder":
        import nd_retro_vault
        path = nd_retro_vault.pick_folder("Where should the parts go", str(body.get("start") or ""))
        return {"ok": bool(path), "path": path}
    if op == "split_upload":           # a dropped file, in pieces: {name, size, i, data}; i=0 starts it
        name = Path(str(body.get("name") or "")).name
        if Path(name).suffix.lower() not in AUDIO:
            return {"ok": False, "msg": "The splitter reads " + ", ".join(sorted(AUDIO)) + " files."}
        try:
            data = base64.b64decode(body.get("data") or "", validate=True)
            i, size = int(body.get("i") or 0), int(body.get("size") or 0)
        except (ValueError, TypeError):
            return {"ok": False, "msg": "A piece of the file did not arrive whole - try again."}
        if len(data) > CHUNK:
            return {"ok": False, "msg": "too big a piece"}
        if i == 0:
            inbox = Path(data_dir) / "audiosplit" / "inbox"
            inbox.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(inbox).free < size * 2.1 + 100 * 2**20:
                return {"ok": False, "msg": "There isn't room on Philibert's drive for a copy of that file and its parts - use Browse instead, which reads it where it is."}
            busy = _job.get("src", "") if _job.get("state") == "running" else ""
            for old in inbox.iterdir():                     # earlier drops that were never split
                if old.is_dir() and not busy.startswith(str(old)):
                    shutil.rmtree(old, ignore_errors=True)
                    _uploads.pop(old.name, None)
            token = uuid.uuid4().hex[:16]
            (inbox / token).mkdir()
            _uploads[token] = {"path": inbox / token / name, "size": size, "got": 0}
            _uploads[token]["path"].write_bytes(b"")
        else:
            token = str(body.get("token") or "")
        u = _uploads.get(token) if _TOKEN.match(token) else None
        if not u:
            return {"ok": False, "msg": "That upload was lost - drop the file again."}
        with open(u["path"], "ab") as f:
            f.write(data)
        u["got"] += len(data)
        if u["got"] < u["size"]:
            return {"ok": True, "token": token, "got": u["got"]}
        _uploads.pop(token, None)
        return {**probe(u["path"]), "token": token, "dropped": True}
    if op == "split_start":
        return start(body, data_dir)
    if op == "split_status":
        j = dict(_job)
        j.pop("started", None)
        j.pop("src", None)
        return {"ok": True, **j}
    if op == "split_show":             # the parts' folder, in Explorer / Finder
        folder = Path(str(body.get("folder") or ""))
        if not folder.is_dir():
            return {"ok": False, "msg": "That folder isn't there."}
        if sys.platform == "win32":
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        return {"ok": True}
    return {"ok": False, "msg": "unknown op"}
