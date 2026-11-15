"""The look step: what a person would see, checked after the tests are green.

Tests that pass say the code does what was asked. They do not say a button is cut off at the edge of a TV screen.
Three times a screenshot found what green tests missed (a sign-in screen too tall at 720 and 540, a drawer title
scrolled out of sight, a whole page too big on a real TV). This step takes those screenshots every time, at several
screen sizes, and runs mechanical checks on each: is anything cut off, covered, clipped mid-word, too small to read,
or wider than the screen?

A pack opts in with PACK.json:
    "look": {"driver": "tests/_look.py", "accept": ["text that marks a known, harmless finding", ...]}
and a driver file in its tests (it knows how to start THIS app and reach its screens):
    SIZES   = [(1920, 1080), (1280, 720), (960, 540)]
    start(w, h) -> ctx          start the app and a headless browser of that size; ctx.br is the browser
    SCREENS = [("guide", fn), ("info drawer", fn), ...]    fn(ctx) brings the page to that screen, in order
    stop(ctx)
The browser object needs .js(expression) and .cmd(devtools method, **params) (tests/_t.py's Browser has both).

    python dev/studio_look.py run <app folder> <out folder> [--driver file] [--vision model]   pictures + findings
    python dev/studio_look.py compare <before out> <after out>                   what is new in "after"
studio_pack.py look <workspace> does both against the app as it was (the baseline), so an old app's old warts are
not blamed on the change. A vision model can add a second opinion (--vision <ollama model>); it never decides.
"""
import base64
import importlib.util
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

# One pass over the page. Every finding: {kind, where, why}. Written to be quiet: a finding should be something a
# person would point at. Anything the page hides on purpose (a closed drawer, a menu off screen) is left alone.
AUDIT_JS = r"""
(function(){
  var W = window.innerWidth, H = window.innerHeight, out = [], seen = {};
  function st(e){ return getComputedStyle(e); }
  function where(e){
    var s = e.tagName.toLowerCase() + (e.id ? '#' + e.id : '');
    if(typeof e.className === 'string' && e.className.trim()) s += '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.');
    var t = (e.getAttribute('aria-label') || e.innerText || e.value || '').replace(/\s+/g, ' ').trim().slice(0, 32);
    return s + (t ? ' "' + t + '"' : '');
  }
  function add(kind, e, why){
    var w = where(e), k = kind + '|' + w;
    if(seen[k]) return;
    seen[k] = 1;
    out.push({kind: kind, where: w, why: why});
  }
  function shown(e){
    var r = e.getBoundingClientRect();
    if(r.width < 2 || r.height < 2) return false;
    for(var p = e; p && p.nodeType === 1; p = p.parentElement){
      var c = st(p);
      if(c.display === 'none' || c.visibility === 'hidden' || c.visibility === 'collapse' || parseFloat(c.opacity) < 0.05) return false;
    }
    return true;
  }
  function ownText(e){
    for(var n = e.firstChild; n; n = n.nextSibling) if(n.nodeType === 3 && n.nodeValue.trim().length > 1) return true;
    return false;
  }
  function interactive(e){
    return /^(BUTTON|A|INPUT|SELECT|TEXTAREA)$/.test(e.tagName) || e.hasAttribute('onclick') || e.hasAttribute('tabindex') || e.getAttribute('role') === 'button';
  }
  function fixedAbove(e){
    for(var p = e; p && p.nodeType === 1; p = p.parentElement) if(st(p).position === 'fixed') return true;
    return false;
  }
  // The box an element can be seen through: the screen, cut down by every ancestor that clips. Also says whether
  // something up the tree scrolls (then a part that is out of sight can be brought into sight).
  function clip(e){
    var box = {l: 0, t: 0, r: W, b: H}, scrollsX = false, scrollsY = false, dots = false;
    for(var p = e.parentElement; p && p.nodeType === 1; p = p.parentElement){
      var c = st(p), r = p.getBoundingClientRect();
      var ox = c.overflowX, oy = c.overflowY;
      if(/auto|scroll/.test(ox) && p.scrollWidth > p.clientWidth + 1) scrollsX = true;
      if(/auto|scroll/.test(oy) && p.scrollHeight > p.clientHeight + 1) scrollsY = true;
      if(c.textOverflow === 'ellipsis' || c.webkitLineClamp !== 'none') dots = true;
      if(ox !== 'visible'){ box.l = Math.max(box.l, r.left); box.r = Math.min(box.r, r.right); }
      if(oy !== 'visible'){ box.t = Math.max(box.t, r.top); box.b = Math.min(box.b, r.bottom); }
    }
    var d = document.scrollingElement || document.documentElement;
    if(!fixedAbove(e) && d.scrollHeight > H + 1) scrollsY = true;
    return {box: box, scrollsX: scrollsX, scrollsY: scrollsY, dots: dots};
  }

  var doc = document.scrollingElement || document.documentElement;
  if(doc.scrollWidth > W + 2) out.push({kind: 'page-wider', where: 'the page', why: 'the page is ' + doc.scrollWidth + ' px wide on a ' + W + ' px screen: it scrolls sideways'});

  var all = document.body ? document.body.querySelectorAll('*') : [], n = 0, tiny = {};
  for(var i = 0; i < all.length && n < 4000; i++){
    var e = all[i];
    if(/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|PATH|DEFS|LINEARGRADIENT|STOP|G|CIRCLE|RECT|ELLIPSE|LINE|POLYLINE|TEXT|OPTION|BR)$/i.test(e.tagName)) continue;
    var act = interactive(e), txt = ownText(e);
    if(!act && !txt) continue;
    if(!shown(e)) continue;
    n++;
    var r = e.getBoundingClientRect(), c = st(e), k = clip(e), b = k.box;
    var visW = Math.min(r.right, b.r) - Math.max(r.left, b.l), visH = Math.min(r.bottom, b.b) - Math.max(r.top, b.t);
    if(visW <= 1 || visH <= 1) continue;                      // wholly out of sight: hidden on purpose, or scrolled away
    var cutX = r.width - visW, cutY = r.height - visH;
    if(cutX > 3 && !k.scrollsX && !k.dots && c.textOverflow !== 'ellipsis')
      add('cut-off', e, Math.round(cutX) + ' px of its width is out of sight and nothing scrolls to show it');
    if(cutY > 3 && !k.scrollsY)
      add('cut-off', e, Math.round(cutY) + ' px of its height is out of sight and nothing scrolls to show it');
    if(txt){
      if(/hidden|clip/.test(c.overflowX) && e.scrollWidth > e.clientWidth + 2 && c.textOverflow !== 'ellipsis')
        add('text-clipped', e, 'its text is ' + e.scrollWidth + ' px wide in a ' + e.clientWidth + ' px box and is cut without "..."');
      if(/hidden|clip/.test(c.overflowY) && e.scrollHeight > e.clientHeight + 3 && c.webkitLineClamp === 'none' && c.textOverflow !== 'ellipsis' && e.children.length === 0)
        add('text-clipped', e, 'its text is ' + e.scrollHeight + ' px tall in a ' + e.clientHeight + ' px box: the last lines are cut');
      var fs = parseFloat(c.fontSize);
      if(fs && fs < 10 && (e.innerText || '').trim().length > 2){ var key = Math.round(fs * 10) / 10; if(!tiny[key]) tiny[key] = e; }
    }
    if(act && c.pointerEvents !== 'none' && cutX <= 3 && cutY <= 3){
      var cx = (Math.max(r.left, 0) + Math.min(r.right, W)) / 2, cy = (Math.max(r.top, 0) + Math.min(r.bottom, H)) / 2;
      if(cx > 0 && cy > 0 && cx < W && cy < H){
        var top = document.elementFromPoint(cx, cy);
        if(top && top !== e && !e.contains(top) && !top.contains(e)){
          var layer = top, big = false;
          for(var q = top; q && q.nodeType === 1; q = q.parentElement){
            var qc = st(q), qr = q.getBoundingClientRect();
            if(/fixed|absolute/.test(qc.position) && qr.width * qr.height > 0.5 * W * H){ big = true; break; }
          }
          if(!big) add('covered', e, 'its middle is under ' + where(top) + ': a click or tap would not reach it');
        }
      }
    }
  }
  // A box as wide as the screen that scrolls sideways is the page scrolling sideways under another name.
  var boxes = document.body ? document.body.querySelectorAll('*') : [];
  for(var j = 0; j < boxes.length; j++){
    var s = boxes[j];
    if(s.clientWidth >= W - 2 && s.scrollWidth > s.clientWidth + 2 && /auto|scroll/.test(st(s).overflowX) && shown(s))
      add('page-wider', s, 'this screen-wide box holds ' + s.scrollWidth + ' px of content on a ' + W + ' px screen: it scrolls sideways');
  }
  for(var f in tiny) add('tiny-text', tiny[f], 'text at ' + f + ' px: too small to read from a sofa, and hard on a phone');

  var a = document.activeElement;
  if(a && a !== document.body && a.nodeType === 1 && shown(a)){
    var ar = a.getBoundingClientRect(), ak = clip(a).box;
    if(ar.left < ak.l - 2 || ar.top < ak.t - 2 || ar.right > ak.r + 2 || ar.bottom > ak.b + 2)
      add('focus-out-of-sight', a, 'the highlighted thing is partly or wholly out of sight');
  }
  return JSON.stringify({w: W, h: H, title: document.title, findings: out});
})()
"""

VISION_PROMPT = ("This is a screenshot of one screen of an app, at {w} x {h} pixels. List only layout faults a user would notice: "
                 "anything cut off at an edge, overlapping, unreadably small, misaligned, or text running out of its box. "
                 "One short line per fault, naming where it is. If the screen looks right, answer exactly: nothing wrong.")


def audit_version():
    """Changes when the checks change: pictures taken with other checks cannot be the "before" of a comparison."""
    import hashlib
    return hashlib.md5((AUDIT_JS + f"|passes={PASSES}").encode()).hexdigest()[:10]


PASSES = 2          # every app is walked this many times: a finding counts when EVERY walk shows it (see run)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def key(f):
    """What makes two findings 'the same' across a before and an after run (numbers change, the fault does not)."""
    return f"{f['size']}|{f['screen']}|{f['kind']}|{f['where']}"


def every_not(walks):
    seen, out = set(), []
    for w_ in walks:
        for x in w_["not_reached"]:
            if (x["size"], x["screen"]) not in seen:
                seen.add((x["size"], x["screen"]))
                out.append(x)
    return out


def run(folder, out, vision=None, log=print, driver=None, passes=None):
    """Drive the pack's driver against the app in `folder`. Pictures and look.json go to `out`. The driver is
    tests/_look.py in that folder unless another file is named (a workspace made before its pack had one)."""
    folder, out = Path(folder).resolve(), Path(out).resolve()
    passes = passes or PASSES
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(folder / "tests"))                 # the driver's helpers (_t.py) are the folder's own
    spec = importlib.util.spec_from_file_location("_look", str(Path(driver).resolve() if driver else folder / "tests" / "_look.py"))
    drv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(drv)
    result = None
    walks = []
    for n in range(passes):                                  # the same walk, more than once: a page is not a still picture
        result = {"when": time.strftime("%Y-%m-%d %H:%M"), "folder": str(folder), "audit": audit_version(), "screens": [],
                  "findings": [], "not_reached": []}
        if passes > 1:
            log(f" walk {n + 1} of {passes}")
        for w, h in drv.SIZES:
            size = f"{w}x{h}"
            try:
                ctx = drv.start(w, h)
            except Exception as e:
                result["not_reached"].append({"size": size, "screen": "(start)", "why": str(e)[:300]})
                log(f"  {size}: the app did not start: {str(e)[:200]}")
                continue
            try:
                for name, go in drv.SCREENS:
                    try:
                        ok = go(ctx)
                        if ok is False:
                            raise RuntimeError("the driver could not reach this screen")
                        time.sleep(0.4)
                        data = json.loads(ctx.br.js(AUDIT_JS) or "{}")
                        png = out / size / f"{slug(name)}.png"
                        png.parent.mkdir(parents=True, exist_ok=True)
                        shot = ctx.br.cmd("Page.captureScreenshot", format="png")
                        png.write_bytes(base64.b64decode(shot["data"]))
                        found = [{**f, "size": size, "screen": name} for f in data.get("findings") or []]
                        seen = {"size": size, "screen": name, "png": str(png.relative_to(out)).replace("\\", "/"), "findings": len(found)}
                        if vision:
                            seen["vision"] = ask_vision(vision, png, w, h)
                        result["screens"].append(seen)
                        result["findings"] += found
                        log(f"  {size} {name}: {len(found)} finding(s)")
                    except Exception as e:
                        result["not_reached"].append({"size": size, "screen": name, "why": str(e)[:300]})
                        log(f"  {size} {name}: not reached ({str(e)[:120]})")
            finally:
                try:
                    drv.stop(ctx)
                except Exception:
                    pass
        walks.append(result)
    # A finding counts when EVERY walk shows it. One that comes and goes (a guide that scrolled a few pixels further,
    # a picture still loading) is kept apart as 'unstable': it never counts as new, and it still counts as 'was there
    # before' when this run is the before of a comparison.
    sets = [{key(f) for f in w_["findings"]} for w_ in walks]
    always = set.intersection(*sets)
    every = {}
    for w_ in walks:
        for f_ in w_["findings"]:
            every.setdefault(key(f_), f_)
    result["findings"] = [f_ for k_, f_ in every.items() if k_ in always]
    result["unstable"] = [f_ for k_, f_ in every.items() if k_ not in always]
    result["passes"] = passes
    reached = [{(x["size"], x["screen"]) for x in w_["not_reached"]} for w_ in walks]
    result["not_reached"] = [x for x in every_not(walks) if any((x["size"], x["screen"]) in r_ for r_ in reached)]
    if result["unstable"]:
        log(f" {len(result['unstable'])} finding(s) did not show on every walk and are not counted")
    (out / "look.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def ask_vision(model, png, w, h, url="http://127.0.0.1:11434"):
    """A second opinion from a local vision model. Its answer is shown next to the picture; it never fails a build."""
    try:
        body = {"model": model, "stream": False, "options": {"temperature": 0.1, "num_predict": 400},
                "messages": [{"role": "user", "content": VISION_PROMPT.format(w=w, h=h),
                              "images": [base64.b64encode(Path(png).read_bytes()).decode()]}]}
        req = urllib.request.Request(url + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=600).read())
        return ((r.get("message") or {}).get("content") or "").strip()[:800]
    except Exception as e:
        return f"(the vision model did not answer: {str(e)[:120]})"


def compare(before, after, accept=()):
    """-> (new findings, gone findings, accepted findings). `before` may be None (then everything is new)."""
    old = {key(f) for f in ((before or {}).get("findings") or []) + ((before or {}).get("unstable") or [])}
    now = {key(f): f for f in after.get("findings") or []}
    new, okd = [], []
    for k, f in now.items():
        if k in old:
            continue
        text = f"{f['kind']} {f['where']} {f['why']}"
        (okd if any(a and a in text for a in accept) else new).append(f)
    gone = sorted(old - set(now))
    return new, gone, okd


def report(after, new, gone, accepted, out, before_dir=None, title="The look step"):
    """LOOK.md: findings first, then every picture (with the 'before' picture beside it where there is one)."""
    out = Path(out)
    L = [f"# {title}", "", f"Written {time.strftime('%Y-%m-%d %H:%M')}. Screens: {len(after.get('screens') or [])} "
         f"({', '.join(sorted({s['size'] for s in after.get('screens') or []}))}).", ""]
    if new:
        L += [f"## {len(new)} new finding(s): look at each one", "", "| Size | Screen | What | Where | Why |", "|---|---|---|---|---|"]
        L += [f"| {f['size']} | {f['screen']} | {f['kind']} | `{f['where'].replace('|', '/')}` | {f['why'].replace('|', '/')} |" for f in new]
    else:
        L += ["## No new findings", "", "The mechanical checks found nothing that was not there before. That is not the same as "
              "looking: open the pictures below."]
    if after.get("not_reached"):
        L += ["", "## Screens the driver could not reach", ""] + [f"- {n['size']} {n['screen']}: {n['why']}" for n in after["not_reached"]]
    if gone:
        L += ["", f"## {len(gone)} finding(s) from before are gone", ""] + [f"- {g.replace('|', ' / ')}" for g in gone[:30]]
    if accepted:
        L += ["", f"## {len(accepted)} accepted (listed in the pack's look.accept)", ""] + [f"- {f['size']} {f['screen']}: {f['kind']} `{f['where']}`" for f in accepted[:30]]
    known = len(after.get("findings") or []) - len(new) - len(accepted)
    if known > 0:
        L += ["", f"({known} finding(s) were already there before this change and are not listed.)"]
    L += ["", "## Pictures", ""]
    for s in after.get("screens") or []:
        L += [f"### {s['size']} - {s['screen']}", ""]
        if before_dir and (Path(before_dir) / s["png"]).is_file():
            L += [f"Before: `{Path(before_dir) / s['png']}`", ""]
        L += [f"![{s['screen']}]({s['png']})", ""]
        if s.get("vision"):
            L += ["Second opinion (vision model, not a verdict): " + s["vision"].replace("\n", " / "), ""]
    (out / "LOOK.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return out / "LOOK.md"


def main(a):
    if len(a) >= 3 and a[0] == "run":
        vision = a[a.index("--vision") + 1] if "--vision" in a else None
        driver = a[a.index("--driver") + 1] if "--driver" in a else None
        r = run(a[1], a[2], vision, driver=driver)
        print(f"{len(r['screens'])} screens, {len(r['findings'])} findings, {len(r['not_reached'])} not reached -> {Path(a[2]) / 'look.json'}")
    elif len(a) >= 3 and a[0] == "compare":
        before = json.loads((Path(a[1]) / "look.json").read_text(encoding="utf-8"))
        after = json.loads((Path(a[2]) / "look.json").read_text(encoding="utf-8"))
        new, gone, okd = compare(before, after)
        print(report(after, new, gone, okd, a[2], a[1]))
        print(f"{len(new)} new, {len(gone)} gone")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
