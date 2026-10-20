"""Reskin jobs: can this model do it at all, and is the app still there after?

WHY THIS EXISTS
---------------
Asked to reskin RetroVault (185,414 bytes, 113 KB of JavaScript, 144 functions,
196 element ids), five models produced:

    frontend-design-expert  185,414 bytes  byte-identical copy, nothing done
    OBSIDIAN-9B-Coder         5,947 bytes  0 chars of JS, 0 of 196 ids kept
    qwen3:14b                 7,614 bytes  0 chars of JS, 0 of 196 ids kept
    qwen3coder-q3xl           6,209 bytes  0 chars of JS, 0 of 196 ids kept
    qwen3-coder:30b           8,924 bytes  1 function,    0 of 196 ids kept

Four of five threw the entire application away and wrote a ~6 KB brochure --
one of them a landing page advertising "Nintendo 64, Sega Genesis, Atari 2600"
with emoji icons and a 2023 copyright. None of them had ever seen the app.

This was never a taste problem, and no amount of design review could fix it.
185 KB is roughly 56,000 tokens. A whole-file rewrite must hold the source AND
the rewrite, so it needs ~112,000. The installed models offer 8,192 to 32,768.
The job was arithmetically impossible for every one of them, and ND let them
try anyway -- so each model improvised a page from the words "retro vault",
and the design-review loop then critiqued the hover states on something that
did nothing at all.

Two guards, from opposite ends:

  fits_window()          before the run: refuse a job the model cannot hold,
                         and say what would fit instead.
  preservation_report()  after the run: a "reskin" that dropped the app is a
                         failure no matter how it looks.

Pure functions, no model and no network, so both are cheap to test.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "estimate_tokens", "looks_like_reskin", "find_source", "fits_window",
    "too_big_message", "app_facts", "preservation_report",
]

# Measured against Ollama's own prompt_eval_count on this box: dense markup
# runs about 1.9 chars/token, ordinary page HTML about 3.3. Use the HIGHER
# ratio -- it yields the SMALLER token estimate, so the guard only ever fires
# when a job is over budget by a margin that survives the optimistic reading.
_CHARS_PER_TOKEN = 3.3


def estimate_tokens(text_or_len):
    """Rough token count. Deliberately optimistic -- see _CHARS_PER_TOKEN."""
    n = text_or_len if isinstance(text_or_len, int) else len(text_or_len or "")
    return int(n / _CHARS_PER_TOKEN)


# A reskin RE-STYLES something that already exists. That is the whole
# distinction from a build: the output must still be the input.
_RESKIN_VERB = (r"(?:re-?skin|re-?style|re-?theme|re-?design|restyle|reimagine|"
                r"modernise|modernize|face-?lift|new\s+look|fresh\s+coat|"
                r"change\s+the\s+(?:look|theme|style|colou?rs?)|"
                r"apply\s+a\s+\w+\s+(?:theme|skin|style))")
_RESKIN_RE = re.compile(_RESKIN_VERB, re.I)

# "the existing app", "this page", a named .html file -- something is already there.
_EXISTING_RE = re.compile(
    r"(?:existing|current|this|the)\s+(?:app|application|page|site|ui|interface|file)"
    r"|\.html?\b", re.I)

_PATH_RE = re.compile(r"""(?:^|[\s"'`(])((?:[A-Za-z]:[\\/]|\.{0,2}[\\/])[^\s"'`<>|?*]+?\.html?)\b""",
                      re.I)


def looks_like_reskin(text):
    """Is this 'make the thing I already have look different'?"""
    t = (text or "").strip()
    if len(t) < 12:
        return False
    return bool(_RESKIN_RE.search(t)) and bool(_EXISTING_RE.search(t))


def find_source(text, workspace=""):
    """The existing file a reskin is aimed at, if one can be identified.

    Picks the LARGEST existing candidate: a reskin request routinely names both
    the source and the destination, and the destination usually does not exist
    yet -- but when it does (a previous failed attempt left a 6 KB stub behind)
    size is what tells them apart.
    """
    seen, best, best_size = set(), "", -1
    for m in _PATH_RE.finditer(text or ""):
        raw = m.group(1)
        for cand in ([raw] if Path(raw).is_absolute() else
                     ([str(Path(workspace) / raw)] if workspace else []) + [raw]):
            if cand in seen:
                continue
            seen.add(cand)
            p = Path(cand)
            try:
                if p.is_file() and p.stat().st_size > best_size:
                    best, best_size = str(p.resolve()), p.stat().st_size
            except OSError:
                continue
    return best


def fits_window(source_path, num_ctx, whole_file_rewrite=True):
    """Can this model actually do this job? Returns a dict, never raises.

    A whole-file rewrite has to hold the source AND the new version in the same
    window, plus the conversation and the tool results around them. That is the
    calculation nobody was doing.
    """
    out = {"path": str(source_path or ""), "bytes": 0, "source_tokens": 0,
           "needed": 0, "num_ctx": int(num_ctx or 0), "fits": True,
           "headroom": 0.0}
    try:
        out["bytes"] = Path(source_path).stat().st_size
    except OSError:
        return out                      # unknown file: do not block on a guess
    out["source_tokens"] = estimate_tokens(out["bytes"])
    # Rewrite: source in, a similar-sized file out, plus room for the prompt,
    # the transcript and tool framing. Edit: only the source needs to be held.
    out["needed"] = int(out["source_tokens"] * (2.2 if whole_file_rewrite else 1.3)) + 2000
    out["fits"] = out["needed"] <= out["num_ctx"]
    out["headroom"] = round(out["num_ctx"] / out["needed"], 2) if out["needed"] else 0.0
    return out


def too_big_message(fit, model, candidates=(), source_label=""):
    """Explain the refusal in numbers, and name what would actually work.

    Never a bare "cannot do that": the user needs to know by how much, and what
    to do instead.
    """
    name = source_label or Path(fit.get("path") or "the file").name
    kb = fit["bytes"] / 1024.0
    lines = [
        f"I can't do this as a whole-file rewrite — it doesn't fit, and I'd "
        f"rather say so than hand you another gutted page.",
        "",
        f"  {name} is {kb:,.0f} KB, about {fit['source_tokens']:,} tokens.",
        f"  Rewriting it means holding the original AND the new version at "
        f"once — roughly {fit['needed']:,} tokens.",
        f"  {model} has {fit['num_ctx']:,}.",
        "",
        f"Over budget by {fit['needed'] / max(fit['num_ctx'], 1):.1f}x. If it "
        f"ran anyway, the model would silently lose most of the file and "
        f"improvise a replacement from the filename — which is exactly how a "
        f"185 KB app came back as a 6 KB brochure.",
        "",
        "What actually works:",
        "",
        "  1. Reskin as an EDIT, not a rewrite. A theme layer appended before "
        "</head> overrides the styling without touching the app. The model "
        "only reads the palette and class names and only writes new CSS — a "
        "few KB, well inside any window here. The app survives because it is "
        "never rewritten.",
    ]
    roomy = [c for c in (candidates or [])
             if int(c.get("num_ctx") or 0) >= fit["needed"]]
    if roomy:
        lines.append("")
        lines.append("  2. Or use a model that can hold the whole file:")
        for c in roomy:
            lines.append(f"       {c.get('model')} — {int(c['num_ctx']):,} tokens")
    else:
        lines += ["", "  2. No installed model has a window this big, so a "
                      "whole-file rewrite is not on the table at any quality."]
    lines += ["", "Say **reskin as an edit** and I'll do it that way."]
    return "\n".join(lines)


# ── After the run: is it still the app? ──────────────────────────────────────

_SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.I | re.S)
_FUNC_RE = re.compile(r"\bfunction\s+\w+|\w+\s*=\s*\([^)]*\)\s*=>")
_ID_RE = re.compile(r'\bid=["\']([\w-]+)["\']')
_NET_RE = re.compile(r"\bfetch\s*\(|XMLHttpRequest|WebSocket", re.I)


def app_facts(text):
    """Structural signals only. Nothing here is a matter of taste."""
    t = text or ""
    return {
        "bytes": len(t),
        "js_chars": sum(len(m) for m in _SCRIPT_RE.findall(t)),
        "functions": len(_FUNC_RE.findall(t)),
        "ids": set(_ID_RE.findall(t)),
        "network": len(_NET_RE.findall(t)),
    }


def preservation_report(source_text, output_text):
    """Did the reskin keep the application, or replace it?

    Returns {"verdict", "severity", "summary", "kept_pct", ...}. severity
    "error" means the loop must not treat the job as done.
    """
    s, o = app_facts(source_text), app_facts(output_text)
    kept = len(s["ids"] & o["ids"])
    total = len(s["ids"])
    kept_pct = (100.0 * kept / total) if total else 100.0
    js_pct = (100.0 * o["js_chars"] / s["js_chars"]) if s["js_chars"] else 100.0
    size_pct = (100.0 * o["bytes"] / s["bytes"]) if s["bytes"] else 100.0

    r = {"kept_ids": kept, "total_ids": total, "kept_pct": round(kept_pct, 1),
         "js_pct": round(js_pct, 1), "size_pct": round(size_pct, 1),
         "source": s, "output": o}

    if source_text == output_text:
        r.update(verdict="unchanged", severity="error",
                 summary=("The output is byte-identical to the source — nothing "
                          "was reskinned. A copy is not a result."))
    elif total and kept == 0:
        r.update(verdict="replaced", severity="error",
                 summary=(f"This is not a reskin: none of the app's {total} "
                          f"element ids survive, and the file is {size_pct:.0f}% "
                          f"of its original size with {o['js_chars']:,} chars of "
                          f"JavaScript against {s['js_chars']:,}. The application "
                          f"was discarded and replaced with a new page."))
    elif kept_pct < 50 or js_pct < 50:
        r.update(verdict="gutted", severity="error",
                 summary=(f"Most of the app is gone: {kept}/{total} element ids "
                          f"({kept_pct:.0f}%) and {js_pct:.0f}% of the "
                          f"JavaScript remain. A reskin changes how it looks, "
                          f"not what it is."))
    elif kept_pct < 90 or js_pct < 90:
        r.update(verdict="partial", severity="warn",
                 summary=(f"Some of the app was lost: {kept}/{total} ids "
                          f"({kept_pct:.0f}%), {js_pct:.0f}% of the JavaScript. "
                          f"Check nothing working was dropped."))
    else:
        r.update(verdict="preserved", severity="ok",
                 summary=(f"The app is intact: {kept}/{total} element ids and "
                          f"{js_pct:.0f}% of the JavaScript are still there."))
    return r


# ── Reskin as an EDIT ────────────────────────────────────────────────────────
# The whole point: the model never sees the app and never writes the app. It
# sees the STYLE SURFACE -- the custom properties, the class vocabulary, the
# fonts -- and writes only a CSS override layer, which is appended to the file
# it never touched. Output is a few KB instead of 185, so it fits any window
# here, and the application survives by construction.

_TAG_SPAN_RE = re.compile(r"<(script|style)\b[^>]*>(.*?)</\1>", re.I | re.S)
_VAR_RE = re.compile(r"(--[\w-]+)\s*:\s*([^;{}]+)[;}]")
_CLASS_RE = re.compile(r'\bclass=["\']([^"\']+)["\']')
_FONT_RE = re.compile(r"font-family\s*:\s*([^;{}]+)", re.I)
_SELECTOR_RE = re.compile(r"^\s*([.#][\w-][\w\s.#,:>()-]*?)\s*\{", re.M)

ND_LAYER_OPEN = "<!-- ND-THEME:start -->"
ND_LAYER_CLOSE = "<!-- ND-THEME:end -->"


def _markup_spans(html):
    """Character ranges that are INSIDE a <script> or <style> block."""
    return [(m.start(), m.end()) for m in _TAG_SPAN_RE.finditer(html or "")]


def _in_span(pos, spans):
    return any(a < pos < b for a, b in spans)


def injection_point(html):
    """Where an override layer must go: after every author stylesheet.

    Not `</head>`. Measured on the real RetroVault: it has a SECOND <style>
    block at char 57,706 -- in the body, 32,000 chars past </head>. CSS later in
    document order wins at equal specificity, so a theme layer in <head> would
    be silently overridden by that block for every property it also sets, and
    the "reskin" would half-apply with no error anywhere.

    The same file also contains </head>, </body> and </html> a second time each,
    inside a JavaScript string that builds a popup document. Matching those
    would inject the theme into a string literal. Both hazards are solved the
    same way: ignore anything inside a script or style block.

    Returns (index, why). index -1 means append to the end.
    """
    h = html or ""
    spans = _markup_spans(h)
    for tag, why in (("</body>", "before </body>, after every author stylesheet"),
                     ("</html>", "before </html>")):
        for m in re.finditer(re.escape(tag), h, re.I):
            if not _in_span(m.start(), spans):
                return m.start(), why
    return -1, "appended to the end of the file (no closing tag in markup)"


def style_surface(html, budget_chars=6000):
    """What a themer actually needs, small enough to fit in a window.

    NOT the stylesheet. RetroVault's head <style> alone is 25,183 chars (~7,600
    tokens) and would not fit the 8K profile with room to answer. A themer does
    not need every rule -- it needs the vocabulary: the custom properties that
    define the palette, the class names in play, the fonts. That is a few
    hundred tokens and it is the part a reskin actually changes.
    """
    h = html or ""
    css = "\n".join(m.group(2) for m in _TAG_SPAN_RE.finditer(h)
                    if m.group(1).lower() == "style")

    seen, variables = set(), []
    for name, val in _VAR_RE.findall(css):
        if name not in seen:
            seen.add(name)
            variables.append((name, " ".join(val.split())[:60]))

    classes = sorted({c for m in _CLASS_RE.findall(h) for c in m.split() if c})
    ids = sorted(set(_ID_RE.findall(h)))
    fonts = sorted({" ".join(f.split())[:70] for f in _FONT_RE.findall(css)})
    selectors = []
    for s in _SELECTOR_RE.findall(css):
        s = " ".join(s.split())
        if s not in selectors:
            selectors.append(s)

    out = []
    if variables:
        out.append("CSS CUSTOM PROPERTIES (the app's palette — retheme these first):")
        out += [f"  {n}: {v}" for n, v in variables[:60]]
    if fonts:
        out.append("\nFONTS IN USE:")
        out += [f"  {f}" for f in fonts[:12]]
    if classes:
        out.append(f"\nCLASS NAMES ({len(classes)} total, most common first):")
        out.append("  " + ", ".join(classes[:120]))
    if ids:
        out.append(f"\nELEMENT IDS ({len(ids)} total) — these MUST keep working:")
        out.append("  " + ", ".join(ids[:80]))
    if selectors:
        out.append(f"\nEXISTING SELECTORS ({len(selectors)} total, a sample):")
        out.append("  " + ", ".join(selectors[:80]))

    text = "\n".join(out)
    if len(text) > budget_chars:
        text = text[:budget_chars].rsplit("\n", 1)[0] + "\n  …(truncated)"
    return text


THEME_PROMPT = """You are restyling an existing web application. It already works.
You are NOT rebuilding it, and you must NOT output any HTML or JavaScript.

THE BRIEF:
{brief}

THE APP'S STYLE SURFACE (this is all you need — the app itself is 185 KB and is
staying exactly as it is):
{surface}

WRITE ONE CSS BLOCK that will be appended to the END of the document, after
every stylesheet the app already has. Because it comes last, plain rules
override the originals — you rarely need !important.

RULES:
- Output ONLY CSS. No <style> tag, no HTML, no explanation, no code fence.
- Retheme by REDEFINING the custom properties above under :root first. That is
  the highest-leverage change and it reaches everything at once.
- Then add whatever the brief needs that variables cannot express: gradients,
  glows, animations, borders, shadows, backdrop effects.
- Style the real class names listed above. Do not invent class names — an
  invented selector matches nothing and changes nothing.
- Never set `display:none` on anything. Hiding the app is not restyling it.
- CONTRAST IS NOT NEGOTIABLE. Every colour you set is measured in a real
  browser afterwards, and text that drops below WCAG AA is reported as a
  failure. Body text needs 4.5:1 against whatever is actually behind it; large
  or bold text needs 3:1. Two mistakes are made constantly and both are caught:
  darkening a muted/secondary text variable to sit near the background, and
  putting white text on a mid-brightness accent (white on #ff00ff is 3.1:1 and
  fails). If you darken a background, lighten the text with it.
- RESTYLE, DO NOT RESIZE. The rendered type scale and layout are measured
  against the original too. Changing a 20px heading to 60px is a redesign, not
  a reskin — it wraps onto two lines and pushes everything else down. Keep
  font-size, padding and width close to what the app already uses; express the
  theme in colour, glow, border, gradient and animation instead.
- Include hover, focus-visible and disabled states, and honour
  prefers-reduced-motion for anything that animates.
"""


def theme_prompt(html, brief, budget_chars=6000):
    return THEME_PROMPT.format(brief=(brief or "").strip() or "Modernise it.",
                               surface=style_surface(html, budget_chars))


def clean_css(text):
    """Strip whatever wrapper the model put around the CSS.

    Models fence it, tag it, or narrate before it. All three would land as
    literal text inside a <style> block and silently break the sheet from the
    first junk character onwards.
    """
    t = (text or "").strip()
    fence = re.search(r"```(?:css)?\s*(.*?)```", t, re.S | re.I)
    if fence:
        t = fence.group(1).strip()
    t = re.sub(r"</?style[^>]*>", "", t, flags=re.I).strip()
    # Drop any lead-in prose before the first real rule or at-rule.
    m = re.search(r"(^|\n)\s*(?::root\b|@|[.#\w\[*])[^\n]*\{", t)
    if m:
        t = t[m.start():].strip()
    # No brace anywhere means this was never CSS -- it is the model saying
    # something ("I could not do that."). Injecting prose into a <style> block
    # breaks the sheet from the first word on, silently. Refuse it.
    if "{" not in t or "}" not in t:
        return ""
    return t


def apply_theme(html, css, label="ND theme"):
    """Append the override layer. Idempotent: re-theming REPLACES, never stacks.

    Stacking would make each pass depend on the last, so a fix could not undo
    an earlier mistake and the file would grow every round.
    """
    h = html or ""
    # Strip the surrounding newlines too, or every remove/re-add cycle leaves
    # two stray characters behind and the file drifts from the original.
    h = re.sub(r"\n?" + re.escape(ND_LAYER_OPEN) + r".*?"
               + re.escape(ND_LAYER_CLOSE) + r"\n?", "", h, flags=re.S)
    css = clean_css(css)
    if not css:
        return h, "no CSS to apply"
    block = (f"\n{ND_LAYER_OPEN}\n<style data-nd-theme=\"{label}\">\n"
             f"{css}\n</style>\n{ND_LAYER_CLOSE}\n")
    idx, why = injection_point(h)
    if idx < 0:
        return h + block, why
    return h[:idx] + block + h[idx:], why


def has_theme(html):
    return ND_LAYER_OPEN in (html or "")
