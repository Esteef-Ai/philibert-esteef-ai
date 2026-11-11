"""Philibert Code Studio: from a few sentences to a plan the foreman can build (dev/PHILIBERT_CODE_STUDIO.md).

Stages, each one model call with a fresh, small context (what the earlier stages decided travels as text):
    questions   the request -> the few questions it leaves open (each with a suggested answer)
    spec        request + answers -> SPEC.md
    plan        SPEC.md -> plan.json for nd_foreman (tasks, files, exact API in each brief, done_when)
    tests       one call per task -> tests/test_<x>.py, written BEFORE any code, judged by the foreman

Pure logic here (prompts, parsing, checks); talking to the model is call_model(). Phase A measures whether a
local model can do this well enough - the proof of concept for the whole Studio.
"""
import json
import re
import time
import urllib.request

OLLAMA = "http://127.0.0.1:11434"

QUESTIONS = """You are the planner of Philibert Code, a local coding assistant. A user described an app they \
want built. Before anything is planned, find what the description leaves OPEN that would change how it is \
built or judged. Cover this checklist, but ask only about what is really unclear:
- what it runs on and in what language / toolkit (suggest one if the user did not say)
- how it is started, and whether it must become a single program file (exe)
- the must-have features (what it must DO), and what can wait
- how it should look (layout, style; "like X" references)
- whether it may change or delete the user's files
- a way to check it automatically (a command-line mode that prints or writes results), so tests can judge it
- anything about speed or size limits

Write at most 7 numbered questions, short and plain, each followed by a suggested answer in square brackets \
that the user can accept as is. Write nothing else.

THE REQUEST:
{request}
"""

SPEC = """You are the planner of Philibert Code. Write SPEC.md for the app below, from the user's request and \
their answers. It is the single source of truth for everyone who builds and tests the app, so every feature \
must be concrete and checkable.

Sections, in this order, in Markdown:
# <App name> - the spec
## Goal            two or three sentences
## Tech            language, toolkit, allowed libraries, how it is packaged
## Features        numbered; each one says exactly what the user sees or gets, with exact names, columns, \
formats and strings where they matter
## Command line    the automation / test mode: exact arguments and the exact output format (JSON keys, types)
## Look            layout and style
## Rules           safety (what it must never do), threading, error handling
## Done means      a checklist a tester can tick

Write only the Markdown.

THE REQUEST:
{request}

THE QUESTIONS AND THE USER'S ANSWERS:
{answers}
"""

FACTS = """FACTS ABOUT THIS COMPUTER (Windows 11, Python 3.11, a normal user without admin rights)
- A directory junction is NOT a symlink to Python 3.11: DirEntry.is_symlink() returns False for it. To skip links and junctions: entry.is_symlink() or bool(entry.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT).
- os.symlink() fails without admin rights; make a test link with subprocess.run(["cmd", "/c", "mklink", "/J", link, target]). os.chmod() cannot make a folder unreadable.
- Programs are not on PATH: run Python as sys.executable and tools through it (sys.executable -m PyInstaller).
- tkinter: Treeview exists only as tkinter.ttk.Treeview; there is no ttk.Toplevel (use tkinter.Toplevel). A Treeview tag colours the whole row. Update the window only from the main thread: a worker thread puts results on a queue.Queue and the main thread polls it with after().
- A folder's size is the sum of everything beneath it, at every level."""


PLAN = """You are the planner of Philibert Code. Turn the spec below into a build plan for a careful but \
literal junior programmer (a local AI model). It builds ONE task at a time and sees only that task's brief, the \
files it names and the project rules, never the whole spec. A separate step writes each task's test file \
BEFORE any code exists, from the brief alone. So each brief must be complete and exact.

RULES FOR THE PLAN
- 4 to 8 tasks, in build order. THE APP MUST RUN EARLY:
  T01 builds the one engine and, if the spec has a command-line mode, that mode and the program's entry script: \
after T01 the real program gives correct answers.
  If the spec has a window, T02 is the WALKING SKELETON: the real entry script opens the real window with every \
area placed and visible, the control that starts the work exists and works, the work runs in the background, and \
the real results appear in the window in their simplest form. Every later task improves ONE feature of an app that \
already runs. The last task is "make it presentable" (title, icon if asked, tidy look, README, packaging).
- ONE SOURCE OF DATA. The engine returns one result object holding everything the app ever shows, including every \
folder and file at every level with all the numbers the display needs. Windows and charts read that object; they \
never walk the disk again and never compute the same thing a second way.
- Field names are defined ONCE, in T01's brief, and every later brief uses exactly those names.
- Each task creates or changes at most 4 files, never anything under tests/. List them all in "files", including \
earlier files it must change to connect its feature.
- Each task has exactly one test file "tests/test_<short_name>.py" (it does not exist yet).
- The brief states the EXACT public API: module paths, class and function names, parameters and their types, \
return values and their exact shape, dataclass fields, exact strings, column names, JSON keys, error behaviour, \
edge cases (empty input, unreadable folders, unicode names...). A tester must be able to write the test from the \
brief alone, and the programmer must not have to guess a single name.
- Later tasks reuse earlier modules by name ("use scan() from app_pkg/scanner.py") instead of repeating code.
- "done_when": 2-5 short, checkable statements; the first is always "tests/test_<x>.py prints 0 failed".
- "depends_on": the ids of the tasks whose modules it uses.
- "rules": 3-6 project-wide rules (safety, libraries, threading, naming). "conventions": 2-4 code-style lines.

OUTPUT: one JSON object and nothing else, shaped exactly like this example (from a different project):
{{"project": "Notely",
  "goal": "One paragraph: what the app is and does.",
  "rules": ["Standard library only.", "..."],
  "conventions": ["Python 3.11, type hints on public functions.", "..."],
  "tasks": [
    {{"id": "T01", "title": "The note store",
      "files": ["notely/__init__.py", "notely/store.py"],
      "tests": "tests/test_store.py",
      "depends_on": [],
      "brief": "Create notely/store.py.\\n- @dataclass class Note: id: int, title: str, body: str, tags: list[str]\\n- load(path: str) -> list[Note]: reads a JSON list; a missing file returns []; ...\\n- ...",
      "done_when": ["tests/test_store.py prints 0 failed", "load() of a missing file returns []"]}}
  ],
  "engine_task": "T01",
  "window_task": null}}
"engine_task" is the id of the task that builds the engine; "window_task" is the id of the walking-skeleton task, \
or null if the app has no window.

@@FACTS@@

THE SPEC:
{spec}
"""

PLAN_REVIEW = """You are the reviewer of Philibert Code's build plans. Below are a spec and the plan written for it. \
A plan fails in two typical ways, so check for both and FIX the plan:

1. A feature has no task. Go through EVERY numbered feature, the command line, the look and every "Done means" \
line of the spec, and name the task that delivers it. Pay special attention to the WIRING: the task that connects \
the parts (fills the window with real results, runs work in the background, updates the status, handles every \
click, hover, double-click, button and resize the spec names). Building the parts is not enough; the app must work \
when it starts.
2. A task needs data an earlier task does not provide. For each task, check that the functions and data it uses \
exist, with those names and fields, in the briefs of the tasks it depends on (for example: a window that shows a \
tree of folders and files needs a scanner that returns that tree, not only totals).
3. Every thing the app DISPLAYS must exist in the data: if the spec shows files (in a list, a tree, a chart), the \
data model holds each file, not only folders or totals.
4. Later tasks must be able to REACH what earlier tasks built. A window built over several tasks is one class \
(for example `class MainWindow` with named attributes for every widget and for the current data, and named methods \
that later tasks add or fill in), never a function that returns only the top window. Each user action (a button, \
a menu, start-up) is tied to a named method, and the brief says which widget calls it.

Then return the corrected plan. Keep what is right; add or split tasks where something is missing (at most 10 \
tasks, at most 3 files each, one new test file each), and make every brief state the exact API. A window with many \
behaviours should be split: layout and filling first, then the interactions. Follow speed advice the spec gives.

5. The app must run EARLY: T01 gives correct real answers; the task named "window_task" opens the real window with \
every area visible and real results in it. Later tasks improve a running app.
6. ONE SOURCE OF DATA: if any task walks the disk (or fetches the data) a second time, or a display needs a field \
the engine's result does not have, change the engine's result and remove the second walk.

@@FACTS@@

OUTPUT: one JSON object and nothing else: the same shape as the plan (keep "engine_task" and "window_task"), plus a key "coverage": a list of \
{{"item": "<spec item, short>", "task": "<task id>"}} with one entry per spec feature and "Done means" line.

THE SPEC:
{spec}

THE PLAN:
{plan}
"""

TESTS = """You are the test writer of Philibert Code. Write the test file {test} for ONE task of the plan below. \
No code exists yet: the test is written from the brief, and the task is finished only when this test passes. \
So it must check what the brief promises, exactly as the brief names it - nothing the brief does not promise.

HOW THE TESTS ARE WRITTEN (follow exactly)
- A plain script, not pytest. Start with: from _t import check, finish, temp_tree, run, WS
  check(label, ok, got="") records one check; finish() prints the summary and must be the last line.
  temp_tree({{"a/b.txt": 1500, "c.mp3": b"..."}}) makes a temporary folder (an int is a size in bytes, bytes are \
the content) and returns its path; it is deleted at exit. run(args, timeout=120) runs a command in the project \
folder and returns (exit_code, output). WS is the project folder (a pathlib.Path); it is already on sys.path.
- Import the task's modules inside try/except; on an import error: check("<module> imports", False, e) then finish().
- Build your own test data with temp_tree and work out the expected answers BY HAND from that data (sum the \
sizes yourself). Never compute an expected value with the code under test.
- 8 to 25 checks with clear labels. Cover every "done_when" line and the edge cases the brief names.
- One failing check must not stop the others: wrap each risky call in try/except and check(..., False, e).
- Fast: the whole file runs in under 60 seconds.
- A window (tkinter): use the REAL window class and the REAL data classes of the app. Never fake or stub a module \
of the app, never use Mock objects for it, never put anything in sys.modules. off_screen(root) keeps the window off \
the desktop; pump(root, 0.3) lets it draw and handle events. Patch only what needs a person: \
tkinter.filedialog.askdirectory, and mainloop if the code under test calls it. Never call mainloop() yourself. \
Do not depend on exact pixel positions; check that things are placed (winfo_ismapped), have the right text, and \
that the parts the brief names are drawn. event_generate cannot send Double-... events (send two presses instead) \
and works only on a window that has been pumped.
- Check real numbers, not just that a result exists: for folders, check sizes and counts at more than one level.
- Packaging: run the build script with run(), then check that the program file exists and that its command-line \
mode gives the right answer on a temp_tree folder.
- Never create, change or delete anything except inside temporary folders (use temp_tree or tempfile): the project \
folder must be unchanged after the test.

@@FACTS@@

THE PROJECT RULES:
{rules}

THE WHOLE PLAN (for the names of earlier modules; test only THIS task):
{plan_summary}

THIS TASK:
{task}

Write only the Python file, in one ```python block.
"""

TEST_REVIEW = """You are the reviewer of Philibert Code's tests. A test that can never pass blocks the whole build \
(the programmer may not edit tests), so find every check below that is wrong and return the corrected file.

A check is WRONG when:
1. It cannot pass on this computer: Windows 11, Python 3.11, a normal user WITHOUT admin rights and without \
Developer Mode. os.symlink() fails there (make a junction instead with \
subprocess.run(["cmd", "/c", "mklink", "/J", link, target]), which needs no admin); os.chmod() cannot make a \
folder unreadable (skip that case, or simulate it only through the API the brief gives). Programs are not on PATH: \
run the project's Python as sys.executable and build tools through it (sys.executable -m PyInstaller).
2. It uses an API that does not exist or is used wrongly: tkinter has no tk.Treeview (it is tkinter.ttk.Treeview, \
which has no bg / selectbackground options - its look is set with ttk.Style); check widget options that exist.
3. It contradicts the brief or the spec: argument order, names, formats, what is printed versus written to a file. \
Where the brief is silent, do not invent an exact format - check the property loosely (for example "ends with KB").
4. It reads the source code for words instead of checking what the code DOES (replace it with a behaviour check, \
or drop it).
5. It is flaky: depends on timing, on exact pixels, on window-manager geometry before update(), or on the order of \
a dict or a folder listing the brief does not promise.

Keep every check that is right. Keep the same helpers (from _t import check, finish, temp_tree, run, WS) and \
finish() at the end.

THE SPEC (short): {spec}

6. It fakes the app: it stubs a module of the app, uses Mock objects for it, or invents classes or fields the app \
does not have. Rewrite it to use the real classes.
7. It writes inside the project folder instead of a temporary folder.

Where THE CODE ALREADY BUILT is shown, it is the truth for every name, field and argument of those finished parts.

@@FACTS@@

THE TASK:
{task}

THE CODE ALREADY BUILT:
{built}

THE TEST FILE {test}:
```python
{code}
```

First list the wrong checks in one line each, then write the whole corrected file in one ```python block.
"""

DISPUTE = """You are the referee of Philibert Code's builds. The programmer failed task {tid} three times and the \
build has stopped. The programmer may not edit tests, so a test that is wrong blocks everything after it. Decide \
who is wrong: the TEST or the CODE.

The TEST is wrong when it cannot pass against a correct program: it builds objects with the wrong fields or \
arguments (the code of the earlier, finished tasks below is the truth for their classes and functions), calls \
an API wrongly, contradicts the task brief or the spec, needs admin rights, or is flaky. A test is NOT wrong just \
because it is strict.

THE SPEC (short): {spec}

THE PLAN: {plan_summary}

THE TASK:
{task}

THE CODE AS IT IS NOW (earlier tasks are finished and passed their own tests):
{code}

THE TEST FILE {test}:
```python
{test_code}
```

THE LAST FAILURE (the programmer's best attempt):
```
{failure}
```

Answer in this form:
VERDICT: TEST or CODE
WHY: one to three lines.
If TEST: the whole corrected test file in one ```python block. Change only what is wrong; keep every right check, \
the helpers (from _t import check, finish, temp_tree, run, WS) and finish() at the end. A failure inside one \
check must not stop the file: build test data inside try blocks.
If CODE: a HINT: line for the programmer, naming the exact fix.
"""

ACCEPT_CORE = """You are the acceptance tester of Philibert Code. Write the test file {test}: it proves the REAL \
PROGRAM gives correct answers, from the outside, the way a user runs it. No code exists yet. This test is written \
once and every task of the build must keep it passing.

- A plain script. Start with: from _t import check, finish, temp_tree, run, WS   (and import sys, json, os, tempfile)
- Build one realistic folder with temp_tree, at least 3 levels deep, with round sizes, hidden files, a file with no \
extension, an empty folder, a file directly in the root and upper-case extensions. Make a directory junction inside \
it (see the facts) that points at one of its own folders.
- Run the real entry script named in the plan with run([sys.executable, str(WS / "<entry script>"), ...]), writing \
its output into a temporary folder.
- Work out every expected number BY HAND in comments from the sizes you chose, then check EVERY value of the spec's \
output: every total, every per-extension row, and every per-entry row with its size and counts. The junction's \
contents must not be counted twice.
- If a total or a row in the spec is ambiguous, choose the plain reading: an entry's size and counts include \
everything beneath it.
- check(label, ok, got) for each value, finish() last. Labels must not contain paths. Under 60 seconds.

@@FACTS@@

THE SPEC:
{spec}

THE PLAN:
{plan_summary}

THE TASK THAT BUILDS THE ENGINE:
{task}

Write only the Python file, in one ```python block.
"""

ACCEPT_WINDOW = """You are the acceptance tester of Philibert Code. Write the test file {test}: it proves the REAL \
WINDOW opens and shows real results. No code exists yet. This test is written once and every later task must keep \
it passing.

- A plain script. Start with: from _t import check, finish, temp_tree, run, WS, off_screen, pump   (import tkinter)
- Use the real entry the brief names for building the window. Nothing of the app may be faked, stubbed or mocked. \
Patch only tkinter.filedialog.askdirectory to return the temporary folder, and mainloop if the app calls it: \
replace mainloop with your own function that runs the checks and then destroys the window.
- Make a small temp_tree, off_screen(root), start the work with the real control (invoke the real button or call \
the real start method the brief names), then pump until the app reports it is finished (give up after 30 seconds).
- Check: every area the spec names is placed (winfo_ismapped() and width over 50), and each area shows real data \
from the temp_tree: a real file name appears in the tree or list, numbers are right for one folder at two levels, \
the chart has drawn items, the status text is the finished text.
- check(label, ok, got) for each, finish() last. The window must be destroyed before finish(). Labels must not \
contain paths. Under 60 seconds.

@@FACTS@@

THE SPEC:
{spec}

THE PLAN:
{plan_summary}

THE TASK THAT OPENS THE WINDOW:
{task}

Write only the Python file, in one ```python block.
"""

TEST_FIX = """You are the test writer of Philibert Code. The test file below breaks these rules; correct them and \
change nothing else:
{problems}

@@FACTS@@

THE TASK:
{task}

THE TEST FILE {test}:
```python
{code}
```

Write the whole corrected file in one ```python block.
"""

# What a generated test must never do; each was seen stopping or fooling a real build.
TEST_LINT = [
    (r"sys\.modules\s*\[", "it puts a fake module in sys.modules: use the real modules of the app"),
    (r"\b(MagicMock|Mock)\s*\(", "it uses Mock objects: use the real classes of the app"),
    (r"^\s*class\s+(Fake|Mock|Dummy|Stub)\w*", "it defines a fake class: use the real classes of the app"),
    (r"types\.ModuleType\(", "it builds a fake module: use the real modules of the app"),
    (r"run\(\s*\[\s*[\"'][^\"']*\.(py|exe)[\"']",
     "it runs a script or exe as a command: use run([sys.executable, str(WS / 'name.py'), ...])"),
    (r"os\.symlink\(", "os.symlink needs admin rights here: make a junction with mklink /J"),
    (r"os\.chmod\(", "os.chmod cannot make a folder unreadable here: remove that case"),
    (r"[\[(,]\s*[\"']python3?[\"']\s*,", 'it runs a bare "python": use sys.executable'),
    (r"[\[(,]\s*[\"']pyinstaller[\"']\s*,", "pyinstaller is not on PATH: use sys.executable, -m, PyInstaller"),
    (r"\btk\.Treeview\b|\btkinter\.Treeview\b", "Treeview exists only in tkinter.ttk"),
    (r"\bttk\.Toplevel\b", "there is no ttk.Toplevel: use tkinter.Toplevel"),
    (r"event_generate\(\s*[\"']<(Double|Triple)", "event_generate cannot send Double/Triple events: send two presses"),
    (r"\bWS\s*/[^\n]*\.(mkdir|write_text|write_bytes|touch)\(", "it writes inside the project folder: use a temporary folder"),
    (r"(open\([^\n]*WS\b[^\n]*[\"'][wax]b?[\"'])", "it writes inside the project folder: use a temporary folder"),
    (r"inspect\.getsource|\.read_text\([^)]*\)\s*\n[^\n]*\bin\b[^\n]*(def |class )", "it greps the source instead of testing behaviour"),
]


def test_problems(code):
    """Rules a generated test breaks, found mechanically (no model needed)."""
    out = []
    for pat, why in TEST_LINT:
        if re.search(pat, code, re.M) and why not in out:
            out.append(why)
    if "finish()" not in code:
        out.append("it does not end with finish()")
    return out


T_HELPER = '''"""Shared helpers for the tests (written by Philibert Code Studio; do not edit)."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))
for _s in (sys.stdout, sys.stderr):      # models write non-ASCII labels (e.g. U+2011); a cp1252 pipe would crash
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
_results = []
_temps = []


def _stable(label):
    """Temp folder paths in a label become <tmp>: their random names would make the label new every run."""
    s = str(label)
    for d in sorted(_temps, key=len, reverse=True):
        for form in {d, str(Path(d).resolve()), d.replace(os.sep, "/"), str(Path(d).resolve()).replace(os.sep, "/")}:
            s = s.replace(form, "<tmp>")
    return re.sub(r"[A-Za-z]:[^ ]*?pc_test_[A-Za-z0-9_#]+", "<tmp>", s)


def check(label, ok, got=""):
    label = _stable(label)
    _results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + str(label) + ("" if ok else f" - got {got!r}"[:400]), flush=True)


def finish():
    for d in _temps:
        shutil.rmtree(d, ignore_errors=True)
    passed = sum(_results)
    print(f"{passed} passed, {len(_results) - passed} failed", flush=True)
    sys.exit(0 if _results and passed == len(_results) else 1)


def pump(root, seconds=0.3):
    """Let a real tkinter window draw and handle events for a while."""
    import time
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


def off_screen(root, width=1000, height=700):
    """Keep a real window off the desktop (it is still mapped, and events still work)."""
    root.geometry(f"{width}x{height}+-4000+-4000")
    pump(root, 0.3)


class _Root(str):
    """A folder path that is a str (os.path.join, ==, str()) and also acts as a pathlib.Path."""
    def __truediv__(self, other):
        return Path(self) / other

    def __fspath__(self):
        return str(self)

    def __getattr__(self, name):          # resolve(), exists(), iterdir(), name, parent ...
        return getattr(Path(self), name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def temp_tree(files):
    """{relative path: size in bytes (int) or content (bytes); a path ending in / is an empty folder} -> folder.
    The folder is a str that also acts as a pathlib.Path: root / "a.txt", root.exists(), with temp_tree(...) as root."""
    root = tempfile.mkdtemp(prefix="pc_test_")
    _temps.append(root)
    for rel, v in files.items():
        p = Path(root) / rel
        if rel.endswith("/"):
            p.mkdir(parents=True, exist_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(v if isinstance(v, bytes) else b"x" * int(v))
    return _Root(root)


def run(args, timeout=120):
    """Run a command in the project folder -> (exit code, stdout + stderr)."""
    try:
        r = subprocess.run(args, cwd=str(WS), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, shell=isinstance(args, str))
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, f"timed out after {timeout}s"
'''


for _name in ("PLAN", "PLAN_REVIEW", "TESTS", "TEST_REVIEW", "ACCEPT_CORE", "ACCEPT_WINDOW", "TEST_FIX"):
    globals()[_name] = globals()[_name].replace("@@FACTS@@", FACTS)


def call_model(model, prompt, think=True, timeout=3600, url=OLLAMA, max_tokens=32000, num_ctx=None):
    """One chat call. -> (answer text, seconds, info dict). max_tokens caps a thinking loop (one review once
    thought for 62,000 tokens and never answered). think: True/False, or "low"/"medium"/"high" for
    models that take a level (gpt-oss). num_ctx: for a model without a context baked into its Modelfile."""
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False, "think": think,
            "options": {"temperature": 0.3, "num_predict": max_tokens, **({"num_ctx": num_ctx} if num_ctx else {})},
            "keep_alive": "15m"}
    t = time.time()
    req = urllib.request.Request(url + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    msg = r.get("message") or {}
    info = {"eval_count": r.get("eval_count"), "prompt_eval_count": r.get("prompt_eval_count"),
            "thinking_chars": len(msg.get("thinking") or "")}
    return msg.get("content") or "", round(time.time() - t, 1), info


def strip_think(text):
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def extract_json(text):
    """The first JSON object in a reply (a ```json block, or from the first { to its matching })."""
    text = strip_think(text)
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in the reply")
    s = text[start:]
    for _ in range(6):                     # a model slips a closing bracket now and then: put it back
        try:
            return json.JSONDecoder().raw_decode(s)[0]
        except json.JSONDecodeError as e:
            if "delimiter" not in e.msg:
                raise
            for fix in ("}", "]"):
                t = s[:e.pos] + fix + s[e.pos:]
                try:
                    return json.JSONDecoder().raw_decode(t)[0]
                except json.JSONDecodeError as e2:
                    if e2.pos > e.pos:
                        s = t
                        break
            else:
                raise
    raise ValueError("the JSON could not be repaired")


def extract_python(text):
    text = strip_think(text)
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    if not blocks:
        raise ValueError("no ```python block in the reply")
    return max(blocks, key=len).strip() + "\n"


def plan_problems(plan):
    """What a Studio plan gets wrong before the foreman even looks (the foreman's own load_plan checks more)."""
    probs = []
    tasks = plan.get("tasks") or []
    if not 3 <= len(tasks) <= 10:
        probs.append(f"{len(tasks)} tasks (expected 4-8)")
    seen_tests = set()
    for t in tasks:
        tid = t.get("id", "?")
        files = t.get("files") or []
        if len(files) > 4:
            probs.append(f"{tid}: {len(files)} files (max 4)")
        if any(str(f).replace("\\", "/").startswith("tests/") for f in files):
            probs.append(f"{tid}: lists a file under tests/")
        test = t.get("tests")
        if isinstance(test, list):
            test = test[0] if len(test) == 1 else None
        if not test or not re.fullmatch(r"tests/test_\w+\.py", str(test)):
            probs.append(f"{tid}: tests must be one tests/test_<x>.py, got {t.get('tests')!r}")
        elif test in seen_tests:
            probs.append(f"{tid}: shares its test file {test}")
        seen_tests.add(test)
        if len(t.get("brief") or "") < 200:
            probs.append(f"{tid}: brief is only {len(t.get('brief') or '')} characters")
        if not t.get("done_when"):
            probs.append(f"{tid}: no done_when")
    return probs


def test_files(t):
    """A task's test files (one string in a fresh plan, a list once acceptance tests are attached)."""
    return [t["tests"]] if isinstance(t.get("tests"), str) else list(t.get("tests") or [])


def plan_summary(plan):
    return "\n".join(f"{t['id']} {t['title']}: files {', '.join(t.get('files') or [])}; "
                     f"depends on {', '.join(t.get('depends_on') or []) or 'nothing'}" for t in plan.get("tasks") or [])


def task_text(t):
    return (f"{t['id']} - {t['title']}\nFiles: {', '.join(t.get('files') or [])}\nTest file: {t.get('tests')}\n"
            f"Brief:\n{t.get('brief')}\nDone when:\n- " + "\n- ".join(t.get("done_when") or []))
