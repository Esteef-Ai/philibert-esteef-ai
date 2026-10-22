"""Band Manager: a working band's records in one SQLite file on the drive.

  gigs, venues, contacts, songs, setlists (+ their songs, in order),
  merch (+ sales), money (income / expenses), reminders

Nothing is ever deleted outright: delete marks a row deleted (the Trash view
lists them, restore brings them back). Philibert's chat and the Band Manager
page share this one file: <data>/band.db.

Entry point: handle(body, db_path) -> dict.
"""
import json
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# table -> column: type. Every table also has id, created, updated, deleted.
SCHEMA = {
    "contacts": {"name": "TEXT", "role": "TEXT", "phone": "TEXT", "email": "TEXT", "notes": "TEXT"},
    "venues": {"name": "TEXT", "address": "TEXT", "city": "TEXT", "capacity": "INTEGER",
               "contact_id": "INTEGER", "notes": "TEXT"},
    "gigs": {"date": "TEXT", "title": "TEXT", "venue_id": "INTEGER", "status": "TEXT", "fee": "REAL",
             "deposit_paid": "INTEGER", "load_in": "TEXT", "set_time": "TEXT", "set_length": "INTEGER",
             "setlist_id": "INTEGER", "contact_id": "INTEGER", "notes": "TEXT"},
    "songs": {"title": "TEXT", "key": "TEXT", "bpm": "INTEGER", "length_sec": "INTEGER", "notes": "TEXT"},
    "setlists": {"name": "TEXT", "notes": "TEXT"},
    "merch": {"name": "TEXT", "variant": "TEXT", "price": "REAL", "cost": "REAL", "stock": "INTEGER", "notes": "TEXT"},
    "sales": {"date": "TEXT", "merch_id": "INTEGER", "gig_id": "INTEGER", "qty": "INTEGER", "price": "REAL"},
    "money": {"date": "TEXT", "kind": "TEXT", "amount": "REAL", "category": "TEXT", "gig_id": "INTEGER", "note": "TEXT"},
    "reminders": {"due": "TEXT", "text": "TEXT", "done": "INTEGER", "gig_id": "INTEGER"},
}
STATUSES = ["idea", "hold", "confirmed", "played", "cancelled"]
REQUIRED = {"contacts": "name", "venues": "name", "gigs": "date", "songs": "title", "setlists": "name",
            "merch": "name", "money": "amount", "reminders": "text", "sales": "merch_id"}
_lock = threading.Lock()


class BandError(Exception):
    pass


def connect(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = DELETE")     # one file on the drive, no -wal sidecar on exFAT
    for t, cols in SCHEMA.items():
        con.execute(f"CREATE TABLE IF NOT EXISTS {t} (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    + ", ".join(f'"{c}" {ty}' for c, ty in cols.items())
                    + ", created REAL, updated REAL, deleted INTEGER DEFAULT 0)")
        have = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
        for c, ty in cols.items():                # later versions add columns, never drop them
            if c not in have:
                con.execute(f'ALTER TABLE {t} ADD COLUMN "{c}" {ty}')
    con.execute("CREATE TABLE IF NOT EXISTS setlist_songs (setlist_id INTEGER, song_id INTEGER, pos INTEGER)")
    return con


def _table(t):
    if t not in SCHEMA:
        raise BandError(f"unknown list {t!r}")
    return t


def _clean(t, row):
    out = {}
    for c, ty in SCHEMA[t].items():
        if c not in row:
            continue
        v = row[c]
        if v in ("", None):
            out[c] = None
        elif ty == "INTEGER":
            try:
                out[c] = int(float(v)) if not isinstance(v, bool) else int(v)
            except (TypeError, ValueError):
                raise BandError(f"{c} should be a whole number")
        elif ty == "REAL":
            try:
                out[c] = round(float(str(v).replace(",", "").replace("$", "").replace("€", "").replace("£", "")), 2)
            except (TypeError, ValueError):
                raise BandError(f"{c} should be a number")
        else:
            out[c] = str(v)[:4000]
    if t == "gigs" and out.get("status") and out["status"] not in STATUSES:
        out["status"] = "hold"
    if t == "money" and out.get("kind") not in (None, "income", "expense"):
        out["kind"] = "income"
    for c in ("date", "due"):
        if out.get(c):
            try:
                datetime.strptime(out[c][:10], "%Y-%m-%d")
            except ValueError:
                raise BandError(f"{c} should look like 2026-11-07")
    return out


def rows(con, t, include_deleted=False, where="", args=()):
    t = _table(t)
    order = {"gigs": "date", "reminders": "done, due", "money": "date DESC", "sales": "date DESC"}.get(t, "name" if "name" in SCHEMA[t] else "title")
    q = f"SELECT * FROM {t} WHERE " + ("deleted = 1" if include_deleted else "deleted = 0") + (f" AND {where}" if where else "")
    return [dict(r) for r in con.execute(q + f" ORDER BY {order}", args)]


def save(con, t, row):
    t = _table(t)
    data = _clean(t, row or {})
    rid = row.get("id")
    now = time.time()
    if not rid:
        if not data.get(REQUIRED[t]) and data.get(REQUIRED[t]) != 0:
            raise BandError(f"give it a {REQUIRED[t].replace('_id', '')}")
        if t == "gigs":
            data.setdefault("status", "hold")
        if t == "money":
            data.setdefault("kind", "income")
            data.setdefault("date", date.today().isoformat())
        if t == "sales":
            data.setdefault("date", date.today().isoformat())
            data.setdefault("qty", 1)
        cols = list(data) + ["created", "updated"]
        cur = con.execute(f"INSERT INTO {t} ({', '.join(chr(34) + c + chr(34) for c in cols)}) VALUES ({', '.join('?' * len(cols))})",
                          [data[c] for c in data] + [now, now])
        rid = cur.lastrowid
        if t == "sales":                          # a sale takes the item off the shelf
            con.execute("UPDATE merch SET stock = COALESCE(stock, 0) - ? WHERE id = ?", (data.get("qty") or 1, data["merch_id"]))
    else:
        if not con.execute(f"SELECT 1 FROM {t} WHERE id = ?", (rid,)).fetchone():
            raise BandError("no such entry")
        if data:
            con.execute(f"UPDATE {t} SET " + ", ".join(f'"{c}" = ?' for c in data) + ", updated = ? WHERE id = ?",
                        [data[c] for c in data] + [now, rid])
    con.commit()
    return dict(con.execute(f"SELECT * FROM {t} WHERE id = ?", (rid,)).fetchone())


def set_deleted(con, t, rid, flag):
    t = _table(t)
    n = con.execute(f"UPDATE {t} SET deleted = ?, updated = ? WHERE id = ?", (1 if flag else 0, time.time(), rid)).rowcount
    con.commit()
    if not n:
        raise BandError("no such entry")


def setlist(con, sid):
    s = con.execute("SELECT * FROM setlists WHERE id = ?", (sid,)).fetchone()
    if not s:
        raise BandError("no such setlist")
    songs = [dict(r) for r in con.execute(
        "SELECT songs.*, setlist_songs.pos FROM setlist_songs JOIN songs ON songs.id = setlist_songs.song_id "
        "WHERE setlist_songs.setlist_id = ? AND songs.deleted = 0 ORDER BY setlist_songs.pos", (sid,))]
    return {**dict(s), "songs": songs, "total_sec": sum(x.get("length_sec") or 0 for x in songs)}


def set_setlist_songs(con, sid, song_ids):
    setlist(con, sid)
    con.execute("DELETE FROM setlist_songs WHERE setlist_id = ?", (sid,))
    for i, song in enumerate(song_ids[:200]):
        con.execute("INSERT INTO setlist_songs VALUES (?, ?, ?)", (sid, int(song), i))
    con.execute("UPDATE setlists SET updated = ? WHERE id = ?", (time.time(), sid))
    con.commit()
    return setlist(con, sid)


def overview(con, today=None):
    today = today or date.today()
    t0 = today.isoformat()
    upcoming = [dict(r) for r in con.execute(
        "SELECT gigs.*, venues.name AS venue FROM gigs LEFT JOIN venues ON venues.id = gigs.venue_id "
        "WHERE gigs.deleted = 0 AND gigs.date >= ? AND COALESCE(gigs.status, '') != 'cancelled' ORDER BY gigs.date LIMIT 6", (t0,))]
    due = [dict(r) for r in con.execute(
        "SELECT * FROM reminders WHERE deleted = 0 AND COALESCE(done, 0) = 0 AND (due IS NULL OR due <= ?) ORDER BY due",
        ((today + timedelta(days=7)).isoformat(),))]
    year = str(today.year)
    inc = con.execute("SELECT COALESCE(SUM(amount), 0) FROM money WHERE deleted = 0 AND kind = 'income' AND date LIKE ?", (year + "%",)).fetchone()[0]
    exp = con.execute("SELECT COALESCE(SUM(amount), 0) FROM money WHERE deleted = 0 AND kind = 'expense' AND date LIKE ?", (year + "%",)).fetchone()[0]
    merch_in = con.execute("SELECT COALESCE(SUM(qty * price), 0) FROM sales WHERE deleted = 0 AND date LIKE ?", (year + "%",)).fetchone()[0]
    low = [dict(r) for r in con.execute("SELECT * FROM merch WHERE deleted = 0 AND COALESCE(stock, 0) <= 5 ORDER BY stock")]
    unpaid = [dict(r) for r in con.execute(
        "SELECT gigs.*, venues.name AS venue FROM gigs LEFT JOIN venues ON venues.id = gigs.venue_id WHERE gigs.deleted = 0 "
        "AND gigs.status = 'played' AND COALESCE(gigs.fee, 0) > 0 AND NOT EXISTS (SELECT 1 FROM money WHERE money.gig_id = gigs.id "
        "AND money.kind = 'income' AND money.deleted = 0)")]
    return {"upcoming": upcoming, "due": due, "year": year, "income": round(inc + merch_in, 2), "expenses": round(exp, 2),
            "merch_income": round(merch_in, 2), "net": round(inc + merch_in - exp, 2), "low_stock": low, "unpaid": unpaid,
            "counts": {t: con.execute(f"SELECT COUNT(*) FROM {t} WHERE deleted = 0").fetchone()[0] for t in SCHEMA}}


def gig_ics(con, gid):
    """A calendar file for one gig (any calendar app opens it)."""
    g = con.execute("SELECT gigs.*, venues.name AS venue, venues.address, venues.city FROM gigs "
                    "LEFT JOIN venues ON venues.id = gigs.venue_id WHERE gigs.id = ?", (gid,)).fetchone()
    if not g:
        raise BandError("no such gig")
    g = dict(g)
    day = g["date"][:10].replace("-", "")
    start = (g.get("set_time") or g.get("load_in") or "").replace(":", "")[:4]

    def esc(s):
        return str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    if len(start) == 4 and start.isdigit():
        mins = int(g.get("set_length") or 60)
        st = datetime.strptime(day + start, "%Y%m%d%H%M")
        times = f"DTSTART:{st:%Y%m%dT%H%M%S}\r\nDTEND:{st + timedelta(minutes=mins):%Y%m%dT%H%M%S}"
    else:
        nxt = (datetime.strptime(day, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
        times = f"DTSTART;VALUE=DATE:{day}\r\nDTEND;VALUE=DATE:{nxt}"
    where = ", ".join(x for x in (g.get("venue"), g.get("address"), g.get("city")) if x)
    desc = "\n".join(x for x in (f"Load-in {g['load_in']}" if g.get("load_in") else "",
                                  f"Set {g['set_time']}" if g.get("set_time") else "", g.get("notes") or "") if x)
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Esteef.Ai//Philibert Band Manager//EN\r\nBEGIN:VEVENT\r\n"
            f"UID:philibert-gig-{gid}@esteef.ai\r\nDTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}\r\n{times}\r\n"
            f"SUMMARY:{esc(g.get('title') or ('Gig at ' + (g.get('venue') or 'TBA')))}\r\n"
            + (f"LOCATION:{esc(where)}\r\n" if where else "") + (f"DESCRIPTION:{esc(desc)}\r\n" if desc else "")
            + "END:VEVENT\r\nEND:VCALENDAR\r\n")


def _line(t, r, con):
    def venue(vid):
        v = con.execute("SELECT name FROM venues WHERE id = ?", (vid,)).fetchone() if vid else None
        return v[0] if v else ""
    if t == "gigs":
        return (f"#{r['id']} {r['date']} {r.get('title') or ('Gig at ' + (venue(r.get('venue_id')) or 'TBA'))}"
                f" [{r.get('status')}] venue_id={r.get('venue_id')} fee={r.get('fee')} set={r.get('set_time') or '-'}"
                f" load_in={r.get('load_in') or '-'}" + (f" notes: {r['notes'][:80]}" if r.get("notes") else ""))
    keep = [c for c in SCHEMA[t] if r.get(c) not in (None, "")]
    return f"#{r['id']} " + ", ".join(f"{c}={str(r[c])[:80]}" for c in keep)


def tool(name, a, db_path):
    """The chat's view of the band: band_info (read) and band_save (write, approved)."""
    with _lock:
        con = connect(db_path)
        try:
            if name == "band_info":
                what = str(a.get("what") or "overview").lower().strip()
                if what == "overview":
                    o = overview(con)
                    return (f"Next gigs: " + ("; ".join(f"{g['date']} {g.get('venue') or g.get('title') or 'TBA'} [{g['status']}]"
                                                         for g in o["upcoming"]) or "none") +
                            f"\nDue this week: " + ("; ".join(f"{x['text']} ({x.get('due') or 'no date'})" for x in o["due"]) or "nothing") +
                            f"\n{o['year']}: income {o['income']} (merch {o['merch_income']}), expenses {o['expenses']}, net {o['net']}" +
                            "\nUnpaid played gigs: " + ("; ".join(f"{g['date']} {g.get('venue')}" for g in o["unpaid"]) or "none") +
                            "\nLow stock: " + ("; ".join(f"{m['name']} {m.get('variant') or ''} ({m.get('stock')})" for m in o["low_stock"]) or "none"))
                if what not in SCHEMA:
                    return f"Unknown list {what!r}. Use one of: overview, " + ", ".join(SCHEMA)
                rs = rows(con, what)
                q = str(a.get("query") or "").lower().split()
                if q:
                    rs = [r for r in rs if all(w in json.dumps(r).lower() for w in q)]
                if what == "setlists":
                    return "\n".join(
                        f"#{s['id']} {s['name']}: " + ", ".join(x["title"] for x in setlist(con, s["id"])["songs"])
                        + f" ({setlist(con, s['id'])['total_sec'] // 60} min)" for s in rs[:30]) or "No setlists yet."
                return "\n".join(_line(what, r, con) for r in rs[:60]) or f"No {what} yet."
            if name == "band_save":
                t = str(a.get("table") or "")
                row = dict(a.get("fields") or {})
                if a.get("id"):
                    row["id"] = a["id"]
                r = save(con, t, row)
                return ("Changed " if a.get("id") else "Added ") + _line(_table(t), r, con)
            return "unknown band tool"
        except BandError as e:
            return f"Could not do that: {e}"
        finally:
            con.close()


def handle(body, db_path):
    body = body or {}
    op = body.get("op", "")
    with _lock:
        con = connect(db_path)
        try:
            if op == "overview":
                return {"ok": True, **overview(con)}
            if op == "list":
                return {"ok": True, "rows": rows(con, body.get("table"))}
            if op == "save":
                return {"ok": True, "row": save(con, body.get("table"), body.get("row") or {})}
            if op == "delete":
                set_deleted(con, body.get("table"), body.get("id"), True)
                return {"ok": True}
            if op == "restore":
                set_deleted(con, body.get("table"), body.get("id"), False)
                return {"ok": True}
            if op == "trash":
                return {"ok": True, "rows": {t: rows(con, t, include_deleted=True) for t in SCHEMA}}
            if op == "setlist":
                return {"ok": True, "setlist": setlist(con, body.get("id"))}
            if op == "setlist_songs":
                return {"ok": True, "setlist": set_setlist_songs(con, body.get("id"), body.get("songs") or [])}
            if op == "ics":
                return {"ok": True, "ics": gig_ics(con, body.get("id"))}
            if op == "schema":
                return {"ok": True, "schema": SCHEMA, "statuses": STATUSES}
            return {"ok": False, "msg": f"unknown op {op!r}"}
        except BandError as e:
            return {"ok": False, "msg": str(e)}
        except sqlite3.Error as e:
            return {"ok": False, "msg": f"The band file said no: {e}"}
        finally:
            con.close()
