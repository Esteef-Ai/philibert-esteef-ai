/* Small, safe Markdown for Philibert's notes (the notes panel and the Notes app).
 *
 * Everything is HTML-escaped first; only the patterns below become markup, so a
 * note can never inject a script. Covers what notes actually use: front matter,
 * headings, bold / italic / strike / code, lists, task lists (- [ ] / - [x]),
 * quotes, rules, code blocks, simple tables, #tags, [[wikilinks]] (with |alias
 * and #heading), ![[embeds]] (shown as links) and [text](https://...) links.
 *
 *   PhilMD.render(src) -> html     task boxes carry data-line = source line index
 *   PhilMD.esc(s)
 */
(function () {
  "use strict";

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function inline(t) {
    // t is already escaped
    var codes = [];
    t = t.replace(/`([^`]+)`/g, function (_, c) { codes.push(c); return "\u0000" + (codes.length - 1) + "\u0000"; });
    t = t
      .replace(/!?\[\[([^\]]+)\]\]/g, function (_, inner) {
        var target = inner.split("|")[0];
        var label = inner.indexOf("|") >= 0 ? inner.split("|").slice(1).join("|") : target.split("#")[0] || target;
        return '<a class="wl" data-note="' + target + '">' + label + "</a>";
      })
      .replace(/\[([^\]]+)\]\(((?:https?:\/\/|mailto:)[^)\s]+)\)/g,
               '<a class="ext" href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/__([^_]+)__/g, "<b>$1</b>")
      .replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, "$1<i>$2</i>")
      .replace(/(^|[^\w])_([^_\s][^_]*)_(?!\w)/g, "$1<i>$2</i>")
      .replace(/~~([^~]+)~~/g, "<s>$1</s>")
      .replace(/==([^=]+)==/g, "<mark>$1</mark>")
      .replace(/(^|\s)#([A-Za-z][\w\-\/]*)/g, '$1<span class="tag">#$2</span>');
    return t.replace(/\u0000(\d+)\u0000/g, function (_, i) { return "<code>" + codes[+i] + "</code>"; });
  }

  function frontmatter(src) {
    var m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(src);
    if (!m) return { props: [], body: src, lines: 0 };
    var props = [];
    m[1].split(/\r?\n/).forEach(function (l) {
      var kv = /^([\w\- ]+):\s*(.*)$/.exec(l);
      if (kv && kv[2].trim()) props.push([kv[1].trim(), kv[2].trim().replace(/^\[|\]$/g, "")]);
    });
    return { props: props, body: src.slice(m[0].length), lines: m[0].split(/\n/).length - 1 };
  }

  function render(src) {
    var fm = frontmatter(String(src || ""));
    // %% comments %% are hidden, as in Obsidian; their newlines stay so line numbers hold
    var lines = fm.body.replace(/%%[\s\S]*?%%/g, function (c) { return c.replace(/[^\n]/g, ""); }).split(/\r?\n/);
    var out = [], list = null, inCode = false, quote = false, table = null, para = [];

    // lines next to each other are one paragraph with line breaks, as in Obsidian
    function closePara() { if (para.length) { out.push("<p>" + para.join("<br>") + "</p>"); para = []; } }
    function closeList() { if (list) { out.push("</" + list + ">"); list = null; } }
    function closeQuote() { if (quote) { out.push("</blockquote>"); quote = false; } }
    function closeTable() {
      if (!table) return;
      var h = "<table><thead><tr>" + table.head.map(function (c) { return "<th>" + inline(esc(c)) + "</th>"; }).join("") +
              "</tr></thead><tbody>" + table.rows.map(function (r) {
                return "<tr>" + r.map(function (c) { return "<td>" + inline(esc(c)) + "</td>"; }).join("") + "</tr>";
              }).join("") + "</tbody></table>";
      out.push(h);
      table = null;
    }
    function cells(l) { return l.trim().replace(/^\||\|$/g, "").split("|").map(function (c) { return c.trim(); }); }

    for (var n = 0; n < lines.length; n++) {
      var line = lines[n], srcLine = n + fm.lines;
      var plain = line.trim() && !/^\s*(```|\||[-*+]\s|\d+[.)]\s|>|#{1,6}\s)/.test(line) &&
                  !/^\s*([-*_])(\s*\1){2,}\s*$/.test(line);
      if (!plain && !inCode) closePara();
      if (/^\s*```/.test(line)) {
        closeList(); closeQuote(); closeTable();
        out.push(inCode ? "</code></pre>" : "<pre><code>");
        inCode = !inCode;
        continue;
      }
      if (inCode) { out.push(esc(line)); continue; }

      if (/^\s*\|.*\|\s*$/.test(line)) {
        if (!table && n + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[n + 1])) {
          closeList(); closeQuote();
          table = { head: cells(line), rows: [] };
          n++;                                     // skip the |---| row
          continue;
        }
        if (table) { table.rows.push(cells(line)); continue; }
      } else closeTable();

      var task = /^\s*[-*+]\s+\[([ xX])\]\s+(.*)$/.exec(line);
      var ul = /^\s*[-*+]\s+(.*)$/.exec(line);
      var ol = /^\s*\d+[.)]\s+(.*)$/.exec(line);
      var q = /^>\s?(.*)$/.exec(line);
      var h = /^(#{1,6})\s+(.*)$/.exec(line);

      if (task || ul) {
        closeQuote();
        if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
        var depth = Math.min(4, Math.floor(/^\s*/.exec(line)[0].replace(/\t/g, "  ").length / 2));
        if (task) {
          var done = task[1] !== " ";
          out.push('<li class="task' + (done ? " done" : "") + '" style="margin-left:' + depth * 18 + 'px">' +
                   '<input type="checkbox" data-line="' + srcLine + '"' + (done ? " checked" : "") + "> " +
                   "<span>" + inline(esc(task[2])) + "</span></li>");
        } else {
          out.push('<li style="margin-left:' + depth * 18 + 'px">' + inline(esc(ul[1])) + "</li>");
        }
        continue;
      }
      if (ol) {
        closeQuote();
        if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; }
        out.push("<li>" + inline(esc(ol[1])) + "</li>");
        continue;
      }
      closeList();
      if (q) {
        if (!quote) { out.push("<blockquote>"); quote = true; }
        out.push("<p>" + inline(esc(q[1])) + "</p>");
        continue;
      }
      closeQuote();
      if (h) { out.push("<h" + h[1].length + ">" + inline(esc(h[2])) + "</h" + h[1].length + ">"); continue; }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push("<hr>"); continue; }
      if (line.trim()) para.push(inline(esc(line)));
    }
    closePara(); closeList(); closeQuote(); closeTable();
    if (inCode) out.push("</code></pre>");

    var props = fm.props.length ? '<div class="props">' + fm.props.map(function (p) {
      return '<span class="prop"><b>' + esc(p[0]) + "</b> " + inline(esc(p[1])) + "</span>";
    }).join("") + "</div>" : "";
    return props + out.join("\n");
  }

  window.PhilMD = { render: render, esc: esc, frontmatter: frontmatter };
})();
