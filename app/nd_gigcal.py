"""Band Manager gigs <-> the band calendar (the Schedule's shared calendar on the board server).

A gig that is confirmed (or played) is a "show" on its band's calendar: date, the set time
(or load-in), the venue's address (with a Directions link there), load-in / set / notes. When
the gig changes, the event follows; when it is cancelled, put back to idea/hold or deleted,
the event is cancelled (the band gets the alert, Google Calendar removes it). Each gig keeps
the event's id (cal_event) and a fingerprint of what was last sent (cal_synced), so nothing
is sent twice; "pending" means it waits for the Internet or for the band to have a group.

    sync_gig(data_dir, band, con, gig, online) -> "sent" | "cancelled" | "same" | "pending" | "none"
    sync_all(data_dir, online, band_id=None) -> {sent, cancelled, pending}
    gig_from_event(data_dir, event) -> the new gig (linked to the event)
"""
import hashlib
import json

import nd_band
import nd_bands

LIVE = ("confirmed", "played")


def _hm(x):
    x = str(x or "").strip()
    return x[:5] if len(x) >= 4 and x[:2].isdigit() and ":" in x else ""


def _add(hm, minutes):
    h, m = map(int, hm.split(":"))
    t = min(h * 60 + m + int(minutes), 24 * 60)
    return f"{t // 60:02d}:{t % 60:02d}"


def payload(con, g):
    """The calendar event a gig stands for (whatever its status)."""
    v = dict(con.execute("SELECT * FROM venues WHERE id = ?", (g.get("venue_id"),)).fetchone() or {}) if g.get("venue_id") else {}
    start = _hm(g.get("set_time")) or _hm(g.get("load_in")) or "20:00"
    end = _add(_hm(g["set_time"]), g.get("set_length") or 60) if _hm(g.get("set_time")) else ""
    bits = [f"Load-in {_hm(g['load_in'])}" if _hm(g.get("load_in")) else "",
            f"Set {_hm(g['set_time'])}" + (f" ({g['set_length']} min)" if g.get("set_length") else "") if _hm(g.get("set_time")) else "",
            "" if _hm(g.get("set_time")) or _hm(g.get("load_in")) else "Time to be confirmed",
            g.get("notes") or ""]
    return {"kind": "show", "title": (g.get("title") or f"Show at {v.get('name') or 'TBA'}")[:120], "date": str(g["date"])[:10],
            "start": start, "end": end, "address": ", ".join(x for x in (v.get("name"), v.get("address"), v.get("city")) if x)[:200],
            "notes": ("\n".join(x for x in bits if x) + f"\n(From the Band Manager, gig #{g['id']})")[:2000]}


def _fp(p):
    return hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()[:16]


def _mark(con, gid, **cols):
    con.execute("UPDATE gigs SET " + ", ".join(f'"{k}" = ?' for k in cols) + " WHERE id = ?", [*cols.values(), gid])
    con.commit()


def sync_gig(data_dir, band, con, g, online):
    import nd_board
    live = g.get("status") in LIVE and not g.get("deleted")
    if not live and not g.get("cal_event"):
        return "none"
    p = payload(con, g)
    want = _fp(p) if live else "cancelled"
    if g.get("cal_synced") == want:
        return "same"
    group = band.get("board_group") or ""
    if not group or not online:
        if g.get("cal_synced") != "pending":
            _mark(con, g["id"], cal_synced="pending")
        return "pending"
    r = nd_board.handle({"op": "event_save", "group": group, "id": g.get("cal_event") or "", **p, "cancelled": not live},
                        data_dir, online)
    if not r.get("ok") and g.get("cal_event") and live and "gone" in (r.get("msg") or ""):
        r = nd_board.handle({"op": "event_save", "group": group, "id": "", **p}, data_dir, online)   # removed there: book it again
    if not r.get("ok"):
        if g.get("cal_synced") != "pending":
            _mark(con, g["id"], cal_synced="pending")
        return "pending"
    _mark(con, g["id"], cal_event=r["event"]["id"], cal_synced=want)
    return "sent" if live else "cancelled"


def sync_all(data_dir, online, band_id=None):
    """Every gig of a band (default: the open one) that the calendar doesn't match yet."""
    band = nd_bands._find(nd_bands.registry(data_dir), band_id) if band_id else nd_bands.active(data_dir)
    out = {"sent": 0, "cancelled": 0, "pending": 0}
    con = nd_band.connect(nd_bands.db_path(data_dir, band["id"]))
    try:
        for g in con.execute("SELECT * FROM gigs").fetchall():
            r = sync_gig(data_dir, band, con, dict(g), online)
            if r in out:
                out[r] += 1
    finally:
        con.close()
    return out


def gig_from_event(data_dir, ev):
    """A show booked in the Schedule, added to the open band's gigs (linked, so no double)."""
    con = nd_band.connect(nd_bands.db_path(data_dir))
    try:
        hit = con.execute("SELECT * FROM gigs WHERE cal_event = ? AND deleted = 0", (ev.get("id"),)).fetchone()
        if hit:
            return dict(hit)
        venue_id = None
        addr = str(ev.get("address") or "").strip()
        if addr:
            name = (ev.get("title") or "")[8:] if str(ev.get("title") or "").startswith("Show at ") else addr.split(",")[0]
            street = addr[len(name) + 1:].strip() if name and addr.lower().startswith(name.lower() + ",") else addr
            v = con.execute("SELECT id FROM venues WHERE deleted = 0 AND (name = ? OR address = ?)", (name, street)).fetchone()
            venue_id = v[0] if v else nd_band.save(con, "venues", {"name": name or addr, "address": street})["id"]
        g = nd_band.save(con, "gigs", {"date": ev["date"], "title": ev.get("title") or "", "status": "confirmed",
                                       "set_time": ev.get("start") or "", "venue_id": venue_id, "notes": ev.get("notes") or ""})
        g = dict(con.execute("SELECT * FROM gigs WHERE id = ?", (g["id"],)).fetchone())
        # linked, and marked as matching what the calendar has now (the next change goes out)
        _mark(con, g["id"], cal_event=ev.get("id"), cal_synced=_fp(payload(con, g)))
        return dict(con.execute("SELECT * FROM gigs WHERE id = ?", (g["id"],)).fetchone())
    finally:
        con.close()
