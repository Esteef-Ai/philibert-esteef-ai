"""The band scheduler's engine: who is free when, and the best times for a practice or show.

A member is free for a slot when all of these hold:
  * the date is not one of their blackout dates,
  * a weekly window of theirs on that weekday covers the whole slot ("Tue 19:00-23:00"),
  * nothing in `busy` (later: their Google Calendar's busy times) overlaps it.
A member who has not filled in any weekly windows yet counts as free, but is named as
"hasn't said" so nobody is surprised. Slots that overlap a band event already booked are
skipped. Days are 0 = Sunday ... 6 = Saturday (as in the page). Times are "HH:MM" local.

    suggest(members, events, **params) -> [ {date, start, end, free, missing, unknown, score} ]
    check_dates(members, events, frm, to, start=None, end=None) -> [ {date, out, events} ]
"""
from datetime import date, timedelta

DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def mins(hm):
    h, m = str(hm).split(":")
    return int(h) * 60 + int(m)


def hm(n):
    return f"{n // 60:02d}:{n % 60:02d}"


def _d(x):
    return x if isinstance(x, date) else date.fromisoformat(str(x))


def weekday(d):
    return _d(d).isoweekday() % 7                       # Sunday = 0


def _windows(m, day):
    """A member's windows on a weekday, overlapping ones merged."""
    ws = sorted((mins(w["start"]), mins(w["end"])) for w in m.get("weekly") or [] if int(w["day"]) == day)
    out = []
    for a, b in ws:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def free(m, d, start, end, busy=()):
    """(True, "") | (True, "hasn't said") | (False, why) for one member and one slot."""
    ds = _d(d).isoformat()
    for b in m.get("blackouts") or []:
        if b["from"] <= ds <= b["to"]:
            return False, "blackout" + (f" ({b['note']})" if b.get("note") else "")
    for (bd, bs, be) in busy:                  # Google Calendar busy times, already in local time
        if bd == ds and bs < end and start < be:
            return False, "busy (Google Calendar)"
    if not m.get("weekly"):
        return True, "hasn't said"
    if any(a <= start and end <= b for a, b in _windows(m, weekday(d))):
        return True, ""
    return False, "not usually free then"


def _band_busy(events, ds, start, end):
    for e in events:
        if e.get("cancelled") or e.get("date") != ds:
            continue
        es = mins(e["start"])
        ee = mins(e["end"]) if e.get("end") else es + 120
        if es < end and start < ee:
            return e
    return None


def suggest(members, events, frm, to, duration=120, earliest="17:00", latest="23:00", required=None,
            min_people=None, step=30, limit=5, busy=None, kind="practice"):
    """The best slot on each day from `frm` to `to`, best days first."""
    busy = busy or {}
    req = set(required) if required else {m["id"] for m in members}
    e0, l0 = mins(earliest), mins(latest)
    habits = {(weekday(e["date"]), e["start"]) for e in events if e.get("kind") == kind and not e.get("cancelled")}
    best = {}
    d, end_day, n = _d(frm), _d(to), 0
    while d <= end_day:
        ds = d.isoformat()
        for s in range(e0, l0 - duration + 1, step):
            t = s + duration
            if _band_busy(events, ds, s, t):
                continue
            ok, missing, unknown = [], [], []
            for m in members:
                f, why = free(m, d, s, t, busy.get(m["id"], ()))
                if f:
                    ok.append(m["name"])
                    if why:
                        unknown.append(m["name"])
                else:
                    missing.append({"name": m["name"], "why": why, "id": m["id"]})
            if any(x["id"] in req for x in missing):
                continue
            if min_people and len(ok) < min_people:
                continue
            score = len(ok) * 100 - len(unknown) * 10 + (15 if (weekday(d), hm(s)) in habits else 0) - n * 0.5
            cand = {"date": ds, "day": DAYS[weekday(d)], "start": hm(s), "end": hm(t), "free": ok,
                    "missing": [{"name": x["name"], "why": x["why"]} for x in missing], "unknown": unknown, "score": score}
            if ds not in best or score > best[ds]["score"]:
                best[ds] = cand
        d += timedelta(days=1)
        n += 1
    return sorted(best.values(), key=lambda c: (-c["score"], c["date"]))[:limit]


def check_dates(members, events, frm, to, start=None, end=None, busy=None):
    """For shows and tours: on each day, who can't make it (and why), and what the band
    already has booked. Without a time only blackouts count; with one, windows do too."""
    busy = busy or {}
    out, d = [], _d(frm)
    while d <= _d(to):
        ds = d.isoformat()
        gone = []
        for m in members:
            if start:
                f, why = free(m, d, mins(start), mins(end) if end else mins(start) + 180, busy.get(m["id"], ()))
            else:
                hit = next((b for b in m.get("blackouts") or [] if b["from"] <= ds <= b["to"]), None)
                f, why = (False, "blackout" + (f" ({hit['note']})" if hit and hit.get("note") else "")) if hit else (True, "")
            if not f:
                gone.append({"name": m["name"], "why": why})
        out.append({"date": ds, "day": DAYS[weekday(d)], "out": gone,
                    "events": [e for e in events if e.get("date") == ds and not e.get("cancelled")]})
        d += timedelta(days=1)
    return out
