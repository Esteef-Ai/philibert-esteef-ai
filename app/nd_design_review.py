"""
nd_design_review.py — give the coding agent eyes.

THE PROBLEM THIS SOLVES
-----------------------
ND's agent writes a UI blind. It emits HTML, never looks at it, and declares
success. Every "why does this look generic / broken / unstyled" complaint traces
back to that single gap: the model has no idea what it produced.

Measured elsewhere on GUI code generation: adding rendered-screenshot feedback
moves task success ~21.7% -> ~28.3% and visual similarity 0.43 -> 0.56. The
ablation matters more than the headline — most of the gain is in ERROR
DETECTION, not repair. A model can fix its own broken layout once it can see it
is broken. It simply cannot tell.

HOW IT WORKS
------------
    render (headless Chrome/Edge)  ->  screenshots at 2 viewports
                                   ->  post-JS DOM dump
    deterministic checks           ->  facts no model has to be trusted for
    vision model                   ->  critique against the design brief

DEPENDENCIES
------------
None beyond what a Windows box already has. Uses the Chrome or Edge binary
already installed rather than Playwright, deliberately: ND is meant to come up
on a stock machine, and a 400 MB browser download to take a screenshot is a bad
trade. Pillow is used when present for blank-page detection and degrades
gracefully when it is not.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

__all__ = ["DesignReview", "find_browser", "layout_regressions"]

# Desktop first, then a phone. Responsive breakage is one of the most common and
# least visible failures — the desktop view can look perfect while the mobile
# view is a horizontally scrolling ruin.
DEFAULT_VIEWPORTS = [("desktop", 1440, 900), ("mobile", 390, 844)]

BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


# Runs INSIDE the page under review. Everything here is deliberately plain ES5-
# ish and wrapped in a try/catch: it is injected into arbitrary user pages, and
# an exception here must never be mistaken for "the page has no contrast
# problems". The result is written into a div the Python side reads back out of
# --dump-dom, which is the only channel available without a DevTools client.
_CONTRAST_JS = r"""
<script>(function(){
  function parse(c){
    var m = /rgba?\(([^)]+)\)/.exec(c||"");
    if(!m) return null;
    var p = m[1].split(",").map(function(x){return parseFloat(x)});
    return {r:p[0], g:p[1], b:p[2], a:(p.length>3?p[3]:1)};
  }
  function over(fg,bg){                       // composite a translucent colour
    if(!fg) return bg;
    if(fg.a>=1||!bg) return fg;
    return {r:fg.r*fg.a+bg.r*(1-fg.a), g:fg.g*fg.a+bg.g*(1-fg.a),
            b:fg.b*fg.a+bg.b*(1-fg.a), a:1};
  }
  function lum(c){
    var v=[c.r,c.g,c.b].map(function(x){
      x=x/255; return x<=0.03928 ? x/12.92 : Math.pow((x+0.055)/1.055,2.4);
    });
    return 0.2126*v[0]+0.7152*v[1]+0.0722*v[2];
  }
  function ratio(a,b){
    var l1=lum(a), l2=lum(b);
    return (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05);
  }
  // The real background is rarely on the element itself -- climb until
  // something opaque is found, compositing translucent layers on the way.
  function bgOf(el){
    var acc=null, n=el;
    while(n && n.nodeType===1){
      var c=parse(getComputedStyle(n).backgroundColor);
      if(c && c.a>0){ acc = acc ? over(acc,c) : c; if(acc.a>=1) return acc; }
      n=n.parentElement;
    }
    return acc && acc.a>=1 ? acc : {r:255,g:255,b:255,a:1};
  }
  function label(el){
    var s=el.tagName.toLowerCase();
    if(el.id) s+="#"+el.id;
    else if(el.className && typeof el.className==="string")
      s+="."+el.className.trim().split(/\s+/).slice(0,2).join(".");
    return s;
  }
  var res={counted:0, failed:0, failures:[], worst:null};
  try{
    var all=document.body.getElementsByTagName("*");
    for(var i=0;i<all.length;i++){
      var el=all[i], t="";
      // Only elements with their OWN text. Without this every ancestor is
      // scored on its descendants' text and one bad label reports 40 times.
      for(var j=0;j<el.childNodes.length;j++)
        if(el.childNodes[j].nodeType===3) t+=el.childNodes[j].nodeValue;
      t=t.replace(/\s+/g," ").trim();
      if(!t) continue;
      var r=el.getBoundingClientRect();
      if(r.width<4||r.height<4) continue;
      var st=getComputedStyle(el);
      if(st.visibility==="hidden"||st.display==="none") continue;
      if(parseFloat(st.opacity)<0.15) continue;   // deliberately faded, not broken
      var bg=bgOf(el);
      var fg=over(parse(st.color), bg);
      if(!fg) continue;
      var size=parseFloat(st.fontSize)||16;
      var bold=(parseInt(st.fontWeight,10)||400)>=700;
      var large=(size>=24)||(bold&&size>=18.66);
      var need=large?3.0:4.5;
      var cr=ratio(fg,bg);
      res.counted++;
      var row={sel:label(el), text:t.slice(0,40), ratio:Math.round(cr*100)/100,
               need:need, size:Math.round(size),
               fg:st.color, bg:"rgb("+Math.round(bg.r)+","+Math.round(bg.g)+","+Math.round(bg.b)+")"};
      if(!res.worst||cr<res.worst.ratio) res.worst=row;
      if(cr<need){ res.failed++; res.failures.push(row); }
    }
    res.failures.sort(function(a,b){return a.ratio-b.ratio});
    res.failures=res.failures.slice(0,__LIMIT__);
  }catch(e){ res.js_error=String(e); }
  var d=document.createElement("div");
  d.id="__nd_contrast";
  d.style.display="none";
  d.textContent=JSON.stringify(res);
  document.body.appendChild(d);
})();</script>
"""


# The layout half of the same idea. Contrast answered "can you read it?"; this
# answers "is it still the same shape?". Both run in the page for the same
# reason: computed type scale, wrapping and overflow are products of the whole
# cascade plus the viewport, and none of them exist in the stylesheet.
_LAYOUT_JS = r"""
<script>(function(){
  function label(el){
    var s=el.tagName.toLowerCase();
    if(el.id) s+="#"+el.id;
    else if(el.className && typeof el.className==="string")
      s+="."+el.className.trim().split(/\s+/).slice(0,2).join(".");
    return s;
  }
  var res={items:[], doc:{}, counted:0};
  try{
    var de=document.documentElement;
    res.doc={
      scrollW: de.scrollWidth, clientW: de.clientWidth,
      // Horizontal scrolling is the single most common responsive failure and
      // it is invisible in a desktop screenshot.
      hscroll: de.scrollWidth > de.clientWidth + 2
    };
    var all=document.body.getElementsByTagName("*");
    for(var i=0;i<all.length;i++){
      var el=all[i], t="";
      for(var j=0;j<el.childNodes.length;j++)
        if(el.childNodes[j].nodeType===3) t+=el.childNodes[j].nodeValue;
      t=t.replace(/\s+/g," ").trim();
      if(!t) continue;
      var r=el.getBoundingClientRect();
      if(r.width<4||r.height<4) continue;
      var st=getComputedStyle(el);
      if(st.visibility==="hidden"||st.display==="none") continue;
      var size=parseFloat(st.fontSize)||16;
      // Resolve `normal` to the usual ~1.2 factor so line counting works.
      var lh=parseFloat(st.lineHeight);
      if(!lh||isNaN(lh)) lh=size*1.2;
      res.counted++;
      res.items.push({
        sel:label(el), text:t.slice(0,40),
        size:Math.round(size*10)/10,
        family:(st.fontFamily||"").split(",")[0].replace(/["']/g,"").toLowerCase(),
        weight:parseInt(st.fontWeight,10)||400,
        w:Math.round(r.width), h:Math.round(r.height),
        lines:Math.max(1, Math.round(r.height/lh)),
        // Text wider than its own box that is not allowed to wrap is clipped
        // or spilling -- either way the user cannot read all of it.
        clipped: el.scrollWidth > el.clientWidth + 2,
        offRight: Math.round(r.right - de.clientWidth)
      });
    }
  }catch(e){ res.js_error=String(e); }
  var d=document.createElement("div");
  d.id="__nd_layout";
  d.style.display="none";
  d.textContent=JSON.stringify(res);
  document.body.appendChild(d);
})();</script>
"""


# How far the type scale may move before it counts as a redesign rather than a
# restyle. 1.4x is deliberately loose -- a theme legitimately nudges sizes, and
# a check that fires on every 10% change would be noise. The failure this is
# aimed at took a 20px heading to 60px.
_TYPE_SCALE_TOLERANCE = 1.4


def layout_regressions(base, now):
    """What the theme broke about the page's SHAPE, comparing like for like.

    Pure function over two layout_audit() results so it can be tested without a
    browser. Same rule as contrast: only things that got WORSE count. An app
    that already scrolls sideways is not the theme's doing.

    `hard` marks a regression that makes content unreachable or unreadable, as
    opposed to one that merely looks different.
    """
    out = []
    b, n = (base or {}), (now or {})
    bdoc, ndoc = b.get("doc") or {}, n.get("doc") or {}

    # A scrollbar the original did not have. The most common responsive failure
    # and completely invisible in a screenshot.
    if ndoc.get("hscroll") and not bdoc.get("hscroll"):
        out.append({"hard": True, "msg": (
            f"The page now scrolls sideways: content is "
            f"{ndoc.get('scrollW')}px wide in a {ndoc.get('clientW')}px "
            f"viewport, and it did not before.")})

    def key(i):
        return (i.get("sel"), (i.get("text") or "")[:24])

    was = {}
    for i in (b.get("items") or []):
        was.setdefault(key(i), i)          # first wins; matches audit order

    for i in (n.get("items") or []):
        o = was.get(key(i))
        if not o:
            continue
        bs, ns = float(o.get("size") or 0), float(i.get("size") or 0)
        if bs > 0 and ns > 0:
            f = ns / bs
            if f >= _TYPE_SCALE_TOLERANCE or f <= 1 / _TYPE_SCALE_TOLERANCE:
                out.append({"hard": False, "msg": (
                    f"{i['sel']} (\"{i['text'][:24]}\") went from {bs:g}px to "
                    f"{ns:g}px, {f:.1f}x.")})
        # One line becoming several is how a heading turns into a wall. Only
        # report it when it also got BIGGER -- text wrapping because the theme
        # narrowed a column is a different (and usually fine) thing.
        if (i.get("lines", 1) > o.get("lines", 1) and ns > bs
                and i.get("lines", 1) >= 2):
            out.append({"hard": False, "msg": (
                f"{i['sel']} (\"{i['text'][:24]}\") now wraps onto "
                f"{i['lines']} lines instead of {o.get('lines')}.")})
        # Text clipped or pushed off the right edge is unreachable, not ugly.
        if i.get("clipped") and not o.get("clipped"):
            out.append({"hard": True, "msg": (
                f"{i['sel']} (\"{i['text'][:24]}\") is now clipped — its text "
                f"is wider than its box.")})
        if (i.get("offRight", 0) > 4) and (o.get("offRight", 0) <= 4):
            out.append({"hard": True, "msg": (
                f"{i['sel']} (\"{i['text'][:24]}\") now extends "
                f"{i['offRight']}px past the right edge of the viewport.")})

    # Hard problems first: unreachable beats merely resized.
    out.sort(key=lambda x: not x["hard"])
    return out


def find_browser(explicit: str = "") -> str:
    """Locate a Chromium-family binary. Explicit config wins, then PATH, then
    the standard install locations."""
    if explicit and Path(explicit).exists():
        return explicit
    for name in ("chrome", "msedge", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    for c in BROWSER_CANDIDATES:
        if Path(c).exists():
            return c
    return ""


# ─── Deterministic checks ─────────────────────────────────────────────────────
# These run before the vision model and cost nothing. They exist because a small
# model asked "does this look good?" will happily praise a blank white page.
# Facts first, opinions second.

# max-width/min-width are the CORRECT pattern and must not be flagged; only a
# hard `width:` is the mobile-breaking one. Lookbehinds rather than a preceding
# character class, because inside a style="" attribute the preceding character
# is a quote and the class-based version silently never matched.
_FIXED_W_RE = re.compile(r"(?<!max-)(?<!min-)\bwidth\s*:\s*(\d{3,})px", re.I)
# Stop at < and > as well as ; } and newline. Without them this ran past the end
# of a style attribute and ate the remainder of a single-line file in one match,
# so a page with four fonts reported one.
_FONT_RE = re.compile(r"font-family\s*:\s*([^;}\n<>]+)", re.I)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
_HEX_RE = re.compile(r"#(?:[0-9a-f]{3}|[0-9a-f]{6})\b", re.I)


def _norm_font(decl: str) -> str:
    first = decl.split(",")[0].strip().strip("'\"").lower()
    return re.sub(r"\s+", " ", first)


def static_checks(html: str, dom: str = "") -> list[dict]:
    """Structural problems findable without rendering. Each finding is
    {level, code, msg} — 'error' means broken, 'warn' means suspect."""
    out: list[dict] = []
    src = dom or html

    def add(level, code, msg):
        out.append({"level": level, "code": code, "msg": msg})

    if not re.search(r"<title>\s*\S", src, re.I):
        add("warn", "no-title", "No <title>. The browser tab will read as the file path.")
    if not re.search(r'<meta[^>]+name=["\']?viewport', src, re.I):
        add("error", "no-viewport",
            "No viewport meta tag. The page will render zoomed-out and unusable on a phone, "
            'regardless of the CSS. Add <meta name="viewport" content="width=device-width, initial-scale=1">.')
    if not re.search(r"<html[^>]+lang=", src, re.I):
        add("warn", "no-lang", "No lang attribute on <html>.")

    imgs = _IMG_RE.findall(src)
    noalt = [t for t in imgs if not re.search(r"\balt\s*=", t, re.I)]
    if noalt:
        add("warn", "img-alt", f"{len(noalt)} of {len(imgs)} <img> tags have no alt attribute.")

    fixed = [int(m) for m in _FIXED_W_RE.findall(html) if int(m) >= 500]
    if fixed:
        add("warn", "fixed-width",
            f"Fixed pixel width(s) found: {sorted(set(fixed))[:5]}. These are the usual cause of "
            "horizontal scrolling on mobile — prefer max-width with a % or vw fallback.")

    fonts = {_norm_font(f) for f in _FONT_RE.findall(html)}
    fonts = {f for f in fonts if f and not f.startswith("var(")}
    if len(fonts) > 3:
        add("warn", "font-sprawl",
            f"{len(fonts)} distinct font families ({', '.join(sorted(fonts)[:6])}). "
            "More than 2-3 reads as unplanned rather than designed.")

    hexes = {h.lower() for h in _HEX_RE.findall(html)}
    if len(hexes) > 18:
        add("warn", "colour-sprawl",
            f"{len(hexes)} distinct hex colours. A designed palette is usually under a dozen; "
            "this many suggests colours were picked ad hoc per element.")

    if re.search(r"lorem ipsum", src, re.I):
        add("warn", "placeholder-text", "Lorem ipsum placeholder text is still in the page.")
    if re.search(r"\bTODO\b|\bFIXME\b", src):
        add("warn", "todo", "TODO/FIXME left in the shipped file.")
    return out


_ASSET_RE = re.compile(
    r"""<(?:link[^>]+href|script[^>]+src|img[^>]+src)\s*=\s*["']([^"']+)["']""", re.I)


def dead_assets(html: str, base_dir: Path) -> list[dict]:
    """Local stylesheets, scripts and images referenced but not present on disk.

    This is the check that would have caught the worst failure this tool was
    built for: a page whose <link rel=stylesheet> pointed at a CSS file that was
    never written. It rendered as unstyled Times New Roman on white -- and both
    a text model reading the HTML and a vision model looking at the screenshot
    called it fine. The HTML was perfect. The stylesheet simply was not there.
    """
    # Scan only real markup. A <script> block full of template literals like
    # `<img src="${game.image}">` is code that BUILDS markup at runtime, not a
    # reference to a file on disk -- reporting it as a dead asset sends the
    # agent off fixing a bug that does not exist.
    # Keep the opening tag, drop only the body: stripping the whole element also
    # removed <script src="app.js"> and a genuinely missing external script
    # stopped being reported. Caught by the must-fire test.
    markup = re.sub(r"(<script\b[^>]*>).*?</script>", r"\1", html, flags=re.S | re.I)
    out = []
    for ref in _ASSET_RE.findall(markup):
        r = ref.strip()
        if not r or r.startswith(("http://", "https://", "//", "data:", "#", "mailto:")):
            continue
        # Any remaining templating syntax is resolved at runtime, not by us.
        if "${" in r or "{{" in r or "<%" in r or r.startswith("{"):
            continue
        target = (base_dir / r.split("?")[0].split("#")[0]).resolve()
        if target.exists():
            continue
        ext = target.suffix.lower()
        if ext == ".css":
            why = ("The page is therefore rendering COMPLETELY UNSTYLED, in browser "
                   "default fonts. Write this file, or inline its rules in a <style> block.")
        elif ext == ".js":
            why = ("Every interactive behaviour on the page is dead. Write this file, "
                   "or inline it in a <script> block.")
        else:
            why = "It will render as a broken-image placeholder."
        out.append({"level": "error", "code": "dead-asset",
                    "msg": f"Referenced file does not exist: {r}. {why}"})
    return out


def palette_from_png(png_path: Path, top: int = 6) -> list[tuple]:
    """The colours ACTUALLY on screen, as facts.

    Without this the vision model is free to agree with whatever palette the
    brief claimed. Measured: told the brief was 'hot magenta, cyan, near-black',
    it reported that the page used hot magenta and cyan. The page was white with
    default-blue and default-red boxes.
    """
    try:
        from PIL import Image
    except Exception:
        return []
    try:
        with Image.open(png_path) as im:
            im = im.convert("RGB").resize((200, 125))
            px = list(im.getdata())
    except Exception:
        return []
    counts: dict = {}
    for p in px:
        # coarse buckets so near-identical shades group together
        key = (p[0] // 24 * 24, p[1] // 24 * 24, p[2] // 24 * 24)
        counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:top]
    total = len(px) or 1
    return [("#%02x%02x%02x" % c, round(n / total, 3)) for c, n in ranked]


def looks_unstyled(html: str, palette: list) -> Optional[dict]:
    """Heuristic for 'the CSS never applied'."""
    has_inline = bool(re.search(r"<style[^>]*>\s*\S", html, re.I))
    has_attr_style = len(re.findall(r"\bstyle\s*=", html, re.I)) >= 3
    if has_inline or has_attr_style:
        return None
    if not re.search(r"<link[^>]+stylesheet", html, re.I):
        return {"level": "error", "code": "no-styles",
                "msg": ("The page has no <style> block and no stylesheet link at all. "
                        "It is rendering with raw browser defaults.")}
    # A stylesheet is linked; if the render is overwhelmingly white it did not land.
    if palette and palette[0][0] in ("#ffffff", "#f8f8f8") and palette[0][1] > 0.8:
        return {"level": "error", "code": "styles-not-applied",
                "msg": ("A stylesheet is linked but the render is "
                        f"{int(palette[0][1]*100)}% plain white — the CSS is not being applied. "
                        "Check the href resolves relative to this file.")}
    return None


# ─── State checks ─────────────────────────────────────────────────────────────
# The house style asks for loading / empty / error / disabled / hover / focus.
# Asking is not enough on its own: a small model reliably forgets whichever ones
# were not mentioned in the last 200 tokens. These are cheap to verify, so verify
# them. Missing states are what makes a generated UI feel like a mockup rather
# than a product.
_STATE_PATTERNS = [
    ("hover",    r":hover\b", "No :hover styles. Interactive elements feel dead."),
    ("focus",    r":focus(-visible)?\b",
     "No :focus styles. The page is unusable by keyboard and fails accessibility."),
    ("disabled", r":disabled\b|\[disabled\]|\bdisabled\b|\.is-disabled|aria-disabled",
     "No disabled state. Controls that need data should be visibly inert until it exists."),
    ("empty",    r"empty[-_]?state|no[-_ ](results|games|items|data)|nothing here|"
                 r"get started|add your first",
     "No empty state. A first-run user sees a blank region with no idea what to do."),
    ("loading",  r"loading|skeleton|spinner|progress|\bloader\b",
     "No loading state. The page will flash from nothing straight to content."),
    ("error",    r"error|failed|unavailable|not (running|found|connected)|try again|retry",
     "No error state. Nothing tells the user what to do when something breaks."),
    ("motion",   r"@keyframes|transition\s*:|animation\s*:",
     "No transitions or animation at all."),
]


# A state is only REQUIRED when the page has something it could apply to.
# Measured 2026-09-24: a page that was one <h1> saying "hello" was told it was
# missing hover, focus, disabled, empty, loading, error and motion, and the
# design loop spent three rounds of a 27B model adding them. There was nothing
# to hover, nothing to disable, and no data that could load, be empty or fail.
_INTERACTIVE_RE = re.compile(
    r"<(?:a\s[^>]*\bhref|button|input|select|textarea|summary|details)\b"
    r"|\bonclick\s*=|\btabindex\s*=|\brole\s*=\s*[\"'](?:button|link|tab|menuitem|switch)",
    re.I)
_CONTROL_RE = re.compile(r"<(?:button|input|select|textarea)\b|\brole\s*=\s*[\"']button", re.I)
_FORM_RE = re.compile(r"<(?:form|input|textarea|select)\b", re.I)
# Content that arrives or changes at run time -- the only kind that can be
# loading, come back empty, or fail.
_DYNAMIC_RE = re.compile(
    r"\bfetch\s*\(|XMLHttpRequest|new\s+WebSocket|EventSource|\.then\s*\(|\bawait\s"
    r"|\.innerHTML\s*[+]?=|\.appendChild\s*\(|\.insertAdjacentHTML|\.replaceChildren\s*\(",
    re.I)


def applicable_states(html: str, dom: str = "") -> set:
    """The states this page can actually have, judged from what is on it."""
    src = (html or "") + "\n" + (dom or "")
    need = set()
    if _INTERACTIVE_RE.search(src):
        need |= {"hover", "focus", "motion"}
    if _CONTROL_RE.search(src):
        need.add("disabled")
    if _DYNAMIC_RE.search(src):
        need |= {"empty", "loading", "error"}
    if _FORM_RE.search(src):
        need.add("error")          # a form needs a way to say its input was wrong
    return need


def state_checks(html: str, dom: str = "") -> list[dict]:
    """Which APPLICABLE interaction states the page does not visibly handle."""
    src = (html or "") + "\n" + (dom or "")
    need = applicable_states(html, dom)
    out = []
    for name, pat, msg in _STATE_PATTERNS:
        if name in need and not re.search(pat, src, re.I):
            out.append({"level": "warn", "code": f"no-{name}", "msg": msg})
    return out


def state_summary(html: str, dom: str = "") -> str:
    src = (html or "") + "\n" + (dom or "")
    need = applicable_states(html, dom)
    have = [n for n, pat, _ in _STATE_PATTERNS if re.search(pat, src, re.I)]
    miss = [n for n, _, _ in _STATE_PATTERNS if n in need and n not in have]
    na = [n for n, _, _ in _STATE_PATTERNS if n not in need and n not in have]
    return ("States present: " + (", ".join(have) if have else "none")
            + (" | MISSING: " + ", ".join(miss) if miss else " | none missing")
            + (" | not applicable to this page: " + ", ".join(na) if na else ""))


def blank_check(png_path: Path) -> dict:
    """Is the render essentially one flat colour? This is the check that catches
    the failure a vision model most often talks itself past: a JS error left the
    page empty, and a confident critique gets written about nothing."""
    try:
        from PIL import Image
    except Exception:
        return {"ok": True, "checked": False}
    try:
        with Image.open(png_path) as im:
            im = im.convert("RGB").resize((160, 100))
            px = list(im.getdata())
    except Exception as e:
        return {"ok": True, "checked": False, "msg": str(e)}
    if not px:
        return {"ok": True, "checked": False}
    counts: dict = {}
    for p in px:
        counts[p] = counts.get(p, 0) + 1
    top, n = max(counts.items(), key=lambda kv: kv[1])
    share = n / len(px)
    return {"ok": share < 0.97, "checked": True, "dominant": top,
            "share": round(share, 3), "distinct": len(counts)}


# ─── The reviewer ─────────────────────────────────────────────────────────────

CRITIQUE_PROMPT = """You are a senior UI designer reviewing a rendered screenshot of a web page.

SEEN: First, in one or two lines, describe only what is literally in the image —
the actual colours, the actual typeface (does it look like a default serif such as
Times, or a chosen font?), and the actual layout. Describe the image in front of
you, not what a page like this usually looks like.
{brief_block}
Then answer these, briefly:

VERDICT: one line — is this shippable, promising, or broken?
WORKS: up to 3 things that genuinely look good. If nothing does, write "nothing yet".
BROKEN: anything visually wrong — unstyled browser defaults, overlapping or
cut-off elements, unreadable contrast, blown-out spacing, placeholder text left in.
GENERIC: where this looks like a template rather than a designed thing. Be blunt.
FIX FIRST: the single highest-impact change, as a concrete instruction.
"""

# Deliberately NOT "here is the brief, does it match?". Given the brief up front,
# a small vision model confirms it: told 'hot magenta, cyan, near-black', it
# reported the page used hot magenta and cyan. The page was white with default
# blue and red boxes. Describe first, compare second, and the measured palette
# is supplied alongside so the comparison has a fact to sit against.
BRIEF_BLOCK = """
It was SUPPOSED to be built to this brief:
{brief}

The colours actually measured in this screenshot are: {palette}
Compare what you SEE against that brief. If the page does not match it, say so
plainly — do not assume the brief was followed.
"""


class DesignReview:
    """Render a local HTML file, check it, and get a critique of what it looks like."""

    def __init__(self, config: Optional[dict] = None, log: Optional[Callable] = None):
        cfg = config or {}
        self.browser = find_browser(str(cfg.get("design_browser") or ""))
        self.timeout = int(cfg.get("design_render_timeout", 45))
        self.out_dir = Path(cfg.get("design_shot_dir") or (Path(__file__).parent / "temp" / "design"))
        self.log = log or (lambda *a, **k: None)
        self.last_error = ""
        # Keyed by (kind, path, mtime, size) -- see _audit_cached().
        self._audit_cache = {}

    # -- rendering ---------------------------------------------------------
    def available(self) -> bool:
        return bool(self.browser)

    def render(self, html_path, viewports=None) -> list[dict]:
        """Screenshot the file at each viewport. Returns [{label, w, h, png, ok}]."""
        p = Path(str(html_path))
        if not p.exists():
            self.last_error = f"file not found: {p}"
            return []
        if not self.browser:
            self.last_error = ("no Chrome or Edge found — set design_browser in "
                               "neuraldock_config.json to a chrome.exe or msedge.exe path")
            return []
        self.out_dir.mkdir(parents=True, exist_ok=True)
        url = p.resolve().as_uri()
        shots = []
        for label, w, h in (viewports or DEFAULT_VIEWPORTS):
            png = self.out_dir / f"{p.stem}-{label}-{int(time.time())}.png"
            # A throwaway profile per run: without it a running Chrome instance
            # hijacks the invocation and the screenshot silently never appears.
            with tempfile.TemporaryDirectory(prefix="nd-shot-") as profile:
                cmd = [
                    self.browser,
                    "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--no-first-run", "--no-default-browser-check",
                    "--disable-extensions", "--mute-audio",
                    f"--user-data-dir={profile}",
                    f"--window-size={w},{h}",
                    # let webfonts, images and any entry script actually finish
                    "--virtual-time-budget=6000",
                    f"--screenshot={png}",
                    url,
                ]
                try:
                    r = subprocess.run(cmd, capture_output=True, timeout=self.timeout)
                    err = (r.stderr or b"").decode("utf-8", "replace")
                except subprocess.TimeoutExpired:
                    err = f"render timed out after {self.timeout}s"
                except Exception as e:
                    err = str(e)
            ok = png.exists() and png.stat().st_size > 0
            shots.append({"label": label, "w": w, "h": h, "png": str(png),
                          "ok": ok, "err": "" if ok else err[:400]})
            self.log(f"design_review: {label} {w}x{h} -> {'ok' if ok else 'FAILED'}",
                     "ok" if ok else "warn")
        return shots

    def dump_dom(self, html_path) -> str:
        """Post-JavaScript DOM. The source file is what was written; this is what
        the browser actually built, which is where JS failures become visible."""
        if not self.browser:
            return ""
        p = Path(str(html_path))
        with tempfile.TemporaryDirectory(prefix="nd-dom-") as profile:
            cmd = [self.browser, "--headless=new", "--disable-gpu", "--no-first-run",
                   f"--user-data-dir={profile}", "--virtual-time-budget=6000",
                   "--dump-dom", p.resolve().as_uri()]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=self.timeout)
                return (r.stdout or b"").decode("utf-8", "replace")
            except Exception:
                return ""

    def contrast_audit(self, html_path, limit=14) -> dict:
        """Measure the contrast of every piece of visible text, in the browser.

        WHY THIS IS NOT A CSS CHECK
        ---------------------------
        Three models reskinned RetroVault and all three made the entire chrome
        -- the menu bar, the ROM toolbar, the sidebar, the warning strip --
        near-black on black. Every automated check passed. The palette looked
        rich (600+ distinct colours), nothing rendered blank, no asset was dead.
        The one thing wrong was the only thing that mattered: you could not read
        it.

        You cannot find that in the stylesheet. The text colour comes from one
        rule, the background from an ancestor several levels up, and either may
        be a custom property the theme layer redefined. Only the browser knows
        what actually won. So ask the browser: walk the rendered tree, take
        getComputedStyle for each text-bearing element, resolve the real
        background by climbing ancestors through transparent ones, and compute
        the WCAG ratio.

        Thresholds are the WCAG AA ones: 4.5:1 for body text, 3.0:1 for large
        text (>=24px, or >=18.66px bold).
        """
        out = {"checked": False, "worst": None, "failures": [], "counted": 0,
               "failed": 0, "error": ""}
        data, err = self._in_page_audit(
            html_path, _CONTRAST_JS.replace("__LIMIT__", str(int(limit))),
            "__nd_contrast")
        if err:
            out["error"] = err
            return out
        out.update(data)
        out["checked"] = True
        return out

    def layout_audit(self, html_path, width=1440, height=900) -> dict:
        """Type scale, wrapping and overflow, measured in the browser.

        The companion to contrast_audit. A theme that keeps every colour legible
        can still wreck the page: the second reskin of RetroVault fixed its
        contrast and simultaneously blew "ALL GAMES" into a huge two-line
        heading. Nothing in the stylesheet says that -- the computed size, the
        line count and the overflow are products of the whole cascade and the
        viewport together.
        """
        out = {"checked": False, "items": [], "doc": {}, "counted": 0, "error": ""}
        data, err = self._in_page_audit(html_path, _LAYOUT_JS, "__nd_layout",
                                        width, height)
        if err:
            out["error"] = err
            return out
        out.update(data)
        out["checked"] = True
        return out

    def _audit_cached(self, kind, html_path, fn):
        """Audit a file once per (path, mtime, size).

        The SOURCE of a reskin never changes during a run, but the review
        re-measured it on every call: contrast on the output, contrast on the
        source, layout on the output, layout on the source -- four headless
        Chrome launches per design_review, two of them recomputing an identical
        answer on a 185 KB page. Across an iteration loop that is most of the
        wall-clock, and it is what made the loop look like a hang.
        """
        p = Path(str(html_path))
        try:
            st = p.stat()
            key = (kind, str(p.resolve()).lower(), int(st.st_mtime), st.st_size)
        except OSError:
            return fn(html_path)
        hit = self._audit_cache.get(key)
        if hit is not None:
            return hit
        val = fn(html_path)
        # Only cache a real measurement. Caching a failure would make one bad
        # browser launch permanent for the rest of the session.
        if val.get("checked"):
            if len(self._audit_cache) > 24:
                self._audit_cache.clear()
            self._audit_cache[key] = val
        return val

    def _in_page_audit(self, html_path, script, marker, width=1440, height=900):
        """Run a measurement script inside the page. Returns (data, error).

        Shared by contrast_audit and layout_audit because the awkward parts are
        identical, and because getting them subtly different in two places is
        how one of them ends up quietly wrong.
        """
        p = Path(str(html_path))
        if not self.browser:
            return None, "no browser"
        if not p.is_file():
            return None, "file not found"
        # The script must run INSIDE the page, so append it to a throwaway copy
        # in the SAME directory -- relative assets (stylesheets, fonts, images)
        # have to keep resolving -- and a copy because reviewing a file must
        # never modify it.
        probe = p.with_name(f".nd-{marker.strip('_')}-{os.getpid()}-{p.name}")
        try:
            html = p.read_text(encoding="utf-8", errors="replace")
            idx = html.lower().rfind("</body>")
            probe.write_text(
                (html[:idx] + script + html[idx:]) if idx > 0 else html + script,
                encoding="utf-8")
            with tempfile.TemporaryDirectory(prefix="nd-audit-") as profile:
                cmd = [self.browser, "--headless=new", "--disable-gpu",
                       "--no-first-run", f"--user-data-dir={profile}",
                       f"--window-size={int(width)},{int(height)}",
                       "--virtual-time-budget=6000",
                       "--dump-dom", probe.resolve().as_uri()]
                r = subprocess.run(cmd, capture_output=True, timeout=self.timeout)
                dom = (r.stdout or b"").decode("utf-8", "replace")
            # Anchor on the DIV, not the bare id. The script's own source is
            # serialised into the dump too and contains the literal
            # d.id="__nd_..." -- a looser pattern matches the script text first
            # and parses JavaScript as JSON. Take the last match for the same
            # reason.
            ms = list(re.finditer(r'<div id="' + re.escape(marker) + r'"[^>]*>(.*?)</div>',
                                  dom, re.S))
            if not ms:
                return None, "audit script did not report"
            return json.loads(html_lib.unescape(ms[-1].group(1))), ""
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"
        finally:
            try:
                probe.unlink()
            except OSError:
                pass

    # -- the full pass -----------------------------------------------------
    def review(self, html_path, brief: str = "", vision_fn: Optional[Callable] = None,
               viewports=None, source_path=None) -> dict:
        """Render, check, critique. `vision_fn(b64_png, prompt) -> str` is injected
        so this module never needs to know how ND talks to Ollama.

        `source_path` is the file a RESKIN was supposed to preserve. When given,
        the output is compared against it before anything else is judged --
        because a page that no longer contains the application is not a design
        problem, and every aesthetic finding below it is beside the point.
        """
        import base64

        p = Path(str(html_path))
        result = {"ok": False, "file": str(p), "shots": [], "findings": [],
                  "critique": "", "blank": None}
        if not p.exists():
            result["error"] = f"file not found: {p}"
            return result

        html = p.read_text(encoding="utf-8", errors="replace")
        dom = self.dump_dom(p)
        # Dead assets first: a missing stylesheet explains every other symptom,
        # and nothing below is worth reading until it is fixed.
        result["findings"] = (dead_assets(html, p.resolve().parent)
                              + static_checks(html, dom)
                              + state_checks(html, dom))
        result["states"] = state_summary(html, dom)

        # Did the reskin keep the app? This goes FIRST and outranks every
        # aesthetic finding. Five models once "reskinned" a 185 KB application
        # into ~6 KB pages with zero JavaScript and none of its 196 element ids,
        # and the review loop -- which only ever looked at hover states and
        # palettes -- reported them as pages needing more interaction states.
        # A beautiful page that is no longer the app is a failed job.
        if source_path:
            try:
                import nd_reskin
                src = Path(str(source_path))
                if src.is_file() and src.resolve() != p.resolve():
                    rep = nd_reskin.preservation_report(
                        src.read_text(encoding="utf-8", errors="replace"), html)
                    result["preservation"] = rep
                    if rep["severity"] in ("error", "warn"):
                        result["findings"].insert(0, {
                            "level": rep["severity"], "code": f"app-{rep['verdict']}",
                            "msg": rep["summary"] + (
                                "  Restore the original and apply the theme as a "
                                "CSS layer instead of rewriting the file."
                                if rep["severity"] == "error" else "")})
            except Exception as e:
                # Never let a missing check pass as a clean bill of health.
                result["findings"].insert(0, {
                    "level": "warn", "code": "preservation-unchecked",
                    "msg": f"Could not verify the app survived the reskin: {e}"})

        shots = self.render(p, viewports)
        result["shots"] = shots
        good = [s for s in shots if s["ok"]]
        if not good:
            result["error"] = (self.last_error
                               or (shots[0]["err"] if shots else "render produced no image"))
            return result

        # Blank-page detection on the desktop shot, before any critique.
        desktop = next((s for s in good if s["label"] == "desktop"), good[0])
        blank = blank_check(Path(desktop["png"]))
        result["blank"] = blank
        if blank.get("checked") and not blank.get("ok"):
            result["findings"].insert(0, {
                "level": "error", "code": "blank-render",
                "msg": (f"The page renders as {int(blank['share']*100)}% a single colour "
                        f"{blank['dominant']}. Nothing meaningful is on screen — this is "
                        "usually a JavaScript error or a stylesheet that never loaded. "
                        "Fix that before any styling work.")})

        # Body text presence: a page can be colourful and still have rendered nothing.
        if dom:
            body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", dom,
                          flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", body)
            if len(re.sub(r"\s+", " ", text).strip()) < 40:
                result["findings"].insert(0, {
                    "level": "error", "code": "empty-dom",
                    "msg": "The rendered DOM contains almost no text. The page built empty."})

        # Measured palette, and the "CSS never applied" check that depends on it.
        palette = palette_from_png(Path(desktop["png"]))
        result["palette"] = palette
        unstyled = looks_unstyled(html, palette)
        if unstyled:
            result["findings"].insert(0, unstyled)

        # ── Contrast, measured in the browser ────────────────────────────────
        # The check that was missing. Everything else here can pass on a page
        # whose text is invisible: the palette looks rich, nothing renders
        # blank, no asset is dead. Only the browser knows what colour actually
        # won the cascade, so it computes the WCAG ratios and we read them back.
        #
        # For a RESKIN the absolute number is the less useful half. RetroVault
        # already fails 5 of 27 elements before anyone touches it -- reporting
        # that as the reskin's fault would be wrong, and I made exactly that
        # mistake by eye before measuring. What matters is the DELTA: did this
        # theme make something readable unreadable?
        contrast = self.contrast_audit(p)
        result["contrast"] = contrast
        if contrast.get("checked"):
            base = None
            if source_path:
                try:
                    src = Path(str(source_path))
                    if src.is_file() and src.resolve() != p.resolve():
                        # Cached: the source does not change during a run, and
                        # re-measuring it every review doubled the browser cost.
                        base = self._audit_cached("contrast", src, self.contrast_audit)
                        result["contrast_source"] = base
                except Exception:
                    base = None

            if base and base.get("checked"):
                # Key on selector AND text. Selector alone collides: this app
                # has several failing bare <span> elements, so a dict keyed on
                # "span" keeps only the last and every other span then looks
                # brand new -- reporting regressions that never happened.
                def _key(f):
                    return (f["sel"], f["text"][:24])

                was = {_key(f): f["ratio"] for f in (base.get("failures") or [])}
                # A regression is text that FAILS now and either passed before
                # or got measurably worse. Anything already broken in the source
                # is the app's problem, not the theme's.
                regressed = [f for f in (contrast.get("failures") or [])
                             if _key(f) not in was
                             or f["ratio"] < was[_key(f)] - 0.3]
                if regressed:
                    worst = regressed[0]
                    result["findings"].insert(0, {
                        "level": "error", "code": "contrast-regression",
                        "msg": (f"The theme made text harder to read. "
                                f"{len(regressed)} element(s) that were legible "
                                f"in the original now fail WCAG AA — worst is "
                                f"{worst['sel']} at {worst['ratio']}:1 (needs "
                                f"{worst['need']}:1), {worst['fg']} on "
                                f"{worst['bg']}, showing \"{worst['text']}\". "
                                f"Fix the colours for these, not the layout.")})
                else:
                    result["findings"].append({
                        "level": "ok", "code": "contrast-held",
                        "msg": (f"Contrast did not regress: "
                                f"{contrast['failed']}/{contrast['counted']} "
                                f"elements fail, against "
                                f"{base['failed']}/{base['counted']} in the "
                                f"original.")})
            elif contrast.get("counted"):
                # No source to compare against, so judge it on its own.
                worst = contrast.get("worst") or {}
                share = contrast["failed"] / max(contrast["counted"], 1)
                if share >= 0.30 or (worst.get("ratio") or 99) < 2.0:
                    result["findings"].insert(0, {
                        "level": "error", "code": "contrast-fail",
                        "msg": (f"{contrast['failed']} of {contrast['counted']} "
                                f"text elements fail WCAG AA. Worst: "
                                f"{worst.get('sel')} at {worst.get('ratio')}:1 "
                                f"(needs {worst.get('need')}:1), "
                                f"{worst.get('fg')} on {worst.get('bg')}. "
                                f"Text this faint is not a style choice, it is "
                                f"unreadable.")})
                elif contrast["failed"]:
                    result["findings"].append({
                        "level": "warn", "code": "contrast-thin",
                        "msg": (f"{contrast['failed']} of {contrast['counted']} "
                                f"text elements are below WCAG AA. Worst: "
                                f"{worst.get('sel')} at {worst.get('ratio')}:1.")})
        elif contrast.get("error"):
            # Silence here would read as a pass. Say the check did not run.
            result["findings"].append({
                "level": "warn", "code": "contrast-unchecked",
                "msg": f"Contrast could not be measured: {contrast['error']}"})

        # ── Layout and typography, measured the same way ─────────────────────
        # Contrast alone is not enough. The reskin that fixed its contrast also
        # blew "ALL GAMES" into a huge two-line heading and it passed every
        # check. Same method, same delta-not-absolute rule: an app with a
        # cramped layout of its own is not the theme's fault, but a theme that
        # doubles the type scale or starts a horizontal scrollbar is.
        layout = self.layout_audit(p)
        result["layout"] = layout
        if layout.get("checked") and source_path:
            try:
                src = Path(str(source_path))
                lbase = (self._audit_cached("layout", src, self.layout_audit)
                         if src.is_file() and src.resolve() != p.resolve() else None)
            except Exception:
                lbase = None
            if lbase and lbase.get("checked"):
                result["layout_source"] = lbase
                probs = layout_regressions(lbase, layout)
                if probs:
                    result["findings"].insert(0, {
                        "level": "error" if any(x["hard"] for x in probs) else "warn",
                        "code": "layout-regression",
                        "msg": ("The theme changed the page's shape, not just its "
                                "colours. " + "  ".join(x["msg"] for x in probs[:4])
                                + "  Restyle these without resizing them.")})
                else:
                    result["findings"].append({
                        "level": "ok", "code": "layout-held",
                        "msg": "Type scale and layout match the original."})
        elif layout.get("checked") and layout.get("doc", {}).get("hscroll"):
            result["findings"].append({
                "level": "warn", "code": "hscroll",
                "msg": (f"The page scrolls sideways at "
                        f"{layout['doc'].get('clientW')}px "
                        f"(content is {layout['doc'].get('scrollW')}px wide).")})
        elif layout.get("error"):
            result["findings"].append({
                "level": "warn", "code": "layout-unchecked",
                "msg": f"Layout could not be measured: {layout['error']}"})

        # Promote the preservation finding back to the top. Several checks above
        # insert themselves at index 0, so the one finding that says "this is no
        # longer the application" was ending up beneath notes about focus rings.
        _pres = next((f for f in result["findings"]
                      if f.get("code", "").startswith("app-")
                      or f.get("code") == "preservation-unchecked"), None)
        if _pres:
            result["findings"].remove(_pres)
            result["findings"].insert(0, _pres)

        if vision_fn:
            pal_str = ", ".join(f"{h} ({int(s*100)}%)" for h, s in palette) or "not measured"
            brief_block = (BRIEF_BLOCK.format(brief=brief.strip(), palette=pal_str)
                           if brief.strip() else
                           f"\nNo brief was given, so judge it on its own merits.\n"
                           f"The colours actually measured in this screenshot are: {pal_str}\n")
            prompt = CRITIQUE_PROMPT.format(brief_block=brief_block)
            try:
                b64 = base64.b64encode(Path(desktop["png"]).read_bytes()).decode()
                result["critique"] = (vision_fn(b64, prompt) or "").strip()
            except Exception as e:
                result["critique"] = f"[vision critique failed: {e}]"

        result["ok"] = True
        return result

    # -- formatting --------------------------------------------------------
    @staticmethod
    def as_text(result: dict) -> str:
        """Render the result for a model to read. Deterministic findings go FIRST:
        they are facts, and a model that reads the opinion first anchors on it."""
        if not result.get("ok"):
            return f"[design_review failed: {result.get('error', 'unknown error')}]"
        lines = [f"[DESIGN REVIEW of {Path(result['file']).name}]"]

        shots = [s for s in result.get("shots", []) if s["ok"]]
        if shots:
            lines.append("Rendered: " + ", ".join(f"{s['label']} {s['w']}x{s['h']}" for s in shots))
        pal = result.get("palette") or []
        if pal:
            lines.append("Measured on screen: "
                         + ", ".join(f"{h} {int(s*100)}%" for h, s in pal[:5]))
        if result.get("states"):
            lines.append(result["states"])

        errs = [f for f in result["findings"] if f["level"] == "error"]
        warns = [f for f in result["findings"] if f["level"] != "error"]
        if errs:
            lines.append("\nBROKEN - fix these first:")
            lines += [f"  ! {f['msg']}" for f in errs]
        if warns:
            lines.append("\nChecks:")
            lines += [f"  - {f['msg']}" for f in warns]
        if not errs and not warns:
            lines.append("\nAutomated checks: all clear.")

        if result.get("critique"):
            lines.append("\nWHAT IT LOOKS LIKE (vision model, from the screenshot):")
            lines.append(result["critique"])

        lines.append("\nAct on FIX FIRST and anything under BROKEN, then call "
                     "design_review again on the same file to confirm it improved.")
        return "\n".join(lines)
