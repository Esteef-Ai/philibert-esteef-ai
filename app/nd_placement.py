"""Turn an open request into PLACED edits, one per fresh context.

Measured on qwen3-coder:30b against the LeninShop benchmark, same model and same
context, varying only how the job was put:

    exact edit given          -> edit_file, valid anchor, 3.0s
    told WHERE, not WHAT      -> edit_file, valid anchor, 10.4s
    open request              -> plans, defers, never edits

Four cheaper explanations were tested and killed first (num_predict, the system
prompt, ND's own [FILE] markers, context size up to 15,576 tokens). The model
executes a PLACED edit reliably and cannot produce one from an open request.

So ND supplies the placement. "Add a stats endpoint with a schema and tests"
becomes three instructions of the shape the model demonstrably handles:

    add GET /stats to app/routers/public.py, after `def list_items(`
    add a by_decade field to StatsOut in app/schemas.py
    add tests for /api/stats to scripts/test_public.py

This module is the pure logic of that: the planning prompt, parsing, and -- the
part that actually matters -- VALIDATING that every anchor exists exactly once in
the file it names. An anchor the model invented makes its step impossible, and
that is checkable on disk for nothing, before a single subagent is spent on it.

Same shape as nd_build_plan.py, which does the equivalent for whole files.
"""

from __future__ import annotations

import ast as _ast
import json
import re
from pathlib import Path
from typing import Optional

__all__ = ["looks_like_change", "plan_prompt", "parse_placements",
           "validate_placements", "step_prompt", "symbol_from_anchor",
           "find_dependents", "dependents_block", "find_dispatcher",
           "new_functions", "auto_register", "find_test_harness",
           "harness_block", "dispatcher_block", "retry_prompt",
           "Placement", "PlacementPlan"]

MAX_STEPS = 8
MAX_ANCHOR_CHARS = 400
POSITIONS = ("after", "before", "replace")


# ── when this applies ─────────────────────────────────────────────────────────
# NOT looks_multi_step: that detects sequencing language ("first ... then ...")
# and was built for plan seeding. The T3 benchmark prompt has none of it and was
# silently skipped, so the whole mechanism never ran. The signal that matters
# here is different and simpler: is this a CHANGE to code that already exists?
_CHANGE_VERB_RE = re.compile(
    r"\b(?:add|adds|adding|change|changes|changing|update|updates|updating|"
    r"fix|fixes|fixing|modify|modifies|modifying|extend|extends|extending|"
    r"implement|implements|implementing|remove|removes|removing|rename|renames|"
    r"refactor|refactors|wire|wires|hook up|support|expose|introduce)\b", re.I)

# "Do not modify", "never change", "without editing" -- the verb is there and the
# request is the opposite of it.
_NEGATED_VERB_RE = re.compile(
    # Stems, not whole words: "without changing" has to match, and "change"
    # is not a substring of "changing".
    r"\b(?:do\s+not|don't|never|avoid|without)\s+(?:\w+\s+){0,2}"
    r"(?:add|chang|updat|fix|modif|extend|implement|remov|renam|refactor|"
    r"wir|touch|edit|alter)\w*", re.I)

# A DIAGNOSIS is not a placement task. "The test suite is failing, find the cause
# and fix it" contains "fix", so it matched -- and placed edits then handed the
# model a planner-chosen spot for a bug whose location nobody knows, including
# the planner. Measured: T4 fell from 6/6 to 1/6, with +53/-1 lines written to
# app/routers/public.py for a one-word bug in app/services/items.py. The ordinary
# loop, where the model reads the failure and hunts, is what scored 6/6.
_DIAGNOSE_RE = re.compile(
    r"\b(?:diagnose|root cause|find (?:the |out )?(?:cause|bug|problem)|"
    r"figure out why|work out why|track down|"
    r"(?:test|suite|build|it)s? (?:is |are |now )?fail(?:s|ing|ed)?|"
    r"failing (?:test|check|suite)|traceback|stack trace)", re.I)

# A question about the code is not a request to change it.
_ASK_ONLY_RE = re.compile(
    r"^\s*(?:what|why|how|where|when|which|who|is|are|does|do|can|could|should|"
    r"explain|describe|tell me|show me|summarise|summarize|list)\b", re.I)


def looks_like_change(text: str, min_len: int = 60) -> bool:
    """Is this a request to change an existing codebase?

    Deliberately not narrow the way looks_like_build is: a false positive costs
    one planning call (~30s), while a false negative costs the whole mechanism,
    which is what happened when this was gated on sequencing words instead.
    The caller still checks that there IS an existing codebase to change.
    """
    t = (text or "").strip()
    if len(t) < min_len:
        return False
    # Diagnosis wins even when a change verb is present: "find the cause and fix
    # it" is both, and the FINDING is the job. Handing that a planner-chosen
    # placement is worse than useless.
    if _DIAGNOSE_RE.search(t):
        return False
    # Then strip negated verbs. Measured: T2's prompt says "Do not modify any
    # existing file", and that "modify" is what sent a three-new-files build into
    # the change-existing-code path. The sentence forbidding edits must not be
    # the thing that asks for them.
    probe = _NEGATED_VERB_RE.sub(" ", t)
    if _ASK_ONLY_RE.match(t) and not _CHANGE_VERB_RE.search(probe):
        return False
    return bool(_CHANGE_VERB_RE.search(probe))


# ── the planning call ─────────────────────────────────────────────────────────

PLAN_PROMPT = """Plan this change as a list of PLACED edits. Do not write the code yet and do not call any tools.

THE REQUEST:
{task}

FILES YOU MAY EDIT (with their sizes):
{files}

{excerpts}
Reply with ONE json array and nothing else. Each element:

  {{
    "file": "<one of the paths listed above, copied exactly>",
    "anchor": "<a SHORT run of text copied VERBATIM from that file>",
    "position": "after",
    "what": "<one line: what to add there>"
  }}

Rules:
- The anchor must be text you have actually SEEN in that file, copied character
  for character. It is used to find the spot; if it is not in the file the step
  is thrown away. Pick something that appears ONCE - a def line, a class line, a
  distinctive comment. Two or three lines is ideal, never more than ten.
- "position" is "after", "before", or "replace".
- One step per place that must change. Steps run in order, each in isolation.
- ONE addition is ONE step. A decorator and the function under it go in together,
  in a single step, at a single anchor. Splitting them across two steps puts them
  in two different places and produces a broken file.
- "what" is a DESCRIPTION, not code. "a GET /stats endpoint returning counts by
  format", not the def line itself.
- At most {max_steps} steps. Fewer is better.
- Do NOT plan a step for a file that is not in the list above.
- Do NOT put the code in "what". Say what belongs there in one line; the step
  itself writes it.
"""


def plan_prompt(task: str, files: list, excerpts: str = "", max_steps: int = MAX_STEPS) -> str:
    """The planning call. `files` is [(path, bytes)]."""
    listing = "\n".join(f"  {p}  ({n:,} bytes)" for p, n in files) or "  (none)"
    block = (f"RELEVANT EXCERPTS -- copy your anchors from these:\n{excerpts}\n\n"
             if excerpts else "")
    return PLAN_PROMPT.format(task=task.strip(), files=listing, excerpts=block,
                              max_steps=max_steps)


def _first_json_array(text: str) -> Optional[list]:
    """The first well-formed JSON array in a reply, brace-matched.

    A regex cannot do this: anchors legitimately contain brackets and braces, so
    the greedy match ends in the wrong place and the whole plan is discarded.
    """
    if not text:
        return None
    start = text.find("[")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c in "[{":
                depth += 1
            elif c in "]}":
                depth -= 1
                if depth == 0:
                    try:
                        val = json.loads(text[start:i + 1])
                        if isinstance(val, list):
                            return val
                    except Exception:
                        pass
                    break
        start = text.find("[", start + 1)
    return None


def parse_placements(text: str, allowed_files=None, max_steps: int = MAX_STEPS) -> list:
    """Read the planner's reply into a list of placement dicts.

    Shape only -- whether the anchors actually exist is validate_placements'
    job, because that needs the disk.
    """
    raw = _first_json_array(text)
    if raw is None:
        return []
    allowed = {str(f).replace("/", "\\").lower() for f in (allowed_files or [])}
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        f = str(item.get("file") or item.get("path") or "").strip().strip('"').strip("'")
        anchor = item.get("anchor") or item.get("old_text") or item.get("after") or ""
        what = str(item.get("what") or item.get("purpose") or item.get("change") or "").strip()
        pos = str(item.get("position") or "after").strip().lower()
        if pos not in POSITIONS:
            pos = "after"
        if not f or not isinstance(anchor, str) or not anchor.strip() or not what:
            continue
        if allowed and f.replace("/", "\\").lower() not in allowed:
            continue          # a file nobody offered it
        out.append({"file": f, "anchor": anchor[:MAX_ANCHOR_CHARS],
                    "position": pos, "what": what[:300]})
        if len(out) >= max_steps:
            break
    return out


# ── the part that earns its place ─────────────────────────────────────────────

def _norm(s: str) -> str:
    """Collapse whitespace, for a forgiving second attempt at a match."""
    return re.sub(r"\s+", " ", s).strip()


def locate_anchor(body: str, anchor: str, position: str = "after"):
    """Find the anchor in the file. Returns (matched_text, how) or (None, why).

    Models get indentation slightly wrong far more often than they get the words
    wrong, so an exact miss is retried on whitespace-insensitive terms and then
    on the anchor's most distinctive single line. Anything recovered is returned
    as the text ACTUALLY in the file, so the caller can hand edit_file something
    that will match.
    """
    if not anchor.strip():
        return None, "empty anchor"
    n = body.count(anchor)
    if n == 1:
        return anchor, "exact"
    if n > 1:
        return None, f"appears {n} times - not unique"

    # Whitespace-tolerant: find the span whose normalised form matches.
    want = _norm(anchor)
    if want:
        lines = body.splitlines(keepends=True)
        for size in range(1, min(12, len(lines)) + 1):
            for i in range(len(lines) - size + 1):
                span = "".join(lines[i:i + size])
                if _norm(span) == want:
                    if body.count(span) == 1:
                        return span, "matched ignoring whitespace"
                    return None, "matched but not unique"

    # Last resort: the anchor's longest line, if that alone is unique.
    cand = sorted((l.strip() for l in anchor.splitlines() if l.strip()),
                  key=len, reverse=True)
    for line in cand[:3]:
        if len(line) >= 12 and body.count(line) == 1:
            for raw in body.splitlines(keepends=True):
                if line in raw:
                    return raw, "narrowed to its most distinctive line"

    # Closest line. A near-miss -- "from app.schemas import ItemOut, ItemPage"
    # for the file's "from ..schemas import ItemOut, ItemPage, ItemRequestIn" --
    # threw the whole step away (2026-10-18). The anchor only says WHERE the
    # step works; the step's own edit must still match the file exactly, so a
    # close, UNIQUE line is a safe place. "replace" asks for near-identity.
    want_line = cand[0] if cand else ""
    if len(want_line) >= 12:
        import difflib
        floor = 0.92 if position == "replace" else 0.75
        scored = []
        for raw in body.splitlines(keepends=True):
            t = raw.strip()
            if len(t) >= 8:
                scored.append((difflib.SequenceMatcher(None, want_line, t).ratio(), raw))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] >= floor                 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08)                 and body.count(scored[0][1]) == 1:
            return scored[0][1], f"closest line ({scored[0][0]:.2f} similar)"
    return None, "not found in the file"


def validate_placements(placements: list, workspace: str) -> tuple:
    """Split a plan into steps that can actually run, and steps that cannot.

    Returns (usable, rejected). Rejected entries carry a `why`, because a plan
    that silently loses half its steps is worse than one that says so.
    """
    ws = Path(workspace) if workspace else None
    usable, rejected = [], []
    for p in placements:
        raw = str(p.get("file") or "")
        path = Path(raw)
        if not path.is_absolute() and ws:
            path = ws / raw
        if not path.is_file():
            rejected.append(dict(p, why=f"no such file: {path}"))
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            rejected.append(dict(p, why=f"unreadable: {e}"))
            continue
        found, how = locate_anchor(body, p["anchor"], str(p.get("position") or "after"))
        if not found:
            rejected.append(dict(p, why=f"anchor {how}"))
            continue
        usable.append(dict(p, file=str(path), anchor=found, matched=how,
                           bytes=len(body)))
    return usable, rejected


# ── who else depends on this ──────────────────────────────────────────────────
# A placement's anchor almost always names the thing being changed -- "class
# StatsOut(BaseModel):", "def paginate(". If that name is used in other files,
# changing it has consequences the model will not go looking for.
DEP_SCAN_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".mjs"}
DEP_SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git",
                 ".nd_backups", "dist", "build", "vendor", ".pytest_cache",
                 # Retired code. Must match the launcher's PLACE_SKIP_DIRS (a test
                 # checks). Measured 2026-09-25: a correct edit removing a constant
                 # was REFUSED because a file in archive/ still used it, and the
                 # job ended with nothing changed.
                 "archive", "archived", "_archive", "old", "deprecated"}
DEP_MAX_FILES = 400
DEP_MAX_HITS = 6

# An import mentions the name; it does not show what depends on it.
_IMPORT_LINE_RE = re.compile(
    r"^(?:from\s|import\s|\s*[A-Za-z_][A-Za-z0-9_]*,\s*$|\s*[A-Za-z_][A-Za-z0-9_]*\s*$)")

_DEF_ANCHOR_RE = re.compile(
    r"^\s*(?:async\s+)?(?:class|def|function)\s+([A-Za-z_][A-Za-z0-9_]*)"
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=")


_TYPE_ANCHOR_RE = re.compile(r"^\s*(?:export\s+)?(?:class|interface|type|struct)\s+")


def _is_type_anchor(anchor: str) -> bool:
    """Does this anchor sit on a TYPE definition?

    The narrowing that makes the dependents warning worth having. A shared type
    gains a required field and every producer of it breaks at runtime; a function
    that merely has a new sibling added after it breaks nothing.
    """
    return any(_TYPE_ANCHOR_RE.match(l) for l in (anchor or "").splitlines())


def symbol_from_anchor(anchor: str):
    """The name a placement is about, if its anchor defines one.

    Returns None for anchors that are not definitions -- a decorator line, a
    return statement, a comment. Those have no symbol to trace, and guessing one
    would produce noise on every step.
    """
    for line in (anchor or "").splitlines():
        m = _DEF_ANCHOR_RE.match(line)
        if m:
            return m.group(1) or m.group(2)
    return None


def defines_name(stripped, symbol):
    """Is this line the file's own definition of `symbol`, rather than a use?

    Deliberately literal. A same-named route handler or module constant is the
    commonest false dependent, and both are recognisable from the line alone.
    """
    if not stripped or not symbol:
        return False
    for kw in ("def ", "async def ", "class "):
        if stripped.startswith(kw + symbol):
            rest = stripped[len(kw) + len(symbol):].lstrip()
            if rest[:1] in ("(", ":", ""):
                return True
    if stripped.startswith(symbol):
        rest = stripped[len(symbol):].lstrip()
        # SORTS = {...} and SORTS: dict = {...}, but never SORTS == x
        if rest.startswith("=") and not rest.startswith("=="):
            return True
        if rest.startswith(":") and "=" in rest:
            return True
    return False


def find_dependents(symbol, workspace, exclude_file=None, max_hits=DEP_MAX_HITS,
                    skip_defs=False):
    """Other files that mention `symbol`. Returns [(path, lineno, text)].

    A plain word-boundary scan, not an import graph: it wants to warn, not to
    prove, and a false positive costs one line of prompt while a false negative
    costs a broken suite.
    """
    if not symbol or len(symbol) < 3 or not workspace:
        return []
    ws = Path(workspace)
    try:
        excl = Path(exclude_file).resolve() if exclude_file else None
    except OSError:
        excl = None
    pat = re.compile(r"\b" + re.escape(symbol) + r"\b")
    hits, seen_files = [], 0
    try:
        for p in ws.rglob("*"):
            if seen_files >= DEP_MAX_FILES or len(hits) >= max_hits:
                break
            if not p.is_file() or p.suffix.lower() not in DEP_SCAN_EXT:
                continue
            try:
                if any(part in DEP_SKIP_DIRS for part in p.relative_to(ws).parts):
                    continue
            except ValueError:
                continue
            try:
                if excl and p.resolve() == excl:
                    continue
            except OSError:
                pass
            seen_files += 1
            try:
                body = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if symbol not in body:
                continue
            # One hit per file is enough to warn, but WHICH hit matters. An
            # import line ("StatsOut,") tells the model nothing; the line that
            # actually builds or returns the thing is what shows the risk. Take
            # the first real usage, and fall back to the import only if that is
            # all there is.
            first, usage = None, None
            for i, line in enumerate(body.splitlines(), 1):
                if not pat.search(line):
                    continue
                stripped = line.strip()
                # A file that DEFINES its own thing by the same name is not a
                # dependent of ours. Measured: the rewrite guard quoted
                # "SORTS = {" from a module with its own unrelated SORTS, and
                # quoted "def delete_photo(...)" -- a route handler that merely
                # shares a name -- instead of the svc.delete_photo() call two
                # lines further down that actually breaks.
                if skip_defs and defines_name(stripped, symbol):
                    continue
                if first is None:
                    first = (str(p), i, stripped[:100])
                if not _IMPORT_LINE_RE.match(stripped):
                    usage = (str(p), i, stripped[:100])
                    break
            if usage or first:
                hits.append(usage or first)
    except OSError:
        return hits
    return hits[:max_hits]


def dependents_block(symbol, deps):
    """The caution handed to the step. Empty when there is nothing to say."""
    if not symbol or not deps:
        return ""
    lines = "\n".join(f"  {Path(f).name}:{n}  {t}" for f, n, t in deps)
    return (f"\nCAUTION - `{symbol}` is also used in {len(deps)} other place"
            f"{'s' if len(deps) != 1 else ''}:\n{lines}\n\n"
            "Whatever you add here must not break those. If you add a field or an "
            "argument, give it a DEFAULT so code that does not set it still works. "
            "Do not change or remove anything that is already there.\n")


# ── how this project already tests that kind of thing ─────────────────────────
# A test step lands in ONE file. If that file has no example of the kind of test
# being asked for, the model reproduces whatever IS there and gets it wrong.
_HTTP_TEST_RE = re.compile(
    r"TestClient\(|client\.(?:get|post|put|patch|delete)\(|"
    r"requests\.(?:get|post)\(|httpx\.(?:AsyncClient|get|post)")

# Does the step ask for a test of an HTTP surface?
_WANTS_HTTP_RE = re.compile(
    r"\b(?:endpoint|route|api|http|handler)\b|/api/|\bGET |\bPOST ", re.I)

HARNESS_MAX_CHARS = 1500


def _is_test_path(path) -> bool:
    n = Path(path).name.lower()
    return n.endswith(".py") and (n.startswith("test_") or n.endswith("_test.py")
                                  or "smoke" in n)


def find_test_harness(workspace, exclude_file=None, max_chars=HARNESS_MAX_CHARS):
    """An excerpt of how this project already tests an HTTP endpoint.

    Returns (path, excerpt) or None. Prefers the smallest file that has the
    pattern, so the excerpt is a whole readable example rather than a slice of
    something enormous.
    """
    if not workspace:
        return None
    ws = Path(workspace)
    try:
        excl = Path(exclude_file).resolve() if exclude_file else None
    except OSError:
        excl = None
    cands = []
    try:
        for p in ws.rglob("*.py"):
            if not p.is_file() or not _is_test_path(p):
                continue
            if any(part in DEP_SKIP_DIRS for part in p.relative_to(ws).parts):
                continue
            try:
                if excl and p.resolve() == excl:
                    continue
            except OSError:
                pass
            try:
                body = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _HTTP_TEST_RE.search(body):
                cands.append((len(body), p, body))
    except (OSError, ValueError):
        return None
    if not cands:
        return None
    cands.sort(key=lambda t: t[0])
    _, path, body = cands[0]
    lines = body.splitlines(keepends=True)

    # The setup: everything before the first def, which is where the env vars and
    # the app import live. That is the half the model keeps getting wrong.
    first_def = next((i for i, l in enumerate(lines) if l.startswith("def ")), len(lines))
    _quotes = ('"' * 3, "'" * 3)
    setup = [l for l in lines[:first_def]
             if l.strip() and not l.lstrip().startswith("#")
             and not l.lstrip().startswith(_quotes)]

    # ...and the first function that actually uses the harness, truncated.
    use_at = next((i for i, l in enumerate(lines) if _HTTP_TEST_RE.search(l)), None)
    body_lines = []
    if use_at is not None:
        start = use_at
        while start > 0 and not lines[start].startswith("def "):
            start -= 1
        body_lines = lines[start:start + 18]

    out = "".join(setup[-14:]) + ("\n" + "".join(body_lines) if body_lines else "")
    if len(out) > max_chars:
        out = out[:max_chars].rsplit("\n", 1)[0] + "\n    ..."
    return (str(path), out.rstrip())


def harness_block(path, excerpt):
    """The example handed to a test step. Empty when there is nothing to show."""
    if not excerpt:
        return ""
    return (f"\nHOW THIS PROJECT TESTS AN ENDPOINT - copy this setup, from "
            f"{Path(path).name}:\n\n{excerpt}\n\n"
            "Use that same import and the same client. The file you are editing "
            "has no example of this, so do NOT copy the style of the tests around "
            "your anchor for the setup part - they test plain functions.\n")


# ── handing one step to a fresh context ───────────────────────────────────────

STEP_PROMPT = """You are editing this one file, and nothing else:

  {file}

Its full contents are below.

WHAT TO DO: {what}

Put it {position} this exact text, which appears once in the file:

{anchor}

{dependents}{harness}{registration}
Call edit_file ONCE (unless the note above says otherwise):
  path      {file}
  old_text  exactly the anchor text above, copied character for character
  new_text  {new_shape}

Write real newlines, not the two characters backslash-n. Do not rewrite the file,
do not touch anything else, and do not call any other tool first.

--- {file} ---
{body}
"""

_SHAPE = {
    "after": "the anchor text, then your addition after it",
    "before": "your addition, then the anchor text after it",
    "replace": "your replacement for the anchor text",
}


def step_prompt(step: dict, body: str = None, workspace: str = None) -> str:
    """One placed edit, as the whole of a fresh conversation.

    Deliberately the shape measured to work: the file, the change in one line,
    and an anchor that is known to exist. Nothing about the wider task, because
    the wider task is what the model could not decompose in the first place.
    """
    path = Path(step["file"])
    if body is None:
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            body = f"[unreadable: {e}]"
    # Who else depends on the thing this step is about -- but ONLY for a shared
    # TYPE. Two of three runs broke an unrelated suite by adding a required field
    # to a pydantic model another file returns, so the warning is real. Warning
    # on every symbol with callers is not: measured at 48% of candidate anchors,
    # which made it noise, and a three-run variance went from mean 7.7 (stdev
    # 0.6) to mean 6.3 (stdev 2.1) with it on.
    #
    # Adding a new function AFTER an existing `def` does not change that def, so
    # its callers are irrelevant. Adding a field after a `class` line is inside
    # the type, and that is exactly what broke.
    sym = symbol_from_anchor(step["anchor"]) if _is_type_anchor(step["anchor"]) else None
    deps = find_dependents(sym, workspace or path.parent, step["file"]) if sym else []

    # A test step whose target file has no example of the kind of test being
    # asked for. Measured: scripts/test_public.py has ZERO uses of TestClient, so
    # a step adding an endpoint test there reproduced the pure-function style
    # around it and invented TestClient(public.app). The pattern it needed was in
    # scripts/smoke_test.py, a file it was never shown.
    harness = ""
    if (_is_test_path(step["file"]) and _WANTS_HTTP_RE.search(step.get("what") or "")
            and not _HTTP_TEST_RE.search(body or "")):
        found = find_test_harness(workspace or path.parent, step["file"])
        if found:
            harness = harness_block(*found)

    # A file that lists its own functions by name needs the new one registered,
    # or it is dead code. Narrow on purpose: test files only, and only when
    # something is being ADDED -- a replace step is editing what is already
    # registered. Every broad intervention tried in this project measured worse.
    registration = ""
    if (REGISTER_HINT and _is_test_path(step["file"])
            and step.get("position", "after") != "replace"):
        registration = dispatcher_block(body, step["file"])

    return STEP_PROMPT.format(file=step["file"], what=step["what"],
                              registration=registration,
                              position=step.get("position", "after"),
                              anchor=step["anchor"],
                              dependents=dependents_block(sym, deps),
                              harness=harness,
                              new_shape=_SHAPE.get(step.get("position", "after"),
                                                   _SHAPE["after"]),
                              body=body)


# ── wiring a new function into the file's own dispatcher ──────────────────────
# Adding the function is half the job in any file that lists its own functions
# somewhere -- a test suite's main(), a registry, a router table. The model does
# the half it was asked for and stops, so the test exists and never runs.
DISPATCH_MIN_CALLS = 3        # below this it is not a dispatcher, it is a function


def _module_functions(tree):
    return [n for n in tree.body if isinstance(n, _ast.FunctionDef)]


# ─── The rewrite guard ────────────────────────────────────────────────────────
# Measured on T4: told to fix one inverted filter, the model wrote a brand new
# app/services/items.py over the real one -- 13 top-level names became 10, only
# 6 sharing a name and those with changed signatures. 191 of 424 tests died,
# because two suites import barcode_variants, which no longer existed.
#
# Nothing caught it. The shrink guard fires on shrinkage and this was +205/-202.
# _verify_file checks that the NEW file resolves against itself, and a
# self-consistent hallucination passes that easily. Neither asks the only
# question that mattered: does the rest of the codebase still work?
#
# So ask it. Names the rewrite deletes, that other files still refer to.
GUARD_MIN_NAME = 3        # shorter names produce noise, not signal
GUARD_MAX_NAMES = 60      # cap the scan on a very large module


def source_names(src):
    """Top-level names a Python source string defines.

    Functions, classes and module constants alike -- a deleted constant that
    another file imports breaks exactly as hard as a deleted function.
    """
    try:
        tree = _ast.parse(src or "")
    except (SyntaxError, ValueError):
        return set()
    out = set()
    for node in tree.body:
        if isinstance(node, (_ast.ClassDef, _ast.FunctionDef, _ast.AsyncFunctionDef)):
            out.add(node.name)
        elif isinstance(node, _ast.Assign):
            for t in node.targets:
                if isinstance(t, _ast.Name):
                    out.add(t.id)
        elif isinstance(node, _ast.AnnAssign) and isinstance(node.target, _ast.Name):
            out.add(node.target.id)
    return out


def lost_names(old_src, new_src):
    """Names the old source defined that the new one does not.

    Empty when either side will not parse: an unparseable new file is the
    verifier's problem, and refusing on a guess we cannot make is worse than
    letting the existing checks handle it.
    """
    old, new = source_names(old_src), source_names(new_src)
    if not old or not new:
        return []
    return sorted(n for n in old - new if len(n) >= GUARD_MIN_NAME)


def broken_dependents(path, old_src, new_src, workspace):
    """Which deleted names other files still use. [(name, relpath, line, text)].

    One hit per name is enough -- the point is to refuse and say why, not to
    enumerate every call site.
    """
    if not workspace or not str(path).lower().endswith(".py"):
        return []
    out = []
    for name in lost_names(old_src, new_src)[:GUARD_MAX_NAMES]:
        for hit in find_dependents(name, workspace, exclude_file=path, max_hits=1,
                                   skip_defs=True):
            out.append((name,) + tuple(hit))
            break
    return out


def rewrite_refusal(path, broken):
    """The message the model gets back instead of a destroyed module."""
    names = sorted({b[0] for b in broken})
    lines = [f"[WRITE REFUSED] This would delete {len(names)} name(s) from "
             f"{Path(path).name} that other files still use:", ""]
    for name, rel, lineno, text in broken[:8]:
        lines.append(f"  {name}  <-  {rel}:{lineno}  {str(text).strip()[:70]}")
    if len(broken) > 8:
        lines.append(f"  ...and {len(broken) - 8} more")
    lines += ["",
              "Nothing was written. You are replacing the file rather than changing it.",
              "Use edit_file with a small unique anchor to change only the part you mean,",
              f"or, if you truly must rewrite it, keep these defined: {', '.join(names)}"]
    return chr(10).join(lines)


RETRY_PROMPT = """The test you just wrote does not work. You ran nothing, so
here is what happened when it was run, and what the data actually looked like at
the line that failed:

  {failure}

Fix the test. Its expectations are what is wrong, not the application -- the
endpoint already works and its behaviour is not up for negotiation. Use the key
names listed above exactly as they appear. Do not guess a different name: the
listing IS the answer, and guessing is what put the wrong name there the first
time.

You are editing this one file and nothing else:

  {file}

Call edit_file with a small unique anchor around just the part that is wrong.
Do not rewrite the file. Do not touch the application code. Do not add a second
test.

--- {file} ---
{body}
"""


def retry_prompt(step: dict, body: str, failure: str) -> str:
    """A second pass at one test step, carrying its own traceback.

    Deliberately narrow: it says the test is wrong, not the app, because the
    measured failure mode is a model that "fixes" a failing test by changing
    the working endpoint underneath it.
    """
    return RETRY_PROMPT.format(file=step["file"], failure=failure, body=body)


def find_dispatcher(body: str):
    """A function that exists to call the file's other functions by name.

    Returns (name, [called names], last_call_lineno) or None. Recognised by
    shape, not by being called "main": a body of bare calls to functions defined
    in the same file.
    """
    try:
        tree = _ast.parse(body)
    except Exception:
        return None
    funcs = _module_functions(tree)
    names = {f.name for f in funcs}
    best = None
    for f in funcs:
        called, last = [], None
        for node in f.body:
            if (isinstance(node, _ast.Expr) and isinstance(node.value, _ast.Call)
                    and isinstance(node.value.func, _ast.Name)
                    and node.value.func.id in names
                    and not node.value.args and not node.value.keywords):
                called.append(node.value.func.id)
                last = node.lineno
        if len(called) >= DISPATCH_MIN_CALLS and (best is None or len(called) > len(best[1])):
            best = (f.name, called, last)
    return best


# Measured OFF. The hint works -- test_stats_endpoint() did get registered in
# main() -- and T3 got WORSE for it: 8/9 -> 7.3 mean, and "nothing that worked
# before is broken" went 3/3 -> 0/3. Two of three runs took the whole suite from
# 424 tests to 0.
#
# Not because registering is wrong. Because the test being registered was
# already broken, and registering it is what made that visible:
#
#     NameError: name 'os' is not defined
#
# The model copies the setup out of smoke_test.py, which imports os and
# tempfile, into test_public.py, which imports neither. Before this hint the
# broken test was never called, so the suite stayed green and only "added tests"
# failed. The defect was always there; it was just silent.
#
# So the 8/9 that T3 scored on three sweeps was partly hiding a dead test.
#
# Turn this back on when _verify_file catches undefined names -- it currently
# returns clean on the file above, which is the actual bug. Then the model gets
# told about the missing import and the registration becomes safe.
REGISTER_HINT = False


def dispatcher_block(body, file_name=""):
    """Tell the step that this file registers its own functions by hand.

    Measured on T3, twice in a row: the model added 116 lines to
    scripts/test_public.py and the suite still ran exactly 50 tests. That file
    lists its tests in main() by name, so a new `def test_x()` is dead code
    until a call to it is added there. Nothing in the prompt said so.

    auto_register() -- doing it FOR the model -- was tried and measured worse
    (7.7 -> 7.0 -> 6.0). Telling the model was never tried on its own, and
    telling it is what worked for dependents and for the harness example.
    """
    d = find_dispatcher(body or "")
    if not d:
        return ""
    name, called, _ = d
    shown = called[:3]
    listing = chr(10).join("        " + c + "()" for c in shown)
    if len(called) > len(shown):
        listing += chr(10) + "        ..."
    return (f"{chr(10)}REGISTERING IT - this file calls its functions by hand, in "
            f"{name}():{chr(10)}{chr(10)}    def {name}():{chr(10)}{listing}{chr(10)}{chr(10)}"
            f"Anything you add is DEAD until a call to it appears in {name}(). "
            f"So call edit_file TWICE and only twice: once to add the function at "
            f"the anchor above, then once more with a small unique anchor inside "
            f"{name}() to add the call. Do not skip the second one.{chr(10)}")


def new_functions(before: str, after: str):
    """Module-level functions in `after` that were not in `before`."""
    try:
        old = {f.name for f in _module_functions(_ast.parse(before))}
        new = [f.name for f in _module_functions(_ast.parse(after))]
    except Exception:
        return []
    return [n for n in new if n not in old]


def _shared_prefix(names):
    """The convention the dispatcher already follows, e.g. 'test_'."""
    if not names:
        return ""
    first = names[0]
    for i in range(len(first), 0, -1):
        p = first[:i]
        if p.endswith("_") and all(n.startswith(p) for n in names):
            return p
    return ""


def auto_register(before: str, after: str):
    """Add a call for a newly added function to the file's dispatcher.

    Returns (new_body, note), or (None, "") when there is nothing to do. Being
    conservative here matters more than catching every case: a wrongly inserted
    call runs something that was never meant to run.
    """
    added = new_functions(before, after)
    if not added:
        return None, ""
    disp = find_dispatcher(after)
    if not disp:
        return None, ""
    _, called, last_line = disp
    if not last_line:
        return None, ""
    prefix = _shared_prefix(called)
    # Only names that follow the convention the file already uses. Without this
    # a helper added alongside the test gets called too.
    wire = [n for n in added if n not in called and (not prefix or n.startswith(prefix))]
    if not wire:
        return None, ""
    lines = after.splitlines(keepends=True)
    if last_line > len(lines):
        return None, ""
    indent = lines[last_line - 1][:len(lines[last_line - 1])
                                 - len(lines[last_line - 1].lstrip())]
    insert = "".join(f"{indent}{n}()\n" for n in wire)
    lines.insert(last_line, insert)
    return ("".join(lines),
            "wired " + ", ".join(f"{n}()" for n in wire) + f" into {disp[0]}()")


# ── plan state ────────────────────────────────────────────────────────────────

class Placement(dict):
    """One placed edit. A dict, so it serialises into the session store as-is."""


class PlacementPlan:
    """Sequence state for a placed-edit run. Holds no file CONTENT: what carries
    between steps is the placement list, which is small and fixed in size."""

    def __init__(self, usable: list, rejected: list = None, task: str = ""):
        self.steps = [Placement(s) for s in usable]
        self.rejected = list(rejected or [])
        self.task = task
        self.results = []      # {file, what, ok, note}
        self.idx = 0

    def __len__(self):
        return len(self.steps)

    def current(self):
        return self.steps[self.idx] if self.idx < len(self.steps) else None

    def record(self, ok: bool, note: str = ""):
        s = self.current()
        if s is None:
            return None
        row = {"file": s["file"], "what": s["what"], "ok": bool(ok), "note": note}
        self.results.append(row)
        self.idx += 1
        return row

    def lines(self) -> str:
        out = []
        for i, s in enumerate(self.steps):
            mark = "[done]" if i < self.idx else ("[NOW] " if i == self.idx else "[next]")
            out.append(f"  {mark} {Path(s['file']).name}: {s['what']}")
        return "\n".join(out)

    def report(self) -> str:
        done = [r for r in self.results if r["ok"]]
        head = f"Made {len(done)} of {len(self.steps)} planned edit(s)."
        body = [f"  {'ok ' if r['ok'] else 'NOT'} {Path(r['file']).name}: {r['what']}"
                + (f"  — {r['note']}" if r["note"] else "") for r in self.results]
        tail = ""
        if self.rejected:
            # Never silent. A plan that lost steps has to say which and why.
            tail = ("\n\nPlanned but not attempted, because the place could not be "
                    "found:\n" + "\n".join(
                        f"  {Path(r['file']).name}: {r['what']}  — {r.get('why', '')}"
                        for r in self.rejected))
        return head + "\n" + "\n".join(body) + tail
