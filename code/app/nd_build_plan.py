"""
nd_build_plan.py — build multi-file projects one file per fresh context.

THE PROBLEM THIS SOLVES
-----------------------
Asked to build a 9-file app, the agent put everything in one conversation: the
brief, four file reads, and every file it had already written. By file five the
prompt was 100% of an 8192-token window, Ollama silently dropped the oldest
messages -- the user's actual instruction -- and the model started improvising.
It then rewrote one .bat file 16 times because it no longer knew what came next.

Asking the user to notice this in advance is a bad deal: they would have to know
the model's context window, guess the file count, and estimate how much it will
read along the way. ND knows all three.

THE APPROACH
------------
    1. PLAN   one small call -> a manifest of files, plus a design brief
    2. BUILD  one file per FRESH conversation, carrying forward only the
              manifest and the brief (small, fixed size) -- never file contents
    3. REPORT what is actually on disk

Context per step stays flat instead of growing with each file, and "what is the
next file" comes from the manifest rather than the model's memory, which removes
the rewrite loop as a side effect.

This module holds the pure logic -- prompts, parsing, state -- so it is testable
without a model or a GPU. The launcher owns orchestration.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Optional

__all__ = ["looks_like_build", "plan_prompt", "parse_manifest", "BuildPlan"]

# Deliberately narrow. A false positive costs the user a wasted planning call on
# an ordinary question, which is worse than a false negative -- a missed split
# just behaves the way ND already did.
_BUILD_VERB = r"(?:creat|build|make|writ|recreat|rebuild|remake|implement|scaffold|port|convert)"
_ARTEFACT = (r"(?:app|application|site|website|web\s*page|webpage|page|ui|interface|dashboard|"
             r"game|tool|clone|front\s*end|frontend|project|prototype|landing)")
_BUILD_RE = re.compile(_BUILD_VERB + r"\w*\b[^.\n]{0,60}\b" + _ARTEFACT, re.I)

# "index.html, styles.css and app.js" — an explicit list of files is a build
# request even without a verb match.
_MULTI_EXT_RE = re.compile(r"\.(?:html?|css|js|jsx|ts|tsx|py|json|bat|ps1|md)\b", re.I)

# ...but only when at least one of them is something you BUILD. Two extensions
# alone used to be enough, so "read config.json, then write README.md and
# CHANGELOG.md" was planned as a UI build — complete with a palette-and-typeface
# design brief, which is how <!DOCTYPE html> ended up as the first line of a
# markdown file, alongside an index.html nobody had asked for. Measured
# 2026-09-01.
_CODE_EXT = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx",
             ".vue", ".svelte", ".py"}


# Three named paths is a build, whatever their extensions. Counting distinct
# EXTENSIONS missed "app/wishlist/models.py, schemas.py, router.py" -- three new
# files, one extension -- so it fell through to the change-existing-code path and
# the model edited app/models.py instead of creating anything. Measured on T2.
_FILE_PATH_RE = re.compile(
    r"\b[\w./\\-]+[/\\][\w-]+\.(?:html?|css|jsx?|tsx?|py|vue|svelte|mjs)\b"
    r"|\b[\w-]+\.(?:html?|css|jsx?|tsx?|py|vue|svelte|mjs)\b", re.I)


# The request says, in words, that it is about ONE file. Measured 2026-09-24:
# "Change ONLY the per-axis loop in set_location.py ... Keep everything else
# exactly as it is" named set_location.py, probe.py (to import from) and
# EDITOR_FACTS.md (to read) -- a .py and a .md, which the extension rule counts
# as a build. The planner then scheduled all three, tried to cut EDITOR_FACTS.md
# from 125 lines to 35 and rewrote probe.py, while the one file asked for was
# never changed; the reply said "Built 3 of 3" and quoted a colour palette.
# Every single-file milestone prompt in that project matched the build rules;
# the earlier ones only escaped because the planner happened to list one file.
_SINGLE_FILE_RE = re.compile(
    r"\b(?:write|create|change|edit|replace|fix|modify|update)\s+(?:only\s+)?"
    r"(?:one|1|a\s+single)\s+(?:new\s+)?file\b"
    r"|\b(?:one|a\s+single)\s+file\s+only\b"
    r"|\bwrite\s+only\s+(?:that|this|the\s+one)\s+file\b"
    r"|\bonly\s+(?:that|this)\s+file\b"
    r"|\b(?:change|edit|modify)\s+only\b"
    r"|\bkeep\s+everything\s+else\b"
    # "Nothing else has changed" (the T4 benchmark prompt) describes the
    # situation, not the scope, so a following has/was/is does not count.
    r"|\bnothing\s+else\b(?!\s+(?:has|had|was|is|changed)\b)",
    re.I)


def single_file_scope(text: str) -> bool:
    """Does the request explicitly confine itself to ONE file?"""
    return bool(_SINGLE_FILE_RE.search(text or ""))


_FILE_NAME_RE = re.compile(
    r"(?<![\w.])((?:[A-Za-z]:)?[\w\\/.-]*?[\w-]+\.(?:py|pyw|js|jsx|ts|tsx|mjs|html|htm|css|"
    r"json|md|txt|toml|ya?ml|ini|cfg|ps1|bat|cmd|sh|go|rs|java|kt|c|cc|cpp|h|hpp|cs|rb|"
    r"php|lua|sql|xml|svg))\b")
# A sentence is split at the end-of-sentence mark, not at the dot inside a name.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
# "... do not edit probe.py or fakegame.py" names files that are OFF limits.
_NEGATION_RE = re.compile(r"\b(?:do\s+not|don'?t|never|not|except|nor|without)\b", re.I)


_CREATE_FILES_RE = re.compile(
    r"\b(?:create|add|write|make)\s+(?:the\s+)?(?:two|three|four|five|several|\d+|some)\s+(?:new\s+)?files?\b"
    r"|\b(?:create|add|make)\s+(?:a\s+|two\s+|three\s+)?new\s+files?\b", re.I)
_LOCATION_REF_RE = re.compile(
    r"\b(?:next\s+to|beside|alongside|in\s+the\s+same\s+(?:folder|directory)\s+as|near)\s+[`'\"]?[\w./\\:-]+", re.I)


def single_file_target(text: str) -> "str | None":
    """The ONE file an explicitly one-file request names, or None.

    Measured 2026-09-25: "Change ONLY set_location.py ... Write only set_location.py"
    was honoured in words only -- ND's test check then asked for a test and the
    model wrote test_set_location.py. Enforcing the scope needs the file itself.
    Only files named in a sentence that carries the scope phrase count, and only
    before any negation in it, so "Change ONLY a.py; do not edit b.py" gives a.py.
    Several different files -> None: ambiguous, so nothing is confined.
    """
    if not single_file_scope(text):
        return None
    # Asking for NEW files is not a one-file change (Elena Live launcher request:
    # "Create two new files ... and change nothing else").
    if _CREATE_FILES_RE.search(text or ""):
        return None
    names = []
    for sent in _SENTENCE_RE.split(text or ""):
        if not _SINGLE_FILE_RE.search(sent):
            continue
        head = _NEGATION_RE.split(sent, maxsplit=1)[0]
        # "next to server.py" names a place, not the file to change.
        head = _LOCATION_REF_RE.sub(" ", head)
        names += _FILE_NAME_RE.findall(head)
    distinct = {n.replace("/", "\\").lower().rstrip(".") for n in names}
    if len({d.rsplit("\\", 1)[-1] for d in distinct}) != 1:
        return None
    # Prefer the most specific spelling (a path over a bare name).
    return max(names, key=len).rstrip(".")


def looks_like_build(text: str, workspace: str = "") -> bool:
    """Is this a request to produce several files?

    `workspace` is what separates "build three new files" from "change three
    existing ones" -- the words are identical and only the disk knows. Without
    it the path rule is skipped entirely rather than guessing, because guessing
    wrong sends a change request into the build planner.
    """
    t = (text or "").strip()
    if len(t) < 15:
        return False
    # An explicitly ONE-file request is never a multi-file build, whatever else it
    # mentions. See _SINGLE_FILE_RE.
    if _SINGLE_FILE_RE.search(t):
        return False
    if _BUILD_RE.search(t):
        return True
    if workspace:
        paths = {m.group(0).replace("\\", "/") for m in _FILE_PATH_RE.finditer(t)}
        ws = Path(workspace)
        # Only paths that do NOT exist yet. T3 names three real files and is a
        # change; T2 names three that do not exist and is a build.
        new = [p for p in paths if not (ws / p).exists() and not Path(p).exists()]
        if len(new) >= 3:
            return True
    exts = {m.group(0).lower() for m in _MULTI_EXT_RE.finditer(t)}
    return len(exts) >= 2 and bool(exts & _CODE_EXT)


PLAN_PROMPT = """Plan this build. Do NOT write any code yet and do not call any tools.

THE REQUEST:
{task}

WORKING DIRECTORY: {workspace}

Reply with ONE json object and nothing else, in exactly this shape:

{{
  "brief": "palette (3-5 colours), typeface pairing, spacing rhythm, and the mood in three words",
  "files": [
    {{"path": "<absolute path in the working directory>", "purpose": "<one line>"}}
  ]
}}

Rules:
- CODE AND TEXT FILES ONLY. You can only write text. Never plan an .mp3, .png,
  .jpg, .wav, .ico or any other binary asset - you cannot produce one, and a
  placeholder file with the wrong extension is worse than no file.
- Never plan a README, LICENSE, or notes file unless it was explicitly asked for.
- NEVER plan separate files for icons, artwork, or UI states. A loading, empty
  or error state is CSS and markup INSIDE the page - not loading.svg. Icons are
  inline <svg> in the page. A plan of one stub page plus three .svg files spends
  every build step on decoration and leaves the actual app unwritten.
- ORDER MATTERS. Each file is written in turn, and every step is told the exact
  names the files before it defined. So anything other files import must come
  FIRST: models before the schemas that use them, schemas before the router that
  returns them. A file written before the thing it imports has to guess that
  name, and it guesses wrong.
- For a web page the entry .html is the exception: it is the one that matters, so
  put it first and let the rest follow.
- Strongly prefer ONE self-contained .html with its CSS in a <style> block and
  its JS in a <script> block. Separate files must agree with each other, and
  when they do not the page renders unstyled.
- Absolute paths, inside the working directory. No subfolders unless necessary.
- No more than {max_files} files. Three good files beat eight thin ones.
"""

# Extensions the model cannot actually produce. A planned .mp3 costs a whole
# build step and yields a text file with a misleading name.
_BINARY_EXT = {".mp3", ".wav", ".ogg", ".png", ".jpg", ".jpeg", ".gif", ".ico",
               ".webp", ".mp4", ".woff", ".woff2", ".ttf", ".otf", ".zip", ".pdf"}
# Text, so writable -- but decoration, and it belongs INSIDE the page.
_DECOR_EXT = {".svg"}
# What counts as a real page worth a build step.
_PAGE_EXT = {".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte", ".php"}


def plan_prompt(task: str, workspace: str, max_files: int = 8, house: str = "") -> str:
    # House style goes into the PLANNING step too, not just the build steps:
    # the brief written here is what every later file is judged against, so
    # rules that arrive afterwards are already too late to shape it.
    return PLAN_PROMPT.format(task=(task or "").strip(),
                              workspace=workspace or "(not set)",
                              max_files=max_files) + (house or "")


def _first_json_object(text: str) -> Optional[dict]:
    """Pull the first balanced {...} out of a reply. Small models wrap JSON in
    prose or a code fence no matter how firmly they are told not to."""
    if not text:
        return None
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def parse_manifest(text: str, workspace: str = "", max_files: int = 8) -> dict:
    """Returns {"brief": str, "files": [{"path", "purpose"}], "error": str}."""
    obj = _first_json_object(text)
    if not obj:
        return {"brief": "", "files": [], "error": "no JSON object in the reply"}

    raw = obj.get("files")
    if isinstance(raw, dict):            # {"index.html": "purpose", ...}
        raw = [{"path": k, "purpose": v} for k, v in raw.items()]
    if not isinstance(raw, list):
        return {"brief": str(obj.get("brief") or ""), "files": [],
                "error": "manifest had no files list"}

    base = Path(workspace) if workspace else None
    # Decoration is only dropped when the plan actually contains a page to put
    # it in. A plan that is genuinely just SVGs stays as it is.
    def _p(it):
        if isinstance(it, str):
            return it
        return str((it or {}).get("path") or (it or {}).get("file")
                   or (it or {}).get("name") or "")
    has_page = any(Path(_p(i)).suffix.lower() in _PAGE_EXT for i in raw)
    files, seen = [], set()
    for item in raw:
        if isinstance(item, str):
            item = {"path": item, "purpose": ""}
        if not isinstance(item, dict):
            continue
        p = str(item.get("path") or item.get("file") or item.get("name") or "").strip()
        p = p.strip('"').strip("'")
        if not p:
            continue
        fp = Path(p)
        # A relative path from the model is normal; anchor it rather than
        # letting it resolve against whatever the process cwd happens to be.
        if not fp.is_absolute() and base:
            fp = base / fp
        # Drop what the model cannot actually write. Measured: one plan spent a
        # whole step on assets/sounds/ui-click.mp3 and produced 333 bytes of
        # text named .mp3.
        if fp.suffix.lower() in _BINARY_EXT:
            continue
        # Drop decoration when a real page is in the plan. Measured: a plan of
        # index.html + loading.svg + error.svg + empty-state.svg spent three of
        # four build steps drawing icons and left index.html a 3 KB stub that
        # rendered as nothing but a loading screen. Inline SVG belongs in the
        # page, so these are never worth a build step of their own.
        if fp.suffix.lower() in _DECOR_EXT and has_page:
            continue
        key = str(fp).lower().replace("/", "\\")
        if key in seen:
            continue
        seen.add(key)
        files.append({"path": str(fp), "purpose": str(item.get("purpose") or "").strip()})
        if len(files) >= max_files:
            break
    return {"brief": str(obj.get("brief") or "").strip(), "files": files, "error": ""}


FILE_PROMPT = """{brief_block}You are building this project, one file per message.

THE PLAN ({done} of {total} files already written):
{plan_lines}

WRITE THIS FILE NOW: {path}
Purpose: {purpose}

Rules:
- Call write_file ONCE, with this exact path and the COMPLETE contents. Nothing else.
- Write the whole file. No placeholders, no "rest of the code here", no TODOs.
- Do not write any other file from the plan - the next message handles the next one.
{extra}"""

HTML_EXTRA = """- Keep this page SELF-CONTAINED: put the CSS in a <style> block and the JS in a
  <script> block in this same file, unless the plan explicitly lists separate
  files for them. A page that links a stylesheet that was never written renders
  as unstyled Times New Roman, and that is the single most common failure here.
- Include <meta name="viewport" content="width=device-width, initial-scale=1">.
- After write_file succeeds, call design_review on this file and fix anything it
  reports as BROKEN."""

SIBLING_EXTRA = """- The other files in the plan already exist or will exist at the paths listed.
  Reference them by those exact filenames."""

# How many names to carry per file. A module with fifty exports does not need all
# of them quoted back; the classes and functions a sibling would import are at
# the top and are what drift.
CARRY_MAX_NAMES = 18


# How far up to describe, and how many modules to name per level. Two levels
# covers "my siblings" and "the package above me", which is where the mistakes
# are; beyond that the list gets long and stops being read.
REL_MAX_LEVELS = 2
REL_MAX_PER_LEVEL = 10


def relative_import_map(path, workspace, max_levels=REL_MAX_LEVELS) -> list:
    """Which dots reach which folder, from this file. [(dots, folder, [names])].

    Walks up from the file towards the workspace root, so it works for a package
    that does not exist yet -- at build time app/wishlist/__init__.py may not
    have been written, and an __init__-based walk would find nothing.
    """
    p, ws = Path(path), Path(workspace) if workspace else None
    if p.suffix.lower() != ".py" or not ws:
        return []
    try:
        p.relative_to(ws)
    except (ValueError, OSError):
        return []
    out, here = [], p.parent
    for level in range(1, max_levels + 1):
        try:
            rel = here.relative_to(ws)
        except ValueError:
            break
        names = []
        try:
            for child in sorted(here.iterdir()):
                if child == p:
                    continue                       # the file being written
                if child.suffix == ".py" and not child.name.startswith("_"):
                    names.append(child.stem)
                elif child.is_dir() and (child / "__init__.py").is_file():
                    names.append(child.name)
        except OSError:
            names = []
        if names:
            out.append(("." * level, str(rel).replace("\\", "/") or ".",
                        names[:REL_MAX_PER_LEVEL]))
        if here == ws:
            break
        here = here.parent
    return out


def relative_import_block(path, workspace) -> str:
    """The dot guide handed to a build step. Empty when there is nothing to say."""
    rows = relative_import_map(path, workspace)
    if not rows:
        return ""
    lines = []
    for dots, folder, names in rows:
        shown = ", ".join(names)
        lines.append(f"    from {dots}<name> import ...   reaches {folder}/  "
                     f"-> {shown}")
    return ("\n- IMPORTING WITHIN THIS PROJECT. This file is at "
            f"{Path(path).name}, and the dots count from where IT sits:\n"
            + "\n".join(lines)
            + "\n  Count the dots from this file, not from the project root. One dot "
              "is the folder this file is in.")


def top_level_names(path) -> list:
    """The names a file defines that another file could refer to.

    Python via AST; everything else by a cheap pattern, because a JS module's
    exports drift exactly the same way and a regex is enough to quote them back.
    """
    p = Path(path)
    try:
        body = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if p.suffix.lower() == ".py":
        try:
            tree = ast.parse(body)
        except SyntaxError:
            return []
        out = []
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append(("class " if isinstance(node, ast.ClassDef) else "def ")
                           + node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and not t.id.startswith("_"):
                        out.append(t.id)
        return out[:CARRY_MAX_NAMES]
    out = []
    for m in re.finditer(r"^\s*(?:export\s+)?(?:class|function|const|let|var)\s+"
                         r"([A-Za-z_$][\w$]*)", body, re.M):
        out.append(m.group(1))
    return out[:CARRY_MAX_NAMES]

# Files a design brief can actually apply to. Same set the UI house style uses.
_BRIEF_EXT = {".html", ".htm", ".css", ".jsx", ".tsx", ".vue", ".svelte"}


_HTML_ID = re.compile(r"""\bid\s*=\s*["']([^"'\s>]+)["']""", re.I)
_JS_BYID = re.compile(r"""getElementById\(\s*["']([^"']+)["']\s*\)""")
_JS_QSEL = re.compile(r"""querySelector(?:All)?\(\s*["']#([\w-]+)["']""")
_JS_HELPER = re.compile(
    r"""(?:function\s+([$\w]+)\s*\(\s*(\w+)\s*\)\s*\{\s*return\s+document\.getElementById\(\s*\2\s*\)"""
    r"""|(?:const|let|var)\s+([$\w]+)\s*=\s*(?:function\s*)?\(?\s*(\w+)\s*\)?\s*(?:=>)?\s*\{?\s*(?:return\s+)?document\.getElementById\(\s*\4\s*\))""")


def html_ids(text: str) -> set:
    """Element ids a page defines."""
    return set(_HTML_ID.findall(text or ""))


def js_ids_used(text: str) -> set:
    """Element ids a script looks up: getElementById("x"), querySelector("#x"),
    and calls to a one-line helper that wraps getElementById, like $("x")."""
    text = text or ""
    ids = set(_JS_BYID.findall(text)) | set(_JS_QSEL.findall(text))
    for m in _JS_HELPER.finditer(text):
        name = m.group(1) or m.group(3)
        if name:
            ids |= set(re.findall(re.escape(name) + r"""\(\s*["']([\w-]+)["']\s*\)""", text))
    return ids


_TAG_ID = re.compile(r"""<([a-zA-Z][\w-]*)\b[^>]*?\bid\s*=\s*["']([^"'\s>]+)["']""", re.I)


def page_tags(text: str) -> dict:
    """{id: tag name} for every element of a page that has an id."""
    return {i: t.lower() for t, i in _TAG_ID.findall(text or "")}


def canvas_ids_needed(text: str) -> set:
    """Ids a script calls getContext on - those elements must be <canvas>."""
    text = text or ""
    out = set(re.findall(r"""getElementById\(\s*["']([^"']+)["']\s*\)\s*\.\s*getContext""", text))
    helpers = [m.group(1) or m.group(3) for m in _JS_HELPER.finditer(text)]
    lookups = [r"""document\.getElementById\(\s*["']([\w-]+)["']\s*\)""",
               r"""document\.querySelector\(\s*["']#([\w-]+)["']\s*\)"""]
    lookups += [re.escape(h) + r"""\(\s*["']([\w-]+)["']\s*\)""" for h in helpers if h]
    for lk in lookups:
        for m in re.finditer(r"""(?:var|let|const)?\s*([$\w]+)\s*=\s*""" + lk, text):
            var, cid = m.group(1), m.group(2)
            if _draws_on(var, text):
                out.add(cid)
    out |= set(re.findall(r"""new\s+(?:window\.)?ElenaMark\(\s*document\.getElementById\(\s*["']([\w-]+)["']""", text))
    return out


def _draws_on(var: str, text: str) -> bool:
    """Does the script call getContext on `var`, or hand it to ElenaMark (which does)?"""
    v = re.escape(var)
    return bool(re.search(r"\b" + v + r"\s*\.\s*getContext\b", text)
                or re.search(r"new\s+(?:window\.)?ElenaMark\(\s*" + v + r"\b", text))


def drawn_non_canvas_created(text: str) -> list:
    """[(variable, tag)] the script CREATES as a non-canvas element and then draws
    on - a bug in the script itself, not the page."""
    out = []
    for m in re.finditer(r"""([$\w]+)\s*=\s*document\.createElement\(\s*["'](\w+)["']\s*\)""", text or ""):
        var, tag = m.group(1), m.group(2).lower()
        if tag != "canvas" and _draws_on(var, text):
            out.append((var, tag))
    return out


_GLOBAL_DEF = re.compile(r"\b(?:window|global|globalThis|self)\.([A-Z_$][\w$]*)\s*=(?!=)")


def globals_defined(text: str) -> set:
    """Globals a script defines: window.X = ..., global.X = ... (capitalised names,
    i.e. libraries and classes, not every small flag)."""
    return set(_GLOBAL_DEF.findall(text or ""))


def globals_used(text: str) -> set:
    """Globals a script uses at load time or later: window.X, new X(."""
    t = text or ""
    return set(re.findall(r"\bwindow\.([A-Z_$][\w$]*)", t)) | set(re.findall(r"\bnew\s+([A-Z][\w$]*)\s*\(", t))


def script_order_problems(scripts: list) -> list:
    """scripts = [(name, text)] in page order. [(user, global, definer)] where a
    script uses a global that only a LATER script defines."""
    out = []
    for i, (name, text) in enumerate(scripts):
        before = set().union(*[globals_defined(t) for _, t in scripts[:i + 1]]) if i >= 0 else set()
        for j in range(i + 1, len(scripts)):
            later = globals_defined(scripts[j][1]) - before
            for g in sorted(globals_used(text) & later):
                out.append((name, g, scripts[j][0]))
    return out


_LIVE_ALWAYS = re.compile(r"(?:^|[-_])(overlay|pill|badge|indicator|status|spinner|toast)(?:$|[-_])", re.I)
_LIVE_NAME = re.compile(
    r"(?:^|[-_])(readout|stat|stats|count|counter|clock|time|age|meter|gauge|live|ticker|cpu|gpu|"
    r"vram|ram|disk|mem|model|task|path|value|uptime|fps|rate|total|latency|tokens)(?:$|[-_])", re.I)
_PLACEHOLDER = re.compile(
    r"^(?:[\u2014\u2013\-.:\u2026%\s]*|0|n/?a|none|idle|offline|--:--(?::--)?|"
    r"(?:waiting|loading|polling|connecting)\b.*)$", re.I)
_OPEN_TAG = re.compile(r"""<([a-zA-Z][\w-]*)\b([^>]*?\bid\s*=\s*["']([^"'\s>]+)["'][^>]*)>""", re.I)


def undriven_ids(page_text: str, script_texts: list) -> list:
    """[(id, current text)] for page elements that look like live state - an
    overlay, pill or status, or a leaf element whose name reads like a reading
    (cpu, count, clock, model, path ...) or whose text is a placeholder ("-",
    "0", "Waiting ...") - that no script ever names. Such a page loads, draws,
    and still shows "Waiting for telemetry" forever."""
    page = page_text or ""
    js = "\n".join(script_texts or [])
    out = []
    for m in _OPEN_TAG.finditer(page):
        tag, attrs, eid = m.group(1).lower(), m.group(2), m.group(3)
        if tag in ("canvas", "script", "style", "link", "meta", "svg", "img", "body", "html"):
            continue
        rest = page[m.end():m.end() + 400]
        lt = rest.find("<")
        text = (rest[:lt] if lt >= 0 else rest).strip()
        leaf = lt >= 0 and rest[lt:lt + 2] == "</"
        live = (bool(_LIVE_ALWAYS.search(eid))
                or (leaf and (bool(_LIVE_NAME.search(eid)) or (text != "" and bool(_PLACEHOLDER.match(text))))))
        if not live:
            continue
        if re.search(r"""["'`]#?""" + re.escape(eid) + r"""["'`]""", js):
            continue
        if "-" in eid and re.search(r"""["'`]#?""" + re.escape(eid.rsplit("-", 1)[0] + "-") + r"""(?:["'`]\s*\+|\$\{)""", js):
            continue                      # built by name: "stat-" + key
        cm = re.search(r"""\bclass\s*=\s*["']([^"']+)["']""", attrs)
        if cm and any(re.search(r"""["'`][^"'`]*\.""" + re.escape(k) + r"""\b""", js) for k in cm.group(1).split()):
            continue                      # reached through querySelector(".pill") ...
        out.append((eid, text[:40]))
    return out


def page_problems(page_text: str, script_texts: list) -> dict:
    """{"missing": [ids the scripts look up that the page lacks],
        "not_canvas": [(id, tag) the scripts draw on that are not <canvas>]}"""
    tags = page_tags(page_text)
    need, canv = set(), set()
    for t in script_texts:
        need |= js_ids_used(t)
        canv |= canvas_ids_needed(t)
    return {"missing": sorted(need - set(tags)),
            "not_canvas": sorted((i, tags[i]) for i in canv if i in tags and tags[i] != "canvas")}


class BuildPlan:
    """State for one multi-file build. Deliberately holds no file CONTENT --
    that is the whole point: what carries forward between steps is the manifest
    and the brief, both small and fixed in size."""

    def __init__(self, manifest: dict, task: str = "", house: str = "",
                 workspace: str = ""):
        self.brief = manifest.get("brief", "")
        self.files = list(manifest.get("files", []))
        self.task = task
        self.house = house or ""       # injected only for UI files, see below
        self.results: list[dict] = []      # {path, ok, bytes, note}
        self.defined: dict[str, list] = {}  # path -> names it actually defines
        self.workspace = workspace or ""
        self.idx = 0
        self.spec = ""                 # the spec the request names, set by the caller
        self.page_ids: dict[str, set] = {}    # .html path -> ids it defines
        self.script_ids: dict[str, set] = {}  # .js path -> ids it looks up

    def __len__(self):
        return len(self.files)

    @property
    def done(self):
        return self.idx

    def remaining(self):
        return self.files[self.idx:]

    def current(self) -> Optional[dict]:
        return self.files[self.idx] if self.idx < len(self.files) else None

    def plan_lines(self) -> str:
        out = []
        for i, f in enumerate(self.files):
            if i < self.idx:
                mark = "[done]"
            elif i == self.idx:
                mark = "[NOW] "
            else:
                mark = "[next]"
            out.append(f"  {mark} {f['path']}"
                       + (f" - {f['purpose']}" if f.get("purpose") else ""))
        return "\n".join(out)

    def retry_prompt(self) -> str:
        """Blunt second attempt when the file is not on disk after step one.

        Measured: on the entry file the model called design_review on
        index.html without ever having written it. One corrective round is far
        cheaper than losing the most important file in the plan."""
        f = self.current() or {}
        return (f"{f.get('path','')} was NOT created. Nothing is on disk at that path.\n\n"
                "Call write_file RIGHT NOW with exactly:\n"
                f'  path: {f.get("path","")}\n'
                "  content: the complete file, start to finish\n\n"
                "Do not call any other tool first. Do not review, inspect or list "
                "anything. Do not explain. One write_file call, complete contents."
                + (f"\n\nIt should be: {f.get('purpose')}" if f.get("purpose") else "")
                + (f"\n\nDesign brief:\n{self.brief}" if self.brief else ""))

    def verify_current(self) -> bool:
        f = self.current() or {}
        try:
            p = Path(f.get("path", ""))
            return p.is_file() and p.stat().st_size > 0
        except OSError:
            return False

    def prompt_for_current(self) -> str:
        f = self.current()
        if not f:
            return ""
        ext = Path(f["path"]).suffix.lower()
        extra = HTML_EXTRA if ext in (".html", ".htm") else ""
        if len(self.files) > 1:
            extra = (extra + "\n" + SIBLING_EXTRA) if extra else SIBLING_EXTRA
            # SIBLING_EXTRA gives it the filenames. This gives it the names
            # inside them, which is what actually drifts.
            extra += self.defined_block()
        # Which dots reach which folder. Measured on T2: one run wrote
        # `from .database` in models.py and `from ..database` in router.py, in
        # the same build -- it is counting dots blind.
        extra += relative_import_block(f["path"], self.workspace)
        # The brief is a palette, a typeface pairing and a mood. Handing that to
        # a README, a config file or a batch script is how a markdown file came
        # back starting with <!DOCTYPE html>. Gate it by extension, exactly as
        # the house style below already is.
        brief_block = (f"DESIGN BRIEF (follow it exactly):\n{self.brief}\n\n"
                       if self.brief and ext in _BRIEF_EXT else "")
        out = FILE_PROMPT.format(
            brief_block=brief_block, done=self.idx, total=len(self.files),
            plan_lines=self.plan_lines(), path=f["path"],
            purpose=f.get("purpose") or "(not stated)", extra=extra)
        # Only on the files it can apply to. Spending 2 KB of an 8K window on
        # colour and state rules while writing games.json helps nothing.
        if self.house and ext in (".html", ".htm", ".css", ".jsx", ".tsx", ".vue", ".svelte"):
            out += self.house
        # The spec, to every file. A step written from a one-line purpose
        # invents its own data shapes (Elena Live, 2026-10-18: server.py made up
        # a state format and test_flows.py called a method that did not exist).
        if self.spec:
            out += self.spec
        out += self.ids_block(ext)
        return out

    def ids_block(self, ext: str) -> str:
        """The element ids the other side of a page/script pair already uses."""
        if ext in (".js", ".mjs") and self.page_ids:
            rows = [f"  {Path(k).name}: " + ", ".join(sorted(v)) for k, v in self.page_ids.items() if v]
            if rows:
                return ("\n- THE PAGE IS ALREADY WRITTEN and defines exactly these element ids:\n"
                        + "\n".join(rows) + "\n  Look up ONLY these ids, spelled exactly so. Do not "
                        "invent an id the page does not have - getElementById returns null for it "
                        "and the whole script dies. If you need an element that is not there, "
                        "create it from the script.")
        if ext in (".html", ".htm") and self.script_ids:
            need = sorted(set().union(*self.script_ids.values()))
            if need:
                return ("\n- THE SCRIPT IS ALREADY WRITTEN and looks up these element ids: "
                        + ", ".join(need) + "\n  The page MUST define an element with every one "
                        "of these ids, spelled exactly so.")
        return ""

    def id_mismatches(self) -> dict:
        """{script path: sorted ids it looks up that no built page defines}."""
        have = set().union(*self.page_ids.values()) if self.page_ids else set()
        if not self.page_ids:
            return {}
        out = {}
        for k, v in self.script_ids.items():
            miss = sorted(v - have)
            if miss:
                out[k] = miss
        return out

    def record(self, note: str = "") -> dict:
        """Verify the current file on disk and advance. Truth comes from the
        filesystem, not from what the model said it did."""
        f = self.current() or {}
        p = Path(f.get("path", ""))
        try:
            ok = p.is_file() and p.stat().st_size > 0
            size = p.stat().st_size if ok else 0
        except OSError:
            ok, size = False, 0
        row = {"path": str(p), "ok": ok, "bytes": size, "note": note}
        # Read back what this file actually defines, so the NEXT file is told
        # rather than left to guess. This is the whole fix for cross-file naming
        # drift, and it costs one parse of a file already on disk.
        if ok:
            try:
                names = top_level_names(p)
                if names:
                    self.defined[str(p)] = names
            except Exception:
                pass
            # Element ids, both ways: a page and its script are written in
            # separate contexts and drifted apart (Elena Live, 2026-10-19).
            try:
                ext = p.suffix.lower()
                if ext in (".html", ".htm"):
                    self.page_ids[str(p)] = html_ids(p.read_text(encoding="utf-8", errors="replace"))
                elif ext in (".js", ".mjs"):
                    self.script_ids[str(p)] = js_ids_used(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                pass
        self.results.append(row)
        self.idx += 1
        return row

    def defined_block(self) -> str:
        """What the files written so far actually contain."""
        if not self.defined:
            return ""
        lines = []
        for path, names in self.defined.items():
            lines.append(f"  {Path(path).name}: " + ", ".join(names))
        return ("\n- ALREADY WRITTEN. These files exist and contain exactly these "
                "names:\n" + "\n".join(lines) + "\n"
                "  Use them EXACTLY as spelled. Do not rename them, do not guess a "
                "different word for the same thing, and do not import a name that is "
                "not in this list.")

    def report(self) -> str:
        good = [r for r in self.results if r["ok"]]
        bad = [r for r in self.results if not r["ok"]]
        lines = [f"Built {len(good)} of {len(self.files)} planned file(s), "
                 "one per step so the context stayed clear."]
        if good:
            lines.append("\nOn disk:")
            lines += [f"  - {r['path']} ({r['bytes']:,} bytes)" for r in good]
        if bad:
            lines.append("\nNOT written:")
            lines += [f"  - {r['path']}" + (f" — {r['note']}" if r['note'] else "")
                      for r in bad]
            lines.append("\nAsk for any of these by name and it will build just that one.")
        if self.brief:
            lines.append(f"\nBuilt to this brief:\n{self.brief}")
        return "\n".join(lines)
