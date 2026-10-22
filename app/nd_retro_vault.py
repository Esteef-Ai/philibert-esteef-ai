"""Retro Vault on the drive: the user's own games, played offline.

Ported from the Retro Vault app (retro-vault/server.py) for Philibert's Full
edition. What changed for a drive that travels between computers:

  - games come from <drive>/Entertainment/Cartridges/<system folder> only
  - EmulatorJS and its cores are on the drive (Entertainment/emulator/<ver>),
    fetched once at install - nothing loads from a CDN while playing
  - box art is cached in Entertainment/art; new art is only downloaded while
    Philibert's Internet switch is on
  - save states are files in Entertainment/saves, so a game saved on Windows
    loads on the Mac; so are battery saves (SRAM, the game's own save), in
    saves/sram, each write keeping the one before as .bak
  - game descriptions come from Philibert's own model, not an online service
  - no netplay, phone page, push-to-talk helper, uploads or LAN sharing

Served by the launcher under /retro/ (handle_get / handle_post).
"""
import difflib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import urllib.request
from pathlib import Path

EJS_VERSION = "4.2.3"
EJS_BASE = f"https://cdn.emulatorjs.org/{EJS_VERSION}/data/"
CORES = ["fceumm", "snes9x", "genesis_plus_gx", "mgba", "mupen64plus_next", "gambatte", "mame2003_plus"]
EJS_FILES = (["loader.js", "emulator.min.js", "emulator.min.css",
              "compression/extractzip.js", "compression/extract7z.js"]
             + [f"cores/{c}-wasm.data" for c in CORES]
             + [f"cores/{c}-legacy-wasm.data" for c in CORES]
             + [f"cores/reports/{c}.json" for c in CORES])

# extensions and folder names per system (from Retro Vault, plus the Master System)
SYS_EXTS = {
    "NES": [".nes", ".zip"], "SNES": [".sfc", ".smc", ".zip"], "Genesis": [".bin", ".md", ".gen", ".zip"],
    "SMS": [".sms", ".bin", ".zip"], "GBA": [".gba", ".zip"], "N64": [".z64", ".n64", ".v64", ".zip"],
    "GB": [".gb", ".gbc", ".zip"], "MAME": [".zip"],
}
SYS_FOLDERS = {
    "NES": ["nes", "Nintendo Entertainment System", "Nintendo Entertainment System (NES)",
            "Nintendo - Nintendo Entertainment System", "Famicom"],
    "SNES": ["snes", "Super Nintendo", "Super Nintendo Entertainment System", "Super Nintendo Entertainment System (SNES)",
             "Nintendo - Super Nintendo Entertainment System", "Super Famicom", "Super NES"],
    "Genesis": ["genesis", "megadrive", "Mega Drive", "md", "Sega Genesis", "Sega Mega Drive", "Sega Mega Drive - Genesis",
                "Sega - Mega Drive - Genesis", "Mega Drive & Genesis", "Sega Genesis & Mega Drive"],
    "SMS": ["sms", "Master System", "Sega Master System", "Sega - Master System - Mark III", "Mark III"],
    "GBA": ["gba", "Game Boy Advance", "Nintendo Game Boy Advance", "Nintendo - Game Boy Advance",
            "Gameboy Advance", "GameBoy Advance"],
    "N64": ["n64", "Nintendo 64", "Nintendo64", "Nintendo - Nintendo 64", "N64 (Nintendo 64)"],
    "GB": ["gb", "gbc", "gameboy", "Game Boy", "Nintendo Game Boy", "Nintendo - Game Boy", "Nintendo - Game Boy Color",
           "Game Boy Color", "GameBoy Color", "GB & GBC"],
    "MAME": ["mame", "arcade", "mame2003", "mame2003_plus", "Arcade - MAME", "MAME - Arcade", "FinalBurn", "FBNeo"],
}
KEYWORDS = {
    "NES": [r"nintendo entertainment", r"\bnes\b", r"famicom"],
    "SNES": [r"super nintendo", r"super nes", r"\bsnes\b", r"super famicom"],
    "Genesis": [r"genesis", r"mega drive", r"megadrive"],
    "SMS": [r"master system", r"\bsms\b", r"mark iii"],
    "GBA": [r"game ?boy advance", r"\bgba\b"],
    "N64": [r"nintendo 64", r"\bn64\b"],
    "GB": [r"game ?boy colou?r", r"\bgbc\b", r"game ?boy$", r"\bgb\b"],
    "MAME": [r"\bmame\b", r"arcade", r"finalburn", r"fbneo"],
}
LIBRETRO = {
    "NES": "Nintendo - Nintendo Entertainment System", "SNES": "Nintendo - Super Nintendo Entertainment System",
    "Genesis": "Sega - Mega Drive - Genesis", "SMS": "Sega - Master System - Mark III",
    "GBA": "Nintendo - Game Boy Advance", "N64": "Nintendo - Nintendo 64", "GB": "Nintendo - Game Boy", "MAME": "MAME",
}
_art_lock = threading.Lock()
# libretro-thumbnails: one GitHub repo per system, named with underscores
# ("Nintendo_-_Super_Nintendo_Entertainment_System"). The old links used the
# spaced name and every request was a 404 - art never arrived (2026-10-22).
THUMB_RAW = "https://raw.githubusercontent.com/libretro-thumbnails/"
THUMB_API = "https://api.github.com/repos/libretro-thumbnails/"
ART_DIRS = {"box": "Named_Boxarts", "snap": "Named_Snaps"}
INDEX_DAYS = 30
REGION_PREF = ["(USA)", "(USA, Europe)", "(World)", "(USA, Australia)", "(Japan, USA)", "(Europe)", "(USA, Japan)", "(Japan)"]
UA = {"User-Agent": "Philibert-RetroVault/1.0"}


# Folders are often mixed: a "Master System" folder full of Genesis, 32X and Game Gear
# games (K: has 947 .bin files, 132 of them Master System). Look there too.
ALSO = {"SMS": ["Sega - Mega Drive - Genesis", "Sega - Game Gear", "Sega - 32X"],
        "Genesis": ["Sega - 32X", "Sega - Master System - Mark III"],
        "GB": ["Nintendo - Game Boy Color"]}


def thumb_repo(sys_id):
    return LIBRETRO.get(sys_id, sys_id).replace(" ", "_")


def art_repos(sys_id):
    return [LIBRETRO[sys_id]] + ALSO.get(sys_id, [])


def art_key(name):
    """A ROM file name and a thumbnail name, reduced to what they share: no region or
    dump tags, no 'The', no punctuation. 'Legend of Zelda - A Link to the Past, The.zip'
    and 'Legend of Zelda, The - A Link to the Past (USA)' both become
    'legendofzeldaalinktothepast'."""
    n = re.sub(r"\.(zip|7z|png|nes|sfc|smc|gba|gb|gbc|z64|n64|v64|sms|bin|md|gen)$", "", str(name), flags=re.I)
    n = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", n).lower().replace("&", " and ")
    n = re.sub(r"\bthe\b", " ", n)
    return re.sub(r"[^a-z0-9]+", "", n)
_STATE_KEY = re.compile(r"^[A-Za-z0-9 _\-.]{1,120}$")
_PROFILE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class Vault:
    def __init__(self, ent_dir, online=lambda: False, ask_json=None, log=print):
        self.root = Path(ent_dir)
        self.carts = self.root / "Cartridges"
        self.emu = self.root / "emulator" / EJS_VERSION
        self.art = self.root / "art"
        self.saves = self.root / "saves"
        self.online, self.ask_json, self.log = online, ask_json, log
        self._keys = {}                                     # (system, kind) -> {art_key: [names]}
        self.job = {"state": "idle"}                        # the background art download

    # --- the library -------------------------------------------------------------
    def sys_dir(self, sys_id):
        if not self.carts.is_dir():
            return None
        dirs = [d for d in self.carts.iterdir() if d.is_dir() and not d.name.startswith(".")]
        cands = [c.lower() for c in SYS_FOLDERS.get(sys_id, [sys_id])]
        for d in dirs:
            if d.name.lower() in cands:
                return d
        for d in dirs:
            if any(re.search(k, d.name.lower()) for k in KEYWORDS.get(sys_id, [])):
                return d
        return None

    def list_system(self, sys_id):
        d = self.sys_dir(sys_id)
        if not d:
            return []
        exts = [e for e in SYS_EXTS.get(sys_id, []) if e != ".zip"]
        files = [f.name for f in d.iterdir() if f.is_file() and not f.name.startswith(".")]
        zips = sorted(f for f in files if f.lower().endswith(".zip"))
        roms = sorted(f for f in files if any(f.lower().endswith(e) for e in exts))
        chosen = zips if zips else roms                      # never both: no duplicates
        return [{"name": f, "path": "/retro/roms/" + sys_id + "/" + urllib.parse.quote(f),
                 "isZip": f.lower().endswith(".zip")} for f in chosen]

    def rom_file(self, sys_id, filename):
        d = self.sys_dir(sys_id)
        if not d or not filename or "/" in filename or "\\" in filename or filename.startswith("."):
            return None
        p = d / filename
        if p.is_file():
            return p
        low = filename.lower()
        for e in d.iterdir():
            if e.is_file() and e.name.lower() == low:
                return e
        base = os.path.splitext(low)[0]
        for e in d.iterdir():
            if e.is_file() and os.path.splitext(e.name)[0].lower() == base:
                return e
        return None

    # --- the emulator ------------------------------------------------------------
    def emulator_ready(self):
        return all((self.emu / f).is_file() for f in EJS_FILES if "-legacy-" not in f)

    def emulator_file(self, rel):
        try:
            root = self.emu.resolve()
            p = (root / rel).resolve()
            p.relative_to(root)
        except (ValueError, OSError):
            return None
        return p if p.is_file() else None

    # --- box art -----------------------------------------------------------------
    @staticmethod
    def lt_title(title):
        t = title.replace("&", " and ").replace(":", " -")
        t = re.sub(r"[/|]", "-", t)
        t = re.sub(r'[?*<>"]', "", t)
        return re.sub(r"\s+", " ", t).strip()

    def art_path(self, sys_id, title, art_type="box"):
        if sys_id not in LIBRETRO or art_type not in ("box", "snap"):
            return None
        safe = self.lt_title(title).replace("\\", "-").replace("/", "-").replace(":", "-")
        if not safe or safe.startswith("."):
            return None
        return self.art / sys_id / art_type / (safe + ".png")

    def art_file(self, sys_id, rom, art_type="box"):
        """Art for a ROM file, kept under the ROM's own name: art/<system>/<box|snap>/<rom stem>.png."""
        if sys_id not in LIBRETRO or art_type not in ART_DIRS or not rom:
            return None
        stem = os.path.splitext(os.path.basename(str(rom)))[0]
        safe = re.sub(r'[\\/:*?"<>|]', "-", stem).strip()
        if not safe or safe.startswith("."):
            return None
        return self.art / sys_id / art_type / (safe + ".png")

    def art_index(self, sys_id, art_type="box", repo=None):
        """Every thumbnail name libretro has for a system (no .png), cached on the drive
        for INDEX_DAYS. Two GitHub API calls when it has to be fetched."""
        repo = (repo or LIBRETRO[sys_id]).replace(" ", "_")
        f = self.art / "_index" / f"{repo}-{art_type}.json"
        try:
            if f.is_file() and (time.time() - f.stat().st_mtime < INDEX_DAYS * 86400 or not self.online()):
                return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if not self.online():
            return []
        def get(url):
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read())
        root = get(THUMB_API + repo + "/git/trees/master")
        sha = next(e["sha"] for e in root.get("tree", []) if e.get("path") == ART_DIRS[art_type])
        names = [e["path"][:-4] for e in get(THUMB_API + repo + "/git/trees/" + sha).get("tree", [])
                 if e.get("path", "").lower().endswith(".png")]
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(names), encoding="utf-8")
        self._keys.pop((repo, art_type), None)
        return names

    def _by_key(self, sys_id, art_type, repo):
        k = (repo.replace(" ", "_"), art_type)
        if k not in self._keys:
            by = {}
            for n in self.art_index(sys_id, art_type, repo):
                by.setdefault(art_key(n), []).append(n)
            self._keys[k] = by
        return self._keys[k]

    def match_art(self, sys_id, rom, art_type="box", with_repo=False):
        """The thumbnail for a ROM, or None: the same key in the system's own list, then
        in the lists of systems its folder often mixes in, then the closest key above
        0.88. The scan libretro has for that game - never a made-up cover. Prefers USA,
        then World, Europe..."""
        key = art_key(rom)
        if not key:
            return None
        found = None
        for repo in art_repos(sys_id):
            names = self._by_key(sys_id, art_type, repo).get(key)
            if names:
                found = (repo, names)
                break
        if not found:
            by = self._by_key(sys_id, art_type, art_repos(sys_id)[0])
            close = difflib.get_close_matches(key, by.keys(), n=1, cutoff=0.88)
            if close:
                found = (art_repos(sys_id)[0], by[close[0]])
        if not found:
            return None
        rank = lambda n: min([i for i, r in enumerate(REGION_PREF) if r in n] or [len(REGION_PREF)])
        name = sorted(found[1], key=lambda n: (rank(n), len(n)))[0]
        return (found[0], name) if with_repo else name

    def fetch_art(self, sys_id, title, art_type="box", rom=None):
        """Art for one game: from the drive if it is there, else (online only) the matched
        libretro thumbnail, saved to the drive."""
        p = self.art_file(sys_id, rom, art_type) if rom else self.art_path(sys_id, title, art_type)
        if not p:
            return None, "unknown system"
        if p.is_file():
            return p, ""
        if not self.online():
            return None, "offline"                        # only cached art while the Internet is off
        try:
            m = self.match_art(sys_id, rom or title, art_type, with_repo=True)
        except Exception as e:
            return None, f"no index ({str(e)[:60]})"
        if not m:
            return None, "not found"
        url = (THUMB_RAW + m[0].replace(" ", "_") + "/master/" + ART_DIRS[art_type] + "/"
               + urllib.parse.quote(m[1] + ".png", safe=""))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                data = r.read(4_000_000)
        except Exception:
            return None, "download failed"
        if len(data) > 500 and data[:4] == b"\x89PNG":
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, p)
            return p, ""
        return None, "not found"

    # --- box art for the whole library, in the background ---------------------------
    def art_job_start(self, kinds=("box",)):
        """Download missing art for every game on the drive, on the server: it carries on
        when the window is minimised, hidden or closed. Misses are remembered so the next
        run does not ask again (until the index is refreshed)."""
        with _art_lock:
            if self.job.get("state") == "running":
                return dict(self.job)
            if not self.online():
                return {"state": "offline"}
            self.job = {"state": "running", "total": 0, "done": 0, "got": 0, "missed": 0, "system": "",
                        "started": time.time()}
        threading.Thread(target=self._art_job, args=(tuple(kinds),), daemon=True).start()
        return dict(self.job)

    def _art_job(self, kinds):
        miss_f = self.art / "_index" / "misses.json"
        try:
            misses = set(json.loads(miss_f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            misses = set()
        work = []
        for sys_id in SYS_EXTS:
            if sys_id not in LIBRETRO:
                continue
            for g in self.list_system(sys_id):
                for kind in kinds:
                    p = self.art_file(sys_id, g["name"], kind)
                    tag = f"{sys_id}/{kind}/{g['name']}"
                    if p and not p.is_file() and tag not in misses:
                        work.append((sys_id, g["name"], kind, tag))
        self.job["total"] = len(work)

        def one(w):
            sys_id, rom, kind, tag = w
            self.job["system"] = sys_id
            p, why = self.fetch_art(sys_id, rom, kind, rom=rom)
            with _art_lock:
                self.job["done"] += 1
                if p:
                    self.job["got"] += 1
                else:
                    self.job["missed"] += 1
                    if why == "not found":
                        misses.add(tag)
        try:
            for sys_id in {w[0] for w in work}:          # the indexes first, not one per thread
                for kind in kinds:
                    for repo in art_repos(sys_id):
                        try:
                            self._by_key(sys_id, kind, repo)
                        except Exception as e:
                            self.log(f"Retro Vault: no art index for {repo} ({e})")
            with ThreadPoolExecutor(max_workers=6) as ex:
                list(ex.map(one, work))
            self.job["state"] = "done"
        except Exception as e:
            self.job.update(state="error", error=str(e)[:200])
        finally:
            try:
                miss_f.parent.mkdir(parents=True, exist_ok=True)
                miss_f.write_text(json.dumps(sorted(misses)), encoding="utf-8")
            except OSError:
                pass

    # --- save states (files on the drive) -------------------------------------------
    def state_path(self, key):
        key = urllib.parse.unquote(key or "")
        if not _STATE_KEY.match(key) or ".." in key:
            return None
        return self.saves / "states" / (key + ".state")

    def sram_path(self, key):
        key = urllib.parse.unquote(key or "")
        if not _STATE_KEY.match(key) or ".." in key:
            return None
        return self.saves / "sram" / (key + ".srm")

    def profile_path(self, uid):
        return self.saves / "profiles" / (uid + ".json") if _PROFILE_ID.match(uid or "") else None

    # --- descriptions from Philibert's own model --------------------------------------
    def describe(self, games):
        if not self.ask_json:
            return {"ok": False, "error": "no model"}
        games = [g for g in (games or []) if isinstance(g, dict)][:12]
        prompt = ("You are a retro video game database. Return ONLY a valid JSON array, no markdown, no "
                  "explanation. One object per game in the same order as the input, each with exactly: "
                  '"title" (proper-case display title), "genre" (one of Platformer, RPG, Action, Fighting, '
                  'Racing, Shooter, Sports, Puzzle, Adventure, Strategy, Simulation), "year" (integer or null), '
                  '"description" (1-2 sentences), "emoji" (one emoji).\n\nGames:\n'
                  + "\n".join(f'{i + 1}. "{str(g.get("name", ""))[:120]}" ({str(g.get("system", ""))[:20]})'
                              for i, g in enumerate(games)))
        try:
            text = self.ask_json(prompt) or ""
            text = re.sub(r"```(?:json)?", "", text).strip()
            start, end = text.find("["), text.rfind("]")
            items = json.loads(text[start:end + 1]) if start >= 0 else []
            return {"ok": True, "items": items if isinstance(items, list) else []}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}


def fetch_emulator(dest_root, log=print, files=None):
    """Download EmulatorJS EJS_VERSION and the cores into <Entertainment>/emulator/<ver>.
    Resumes: files already there are skipped. Returns the number downloaded."""
    dest = Path(dest_root) / "emulator" / EJS_VERSION
    n = 0
    for rel in files or EJS_FILES:
        p = dest / rel
        if p.is_file() and p.stat().st_size > 0:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")
        req = urllib.request.Request(EJS_BASE + rel, headers={"User-Agent": "Philibert-Setup/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(tmp, p)
        n += 1
        log(f"emulator: {rel}")
    (dest / "VERSION.txt").write_text(
        f"EmulatorJS {EJS_VERSION} (GPL-3.0, https://github.com/EmulatorJS/EmulatorJS) with libretro cores: "
        + ", ".join(CORES) + ". Downloaded from " + EJS_BASE + "\n", encoding="utf-8")
    return n


# --- HTTP ----------------------------------------------------------------------------
TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".css": "text/css",
         ".json": "application/json", ".wasm": "application/wasm", ".png": "image/png", ".data": "application/octet-stream",
         ".zip": "application/zip"}


def _art_url(sys_id, kind, rom):
    return "/retro/art/" + "/".join(urllib.parse.quote(x, safe="") for x in (sys_id, kind, rom))


def handle_get(v, path, query):
    """-> (status, content_type, bytes_or_Path). path is under /retro/."""
    rel = path[len("/retro/"):] if path.startswith("/retro/") else ""
    if rel == "api/status":
        systems = {s: len(v.list_system(s)) for s in SYS_EXTS}
        return 200, "application/json", json.dumps({
            "ok": True, "emulator": v.emulator_ready(), "version": EJS_VERSION, "online": v.online(),
            "cartridges": str(v.carts), "systems": systems}).encode()
    if rel == "api/roms":
        sys_q = (query.get("system") or ["all"])[0]
        data = {s: v.list_system(s) for s in SYS_EXTS} if sys_q in ("all", "") else v.list_system(sys_q)
        return 200, "application/json", json.dumps(data).encode()
    if rel == "api/get-sys-paths":
        data = {s: {"override": None, "resolved": str(v.sys_dir(s)) if v.sys_dir(s) else None,
                    "count": len(v.list_system(s))} for s in SYS_EXTS}
        return 200, "application/json", json.dumps(data).encode()
    if rel == "api/meta":
        return 200, "application/json", json.dumps({"publisher": "", "developer": "", "year": None, "genre": ""}).encode()
    if rel == "ping":
        return 200, "application/json", json.dumps({"ok": True, "romsDir": str(v.carts),
                                                   "romsDirExists": v.carts.is_dir()}).encode()
    if rel.startswith("roms/"):
        parts = urllib.parse.unquote(rel[5:]).split("/", 1)
        f = v.rom_file(parts[0], parts[1] if len(parts) > 1 else "")
        return (200, TYPES.get(f.suffix.lower(), "application/octet-stream"), f) if f else \
               (404, "text/plain", b"That game is not in Entertainment/Cartridges.")
    if rel == "api/art-job":
        return 200, "application/json", json.dumps(dict(v.job, online=v.online())).encode()
    if rel.startswith("art/"):                          # art/<system>/<box|snap>/<rom file>
        parts = [urllib.parse.unquote(x) for x in rel[4:].split("/", 2)]
        p = v.art_file(parts[0], parts[2], parts[1]) if len(parts) == 3 else None
        return (200, "image/png", p) if p and p.is_file() else (204, "text/plain", b"")
    if rel.startswith("boxart/"):
        parts = [urllib.parse.unquote(x) for x in rel[7:].split("/")]
        p = v.art_path(parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else "box")
        return (200, "image/png", p) if p and p.is_file() else (204, "text/plain", b"")
    if rel.startswith("emulator/"):
        f = v.emulator_file(urllib.parse.unquote(rel[9:]))
        return (200, TYPES.get(f.suffix.lower(), "application/octet-stream"), f) if f else \
               (404, "text/plain", b"Retro Vault's emulator is not on this drive yet.")
    if rel.startswith("state/"):
        p = v.state_path(rel[6:])
        return (200, "application/octet-stream", p) if p and p.is_file() else (404, "text/plain", b"")
    if rel.startswith("sram/"):
        p = v.sram_path(rel[5:])
        return (200, "application/octet-stream", p) if p and p.is_file() else (404, "text/plain", b"")
    if rel.startswith("profile/"):
        p = v.profile_path(urllib.parse.unquote(rel[8:]).strip("/"))
        return (200, "application/json", p) if p and p.is_file() else (404, "application/json", b'{"error":"Not found"}')
    if rel.startswith("no-ptt/"):
        return 404, "text/plain", b""                       # the push-to-talk helper is not part of Philibert
    return None


def handle_post(v, path, raw):
    rel = path[len("/retro/"):] if path.startswith("/retro/") else ""
    if rel == "api/fetch-art":
        try:
            d = json.loads(raw or b"{}")
        except ValueError:
            d = {}
        sys_id, kind, rom = str(d.get("system", "")), str(d.get("type", "box")), str(d.get("file") or "")
        p, why = v.fetch_art(sys_id, str(d.get("title", "")), kind, rom=rom or None)
        if p:
            url = (_art_url(sys_id, kind, rom) if rom else
                   "/retro/boxart/" + urllib.parse.quote(sys_id, safe="") + "/"
                   + urllib.parse.quote(str(d.get("title")), safe="") + "/" + kind)
            return 200, "application/json", json.dumps({"ok": True, "url": url}).encode()
        return 200, "application/json", json.dumps({"ok": False, "why": why}).encode()
    if rel == "api/art-job":
        return 200, "application/json", json.dumps(v.art_job_start()).encode()
    if rel == "api/art-cached":
        # which games already have art on the drive: one request for the whole library,
        # so art shows offline at once (new art is only downloaded while online)
        try:
            games = (json.loads(raw or b"{}").get("games") or [])[:20000]
        except (ValueError, AttributeError):
            games = []
        out = []
        for g in games:
            sys_id, title = str((g or {}).get("system", "")), str((g or {}).get("title", ""))
            rom = str((g or {}).get("file") or "")
            hit = {}
            for kind in ("box", "snap"):
                p = v.art_file(sys_id, rom, kind) if rom else None
                if p and p.is_file():
                    hit[kind] = _art_url(sys_id, kind, rom)
                    continue
                p = v.art_path(sys_id, title, kind)
                if p and p.is_file():
                    hit[kind] = ("/retro/boxart/" + urllib.parse.quote(sys_id, safe="") + "/"
                                 + urllib.parse.quote(title, safe="") + "/" + kind)
            out.append(hit)
        return 200, "application/json", json.dumps({"ok": True, "art": out, "online": v.online()}).encode()
    if rel == "api/describe":
        try:
            d = json.loads(raw or b"{}")
        except ValueError:
            d = {}
        return 200, "application/json", json.dumps(v.describe(d.get("games"))).encode()
    if rel.startswith("state/"):
        p = v.state_path(rel[6:])
        if not p or not raw or len(raw) > 64_000_000:
            return 400, "application/json", b'{"ok":false}'
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".saving")
        tmp.write_bytes(raw)
        os.replace(tmp, p)
        return 200, "application/json", b'{"ok":true}'
    if rel.startswith("sram/"):
        p = v.sram_path(rel[5:])
        if not p or not raw or len(raw) > 4_000_000:
            return 400, "application/json", b'{"ok":false}'
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_file():
            if p.read_bytes() == raw:
                return 200, "application/json", b'{"ok":true}'
            os.replace(p, p.with_name(p.name + ".bak"))     # one step back, if a write ever goes wrong
        tmp = p.with_name(p.name + ".saving")
        tmp.write_bytes(raw)
        os.replace(tmp, p)
        return 200, "application/json", b'{"ok":true}'
    if rel.startswith("profile/"):
        uid = urllib.parse.unquote(rel[8:]).strip("/")
        p = v.profile_path(uid)
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            data = None
        if not p or not isinstance(data, dict) or str(data.get("id", "")) != uid or len(raw) > 500_000:
            return 400, "application/json", b'{"error":"bad profile"}'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return 200, "application/json", json.dumps({"ok": True, "id": uid}).encode()
    return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "--fetch":
        n = fetch_emulator(sys.argv[2], log=lambda m: print(m, flush=True))   # Setup shows each line
        print(n, "files downloaded", flush=True)
