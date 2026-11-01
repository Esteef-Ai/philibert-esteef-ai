"""One person's Philibert on several computers: notes and app data kept in step, over Tailscale.

The big computer (the one that shares its models, nd_modelshare) can also share its notes
and app data. The other computers keep their own copy and sync both ways with it whenever
they can reach it, so each one works offline and nothing passes through anyone's server.

    the hub      serve(areas, op, body)   answers over the model-sharing relay, same address
                                          and key: /<key>/sync/<op>. Off unless turned on.
    a laptop     sync_once(address, areas, state_path, me)   every 5 minutes and on demand.

What is kept in step (Areas):
  folders   the notes vault and Yo Teach's documents, file by file.
  databases Yo Teach and every Band Manager band, row by row. Each row gets a `uid`
            the first time it is synced, so ids made on two computers never clash;
            links between rows (a note's student, a gig's venue) travel as uids.
  settings  the apps' settings, except which model to use (that differs per computer).

How a change wins: the laptop remembers what both sides looked like after the last sync
(state_path). A side that changed since then wins over one that did not.
  - Both changed a note: the hub's version stays at its name and the laptop's is kept
    beside it as "name (conflict laptop-name 2026-10-31).md" on both. Two copies of a
    memory Philibert wrote itself (nd_generated: true) are not kept: the newer one wins.
  - Both changed a row: the one changed last (its `updated`) wins.
  - A note deleted on one side is moved to .sync-trash/<date>/ on the other, not deleted.
    A file replaced by a sync goes there too. Kept 30 days.
  - A row removed for good (emptied from the Trash) is removed on the other side only if it
    is in the Trash there too. Nothing live is ever removed by a sync.
Every write checks the file or row is still what the laptop saw a moment ago; one that
changed in between is left for the next sync.

Stdlib only.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import threading
import time
import urllib.request
import uuid
from datetime import date, datetime
from pathlib import Path

MAX_FILE = 20 * 1024 * 1024                    # bigger files are not synced
BATCH = 8 * 1024 * 1024                        # bytes of files fetched in one request
TRASH = ".sync-trash"
TRASH_DAYS = 30
NO_SYNC_SETTING = re.compile(r"model", re.I)   # writer_model, vision_model...: per computer
_GENERATED = re.compile(rb"^nd_generated:\s*true\s*$", re.M | re.I)
_hash_cache = {}
_lock = threading.Lock()


class SyncError(Exception):
    pass


def _h(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def device_name():
    return re.sub(r"[^\w .-]", "", socket.gethostname())[:40] or "other computer"


# ---------------------------------------------------------------------------
# folders
# ---------------------------------------------------------------------------
def _skip_name(name):
    return name.startswith((".", "~$")) or name.endswith((".tmp", ".part", ".sync-tmp"))


def scan(root):
    """{relative/path: [sha1, mtime]} of every file under root that syncs."""
    root = Path(root)
    out = {}
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]   # .obsidian, .trash, .sync-trash
        for fn in filenames:
            if _skip_name(fn):
                continue
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_size > MAX_FILE:
                continue
            key = (str(p), st.st_mtime_ns, st.st_size)
            h = _hash_cache.get(key)
            if h is None:
                try:
                    h = hashlib.sha1(p.read_bytes()).hexdigest()
                except OSError:
                    continue
                _hash_cache[key] = h
            out[p.relative_to(root).as_posix()] = [h, st.st_mtime]
    return out


def _safe(root, rel):
    """root/rel, refusing anything that would leave root or touch a hidden folder."""
    rel = str(rel or "").replace("\\", "/")
    parts = rel.split("/")
    if not rel or rel.startswith("/") or ":" in rel or any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        raise SyncError(f"not a path inside the folder: {rel!r}")
    return Path(root).joinpath(*parts)


def _file_hash(p):
    try:
        return hashlib.sha1(Path(p).read_bytes()).hexdigest()
    except OSError:
        return None


def _to_trash(root, p):
    rel = Path(p).relative_to(root)
    dest = Path(root) / TRASH / date.today().isoformat() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = 1
    while dest.exists():
        n += 1
        dest = dest.with_name(f"{rel.stem} ({n}){rel.suffix}")
    shutil.move(str(p), str(dest))


def read_files(root, rels):
    out = {}
    for rel in rels:
        try:
            out[rel] = base64.b64encode(_safe(root, rel).read_bytes()).decode()
        except (OSError, SyncError):
            out[rel] = None
    return out


def write_file(root, rel, data, expect):
    """Write rel if it is still `expect` (None = must not exist). The version it replaces
    goes to the sync trash. True when written."""
    p = _safe(root, rel)
    if _file_hash(p) != expect:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".sync-tmp")
    tmp.write_bytes(data)
    if expect is not None:
        _to_trash(root, p)
    os.replace(tmp, p)
    return True


def trash_file(root, rel, expect):
    p = _safe(root, rel)
    if expect is None or _file_hash(p) != expect:
        return False
    _to_trash(root, p)
    return True


def prune_trash(root, days=TRASH_DAYS):
    t = Path(root) / TRASH
    if not t.is_dir():
        return
    cutoff = time.time() - days * 86400
    for d in t.iterdir():
        try:
            if d.is_dir() and datetime.strptime(d.name, "%Y-%m-%d").timestamp() < cutoff:
                shutil.rmtree(d)
        except (ValueError, OSError):
            continue


def _conflict_name(rel, who):
    p = Path(rel)
    return (p.parent / f"{p.stem} (conflict {who} {date.today().isoformat()}){p.suffix}").as_posix()


# ---------------------------------------------------------------------------
# databases
# ---------------------------------------------------------------------------
def _cols(con, t):
    return [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]


def layout(con):
    """({table: cols} of tables with rows to sync, {table: cols} of link tables)."""
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
             if not r[0].startswith(("sqlite_", "_"))]
    synced, links = {}, {}
    for t in names:
        cols = _cols(con, t)
        if {"id", "updated", "deleted"} <= set(cols):
            synced[t] = cols
        elif t != "settings" and cols and "id" not in cols and cols[0].endswith("_id"):
            links[t] = cols                   # class_students, setlist_songs: first column is the owner
    return synced, links


def _target(col, synced):
    """The table a *_id column points at: student_id -> students, class_id -> classes."""
    if not col.endswith("_id"):
        return None
    base = col[:-3]
    for t in (base, base + "s", base + "es"):
        if t in synced:
            return t
    return None


def ensure_uids(con):
    synced, _ = layout(con)
    for t, cols in synced.items():
        if "uid" not in cols:
            con.execute(f'ALTER TABLE "{t}" ADD COLUMN uid TEXT')
        for (rid,) in con.execute(f'SELECT id FROM "{t}" WHERE uid IS NULL OR uid = ""').fetchall():
            con.execute(f'UPDATE "{t}" SET uid = ? WHERE id = ?', (uuid.uuid4().hex, rid))
        con.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS "_uid_{t}" ON "{t}" (uid)')
    con.commit()


def _rel_path(v, root):
    if v and root:
        try:
            return "@/" + Path(v).resolve().relative_to(Path(root).resolve()).as_posix()
        except (ValueError, OSError):
            pass
    return v


def _abs_path(v, root):
    if isinstance(v, str) and v.startswith("@/") and root:
        return str(Path(root).joinpath(*v[2:].split("/")))
    return v


def dump(con, paths=None, roots=None):
    """Everything to sync in one database, ids replaced by uids:
    {"rows": {table: {uid: row}}, "links": {table: {owner uid: [row, ...]}}, "settings": {k: v}}."""
    paths, roots = paths or {}, roots or {}
    synced, links = layout(con)
    uids = {t: dict(con.execute(f'SELECT id, uid FROM "{t}"').fetchall()) for t in synced}
    out = {"rows": {}, "links": {}, "settings": {}}
    for t, cols in synced.items():
        fk = {c: _target(c, synced) for c in cols}
        pc = paths.get(t, {})
        rows = {}
        for r in con.execute(f'SELECT * FROM "{t}"'):
            r = dict(zip(cols, r))
            row = {}
            for c in cols:
                if c in ("id", "uid"):
                    continue
                v = r[c]
                if fk[c] and v is not None:
                    v = uids[fk[c]].get(v)
                elif c in pc:
                    v = _rel_path(v, roots.get(pc[c]))
                row[c] = v
            rows[r["uid"]] = row
        out["rows"][t] = rows
    for t, cols in links.items():
        fk = {c: _target(c, synced) for c in cols}
        groups = {}
        for r in con.execute(f'SELECT * FROM "{t}"'):
            r = dict(zip(cols, r))
            owner = uids.get(fk[cols[0]], {}).get(r[cols[0]]) if fk[cols[0]] else None
            if not owner:
                continue
            groups.setdefault(owner, []).append(
                {c: (uids[fk[c]].get(r[c]) if fk[c] and r[c] is not None else r[c]) for c in cols[1:]})
        out["links"][t] = {k: sorted(v, key=lambda x: json.dumps(x, sort_keys=True, default=str))
                           for k, v in groups.items()}
    if "settings" in [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]:
        out["settings"] = {k: v for k, v in con.execute("SELECT k, v FROM settings") if not NO_SYNC_SETTING.search(k)}
    return out


def apply(con, change, paths=None, roots=None):
    """Make the changes the other side decided on, each only if what it replaces is still
    what was seen (its hash). change = {"rows": {t: {uid: [expect, row or None]}},
    "links": {t: {owner: [expect, rows]}}, "settings": {k: [expect, v or None]}}.
    Returns the keys done: {"rows": {t: [uid]}, "links": {t: [owner]}, "settings": [k]}."""
    paths, roots = paths or {}, roots or {}
    done = {"rows": {}, "links": {}, "settings": []}
    con.execute("BEGIN IMMEDIATE")
    try:
        cur = dump(con, paths, roots)
        synced, links = layout(con)
        later = []                              # (table, uid, {fk col: uid}) once every row exists
        for t, items in (change.get("rows") or {}).items():
            if t not in synced:
                continue
            cols = set(synced[t]) - {"id", "uid"}
            pc = paths.get(t, {})
            for u, (expect, row) in items.items():
                have = cur["rows"].get(t, {}).get(u)
                if (_h(have) if have is not None else None) != expect:
                    continue
                if row is None:
                    if have and have.get("deleted"):
                        con.execute(f'DELETE FROM "{t}" WHERE uid = ?', (u,))
                        done["rows"].setdefault(t, []).append(u)
                    continue
                data, refs = {}, {}
                for c, v in row.items():
                    if c not in cols:
                        continue
                    if _target(c, synced):
                        refs[c] = v
                    else:
                        data[c] = _abs_path(v, roots.get(pc[c])) if c in pc else v
                if have is None:
                    ks = ["uid"] + list(data)
                    con.execute(f'INSERT INTO "{t}" (' + ", ".join(f'"{k}"' for k in ks) + ") VALUES ("
                                + ", ".join("?" * len(ks)) + ")", [u] + list(data.values()))
                elif data:
                    con.execute(f'UPDATE "{t}" SET ' + ", ".join(f'"{k}" = ?' for k in data) + " WHERE uid = ?",
                                list(data.values()) + [u])
                later.append((t, u, refs))
                done["rows"].setdefault(t, []).append(u)
        ids = {t: {u: i for i, u in con.execute(f'SELECT id, uid FROM "{t}"')} for t in synced}
        for t, u, refs in later:
            if refs:
                vals = [ids[_target(c, synced)].get(v) if v else None for c, v in refs.items()]
                con.execute(f'UPDATE "{t}" SET ' + ", ".join(f'"{c}" = ?' for c in refs) + " WHERE uid = ?", vals + [u])
        for t, items in (change.get("links") or {}).items():
            if t not in links:
                continue
            cols = links[t]
            owner_t = _target(cols[0], synced)
            for owner, (expect, rows) in items.items():
                if _h(cur["links"].get(t, {}).get(owner, [])) != expect:
                    continue
                oid = ids.get(owner_t, {}).get(owner)
                if oid is None:
                    continue
                con.execute(f'DELETE FROM "{t}" WHERE "{cols[0]}" = ?', (oid,))
                for r in rows or []:
                    vals = []
                    for c in cols[1:]:
                        tt = _target(c, synced)
                        vals.append(ids[tt].get(r.get(c)) if tt and r.get(c) else r.get(c))
                    if any(_target(c, synced) and v is None for c, v in zip(cols[1:], vals)):
                        continue                # points at a row this side does not have
                    con.execute(f'INSERT INTO "{t}" VALUES (' + ", ".join("?" * len(cols)) + ")", [oid] + vals)
                done["links"].setdefault(t, []).append(owner)
        if change.get("settings"):
            con.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)")
            for k, (expect, v) in change["settings"].items():
                if NO_SYNC_SETTING.search(k) or cur["settings"].get(k) != expect:
                    continue
                if v is None:
                    con.execute("DELETE FROM settings WHERE k = ?", (k,))
                else:
                    con.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (k, v))
                done["settings"].append(k)
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return done


def adopt(con, local, remote, base, keys):
    """First sync of two installs that both have Student A: give the local row the hub's
    uid, so they become one row instead of two. Only rows neither side has synced before."""
    n = 0
    for t, kcols in (keys or {}).items():
        lr, rr, br = local["rows"].get(t, {}), remote["rows"].get(t, {}), base.get("rows", {}).get(t, {})
        def key(row):
            return tuple(str(row.get(c) or "").strip().lower() for c in kcols)
        free = {}
        for u, row in lr.items():
            if u not in rr and u not in br and any(key(row)):
                free.setdefault(key(row), u)
        for u, row in rr.items():
            if u in lr or u in br:
                continue
            mine = free.pop(key(row), None)
            if mine:
                con.execute(f'UPDATE "{t}" SET uid = ? WHERE uid = ?', (u, mine))
                n += 1
    if n:
        con.commit()
    return n


# ---------------------------------------------------------------------------
# what syncs on a Philibert
# ---------------------------------------------------------------------------
class Areas:
    """folders(): {name: Path}; dbs(): {name: {path, connect, keys, paths, meta}};
    ensure_db(name, meta) -> Path or None (makes room for a database the other side has)."""

    def __init__(self, folders=None, dbs=None):
        self._folders, self._dbs = folders or {}, dbs or {}

    def folders(self):
        return dict(self._folders)

    def dbs(self):
        return dict(self._dbs)

    def ensure_db(self, name, meta):
        d = self._dbs.get(name)
        return Path(d["path"]) if d else None


class PhilibertAreas(Areas):
    def __init__(self, data_dir, vault_dir, docs_dir):
        super().__init__()
        self.data, self.vault, self.docs = Path(data_dir), Path(vault_dir) if vault_dir else None, Path(docs_dir)

    def folders(self):
        out = {"yoteach-docs": self.docs}
        if self.vault:
            out["notes"] = self.vault
        return out

    def dbs(self):
        import nd_band
        import nd_bands
        import nd_yoteach
        out = {"yoteach": {"path": self.data / "yoteach.db", "connect": nd_yoteach.connect, "keys": nd_yoteach.SYNC_KEYS,
                           "paths": {"docs": {"docx": "yoteach-docs", "pdf": "yoteach-docs"}}, "meta": {}}}
        for b in nd_bands.registry(self.data)["bands"]:
            out["band:" + b["id"]] = {"path": self.data / b["db"], "connect": nd_band.connect, "keys": nd_band.SYNC_KEYS,
                                      "paths": {}, "meta": {"name": b["name"]}}
        return out

    def ensure_db(self, name, meta):
        if name == "yoteach":
            return self.data / "yoteach.db"
        if not name.startswith("band:"):
            return None
        import nd_bands
        bid = name[5:]
        if not re.fullmatch(r"[\w-]{1,40}", bid):
            return None
        r = nd_bands.registry(self.data)
        for b in r["bands"]:
            if b["id"] == bid:
                return self.data / b["db"]
        b = {"id": bid, "name": str((meta or {}).get("name") or "Band")[:60], "db": f"bands/{bid}.db",
             "board_group": "", "created": time.time()}
        r["bands"].append(b)
        nd_bands._save(self.data, r)
        return self.data / b["db"]


def _open(d, path=None):
    con = d["connect"](path or d["path"])
    con.row_factory = None
    ensure_uids(con)
    return con


def _roots(areas):
    return {k: str(v) for k, v in areas.folders().items()}


# ---------------------------------------------------------------------------
# the hub's side
# ---------------------------------------------------------------------------
def serve(areas, op, body, device_id=""):
    body = body or {}
    folders = areas.folders()
    if op == "manifest":
        dbs = {}
        for name, d in areas.dbs().items():
            if not Path(d["path"]).exists():
                continue
            con = _open(d)
            try:
                dbs[name] = {"meta": d.get("meta") or {}, "dump": dump(con, d.get("paths"), _roots(areas))}
            finally:
                con.close()
        return {"ok": True, "device": device_id, "name": device_name(),
                "folders": {k: scan(v) for k, v in folders.items()}, "dbs": dbs}
    if op in ("files", "put", "trash"):
        root = folders.get(str(body.get("folder")))
        if not root:
            raise SyncError("no such folder")
        if op == "files":
            return {"ok": True, "files": read_files(root, list(body.get("rels") or [])[:500])}
        if op == "put":
            ok = write_file(root, body.get("rel"), base64.b64decode(body.get("b64") or ""), body.get("expect"))
        else:
            ok = trash_file(root, body.get("rel"), body.get("expect"))
        return {"ok": True, "done": ok}
    if op == "apply":
        name = str(body.get("db") or "")
        d = areas.dbs().get(name)
        if not d:
            path = areas.ensure_db(name, body.get("meta"))
            d = areas.dbs().get(name) if path else None
        if not d:
            raise SyncError("no such database")
        con = _open(d)
        try:
            return {"ok": True, "done": apply(con, body.get("change") or {}, d.get("paths"), _roots(areas))}
        finally:
            con.close()
    raise SyncError(f"unknown sync step {op!r}")


# ---------------------------------------------------------------------------
# the laptop's side
# ---------------------------------------------------------------------------
def _call(address, op, body=None, timeout=300):
    req = urllib.request.Request(address.rstrip("/") + "/sync/" + op, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    if not out.get("ok"):
        raise SyncError(out.get("msg") or f"the other computer refused {op}")
    return out


def _load(state_path):
    try:
        return json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state_path, state):
    p = Path(state_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, p)


def _generated(data):
    return bool(data) and bool(_GENERATED.search(data[:2000]))


def sync_folder(call, name, root, remote, base, who):
    """One folder. Returns (new base {rel: hash}, counts)."""
    root = Path(root)
    local = scan(root)
    n = {"sent": 0, "got": 0, "trashed": 0, "conflicts": 0, "waiting": 0}
    new = {}
    pull, plan = [], []
    for rel in sorted(set(local) | set(remote) | set(base)):
        l = local.get(rel, [None])[0]
        r = remote.get(rel, [None])[0]
        b = base.get(rel)
        if l == r:
            if l:
                new[rel] = l
        elif l == b:
            plan.append(("trash_here" if r is None else "pull", rel, l, r))
            if r is not None:
                pull.append(rel)
        elif r == b:
            plan.append(("trash_there" if l is None else "push", rel, l, r))
        elif l is None:
            plan.append(("pull", rel, l, r))
            pull.append(rel)
        elif r is None:
            plan.append(("push", rel, l, r))
        else:
            plan.append(("conflict", rel, l, r))
            pull.append(rel)
    got = {}
    batch, size = [], 0
    for rel in pull:
        batch.append(rel)
        size += 1024
        if len(batch) >= 200 or size >= BATCH:
            got.update(call("files", {"folder": name, "rels": batch})["files"])
            batch, size = [], 0
    if batch:
        got.update(call("files", {"folder": name, "rels": batch})["files"])

    def push(rel, data, expect):
        return call("put", {"folder": name, "rel": rel, "b64": base64.b64encode(data).decode(), "expect": expect})["done"]

    for kind, rel, l, r in plan:
        try:
            if kind == "trash_here":
                ok = trash_file(root, rel, l)
                n["trashed"] += ok
            elif kind == "trash_there":
                ok = call("trash", {"folder": name, "rel": rel, "expect": r})["done"]
                n["trashed"] += ok
            elif kind == "pull":
                data = base64.b64decode(got.get(rel) or "") if got.get(rel) is not None else None
                ok = data is not None and hashlib.sha1(data).hexdigest() == r and write_file(root, rel, data, l)
                n["got"] += ok
            elif kind == "push":
                data = _safe(root, rel).read_bytes()
                ok = hashlib.sha1(data).hexdigest() == l and push(rel, data, r)
                n["sent"] += ok
            else:
                theirs = base64.b64decode(got.get(rel) or "") if got.get(rel) is not None else None
                mine = _safe(root, rel).read_bytes()
                if theirs is None or hashlib.sha1(theirs).hexdigest() != r or hashlib.sha1(mine).hexdigest() != l:
                    ok = False
                elif _generated(mine) and _generated(theirs):
                    # Philibert's own memories: one fact each, so the newer one is the fact
                    if local[rel][1] > remote[rel][1]:
                        ok = push(rel, mine, r)
                        r = l
                    else:
                        ok = write_file(root, rel, theirs, l)
                else:
                    other = _conflict_name(rel, who)
                    ok = (write_file(root, other, mine, None) and push(other, mine, None)
                          and write_file(root, rel, theirs, l))
                    if ok:
                        new[other] = l
                    n["conflicts"] += 1
                if ok:
                    l = r
            if ok:
                if kind in ("trash_here", "trash_there"):
                    pass
                elif kind == "push":
                    new[rel] = l
                else:
                    new[rel] = r
            else:
                n["waiting"] += 1
                if b := base.get(rel):
                    new[rel] = b
        except (OSError, SyncError):
            n["waiting"] += 1
            if base.get(rel):
                new[rel] = base[rel]
    return new, n


def _decide(lrow, rrow, b):
    """Which way a row (or link set, or setting) goes: None, "here" (take the hub's)
    or "there" (send ours)."""
    l = _h(lrow) if lrow is not None else None
    r = _h(rrow) if rrow is not None else None
    if l == r:
        return None, l, r
    if l == b:
        return "here", l, r
    if r == b:
        return "there", l, r
    if lrow is None:
        return "here", l, r
    if rrow is None:
        return "there", l, r
    if isinstance(lrow, dict) and float(lrow.get("updated") or 0) > float(rrow.get("updated") or 0):
        return "there", l, r
    return "here", l, r


def sync_db(call, name, d, remote, base, roots):
    """One database. Returns (new base, counts)."""
    path = Path(d["path"])
    con = _open(d, path)
    n = {"sent": 0, "got": 0, "waiting": 0}
    try:
        empty = {"rows": {}, "links": {}, "settings": {}}
        remote = remote or empty
        local = dump(con, d.get("paths"), roots)
        if adopt(con, local, remote, base, d.get("keys")):
            local = dump(con, d.get("paths"), roots)
        here = {"rows": {}, "links": {}, "settings": {}}
        there = {"rows": {}, "links": {}, "settings": {}}
        result = {"rows": {}, "links": {}, "settings": {}}   # the hash each key ends at, if applied
        owner_way = {}                          # uid -> which way its row went, for its links
        for t in sorted(set(local["rows"]) | set(remote["rows"])):
            lr, rr, br = local["rows"].get(t, {}), remote["rows"].get(t, {}), base.get("rows", {}).get(t, {})
            for u in set(lr) | set(rr) | set(br):
                way, l, r = _decide(lr.get(u), rr.get(u), br.get(u))
                lrow, rrow = lr.get(u), rr.get(u)
                # never remove a live row: copy it back instead
                if way == "here" and rrow is None and lrow is not None and not lrow.get("deleted"):
                    way = "there"
                elif way == "there" and lrow is None and rrow is not None and not rrow.get("deleted"):
                    way = "here"
                owner_way[u] = way
                if way == "here":
                    here["rows"].setdefault(t, {})[u] = [l, rrow]
                    result["rows"].setdefault(t, {})[u] = r
                elif way == "there":
                    there["rows"].setdefault(t, {})[u] = [r, lrow]
                    result["rows"].setdefault(t, {})[u] = l
                elif l:
                    result["rows"].setdefault(t, {})[u] = l
        for t in sorted(set(local["links"]) | set(remote["links"])):
            ll, rl, bl = local["links"].get(t, {}), remote["links"].get(t, {}), base.get("links", {}).get(t, {})
            for o in set(ll) | set(rl) | set(bl):
                lv, rv = ll.get(o, []), rl.get(o, [])
                way, l, r = _decide(lv, rv, bl.get(o, _h([])))
                if way and l != bl.get(o, _h([])) and r != bl.get(o, _h([])):
                    # both changed: the side whose owner row won the row decision
                    way = owner_way.get(o) or way
                if way == "here":
                    here["links"].setdefault(t, {})[o] = [l, rv]
                    result["links"].setdefault(t, {})[o] = r
                elif way == "there":
                    there["links"].setdefault(t, {})[o] = [r, lv]
                    result["links"].setdefault(t, {})[o] = l
                else:
                    result["links"].setdefault(t, {})[o] = l
        ls, rs, bs = local["settings"], remote["settings"], base.get("settings", {})
        for k in set(ls) | set(rs) | set(bs):
            lv, rv, b = ls.get(k), rs.get(k), bs.get(k, "\0none")
            if lv == rv:
                if lv is not None:
                    result["settings"][k] = lv
                continue
            if lv == b or (rv != b and rv is not None) or lv is None:
                here["settings"][k] = [lv, rv]
                result["settings"][k] = rv
            else:
                there["settings"][k] = [rv, lv]
                result["settings"][k] = lv

        def count(c):
            return sum(len(v) for v in c["rows"].values()) + sum(len(v) for v in c["links"].values()) + len(c["settings"])

        done_there = {"rows": {}, "links": {}, "settings": []}
        if count(there):
            done_there = call("apply", {"db": name, "meta": d.get("meta") or {}, "change": there})["done"]
        done_here = apply(con, here, d.get("paths"), roots) if count(here) else {"rows": {}, "links": {}, "settings": []}
        n["sent"], n["got"] = count({"rows": done_there["rows"], "links": done_there["links"], "settings": done_there["settings"]}), \
            count({"rows": done_here["rows"], "links": done_here["links"], "settings": done_here["settings"]})
        n["waiting"] = count(here) + count(there) - n["sent"] - n["got"]

        # the new base: what both sides agree on now; a change not made keeps the old one
        new = {"rows": {}, "links": {}, "settings": {}}
        for part in ("rows", "links"):
            for t, items in result[part].items():
                okh = set(done_here[part].get(t, [])) | set(done_there[part].get(t, []))
                pend = set(here[part].get(t, {})) | set(there[part].get(t, {}))
                for k, h in items.items():
                    if k in pend and k not in okh:
                        h = base.get(part, {}).get(t, {}).get(k)
                    if h:
                        new[part].setdefault(t, {})[k] = h
        okk = set(done_here["settings"]) | set(done_there["settings"])
        for k, v in result["settings"].items():
            if (k in here["settings"] or k in there["settings"]) and k not in okk:
                v = base.get("settings", {}).get(k)
            if v is not None:
                new["settings"][k] = v
        return new, n
    finally:
        con.close()


def sync_once(address, areas, state_path, who=None, device_id="", call=None):
    """Sync with the hub at `address` (the model-sharing address). Returns a report.
    call(op, body) -> dict replaces the HTTP call (tests)."""
    who = who or device_name()
    if not _lock.acquire(blocking=False):
        return {"ok": False, "msg": "A sync is already running."}
    try:
        call = call or (lambda op, body=None: _call(address, op, body))
        man = call("manifest")
        hub = str(man.get("device") or address)
        if device_id and hub == device_id:
            return {"ok": False, "msg": "That address is this computer's own."}
        state = _load(state_path)
        st = state.setdefault(hub, {"folders": {}, "dbs": {}, "dbs_seen": []})
        report = {"ok": True, "with": man.get("name") or "", "at": time.time(), "folders": {}, "dbs": {}}
        roots = _roots(areas)
        for name, root in areas.folders().items():
            if name not in man["folders"]:
                continue
            Path(root).mkdir(parents=True, exist_ok=True)
            st["folders"][name], report["folders"][name] = sync_folder(
                call, name, root, man["folders"][name], st["folders"].get(name, {}), who)
            prune_trash(root)
        dbs = areas.dbs()
        seen = set(st.get("dbs_seen") or [])
        for name in sorted(set(dbs) | set(man["dbs"])):
            d = dbs.get(name)
            if d is None:
                if name in seen:
                    continue                    # removed here (a band deleted): not brought back
                if not areas.ensure_db(name, man["dbs"][name].get("meta")):
                    continue
                d = areas.dbs().get(name)
                if not d:
                    continue
            if not Path(d["path"]).exists() and name not in man["dbs"]:
                continue
            st["dbs"][name], report["dbs"][name] = sync_db(
                call, name, d, (man["dbs"].get(name) or {}).get("dump"), st["dbs"].get(name, {}), roots)
            seen.add(name)
        st["dbs_seen"] = sorted(seen)
        st["last"] = time.time()
        _save(state_path, state)
        return report
    finally:
        _lock.release()


def summary(report):
    """'Synced with HOME-PC: 3 sent, 5 received, 1 conflict kept as a copy.'"""
    if not report.get("ok"):
        return report.get("msg") or "Sync did not finish."
    tot = {"sent": 0, "got": 0, "conflicts": 0, "waiting": 0}
    for part in ("folders", "dbs"):
        for c in report.get(part, {}).values():
            for k in tot:
                tot[k] += c.get(k, 0)
    bits = [f"{tot['sent']} sent", f"{tot['got']} received"]
    if tot["conflicts"]:
        bits.append(f"{tot['conflicts']} changed on both - kept both copies")
    if tot["waiting"]:
        bits.append(f"{tot['waiting']} left for next time")
    return f"Synced with {report.get('with') or 'your other computer'}: " + ", ".join(bits) + "."
