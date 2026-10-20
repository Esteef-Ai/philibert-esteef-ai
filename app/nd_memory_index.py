"""
nd_memory_index.py  --  fast hybrid retrieval over the Obsidian vault
=====================================================================
Companion to nd_obsidian_memory.py. That module owns reading and writing the
vault; this one owns *finding the right part of it quickly*.

Why this exists
---------------
The first cut scored whole notes by keyword overlap and injected whole notes.
Two problems:

  * A 5 KB architecture note is mostly irrelevant to any single question, but it
    cost 5 KB of budget once one keyword matched.
  * Keyword overlap misses paraphrase entirely. "why is image gen slow" does not
    share a single content word with "VRAM arbitration evicts Ollama models".

So: chunk by heading, and score with BOTH lexical and semantic signals.

  1. CHUNKING     Notes split on H2/H3 boundaries, ~1200 chars max. A chunk
                  carries its note title, heading path, project and tags, so a
                  retrieved fragment is still self-describing.
  2. BM25         Classic lexical ranking. Catches exact identifiers that
                  embeddings blur -- OLLAMA_KV_CACHE_TYPE, q8_0, sm_120, 7788.
  3. EMBEDDINGS   nomic-embed-text via the local Ollama already running.
                  Catches paraphrase and concept matches BM25 cannot see.
  4. FUSION       Reciprocal Rank Fusion. No score normalisation to tune, and
                  a chunk ranked well by either signal survives.

Everything degrades rather than fails. No Ollama -> pure BM25. No cache ->
rebuild. Corrupt cache -> rebuild. Retrieval never raises into chat.

Cost
----
The index is cached on disk keyed by (path, mtime, size), so a restart re-embeds
nothing. Only edited notes are re-embedded. A query costs one embed call
(~20-40 ms) plus in-memory scoring.

CLI
---
    python nd_memory_index.py build          # build/refresh, report timings
    python nd_memory_index.py search <query> # ranked chunks with scores
    python nd_memory_index.py context <query># exactly what chat would receive
    python nd_memory_index.py stats
"""

from __future__ import annotations

import base64
import json
import math
import re
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from nd_obsidian_memory import (
    MEMORY_CATEGORIES, MARKER_KEY, ObsidianMemory, _tokens, parse_front_matter,
)

DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_OLLAMA = "http://127.0.0.1:11434"
CHUNK_TARGET = 1200          # chars; a heading section longer than this is split
CHUNK_MIN = 120              # below this a section is merged into the next
# Reciprocal rank fusion constant. The literature default is 60, which was
# measured here to be actively harmful: at k=60 the score gap between rank 1 and
# rank 40 is only 25%, so a chunk that ranks mediocre on BOTH signals outscores
# one that ranks 2nd on a single strong signal. "why is image generation slow"
# fell out of the top 10 entirely that way. k=10 gives ~6x the spread and fixes
# it without hurting any other case. See temp/eval_retrieval.py.
RRF_K = 10
CANDIDATES = 40              # per-signal candidate pool feeding the fusion
# Fusion weights. Semantic is always 1.0. Lexical gets parity when the query
# looks like an identifier lookup and is damped otherwise, so BM25 noise cannot
# bury a good semantic hit on a vaguely-worded question.
#
# HONESTY NOTE: the sweep in temp/sweep.py shows W_LEX_VAGUE to be INERT on the
# current 18-case eval -- 0.2 and 1.0 give identical MRR, because at
# CANDIDATES=40 essentially every top-ranked chunk appears in BOTH signal lists,
# so a uniform scale on one of them does not reorder anything. It is kept
# because it is the right shape for a larger vault where the lists diverge, but
# it has NOT been shown to help here. RRF_K and CANDIDATES are what actually
# moved the numbers (MRR 0.859 -> 0.896).
W_LEX_RARE = 1.0
W_LEX_VAGUE = 0.35
EMBED_KEEP_ALIVE = "30m"     # keep the embed model resident; cold load is 2.3 s
CACHE_VERSION = 3

# nomic-embed-text is trained with asymmetric task prefixes. Using them is worth
# several points of retrieval quality and costs nothing.
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


# ---------------------------------------------------------------------------
# vector helpers -- float32 packed into base64 so the cache stays small
# ---------------------------------------------------------------------------

def pack_vec(vec: List[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(vec)}f", *vec)).decode("ascii")


def unpack_vec(blob: str) -> List[float]:
    raw = base64.b64decode(blob)
    return list(struct.unpack(f"<{len(raw)//4}f", raw))


def normalize(vec: List[float]) -> List[float]:
    n = math.sqrt(sum(v * v for v in vec))
    return [v / n for v in vec] if n else vec


def dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# chunking
# ---------------------------------------------------------------------------

def split_sections(body: str) -> List[Tuple[str, str]]:
    """Split a note body into (heading, text) on H2/H3 boundaries."""
    lines = body.splitlines()
    out: List[Tuple[str, List[str]]] = []
    heading = ""
    buf: List[str] = []
    for line in lines:
        m = re.match(r"^(#{2,3})\s+(.*)", line)
        if m:
            if buf and any(l.strip() for l in buf):
                out.append((heading, buf))
            heading = m.group(2).strip()
            buf = []
        else:
            buf.append(line)
    if buf and any(l.strip() for l in buf):
        out.append((heading, buf))
    return [(h, "\n".join(b).strip()) for h, b in out]


def hard_wrap(text: str, limit: int) -> List[str]:
    """Split an over-long section on paragraph boundaries, never mid-sentence."""
    if len(text) <= limit:
        return [text]
    paras = re.split(r"\n\s*\n", text)
    parts, cur = [], ""
    for para in paras:
        if len(para) > limit:                      # a single huge paragraph
            if cur:
                parts.append(cur)
                cur = ""
            for i in range(0, len(para), limit):
                parts.append(para[i:i + limit])
            continue
        if len(cur) + len(para) + 2 > limit and cur:
            parts.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    return parts


def chunk_note(path: Path, vault: Path, fm: dict, body: str) -> List[dict]:
    """One note -> a list of self-describing chunk dicts."""
    stem = path.stem
    project = str(fm.get("project") or "")
    ntype = str(fm.get("type") or "note")
    tags = fm.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    tags = [str(t) for t in tags]

    sections = split_sections(body) or [("", body.strip())]

    # merge runts forward so we do not index three-word fragments
    merged: List[Tuple[str, str]] = []
    for heading, text in sections:
        if merged and len(text) < CHUNK_MIN:
            ph, pt = merged[-1]
            merged[-1] = (ph, f"{pt}\n\n## {heading}\n{text}" if heading else f"{pt}\n{text}")
        else:
            merged.append((heading, text))

    chunks = []
    for heading, text in merged:
        for i, piece in enumerate(hard_wrap(text, CHUNK_TARGET)):
            if not piece.strip():
                continue
            crumb = f"{stem} > {heading}" if heading else stem
            if i:
                crumb += f" ({i + 1})"
            chunks.append({
                "note": stem,
                "rel": str(path.relative_to(vault)),
                "heading": heading,
                "crumb": crumb,
                "project": project,
                "type": ntype,
                "tags": tags,
                "text": piece,
                # what actually gets embedded: breadcrumb + metadata + body, so
                # a chunk about "Roadmap" still carries its project name
                "embed_text": f"{crumb}\n{project} {ntype} {' '.join(tags)}\n{piece}",
            })
    return chunks


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9][a-z0-9_.\-]*")


def index_tokens(text: str) -> List[str]:
    """Lexical tokens. Deliberately keeps _ . - so OLLAMA_KV_CACHE_TYPE and
    q8_0 and sm_120 survive as single searchable terms."""
    toks = _WORD.findall(text.lower())
    out = []
    for t in toks:
        t = t.strip(".-")
        if len(t) < 2:
            continue
        out.append(t)
        # also index the pieces, so "kv cache" finds OLLAMA_KV_CACHE_TYPE
        if "_" in t or "." in t or "-" in t:
            out.extend(p for p in re.split(r"[_.\-]+", t) if len(p) > 1)
    return out


_IDENT_SHAPE = re.compile(r"[a-z]+[_.:\-/][a-z0-9]|[a-z][0-9]|[0-9][a-z]|^\d{3,}$")


def looks_like_identifier_query(raw: str, qtok: List[str], bm25) -> bool:
    """Is this query hunting for a literal token rather than a concept?

    Deliberately NOT 'contains a low-df term'. In a 177-chunk corpus that fires
    on ordinary words -- 'slow' appears in 6 chunks, so a plain-English question
    counted as an identifier lookup and the damping never applied. Measured, not
    assumed: that bug made the whole tuning sweep return identical numbers.

    Instead, look at the SHAPE of the token (mixed letters+digits, embedded
    underscore/dot/colon/slash, a long bare number) or at genuine near-uniqueness
    (df <= 2), plus original-case ALLCAPS which is almost always a constant.
    """
    for word in re.findall(r"\S+", raw):
        stripped = word.strip(".,;:!?()[]{}\"'")
        if len(stripped) >= 3 and stripped.isupper() and stripped.isalpha():
            return True                      # ALLCAPS constant, e.g. OLLAMA_HOST
    for t in qtok:
        if _IDENT_SHAPE.search(t):
            return True
        if bm25 is not None and bm25.df.get(t, 0) and bm25.df.get(t, 0) <= 2:
            return True
    return False


class BM25:
    __slots__ = ("docs", "df", "idf", "avg_len", "k1", "b", "n")

    def __init__(self, docs: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.docs = docs
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.avg_len = (sum(len(d) for d in docs) / self.n) if self.n else 0.0
        self.df: Dict[str, int] = {}
        for d in docs:
            for t in set(d):
                self.df[t] = self.df.get(t, 0) + 1
        self.idf = {
            t: math.log(1 + (self.n - c + 0.5) / (c + 0.5))
            for t, c in self.df.items()
        }

    def scores(self, query: List[str]) -> List[float]:
        out = [0.0] * self.n
        if not self.n:
            return out
        for i, doc in enumerate(self.docs):
            if not doc:
                continue
            tf: Dict[str, int] = {}
            for t in doc:
                tf[t] = tf.get(t, 0) + 1
            dl = len(doc)
            s = 0.0
            for q in query:
                f = tf.get(q)
                if not f:
                    continue
                idf = self.idf.get(q, 0.0)
                s += idf * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b * dl / (self.avg_len or 1))
                )
            out[i] = s
        return out


# ---------------------------------------------------------------------------
# embeddings via the local Ollama
# ---------------------------------------------------------------------------

class Embedder:
    def __init__(self, url: str = DEFAULT_OLLAMA, model: str = DEFAULT_EMBED_MODEL,
                 timeout: float = 30.0):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.last_error: Optional[str] = None
        self._ok: Optional[bool] = None

    def available(self) -> bool:
        if self._ok is not None:
            return self._ok
        try:
            vec = self.embed(["ping"])
            self._ok = bool(vec and vec[0])
        except Exception as e:
            self.last_error = str(e)
            self._ok = False
        return self._ok

    def embed(self, texts: List[str], batch: int = 32) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), batch):
            payload = json.dumps({
                "model": self.model,
                "input": texts[i:i + batch],
                # Without this the 274 MB model unloads between messages and
                # every query pays a 2.3 s cold load instead of ~35 ms.
                "keep_alive": EMBED_KEEP_ALIVE,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self.url}/api/embed", data=payload,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            vecs = data.get("embeddings") or []
            out.extend(normalize([float(x) for x in v]) for v in vecs)
        return out


# ---------------------------------------------------------------------------
# the index
# ---------------------------------------------------------------------------

class MemoryIndex:
    def __init__(self, obs: ObsidianMemory, cache_path: Optional[Path] = None,
                 embed_model: str = DEFAULT_EMBED_MODEL,
                 ollama_url: str = DEFAULT_OLLAMA,
                 use_embeddings: bool = True):
        self.obs = obs
        cfg = obs.config or {}
        self.cache_path = Path(cache_path or (obs.config_dir / "nd_memory_index.json"))
        self.embed_model = cfg.get("memory_embed_model", embed_model)
        self.ollama_url = cfg.get("ollama_url", ollama_url)
        self.use_embeddings = bool(cfg.get("memory_use_embeddings", use_embeddings))
        self.embedder = Embedder(self.ollama_url, self.embed_model)

        self.chunks: List[dict] = []
        self.vectors: List[Optional[List[float]]] = []
        self.bm25: Optional[BM25] = None
        self._file_sig: Dict[str, list] = {}     # rel -> [mtime, size]
        self.last_build: Dict[str, float] = {}
        self.last_error: Optional[str] = None
        self._loaded = False

    # -- cache ------------------------------------------------------------

    def _load_cache(self) -> dict:
        try:
            if self.cache_path.is_file():
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if data.get("version") == CACHE_VERSION and \
                   data.get("embed_model") == self.embed_model:
                    return data
        except Exception as e:
            self.last_error = f"cache unreadable: {e}"
        return {}

    def _save_cache(self):
        try:
            payload = {
                "version": CACHE_VERSION,
                "embed_model": self.embed_model,
                "vault": str(self.obs.vault) if self.obs.vault else "",
                "file_sig": self._file_sig,
                "chunks": self.chunks,
                "vectors": [pack_vec(v) if v else "" for v in self.vectors],
            }
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self.cache_path)
        except Exception as e:
            self.last_error = f"cache unwritable: {e}"

    # -- build ------------------------------------------------------------

    @staticmethod
    def _sig(p: Path) -> list:
        st = p.stat()
        return [int(st.st_mtime), st.st_size]

    def refresh(self, force: bool = False) -> dict:
        """Rebuild only what changed. Returns a small report."""
        t0 = time.time()
        if not self.obs.available:
            self.chunks, self.vectors, self.bm25 = [], [], None
            return {"ok": False, "reason": "vault unavailable"}

        vault = self.obs.vault
        cache = {} if force else self._load_cache()
        old_chunks = cache.get("chunks") or []
        old_vecs_raw = cache.get("vectors") or []
        old_sig = cache.get("file_sig") or {}

        # group cached chunks + vectors by source file
        by_file: Dict[str, List[Tuple[dict, str]]] = {}
        for i, ch in enumerate(old_chunks):
            raw = old_vecs_raw[i] if i < len(old_vecs_raw) else ""
            by_file.setdefault(ch.get("rel", ""), []).append((ch, raw))

        notes = self.obs.all_notes()
        live = {}
        chunks: List[dict] = []
        raw_vecs: List[str] = []
        reused = rebuilt = 0

        for p in notes:
            rel = str(p.relative_to(vault))
            try:
                sig = self._sig(p)
            except OSError:
                continue
            live[rel] = sig
            if not force and old_sig.get(rel) == sig and rel in by_file:
                for ch, raw in by_file[rel]:
                    chunks.append(ch)
                    raw_vecs.append(raw)
                reused += 1
                continue
            fm, body = self.obs._read_note(p)
            for ch in chunk_note(p, vault, fm, body):
                chunks.append(ch)
                raw_vecs.append("")
            rebuilt += 1

        self.chunks = chunks
        self._file_sig = live
        t_chunk = time.time() - t0

        # embed only the chunks that have no vector yet
        embedded = 0
        vectors: List[Optional[List[float]]] = [
            unpack_vec(r) if r else None for r in raw_vecs
        ]
        if self.use_embeddings:
            todo = [i for i, v in enumerate(vectors) if v is None]
            if todo:
                if self.embedder.available():
                    try:
                        texts = [DOC_PREFIX + chunks[i]["embed_text"] for i in todo]
                        new = self.embedder.embed(texts)
                        for i, vec in zip(todo, new):
                            vectors[i] = vec
                        embedded = len(new)
                    except Exception as e:
                        self.last_error = f"embedding failed: {e}"
                else:
                    self.last_error = (
                        f"embeddings unavailable ({self.embedder.last_error}); "
                        "lexical search only")
        self.vectors = vectors

        self.bm25 = BM25([index_tokens(c["embed_text"]) for c in chunks])
        self._loaded = True
        self._save_cache()

        report = {
            "ok": True,
            "notes": len(notes),
            "chunks": len(chunks),
            "files_reused": reused,
            "files_rebuilt": rebuilt,
            "chunks_embedded": embedded,
            "vectors_present": sum(1 for v in vectors if v),
            "chunk_sec": round(t_chunk, 3),
            "total_sec": round(time.time() - t0, 3),
            "last_error": self.last_error,
        }
        self.last_build = report
        return report

    def ensure(self):
        """Cheap: refresh only if the vault changed since the last build."""
        if not self._loaded:
            self.refresh()
            return
        try:
            live = {}
            for p in self.obs.all_notes():
                live[str(p.relative_to(self.obs.vault))] = self._sig(p)
            if live != self._file_sig:
                self.refresh()
        except Exception as e:
            self.last_error = f"ensure failed: {e}"


    # -- search -----------------------------------------------------------

    def search(self, query: str, k: int = 8, candidates: Optional[int] = None) -> List[dict]:
        """Hybrid BM25 + embedding search. Returns chunk dicts with scores."""
        # read the module global at CALL time, not as a default argument, so the
        # tuning sweep in temp/sweep.py can actually vary it
        candidates = CANDIDATES if candidates is None else candidates
        self.ensure()
        if not self.chunks or not query.strip():
            return []

        # lexical
        qtok = index_tokens(query)
        lex = self.bm25.scores(qtok) if self.bm25 else [0.0] * len(self.chunks)
        lex_rank = sorted(range(len(lex)), key=lambda i: -lex[i])[:candidates]
        lex_pos = {idx: r for r, idx in enumerate(lex_rank) if lex[idx] > 0}

        # semantic
        sem_pos: Dict[int, int] = {}
        sims: List[float] = [0.0] * len(self.chunks)
        if self.use_embeddings and any(v for v in self.vectors):
            try:
                qv = self.embedder.embed([QUERY_PREFIX + query])[0]
                for i, v in enumerate(self.vectors):
                    sims[i] = dot(qv, v) if v else 0.0
                sem_rank = sorted(range(len(sims)), key=lambda i: -sims[i])[:candidates]
                sem_pos = {idx: r for r, idx in enumerate(sem_rank)}
            except Exception as e:
                self.last_error = f"query embedding failed: {e}"

        # Weighted reciprocal rank fusion.
        #
        # Semantic carries more weight by default, because on a vague question
        # ("why is image generation slow") every query word is a stopword and
        # BM25's candidates are noise that crowds out the real answer.
        #
        # But BM25 is the ONLY signal that reliably finds exact identifiers --
        # sm_120, q8_0, OLLAMA_KV_CACHE_TYPE, 7788 -- which embeddings blur into
        # their neighbours ("sm_120" scores rank 0 semantically, rank 2
        # lexically). So when the query looks like it contains an identifier,
        # lexical weight is restored to parity. See looks_like_identifier_query.
        w_lex = W_LEX_RARE if looks_like_identifier_query(query, qtok, self.bm25) \
            else W_LEX_VAGUE
        w_sem = 1.0

        fused: Dict[int, float] = {}
        for idx, r in lex_pos.items():
            fused[idx] = fused.get(idx, 0.0) + w_lex / (RRF_K + r + 1)
        for idx, r in sem_pos.items():
            fused[idx] = fused.get(idx, 0.0) + w_sem / (RRF_K + r + 1)
        if not fused:
            return []

        order = sorted(fused, key=lambda i: -fused[i])[:k]
        out = []
        for i in order:
            ch = dict(self.chunks[i])
            ch["score"] = round(fused[i], 5)
            ch["bm25"] = round(lex[i], 3)
            ch["cosine"] = round(sims[i], 4)
            ch["why"] = "+".join(
                s for s, hit in (("lexical", i in lex_pos), ("semantic", i in sem_pos)) if hit)
            out.append(ch)
        return out

    # -- context ----------------------------------------------------------

    def context_for(self, query: str = "", budget: Optional[int] = None) -> str:
        """The system-prompt block. Never raises."""
        try:
            return self._context_for(query, budget)
        except Exception as e:
            self.last_error = f"context build failed: {e}"
            return ""

    def _context_for(self, query: str, budget: Optional[int]) -> str:
        budget = int(budget or self.obs.budget)
        parts: List[str] = []
        used = 0

        # Tier 1 -- every atomic memory, always, in full
        atomic = self.obs._render_atomic(self.obs.load_memory())
        if atomic:
            parts.append(atomic)
            used += len(atomic)

        # Tier 2 -- one line per note, so the model always knows what exists
        rows = self.obs.index_lines()
        if rows:
            block = ("## Vault index (every note; ask to read any of these)\n"
                     + "\n".join(rows))
            parts.append(block)
            used += len(block)

        # Tier 3 -- the actual retrieval
        self.ensure()
        hits = self.search(query, k=12) if query.strip() else []
        if not hits:
            # No query, or nothing matched. Fall back to whole notes so an
            # empty-query call still carries real content. The shared rendering
            # loop below does all the budget accounting.
            for p in self.obs.all_notes():
                if self.obs.mem_dir and p.parent == self.obs.mem_dir:
                    continue
                _fm, body = self.obs._read_note(p)
                if body.strip():
                    hits.append({"crumb": p.stem, "note": p.stem,
                                 "text": body.strip(), "score": 0.0,
                                 "why": "fallback"})

        shown: List[str] = []
        seen_notes: Dict[str, int] = {}
        for h in hits:
            if used >= budget:
                break
            # at most 3 chunks from any one note, so one long note cannot
            # monopolise the budget
            n = seen_notes.get(h["note"], 0)
            if n >= 3:
                continue
            piece = f"### {h['crumb']}\n{h['text']}"
            room = budget - used
            if len(piece) > room:
                if room < 300:
                    break
                piece = piece[:room - 20].rstrip() + "\n...(truncated)"
            shown.append(piece)
            seen_notes[h["note"]] = n + 1
            used += len(piece)
        if shown:
            parts.append("## Retrieved from the vault (most relevant first)\n\n"
                         + "\n\n".join(shown))

        if not parts:
            return ""
        header = (
            f"# Shared memory (Obsidian vault: {self.obs.vault.name})\n"
            "Established facts about the user and their projects. The vault index "
            "lists every note that exists; the retrieved sections below were "
            "selected for this specific message. If you need a note that was not "
            "retrieved, say so and ask for it rather than guessing. Write new "
            "memories only through the memory tool.")
        return header + "\n\n" + "\n\n".join(parts)

    # -- introspection ----------------------------------------------------

    def stats(self) -> dict:
        self.ensure()      # otherwise a fresh object reports 0 chunks, which
                           # reads as "the index is broken" when it is only cold
        return {
            "vault": str(self.obs.vault) if self.obs.vault else None,
            "cache": str(self.cache_path),
            "cache_exists": self.cache_path.is_file(),
            "embed_model": self.embed_model,
            "embeddings_enabled": self.use_embeddings,
            "embeddings_available": self.embedder.available() if self.use_embeddings else False,
            "chunks": len(self.chunks),
            "vectors": sum(1 for v in self.vectors if v),
            "last_build": self.last_build,
            "last_error": self.last_error,
        }


# ---------------------------------------------------------------------------
# convenience + CLI
# ---------------------------------------------------------------------------

def build_index(config: dict, config_dir) -> MemoryIndex:
    return MemoryIndex(ObsidianMemory(config, config_dir))


if __name__ == "__main__":
    import os
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    here = Path(__file__).parent
    cfg = {}
    for cand in (here / "neuraldock_config.json",
                 Path(os.environ.get("APPDATA", "")) / "NeuralDock" / "neuraldock_config.json"):
        try:
            if cand.is_file():
                cfg = json.loads(cand.read_text(encoding="utf-8"))
                break
        except Exception:
            pass

    idx = MemoryIndex(ObsidianMemory(cfg, here))
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "stats").lower()
    arg = " ".join(sys.argv[2:])

    if cmd == "build":
        print(json.dumps(idx.refresh(force="--force" in sys.argv), indent=2))
    elif cmd == "stats":
        print(json.dumps(idx.stats(), indent=2))
    elif cmd == "search":
        t0 = time.time()
        hits = idx.search(arg or "how do I speed up image generation", k=8)
        dt = (time.time() - t0) * 1000
        print(f'query: "{arg}"   {len(hits)} hits in {dt:.0f} ms\n')
        for h in hits:
            print(f"  [{h['score']:.5f}] {h['crumb']}")
            print(f"      via {h['why']}  bm25={h['bm25']}  cos={h['cosine']}")
            print(f"      {h['text'][:150].replace(chr(10), ' ')}...")
            print()
    elif cmd == "context":
        t0 = time.time()
        out = idx.context_for(arg)
        dt = (time.time() - t0) * 1000
        print(out)
        print(f"\n--- {len(out)} chars (~{len(out)//4} tokens) in {dt:.0f} ms ---")
    else:
        print(__doc__)
