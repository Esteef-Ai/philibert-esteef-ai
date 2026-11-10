"""Guitar audio -> tablature.

    python guitartab.py riff.wav --bpm 112 --tuning "E A D G B E"

Steps: detect the notes (Spotify's Basic Pitch), snap them to the beat grid from the BPM,
choose a string and fret for every note (the path a hand would play), write a text tab.

Philibert's Guitar Tab app ships this file as nd_guitartab_engine.py (the GuitarTab project is where
it is written and scored) and runs it in app mode, with the add-on's packages folder:

    python nd_guitartab_engine.py --site <packages> app transcribe '<json job>'
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

if "--site" in sys.argv:                 # app mode: the add-on's own packages come first
    _i = sys.argv.index("--site")
    sys.path.insert(0, sys.argv[_i + 1])
    del sys.argv[_i:_i + 2]

import numpy as np                       # noqa: E402

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B", "Fb": "E"}
PRESETS = {
    "standard": "E A D G B E", "dropd": "D A D G B E", "halfstep": "Eb Ab Db Gb Bb Eb",
    "dstandard": "D G C F A D", "dropc": "C G C F A D", "openg": "D G D G B D", "dadgad": "D A D G A D",
    "7standard": "B E A D G B E", "7dropa": "A E A D G B E", "8standard": "F# B E A D G B E",
}
TPB = 12                       # ticks per quarter note: 16ths (3 ticks) and 8th triplets (4 ticks)
MAX_FRET = 24


# ── tuning ──────────────────────────────────────────────────────────────────────────────────
def parse_tuning(text, strings=None):
    """'E A D G B E' (low to high) or 'E2 A2 ...' or a preset name -> list of MIDI numbers.
    Without octaves the lowest string goes at or below A2 (a 7-string's at or below E2, an
    8-string's B1) and each next string is the nearest pitch above the one before."""
    text = PRESETS.get(text.lower().replace(" ", "").replace("-", ""), text) if text else None
    if not text:
        text = {6: PRESETS["standard"], 7: PRESETS["7standard"], 8: PRESETS["8standard"]}.get(strings or 6)
        if not text:
            raise SystemExit(f"no default tuning for {strings} strings: give --tuning")
    toks = re.findall(r"([A-Ga-g])([#b]?)(-?\d)?", text)
    if not toks:
        raise SystemExit(f"can't read the tuning {text!r}")
    lowest = 45 - 5 * max(0, len(toks) - 6)       # 6 strings: at or below A2, 7: E2, 8: B1
    out = []
    for letter, acc, octv in toks:
        name = letter.upper() + acc
        name = FLATS.get(name, name)
        pc = NAMES.index(name)
        if octv:
            m = 12 * (int(octv) + 1) + pc
        elif not out:
            m = 12 * 3 + pc                                    # octave 2
            while m > lowest:
                m -= 12
        else:
            m = out[-1] + 1
            while m % 12 != pc:
                m += 1
        out.append(m)
    if strings and len(out) != strings:
        raise SystemExit(f"--strings {strings} but the tuning has {len(out)} notes")
    return out


def note_name(m):
    return NAMES[m % 12] + str(m // 12 - 1)


# ── note detection ──────────────────────────────────────────────────────────────────────────
def detect_notes(path, tuning, onset=0.6, frame=0.4, min_len_ms=60, cache=None):   # tuned on GuitarSet (tests/tune_detect.py)
    """Basic Pitch's notes, kept in `cache` (a .json) when given: a new BPM or tuning does not
    need the detection again (it covers the whole guitar range, any tuning's included)."""
    if cache and Path(cache).is_file():
        return json.loads(Path(cache).read_text(encoding="utf-8"))
    notes = _detect(path, tuning if not cache else [28, 64], onset, frame, min_len_ms)
    if cache:
        Path(cache).write_text(json.dumps(notes), encoding="utf-8")
    return notes


def _detect(path, tuning, onset, frame, min_len_ms):
    import logging
    logging.disable(logging.WARNING)               # Basic Pitch warns about backends we don't use
    from basic_pitch import inference
    import basic_pitch
    model = Path(basic_pitch.__file__).parent / "saved_models" / "icassp_2022" / "nmp.onnx"
    lo = 440 * 2 ** ((tuning[0] - 69 - 0.5) / 12)
    hi = 440 * 2 ** ((tuning[-1] + MAX_FRET - 69 + 0.5) / 12)
    _, _, events = inference.predict(str(path), model_or_model_path=str(model), onset_threshold=onset,
                                     frame_threshold=frame, minimum_note_length=min_len_ms,
                                     minimum_frequency=lo, maximum_frequency=hi, melodia_trick=False)
    notes = [dict(t=float(s), end=float(e), midi=int(p), amp=float(a)) for s, e, p, a, _ in events]
    notes.sort(key=lambda n: (n["t"], n["midi"]))
    return notes


def clean_notes(notes, min_amp=0.1, ghost=0.5):
    """Drop faint notes (relative to the loud ones), and octave ghosts: a quieter note an
    octave (or octave + 5th, two octaves) above a note starting with it is usually that
    string's harmonic, not a second string."""
    if not notes:
        return notes
    top = np.percentile([n["amp"] for n in notes], 90)
    notes = [n for n in notes if n["amp"] >= min_amp * top]
    keep = []
    for n in notes:
        if any(o is not n and n["midi"] - o["midi"] in (12, 19, 24) and abs(o["t"] - n["t"]) < 0.04
               and n["amp"] < ghost * o["amp"] for o in notes):
            continue
        keep.append(n)
    return keep


def estimate_bpm(path):
    import librosa
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    return float(np.atleast_1d(tempo)[0])


# ── rhythm ──────────────────────────────────────────────────────────────────────────────────
def find_beat_phase(notes, beat):
    """Time of beat 1: the phase that puts the (loudness-weighted) onsets on the 16th grid,
    on the 16th nearest the first note - a riff starts on beat 1 unless the user says otherwise."""
    t = np.array([n["t"] for n in notes])
    w = np.array([n["amp"] for n in notes])
    s16 = beat / 4
    phases = np.arange(0, s16, 0.002)
    err = [np.sum(w * np.abs((t - p) / s16 - np.round((t - p) / s16))) for p in phases]
    p16 = phases[int(np.argmin(err))]
    first = t.min()
    return p16 + np.round((first - p16) / s16) * s16


def track_beats(path, bpm):
    """The beats as played: players (and generated music) drift off a steady tempo, so the grid
    follows the music, with the user's BPM as the guide. None when the tracker can't find a
    beat near that tempo (then the grid is steady)."""
    import librosa
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    _, beats = librosa.beat.beat_track(y=y, sr=sr, hop_length=128, start_bpm=bpm, tightness=300,
                                       units="time", trim=False)
    if len(beats) < 8:
        return None
    beats = np.asarray(beats, dtype=float)
    period = float(np.median(np.diff(beats)))
    if abs(period * bpm / 60 - 1) > 0.15:
        return None
    # each beat from a straight line through its neighbours (8 either side): follows a drifting
    # tempo, not the tracker's jitter
    idx = np.arange(len(beats), dtype=float)
    sm = np.empty_like(beats)
    for i in range(len(beats)):
        a, b = max(0, i - 8), min(len(beats), i + 9)
        k, c = np.polyfit(idx[a:b], beats[a:b], 1)
        sm[i] = k * i + c
    return sm


def beat_position(t, beats):
    """Seconds -> position in beats along the tracked beats (straight lines past the ends)."""
    t = np.asarray(t, dtype=float)
    idx = np.arange(len(beats), dtype=float)
    pos = np.interp(t, beats, idx)
    p0, p1 = beats[1] - beats[0], beats[-1] - beats[-2]
    pos = np.where(t < beats[0], (t - beats[0]) / p0, pos)
    return np.where(t > beats[-1], idx[-1] + (t - beats[-1]) / p1, pos)


def quantize(notes, bpm, offset=None, triplets=True, beats=None):
    """Onsets and ends -> integer ticks from the first bar line (TPB ticks a quarter).
    Each beat is snapped to 16ths, or to 8th triplets when they fit clearly better.
    With tracked beats the grid follows them; otherwise it is steady at the BPM."""
    beat = 60.0 / bpm
    if beats is not None and offset is None:
        # the tracker's beats can sit a fraction of a beat off the notes: find the phase that puts
        # the onsets on the 16th grid, and make the first note beat 1 (as on the steady grid)
        pos = beat_position([n["t"] for n in notes], beats)
        w = np.array([n["amp"] for n in notes])
        phases = np.arange(0, 0.25, 0.005)
        err = [np.sum(w * np.abs((pos - ph) * 4 - np.round((pos - ph) * 4))) for ph in phases]
        ph = phases[int(np.argmin(err))]
        b0 = float(ph + np.round((pos.min() - ph) * 4) / 4)
        for n in notes:
            n["b"] = float(beat_position(n["t"], beats)) - b0
            n["be"] = float(beat_position(n["end"], beats)) - b0
        idx = np.arange(len(beats), dtype=float)
        offset = float(np.interp(b0, idx, beats)) if 0 <= b0 < len(beats) else beats[0] + b0 * (beats[1] - beats[0])
    else:
        if offset is None:
            offset = find_beat_phase(notes, beat)
        for n in notes:
            n["b"] = (n["t"] - offset) / beat
            n["be"] = (n["end"] - offset) / beat
    by_beat = {}
    for n in notes:
        by_beat.setdefault(int(np.floor(n["b"] + 1 / 8)), []).append(n)   # a hair early still counts
    for b, group in by_beat.items():
        pos = np.array([n["b"] - b for n in group])
        e16 = np.abs(pos * 4 - np.round(pos * 4)).sum() / 4
        e3 = np.abs(pos * 3 - np.round(pos * 3)).sum() / 3
        trip = triplets and len({round(p * 3) for p in pos}) >= 2 and e3 < 0.5 * e16 and e16 > 0.03
        step = 4 if trip else 3
        for n in group:
            n["tick"] = b * TPB + int(round((n["b"] - b) * TPB / step)) * step
            n["miss"] = abs(n["b"] * TPB - n["tick"]) / TPB          # how far off the grid, in beats
    for n in notes:
        n["tick_end"] = max(n["tick"] + 3, int(round(n["be"] * 4)) * 3)
    first_tick = min(n["tick"] for n in notes)
    shift = int(np.floor(first_tick / TPB)) * TPB
    for n in notes:
        n["tick"] -= shift
        n["tick_end"] -= shift
    return offset + shift / TPB * beat if beats is None else offset


@dataclass
class Event:
    tick: int
    pitches: list                   # MIDI, low to high
    amps: list
    end: int                        # when the notes stop sounding
    frets: list = field(default_factory=list)    # (string index, fret) per kept pitch


def group_events(notes, max_notes):
    ev = {}
    for n in notes:
        e = ev.setdefault(n["tick"], {})
        if n["midi"] not in e or e[n["midi"]][0] < n["amp"]:
            e[n["midi"]] = (n["amp"], n["tick_end"])
    out = []
    for tick in sorted(ev):
        items = sorted(ev[tick].items(), key=lambda kv: -kv[1][0])[:max_notes]   # loudest first
        items.sort()
        out.append(Event(tick, [m for m, _ in items], [a for _, (a, _) in items], max(e for _, (_, e) in items)))
    return out


# ── strings and frets ───────────────────────────────────────────────────────────────────────
def fingerings(pitches, tuning, max_span=4):
    """Every way to play these pitches together: one string each, fretted notes within a
    hand span. Returns [(string, fret) per pitch]."""
    opts = []
    for p in pitches:
        o = [(s, p - open_) for s, open_ in enumerate(tuning) if 0 <= p - open_ <= MAX_FRET]
        if not o:
            return []
        opts.append(o)
    res = []
    for combo in product(*opts):
        strings = [s for s, _ in combo]
        if len(set(strings)) != len(strings):
            continue
        fr = [f for _, f in combo if f > 0]
        if fr and max(fr) - min(fr) > max_span:
            continue
        res.append(list(combo))
    return res


# fingering costs (tuned on GuitarSet: tests/tune_frets.py)
W = dict(fret=0.0, high=0.767, skip=1.165, stretch=0.666, move=1.346, move_d=0.364, pos=0.0, open_high=0.0,
         ring=0.653, speed_max=2.152)


def assign_frets(events, tuning, w=None):
    """Choose a fingering for every event (Viterbi). The fretting hand sits at a position:
    the index finger's fret, covering that fret and the next three (a stretch to a fifth costs
    a little). Moving the hand costs; staying in position across strings is free, as are open
    strings. Chords that skip a string in the middle cost extra, and so does going high."""
    w = {**W, **(w or {})}

    def static(c):
        fr = [f for _, f in c if f > 0]
        cost = w["fret"] * (sum(fr) / len(fr) if fr else 0) + w["high"] * (bool(fr) and max(fr) > 12)
        strings = sorted(s for s, _ in c)
        cost += w["skip"] * sum(b - a - 1 for a, b in zip(strings, strings[1:]))      # skipped strings
        return cost

    def positions(c):
        """Hand positions this fingering can be played from (None: open strings only)."""
        fr = [f for _, f in c if f > 0]
        if not fr:
            return [None]
        return [(p, w["stretch"] if max(fr) - p == 4 else 0.0) for p in range(max(1, max(fr) - 4), min(fr) + 1)]

    layers = []
    for e in events:
        pitches, amps = list(e.pitches), list(e.amps)
        cands = fingerings(pitches, tuning)
        while not cands and len(pitches) > 1:            # unplayable together: drop the faintest note
            i = int(np.argmin(amps))
            pitches.pop(i); amps.pop(i)
            cands = fingerings(pitches, tuning)
        e.pitches, e.amps = pitches, amps
        layers.append(cands)

    # states: (fingering index, hand position) -> (cost, back pointer to a state of the layer before)
    prev = None
    back = []
    for li, cands in enumerate(layers):
        cur = {}
        if not cands:                                   # nothing playable here: carry the paths through
            cur = {(-1, k[1]): (v[0], k) for k, v in prev.items()} if prev else {}
            back.append(cur); prev = cur or prev
            continue
        gap = max(1, events[li].tick - events[li - 1].tick) if li else 12
        speed = min(w["speed_max"], max(1.0, 6 / gap))              # moving the hand is harder in fast passages
        ringing = li and events[li - 1].end > events[li].tick + 2      # the note before still sounds
        for ci, c in enumerate(cands):
            sc = static(c)
            for ps in positions(c):
                if prev is None:
                    p, stretch = (None, 0.0) if ps is None else ps
                    cur[(ci, p)] = (sc + stretch + w["pos"] * (p or 0), None)
                    continue
                for (pci, pp), (pcost, _) in prev.items():
                    n_open = sum(1 for _, f in c if f == 0)
                    if ps is None:                       # open strings: the hand stays where it was
                        key, extra = (ci, pp), 0.0
                    else:
                        p, stretch = ps
                        key = (ci, p)
                        extra = stretch + (0.0 if pp is None or pp == p else (w["move"] + w["move_d"] * abs(p - pp)) * speed)
                    if ringing and pci >= 0:                         # don't cut off a string that rings on
                        used = {st for st, _ in layers[li - 1][pci]}
                        extra += w["ring"] * sum(1 for st, _ in c if st in used)
                    hand = key[1]
                    extra += w["pos"] * (hand or 0)                     # staying up the neck costs a little, every note
                    if n_open and hand is not None and hand > 4:    # an open string while playing high up
                        extra += w["open_high"] * (hand - 4) * n_open
                    tot = pcost + sc + extra
                    if key not in cur or tot < cur[key][0]:
                        cur[key] = (tot, (pci, pp))
        back.append(cur)
        prev = cur
    if not back or not back[-1]:
        return
    key = min(back[-1], key=lambda k: back[-1][k][0])
    for li in range(len(layers) - 1, -1, -1):
        ci = key[0]
        events[li].frets = layers[li][ci] if ci >= 0 and layers[li] else []
        key = back[li][key][1]
        if key is None:
            break


# ── layout ──────────────────────────────────────────────────────────────────────────────────
DUR = [(48, "w"), (36, "h."), (24, "h"), (18, "q."), (12, "q"), (9, "e."), (8, "q3"), (6, "e"), (4, "e3"), (3, "s"), (2, "s3"), (1, "t")]


def split_dur(ticks):
    out = []
    for t, name in DUR:
        while ticks >= t:
            out.append((t, name)); ticks -= t
    return out


def build_items(events, bar_ticks):
    """Events -> timeline items (note / rest / tied continuation), cut at bar lines and into
    note values that exist. An item: dict(tick, ticks, kind, frets, sym)."""
    items = []
    for i, e in enumerate(events):
        nxt = events[i + 1].tick if i + 1 < len(events) else max(e.end, e.tick + 3)
        gap = nxt - e.tick
        sound = min(gap, max(3, e.end - e.tick))
        if gap - sound < 6:                          # less than an 8th of silence: let it ring
            sound = gap
        segs = [(e.tick, sound, "note"), (e.tick + sound, gap - sound, "rest")]
        for start, length, kind in segs:
            t = start
            first = True
            while length > 0:
                room = bar_ticks - (t % bar_ticks)
                chunk = min(length, room)
                for d, name in split_dur(chunk):
                    k = kind if not (kind == "note" and not first) else "tie"
                    items.append(dict(tick=t, ticks=d, kind=k, frets=e.frets if k == "note" else [], sym=name))
                    t += d; first = False
                length -= chunk
    return items


def render_tab(items, tuning, bar_ticks, header, width=110):
    S = len(tuning)
    labels = []
    for s, m in enumerate(tuning):
        name = NAMES[m % 12]
        labels.append(name.lower() if s == S - 1 and name == NAMES[tuning[0] % 12] else name)
    lw = max(len(l) for l in labels)
    bars = {}
    for it in items:
        bars.setdefault(it["tick"] // bar_ticks, []).append(it)
    n_bars = max(bars) + 1 if bars else 0

    def bar_cols(its):
        cols = []
        for it in its:
            cell = [""] * S
            for s, f in it["frets"]:
                cell[s] = str(f)
            sym = it["sym"] if it["kind"] == "note" else ("r" + it["sym"] if it["kind"] == "rest" else "~" + it["sym"])
            w = max(max(len(c) for c in cell) + 1, len(sym) + 1, it["ticks"] * 2 // 3)
            cols.append((cell, sym, w))
        return cols

    out = [header, ""]
    row, row_w = [], 0
    rows = []
    for b in range(n_bars):
        cols = bar_cols(bars.get(b, [dict(tick=b * bar_ticks, ticks=bar_ticks, kind="rest", frets=[], sym="w")]))
        bw = sum(w for _, _, w in cols) + 2
        if row and row_w + bw > width - lw - 2:
            rows.append(row); row, row_w = [], 0
        row.append((b, cols, bw)); row_w += bw
    if row:
        rows.append(row)
    for r in rows:
        num = " " * (lw + 1)
        lines = [labels[s].rjust(lw) + "|" for s in range(S - 1, -1, -1)]
        rhythm = " " * (lw + 1)
        for b, cols, bw in r:
            num += str(b + 1).ljust(bw)
            for i, s in enumerate(range(S - 1, -1, -1)):
                lines[i] += "-" + "".join(c[s].ljust(w, "-") for c, _, w in cols) + "|"
            rhythm += " " + "".join(sym.ljust(w) for _, sym, w in cols) + " "
        out += [num.rstrip()] + lines + [rhythm.rstrip(), ""]
    out.append("Rhythm: w whole, h half, q quarter, e 8th, s 16th, t 32nd; . dotted; 3 triplet; r rest; ~ held over.")
    return "\n".join(out)


# ── main ────────────────────────────────────────────────────────────────────────────────────
def beat_time(pos, beats):
    """Position in beats along the tracked beats -> seconds (straight lines past the ends)."""
    idx = np.arange(len(beats), dtype=float)
    if pos < 0:
        return float(beats[0] + pos * (beats[1] - beats[0]))
    if pos > idx[-1]:
        return float(beats[-1] + (pos - idx[-1]) * (beats[-1] - beats[-2]))
    return float(np.interp(pos, idx, beats))


def transcribe(path, tuning, bpm, time_sig=(4, 4), offset=None, min_amp=0.1, triplets=True, follow=True, cache=None):
    notes = detect_notes(path, tuning, cache=cache)
    lo, hi = tuning[0], tuning[-1] + MAX_FRET
    notes = clean_notes([dict(n) for n in notes if lo <= n["midi"] <= hi], min_amp)
    if not notes:
        return None
    beats = track_beats(path, bpm) if follow and offset is None else None
    if beats is not None:
        # keep whichever grid the notes sit on better: steady (played to a click) or following
        import copy
        steady = copy.deepcopy(notes)
        b_steady = quantize(steady, bpm, offset, triplets)
        b_follow = quantize(notes, bpm, offset, triplets, beats)
        miss = lambda ns: float(np.average([n["miss"] for n in ns], weights=[n["amp"] for n in ns]))
        if miss(steady) <= miss(notes):
            notes, beats, beat1 = steady, None, b_steady
        else:
            beat1 = b_follow
    else:
        beat1 = quantize(notes, bpm, offset, triplets)
    events = group_events(notes, len(tuning))
    assign_frets(events, tuning)
    events = [e for e in events if e.frets]
    bar_ticks = time_sig[0] * TPB * 4 // time_sig[1]
    items = build_items(events, bar_ticks)
    # when each beat falls, from bar 1 (for a cursor that follows the recording)
    n_beats = (max((it["tick"] + it["ticks"] for it in items), default=0) // TPB) + 2
    if beats is not None:
        origin = float(beat_position(beat1, beats))
        beat_times = [beat_time(origin + k, beats) for k in range(n_beats)]
    else:
        beat_times = [beat1 + k * 60.0 / bpm for k in range(n_beats)]
    return dict(notes=notes, events=events, items=items, bar_ticks=bar_ticks, beat1=beat1, followed=beats is not None,
                beat_times=beat_times)


def preview_wav(events, bpm, tuning, path):
    """The tab played back (plucked-string synth), to compare with the original by ear."""
    import soundfile as sf
    from ks import render, SR
    sec = 60.0 / bpm / TPB
    notes = []
    for e in events:
        for s, f in e.frets:
            notes.append((e.tick * sec, max(0.15, (e.end - e.tick) * sec), tuning[s] + f, 0.5))
    sf.write(str(path), render(notes), SR)


def app(argv):
    """Philibert's app mode: one JSON job in, JSON out on the last line; progress lines before it
    start with "STEP "."""
    cmd, job = argv[0], json.loads(argv[1]) if len(argv) > 1 else {}
    if cmd == "check":
        import logging
        logging.disable(logging.WARNING)
        import basic_pitch.inference   # noqa: F401
        import librosa                 # noqa: F401
        import onnxruntime             # noqa: F401
        print(json.dumps({"ok": True}))
        return 0
    if cmd == "estimate":
        print(json.dumps({"ok": True, "bpm": round(estimate_bpm(job["audio"]), 1)}))
        return 0
    if cmd == "transcribe":
        tuning = [int(m) for m in job["tuning"]]
        num, den = job.get("time", [4, 4])
        print("STEP notes", flush=True)
        detect_notes(job["audio"], tuning, cache=job.get("cache"))
        print("STEP tab", flush=True)
        r = transcribe(job["audio"], tuning, float(job["bpm"]), (int(num), int(den)), job.get("offset"),
                       triplets=job.get("triplets", True), follow=not job.get("steady"), cache=job.get("cache"))
        if r is None:
            print(json.dumps({"ok": False, "msg": "No guitar notes found in this recording."}))
            return 0
        out = dict(ok=True, tuning=tuning, bpm=float(job["bpm"]), time=[int(num), int(den)], tpb=TPB,
                   bar_ticks=r["bar_ticks"], beat1=r["beat1"], followed=r["followed"], beat_times=r["beat_times"],
                   items=[dict(tick=it["tick"], ticks=it["ticks"], kind=it["kind"], sym=it["sym"],
                               frets=[list(f) for f in it["frets"]]) for it in r["items"]],
                   events=[dict(tick=e.tick, end=e.end, frets=[list(f) for f in e.frets]) for e in r["events"]])
        Path(job["out"]).write_text(json.dumps(out), encoding="utf-8")
        print(json.dumps({"ok": True, "events": len(r["events"])}))
        return 0
    print(json.dumps({"ok": False, "msg": f"unknown command {cmd}"}))
    return 2


def main(argv=None):
    ap = argparse.ArgumentParser(description="Guitar audio to tablature (prototype)")
    ap.add_argument("audio")
    ap.add_argument("--bpm", type=float, help="tempo; leave out to get an estimate")
    ap.add_argument("--strings", type=int)
    ap.add_argument("--tuning", help='low to high, e.g. "D A D G B E", or a preset: ' + ", ".join(PRESETS))
    ap.add_argument("--time", default="4/4", help="time signature (default 4/4)")
    ap.add_argument("--offset", type=float, help="seconds where beat 1 of bar 1 falls (default: found)")
    ap.add_argument("--min-amp", type=float, default=0.1, help="drop notes fainter than this share of the loud ones")
    ap.add_argument("--no-triplets", action="store_true")
    ap.add_argument("--steady", action="store_true", help="a steady grid at the BPM (recorded to a click) instead of following the beat")
    ap.add_argument("-o", "--out", help="tab text file (default: next to the audio)")
    ap.add_argument("--preview", action="store_true", help="also write <out>.preview.wav")
    a = ap.parse_args(argv)

    src = Path(a.audio)
    tuning = parse_tuning(a.tuning, a.strings)
    if not a.bpm:
        print(f"Estimated tempo: {estimate_bpm(src):.1f} BPM - run again with --bpm", file=sys.stderr)
        return 2
    num, den = (int(x) for x in a.time.split("/"))
    r = transcribe(src, tuning, a.bpm, (num, den), a.offset, a.min_amp, not a.no_triplets, not a.steady)
    if r is None:
        print("No notes found.", file=sys.stderr)
        return 1
    header = (f"{src.name}\nTuning: {' '.join(note_name(m) for m in tuning)} ({len(tuning)} strings)   "
              f"Tempo: {a.bpm:g} BPM{' (following the beat)' if r['followed'] else ''}   Time: {num}/{den}   Beat 1 at {r['beat1']:.3f} s")
    text = render_tab(r["items"], tuning, r["bar_ticks"], header)
    out = Path(a.out) if a.out else src.with_suffix(".tab.txt")
    out.write_text(text + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(dict(
        tuning=tuning, bpm=a.bpm, time=[num, den], beat1=r["beat1"],
        events=[dict(tick=e.tick, end=e.end, pitches=e.pitches, frets=e.frets) for e in r["events"]],
        notes=[{k: n[k] for k in ("t", "end", "midi", "amp", "tick")} for n in r["notes"]]), indent=1))
    if a.preview:
        preview_wav(r["events"], a.bpm, tuning, out.with_suffix(".preview.wav"))
    print(text)
    print(f"\nWrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "app":
        sys.exit(app(sys.argv[2:]))
    sys.exit(main())
