"""Several bands on one drive: the Band Manager's list of bands, which one is open, and
where each one's data lives. Each band is its own SQLite file (nd_band does the rest):
the first band keeps the original data/band.db; new ones are data/bands/<id>.db.

    data/bands/bands.json   {"active": id, "bands": [{id, name, db, board_group, created}]}

A band can be linked to a Group Board group (board_group = the group's id), so the
Schedule shares that band's availability and calendar with the right people.

    handle(body, data_dir) -> dict          ops: bands_list, bands_create, bands_rename,
                                             bands_select, bands_delete, bands_link
    db_path(data_dir, band_id=None) -> Path  (None = the open band)
"""
import json
import re
import secrets
import shutil
import time
from pathlib import Path


class BandsError(Exception):
    pass


def _reg_file(data_dir):
    return Path(data_dir) / "bands" / "bands.json"


def registry(data_dir):
    f = _reg_file(data_dir)
    try:
        r = json.loads(f.read_text(encoding="utf-8"))
        if r.get("bands"):
            return r
    except (OSError, ValueError):
        pass
    # first use: the drive's one band so far (data/band.db, if any) becomes the first entry
    r = {"active": "main", "bands": [{"id": "main", "name": _first_name(data_dir), "db": "band.db", "board_group": "",
                                       "created": time.time()}]}
    _save(data_dir, r)
    return r


def _first_name(data_dir):
    board = Path(data_dir) / "board"
    try:                                      # the board group's name is a good first guess
        allm = json.loads((board / "memberships.json").read_text(encoding="utf-8"))["groups"]
        if len(allm) == 1:
            return next(iter(allm.values()))["group"]["name"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        return json.loads((board / "membership.json").read_text(encoding="utf-8"))["group"]["name"]
    except (OSError, ValueError, KeyError):
        return "My band"


def _save(data_dir, r):
    f = _reg_file(data_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(r, indent=1), encoding="utf-8")


def _find(r, band_id):
    b = next((x for x in r["bands"] if x["id"] == band_id), None)
    if not b:
        raise BandsError("No such band.")
    return b


def db_path(data_dir, band_id=None):
    r = registry(data_dir)
    b = _find(r, band_id or r["active"]) if (band_id or r["active"]) else r["bands"][0]
    return Path(data_dir) / b["db"]


def active(data_dir):
    r = registry(data_dir)
    return _find(r, r["active"])


def _clean(name):
    name = " ".join(str(name or "").split())[:60]
    if len(name) < 1:
        raise BandsError("Give the band a name.")
    return name


def handle(body, data_dir):
    body = body or {}
    op = body.get("op", "")
    try:
        r = registry(data_dir)
        if op == "bands_list":
            return {"ok": True, "active": r["active"], "bands": r["bands"]}
        if op == "bands_create":
            name = _clean(body.get("name"))
            if any(b["name"].lower() == name.lower() for b in r["bands"]):
                raise BandsError("There's already a band called that.")
            bid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "band"
            bid = f"{bid}-{secrets.token_hex(3)}"
            r["bands"].append({"id": bid, "name": name, "db": f"bands/{bid}.db", "board_group": "", "created": time.time()})
            r["active"] = bid
            _save(data_dir, r)
            return {"ok": True, "active": bid, "bands": r["bands"]}
        if op == "bands_rename":
            b = _find(r, body.get("id"))
            name = _clean(body.get("name"))
            if any(x["name"].lower() == name.lower() and x["id"] != b["id"] for x in r["bands"]):
                raise BandsError("There's already a band called that.")
            b["name"] = name
            _save(data_dir, r)
            return {"ok": True, "active": r["active"], "bands": r["bands"]}
        if op == "bands_select":
            r["active"] = _find(r, body.get("id"))["id"]
            _save(data_dir, r)
            return {"ok": True, "active": r["active"], "bands": r["bands"]}
        if op == "bands_link":                # the Group Board group this band schedules with
            _find(r, body.get("id"))["board_group"] = str(body.get("group") or "")[:40]
            _save(data_dir, r)
            return {"ok": True, "active": r["active"], "bands": r["bands"]}
        if op == "bands_delete":
            if len(r["bands"]) == 1:
                raise BandsError("That's the only band - rename it instead.")
            b = _find(r, body.get("id"))
            src = Path(data_dir) / b["db"]
            if src.exists():                  # kept, not destroyed: a copy goes to the exports folder
                keep = Path(data_dir) / "exports" / "Deleted bands"
                keep.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.move(str(src), str(keep / f"{b['name']} {time.strftime('%Y-%m-%d %H%M%S')}.db"))
                except OSError:
                    raise BandsError("That band's file is in use - close other Band Manager windows and try again.")
            r["bands"] = [x for x in r["bands"] if x["id"] != b["id"]]
            if r["active"] == b["id"]:
                r["active"] = r["bands"][0]["id"]
            _save(data_dir, r)
            return {"ok": True, "active": r["active"], "bands": r["bands"]}
    except BandsError as e:
        return {"ok": False, "msg": str(e)}
    return {"ok": False, "msg": f"unknown op {op!r}"}
