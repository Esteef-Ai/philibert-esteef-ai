"""Yes Chef! - the cooking app: recipes kept by weight, test forks, several batches at once with
their own timers, a cook mode that keeps the screen on, and recipes imported from a link, a PDF,
a Word file, a screenshot or a photo, read ahead for MUST READ / MUST CHECK warnings.

The page (live/static/yeschef.html + live/static/yeschef/) does the reading of recipes (amounts
to grams, timers, warnings). This file keeps the data, fetches and unpacks what is imported, and
asks Philibert's own models:

  <data>/yeschef/db.json        recipes, batches, settings; "rev" goes up on every change so the
                                page notices changes made in another window
  <data>/yeschef/photos/        photos taken during a bake, served at /yeschef/photo/<name>

Importing: a link (needs INTERNET on) is read from the recipe data most sites publish
(schema.org Recipe), else as page text. A PDF with real text is read directly; a scanned PDF or a
picture goes through the text recognition built into Windows (nd_yeschef_ocr.ps1), or, on a Mac,
Philibert's picture-reading model. Word (.docx) is unzipped. Nothing is installed.

Entry point: handle(body, data_dir, online, chat=None, vision=None) -> dict
  chat / vision: (callable(messages) -> str, model name) or None.
"""
import base64
import html as _html
import io
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "live" / "static" / "yeschef" / "sample.json"
OCR_SCRIPT = HERE / "nd_yeschef_ocr.ps1"
COLLS = ("recipes", "batches")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_PHOTO = re.compile(r"^\d{10,14}-[0-9a-f]{8}\.(jpg|png|webp)$")
MAX_ITEM = 2 * 1024 * 1024          # one recipe or batch, as JSON
MAX_FILE = 25 * 1024 * 1024         # an imported file or a photo
_lock = threading.Lock()
# Many recipe sites refuse requests that don't look like a normal browser.
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


# ============================== storage ==============================
def _dir(data_dir):
    d = Path(data_dir) / "yeschef"
    (d / "photos").mkdir(parents=True, exist_ok=True)
    return d


def _db_path(data_dir):
    return _dir(data_dir) / "db.json"


def _fresh():
    db = {"rev": 1, "recipes": {}, "batches": {}, "settings": {}}
    try:
        for r in json.loads(SAMPLE.read_text(encoding="utf-8")):
            r["createdAt"] = int(time.time() * 1000)
            db["recipes"][r["id"]] = r
    except (OSError, ValueError):
        pass
    return db


def load(data_dir):
    p = _db_path(data_dir)
    try:
        db = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(db, dict):
            raise ValueError
    except FileNotFoundError:
        db = _fresh()
        save(data_dir, db)
    except (OSError, ValueError):
        # keep the damaged file aside instead of overwriting someone's recipes
        bad = p.with_name(f"db.damaged-{int(time.time())}.json")
        try:
            p.replace(bad)
        except OSError:
            pass
        db = _fresh()
        save(data_dir, db)
    for k in COLLS:
        db.setdefault(k, {})
    db.setdefault("settings", {})
    db.setdefault("rev", 1)
    return db


def save(data_dir, db):
    p = _db_path(data_dir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def photo_file(data_dir, name):
    """The file for GET /yeschef/photo/<name>, or None."""
    if not _PHOTO.match(name or ""):
        return None
    f = _dir(data_dir) / "photos" / name
    return f if f.is_file() else None


# ============================== the API ==============================
def handle(body, data_dir, online=False, chat=None, vision=None):
    op = str(body.get("op") or "")
    try:
        if op == "state":
            with _lock:
                return {"ok": True, "state": load(data_dir)}
        if op == "rev":
            with _lock:
                return {"ok": True, "rev": load(data_dir)["rev"]}
        if op in ("save", "delete"):
            coll, item = body.get("coll"), body.get("item") or {}
            iid = str(body.get("id") or item.get("id") or "")
            if coll not in COLLS or not _ID.match(iid):
                return {"ok": False, "msg": "Bad item"}
            if op == "save" and (not isinstance(item, dict) or len(json.dumps(item)) > MAX_ITEM):
                return {"ok": False, "msg": "That is too large to save"}
            with _lock:
                db = load(data_dir)
                if op == "save":
                    item["id"] = iid
                    item["updatedAt"] = int(time.time() * 1000)
                    db[coll][iid] = item
                else:
                    db[coll].pop(iid, None)
                db["rev"] += 1
                save(data_dir, db)
                return {"ok": True, "rev": db["rev"]}
        if op == "settings":
            with _lock:
                db = load(data_dir)
                patch = body.get("settings") or {}
                if isinstance(patch, dict):
                    db["settings"].update({k: v for k, v in patch.items() if isinstance(k, str) and len(k) < 40})
                db["rev"] += 1
                save(data_dir, db)
                return {"ok": True, "rev": db["rev"], "settings": db["settings"]}
        if op == "export":
            with _lock:
                return {"ok": True, "db": load(data_dir)}
        if op == "restore":
            new = body.get("db") or {}
            if not isinstance(new, dict) or not isinstance(new.get("recipes"), dict):
                return {"ok": False, "msg": "That is not a Yes Chef! (or Bread Lab) backup."}
            with _lock:
                old = load(data_dir)
                aside = _dir(data_dir) / f"db.before-restore-{int(time.time())}.json"
                aside.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
                new = {"recipes": new.get("recipes") or {}, "batches": new.get("batches") or {},
                       "settings": {}, "rev": old["rev"] + 1}
                save(data_dir, new)
                return {"ok": True, "rev": new["rev"], "recipes": len(new["recipes"]), "batches": len(new["batches"])}
        if op == "photo_add":
            raw, ext = _b64(body.get("data")), {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(str(body.get("type")))
            if not ext:
                return {"ok": False, "msg": "Photos must be JPEG, PNG or WebP"}
            if not raw or len(raw) > MAX_FILE:
                return {"ok": False, "msg": "The photo was empty or too large"}
            name = f"{int(time.time() * 1000)}-{secrets.token_hex(4)}.{ext}"
            (_dir(data_dir) / "photos" / name).write_bytes(raw)
            return {"ok": True, "url": "/yeschef/photo/" + name}
        if op == "ai_status":
            return {"ok": True, "chat": chat[1] if chat else "", "vision": vision[1] if vision else ""}
        if op == "import_url":
            if not online:
                return {"ok": False, "msg": "INTERNET is off. Turn it on (top right in Philibert) to import from a link, "
                                            "or save the page as a PDF and add the file instead."}
            return {"ok": True, **import_url(body.get("url"))}
        if op == "import_file":
            raw = _b64(body.get("data"))
            if not raw:
                return {"ok": False, "msg": "The file was empty."}
            if len(raw) > MAX_FILE:
                return {"ok": False, "msg": "That file is too large (25 MB at most)."}
            return {"ok": True, **import_file(raw, str(body.get("name") or "file"), str(body.get("type") or ""), vision)}
        if op == "ask":
            return ask(body, data_dir, chat)
        if op == "evaluate":
            return evaluate(body, data_dir, vision)
        if op == "structure":
            return structure(body, chat)
        return {"ok": False, "msg": f"Unknown op {op!r}"}
    except ImportError_ as e:
        return {"ok": False, "msg": str(e)}
    except Exception as e:                          # never a traceback on the page
        return {"ok": False, "msg": f"Something went wrong: {type(e).__name__}: {e}"}


class ImportError_(Exception):
    """A problem to show the person as it is (not a crash)."""


def _b64(s):
    try:
        return base64.b64decode(str(s or ""), validate=False)
    except (ValueError, TypeError):
        return b""


# ============================== links ==============================
def import_url(raw):
    url = str(raw or "").strip()
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ImportError_("That does not look like a web address.")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            data = r.read(MAX_FILE + 1)
            final = r.geturl()
    except urllib.error.HTTPError as e:
        hint = " (it blocks automatic downloads)" if e.code == 403 else ""
        raise ImportError_(f"The site answered {e.code}{hint}. Open the recipe in your browser and copy the text "
                           "into Paste text, or save the page as a PDF and add that.")
    except (urllib.error.URLError, OSError) as e:
        raise ImportError_(f"Could not reach the site ({getattr(e, 'reason', e)}).")
    if len(data) > MAX_FILE:
        raise ImportError_("That page is too large to import.")
    source = {"type": "url", "url": final}
    if "html" not in ctype and "text/plain" not in ctype:
        out = import_file(data, Path(urllib.parse.urlparse(final).path).name or "download", ctype, None)
        out["source"] = source
        return out
    page = data.decode("utf-8", "replace")
    title, site = _page_meta(page, final)
    source["site"] = site
    rec = find_jsonld_recipe(page)
    if rec:
        return {"kind": "structured", "recipe": normalize_schema(rec, final), "source": source}
    return {"kind": "text", "title": title, "text": html_to_text(page), "source": source, "method": "page text"}


def _page_meta(page, url):
    def og(p):
        m = re.search(r'<meta[^>]+property=["\']og:' + p + r'["\'][^>]*content=["\']([^"\']+)', page, re.I)
        return m.group(1) if m else ""
    t = og("title")
    if not t:
        m = re.search(r"<title[^>]*>([^<]*)</title>", page, re.I)
        t = m.group(1) if m else ""
    host = urllib.parse.urlparse(url).netloc
    return _html.unescape(t).strip(), _html.unescape(og("site_name") or re.sub(r"^www\.", "", host))


def find_jsonld_recipe(page):
    for m in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.I | re.S):
        try:
            data = json.loads(m.group(1).strip().strip("<!-->").strip())
        except ValueError:
            continue
        found = _walk(data)
        if found:
            return found
    return None


def _walk(node):
    if isinstance(node, list):
        for n in node:
            f = _walk(n)
            if f:
                return f
        return None
    if not isinstance(node, dict):
        return None
    t = node.get("@type")
    if t == "Recipe" or (isinstance(t, list) and "Recipe" in t):
        return node
    for k in ("@graph", "mainEntity", "mainEntityOfPage", "itemListElement"):
        f = _walk(node.get(k))
        if f:
            return f
    return None


def _txt(v):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", str(v or "")))).strip()


def normalize_schema(r, url):
    steps = []

    def add(node, section=""):
        if not node:
            return
        if isinstance(node, str):
            for part in re.split(r"\n+|</?p>|<br\s*/?>", _html.unescape(node), flags=re.I):
                if _txt(part):
                    steps.append({"text": _txt(part), "section": section})
            return
        if isinstance(node, list):
            for n in node:
                add(n, section)
            return
        if not isinstance(node, dict):
            return
        if node.get("@type") == "HowToSection":
            add(node.get("itemListElement"), _txt(node.get("name")) or section)
            return
        if node.get("itemListElement"):
            add(node["itemListElement"], section)
            return
        s = _txt(node.get("text") or node.get("name") or node.get("description"))
        if s:
            nm = _txt(node.get("name")) if node.get("name") and node.get("text") else ""
            steps.append({"text": s, "name": nm if nm != s else "", "section": section})

    add(r.get("recipeInstructions"))
    y = r.get("recipeYield")
    author = r.get("author")
    if isinstance(author, list):
        author = author[0] if author else ""
    if isinstance(author, dict):
        author = author.get("name")
    ing = r.get("recipeIngredient") or r.get("ingredients") or []
    return {
        "name": _txt(r.get("name")),
        "description": _txt(r.get("description")),
        "yield": _txt(y[-1] if isinstance(y, list) and y else y),
        "totalTime": str(r.get("totalTime") or ""),
        "ingredients": [_txt(i) for i in (ing if isinstance(ing, list) else [ing]) if _txt(i)],
        "steps": steps,
        "notes": _txt(r.get("recipeNotes")),
        "author": _txt(author),
        "url": url,
    }


def html_to_text(page):
    h = re.sub(r"<(script|style|noscript|svg|header|footer|nav|form|aside|iframe)\b.*?</\1>", " ", page, flags=re.I | re.S)
    h = re.sub(r"<!--.*?-->", " ", h, flags=re.S)
    m = re.search(r"<(article|main)[^>]*>(.*)</\1>", h, re.I | re.S)
    if m and len(m.group(2)) > 500:
        h = m.group(2)
    h = re.sub(r"<li[^>]*>", "\n• ", h, flags=re.I)
    h = re.sub(r"<(br|/p|/div|/h\d|/li|/tr|/section|/article)[^>]*>", "\n", h, flags=re.I)
    h = re.sub(r"</t[dh]>", "\t", h, flags=re.I)
    h = _html.unescape(re.sub(r"<[^>]+>", " ", h))
    lines = (re.sub(r"[ \t ]+", " ", l).strip() for l in h.split("\n"))
    return "\n".join(l for l in lines if l)


# ============================== files ==============================
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic"}


def import_file(raw, name, ctype, vision):
    ext = Path(name).suffix.lower()
    source = {"type": "file", "name": name}
    if ext == ".pdf" or "pdf" in ctype or raw[:5] == b"%PDF-":
        try:
            text = pdf_text(raw)
        except Exception:
            text = ""
        if len(re.sub(r"\s", "", text)) > 80:
            return {"kind": "text", "text": text, "source": source, "method": "PDF text"}
        return {"kind": "text", "text": clean_ocr(ocr(raw, ".pdf", True, vision)), "source": source, "method": "OCR (scanned PDF)"}
    if ext == ".docx" or (raw[:4] == b"PK\x03\x04" and ("word" in ctype or not ext)):
        return {"kind": "text", "text": docx_text(raw), "source": source, "method": "Word document"}
    if ext == ".doc":
        raise ImportError_("Old .doc files can't be read. In Word, use Save As > .docx or PDF, then add that.")
    if ctype.startswith("image/") or ext in IMAGE_EXT:
        return {"kind": "text", "text": clean_ocr(ocr(raw, ext or ".png", False, vision)), "source": source, "method": "OCR (image)"}
    if ctype.startswith("text/plain") or ext in (".txt", ".md"):
        return {"kind": "text", "text": raw.decode("utf-8", "replace"), "source": source, "method": "text file"}
    if "html" in ctype or ext in (".html", ".htm"):
        page = raw.decode("utf-8", "replace")
        rec = find_jsonld_recipe(page)
        if rec:
            return {"kind": "structured", "recipe": normalize_schema(rec, name), "source": source}
        return {"kind": "text", "text": html_to_text(page), "source": source, "method": "web page file"}
    raise ImportError_(f"Can't read {ext or ctype or 'this kind of file'}. Use a link, PDF, Word .docx, a picture, or paste the text.")


def clean_ocr(t):
    t = re.sub(r"(\d{2,3})[0oO°]\s?F\b", r"\1°F", t)       # "4750F" -> "475°F"
    return t.replace("“", '"').replace("”", '"')


def ocr(raw, ext, is_pdf, vision):
    """Text in a picture or a scanned PDF: Windows' own OCR, else Philibert's picture model."""
    if sys.platform == "win32" and OCR_SCRIPT.is_file():
        fd, tmp = tempfile.mkstemp(prefix="yeschef-", suffix=ext)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(OCR_SCRIPT), "-Path", tmp]
            if is_pdf:
                args.append("-Pdf")
            p = subprocess.run(args, capture_output=True, timeout=180,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out = p.stdout.decode("utf-8", "replace")
            if p.returncode == 0 and out.strip():
                return out
            err = p.stderr.decode("utf-8", "replace").strip().splitlines()
            if not vision:
                raise ImportError_("Windows text recognition failed" + (f": {err[0]}" if err else "."))
        except subprocess.TimeoutExpired:
            if not vision:
                raise ImportError_("Reading the picture took too long.")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    if is_pdf:
        raise ImportError_("This PDF is a scan (pictures of pages). On this computer it can't be read; "
                           "take a screenshot of each page and add those, or paste the text.")
    if not vision:
        raise ImportError_("Reading pictures needs Philibert's picture model (Eyes). Add it in Models, or paste the text.")
    fn, _name = vision
    out = fn([{"role": "user", "images": [base64.b64encode(raw).decode()],
               "content": "Write out ALL the text in this picture exactly as printed, line by line, keeping "
                          "numbers, fractions, units and temperatures exactly. No comments, only the text."}])
    if not out or out.startswith("[Ollama error"):
        raise ImportError_("The picture model could not read it: " + (out or "no answer"))
    return out


def docx_text(raw):
    try:
        xml = zipfile.ZipFile(io.BytesIO(raw)).read("word/document.xml").decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError):
        raise ImportError_("This Word file looks damaged.")
    out, line, in_row, counters = [], "", 0, {}
    tok = re.compile(r'<w:tr[ >]|</w:tr>|</w:tc>|<w:p[ >]|<w:p/>|</w:p>|<w:numId w:val="(\d+)"|'
                     r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>|<w:tab/>|<w:br[^>]*/>")
    for m in tok.finditer(xml):
        t = m.group(0)
        if t.startswith("<w:tr"):
            in_row += 1
        elif t == "</w:tr>":
            in_row = max(0, in_row - 1)
            out.append(line.rstrip("\t "))
            line = ""
        elif t == "</w:tc>":
            line = line.rstrip(" ") + "\t"
        elif m.group(1):
            counters[m.group(1)] = counters.get(m.group(1), 0) + 1
            line = f"{counters[m.group(1)]}. " + line
        elif m.group(2) is not None:
            line += _html.unescape(m.group(2))
        elif t == "<w:tab/>":
            line += "\t"
        elif t.startswith("<w:br"):
            line += "\n"
        elif t == "</w:p>":
            if in_row:
                line += " "
            else:
                out.append(line)
                line = ""
    if line:
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out))


# ---------- PDF text (for PDFs that contain real text) ----------
# Reads each piece of text with its position, then rebuilds the lines, so table rows
# ("Bread flour .... 600 g") stay together. Scans have no text; they go to OCR.
_WIN = {128: "€", 130: "‚", 131: "ƒ", 132: "„", 133: "…", 134: "†", 135: "‡", 136: "ˆ", 137: "‰", 138: "Š", 139: "‹",
        140: "Œ", 142: "Ž", 145: "‘", 146: "’", 147: "“", 148: "”", 149: "•", 150: "–", 151: "—", 152: "˜", 153: "™",
        154: "š", 155: "›", 156: "œ", 158: "ž", 159: "Ÿ"}


def _a85(b):
    s = re.sub(rb"\s", b"", b)
    if s.startswith(b"<~"):
        s = s[2:]
    if b"~>" in s:
        s = s[:s.index(b"~>")]
    out, group = bytearray(), []
    for ch in s:
        if ch == ord("z") and not group:
            out += b"\0\0\0\0"
            continue
        group.append(ch - 33)
        if len(group) == 5:
            v = 0
            for d in group:
                v = v * 85 + d
            out += (v & 0xFFFFFFFF).to_bytes(4, "big")
            group = []
    if group:
        n = len(group)
        group += [84] * (5 - n)
        v = 0
        for d in group:
            v = v * 85 + d
        out += (v & 0xFFFFFFFF).to_bytes(4, "big")[: n - 1]
    return bytes(out)


def _decode_stream(dct, raw):
    m = re.search(rb"/Filter\s*(\[[^\]]*\]|/\w+)", dct)
    filters = re.findall(rb"/(\w+)", m.group(1)) if m else []
    out = raw
    for f in filters:
        if f in (b"FlateDecode", b"Fl"):
            try:
                out = zlib.decompress(out)
            except zlib.error:
                try:
                    out = zlib.decompressobj().decompress(out)
                except zlib.error:
                    return None
        elif f in (b"ASCII85Decode", b"A85"):
            out = _a85(out)
        elif f in (b"ASCIIHexDecode", b"AHx"):
            h = re.sub(rb"[^0-9a-fA-F]", b"", out)
            out = bytes.fromhex((h + b"0").decode() if len(h) % 2 else h.decode())
        else:
            return None                                     # images and other filters: not text
    return out


def pdf_text(buf):
    objs = {}
    for m in re.finditer(rb"(\d+)\s+(\d+)\s+obj\b", buf):
        start = m.end()
        end = buf.find(b"endobj", start)
        if end < 0:
            break
        body = buf[start:end]
        sm = re.search(rb"\bstream\r?\n", body)
        dct, raw = body, None
        if sm:
            dct = body[:sm.start()]
            ds = start + sm.end()
            lm = re.search(rb"/Length\s+(\d+)(?!\s+\d+\s+R)", dct)
            de = ds + int(lm.group(1)) if lm else buf.find(b"endstream", ds)
            if de > end or de < ds:
                de = buf.find(b"endstream", ds)
            raw = buf[ds:de]
        objs.setdefault(int(m.group(1)), {"dict": dct, "raw": raw})
    cache = {}

    def data(n):
        if n not in cache:
            o = objs.get(n)
            cache[n] = _decode_stream(o["dict"], o["raw"]) if o and o["raw"] is not None else None
        return cache[n]

    # objects packed inside object streams (newer PDFs)
    for n, o in list(objs.items()):
        if not re.search(rb"/Type\s*/ObjStm", o["dict"]):
            continue
        d = data(n)
        if not d:
            continue
        first = int((re.search(rb"/First\s+(\d+)", o["dict"]) or [0, b"0"])[1])
        nums = [int(x) for x in d[:first].split()]
        for i in range(0, len(nums) - 1, 2):
            a = first + nums[i + 1]
            b = first + nums[i + 3] if i + 3 < len(nums) else len(d)
            objs.setdefault(nums[i], {"dict": d[a:b], "raw": None})

    def ref(s, key):
        m = re.search(rb"/" + key + rb"\s+(\d+)\s+\d+\s+R", s)
        return int(m.group(1)) if m else None

    def dict_of(s, key):
        r = ref(s, key)
        if r is not None:
            return (objs.get(r) or {}).get("dict", b"")
        i = s.find(b"/" + key)
        if i < 0:
            return b""
        j = s.find(b"<<", i)
        if j < 0:
            return b""
        depth, k = 0, j
        while k < len(s) - 1:
            if s[k:k + 2] == b"<<":
                depth += 1
                k += 2
                continue
            if s[k:k + 2] == b">>":
                depth -= 1
                k += 2
                if not depth:
                    return s[j:k]
                continue
            k += 1
        return b""

    fonts_cache = {}

    def load_font(n):
        if n in fonts_cache:
            return fonts_cache[n]
        d = (objs.get(n) or {}).get("dict", b"")
        f = {"map": None, "two": False}
        tu = ref(d, b"ToUnicode")
        if tu is not None and data(tu):
            cm = data(tu)
            f["map"] = {}
            space = re.search(rb"begincodespacerange(.*?)endcodespacerange", cm, re.S)
            f["two"] = bool(space and re.search(rb"<[0-9a-fA-F]{4}>\s*<[0-9a-fA-F]{4}>", space.group(1)))

            def hx(h):
                h = h.decode()
                return "".join(chr(int(h[i:i + 4], 16)) for i in range(0, len(h) - 3, 4))
            for blk in re.findall(rb"beginbfchar(.*?)endbfchar", cm, re.S):
                for a, b in re.findall(rb"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]*)>", blk):
                    f["map"][int(a, 16)] = hx(b)
            for blk in re.findall(rb"beginbfrange(.*?)endbfrange", cm, re.S):
                for lo, hi, dst, arr in re.findall(rb"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>\s*(?:<([0-9a-fA-F]*)>|\[([^\]]*)\])", blk):
                    lo, hi = int(lo, 16), int(hi, 16)
                    if dst:
                        base, prefix = int(dst[-4:], 16), hx(dst[:-4])
                        for c in range(lo, min(hi, lo + 5000) + 1):
                            f["map"][c] = prefix + chr(base + c - lo)
                    else:
                        for i, v in enumerate(re.findall(rb"<([0-9a-fA-F]*)>", arr)):
                            f["map"][lo + i] = hx(v)
        elif b"Identity-H" in d:
            f["two"] = True
        fonts_cache[n] = f
        return f

    def decode_str(bs, font):
        if font and font["map"] is not None:
            step = 2 if font["two"] else 1
            out = []
            for i in range(0, len(bs) - step + 1, step):
                code = (bs[i] << 8) | bs[i + 1] if step == 2 else bs[i]
                out.append(font["map"].get(code, (_WIN.get(code) or chr(code)) if step == 1 else ""))
            return "".join(out)
        if font and font["two"]:
            return ""
        return "".join(_WIN.get(b) or chr(b) for b in bs)

    pages = []

    def visit(n, inherited, depth=0):
        o = objs.get(n)
        if not o or depth > 30:
            return
        res = dict_of(o["dict"], b"Resources") or inherited
        if re.search(rb"/Type\s*/Pages", o["dict"]):
            kids = re.search(rb"/Kids\s*\[([^\]]*)\]", o["dict"])
            for k in re.findall(rb"(\d+)\s+\d+\s+R", kids.group(1) if kids else b""):
                visit(int(k), res, depth + 1)
        else:
            pages.append((o, res))

    cat = next((o for o in objs.values() if re.search(rb"/Type\s*/Catalog", o["dict"])), None)
    root = ref(cat["dict"], b"Pages") if cat else None
    if root is not None:
        visit(root, b"")
    if not pages:
        pages = [(o, dict_of(o["dict"], b"Resources")) for o in objs.values() if re.search(rb"/Type\s*/Page\b", o["dict"])]

    texts = []
    for o, res in pages:
        fonts = {}
        for name, num in re.findall(rb"/([^\s/<>\[\]()]+)\s+(\d+)\s+\d+\s+R", dict_of(res, b"Font")):
            fonts[name.decode("latin-1")] = load_font(int(num))
        content = []
        cm = re.search(rb"/Contents\s*(?:\[([^\]]*)\]|(\d+)\s+\d+\s+R)", o["dict"])
        if cm:
            nums = [int(x) for x in re.findall(rb"(\d+)\s+\d+\s+R", cm.group(1))] if cm.group(1) else [int(cm.group(2))]
            for n in nums:
                d = data(n)
                if d:
                    content.append(d)
        texts.append(_layout(_runs(b"\n".join(content), fonts, decode_str)))
    return "\n\n".join(_drop_repeats(texts))


def _mul(a, b):
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3], a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


_TOK = re.compile(rb"%[^\r\n]*|\((?:\\.|[^\\()]|\((?:\\.|[^\\()])*\))*\)|<<|>>|<[0-9a-fA-F\s]*>|\[|\]|/[^\s/\[\]()<>{}%]+|"
                  rb"[+\-]?(?:\d+\.?\d*|\.\d+)|[A-Za-z*'\"]+|\S", re.S)
_ESC = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}


def _lit(tok):
    s, out, i = tok[1:-1], bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == 92 and i + 1 < len(s):        # backslash
            i += 1
            c = s[i]
            if c in _ESC:
                out.append(_ESC[c])
            elif 48 <= c <= 55:
                o = bytes([c])
                while len(o) < 3 and i + 1 < len(s) and 48 <= s[i + 1] <= 55:
                    i += 1
                    o += bytes([s[i]])
                out.append(int(o, 8) & 255)
            elif c in (10, 13):
                pass
            else:
                out.append(c)
        else:
            out.append(c)
        i += 1
    return bytes(out)


def _runs(stream, fonts, decode_str):
    runs, stack, ops = [], [], []
    ctm, tm, lm = [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 0, 0]
    font, size, leading, dict_depth = None, 10.0, 0.0, 0

    def emit(text):
        nonlocal tm
        if not text.strip():
            return
        m = _mul(tm, ctm)
        runs.append((m[4], m[5], abs(size * (m[3] or m[0])) or size, text))
        tm = _mul([1, 0, 0, 1, len(text) * size * 0.5, 0], tm)

    for t in _TOK.findall(stream):
        if t.startswith(b"%"):
            continue
        if t == b"<<":
            dict_depth += 1
            continue
        if t == b">>":
            dict_depth = max(0, dict_depth - 1)
            continue
        if dict_depth:
            continue
        if t.startswith(b"("):
            ops.append(("s", _lit(t)))
        elif t.startswith(b"<"):
            h = re.sub(rb"\s", b"", t[1:-1])
            ops.append(("s", bytes.fromhex((h + b"0").decode() if len(h) % 2 else h.decode())))
        elif t == b"[":
            ops.append(("[", None))
        elif t == b"]":
            arr = []
            while ops and ops[-1][0] != "[":
                arr.insert(0, ops.pop())
            if ops:
                ops.pop()
            ops.append(("a", arr))
        elif t.startswith(b"/"):
            ops.append(("n", t[1:].decode("latin-1")))
        elif re.match(rb"[+\-]?(\d|\.\d)", t):
            ops.append(("f", float(t)))
        else:
            op = t.decode("latin-1")
            nums = [v for k, v in ops if k == "f"]
            if op == "q":
                stack.append(ctm)
            elif op == "Q":
                ctm = stack.pop() if stack else [1, 0, 0, 1, 0, 0]
            elif op == "cm" and len(nums) >= 6:
                ctm = _mul(nums[-6:], ctm)
            elif op == "BT":
                tm = lm = [1, 0, 0, 1, 0, 0]
            elif op == "Tf":
                nm = next((v for k, v in ops if k == "n"), None)
                font = fonts.get(nm)
                size = nums[-1] if nums else size
            elif op == "TL" and nums:
                leading = nums[-1]
            elif op == "Tm" and len(nums) >= 6:
                tm = lm = nums[-6:]
            elif op in ("Td", "TD") and len(nums) >= 2:
                tx, ty = nums[-2:]
                if op == "TD":
                    leading = -ty
                lm = _mul([1, 0, 0, 1, tx, ty], lm)
                tm = lm
            elif op == "T*":
                lm = _mul([1, 0, 0, 1, 0, -leading], lm)
                tm = lm
            elif op in ("Tj", "'", '"'):
                if op != "Tj":
                    lm = _mul([1, 0, 0, 1, 0, -leading], lm)
                    tm = lm
                s = next((v for k, v in reversed(ops) if k == "s"), None)
                if s is not None:
                    emit(decode_str(s, font))
            elif op == "TJ":
                arr = next((v for k, v in reversed(ops) if k == "a"), None)
                if arr:
                    words, cur = [], b""
                    for k, v in arr:
                        if k == "s":
                            cur += v
                        elif k == "f" and v < -180:            # a gap wide enough to be a space
                            words.append(cur)
                            cur = b""
                    words.append(cur)
                    emit(" ".join(decode_str(w, font) for w in words))
            ops = []
    return runs


def _layout(runs):
    if not runs:
        return ""
    lines = []
    for r in sorted(runs, key=lambda r: (-r[1], r[0])):
        ln = next((l for l in lines if abs(l[0] - r[1]) < max(2, r[2] * 0.45)), None)
        if ln:
            ln[1].append(r)
        else:
            lines.append([r[1], [r]])
    out = []
    for y, rs in sorted(lines, key=lambda l: -l[0]):
        rs.sort(key=lambda r: r[0])
        s, end = "", None
        for x, _y, sz, text in rs:
            if end is not None:
                gap = x - end
                if gap > sz * 2.5:
                    s += "\t"
                elif gap > sz * 0.12 and not s.endswith(" ") and not text.startswith(" "):
                    s += " "
            s += text
            end = x + len(text) * sz * 0.5
        out.append(re.sub(r" {2,}", " ", s).rstrip())
    return "\n".join(out)


def _drop_repeats(pages):
    """Headers and footers repeat on every page; drop them, and 'Page N'."""
    pageno = re.compile(r"^\s*page \d+( of \d+)?\s*$", re.I)
    if len(pages) < 2:
        return ["\n".join(l for l in p.split("\n") if not pageno.match(l)) for p in pages]
    count = {}
    for p in pages:
        for k in {re.sub(r"\d+", "#", l.strip()) for l in p.split("\n")}:
            count[k] = count.get(k, 0) + 1
    keep = []
    for p in pages:
        lines = []
        for l in p.split("\n"):
            k = re.sub(r"\d+", "#", l.strip())
            if k and not (count.get(k, 0) >= max(2, len(pages) * 0.6) and len(k) < 80) and not pageno.match(l):
                lines.append(l)
        keep.append("\n".join(lines))
    return keep


# ============================== Philibert helping ==============================
SYSTEM = ("You are Philibert, helping a home cook in real time inside the Yes Chef! app. Answer briefly and "
          "practically: a few sentences or a short list. Use the recipe and batch below. When you suggest an "
          "improvement, suggest one change at a time and say why.")


def _context(db, batch_id=None, recipe_id=None):
    b = db["batches"].get(batch_id) if batch_id else None
    r = (b or {}).get("recipe") or (db["recipes"].get(recipe_id) if recipe_id else None)
    if not r:
        return "No recipe is open."
    f = (b or {}).get("factor") or 1
    flour = sum(float(i.get("grams") or 0) for i in r.get("ingredients", []) if i.get("flour")) or 1
    lines = [f"Recipe: {r.get('name')}", "Ingredients (scaled):"]
    for i in r.get("ingredients", []):
        g = float(i.get("grams") or 0)
        lines.append(f"- {i.get('name')}: {round(g * f, 1)} g ({round(g / flour * 100, 1)}%)" if g else f"- {i.get('name')}: {i.get('note') or ''}")
    if r.get("notes"):
        lines.append("Recipe notes: " + str(r["notes"])[:1500])
    steps = r.get("steps", [])
    if b:
        cur = b.get("current", 0)
        lines.append(f"Batch: {b.get('label')}")
        if cur < len(steps):
            s = steps[cur]
            lines.append(f"Current step {cur + 1} of {len(steps)}: {s.get('title')} - {s.get('detail')}")
            st = (b.get("log") or {}).get(s.get("id"), {}).get("startedAt")
            if st:
                lines.append(f"On this step for {int((time.time() * 1000 - st) / 60000)} minutes.")
        if b.get("notes"):
            lines.append("Batch notes: " + str(b["notes"])[:800])
    else:
        lines.append("Steps: " + " | ".join(f"{n + 1}. {s.get('title')}" for n, s in enumerate(steps))[:1500])
    return "\n".join(lines)


GUIDE = HERE / "guides" / "yeschef.md"


def _guide():
    try:
        return GUIDE.read_text(encoding="utf-8")[:6000]
    except OSError:
        return ""


def _no_model(kind):
    return {"ok": False, "msg": f"No {kind} model on this drive yet. Add one in Models, then try again."}


def ask(body, data_dir, chat):
    if not chat:
        return _no_model("chat")
    q = str(body.get("question") or "").strip()
    if not q:
        return {"ok": False, "msg": "Type a question first."}
    with _lock:
        db = load(data_dir)
    msgs = [{"role": "system", "content": SYSTEM + "\n\n" + _guide() + "\n\n## Now\n" +
             _context(db, body.get("batchId"), body.get("recipeId"))}]
    for h in (body.get("history") or [])[-8:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant"):
            msgs.append({"role": h["role"], "content": str(h.get("content") or "")[:4000]})
    msgs.append({"role": "user", "content": q[:4000]})
    out = chat[0](msgs)
    if not out or out.startswith("[Ollama error") or out == "[No response]":
        return {"ok": False, "msg": "Philibert could not answer: " + (out or "no answer")}
    return {"ok": True, "answer": out, "model": chat[1]}


def evaluate(body, data_dir, vision):
    if not vision:
        return _no_model("picture-reading (Eyes)")
    name = Path(str(body.get("photoUrl") or "")).name
    f = photo_file(data_dir, name)
    if not f:
        return {"ok": False, "msg": "Photo not found."}
    with _lock:
        db = load(data_dir)
    b = db["batches"].get(body.get("batchId")) or {}
    step = next((s for s in (b.get("recipe") or {}).get("steps", []) if s.get("id") == body.get("stepId")), None)
    prompt = ("Look at this photo of my dough or bread at this stage. Say what you see, whether it looks on "
              "track, and what I should do next. Be specific and short.")
    if step:
        prompt += f"\nStage: {step.get('title')} - {step.get('detail')}"
        if step.get("check"):
            prompt += f"\nIt is ready when: {step['check']}"
    prompt += "\n\n" + _context(db, body.get("batchId"))
    out = vision[0]([{"role": "user", "content": prompt, "images": [base64.b64encode(f.read_bytes()).decode()]}])
    if not out or out.startswith("[Ollama error") or out == "[No response]":
        return {"ok": False, "msg": "The picture model could not look at it: " + (out or "no answer")}
    return {"ok": True, "answer": out, "model": vision[1]}


def structure(body, chat):
    """Messy imported text (a photo, an odd layout) -> a clean recipe, by Philibert's chat model."""
    if not chat:
        return _no_model("chat")
    text = str(body.get("text") or "").strip()
    if not text:
        return {"ok": False, "msg": "No text to tidy."}
    prompt = ("Extract the recipe from the text below. Reply with JSON only, no commentary, in this shape:\n"
              '{"name": string, "ingredients": [string, ...], "steps": [string, ...], "notes": string}\n'
              "- ingredients: one line each exactly as written (keep amounts and units, and gram amounts if given)\n"
              "- steps: one entry per instruction step, in order, keeping every time, temperature and warning\n"
              "- notes: tips, make-ahead or storage notes that are not steps\n"
              'Text:\n"""\n' + text[:24000] + '\n"""')
    out = chat[0]([{"role": "user", "content": prompt}])
    try:
        data = json.loads(out[out.index("{"): out.rindex("}") + 1])
        if not isinstance(data.get("ingredients"), list) or not isinstance(data.get("steps"), list):
            raise ValueError
    except ValueError:
        return {"ok": False, "msg": "Philibert's answer was not a recipe. Try again, or use a bigger model."}
    steps = [{"text": str(s.get("text") or s.get("step") or "") if isinstance(s, dict) else str(s)} for s in data["steps"]]
    return {"ok": True, "recipe": {"name": str(data.get("name") or ""), "ingredients": [str(i) for i in data["ingredients"]],
                                   "steps": steps, "notes": str(data.get("notes") or "")}}
