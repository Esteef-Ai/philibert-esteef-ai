"""
nd_obsidian_memory.py  --  Obsidian-backed memory for NeuralDock
================================================================
Drop this file next to NeuralDock_launcher.py.

Design contract (from the four decisions made before this was written):

  1. WRITE FORMAT   one note per fact, inside <vault>/AI Memory/
  2. READ SCOPE     whole-vault awareness, every message
  3. WRITE SAFETY   ND may only create/modify files it created, and only
                    inside AI Memory/. Hand-written notes are read-only.
  4. (installer handled separately in Install_NeuralDock.bat)

--------------------------------------------------------------------------
NOTE ON DECISION 2 -- read this, it changes behaviour
--------------------------------------------------------------------------
"Whole vault, every message" cannot be taken literally. The vault is ~50 KB
across 24 notes today; at num_ctx 32768 that is roughly 12-13k tokens burned
on EVERY request before you have typed a word, and it grows as you write
more notes. It would eventually crowd out the conversation itself.

So this module implements whole-vault *awareness* under a char budget, with
graceful degradation. Three tiers, in priority order:

  Tier 1  ATOMIC MEMORY   every note in AI Memory/, in full. These are the
                          one-line facts ND itself learned. Small, always in.
  Tier 2  VAULT INDEX     every other note in the vault, one line each:
                          title, type, project, tags. ~24 lines / ~2 KB today.
                          The model always knows the vault's full shape.
  Tier 3  FULL BODIES     notes scored as relevant to the current message,
                          injected verbatim until the budget is spent.

If the whole vault fits inside the budget, the whole vault goes in verbatim --
so for a small vault the literal reading of decision 2 is what happens.
Raise `obsidian_budget_chars` in neuraldock_config.json to push more in.

--------------------------------------------------------------------------
Integration -- three edits in NeuralDock_launcher.py
--------------------------------------------------------------------------
(1) near the other imports:

        from nd_obsidian_memory import ObsidianMemory, install_shims

(2) after CONFIG is loaded (needs CONFIG and _CONFIG_DIR to exist):

        OBS = ObsidianMemory(CONFIG, _CONFIG_DIR)
        load_memory, save_memory, memory_to_prompt = install_shims(OBS)

    Those three names keep their original signatures, so every existing call
    site -- including /api/memory and extract_memory_from_conversation() --
    keeps working with no further changes. Delete or comment out the old
    def load_memory / save_memory / memory_to_prompt bodies.

(3) at the injection site (was ~line 3210), replace

        mem_str = memory_to_prompt(mem)

    with

        mem_str = OBS.context_for(user_text)

    where user_text is the latest user message string. That is what turns on
    the relevance tier. If you skip (3) it still works -- you just get tiers
    1 and 2 and no relevance-selected bodies.

Config keys read from neuraldock_config.json (all optional):

    obsidian_root            "D:\\Obsidian"
    obsidian_vault           "EsteefAI"          (auto-detected if absent)
    obsidian_memory_folder   "AI Memory"
    obsidian_budget_chars    12000
    obsidian_enabled         true

Stdlib only. No Obsidian plugins required -- this is plain files on disk,
which is the whole point: Obsidian sees ND's writes instantly and vice versa.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Matches the categories NeuralDock already uses. Keep in sync with
# MEMORY_CATEGORIES in the launcher.
MEMORY_CATEGORIES = [
    "projects", "preferences", "corrections",
    "paths", "hardware", "people", "facts",
]

DEFAULT_BUDGET = 12000          # characters, not tokens (~3k tokens)
MARKER_KEY = "nd_generated"     # front-matter flag proving ND wrote a note
STOPWORDS = {
    "the", "and", "for", "you", "your", "with", "that", "this", "have", "has",
    "was", "are", "but", "not", "can", "get", "got", "how", "what", "when",
    "where", "why", "from", "into", "about", "would", "should", "could",
    "there", "their", "them", "then", "than", "some", "just", "like", "make",
    "made", "does", "did", "will", "its", "it's", "i'm", "i've", "we're",
}


# ---------------------------------------------------------------------------
# tiny front-matter parser (no pyyaml dependency)
# ---------------------------------------------------------------------------

def parse_front_matter(text: str) -> Tuple[dict, str]:
    """Return (front_matter_dict, body). Tolerant: never raises."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4:].lstrip("\n")
    fm: dict = {}
    for line in raw.splitlines():
        line = line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            items = [v.strip().strip("'\"") for v in val[1:-1].split(",")]
            fm[key] = [v for v in items if v]
        elif val.lower() in ("true", "false"):
            fm[key] = (val.lower() == "true")
        else:
            fm[key] = val.strip("'\"")
    return fm, body


def dump_front_matter(fm: dict) -> str:
    lines = ["---"]
    for key, val in fm.items():
        if isinstance(val, list):
            inner = ", ".join(str(v) for v in val)
            lines.append(f"{key}: [{inner}]")
        elif isinstance(val, bool):
            lines.append(f"{key}: {'true' if val else 'false'}")
        else:
            lines.append(f"{key}: {val}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def slugify(text: str, maxlen: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip()
    text = re.sub(r"[\s_]+", " ", text)
    if len(text) > maxlen:
        cut = text[:maxlen].rsplit(" ", 1)[0]
        text = cut or text[:maxlen]
    return text or "memory"


def _tokens(text: str) -> set:
    words = re.findall(r"[a-z0-9][a-z0-9'\-]{2,}", (text or "").lower())
    return {w for w in words if w not in STOPWORDS}


# ---------------------------------------------------------------------------
# the vault
# ---------------------------------------------------------------------------

class ObsidianMemory:
    """Vault-backed memory. Reads the whole vault, writes only to AI Memory/."""

    def __init__(self, config: Optional[dict] = None,
                 config_dir: Optional[Path] = None):
        config = config or {}
        self.config = config
        self.config_dir = Path(config_dir) if config_dir else Path.cwd()
        self.enabled = bool(config.get("obsidian_enabled", True))
        self.budget = int(config.get("obsidian_budget_chars", DEFAULT_BUDGET))
        self.mem_folder_name = config.get("obsidian_memory_folder", "AI Memory")

        root = config.get("obsidian_root") or r"D:\Obsidian"
        self.root = Path(root)
        self.vault = self._resolve_vault(config.get("obsidian_vault"))
        self.mem_dir = (self.vault / self.mem_folder_name) if self.vault else None

        # JSON file ND used before. Kept as a fallback and as a migration source.
        self.json_file = self.config_dir / "neuraldock_memory.json"

        self._cache: Dict[Path, Tuple[float, dict, str]] = {}
        self.last_error: Optional[str] = None

    # -- discovery ---------------------------------------------------------

    def _resolve_vault(self, name: Optional[str]) -> Optional[Path]:
        if not self.root.is_dir():
            self.last_error = f"Obsidian root not found: {self.root}"
            return None
        if name:
            cand = self.root / name
            if cand.is_dir():
                return cand
        # a vault is a directory containing .obsidian/, else the only subdir
        subs = [p for p in self.root.iterdir() if p.is_dir()
                and not p.name.startswith(".")]
        marked = [p for p in subs if (p / ".obsidian").is_dir()]
        if len(marked) == 1:
            return marked[0]
        if marked:
            return sorted(marked)[0]
        if len(subs) == 1:
            return subs[0]
        if subs:
            return sorted(subs)[0]
        return None

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.vault and self.vault.is_dir())

    def ensure_memory_dir(self) -> Optional[Path]:
        if not self.available:
            return None
        self.mem_dir.mkdir(parents=True, exist_ok=True)
        return self.mem_dir

    # -- reading -----------------------------------------------------------

    def _read_note(self, path: Path) -> Tuple[dict, str]:
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return {}, ""
        hit = self._cache.get(path)
        if hit and hit[0] == stamp:
            return hit[1], hit[2]
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {}, ""
        fm, body = parse_front_matter(text)
        self._cache[path] = (stamp, fm, body)
        return fm, body

    def all_notes(self) -> List[Path]:
        if not self.available:
            return []
        out = []
        for p in self.vault.rglob("*.md"):
            parts = set(p.parts)
            if ".obsidian" in parts or ".trash" in parts:
                continue
            out.append(p)
        return sorted(out)

    def memory_notes(self) -> List[Path]:
        if not self.available or not self.mem_dir.is_dir():
            return []
        return sorted(p for p in self.mem_dir.glob("*.md")
                      if not p.name.startswith("_"))

    # -- ND-compatible dict view -------------------------------------------

    def load_memory(self) -> dict:
        """Same shape the launcher already expects: {category: [str, ...]}."""
        mem = {c: [] for c in MEMORY_CATEGORIES}
        if not self.available:
            return self._load_json_fallback(mem)
        for path in self.memory_notes():
            fm, body = self._read_note(path)
            if fm.get("type") != "memory":
                continue
            cat = str(fm.get("category", "facts")).strip().lower()
            if cat not in mem:
                cat = "facts"
            fact = self._body_fact(body) or str(fm.get("title", "")).strip()
            if fact:
                mem[cat].append(fact)
        return mem

    @staticmethod
    def _body_fact(body: str) -> str:
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("<!--"):
                continue
            return line.lstrip("-* ").strip()
        return ""

    def _load_json_fallback(self, mem: dict) -> dict:
        try:
            if self.json_file.exists():
                data = json.loads(self.json_file.read_text(encoding="utf-8"))
                for cat in mem:
                    vals = data.get(cat) or []
                    if isinstance(vals, list):
                        mem[cat] = [str(v) for v in vals if str(v).strip()]
        except Exception as exc:
            self.last_error = f"memory json unreadable: {exc}"
        return mem

    def save_memory(self, mem: dict) -> dict:
        """Reconcile the dict view back into notes. Additive + prunes ours."""
        if not self.available:
            return self._save_json_fallback(mem)
        self.ensure_memory_dir()
        wanted = set()
        written, skipped = 0, 0
        for cat in MEMORY_CATEGORIES:
            for fact in (mem.get(cat) or []):
                fact = str(fact).strip()
                if not fact:
                    continue
                path = self.write_fact(fact, cat)
                if path:
                    wanted.add(path.name)
                    written += 1
                else:
                    skipped += 1
        # remove ND-authored notes whose fact is gone (a delete_item call)
        removed = 0
        for path in self.memory_notes():
            if path.name in wanted:
                continue
            fm, _ = self._read_note(path)
            if fm.get(MARKER_KEY) is True:
                try:
                    path.unlink()
                    self._cache.pop(path, None)
                    removed += 1
                except OSError:
                    pass
        self.write_moc()
        self._save_json_fallback(mem)      # mirror, so nothing is ever stranded
        return {"written": written, "removed": removed, "skipped": skipped}

    def _save_json_fallback(self, mem: dict) -> dict:
        try:
            self.json_file.parent.mkdir(parents=True, exist_ok=True)
            self.json_file.write_text(
                json.dumps(mem, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            self.last_error = f"memory json unwritable: {exc}"
        return {"written": 0, "removed": 0, "skipped": 0}

    # -- writing (guarded) -------------------------------------------------

    def _guard(self, path: Path) -> bool:
        """True only if writing this path is allowed by decision 3."""
        if not self.available:
            return False
        try:
            target = path.resolve()
            base = self.mem_dir.resolve()
        except OSError:
            return False
        if target.parent != base:
            self.last_error = f"refused write outside AI Memory: {path}"
            return False
        if target.exists():
            fm, _ = self._read_note(target)
            if fm.get(MARKER_KEY) is not True:
                self.last_error = f"refused overwrite of hand-written note: {path.name}"
                return False
        return True

    def write_fact(self, fact: str, category: str = "facts",
                   project: str = "", tags: Optional[List[str]] = None,
                   source: str = "chat") -> Optional[Path]:
        """One fact -> one note. Returns the path, or None if refused."""
        fact = str(fact).strip()
        if not fact or not self.available:
            return None
        self.ensure_memory_dir()
        category = (category or "facts").strip().lower()
        if category not in MEMORY_CATEGORIES:
            category = "facts"
        project = project or self._guess_project(fact)
        today = datetime.date.today().isoformat()
        name = f"{today} - {slugify(fact)}.md"
        path = self.mem_dir / name

        # same fact already stored under a different date -> leave it alone
        for existing in self.memory_notes():
            fm, body = self._read_note(existing)
            if fm.get(MARKER_KEY) is True and self._body_fact(body) == fact:
                return existing

        if not self._guard(path):
            return None

        tag_list = ["ai-memory", category]
        for extra in (tags or []):
            extra = str(extra).strip().lstrip("#")
            if extra and extra not in tag_list:
                tag_list.append(extra)

        fm = {
            "title": slugify(fact, 80),
            "type": "memory",
            "category": category,
            "project": project or "",
            "source": source,
            "created": today,
            MARKER_KEY: True,
            "tags": tag_list,
        }
        lines = [dump_front_matter(fm), "", fact, ""]
        links = self._links_for(project)
        if links:
            lines += ["", "## Related", ""] + [f"- {l}" for l in links] + [""]
        try:
            path.write_text("\n".join(lines), encoding="utf-8")
        except OSError as exc:
            self.last_error = f"write failed: {exc}"
            return None
        self._cache.pop(path, None)
        return path

    def delete_fact(self, fact: str) -> bool:
        fact = str(fact).strip()
        for path in self.memory_notes():
            fm, body = self._read_note(path)
            if fm.get(MARKER_KEY) is not True:
                continue
            if self._body_fact(body) == fact:
                try:
                    path.unlink()
                    self._cache.pop(path, None)
                    self.write_moc()
                    return True
                except OSError:
                    return False
        return False

    def _guess_project(self, fact: str) -> str:
        """Match the fact against existing project hub notes in the vault."""
        low = fact.lower()
        best, best_len = "", 0
        for path in self.all_notes():
            fm, _ = self._read_note(path)
            proj = str(fm.get("project", "")).strip()
            if not proj or len(proj) <= best_len:
                continue
            if proj.lower() in low:
                best, best_len = proj, len(proj)
        return best

    def _links_for(self, project: str) -> List[str]:
        if not project:
            return []
        out = []
        for path in self.all_notes():
            if path.parent == self.mem_dir:
                continue
            fm, _ = self._read_note(path)
            if str(fm.get("project", "")).strip().lower() == project.lower():
                out.append(f"[[{path.stem}]]")
        return out[:6]

    def write_moc(self) -> Optional[Path]:
        """Regenerate AI Memory/_AI Memory MOC.md -- an index Obsidian can browse."""
        if not self.available:
            return None
        self.ensure_memory_dir()
        path = self.mem_dir / "_AI Memory MOC.md"
        if path.exists():
            fm, _ = self._read_note(path)
            if fm.get(MARKER_KEY) is not True:
                return None
        buckets: Dict[str, List[str]] = {c: [] for c in MEMORY_CATEGORIES}
        for note in self.memory_notes():
            fm, body = self._read_note(note)
            if fm.get("type") != "memory":
                continue
            cat = str(fm.get("category", "facts")).lower()
            buckets.setdefault(cat, []).append(f"- [[{note.stem}]] - {self._body_fact(body)}")
        head = dump_front_matter({
            "title": "AI Memory MOC",
            "type": "moc",
            "project": "NeuralDock",
            MARKER_KEY: True,
            "updated": datetime.date.today().isoformat(),
            "tags": ["ai-memory", "moc"],
        })
        out = [head, "", "# AI Memory", "",
               "Auto-generated by NeuralDock. Notes here are ND-authored;",
               "everything outside this folder is read-only to ND.", ""]
        for cat in MEMORY_CATEGORIES:
            rows = buckets.get(cat) or []
            if not rows:
                continue
            out += [f"## {cat.title()}", ""] + sorted(rows) + [""]
        try:
            path.write_text("\n".join(out), encoding="utf-8")
        except OSError:
            return None
        self._cache.pop(path, None)
        return path

    # -- context assembly (decision 2) -------------------------------------

    def index_lines(self) -> List[str]:
        """One line per non-memory note: the vault's shape, always injected."""
        rows = []
        for path in self.all_notes():
            if self.mem_dir and path.parent == self.mem_dir:
                continue
            fm, body = self._read_note(path)
            title = str(fm.get("title") or path.stem)
            typ = str(fm.get("type") or "note")
            proj = str(fm.get("project") or "")
            tags = fm.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
            bits = [f"[[{path.stem}]]"]
            if title and title != path.stem:
                bits.append(title)
            meta = [b for b in (typ, proj) if b]
            if meta:
                bits.append("(" + ", ".join(meta) + ")")
            if tags:
                bits.append("#" + " #".join(str(t) for t in tags[:5]))
            rows.append("- " + " ".join(bits))
        return rows

    def _score(self, path: Path, query_tokens: set) -> float:
        fm, body = self._read_note(path)
        if not query_tokens:
            return 0.0
        title_tok = _tokens(str(fm.get("title") or path.stem))
        proj_tok = _tokens(str(fm.get("project") or ""))
        tags = fm.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        tag_tok = _tokens(" ".join(str(t) for t in tags))
        body_tok = _tokens(body[:4000])
        score = 0.0
        score += 4.0 * len(query_tokens & title_tok)
        score += 3.0 * len(query_tokens & proj_tok)
        score += 2.0 * len(query_tokens & tag_tok)
        score += 1.0 * len(query_tokens & body_tok)
        return score

    # Hybrid retrieval lives in nd_memory_index.py. It is imported lazily and
    # optionally: if that module or its embedding backend is missing, this class
    # still works on its own with whole-note keyword scoring.
    _index = None
    _index_tried = False

    def index(self):
        """The hybrid BM25 + embedding index, or None if unavailable."""
        if self._index_tried:
            return self._index
        self._index_tried = True
        if not self.config.get("memory_hybrid_search", True):
            return None
        try:
            from nd_memory_index import MemoryIndex
            self._index = MemoryIndex(self)
        except Exception as exc:
            self.last_error = f"hybrid index unavailable: {exc}"
        return self._index

    def context_for(self, user_text: str = "", budget: Optional[int] = None) -> str:
        """The string to append to the system prompt. Never raises."""
        idx = self.index()
        if idx is not None:
            try:
                out = idx.context_for(user_text, budget)
                if out:
                    return out
            except Exception as exc:
                self.last_error = f"hybrid context failed: {exc}"
        try:
            return self._context_for(user_text, budget)
        except Exception as exc:            # memory must never break chat
            self.last_error = f"context build failed: {exc}"
            return ""

    def search(self, query: str, k: int = 8):
        """Ranked chunks for a query. Empty list if the index is unavailable."""
        idx = self.index()
        if idx is None:
            return []
        try:
            return idx.search(query, k=k)
        except Exception as exc:
            self.last_error = f"search failed: {exc}"
            return []

    def _context_for(self, user_text: str, budget: Optional[int]) -> str:
        budget = int(budget or self.budget)
        if not self.available:
            mem = self._load_json_fallback({c: [] for c in MEMORY_CATEGORIES})
            return self._render_atomic(mem)

        parts: List[str] = []
        used = 0

        # Tier 1 -- atomic memory, always in full
        mem = self.load_memory()
        atomic = self._render_atomic(mem)
        if atomic:
            parts.append(atomic)
            used += len(atomic)

        # Tier 2 -- vault index, always
        rows = self.index_lines()
        if rows:
            block = ("## Obsidian vault index (all notes available)\n"
                     + "\n".join(rows))
            parts.append(block)
            used += len(block)

        # Tier 3 -- full bodies, most relevant first, until the budget runs out
        qt = _tokens(user_text)
        candidates = [p for p in self.all_notes()
                      if not (self.mem_dir and p.parent == self.mem_dir)]
        scored = sorted(((self._score(p, qt), p) for p in candidates),
                        key=lambda x: (-x[0], str(x[1])))
        bodies: List[str] = []
        for score, path in scored:
            if used >= budget:
                break
            fm, body = self._read_note(path)
            if not body.strip():
                continue
            if qt and score <= 0:
                continue
            chunk = f"### {path.stem}\n{body.strip()}"
            room = budget - used
            if len(chunk) > room:
                if room < 400:
                    break
                chunk = chunk[:room - 20].rstrip() + "\n...(truncated)"
            bodies.append(chunk)
            used += len(chunk)
        if bodies:
            parts.append("## Relevant vault notes (verbatim)\n\n"
                         + "\n\n".join(bodies))

        if not parts:
            return ""
        header = ("# Shared memory (Obsidian vault: "
                  f"{self.vault.name})\n"
                  "Treat these as established facts about the user and their "
                  "projects. You may write new memories only via the memory "
                  "tool; never claim to have edited vault notes yourself.")
        return header + "\n\n" + "\n\n".join(parts)

    @staticmethod
    def _render_atomic(mem: dict) -> str:
        rows = []
        for cat in MEMORY_CATEGORIES:
            vals = [v for v in (mem.get(cat) or []) if str(v).strip()]
            if not vals:
                continue
            rows.append(f"### {cat}")
            rows += [f"- {v}" for v in vals]
        if not rows:
            return ""
        return "## Known facts\n" + "\n".join(rows)

    # -- housekeeping ------------------------------------------------------

    def migrate_json(self) -> dict:
        """Move any pre-existing JSON memory into notes. Safe to run repeatedly."""
        if not self.available:
            return {"migrated": 0, "reason": "vault unavailable"}
        mem = self._load_json_fallback({c: [] for c in MEMORY_CATEGORIES})
        count = 0
        for cat in MEMORY_CATEGORIES:
            for fact in (mem.get(cat) or []):
                if self.write_fact(fact, cat, source="migrated-json"):
                    count += 1
        if count:
            self.write_moc()
        return {"migrated": count}

    def validate(self) -> List[str]:
        """Report front-matter problems. Read-only -- never edits anything."""
        problems = []
        for path in self.all_notes():
            fm, _ = self._read_note(path)
            if fm.get(MARKER_KEY) is True:
                continue                      # ND's own notes use slug titles
            if not fm:
                problems.append(f"{path.name}: no front matter")
                continue
            title = str(fm.get("title") or "")
            if title and title.lower() != path.stem.lower():
                problems.append(
                    f"{path.name}: front-matter title '{title}' does not match filename")
            proj = str(fm.get("project") or "")
            # only meaningful for the "<Project> - <Facet>.md" convention
            if proj and " - " in path.stem:
                prefix = path.stem.split(" - ", 1)[0]
                if prefix.lower() != proj.lower():
                    problems.append(
                        f"{path.name}: project '{proj}' does not match filename prefix "
                        f"'{prefix}' -- likely a copy-paste slip in the front matter")
        return problems

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "root": str(self.root),
            "vault": str(self.vault) if self.vault else None,
            "memory_folder": str(self.mem_dir) if self.mem_dir else None,
            "available": self.available,
            "notes_total": len(self.all_notes()),
            "notes_memory": len(self.memory_notes()),
            "budget_chars": self.budget,
            "last_error": self.last_error,
        }


# ---------------------------------------------------------------------------
# drop-in replacements for the launcher's three functions
# ---------------------------------------------------------------------------

def install_shims(obs: "ObsidianMemory"):
    """Return (load_memory, save_memory, memory_to_prompt) bound to `obs`."""

    def load_memory() -> dict:
        return obs.load_memory()

    def save_memory(mem: dict):
        return obs.save_memory(mem)

    def memory_to_prompt(mem: dict, max_chars: int = 2000) -> str:
        # signature preserved; `mem` is ignored because the vault is the truth
        return obs.context_for("", budget=max(max_chars, obs.budget))

    return load_memory, save_memory, memory_to_prompt


# ---------------------------------------------------------------------------
# CLI -- python nd_obsidian_memory.py [status|validate|migrate|moc|test]
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Windows consoles default to cp1252 and will crash on box-drawing or
    # em-dash characters that appear inside vault notes. Never let a print
    # kill a diagnostic run.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = {}
    for cand in (Path(os.environ.get("APPDATA", "")) / "NeuralDock" / "neuraldock_config.json",
                 Path.home() / ".neuraldock" / "neuraldock_config.json",
                 Path("neuraldock_config.json")):
        try:
            if cand.is_file():
                cfg = json.loads(cand.read_text(encoding="utf-8"))
                break
        except Exception:
            pass

    obs = ObsidianMemory(cfg, Path(cfg.get("config_dir", ".")))
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()

    if cmd == "status":
        print(json.dumps(obs.status(), indent=2))
    elif cmd == "validate":
        issues = obs.validate()
        print("\n".join(issues) if issues else "No front-matter problems found.")
    elif cmd == "migrate":
        print(json.dumps(obs.migrate_json(), indent=2))
    elif cmd == "moc":
        print(obs.write_moc())
    elif cmd == "test":
        q = " ".join(sys.argv[2:]) or "neuraldock comfyui vram"
        out = obs.context_for(q)
        print(out)
        print(f"\n--- {len(out)} chars (~{len(out)//4} tokens) ---")
    else:
        print(__doc__)
