/* Philibert Chat — the one-stop page around Elena Live's board and vault.
 *
 * Unload GPU, the brand spark, and the notes panel: the notes Philibert has
 * just read (newest first, coloured by read / write / update), and any note
 * opened from that list, from a [[wikilink]], or by clicking it in the vault.
 * Reads only: editing notes is the Notes app's job.
 */
(function () {
  "use strict";

  var OP = { read: "#00f2fe", write: "#10b981", update: "#f59e0b" };
  var body = document.getElementById("notes-body");
  var sub = document.getElementById("notes-sub");
  var back = document.getElementById("notes-back");
  var toastEl = document.getElementById("toast");
  var lastState = null;
  var openId = null;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function stem(id) { return String(id).replace(/\.md$/i, "").split("/").pop(); }
  function ago(t) {
    var s = Math.max(0, Date.now() / 1000 - t);
    if (s < 60) return Math.round(s) + "s";
    if (s < 3600) return Math.round(s / 60) + "m";
    if (s < 86400) return Math.round(s / 3600) + "h";
    return Math.round(s / 86400) + "d";
  }
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add("on");
    clearTimeout(toast.t);
    toast.t = setTimeout(function () { toastEl.classList.remove("on"); }, 2600);
  }

  /* ---------- unload the GPU ---------- */
  var unloadBtn = document.getElementById("btn-unload");
  unloadBtn.addEventListener("click", function () {
    unloadBtn.classList.add("busy");
    unloadBtn.textContent = "UNLOADING…";
    fetch("/api/unload_gpu", { method: "POST", headers: { "Content-Type": "application/json" },
                               body: JSON.stringify({ reason: "the Unload GPU button" }) })
      .then(function (r) { return r.json(); })
      .then(function () { toast("The model is off the graphics card. It loads again on your next message."); })
      .catch(function () { toast("Could not unload the GPU."); })
      .then(function () { unloadBtn.classList.remove("busy"); unloadBtn.textContent = "UNLOAD GPU"; });
  });

  /* ---------- the notes panel ---------- */
  function noteIdByName(name) {
    var notes = (lastState && lastState.vault && lastState.vault.graph && lastState.vault.graph.notes) || [];
    var want = String(name).split("|")[0].split("#")[0].trim().toLowerCase();
    for (var i = 0; i < notes.length; i++) {
      if (stem(notes[i].id).toLowerCase() === want) return notes[i].id;
    }
    return null;
  }

  // small, safe Markdown: everything is escaped first, then a few patterns
  function md(src) {
    var fm = "";
    var m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(src);
    if (m) {
      var tags = /tags:\s*\[?([^\]\n]*)/.exec(m[1]);
      var type = /type:\s*(\S+)/.exec(m[1]);
      fm = [type ? type[1] : "", tags ? tags[1].trim() : ""].filter(Boolean).join("  ·  ");
      src = src.slice(m[0].length);
    }
    var out = [], inList = false, inCode = false;
    src.split(/\r?\n/).forEach(function (line) {
      if (/^```/.test(line)) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push(inCode ? "</pre>" : "<pre>");
        inCode = !inCode;
        return;
      }
      if (inCode) { out.push(esc(line)); return; }
      var t = esc(line)
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
        .replace(/(^|[^*])\*([^*]+)\*/g, "$1<i>$2</i>")
        .replace(/\[\[([^\]]+)\]\]/g, function (_, inner) {
          var label = inner.indexOf("|") >= 0 ? inner.split("|")[1] : inner;
          return '<a class="wl" data-note="' + inner + '">' + label + "</a>";
        });
      var h = /^(#{1,3})\s+(.*)$/.exec(t);
      var li = /^\s*[-*]\s+(.*)$/.exec(t);
      if (li) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push("<li>" + li[1] + "</li>");
        return;
      }
      if (inList) { out.push("</ul>"); inList = false; }
      if (h) out.push("<h" + h[1].length + ">" + h[2] + "</h" + h[1].length + ">");
      else if (t.trim()) out.push("<p>" + t + "</p>");
    });
    if (inList) out.push("</ul>");
    if (inCode) out.push("</pre>");
    return (fm ? '<div class="fm">' + esc(fm) + "</div>" : "") + out.join("\n");
  }

  function showRecent() {
    openId = null;
    back.hidden = true;
    sub.textContent = "recently read";
    var evs = (lastState && lastState.vault && lastState.vault.events) || [];
    var seen = {}, rows = [];
    for (var i = evs.length - 1; i >= 0 && rows.length < 14; i--) {
      var e = evs[i];
      if (!e.note || seen[e.note]) continue;
      seen[e.note] = true;
      rows.push(e);
    }
    if (!rows.length) {
      body.innerHTML = '<div class="empty">Notes light up here as Philibert reads them. ' +
        "Click any star in the vault to open its note.</div>";
      return;
    }
    body.innerHTML = rows.map(function (e) {
      return '<div class="item" data-id="' + esc(e.note) + '"><i style="color:' + (OP[e.op] || OP.read) +
        ";background:" + (OP[e.op] || OP.read) + '"></i><span class="t">' + esc(stem(e.note)) +
        '</span><span class="w">' + esc(e.op || "read") + " · " + ago(e.t) + "</span></div>";
    }).join("");
  }

  function openNote(id, fromVault) {
    if (!id) { showRecent(); return; }
    openId = id;
    back.hidden = false;
    sub.textContent = stem(id);
    body.innerHTML = '<div class="empty">opening…</div>';
    if (!fromVault && window.vaultFocusNote) window.vaultFocusNote(id);
    fetch("/api/vault_note?id=" + encodeURIComponent(id))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (openId !== id) return;
        body.innerHTML = d.body != null ? '<div class="md">' + md(d.body) + "</div>"
                                        : '<div class="empty">This note could not be opened.</div>';
        body.scrollTop = 0;
      })
      .catch(function () { body.innerHTML = '<div class="empty">This note could not be opened.</div>'; });
  }

  body.addEventListener("click", function (ev) {
    var item = ev.target.closest(".item");
    if (item) { openNote(item.getAttribute("data-id")); return; }
    var wl = ev.target.closest("a.wl");
    if (wl) {
      var id = noteIdByName(wl.getAttribute("data-note"));
      if (id) openNote(id); else toast("That note is not in the vault yet.");
    }
  });
  back.addEventListener("click", function () { showRecent(); });
  window.addEventListener("vault-focus", function (ev) {
    if (ev.detail) openNote(ev.detail, true);
  });

  /* ---------- the state, once per poll ---------- */
  var spark = document.getElementById("brand-spark");
  var lastEvKey = "";
  window.addEventListener("viz-state", function (ev) {
    lastState = ev.detail || null;
    var kind = (lastState && lastState.task && lastState.task.kind) || "idle";
    if (spark) spark.className = "spark" + (kind === "idle" ? "" : " " + kind);
    if (openId) return;
    var evs = (lastState && lastState.vault && lastState.vault.events) || [];
    var key = evs.length ? evs[evs.length - 1].t + "|" + evs.length : "none";
    if (key !== lastEvKey) { lastEvKey = key; showRecent(); }
  });

  showRecent();
})();
