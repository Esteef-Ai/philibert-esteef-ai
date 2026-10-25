"""Band Manager: a working band's records in one SQLite file on the drive.

  gigs, venues, contacts, songs, setlists (+ their songs, in order),
  merch (+ sales), money (income / expenses), reminders, tours (a run of gigs),
  suppliers (van hire, printers, PA...), bills (owed to them; paying one books
  the expense in money), and settings (the currency)

Backups: once a day, before the first change, the file is copied to
<data>/exports/Band backups (the last 14 are kept); BACK UP NOW and restore
work on the same folder, and a restore first backs up what it replaces.
Export: a zip of one CSV per list, for a spreadsheet or an accountant.

Nothing is ever deleted outright: delete marks a row deleted (the Trash view
lists them, restore brings them back). Philibert's chat and the Band Manager
page share this one file: <data>/band.db.

Entry point: handle(body, db_path) -> dict.
"""
import base64
import csv
import io
import json
import re
import sqlite3
import sys
import urllib.parse
import threading
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

# table -> column: type. Every table also has id, created, updated, deleted.
SCHEMA = {
    "contacts": {"name": "TEXT", "role": "TEXT", "phone": "TEXT", "email": "TEXT", "notes": "TEXT"},
    "venues": {"name": "TEXT", "address": "TEXT", "city": "TEXT", "capacity": "INTEGER",
               "contact_id": "INTEGER", "notes": "TEXT"},
    "gigs": {"date": "TEXT", "title": "TEXT", "venue_id": "INTEGER", "status": "TEXT", "fee": "REAL",
             "deposit_paid": "INTEGER", "load_in": "TEXT", "set_time": "TEXT", "set_length": "INTEGER",
             "setlist_id": "INTEGER", "contact_id": "INTEGER", "notes": "TEXT", "tour_id": "INTEGER"},
    "songs": {"title": "TEXT", "key": "TEXT", "bpm": "INTEGER", "length_sec": "INTEGER", "notes": "TEXT"},
    "setlists": {"name": "TEXT", "notes": "TEXT"},
    "merch": {"name": "TEXT", "variant": "TEXT", "price": "REAL", "cost": "REAL", "stock": "INTEGER", "notes": "TEXT",
              "supplier_id": "INTEGER"},
    "sales": {"date": "TEXT", "merch_id": "INTEGER", "gig_id": "INTEGER", "qty": "INTEGER", "price": "REAL"},
    "money": {"date": "TEXT", "kind": "TEXT", "amount": "REAL", "category": "TEXT", "gig_id": "INTEGER", "note": "TEXT",
              "tour_id": "INTEGER", "supplier_id": "INTEGER"},
    "reminders": {"due": "TEXT", "text": "TEXT", "done": "INTEGER", "gig_id": "INTEGER"},
    "tours": {"name": "TEXT", "starts": "TEXT", "ends": "TEXT", "notes": "TEXT"},
    "suppliers": {"name": "TEXT", "kind": "TEXT", "person": "TEXT", "phone": "TEXT", "email": "TEXT",
                  "website": "TEXT", "notes": "TEXT"},
    "bills": {"due": "TEXT", "what": "TEXT", "supplier_id": "INTEGER", "amount": "REAL", "category": "TEXT",
              "paid": "INTEGER", "paid_on": "TEXT", "money_id": "INTEGER", "gig_id": "INTEGER", "tour_id": "INTEGER",
              "note": "TEXT"},
}
STATUSES = ["idea", "hold", "confirmed", "played", "cancelled"]
REQUIRED = {"contacts": "name", "venues": "name", "gigs": "date", "songs": "title", "setlists": "name",
            "merch": "name", "money": "amount", "reminders": "text", "sales": "merch_id",
            "tours": "name", "suppliers": "name", "bills": "amount"}
CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD", "NZD", "JPY", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK",
              "MXN", "BRL", "ZAR", "INR", "KRW", "SGD", "HKD", "ILS", "TRY"]
SETTINGS = {"currency": "USD", "units": "imperial"}
UNITS = {"imperial": "feet and inches, pounds, miles", "metric": "metres and centimetres, kilograms, kilometres"}
KEEP_AUTO = 14
_lock = threading.Lock()


class BandError(Exception):
    pass


def _open(path, timeout=10):
    """sqlite3.connect, but on a Mac with dot-file locking: SQLite's usual byte-range
    locks fail on an exFAT drive there, so reads worked and every save failed
    (2026-10-25). The lock is then a folder beside the file, which any drive holds."""
    if sys.platform == "darwin":
        return sqlite3.connect(Path(path).resolve().as_uri() + "?vfs=unix-dotfile", uri=True, timeout=timeout)
    return sqlite3.connect(str(path), timeout=timeout)


def connect(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = _open(db_path)
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
    con.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)")
    return con


def settings(con):
    out = dict(SETTINGS)
    out.update({r[0]: r[1] for r in con.execute("SELECT k, v FROM settings")})
    return out


def set_settings(con, new):
    cur = str((new or {}).get("currency") or "").upper().strip()
    if cur:
        if not re.fullmatch(r"[A-Z]{3}", cur):
            raise BandError("the currency should be a 3-letter code, like USD, EUR or GBP")
        con.execute("INSERT OR REPLACE INTO settings VALUES ('currency', ?)", (cur,))
    units = str((new or {}).get("units") or "").lower().strip()
    if units:
        if units not in UNITS:
            raise BandError("measurements should be imperial or metric")
        con.execute("INSERT OR REPLACE INTO settings VALUES ('units', ?)", (units,))
    con.commit()
    return settings(con)


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
                out[c] = round(float(re.sub(r"[^\d.\-]", "", str(v).replace(",", "")) or "x"), 2)
            except (TypeError, ValueError):
                raise BandError(f"{c} should be a number")
        else:
            out[c] = str(v)[:4000]
    if t == "gigs" and out.get("status") and out["status"] not in STATUSES:
        out["status"] = "hold"
    if t == "money" and out.get("kind") not in (None, "income", "expense"):
        out["kind"] = "income"
    for c in ("date", "due", "starts", "ends", "paid_on"):
        if out.get(c):
            try:
                datetime.strptime(out[c][:10], "%Y-%m-%d")
            except ValueError:
                raise BandError(f"{c} should look like 2026-11-07")
    return out


def rows(con, t, include_deleted=False, where="", args=()):
    t = _table(t)
    order = {"gigs": "date", "reminders": "done, due", "money": "date DESC", "sales": "date DESC",
             "tours": "starts DESC", "bills": "paid, due"}.get(t, "name" if "name" in SCHEMA[t] else "title")
    q = f"SELECT * FROM {t} WHERE " + ("deleted = 1" if include_deleted else "deleted = 0") + (f" AND {where}" if where else "")
    return [dict(r) for r in con.execute(q + f" ORDER BY {order}", args)]


def save(con, t, row):
    t = _table(t)
    data = _clean(t, row or {})
    data.pop("money_id", None)                    # only paying a bill sets this
    rid = row.get("id")
    was = dict(con.execute("SELECT * FROM bills WHERE id = ?", (rid,)).fetchone() or {}) if t == "bills" and rid else {}
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
    if t == "bills":
        _bill_money(con, rid, was)
    con.commit()
    return dict(con.execute(f"SELECT * FROM {t} WHERE id = ?", (rid,)).fetchone())


def _bill_money(con, bid, was):
    """A paid bill has one expense in money; un-paying it puts that expense in the Trash."""
    b = dict(con.execute("SELECT * FROM bills WHERE id = ?", (bid,)).fetchone())
    now = time.time()
    if b.get("paid") and not b.get("money_id"):
        paid_on = b.get("paid_on") or date.today().isoformat()
        sup = con.execute("SELECT name FROM suppliers WHERE id = ?", (b.get("supplier_id"),)).fetchone()
        note = " - ".join(x for x in (sup[0] if sup else "", b.get("what") or "") if x) or "Bill"
        mid = con.execute("INSERT INTO money (date, kind, amount, category, gig_id, tour_id, supplier_id, note, created, updated) "
                          "VALUES (?, 'expense', ?, ?, ?, ?, ?, ?, ?, ?)",
                          (paid_on, b.get("amount") or 0, b.get("category") or "Bill", b.get("gig_id"), b.get("tour_id"),
                           b.get("supplier_id"), note, now, now)).lastrowid
        con.execute("UPDATE bills SET money_id = ?, paid_on = ? WHERE id = ?", (mid, paid_on, bid))
    elif not b.get("paid") and b.get("money_id"):
        con.execute("UPDATE money SET deleted = 1, updated = ? WHERE id = ?", (now, b["money_id"]))
        con.execute("UPDATE bills SET money_id = NULL, paid_on = NULL WHERE id = ?", (bid,))
    elif b.get("paid") and b.get("money_id") and (b.get("amount"), b.get("paid_on")) != (was.get("amount"), was.get("paid_on")):
        con.execute("UPDATE money SET amount = ?, date = COALESCE(?, date), updated = ? WHERE id = ?",
                    (b.get("amount") or 0, b.get("paid_on"), now, b["money_id"]))


def tour(con, tid):
    """One tour: its gigs, and what it brought in, cost and kept."""
    tr = con.execute("SELECT * FROM tours WHERE id = ?", (tid,)).fetchone()
    if not tr:
        raise BandError("no such tour")
    gigs = [dict(r) for r in con.execute(
        "SELECT gigs.*, venues.name AS venue, venues.city FROM gigs LEFT JOIN venues ON venues.id = gigs.venue_id "
        "WHERE gigs.deleted = 0 AND gigs.tour_id = ? ORDER BY gigs.date", (tid,))]
    ids = [g["id"] for g in gigs] or [-1]
    mark = ",".join("?" * len(ids))
    cash = [dict(r) for r in con.execute(
        f"SELECT * FROM money WHERE deleted = 0 AND (tour_id = ? OR gig_id IN ({mark}))", [tid] + ids)]
    inc = sum(m["amount"] or 0 for m in cash if m["kind"] == "income")
    exp = sum(m["amount"] or 0 for m in cash if m["kind"] == "expense")
    merch = con.execute(f"SELECT COALESCE(SUM(qty * price), 0) FROM sales WHERE deleted = 0 AND gig_id IN ({mark})", ids).fetchone()[0]
    owed = con.execute("SELECT COALESCE(SUM(amount), 0) FROM bills WHERE deleted = 0 AND COALESCE(paid, 0) = 0 "
                       f"AND (tour_id = ? OR gig_id IN ({mark}))", [tid] + ids).fetchone()[0]
    live = [g for g in gigs if g.get("status") != "cancelled"]
    t = dict(tr)
    return {**t, "gigs": gigs, "starts": t.get("starts") or (live[0]["date"] if live else None),
            "ends": t.get("ends") or (live[-1]["date"] if live else None),
            "fees": round(sum(g.get("fee") or 0 for g in live), 2), "income": round(inc + merch, 2),
            "merch_income": round(merch, 2), "expenses": round(exp, 2), "owed": round(owed, 2),
            "net": round(inc + merch - exp, 2)}


def set_deleted(con, t, rid, flag):
    t = _table(t)
    n = con.execute(f"UPDATE {t} SET deleted = ?, updated = ? WHERE id = ?", (1 if flag else 0, time.time(), rid)).rowcount
    con.commit()
    if not n:
        raise BandError("no such entry")


def purge(con, t=None, rid=None):
    """Delete Trash rows for good: one (t, rid) or every deleted row. Rows elsewhere that
    pointed at them lose the link (set to empty) instead of pointing at nothing."""
    targets = [(_table(t), int(rid))] if t else [(tb, r[0]) for tb in SCHEMA
                                                  for r in con.execute(f"SELECT id FROM {tb} WHERE deleted = 1")]
    n = 0
    for tb, i in targets:
        n += con.execute(f"DELETE FROM {tb} WHERE id = ? AND deleted = 1", (i,)).rowcount
        col = {"setlists": "setlist_id", "songs": "song_id"}.get(tb)
        if col:
            con.execute(f"DELETE FROM setlist_songs WHERE {col} = ?", (i,))
        ref = {"money": "money_id", "merch": "merch_id"}.get(tb, tb[:-1] + "_id")   # gigs -> gig_id ...
        for other, cols in SCHEMA.items():
            if ref in cols:
                con.execute(f'UPDATE {other} SET "{ref}" = NULL WHERE "{ref}" = ?', (i,))
    con.commit()
    if t and not n:
        raise BandError("not in the trash")
    return n


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
    bills = [dict(r) for r in con.execute(
        "SELECT bills.*, suppliers.name AS supplier FROM bills LEFT JOIN suppliers ON suppliers.id = bills.supplier_id "
        "WHERE bills.deleted = 0 AND COALESCE(bills.paid, 0) = 0 AND (bills.due IS NULL OR bills.due <= ?) ORDER BY bills.due",
        ((today + timedelta(days=14)).isoformat(),))]
    tours = [tour(con, r[0]) for r in con.execute("SELECT id FROM tours WHERE deleted = 0")]
    tours = sorted((x for x in tours if (x.get("ends") or "9999") >= t0), key=lambda x: x.get("starts") or "9999")
    tours = [{**{k: v for k, v in x.items() if k != "gigs"}, "gig_count": len(x["gigs"])} for x in tours[:3]]
    return {"upcoming": upcoming, "due": due, "year": year, "bills_due": bills, "tours": tours,
            "currency": settings(con)["currency"], "units": settings(con)["units"], "income": round(inc + merch_in, 2), "expenses": round(exp, 2),
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
    maps = ("https://www.google.com/maps/dir/?api=1&destination=" + urllib.parse.quote(where)
            if g.get("address") or g.get("city") else "")
    desc = "\n".join(x for x in (f"Load-in {g['load_in']}" if g.get("load_in") else "",
                                  f"Set {g['set_time']}" if g.get("set_time") else "", g.get("notes") or "",
                                  f"Directions: {maps}" if maps else "") if x)
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Esteef.Ai//Philibert Band Manager//EN\r\nBEGIN:VEVENT\r\n"
            f"UID:philibert-gig-{gid}@esteef.ai\r\nDTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}\r\n{times}\r\n"
            f"SUMMARY:{esc(g.get('title') or ('Gig at ' + (g.get('venue') or 'TBA')))}\r\n"
            + (f"LOCATION:{esc(where)}\r\n" if where else "") + (f"URL:{maps}\r\n" if maps else "") + (f"DESCRIPTION:{esc(desc)}\r\n" if desc else "")
            + "END:VEVENT\r\nEND:VCALENDAR\r\n")


def _backup_dir(db_path):
    return Path(db_path).parent / "exports" / "Band backups"


def backup(con, db_path, auto=False):
    """A copy of the band file in the backups folder (SQLite's own copy, safe while open)."""
    d = _backup_dir(db_path)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H%M%S")
    dst = d / (f"auto {stamp}.db" if auto else f"band {stamp}.db")
    n = 2
    while dst.exists():
        dst = dst.with_name(dst.stem.split(" (")[0] + f" ({n}).db")
        n += 1
    out = _open(dst)
    try:
        con.backup(out)
    finally:
        out.close()
    if auto:
        for old in sorted(d.glob("auto *.db"))[:-KEEP_AUTO]:
            old.unlink()
    return dst.name


def backups(db_path):
    d = _backup_dir(db_path)
    if not d.is_dir():
        return []
    return [{"name": p.name, "size": p.stat().st_size, "auto": p.name.startswith("auto "), "when": p.stat().st_mtime}
            for p in sorted(d.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)]


def daily_backup(con, db_path):
    """Before the first change of the day: one copy, if there is anything to keep."""
    if not any(con.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() for t in SCHEMA):
        return None
    if any(_backup_dir(db_path).glob(f"auto {date.today().isoformat()} *.db")):
        return None
    return backup(con, db_path, auto=True)


def restore_backup(con, db_path, name):
    if not any(b["name"] == name for b in backups(db_path)):    # only a file the list showed: no paths
        raise BandError("no such backup")
    src = _open(_backup_dir(db_path) / name)
    try:
        if src.execute("SELECT name FROM sqlite_master WHERE name = 'gigs'").fetchone() is None:
            raise BandError("that file is not a band backup")
        saved = backup(con, db_path)              # what is replaced can come back too
        src.backup(con)
    finally:
        src.close()
    connect(db_path).close()                      # an older backup gets today's columns
    return saved


def export_zip(con):
    """One CSV per list (the Trash left out), for a spreadsheet or an accountant."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for t, cols in SCHEMA.items():
            s = io.StringIO()
            w = csv.writer(s)
            names = ["id"] + list(cols)
            w.writerow(names)
            for r in rows(con, t):
                w.writerow(["" if r.get(c) is None else r.get(c) for c in names])
            z.writestr(f"{t}.csv", "\ufeff" + s.getvalue())        # the BOM makes Excel read it as UTF-8
        z.writestr("settings.json", json.dumps(settings(con), indent=2))
    return buf.getvalue()


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
                            "\nLow stock: " + ("; ".join(f"{m['name']} {m.get('variant') or ''} ({m.get('stock')})" for m in o["low_stock"]) or "none") +
                            "\nBills due in 14 days: " + ("; ".join(f"{b.get('supplier') or b.get('what') or 'bill'} {b['amount']} ({b.get('due') or 'no date'})"
                                                                     for b in o["bills_due"]) or "none") +
                            "\nTours: " + ("; ".join(f"#{x['id']} {x['name']} {x.get('starts') or '?'}..{x.get('ends') or '?'}, "
                                                      f"{x['gig_count']} gigs, net {x['net']}" for x in o["tours"]) or "none") +
                            f"\nAll money is in {o['currency']}. Measurements and weights: {o['units']} "
                            f"({UNITS.get(o['units'], '')}).")
                if what == "tours" and a.get("id"):
                    x = tour(con, int(a["id"]))
                    return (f"Tour #{x['id']} {x['name']} {x.get('starts')}..{x.get('ends')}: fees {x['fees']}, in {x['income']}, "
                            f"out {x['expenses']}, owed {x['owed']}, net {x['net']}\n" + "\n".join(_line("gigs", g, con) for g in x["gigs"]))
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
                daily_backup(con, db_path)
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
        try:
            con = connect(db_path)
        except sqlite3.Error as e:                   # opening it is where a drive's locking fails
            return {"ok": False, "msg": f"Could not open the band file: {e}"}
        try:
            if op in ("save", "delete", "restore", "setlist_songs", "settings_save"):
                daily_backup(con, db_path)
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
            if op == "purge":
                return {"ok": True, "deleted": purge(con, body.get("table"), body.get("id"))}
            if op == "setlist":
                return {"ok": True, "setlist": setlist(con, body.get("id"))}
            if op == "setlist_songs":
                return {"ok": True, "setlist": set_setlist_songs(con, body.get("id"), body.get("songs") or [])}
            if op == "ics":
                return {"ok": True, "ics": gig_ics(con, body.get("id"))}
            if op == "schema":
                return {"ok": True, "schema": SCHEMA, "statuses": STATUSES, "currencies": CURRENCIES}
            if op == "tour":
                return {"ok": True, "tour": tour(con, body.get("id"))}
            if op == "settings":
                return {"ok": True, "settings": settings(con), "currencies": CURRENCIES, "units": UNITS}
            if op == "settings_save":
                return {"ok": True, "settings": set_settings(con, body.get("settings"))}
            if op == "backup":
                return {"ok": True, "name": backup(con, db_path), "backups": backups(db_path)}
            if op == "backups":
                return {"ok": True, "backups": backups(db_path)}
            if op == "restore_backup":
                saved = restore_backup(con, db_path, str(body.get("name") or ""))
                return {"ok": True, "saved": saved, "backups": backups(db_path)}
            if op == "export":
                return {"ok": True, "name": f"Band Manager {date.today().isoformat()}.zip",
                        "zip": base64.b64encode(export_zip(con)).decode("ascii")}
            return {"ok": False, "msg": f"unknown op {op!r}"}
        except BandError as e:
            return {"ok": False, "msg": str(e)}
        except sqlite3.Error as e:
            return {"ok": False, "msg": f"The band file said no: {e}"}
        finally:
            con.close()
