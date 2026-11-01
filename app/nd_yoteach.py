"""Yo Teach: a teacher's records and paperwork in one SQLite file on the drive.

  students    by label ("Student G") - a name is optional and stays on the drive; what is
              written down about them: subject, level, strengths, needs, documented supports
              and formal accommodations (kept apart: a support idea is not an accommodation)
  classes     a class or a one-to-one session slot: subject, room, days, times, its students
  sessions    one meeting of a class on a day: started / ended, attendance, timestamped notes,
              and the summary made from them (on demand, every N minutes while it runs, and
              when it ends)
  docs        the lessons, worksheets, homework, assessments and teacher copies made here,
              as Word + PDF pairs in <drive>/Philibert/Documents/Yo Teach/<student or class>/

Lessons and worksheets are written by the model in a small Markdown dialect and turned into
files by nd_docbuild, which applies the house rules in code (Times New Roman 12, black and
gray, no headers or footers, tables inside the margins, and - on student copies - no Part
labels, printed objectives, timing or checkboxes). The rules the model is given are in
settings (rules), so a teacher can change them without a new version.

Nothing is deleted outright: delete marks a row deleted and the Trash brings it back.
Backups: once a day, before the first change, the file is copied to
<data>/exports/Yo Teach backups (the last 14 are kept).

Entry points:
    handle(body, db_path, docs_dir, llm=None, chrome="") -> dict   the page's requests
    tick(db_path, llm)                                             the summary timer (call each minute)
    tool(name, args, db_path) -> str                                the chat's teach_info
llm(model, messages) -> str is the launcher's model call; messages may carry "images".
"""
import base64
import json
import re
import shutil
import sqlite3
import sys
import threading
import time
import uuid
from datetime import date, datetime
from pathlib import Path

import nd_docbuild

SCHEMA = {
    "students": {"label": "TEXT", "name": "TEXT", "subject": "TEXT", "level": "TEXT", "strengths": "TEXT",
                 "needs": "TEXT", "supports": "TEXT", "accommodations": "TEXT", "interests": "TEXT",
                 "notes": "TEXT", "active": "INTEGER"},
    "classes": {"name": "TEXT", "subject": "TEXT", "room": "TEXT", "days": "TEXT", "start_time": "TEXT",
                "end_time": "TEXT", "notes": "TEXT", "summary_every": "INTEGER"},
    "sessions": {"class_id": "INTEGER", "date": "TEXT", "topic": "TEXT", "started": "REAL", "ended": "REAL",
                 "summary": "TEXT", "summary_at": "REAL", "summary_notes": "INTEGER"},
    "attendance": {"session_id": "INTEGER", "student_id": "INTEGER", "status": "TEXT", "at": "REAL", "note": "TEXT"},
    "notes": {"session_id": "INTEGER", "student_id": "INTEGER", "at": "REAL", "kind": "TEXT", "text": "TEXT"},
    "docs": {"student_id": "INTEGER", "class_id": "INTEGER", "kind": "TEXT", "title": "TEXT", "topic": "TEXT",
             "minutes": "INTEGER", "docx": "TEXT", "pdf": "TEXT", "source": "TEXT", "fixes": "TEXT", "batch": "TEXT"},
}
REQUIRED = {"students": "label", "classes": "name", "sessions": "class_id", "attendance": "student_id",
            "notes": "text", "docs": "kind"}
STATUSES = ["present", "late", "absent", "excused", "left early"]
NOTE_KINDS = ["note", "participation", "behaviour", "homework", "tech", "follow-up"]
KINDS = {
    "lesson": ("Lesson", "student"),
    "worksheet": ("Worksheet", "student"),
    "homework": ("Homework", "student"),
    "project": ("Project", "student"),
    "assessment": ("Assessment", "student"),
    "teacher": ("Teacher Copy", "teacher"),
}
DEFAULT_RULES = """Student copies (lesson, worksheet, homework, project, assessment):
- No headers, footers or footnotes. A plain document title is fine.
- No printed learning objectives or outcomes.
- No "Part 1" / "Part 2" labels: give each section a short descriptive title instead.
- No timing on the page: no minutes, no "time used", no start/finish time lines.
- No checkboxes and no ruled answer lines inside table cells. Leave open writing space with [space N].
- Tables: four columns at most, short cell text.
- Spanish and other language classes: every direction, explanation and extra word is in English;
  the examples, target vocabulary, conjugations and the practice itself are in the target language.
- Size the amount of work to the minutes given, without printing the minutes.
- Lesson and worksheet are separate documents; do not repeat the lesson inside the worksheet.
- Never put answers, an answer key or teacher notes in a student document: they go in the teacher copy only.
- Number the items straight through a document (1, 2, 3 ... not starting again at 1 in each section).
- Check every target-language example for grammar, accents and agreement before you finish.
Teacher copies: may include objectives, pacing with minutes, the answer key, scoring, supports and follow-up notes.
Students: use only what is written down about the student. Never invent a diagnosis, accommodation, behaviour,
grade or interest. A one-time theme is not a lasting interest."""
SETTINGS = {"writer_model": "", "vision_model": "", "summary_model": "", "rules": DEFAULT_RULES,
            "school": "", "teacher": ""}
KEEP_AUTO = 14
_lock = threading.Lock()
_jobs = {}                                   # job id -> {status, step, done, total, result, error}


class TeachError(Exception):
    pass


# ---------------------------------------------------------------------------
# the file
# ---------------------------------------------------------------------------
def _open(path, timeout=10):
    """sqlite3.connect; dot-file locking on a Mac (exFAT drives refuse SQLite's usual locks)."""
    if sys.platform == "darwin":
        return sqlite3.connect(Path(path).resolve().as_uri() + "?vfs=unix-dotfile", uri=True, timeout=timeout)
    return sqlite3.connect(str(path), timeout=timeout)


def connect(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = _open(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = DELETE")
    for t, cols in SCHEMA.items():
        con.execute(f"CREATE TABLE IF NOT EXISTS {t} (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    + ", ".join(f'"{c}" {ty}' for c, ty in cols.items())
                    + ", created REAL, updated REAL, deleted INTEGER DEFAULT 0)")
        have = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
        for c, ty in cols.items():
            if c not in have:
                con.execute(f'ALTER TABLE {t} ADD COLUMN "{c}" {ty}')
    con.execute("CREATE TABLE IF NOT EXISTS class_students (class_id INTEGER, student_id INTEGER, "
                "PRIMARY KEY (class_id, student_id))")
    con.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)")
    return con


def settings(con):
    out = dict(SETTINGS)
    out.update({r[0]: r[1] for r in con.execute("SELECT k, v FROM settings")})
    if not str(out.get("rules") or "").strip():
        out["rules"] = DEFAULT_RULES
    return out


def set_settings(con, new):
    for k, v in (new or {}).items():
        if k in SETTINGS:
            con.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (k, str(v or "")[:8000]))
    con.commit()
    return settings(con)


def _table(t):
    if t not in SCHEMA:
        raise TeachError(f"unknown list {t!r}")
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
                raise TeachError(f"{c} should be a whole number")
        elif ty == "REAL":
            try:
                out[c] = float(v)
            except (TypeError, ValueError):
                raise TeachError(f"{c} should be a number")
        else:
            out[c] = str(v)[:8000]
    if t == "attendance" and out.get("status") and out["status"] not in STATUSES:
        out["status"] = "present"
    if t == "notes" and out.get("kind") and out["kind"] not in NOTE_KINDS:
        out["kind"] = "note"
    if out.get("date"):
        try:
            datetime.strptime(out["date"][:10], "%Y-%m-%d")
        except ValueError:
            raise TeachError("date should look like 2026-11-07")
    for c in ("start_time", "end_time"):
        if out.get(c) and not re.fullmatch(r"\d{1,2}:\d{2}", out[c]):
            raise TeachError(f"{c.replace('_', ' ')} should look like 09:30")
    return out


def rows(con, t, include_deleted=False, where="", args=()):
    t = _table(t)
    order = {"students": "label", "classes": "name", "sessions": "date DESC, started DESC",
             "attendance": "id", "notes": "at", "docs": "created DESC"}[t]
    q = f"SELECT * FROM {t} WHERE " + ("deleted = 1" if include_deleted else "deleted = 0") + (f" AND {where}" if where else "")
    return [dict(r) for r in con.execute(q + f" ORDER BY {order}", args)]


def get(con, t, rid):
    r = con.execute(f"SELECT * FROM {_table(t)} WHERE id = ?", (rid,)).fetchone()
    if not r:
        raise TeachError("no such entry")
    return dict(r)


def save(con, t, row):
    t = _table(t)
    row = row or {}
    data = _clean(t, row)
    rid = row.get("id")
    now = time.time()
    if not rid:
        if data.get(REQUIRED[t]) in (None, ""):
            raise TeachError(f"give it a {REQUIRED[t].replace('_id', '')}")
        if t == "students":
            data.setdefault("active", 1)
            if con.execute("SELECT 1 FROM students WHERE deleted = 0 AND lower(label) = lower(?)", (data["label"],)).fetchone():
                raise TeachError(f"there is already a {data['label']}")
        if t == "notes":
            data.setdefault("at", now)
            data.setdefault("kind", "note")
        cols = list(data) + ["created", "updated"]
        cur = con.execute(f"INSERT INTO {t} ({', '.join(chr(34) + c + chr(34) for c in cols)}) VALUES ({', '.join('?' * len(cols))})",
                          [data[c] for c in data] + [now, now])
        rid = cur.lastrowid
    else:
        if not con.execute(f"SELECT 1 FROM {t} WHERE id = ?", (rid,)).fetchone():
            raise TeachError("no such entry")
        if data:
            con.execute(f"UPDATE {t} SET " + ", ".join(f'"{c}" = ?' for c in data) + ", updated = ? WHERE id = ?",
                        [data[c] for c in data] + [now, rid])
    if t == "classes" and "students" in row:
        set_class_students(con, rid, row.get("students") or [])
    con.commit()
    return get(con, t, rid)


def set_deleted(con, t, rid, flag):
    n = con.execute(f"UPDATE {_table(t)} SET deleted = ?, updated = ? WHERE id = ?",
                    (1 if flag else 0, time.time(), rid)).rowcount
    con.commit()
    if not n:
        raise TeachError("no such entry")


def purge(con, t=None, rid=None):
    targets = [(_table(t), int(rid))] if t else [(tb, r[0]) for tb in SCHEMA
                                                  for r in con.execute(f"SELECT id FROM {tb} WHERE deleted = 1")]
    n = 0
    for tb, i in targets:
        n += con.execute(f"DELETE FROM {tb} WHERE id = ? AND deleted = 1", (i,)).rowcount
        if tb == "classes":
            con.execute("DELETE FROM class_students WHERE class_id = ?", (i,))
        if tb == "students":
            con.execute("DELETE FROM class_students WHERE student_id = ?", (i,))
    con.commit()
    if t and not n:
        raise TeachError("not in the trash")
    return n


def class_students(con, cid):
    return [dict(r) for r in con.execute(
        "SELECT s.* FROM students s JOIN class_students cs ON cs.student_id = s.id "
        "WHERE cs.class_id = ? AND s.deleted = 0 ORDER BY s.label", (cid,))]


def set_class_students(con, cid, ids):
    con.execute("DELETE FROM class_students WHERE class_id = ?", (cid,))
    for sid in ids:
        con.execute("INSERT OR IGNORE INTO class_students VALUES (?, ?)", (cid, int(sid)))


# ---------------------------------------------------------------------------
# a class meeting: start, attendance, notes, end
# ---------------------------------------------------------------------------
def start_session(con, cid, topic=""):
    cls = get(con, "classes", cid)
    open_ = con.execute("SELECT id FROM sessions WHERE class_id = ? AND ended IS NULL AND deleted = 0", (cid,)).fetchone()
    if open_:
        return session(con, open_[0])
    now = time.time()
    s = save(con, "sessions", {"class_id": cls["id"], "date": date.today().isoformat(), "topic": topic or None,
                               "started": now})
    for st in class_students(con, cid):           # everybody starts present; a tap changes it
        save(con, "attendance", {"session_id": s["id"], "student_id": st["id"], "status": "present", "at": now})
    return session(con, s["id"])


def end_session(con, sid):
    s = get(con, "sessions", sid)
    if not s.get("ended"):
        con.execute("UPDATE sessions SET ended = ?, updated = ? WHERE id = ?", (time.time(), time.time(), sid))
        con.commit()
    return session(con, sid)


def mark(con, sid, student_id, status, note=None):
    if status not in STATUSES:
        raise TeachError("attendance is one of: " + ", ".join(STATUSES))
    r = con.execute("SELECT id FROM attendance WHERE session_id = ? AND student_id = ? AND deleted = 0",
                    (sid, student_id)).fetchone()
    row = {"session_id": sid, "student_id": student_id, "status": status, "at": time.time()}
    if note is not None:
        row["note"] = note
    if r:
        row["id"] = r[0]
    return save(con, "attendance", row)


def session(con, sid):
    s = get(con, "sessions", sid)
    s["class"] = get(con, "classes", s["class_id"]) if s.get("class_id") else None
    s["attendance"] = [dict(r) for r in con.execute(
        "SELECT a.*, st.label, st.name FROM attendance a JOIN students st ON st.id = a.student_id "
        "WHERE a.session_id = ? AND a.deleted = 0 ORDER BY st.label", (sid,))]
    s["notes"] = [dict(r) for r in con.execute(
        "SELECT n.*, st.label FROM notes n LEFT JOIN students st ON st.id = n.student_id "
        "WHERE n.session_id = ? AND n.deleted = 0 ORDER BY n.at", (sid,))]
    return s


def today(con, day=None):
    """Today's classes (by weekday), their meetings so far, and anything still running."""
    day = day or date.today().isoformat()
    wd = datetime.strptime(day, "%Y-%m-%d").strftime("%a").lower()[:3]
    classes = rows(con, "classes")
    for c in classes:
        days = [d.strip().lower()[:3] for d in re.split(r"[,\s/]+", c.get("days") or "") if d.strip()]
        c["today"] = (not days) or wd in days
        c["students"] = [x["id"] for x in class_students(con, c["id"])]
    sessions = [session(con, r["id"]) for r in rows(con, "sessions", where="date = ?", args=(day,))]
    running = [session(con, r[0]) for r in con.execute(
        "SELECT id FROM sessions WHERE ended IS NULL AND deleted = 0 ORDER BY started")]
    return {"date": day, "classes": classes, "sessions": sessions, "running": running}


# ---------------------------------------------------------------------------
# summaries
# ---------------------------------------------------------------------------
def _clock(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "?"


def session_text(s):
    cls = s.get("class") or {}
    lines = [f"Class: {cls.get('name') or '?'} ({cls.get('subject') or 'subject not given'}), {s['date']}, "
             f"{_clock(s.get('started'))} to {_clock(s.get('ended')) if s.get('ended') else 'still running'}",
             f"Topic: {s.get('topic') or 'not given'}", "Attendance:"]
    for a in s["attendance"]:
        lines.append(f"- {a['label']}: {a['status']}" + (f" ({a['note']})" if a.get("note") else ""))
    lines.append("Notes taken during class:")
    for n in s["notes"]:
        who = n.get("label") or "whole class"
        lines.append(f"- {_clock(n['at'])} [{n.get('kind') or 'note'}] {who}: {n['text']}")
    if not s["notes"]:
        lines.append("- (none)")
    return "\n".join(lines)


SUMMARY_PROMPT = (
    "You write a teacher's end-of-class summary from their own attendance and notes. Use only what is written: "
    "never add events, motives, diagnoses or grades. Plain text, short, in this order:\n"
    "Attendance: one line (who was absent, late or left early; 'Everyone present' if so).\n"
    "Covered: one or two sentences.\n"
    "Students: one line per student with notes, by their label, what was observed.\n"
    "Follow-up: bullet list of anything the notes say needs doing (homework, contact a parent, re-teach, tech), "
    "or 'Nothing noted'.\n"
    "Keep student labels as given. Write in English.")


def summarize(con, sid, llm, model):
    if not llm or not model:
        raise TeachError("choose a model for summaries in Yo Teach > Settings")
    s = session(con, sid)
    text = llm(model, [{"role": "system", "content": SUMMARY_PROMPT},
                       {"role": "user", "content": session_text(s)}])
    text = str(text or "").strip()
    if not text or text.startswith("[Ollama error") or text == "[No response]":
        raise TeachError("the model did not answer: " + text[:200])
    con.execute("UPDATE sessions SET summary = ?, summary_at = ?, summary_notes = ?, updated = ? WHERE id = ?",
                (text, time.time(), len(s["notes"]), time.time(), sid))
    con.commit()
    return session(con, sid)


def day_summary(con, day, llm, model):
    """Every class of a day in one digest (each class summarised first if it has no summary)."""
    out = []
    for r in rows(con, "sessions", where="date = ?", args=(day,)):
        s = session(con, r["id"])
        if s["notes"] and (not s.get("summary") or (s.get("summary_notes") or 0) < len(s["notes"])):
            s = summarize(con, s["id"], llm, model)
        out.append(f"## {(s.get('class') or {}).get('name') or 'Class'} ({_clock(s.get('started'))})\n"
                   + (s.get("summary") or session_text(s)))
    return "\n\n".join(out) or "No classes recorded on this day."


def tick(db_path, llm):
    """The timer: a running class with 'summary every N minutes' gets a fresh summary when
    there are new notes; a class that ended with notes and no summary gets one. Never raises."""
    try:
        with _lock:
            con = connect(db_path)
            try:
                st = settings(con)
                model = st.get("summary_model") or st.get("writer_model")
                if not model:
                    return
                now = time.time()
                for r in con.execute("SELECT s.id, s.ended, s.summary_at, s.summary_notes, c.summary_every FROM sessions s "
                                     "LEFT JOIN classes c ON c.id = s.class_id WHERE s.deleted = 0 AND s.date >= ?",
                                     (date.fromtimestamp(now - 86400 * 2).isoformat(),)).fetchall():
                    n = con.execute("SELECT COUNT(*) FROM notes WHERE session_id = ? AND deleted = 0", (r["id"],)).fetchone()[0]
                    if not n or n <= (r["summary_notes"] or 0):
                        continue
                    every = r["summary_every"] or 0
                    due = (r["ended"] and not r["summary_at"]) or \
                          (r["ended"] and (r["summary_at"] or 0) < r["ended"]) or \
                          (not r["ended"] and every > 0 and now - (r["summary_at"] or 0) >= every * 60)
                    if due:
                        summarize(con, r["id"], llm, model)
            finally:
                con.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# lessons, worksheets and the rest
# ---------------------------------------------------------------------------
FORMAT = """Write ONLY the document body in this Markdown (no title - it is added for you; no code fences):
# Section title            ## Smaller heading
Plain paragraphs. **bold** and *italic* are fine.
- bullet items             1. numbered items
| Column | Column |        (a table: first row is the header; at most four columns)
[space 4]                  open writing space about four lines tall, where the student writes
[page]                     a new page
Use [space N] after every question or task the student answers in writing."""

KIND_BRIEF = {
    "lesson": "A {m}-minute lesson the student works through with the teacher: a short clear explanation, "
              "worked examples, then a little guided practice with the answers left for the student.",
    "worksheet": "A {m}-minute independent practice worksheet on the same topic: varied items from easier to harder, "
                 "clear directions above each group of items, and room to write.",
    "homework": "A {m}-minute homework assignment the student can do alone: a brief reminder of the key idea, "
                "then practice with room to write.",
    "project": "A {m}-minute project: what to make or find out, the steps, what to hand in, and - where research is "
               "involved - named sources, one specific example and an explanation in the student's own words.",
    "assessment": "A {m}-minute assessment of what the student actually studied (only that): directions, the items "
                  "with room to answer. No answers and no points on the student copy.",
    "teacher": "The TEACHER COPY for the documents below: objectives, a pacing plan with minutes, the answer key for "
               "every item, scoring if it is an assessment, supports for this student (only the documented ones), "
               "and one or two quick checks for understanding.",
}


def student_context(st):
    if not st:
        return "Student: not given (a general document)."
    parts = [f"Student: {st['label']}"]
    for k, label in (("subject", "Subject"), ("level", "Level"), ("strengths", "Documented strengths"),
                     ("needs", "Documented needs"), ("supports", "Supports that have worked"),
                     ("accommodations", "Formal accommodations"), ("interests", "Interests the student has shown"),
                     ("notes", "Teacher notes")):
        if st.get(k):
            parts.append(f"{label}: {st[k]}")
    return "\n".join(parts)


def _recent_topics(con, sid):
    return [r[0] for r in con.execute("SELECT DISTINCT topic FROM docs WHERE student_id = ? AND deleted = 0 "
                                      "AND topic IS NOT NULL ORDER BY created DESC LIMIT 8", (sid,))]


def _strip_title(md, title, topic):
    """Models often open with the title anyway: drop a first heading that repeats it."""
    lines = md.strip().split("\n")
    if lines and re.match(r"^#{1,2}\s", lines[0]):
        h = re.sub(r"[^a-z0-9]+", " ", lines[0].lower()).strip()
        for t in (title, topic):
            k = re.sub(r"[^a-z0-9]+", " ", str(t or "").lower()).strip()
            if k and (k in h or h in k):
                return "\n".join(lines[1:]).strip()
    return md.strip()


def _strip_fences(md):
    md = re.sub(r"<think>.*?</think>", "", str(md or ""), flags=re.S)
    m = re.search(r"```(?:markdown|md)?\s*\n(.*?)```", md, re.S)
    return m.group(1) if m and len(m.group(1)) > len(md) * 0.5 else md


def make_docs(db_path, docs_dir, req, llm, chrome, job=None):
    """Write the documents a request asks for. req: student_id, class_id, subject, level, topic,
    details, kinds [..], minutes {kind: n}, screenshot (base64 image, optional)."""
    def step(text, done=None):
        if job is not None:
            job["step"] = text
            if done is not None:
                job["done"] = done

    with _lock:
        con = connect(db_path)
        try:
            st = settings(con)
            stu = get(con, "students", int(req["student_id"])) if req.get("student_id") else None
            recent = _recent_topics(con, stu["id"]) if stu else []
            daily_backup(con, db_path)
        finally:
            con.close()
    model = req.get("model") or st.get("writer_model")
    if not model:
        raise TeachError("choose a writing model in Yo Teach > Settings")
    topic = str(req.get("topic") or "").strip()
    if not topic:
        raise TeachError("give it a topic")
    kinds = [k for k in (req.get("kinds") or ["lesson", "worksheet", "teacher"]) if k in KINDS]
    student_kinds = [k for k in kinds if k != "teacher"]
    if not kinds:
        raise TeachError("pick at least one document")
    minutes = req.get("minutes") or {}
    total = len(kinds) + (1 if req.get("screenshot") else 0)
    if job is not None:
        job["total"] = total

    source = ""
    if req.get("screenshot"):
        vmodel = req.get("vision_model") or st.get("vision_model")
        if not vmodel:
            raise TeachError("reading a screenshot needs a model that can see pictures - choose one in Settings")
        step("Reading the screenshot", 0)
        img = str(req["screenshot"]).split(",", 1)[-1]
        source = str(llm(vmodel, [{"role": "user", "images": [img], "content":
                                   "Transcribe everything written in this screenshot exactly, in its own language: "
                                   "headings, the learning target or objective, instructions, vocabulary, examples, "
                                   "and any notes about the student. Then, on a last line starting 'Main point:', "
                                   "say in one sentence what the lesson is about."}]) or "").strip()
        if source.startswith("[Ollama error") or source == "[No response]":
            raise TeachError("could not read the screenshot: " + source[:200])

    label = stu["label"] if stu else (req.get("class_name") or "General")
    subject = req.get("subject") or (stu or {}).get("subject") or ""
    level = req.get("level") or (stu or {}).get("level") or ""
    brief = (f"Subject: {subject or 'not given'}\nLevel: {level or 'not given'}\nTopic: {topic}\n"
             + (f"Teacher's details: {req['details']}\n" if req.get("details") else "")
             + (f"Topics already covered with this student: {'; '.join(recent)}\n" if recent else "")
             + (f"\nFrom the teacher's screenshot:\n{source}\n" if source else "")
             + "\n" + student_context(stu))
    system = ("You are a careful, experienced teacher's assistant who writes classroom documents that are ready "
              "to print. Accuracy first: correct language, correct answers, a workload that fits the time.\n\n"
              "THE TEACHER'S RULES:\n" + st["rules"] + "\n\n" + FORMAT)
    folder = Path(docs_dir) / nd_docbuild.safe_name(label)
    batch = uuid.uuid4().hex[:10]
    made, written = [], {}
    words, short = topic.split(), ""
    for w in words:                                    # the topic's first words, whole, ~45 letters
        if len(short) + len(w) > 45 and short:
            break
        short = f"{short} {w}".strip()
    stem = nd_docbuild.safe_name(f"{label} {short}", 90)
    for i, kind in enumerate(student_kinds + (["teacher"] if "teacher" in kinds else [])):
        word, copy = KINDS[kind]
        m = int(minutes.get(kind) or (minutes.get("lesson") if kind == "teacher" else 0) or 20)
        step(f"Writing the {word.lower()}", i + (1 if source else 0))
        ask = KIND_BRIEF[kind].format(m=m) + "\n\n" + brief
        if kind == "teacher":
            ask += "\n\nTHE STUDENT DOCUMENTS:\n" + "\n\n".join(f"=== {KINDS[k][0]} ===\n{written[k]}" for k in written)
        elif written.get("lesson") and kind != "lesson":
            ask += "\n\nThe lesson this follows (do not repeat it):\n" + written["lesson"][:6000]
        md = _strip_fences(llm(model, [{"role": "system", "content": system}, {"role": "user", "content": ask}]))
        if not md.strip() or md.startswith("[Ollama error") or md.strip() == "[No response]":
            raise TeachError(f"the model did not write the {word.lower()}: {md[:200]}")
        title = topic if kind == "lesson" else f"{topic}: {word}"
        md = _strip_title(md, title, topic)
        written[kind] = md
        step(f"Making the {word.lower()} files")
        r = nd_docbuild.build(title, md, copy, folder, f"{stem}_{word.replace(' ', '_')}", chrome)
        with _lock:
            con = connect(db_path)
            try:
                d = save(con, "docs", {"student_id": stu["id"] if stu else None, "class_id": req.get("class_id"),
                                       "kind": kind, "title": title, "topic": topic, "minutes": m,
                                       "docx": r["docx"], "pdf": r["pdf"] or None, "source": md,
                                       "fixes": json.dumps(r["fixes"]), "batch": batch})
            finally:
                con.close()
        d["fixes"] = r["fixes"]
        d["pdf_error"] = r.get("pdf_error", "")
        d["pages"] = r.get("pages")
        made.append(d)
    step("Done", total)
    return {"docs": made, "folder": str(folder), "batch": batch}


def remake(db_path, doc_id, md, chrome):
    """The teacher edited a document's text: write its files again from that."""
    with _lock:
        con = connect(db_path)
        try:
            d = get(con, "docs", doc_id)
        finally:
            con.close()
    copy = KINDS.get(d["kind"], ("", "student"))[1]
    docx = Path(d["docx"])
    r = nd_docbuild.build(d["title"], md, copy, docx.parent, docx.stem, chrome)
    with _lock:
        con = connect(db_path)
        try:
            d = save(con, "docs", {"id": doc_id, "source": md, "pdf": r["pdf"] or None, "fixes": json.dumps(r["fixes"])})
        finally:
            con.close()
    d["fixes"], d["pdf_error"] = r["fixes"], r.get("pdf_error", "")
    return d


def start_job(fn, *args):
    jid = uuid.uuid4().hex[:12]
    job = {"status": "running", "step": "Starting", "done": 0, "total": 1, "result": None, "error": "", "at": time.time()}
    _jobs[jid] = job

    def run():
        try:
            job["result"] = fn(*args, job=job)
            job["status"] = "done"
        except TeachError as e:
            job["status"], job["error"] = "error", str(e)
        except Exception as e:
            job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"
    threading.Thread(target=run, daemon=True).start()
    for k in [k for k, j in _jobs.items() if time.time() - j["at"] > 6 * 3600]:
        _jobs.pop(k, None)
    return jid


# ---------------------------------------------------------------------------
# backups and export
# ---------------------------------------------------------------------------
def _backup_dir(db_path):
    return Path(db_path).parent / "exports" / "Yo Teach backups"


def backup(con, db_path, auto=False):
    d = _backup_dir(db_path)
    d.mkdir(parents=True, exist_ok=True)
    name = f"{'auto' if auto else 'saved'} {date.today().isoformat()} {datetime.now().strftime('%H%M%S')}.db"
    dst = _open(d / name)
    try:
        con.backup(dst)
    finally:
        dst.close()
    autos = sorted(d.glob("auto *.db"))
    for old in autos[:-KEEP_AUTO]:
        old.unlink()
    return name


def daily_backup(con, db_path):
    if not any(con.execute(f"SELECT 1 FROM {t} LIMIT 1").fetchone() for t in SCHEMA):
        return None
    if any(_backup_dir(db_path).glob(f"auto {date.today().isoformat()} *.db")):
        return None
    return backup(con, db_path, auto=True)


def export_json(con):
    """Everything (Trash left out) as one JSON document: the start of moving Yo Teach
    between computers, and a readable copy for the teacher."""
    out = {"app": "Yo Teach", "version": 1, "exported": datetime.now().isoformat(timespec="seconds"),
           "settings": settings(con), "class_students": [dict(r) for r in con.execute("SELECT * FROM class_students")]}
    for t in SCHEMA:
        out[t] = rows(con, t)
    return out


def import_json(con, data):
    """Bring in an export (or a starter file): students by label and classes by name are
    added or filled in - what is already here wins - and settings only where still default.
    Class meetings and documents stay with the computer they were made on."""
    if not isinstance(data, dict) or data.get("app") != "Yo Teach":
        raise TeachError("that is not a Yo Teach file")
    added = {"students": 0, "classes": 0, "updated": 0}
    ids = {}
    for s in data.get("students") or []:
        label = str(s.get("label") or "").strip()
        if not label:
            continue
        have = con.execute("SELECT * FROM students WHERE deleted = 0 AND lower(label) = lower(?)", (label,)).fetchone()
        row = {k: s.get(k) for k in SCHEMA["students"] if s.get(k) not in (None, "")}
        if have:
            fill = {k: v for k, v in row.items() if not have[k]}
            if fill:
                save(con, "students", {"id": have["id"], **fill})
                added["updated"] += 1
            ids[s.get("id")] = have["id"]
        else:
            ids[s.get("id")] = save(con, "students", row)["id"]
            added["students"] += 1
    links = {}
    for cs in data.get("class_students") or []:
        links.setdefault(cs.get("class_id"), []).append(cs.get("student_id"))
    for c in data.get("classes") or []:
        name = str(c.get("name") or "").strip()
        if not name or con.execute("SELECT 1 FROM classes WHERE deleted = 0 AND lower(name) = lower(?)", (name,)).fetchone():
            continue
        row = {k: c.get(k) for k in SCHEMA["classes"] if c.get(k) not in (None, "")}
        row["students"] = [ids[x] for x in links.get(c.get("id"), []) if x in ids]
        save(con, "classes", row)
        added["classes"] += 1
    cur = settings(con)
    new = {k: v for k, v in (data.get("settings") or {}).items()
           if k in SETTINGS and v and (not cur.get(k) or cur.get(k) == SETTINGS[k]) and k not in ("writer_model", "vision_model", "summary_model")}
    if new:
        set_settings(con, new)
    return added


# ---------------------------------------------------------------------------
# the chat's view
# ---------------------------------------------------------------------------
def tool(name, a, db_path):
    with _lock:
        con = connect(db_path)
        try:
            what = str(a.get("what") or "today").lower()
            if what == "today":
                t = today(con)
                lines = [f"Today {t['date']}:"]
                for c in t["classes"]:
                    if c["today"]:
                        lines.append(f"- class #{c['id']} {c['name']} {c.get('start_time') or ''}-{c.get('end_time') or ''} "
                                     f"({len(c['students'])} students)")
                for s in t["sessions"]:
                    absent = [x["label"] for x in s["attendance"] if x["status"] in ("absent", "excused")]
                    lines.append(f"- met: {(s['class'] or {}).get('name')} at {_clock(s['started'])}, "
                                 f"{len(s['notes'])} notes, absent: {', '.join(absent) or 'nobody'}"
                                 + (f"\n  summary: {s['summary']}" if s.get("summary") else ""))
                return "\n".join(lines)
            if what == "students":
                q = str(a.get("query") or "").lower()
                out = []
                for s in rows(con, "students"):
                    if q and q not in json.dumps(s).lower():
                        continue
                    out.append(student_context(s).replace("\n", "; ") + f" [id {s['id']}]")
                return "\n".join(out) or "No students yet."
            if what == "docs":
                return "\n".join(f"- {d['created'] and datetime.fromtimestamp(d['created']).date()} {d['title']} "
                                 f"({d['kind']}) {d['docx']}" for d in rows(con, "docs")[:30]) or "No documents yet."
            if what == "session" and a.get("id"):
                return session_text(session(con, int(a["id"])))
            return "Ask for: today | students | docs | session (with id)."
        finally:
            con.close()


# ---------------------------------------------------------------------------
# the page's requests
# ---------------------------------------------------------------------------
def _inside(docs_dir, p):
    p, root = Path(p).resolve(), Path(docs_dir).resolve()
    return p == root or root in p.parents


def handle(body, db_path, docs_dir, llm=None, chrome=""):
    body = body or {}
    op = body.get("op", "")
    if op == "job":
        j = _jobs.get(str(body.get("id") or ""))
        return {"ok": bool(j), **(j or {"msg": "no such job"})}
    if op == "make":
        return {"ok": True, "job": start_job(make_docs, db_path, docs_dir, body.get("request") or {}, llm, chrome)}
    if op == "remake":
        try:
            return {"ok": True, "doc": remake(db_path, int(body.get("id")), str(body.get("source") or ""), chrome)}
        except (TeachError, OSError, ValueError, TypeError) as e:
            return {"ok": False, "msg": str(e)}
    with _lock:
        try:
            con = connect(db_path)
        except sqlite3.Error as e:
            return {"ok": False, "msg": f"Could not open the Yo Teach file: {e}"}
        try:
            if op in ("save", "delete", "restore", "start", "end", "mark", "note", "settings_save"):
                daily_backup(con, db_path)
            if op == "today":
                return {"ok": True, **today(con, body.get("date"))}
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
            if op == "class":
                c = get(con, "classes", int(body.get("id")))
                c["students"] = [x["id"] for x in class_students(con, c["id"])]
                return {"ok": True, "class": c}
            if op == "start":
                return {"ok": True, "session": start_session(con, int(body.get("class_id")), body.get("topic") or "")}
            if op == "end":
                return {"ok": True, "session": end_session(con, int(body.get("id")))}
            if op == "session":
                return {"ok": True, "session": session(con, int(body.get("id")))}
            if op == "mark":
                mark(con, int(body.get("session_id")), int(body.get("student_id")), body.get("status"), body.get("note"))
                return {"ok": True, "session": session(con, int(body.get("session_id")))}
            if op == "note":
                save(con, "notes", {"session_id": int(body.get("session_id")), "student_id": body.get("student_id"),
                                    "kind": body.get("kind") or "note", "text": body.get("text"), "at": time.time()})
                return {"ok": True, "session": session(con, int(body.get("session_id")))}
            if op == "summarize":
                st = settings(con)
                return {"ok": True, "session": summarize(con, int(body.get("id")), llm,
                                                         body.get("model") or st.get("summary_model") or st.get("writer_model"))}
            if op == "day_summary":
                st = settings(con)
                return {"ok": True, "text": day_summary(con, body.get("date") or date.today().isoformat(), llm,
                                                        body.get("model") or st.get("summary_model") or st.get("writer_model"))}
            if op == "settings":
                return {"ok": True, "settings": settings(con), "default_rules": DEFAULT_RULES,
                        "statuses": STATUSES, "note_kinds": NOTE_KINDS, "kinds": {k: v[0] for k, v in KINDS.items()}}
            if op == "settings_save":
                return {"ok": True, "settings": set_settings(con, body.get("settings") or {})}
            if op == "doc":
                d = get(con, "docs", int(body.get("id")))
                d["fixes"] = json.loads(d.get("fixes") or "[]")
                return {"ok": True, "doc": d}
            if op == "docs":
                ds = rows(con, "docs")
                if body.get("student_id"):
                    ds = [d for d in ds if d.get("student_id") == int(body["student_id"])]
                for d in ds:
                    d["fixes"] = json.loads(d.get("fixes") or "[]")
                    d.pop("source", None)
                return {"ok": True, "docs": ds}
            if op == "open":                         # a made file, in Word / the PDF viewer, or its folder
                d = get(con, "docs", int(body.get("id")))
                p = Path(d.get(body.get("which") or "docx") or "")
                if body.get("folder"):
                    p = p.parent
                if not p.exists() or not _inside(docs_dir, p):
                    return {"ok": False, "msg": "that file is not there any more"}
                _reveal(p)
                return {"ok": True}
            if op == "backup":
                return {"ok": True, "name": backup(con, db_path)}
            if op == "export":
                return {"ok": True, "data": export_json(con)}
            if op == "import":
                daily_backup(con, db_path)
                return {"ok": True, **import_json(con, body.get("data"))}
            return {"ok": False, "msg": f"unknown op {op!r}"}
        except TeachError as e:
            return {"ok": False, "msg": str(e)}
        except (sqlite3.Error, ValueError, TypeError, KeyError) as e:
            return {"ok": False, "msg": f"{type(e).__name__}: {e}"}
        finally:
            con.close()


def _reveal(p):
    import os
    import subprocess
    if sys.platform == "win32":
        os.startfile(str(p))                                  # noqa: the teacher's own file
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])
