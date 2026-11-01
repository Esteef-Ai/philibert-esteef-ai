"""Word (.docx) and PDF files from one document, with a teacher's house rules built in.

A document is a title plus blocks, written as plain Markdown (what a model writes well):

    # Heading            ## Smaller heading
    A paragraph, with **bold** and *italic*.
    - a bullet           1. a numbered item
    | a | table |        (the first row is the header; |---| lines are skipped)
    [space 4]            open writing space, about 4 lines tall (no ruled lines)
    [page]               a page break

    parse(md) -> [block]                 blocks: heading / para / list / table / space / page
    tidy(blocks, kind) -> (blocks, fixes)  kind "student" applies the student rules (below)
    docx_bytes(title, blocks) -> bytes   a real Word file (opens in Word and Google Docs)
    html(title, blocks) -> str           the same document as a printable page
    pdf(title, blocks, out_path, chrome) the page printed to PDF by a Chromium (Philibert's own)
    build(title, md, kind, folder, name, chrome) -> {docx, pdf, fixes}

Both files come from the same blocks, so the Word file and the PDF always say the same thing.

House rules (every document): Times New Roman, 12 pt body text, black and gray only, no
headers, footers or footnotes, US Letter with 1-inch margins, and every table exactly the
width between the margins (fixed layout: a column can wrap, never spill past the edge).
Student copies also lose what does not belong on them: "Part 1" labels (the heading keeps
its words), printed objectives, timing and time-used prompts, and checkboxes.

Stdlib only: the .docx is written as its own XML, so an install needs nothing new.
"""
import html as _html
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

FONT = "Times New Roman"
BODY_PT = 12
TITLE_PT = 14
PAGE_W, PAGE_H, MARGIN = 12240, 15840, 1440          # twips: US Letter, 1-inch margins
TEXT_W = PAGE_W - 2 * MARGIN                          # 9360 twips = 6.5 in between the margins
CELL_PAD = 100                                        # twips of padding inside each table cell
GRAY = "808080"

# ---------------------------------------------------------------------------
# Markdown -> blocks
# ---------------------------------------------------------------------------
_SPACE = re.compile(r"^\[\s*space(?:\s+(\d+))?\s*\]$", re.I)
_PAGE = re.compile(r"^\[\s*page(?:\s*break)?\s*\]$", re.I)
_RULE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def _cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


_SPACE_IN = re.compile(r"\s*\[\s*space(?:\s+(\d+))?\s*\]\s*", re.I)


def parse(md):
    """Markdown in the small dialect above -> a list of blocks. A [space N] written at the
    end of a line or list item (models do: "Un día [space 4]") becomes writing space after
    it; a numbered list split by one carries on with its numbers."""
    blocks = []
    for b in _parse(md):
        if b["type"] == "para" and _SPACE_IN.search(b["text"]):
            n = max(int(x or 3) for x in _SPACE_IN.findall(b["text"]))
            text = _SPACE_IN.sub(" ", b["text"]).strip()
            if text:
                blocks.append({"type": "para", "text": text})
            blocks.append({"type": "space", "lines": max(1, min(30, n))})
        elif b["type"] == "list" and any(_SPACE_IN.search(i) for i in b["items"]):
            start, cur = b.get("start", 1), []
            for k, it in enumerate(b["items"]):
                hit = _SPACE_IN.findall(it)
                cur.append(_SPACE_IN.sub(" ", it).strip())
                if hit:
                    blocks.append({**b, "items": cur, "start": start})
                    blocks.append({"type": "space", "lines": max(1, min(30, max(int(x or 3) for x in hit)))})
                    start += len(cur)
                    cur = []
            if cur:
                blocks.append({**b, "items": cur, "start": start})
        elif b["type"] == "table":
            b["rows"] = [[_SPACE_IN.sub(" ", c).strip() for c in r] for r in b["rows"]]
            blocks.append(b)
        else:
            blocks.append(b)
    return blocks


def _parse(md):
    blocks, para, table = [], [], None

    def end_para():
        if para:
            blocks.append({"type": "para", "text": " ".join(para)})
            para.clear()

    def end_table():
        nonlocal table
        if table:
            blocks.append({"type": "table", "rows": table})
        table = None

    for raw in str(md or "").replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        s = line.strip()
        if s.startswith("|") and s.count("|") >= 2:
            end_para()
            if _RULE.match(s):
                continue
            table = (table or []) + [_cells(s)]
            continue
        end_table()
        if not s:
            end_para()
            continue
        if s.startswith("```"):
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            end_para()
            blocks.append({"type": "heading", "level": min(len(m.group(1)), 3), "text": m.group(2).strip().strip("#").strip()})
            continue
        if _SPACE.match(s):
            end_para()
            blocks.append({"type": "space", "lines": max(1, min(30, int(_SPACE.match(s).group(1) or 3)))})
            continue
        if _PAGE.match(s):
            end_para()
            blocks.append({"type": "page"})
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):        # a Markdown rule: nothing on paper
            end_para()
            continue
        m = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", s)
        if m:
            end_para()
            ordered = m.group(1)[0].isdigit()
            last = blocks[-1] if blocks else None
            if last and last["type"] == "list" and last["ordered"] == ordered:
                last["items"].append(m.group(2))
            else:                                  # a numbered list keeps the number it starts at (6. after 1-5)
                blocks.append({"type": "list", "ordered": ordered, "items": [m.group(2)],
                               "start": int(re.sub(r"\D", "", m.group(1))) if ordered else 1})
            continue
        para.append(s)
    end_para()
    end_table()
    return blocks


# ---------------------------------------------------------------------------
# house rules
# ---------------------------------------------------------------------------
_PART = re.compile(r"^\s*(part|section|step)\s+([0-9]+|[ivx]+|one|two|three|four|five|[a-e])\b\s*[:.\-–—]?\s*", re.I)
_OBJECTIVE = re.compile(r"^\s*(\*\*)?\s*(learning\s+)?(objectives?|outcomes?|goals?|i\s+can|students?\s+will\s+be\s+able)\b", re.I)
# a paragraph is only an objective when it says so ("Objective: ...") - "Goals scored..." is not
_OBJECTIVE_PARA = re.compile(r"^\s*(\*\*)?\s*(learning\s+)?(objectives?|outcomes?|goals?)\s*(\*\*)?\s*[:\-–]|"
                             r"^\s*(\*\*)?\s*(students?\s+will\s+be\s+able|by\s+the\s+end\s+of\s+(this|the)\s+(lesson|class))", re.I)
_TIMING = re.compile(r"(\b(time\s+(used|spent|started|finished)|tiempo\s+usado|start(ed)?\s+time|end\s+time|finish(ed)?\s+time|"
                     r"estimated\s+time|time\s*:)|\(\s*\d+\s*(-\s*\d+\s*)?(min|mins|minutes)\s*\)|"
                     r"^\s*\d+\s*(-\s*\d+\s*)?(min|mins|minutes)\b)", re.I)
# teacher-only material that models put on student pages anyway (measured 2026-10-31: the 8B
# ended a worksheet with "Answer Key (for teacher use only)")
_TEACHER_ONLY = re.compile(r"^\s*(\*\*)?\s*(answer\s*key|answers|key\s*:|solutions?|teacher'?s?\s+(notes?|copy|key|guide)|"
                           r"for\s+the\s+teacher|notes?\s+for\s+(the\s+)?teacher)\b", re.I)
_BOX = re.compile(r"[☐☑☒□▢◻❏]|\[\s?[xX ]?\s?\]")


def _clean_text(t):
    return re.sub(r"\s{2,}", " ", _BOX.sub("", t)).strip()


def tidy(blocks, kind="student"):
    """The blocks with the house rules applied, and a list of what was changed."""
    if kind != "student":
        return blocks, []
    out, fixes = [], []
    skip_section = False                       # under an "Objectives" heading: drop until the next heading
    for b in blocks:
        b = dict(b)
        t = b["type"]
        if t == "heading":
            text = b["text"]
            if _OBJECTIVE.match(text):
                skip_section = True
                fixes.append(f"took the objectives section off the student copy ({text})")
                continue
            if _TEACHER_ONLY.match(text):
                skip_section = True
                fixes.append(f"took the answer key / teacher notes off the student copy ({text})")
                continue
            if _TIMING.search(text) and not _PART.match(text):
                stripped = _TIMING.sub("", text).strip(" -:–—()")
                if stripped:
                    fixes.append(f"took the timing out of the heading \"{text}\"")
                    text = stripped
            skip_section = False
            if _PART.match(text):
                new = _PART.sub("", text).strip()
                new = _TIMING.sub("", new).strip(" -:–—()")
                if not new:
                    fixes.append(f"dropped the heading \"{text}\" (a bare Part label)")
                    continue
                fixes.append(f"\"{text}\" is now \"{new}\" (no Part labels)")
                text = new
            b["text"] = text
            out.append(b)
            continue
        if skip_section:
            continue
        if t == "para":
            text = b["text"]
            if _OBJECTIVE_PARA.match(text):
                fixes.append("took a printed objective off the student copy")
                continue
            if _TEACHER_ONLY.match(text) and len(_plain(text)) < 90:
                skip_section = True          # a bold "Answer Key:" line starts the teacher's part
                fixes.append(f"took the answer key / teacher notes off the student copy ({_plain(text)})")
                continue
            if _TIMING.search(text):
                fixes.append(f"took a timing line off the student copy (\"{text[:50]}\")")
                continue
            if _BOX.search(text):
                fixes.append("took the checkboxes out")
                text = _clean_text(text)
            if _PART.match(text) and len(text) < 80:
                text = _PART.sub("", text).strip()
                fixes.append("took a Part label out")
            if text:
                b["text"] = text
                out.append(b)
            continue
        if t == "list":
            items = []
            for it in b["items"]:
                if _TIMING.search(it):
                    fixes.append(f"took a timing item off the student copy (\"{it[:50]}\")")
                    continue
                if _BOX.search(it):
                    fixes.append("took the checkboxes out")
                    it = _clean_text(it)
                if it:
                    items.append(it)
            if items:
                b["items"] = items
                out.append(b)
            continue
        if t == "table":
            rows = []
            for r in b["rows"]:
                if any(_TIMING.search(c) for c in r if c):
                    fixes.append("took a timing row out of a table")
                    continue
                rows.append([_clean_text(c) if _BOX.search(c) else c for c in r])
            if rows:
                b["rows"] = rows
                out.append(b)
            continue
        out.append(b)
    seen, uniq = set(), []
    for f in fixes:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    return out, uniq


def col_widths(rows, total=TEXT_W):
    """Column widths (twips) that always add up to exactly `total`: by how much each
    column has to say, with every column at least a fair minimum."""
    n = max(len(r) for r in rows) if rows else 1
    weight = []
    for c in range(n):
        lens = [len(_plain(r[c])) if c < len(r) else 0 for r in rows]
        longest = max(lens) if lens else 0
        avg = sum(lens) / max(1, len(lens))
        weight.append(max(4.0, min(60.0, 0.6 * avg + 0.4 * min(longest, 60))))
    floor = total // (n * 3) if n > 1 else total
    raw = [total * w / sum(weight) for w in weight]
    short = [max(floor, int(x)) for x in raw]
    over = sum(short) - total
    while over > 0:                            # take the excess from the widest columns
        i = max(range(n), key=lambda k: short[k])
        cut = min(over, short[i] - floor)
        if cut <= 0:
            break
        short[i] -= cut
        over -= cut
    short[-1] += total - sum(short)            # rounding: the last column takes the remainder
    return short


# ---------------------------------------------------------------------------
# inline **bold** / *italic*
# ---------------------------------------------------------------------------
_INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|__[^_]+__)")


def _runs(text):
    out = []
    for part in _INLINE.split(text or ""):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append((part[2:-2], True, False))
        elif part.startswith("__") and part.endswith("__") and len(part) > 4:
            out.append((part[2:-2], True, False))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append((part[1:-1], False, True))
        else:
            out.append((part, False, False))
    return out


def _plain(text):
    return "".join(t for t, _, _ in _runs(text))


# ---------------------------------------------------------------------------
# .docx
# ---------------------------------------------------------------------------
def _x(s):
    return _html.escape(str(s), quote=True)


def _r(text, bold=False, italic=False, size=None):
    props = ""
    if bold:
        props += "<w:b/>"
    if italic:
        props += "<w:i/>"
    if size:
        props += f'<w:sz w:val="{size * 2}"/><w:szCs w:val="{size * 2}"/>'
    return (f"<w:r>{'<w:rPr>' + props + '</w:rPr>' if props else ''}"
            f'<w:t xml:space="preserve">{_x(text)}</w:t></w:r>')


def _p(text="", style=None, bold=False, size=None, keep=False, numid=None, align=None, after=None, page_before=False):
    ppr = ""
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if keep:
        ppr += "<w:keepNext/>"
    if page_before:
        ppr += "<w:pageBreakBefore/>"
    if numid is not None:
        ppr += f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{numid}"/></w:numPr>'
    if after is not None:
        ppr += f'<w:spacing w:after="{after}"/>'
    if align:
        ppr += f'<w:jc w:val="{align}"/>'
    runs = "".join(_r(t, bold or b, i, size) for t, b, i in _runs(text))
    return f"<w:p>{'<w:pPr>' + ppr + '</w:pPr>' if ppr else ''}{runs}</w:p>"


def _table(rows):
    n = max(len(r) for r in rows)
    widths = col_widths(rows)
    border = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="{GRAY}"/>'
                     for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    x = ('<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblInd w:w="0" w:type="dxa"/>'
         '<w:tblBorders>%s</w:tblBorders><w:tblLayout w:type="fixed"/>'
         '<w:tblCellMar><w:left w:w="%d" w:type="dxa"/><w:right w:w="%d" w:type="dxa"/></w:tblCellMar>'
         '<w:tblLook w:val="0000"/></w:tblPr><w:tblGrid>%s</w:tblGrid>'
         % (TEXT_W, border, CELL_PAD, CELL_PAD, "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)))
    for ri, r in enumerate(rows):
        x += "<w:tr><w:trPr><w:cantSplit/>" + ("<w:tblHeader/>" if ri == 0 and len(rows) > 1 else "") + "</w:trPr>"
        for c in range(n):
            text = r[c] if c < len(r) else ""
            x += (f'<w:tc><w:tcPr><w:tcW w:w="{widths[c]}" w:type="dxa"/></w:tcPr>'
                  + _p(text, bold=(ri == 0 and len(rows) > 1), after=0) + "</w:tc>")
        x += "</w:tr>"
    return x + "</w:tbl>" + _p("", after=0)


def docx_bytes(title, blocks):
    body, nums = [], []
    if title:
        body.append(_p(title, style="Title"))
    page_next = False
    for b in blocks:
        t = b["type"]
        if t == "page":
            page_next = True
            continue
        if t == "heading":
            body.append(_p(b["text"], style=f"Heading{b.get('level', 1)}", keep=True, page_before=page_next))
        elif t == "para":
            body.append(_p(b["text"], page_before=page_next))
        elif t == "list":
            nums.append((b["ordered"], b.get("start", 1)))
            nid = len(nums)
            for i, it in enumerate(b["items"]):
                body.append(_p(it, style="ListParagraph", numid=nid, page_before=page_next and i == 0))
        elif t == "table":
            if page_next:
                body.append(_p("", page_before=True, after=0))
            body.append(_table(b["rows"]))
        elif t == "space":
            for i in range(b.get("lines", 3)):
                body.append(_p("", after=0, page_before=page_next and i == 0))
        page_next = False
    sect = (f'<w:sectPr><w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}"/>'
            f'<w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" '
            f'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>')
    W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
         'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {W}><w:body>'
                + "".join(body) + sect + "</w:body></w:document>")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
            '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            '</Types>'),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            '</Relationships>'),
        "word/_rels/document.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
            '</Relationships>'),
        "word/document.xml": document,
        "word/styles.xml": _styles(),
        "word/numbering.xml": _numbering(nums),
        "word/settings.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:defaultTabStop w:val="720"/><w:compat><w:compatSetting w:name="compatibilityMode" '
            'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>'),
        "docProps/core.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{_x(title or "")}</dc:title><dc:creator>Philibert Yo Teach</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>'),
        "docProps/app.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            '<Application>Philibert</Application></Properties>'),
    }
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("[Content_Types].xml", "_rels/.rels", "word/_rels/document.xml.rels", "word/document.xml",
                     "word/styles.xml", "word/numbering.xml", "word/settings.xml", "docProps/core.xml", "docProps/app.xml"):
            z.writestr(name, files[name])
    return buf.getvalue()


def _styles():
    def style(sid, name, size, bold=False, keep=False, before=0, after=120, based="Normal"):
        return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/>'
                f'<w:basedOn w:val="{based}"/><w:next w:val="Normal"/><w:qFormat/>'
                f'<w:pPr>{"<w:keepNext/>" if keep else ""}<w:spacing w:before="{before}" w:after="{after}"/></w:pPr>'
                f'<w:rPr>{"<w:b/><w:bCs/>" if bold else ""}<w:sz w:val="{size * 2}"/><w:szCs w:val="{size * 2}"/></w:rPr></w:style>')
    rfonts = f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:eastAsia="{FONT}" w:cs="{FONT}"/>'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:docDefaults><w:rPrDefault><w:rPr>{rfonts}<w:color w:val="000000"/>'
            f'<w:sz w:val="{BODY_PT * 2}"/><w:szCs w:val="{BODY_PT * 2}"/><w:lang w:val="en-US"/></w:rPr></w:rPrDefault>'
            '<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/>'
            f'<w:rPr>{rfonts}<w:color w:val="000000"/><w:sz w:val="{BODY_PT * 2}"/></w:rPr></w:style>'
            + style("Title", "Title", TITLE_PT, bold=True, keep=True, after=240)
            + style("Heading1", "heading 1", BODY_PT, bold=True, keep=True, before=240, after=120)
            + style("Heading2", "heading 2", BODY_PT, bold=True, keep=True, before=180, after=80)
            + style("Heading3", "heading 3", BODY_PT, bold=True, keep=True, before=120, after=60)
            + '<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/>'
              '<w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="60"/><w:ind w:left="720"/></w:pPr></w:style>'
            '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/>'
            '<w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/>'
            f'<w:left w:w="{CELL_PAD}" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="{CELL_PAD}" w:type="dxa"/>'
            '</w:tblCellMar></w:tblPr></w:style></w:styles>')


def _numbering(lists):
    """One numbering definition per list, so each numbered list starts again at 1."""
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    abstract, nums = [], []
    for i, (ordered, start) in enumerate(lists, start=1):
        fmt, text = ("decimal", "%1.") if ordered else ("bullet", "•")
        abstract.append(f'<w:abstractNum w:abstractNumId="{i}"><w:multiLevelType w:val="singleLevel"/>'
                        f'<w:lvl w:ilvl="0"><w:start w:val="{max(1, int(start or 1))}"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/>'
                        '<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr>'
                        f'<w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}"/></w:rPr></w:lvl></w:abstractNum>')
        nums.append(f'<w:num w:numId="{i}"><w:abstractNumId w:val="{i}"/></w:num>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:numbering {W}>'
            + "".join(abstract) + "".join(nums) + "</w:numbering>")


# ---------------------------------------------------------------------------
# HTML -> PDF
# ---------------------------------------------------------------------------
def _inline_html(text):
    out = ""
    for t, b, i in _runs(text):
        s = _html.escape(t)
        if b:
            s = f"<b>{s}</b>"
        if i:
            s = f"<i>{s}</i>"
        out += s
    return out


def html(title, blocks):
    tw = TEXT_W / 1440                                    # inches
    parts = [f"<h1 class='title'>{_inline_html(title)}</h1>"] if title else []
    page_next = False
    for b in blocks:
        t = b["type"]
        cls = " class='pb'" if page_next else ""
        if t == "page":
            page_next = True
            continue
        if t == "heading":
            lv = b.get("level", 1) + 1
            parts.append(f"<h{lv}{cls}>{_inline_html(b['text'])}</h{lv}>")
        elif t == "para":
            parts.append(f"<p{cls}>{_inline_html(b['text'])}</p>")
        elif t == "list":
            tag = "ol" if b["ordered"] else "ul"
            if b["ordered"] and b.get("start", 1) > 1:
                cls += f" start='{int(b['start'])}'"
            parts.append(f"<{tag}{cls}>" + "".join(f"<li>{_inline_html(i)}</li>" for i in b["items"]) + f"</{tag}>")
        elif t == "table":
            widths = col_widths(b["rows"])
            n = len(widths)
            head = len(b["rows"]) > 1
            rows = ""
            for ri, r in enumerate(b["rows"]):
                tag = "th" if head and ri == 0 else "td"
                rows += "<tr>" + "".join(f"<{tag}>{_inline_html(r[c] if c < len(r) else '')}</{tag}>" for c in range(n)) + "</tr>"
            cols = "".join(f"<col style='width:{w / TEXT_W * 100:.3f}%'>" for w in widths)
            parts.append(f"<table{cls}><colgroup>{cols}</colgroup>{rows}</table>")
        elif t == "space":
            parts.append(f"<div class='space{' pb' if page_next else ''}' style='height:{b.get('lines', 3) * 1.45:.2f}em'></div>")
        page_next = False
    return ("<!doctype html><html><head><meta charset='utf-8'><title>" + _html.escape(title or "") + "</title><style>"
            f"@page{{size:letter;margin:1in}}"
            f"html,body{{margin:0;padding:0;background:#fff;color:#000}}"
            f"body{{font-family:'{FONT}',Times,serif;font-size:{BODY_PT}pt;line-height:1.32;width:{tw}in}}"
            f"h1.title{{font-size:{TITLE_PT}pt;margin:0 0 12pt}}"
            f"h2,h3,h4{{font-size:{BODY_PT}pt;margin:12pt 0 6pt;break-after:avoid;page-break-after:avoid}}"
            "p{margin:0 0 6pt}ul,ol{margin:0 0 6pt;padding-left:.5in}li{margin:0 0 3pt}"
            "table{width:100%;max-width:100%;table-layout:fixed;border-collapse:collapse;margin:0 0 8pt}"
            f"th,td{{border:.5pt solid #{GRAY};padding:2pt {CELL_PAD / 20:.0f}pt;text-align:left;vertical-align:top;"
            "overflow-wrap:anywhere;word-break:break-word}"
            "th{font-weight:bold}tr{break-inside:avoid;page-break-inside:avoid}"
            ".pb{break-before:page;page-break-before:always}"
            "</style></head><body>" + "".join(parts) + "</body></html>")


def pdf(title, blocks, out_path, chrome):
    """Print the page to `out_path` with a Chromium-family browser. Returns "" or the error."""
    if not chrome or not Path(chrome).exists():
        return "no browser to print with"
    tmp = Path(tempfile.mkdtemp(prefix="ndpdf"))
    try:
        page = tmp / "doc.html"
        page.write_text(html(title, blocks), encoding="utf-8")
        out = Path(out_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               f"--user-data-dir={tmp / 'profile'}", "--no-pdf-header-footer", "--print-to-pdf-no-header",
               f"--print-to-pdf={out}", page.as_uri()]
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90, creationflags=flags)
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"printing failed: {e}"
        # Edge on Windows can hand the job to a helper and return before the file is written
        # (measured 2026-10-31): wait until the PDF is there and has stopped growing
        import time
        last, end = -1, time.time() + 45
        while time.time() < end:
            size = out.stat().st_size if out.exists() else -1
            if size > 400 and size == last:
                break
            last = size
            time.sleep(0.5)
        if not out.exists() or out.stat().st_size < 400 or not out.read_bytes()[:5] == b"%PDF-":
            return "printing made no PDF"
        return ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def pdf_pages(path):
    """How many pages a PDF has (a rough count from its page objects)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return 0
    return len(re.findall(rb"/Type\s*/Page(?!s)", data))


def safe_name(s, limit=80):
    s = re.sub(r"[^\w\- ]+", "", str(s or ""), flags=re.UNICODE).strip()
    return re.sub(r"[\s]+", "_", s)[:limit] or "Document"


def build(title, md, kind, folder, name, chrome=""):
    """Write <folder>/<name>.docx and .pdf from Markdown. kind: "student" or "teacher"."""
    blocks, fixes = tidy(parse(md), kind)
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    base = safe_name(name, 150)
    docx = folder / f"{base}.docx"
    docx.write_bytes(docx_bytes(title, blocks))
    out = {"docx": str(docx), "pdf": "", "fixes": fixes, "pdf_error": ""}
    err = pdf(title, blocks, folder / f"{base}.pdf", chrome)
    if err:
        out["pdf_error"] = err
    else:
        out["pdf"] = str(folder / f"{base}.pdf")
        out["pages"] = pdf_pages(out["pdf"])
    return out
