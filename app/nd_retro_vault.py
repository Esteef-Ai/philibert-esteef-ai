"""Retro Vault on the drive: the user's own games, played offline.

Ported from the Retro Vault app (retro-vault/server.py) for Philibert's Full
edition. What changed for a drive that travels between computers:

  - games come from <drive>/Entertainment/Cartridges/<system folder> only
  - EmulatorJS and its cores are on the drive (Entertainment/emulator/<ver>),
    fetched once at install - nothing loads from a CDN while playing
  - box art is cached in Entertainment/art; new art is only downloaded while
    Philibert's Internet switch is on
  - save states are files in Entertainment/saves, so a game saved on Windows
    loads on the Mac
  - game descriptions come from Philibert's own model, not an online service
  - no netplay, phone page, push-to-talk helper, uploads or LAN sharing

Served by the launcher under /retro/ (handle_get / handle_post).
"""
import json
import os
import re
import threading
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

    def fetch_art(self, sys_id, title, art_type="box"):
        p = self.art_path(sys_id, title, art_type)
        if not p:
            return None, "unknown system"
        if p.is_file():
            return p, ""
        if not self.online():
            return None, "offline"                        # only cached art while the Internet is off
        url = ("https://raw.githubusercontent.com/libretro-thumbnails/" + urllib.parse.quote(LIBRETRO[sys_id], safe="")
               + "/master/" + ("Named_Boxarts" if art_type == "box" else "Named_Snaps") + "/"
               + urllib.parse.quote(self.lt_title(title) + ".png", safe=""))
        with _art_lock:
            if p.is_file():
                return p, ""
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Philibert-RetroVault/1.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = r.read(4_000_000)
                if len(data) > 500 and data[:4] == b"\x89PNG":
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(data)
                    return p, ""
            except Exception:
                pass
        return None, "not found"

    # --- save states (files on the drive) -------------------------------------------
    def state_path(self, key):
        key = urllib.parse.unquote(key or "")
        if not _STATE_KEY.match(key) or ".." in key:
            return None
        return self.saves / "states" / (key + ".state")

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
        p, why = v.fetch_art(str(d.get("system", "")), str(d.get("title", "")), str(d.get("type", "box")))
        if p:
            url = ("/retro/boxart/" + urllib.parse.quote(str(d.get("system")), safe="") + "/"
                   + urllib.parse.quote(str(d.get("title")), safe="") + "/" + str(d.get("type", "box")))
            return 200, "application/json", json.dumps({"ok": True, "url": url}).encode()
        return 200, "application/json", json.dumps({"ok": False, "why": why}).encode()
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
