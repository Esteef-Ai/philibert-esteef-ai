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

PLAN = """You are the planner of Philibert Code. Turn the spec below into a build plan for a careful but \
literal junior programmer (a local AI model). It builds ONE task at a time and sees only that task's brief, the \
files it names and the project rules, never the whole spec. A separate step writes each task's test file \
BEFORE any code exists, from the brief alone. So each brief must be complete and exact.

RULES FOR THE PLAN
- 4 to 8 tasks, in build order: pure logic first (data, calculations), then the command-line mode, then the \
window, then packaging, then a last "make it presentable" task (window title, icon if asked, tidy look, README).
- Each task creates or changes at most 3 files, never anything under tests/. List them all in "files".
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
  ]}}

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

OUTPUT: one JSON object and nothing else: the same shape as the plan, plus a key "coverage": a list of \
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
- A window (tkinter): create it, call update() a few times, inspect widgets and canvas items, then destroy() it. \
Never call mainloop(). Do not depend on exact pixel positions; check that things exist, are visible, have the \
right text, and that the parts the brief names are drawn.
- Packaging: run the build script with run(), then check that the program file exists and that its command-line \
mode gives the right answer on a temp_tree folder.
- Never write, change or delete anything outside the temporary folders and the project folder.

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

THE TASK:
{task}

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

T_HELPER = '''"""Shared helpers for the tests (written by Philibert Code Studio; do not edit)."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WS))
_results = []
_temps = []


def check(label, ok, got=""):
    _results.append(bool(ok))
    print(("  PASS  " if ok else "  FAIL  ") + str(label) + ("" if ok else f" - got {got!r}"[:400]), flush=True)


def finish():
    for d in _temps:
        shutil.rmtree(d, ignore_errors=True)
    passed = sum(_results)
    print(f"{passed} passed, {len(_results) - passed} failed", flush=True)
    sys.exit(0 if _results and passed == len(_results) else 1)


def temp_tree(files):
    """{relative path: size in bytes (int) or content (bytes); a path ending in / is an empty folder} -> folder."""
    root = tempfile.mkdtemp(prefix="pc_test_")
    _temps.append(root)
    for rel, v in files.items():
        p = Path(root) / rel
        if rel.endswith("/"):
            p.mkdir(parents=True, exist_ok=True)
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(v if isinstance(v, bytes) else b"x" * int(v))
    return root


def run(args, timeout=120):
    """Run a command in the project folder -> (exit code, stdout + stderr)."""
    try:
        r = subprocess.run(args, cwd=str(WS), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, shell=isinstance(args, str))
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, f"timed out after {timeout}s"
'''


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
        if len(files) > 3:
            probs.append(f"{tid}: {len(files)} files (max 3)")
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


def plan_summary(plan):
    return "\n".join(f"{t['id']} {t['title']}: files {', '.join(t.get('files') or [])}; "
                     f"depends on {', '.join(t.get('depends_on') or []) or 'nothing'}" for t in plan.get("tasks") or [])


def task_text(t):
    return (f"{t['id']} - {t['title']}\nFiles: {', '.join(t.get('files') or [])}\nTest file: {t.get('tests')}\n"
            f"Brief:\n{t.get('brief')}\nDone when:\n- " + "\n- ".join(t.get("done_when") or []))
