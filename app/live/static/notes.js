/* Philibert Notes — the vault's Markdown files, written and read.
 *
 * Talks to /api/notes (nd_notes.py). Saves as you type (and on Ctrl+S); a note
 * changed elsewhere while open is never overwritten: a banner asks which to keep.
 * Deleting moves notes to the vault's .trash, from where they can be put back.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var esc = PhilMD.esc;
  var ed = $("editor"), titleEl = $("title"), preview = $("preview"), panes = $("panes");
  var st = {
    notes: [], folders: [], byTitle: {}, info: {},
    cur: null,            // {id, title, hash, crlf, mtime, backlinks}
    dirty: false, saving: false, timer: null,
    mode: load("notes.mode", "split"),
    open: JSON.parse(load("notes.open", "{}")),
  };

  function load(k, d) { try { var v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function keep(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } }
  function today() {           // local date: toISOString() is UTC and runs a day ahead in the evening
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }
  function stem(id) { return String(id).replace(/\.md$/i, "").split("/").pop(); }
  function folderOf(id) { var i = id.lastIndexOf("/"); return i < 0 ? "" : id.slice(0, i); }
  function ago(t) {
    var s = Math.max(0, Date.now() / 1000 - t);
    if (s < 45) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return new Date(t * 1000).toLocaleDateString();
  }
  function toast(msg, ms) {
    var el = $("toast");
    el.textContent = msg;
    el.classList.add("on");
    clearTimeout(toast.t);
    toast.t = setTimeout(function () { el.classList.remove("on"); }, ms || 2800);
  }
  function api(op, data, keepalive) {
    var body = Object.assign({ op: op }, data || {});
    return fetch("/api/notes", { method: "POST", headers: { "Content-Type": "application/json" },
                                 body: JSON.stringify(body), keepalive: !!keepalive })
      .then(function (r) { return r.json(); });
  }

  /* ================= the tree ================= */
  function indexTitles() {
    st.byTitle = {};
    st.notes.slice().sort(function (a, b) { return a.id.split("/").length - b.id.split("/").length; })
      .forEach(function (n) { if (!st.byTitle[n.title.toLowerCase()]) st.byTitle[n.title.toLowerCase()] = n.id; });
  }

  function loadTree() {
    return api("tree").then(function (d) {
      if (!d.ok) { $("tree").innerHTML = '<div class="row" style="color:var(--txt-faint)">' + esc(d.msg || "No vault") + "</div>"; return; }
      var sig = JSON.stringify([d.folders, d.notes.map(function (n) { return n.id; })]);
      st.notes = d.notes; st.folders = d.folders;
      if (sig !== st.sig) {               // the 6-second poll redraws only when something moved
        st.sig = sig;
        indexTitles();
        renderTree();
        fillFolderSelect();
      }
      if (st.cur && !st.dirty) {
        var n = st.notes.find(function (x) { return x.id === st.cur.id; });
        if (n && st.cur.mtime && n.mtime > st.cur.mtime + 0.5) openNote(st.cur.id, { quiet: true });  // changed elsewhere
      }
    });
  }

  function renderTree() {
    var root = { folders: {}, notes: [] };
    st.folders.forEach(function (f) {
      var node = root;
      f.split("/").forEach(function (part) { node = node.folders[part] = node.folders[part] || { folders: {}, notes: [] }; });
    });
    st.notes.forEach(function (n) {
      var node = root;
      if (n.folder) n.folder.split("/").forEach(function (part) { node = node.folders[part] = node.folders[part] || { folders: {}, notes: [] }; });
      node.notes.push(n);
    });
    function count(node) {
      var c = node.notes.length;
      Object.keys(node.folders).forEach(function (k) { c += count(node.folders[k]); });
      return c;
    }
    function html(node, path, depth) {
      var out = "";
      Object.keys(node.folders).sort(function (a, b) { return a.toLowerCase() < b.toLowerCase() ? -1 : 1; }).forEach(function (name) {
        var p = path ? path + "/" + name : name, closed = !st.open[p];
        out += '<div class="row folder' + (closed ? " closed" : "") + '" data-folder="' + esc(p) + '" style="padding-left:' + (8 + depth * 14) + 'px">' +
               '<svg class="chev" viewBox="0 0 10 10"><path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>' +
               '<span class="lbl">' + esc(name) + '</span><span class="cnt">' + count(node.folders[name]) + "</span></div>" +
               '<div class="kids' + (closed ? " closed" : "") + '">' + html(node.folders[name], p, depth + 1) + "</div>";
      });
      node.notes.sort(function (a, b) { return a.title.toLowerCase() < b.title.toLowerCase() ? -1 : 1; }).forEach(function (n) {
        out += '<div class="row note' + (st.cur && st.cur.id === n.id ? " active" : "") + '" draggable="true" data-id="' + esc(n.id) +
               '" title="' + esc(n.id) + '" style="padding-left:' + (12 + depth * 14) + 'px"><i class="dot"></i><span class="lbl">' + esc(n.title) + "</span></div>";
      });
      return out;
    }
    $("tree").innerHTML = html(root, "", 0) ||
      '<div class="row" style="color:var(--txt-faint);cursor:default">No notes yet. Make the first one.</div>';
  }

  function revealInTree(id) {
    var parts = folderOf(id).split("/"), p = "";
    parts.forEach(function (part) { if (!part) return; p = p ? p + "/" + part : part; st.open[p] = true; });
    keep("notes.open", JSON.stringify(st.open));
  }

  function fillFolderSelect() {
    var sel = $("folder"), cur = st.cur ? folderOf(st.cur.id) : "";
    sel.innerHTML = '<option value="">(vault)</option>' + st.folders.map(function (f) {
      return '<option value="' + esc(f) + '">' + esc(f) + "</option>";
    }).join("");
    sel.value = cur;
  }

  $("tree").addEventListener("click", function (ev) {
    var row = ev.target.closest(".row");
    if (!row) return;
    if (row.dataset.folder != null) {
      var p = row.dataset.folder;
      st.open[p] = !st.open[p];
      keep("notes.open", JSON.stringify(st.open));
      row.classList.toggle("closed");
      row.nextElementSibling.classList.toggle("closed");
    } else if (row.dataset.id) openNote(row.dataset.id);
  });
  $("btn-collapse").addEventListener("click", function () {
    st.open = {}; keep("notes.open", "{}"); renderTree();
  });

  // drag a note onto a folder (or onto VAULT for the top level) to move it
  $("tree").addEventListener("dragstart", function (ev) {
    var row = ev.target.closest(".row.note");
    if (row) ev.dataTransfer.setData("text/x-note", row.dataset.id);
  });
  function dropTarget(ev) { return ev.target.closest(".row.folder") || ev.target.closest(".side-head"); }
  document.querySelector(".side").addEventListener("dragover", function (ev) {
    var t = dropTarget(ev);
    document.querySelectorAll(".drop").forEach(function (e) { if (e !== t) e.classList.remove("drop"); });
    if (t) { ev.preventDefault(); t.classList.add("drop"); }
  });
  document.querySelector(".side").addEventListener("drop", function (ev) {
    var t = dropTarget(ev), id = ev.dataTransfer.getData("text/x-note");
    document.querySelectorAll(".drop").forEach(function (e) { e.classList.remove("drop"); });
    if (!t || !id) return;
    ev.preventDefault();
    moveNote(id, t.dataset.folder || "");
  });

  /* ================= opening and showing a note ================= */
  function showView(name) {
    ["v-welcome", "v-search", "v-trash"].forEach(function (v) { $(v).classList.toggle("on", v === name); });
  }

  function openNote(id, opts) {
    opts = opts || {};
    var go = function () {
      return api("read", { id: id }).then(function (d) {
        if (!d.ok) { toast(d.msg || "That note could not be opened."); return; }
        st.cur = { id: d.id, title: d.title, hash: d.hash, crlf: d.body.indexOf("\r\n") >= 0,
                   mtime: d.mtime, backlinks: d.backlinks };
        var keepPos = opts.quiet ? ed.selectionStart : 0;
        ed.value = d.body.replace(/\r\n/g, "\n");
        if (opts.quiet) ed.selectionStart = ed.selectionEnd = Math.min(keepPos, ed.value.length);
        titleEl.value = d.title;
        setDirty(false);
        $("conflict").classList.remove("on");
        showView(null);
        revealInTree(d.id);
        renderTree();
        fillFolderSelect();
        refresh();
        $("mtime").textContent = "edited " + ago(d.mtime);
        $("btn-obsidian").textContent = st.info.obsidian ? "OPEN IN OBSIDIAN" : "GET OBSIDIAN";
        $("btn-obsidian").title = st.info.obsidian ? "Open this note in Obsidian"
          : "Obsidian is a free notes app that opens this vault too: get it from obsidian.md";
        $("btn-obsidian").hidden = false;
        history.replaceState(null, "", "#" + encodeURIComponent(d.id));
        if (!opts.quiet && !opts.keepFocus) {
          if (!ed.value.trim()) ed.focus();
          var a = document.querySelector('.row.note.active');
          if (a) a.scrollIntoView({ block: "nearest" });
        }
        if (opts.quiet) toast("Updated from the drive: it was changed somewhere else.");
      });
    };
    return st.dirty && st.cur && st.cur.id !== id ? saveNow().then(go) : go();
  }

  function refresh() {
    var text = ed.value;
    preview.innerHTML = PhilMD.render(text);
    preview.querySelectorAll("a.wl").forEach(function (a) {
      if (!resolve(a.getAttribute("data-note"))) a.classList.add("missing");
    });
    var body = PhilMD.frontmatter(text).body;
    var words = (body.match(/[^\s#*>\-\[\]|`]+/g) || []).length;
    $("words").textContent = words + (words === 1 ? " word" : " words");
    renderRail(text);
  }

  function resolve(name) {
    var t = String(name || "").split("|")[0].split("#")[0].trim().split("/").pop().toLowerCase();
    return st.byTitle[t] || null;
  }

  function renderRail(text) {
    var cur = st.cur;
    $("r-back").innerHTML = cur && cur.backlinks && cur.backlinks.length ? cur.backlinks.map(function (id) {
      return '<a class="link" data-id="' + esc(id) + '" title="' + esc(id) + '">' + esc(stem(id)) + "</a>";
    }).join("") : '<div class="none">No other note links here yet.</div>';
    var seen = {}, out = [];
    (text.match(/\[\[[^\]|#\n]+(?=[|#][^\]\n]*\]\]|\]\])/g) || []).forEach(function (m) {   // finished links only
      var name = m.slice(2).trim(), key = name.toLowerCase();
      if (!name || seen[key]) return;
      seen[key] = true;
      var id = resolve(name);
      out.push(id ? '<a class="link" data-id="' + esc(id) + '">' + esc(stem(id)) + "</a>"
                  : '<a class="link missing" data-create="' + esc(name.split("/").pop()) + '" title="Click to create it">' + esc(name) + "</a>");
    });
    $("r-out").innerHTML = out.join("") || '<div class="none">Type [[ to link a note.</div>';
    var toc = [], lines = text.split("\n"), inCode = false;
    lines.forEach(function (l, i) {
      if (/^\s*```/.test(l)) inCode = !inCode;
      var h = !inCode && /^(#{1,3})\s+(.+)$/.exec(l);
      if (h) toc.push('<a class="link h' + h[1].length + '" data-line="' + i + '">' + esc(h[2]) + "</a>");
    });
    $("r-toc").innerHTML = toc.join("") || '<div class="none">Headings (#) show up here.</div>';
  }

  $("rail").addEventListener("click", function (ev) {
    var a = ev.target.closest(".link");
    if (!a) return;
    if (a.dataset.id) openNote(a.dataset.id);
    else if (a.dataset.create) createNote(a.dataset.create, "");
    else if (a.dataset.line != null) gotoLine(+a.dataset.line);
  });

  function gotoLine(n) {
    var lines = ed.value.split("\n"), pos = 0;
    for (var i = 0; i < n && i < lines.length; i++) pos += lines[i].length + 1;
    if (st.mode === "read") {
      var hs = preview.querySelectorAll("h1,h2,h3"), idx = 0;
      for (var j = 0, c = 0; j < lines.length && j < n; j++) if (/^#{1,3}\s/.test(lines[j])) c++;
      idx = Math.min(c, hs.length - 1);
      if (hs[idx]) hs[idx].scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    ed.focus();
    ed.setSelectionRange(pos, pos + (lines[n] || "").length);
    var lh = parseFloat(getComputedStyle(ed).lineHeight) || 26;
    ed.scrollTop = Math.max(0, caretXY(ed, pos).y - 3 * lh);
  }

  // links and checkboxes in the rendered note
  preview.addEventListener("click", function (ev) {
    var a = ev.target.closest("a.wl");
    if (a) {
      ev.preventDefault();
      var id = resolve(a.getAttribute("data-note"));
      if (id) openNote(id);
      else createNote(a.getAttribute("data-note").split("#")[0].split("/").pop(), "");
    }
  });
  preview.addEventListener("change", function (ev) {
    var box = ev.target;
    if (box.type !== "checkbox" || box.dataset.line == null) return;
    var lines = ed.value.split("\n"), n = +box.dataset.line;
    if (lines[n] == null) return;
    lines[n] = lines[n].replace(/\[( |x|X)\]/, box.checked ? "[x]" : "[ ]");
    ed.value = lines.join("\n");
    changed();
  });

  /* ================= saving ================= */
  function setDirty(d, state) {
    st.dirty = d;
    var s = $("status");
    s.className = "status" + (state ? " " + state : d ? " dirty" : "");
    $("status-t").textContent = state === "saving" ? "saving…" : state === "err" ? "not saved" : d ? "editing" : "saved";
  }

  function changed() {
    if (!st.cur) return;
    setDirty(true);
    refresh();
    clearTimeout(st.timer);
    st.timer = setTimeout(saveNow, 900);
  }

  function saveNow(force) {
    clearTimeout(st.timer);
    if (!st.cur || (!st.dirty && !force)) return Promise.resolve();
    if (st.saving) return st.saving;
    var cur = st.cur, text = ed.value;
    var body = cur.crlf ? text.replace(/\n/g, "\r\n") : text;
    setDirty(true, "saving");
    st.saving = api("save", { id: cur.id, body: body, hash: force ? null : cur.hash }).then(function (d) {
      st.saving = false;
      if (d.conflict) {
        st.theirs = d;
        $("conflict").classList.add("on");
        setDirty(true, "err");
        return;
      }
      if (!d.ok) { setDirty(true, "err"); toast(d.msg || "Could not save."); return; }
      cur.hash = d.hash; cur.mtime = d.mtime;
      $("mtime").textContent = "edited just now";
      setDirty(ed.value !== text);          // typed more while saving
      if (st.dirty) st.timer = setTimeout(saveNow, 900);
      var p = $("pulse"); p.classList.remove("go"); void p.offsetWidth; p.classList.add("go");
      var row = document.querySelector('.row.note[data-id="' + CSS.escape(cur.id) + '"]');
      if (row) { row.classList.add("fresh"); setTimeout(function () { row.classList.remove("fresh"); }, 1500); }
    }).catch(function () { st.saving = false; setDirty(true, "err"); toast("Could not reach Philibert to save."); });
    return st.saving;
  }

  $("c-mine").addEventListener("click", function () { $("conflict").classList.remove("on"); saveNow(true); });
  $("c-theirs").addEventListener("click", function () {
    $("conflict").classList.remove("on");
    st.dirty = false;
    openNote(st.cur.id, { keepFocus: true });
  });
  window.addEventListener("beforeunload", function () {
    if (st.dirty && st.cur) {
      var body = st.cur.crlf ? ed.value.replace(/\n/g, "\r\n") : ed.value;
      api("save", { id: st.cur.id, body: body, hash: st.cur.hash }, true);
    }
  });

  /* ================= title, folder, rename, move ================= */
  function rename() {
    if (!st.cur) return;
    var want = titleEl.value.trim();
    if (!want || want === st.cur.title) { titleEl.value = st.cur.title; return; }
    saveNow().then(function () {
      return api("rename", { id: st.cur.id, title: want });
    }).then(function (d) {
      if (!d.ok) { toast(d.msg); titleEl.value = st.cur.title; return; }
      st.cur.id = d.id; st.cur.title = d.title; titleEl.value = d.title;
      history.replaceState(null, "", "#" + encodeURIComponent(d.id));
      if (d.relinked && d.relinked.length) toast("Renamed. Links updated in " + d.relinked.length + (d.relinked.length === 1 ? " note." : " notes."));
      loadTree().then(refresh);
    });
  }
  titleEl.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") { ev.preventDefault(); ed.focus(); }
    if (ev.key === "Escape") { titleEl.value = st.cur ? st.cur.title : ""; ed.focus(); }
  });
  titleEl.addEventListener("change", rename);

  function moveNote(id, folder) {
    if (folderOf(id) === folder) return;
    var go = function () {
      return api("rename", { id: id, folder: folder }).then(function (d) {
        if (!d.ok) { toast(d.msg); return; }
        if (st.cur && st.cur.id === id) { st.cur.id = d.id; history.replaceState(null, "", "#" + encodeURIComponent(d.id)); }
        if (folder) { st.open[folder] = true; keep("notes.open", JSON.stringify(st.open)); }
        toast("Moved to " + (folder || "the top of the vault") + ".");
        loadTree();
      });
    };
    return st.cur && st.cur.id === id ? saveNow().then(go) : go();
  }
  $("folder").addEventListener("change", function () { if (st.cur) moveNote(st.cur.id, $("folder").value); });

  /* ================= new note / folder, the dialog ================= */
  function dialog(title, name, extra, okText) {
    return new Promise(function (resolveP) {
      var dlg = $("dlg");
      $("dlg-title").textContent = title;
      $("dlg-name").value = name || "";
      $("dlg-extra").innerHTML = extra || "";
      $("dlg-ok").textContent = okText || "CREATE";
      dlg.onclose = function () { resolveP(dlg.returnValue === "ok" ? $("dlg-name").value.trim() : null); };
      dlg.returnValue = "";
      dlg.showModal();
      $("dlg-name").select();
    });
  }
  $("dlg-name").addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") { ev.preventDefault(); $("dlg").close("ok"); }
  });

  function newNoteDialog(folder) {
    var here = folder != null ? folder : st.cur ? folderOf(st.cur.id) : "";
    var tpls = st.info.templates || [];
    var extra = '<label for="dlg-folder">FOLDER</label><select id="dlg-folder"><option value="">(vault)</option>' +
      st.folders.map(function (f) { return '<option' + (f === here ? " selected" : "") + ">" + esc(f) + "</option>"; }).join("") + "</select>" +
      (tpls.length ? '<label for="dlg-tpl">START FROM</label><select id="dlg-tpl"><option value="">A blank page</option>' +
        tpls.map(function (t) { return '<option value="' + esc(t.id) + '">' + esc(t.title) + "</option>"; }).join("") + "</select>" : "");
    var dl = dialog("New note", "", extra, "CREATE");
    var tplSel = $("dlg-tpl");
    if (tplSel) tplSel.addEventListener("change", function () {
      if (!$("dlg-name").value.trim() && tplSel.value) $("dlg-name").value = stem(tplSel.value).replace(/\s*template$/i, "") + " " + today();
    });
    var folderSel = $("dlg-folder");
    dl.then(function (name) {
      if (name == null) return;
      createNote(name || "Untitled", folderSel.value, tplSel ? tplSel.value : null);
    });
  }

  function createNote(title, folder, template) {
    return saveNow().then(function () {
      return api("create", { title: title, folder: folder || "", template: template || null });
    }).then(function (d) {
      if (!d.ok) { toast(d.msg); return; }
      return loadTree().then(function () { return openNote(d.id); }).then(function () {
        if (!template) { ed.focus(); }
      });
    });
  }

  $("btn-new").addEventListener("click", function () { newNoteDialog(); });
  $("btn-newfolder").addEventListener("click", function () { newFolder(""); });
  function newFolder(parent) {
    dialog("New folder" + (parent ? " in " + parent : ""), "", "", "CREATE").then(function (name) {
      if (!name) return;
      api("mkdir", { folder: (parent ? parent + "/" : "") + name }).then(function (d) {
        if (!d.ok) { toast(d.msg); return; }
        st.open[d.folder] = true; keep("notes.open", JSON.stringify(st.open));
        loadTree();
      });
    });
  }

  /* ================= menus ================= */
  var menu = $("menu");
  function showMenu(x, y, items) {
    menu.innerHTML = items.map(function (it, i) {
      if (it === "-") return "<hr>";
      if (it.label) return '<div class="lbl">' + esc(it.label) + "</div>";
      return '<div data-i="' + i + '">' + esc(it.text) + "</div>";
    }).join("");
    menu.style.display = "block";
    var r = menu.getBoundingClientRect();
    menu.style.left = Math.min(x, innerWidth - r.width - 8) + "px";
    menu.style.top = Math.min(y, innerHeight - r.height - 8) + "px";
    menu.onclick = function (ev) {
      var d = ev.target.closest("[data-i]");
      if (!d) return;
      hideMenu();
      items[+d.dataset.i].run();
    };
  }
  function hideMenu() { menu.style.display = "none"; }
  document.addEventListener("click", function (ev) { if (!menu.contains(ev.target) && !ev.target.closest("#btn-more")) hideMenu(); });

  function noteMenu(id) {
    return [
      { label: stem(id) },
      { text: "Open", run: function () { openNote(id); } },
      { text: "Rename…", run: function () {
          dialog("Rename note", stem(id), "", "RENAME").then(function (name) {
            if (!name) return;
            saveNow().then(function () { return api("rename", { id: id, title: name }); }).then(function (d) {
              if (!d.ok) { toast(d.msg); return; }
              if (st.cur && st.cur.id === id) { st.cur.id = d.id; st.cur.title = d.title; titleEl.value = d.title; }
              if (d.relinked && d.relinked.length) toast("Renamed. Links updated in " + d.relinked.length + " notes.");
              loadTree().then(refresh);
            });
          });
        } },
      { text: "Copy link  [[" + stem(id) + "]]", run: function () {
          (navigator.clipboard ? navigator.clipboard.writeText("[[" + stem(id) + "]]") : Promise.reject())
            .then(function () { toast("Link copied: paste it into another note."); }, function () { toast("[[" + stem(id) + "]]"); });
        } },
      st.info.obsidian ? { text: "Open in Obsidian", run: function () { openObsidian(id); } } : null,
      "-",
      { text: "Move to Trash", run: function () { trashNote(id); } },
    ].filter(Boolean);
  }

  $("tree").addEventListener("contextmenu", function (ev) {
    var row = ev.target.closest(".row");
    if (!row) return;
    ev.preventDefault();
    if (row.dataset.id) showMenu(ev.clientX, ev.clientY, noteMenu(row.dataset.id));
    else if (row.dataset.folder != null) {
      var f = row.dataset.folder;
      showMenu(ev.clientX, ev.clientY, [
        { label: f },
        { text: "New note here", run: function () { newNoteDialog(f); } },
        { text: "New folder inside", run: function () { newFolder(f); } },
      ]);
    }
  });
  $("btn-more").addEventListener("click", function (ev) {
    if (!st.cur) return;
    var r = ev.currentTarget.getBoundingClientRect();
    showMenu(r.left - 150, r.bottom + 6, noteMenu(st.cur.id));
  });

  function trashNote(id) {
    var go = function () {
      return api("trash", { id: id }).then(function (d) {
        if (!d.ok) { toast(d.msg); return; }
        if (st.cur && st.cur.id === id) {
          st.cur = null; st.dirty = false; ed.value = ""; titleEl.value = "";
          renderRail(""); showView("v-welcome"); history.replaceState(null, "", "#");
        }
        toast("Moved to Trash. Open Trash (bottom left) to put it back.", 3800);
        loadTree(); trashCount();
      });
    };
    return st.cur && st.cur.id === id ? saveNow().then(go) : go();
  }

  function openObsidian(id) {
    saveNow().then(function () { return api("obsidian", { id: id }); }).then(function (d) {
      if (!d.ok) { toast(d.msg); return; }
      if (!load("notes.obsidianHint", "")) { keep("notes.obsidianHint", "1"); toast(d.hint + "  " + d.vault, 9000); }
    });
  }
  // Obsidian is never shipped on the drive (its licence forbids passing it on): the
  // person gets it from the official page, and the vault already opens in it.
  $("btn-obsidian").addEventListener("click", function () {
    if (!st.info.obsidian) { window.open("https://obsidian.md/download", "_blank", "noopener"); return; }
    if (st.cur) openObsidian(st.cur.id);
  });

  /* ================= trash ================= */
  function trashCount() {
    return api("trash_list").then(function (d) {
      var n = (d.items || []).length;
      $("trash-count").textContent = n ? n : "";
      return d.items || [];
    });
  }
  $("btn-trash").addEventListener("click", function () {
    saveNow();
    trashCount().then(function (items) {
      $("t-list").innerHTML = items.length ? items.map(function (it) {
        return '<div class="card"><div class="grow"><div class="t">' + esc(it.title) + '</div><div class="f">was in ' +
               esc(folderOf(it.from) || "the vault") + " · deleted " + esc(ago(it.at)) + '</div></div>' +
               '<button class="btn" data-restore="' + esc(it.name) + '">PUT BACK</button></div>';
      }).join("") : '<p class="lead">The trash is empty.</p>';
      showView("v-trash");
    });
  });
  $("t-list").addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-restore]");
    if (!b) return;
    api("restore", { name: b.dataset.restore }).then(function (d) {
      if (!d.ok) { toast(d.msg); return; }
      toast("Put back.");
      loadTree().then(function () { trashCount(); openNote(d.id); });
    });
  });

  /* ================= search & jump ================= */
  var q = $("q"), sTimer = null;
  q.addEventListener("input", function () {
    clearTimeout(sTimer);
    var text = q.value.trim();
    if (!text) { showView(st.cur ? null : "v-welcome"); return; }
    sTimer = setTimeout(function () { runSearch(text); }, 160);
  });
  q.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") { var first = $("s-list").querySelector(".card"); if (first) first.click(); }
    if (ev.key === "Escape") { q.value = ""; showView(st.cur ? null : "v-welcome"); ed.focus(); }
  });
  function mark(s, words) {
    var h = esc(s);
    words.forEach(function (w) {
      if (w.length < 2) return;
      h = h.replace(new RegExp("(" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"), "<mark>$1</mark>");
    });
    return h;
  }
  function runSearch(text) {
    var words = text.toLowerCase().split(/\s+/).filter(Boolean);
    api("search", { q: text }).then(function (d) {
      if (q.value.trim() !== text) return;
      var res = d.results || [];
      $("s-title").textContent = res.length ? res.length + (res.length === 1 ? " note" : " notes") : "Nothing found";
      $("s-lead").innerHTML = res.length ? "Enter opens the first one." :
        'No note mentions that. <a href="#" id="s-make" style="color:var(--cyan)">Make a note called “' + esc(text) + "”</a>";
      $("s-list").innerHTML = res.map(function (r) {
        return '<div class="card" data-id="' + esc(r.id) + '"><div class="grow"><div class="t">' + mark(r.title, words) +
               '</div><div class="s">' + mark(r.snippet, words) + '</div></div><div class="f">' + esc(folderOf(r.id)) + "</div></div>";
      }).join("");
      showView("v-search");
      var mk = $("s-make");
      if (mk) mk.addEventListener("click", function (ev) { ev.preventDefault(); q.value = ""; createNote(text, ""); });
    });
  }
  $("s-list").addEventListener("click", function (ev) {
    var c = ev.target.closest(".card");
    if (c) { q.value = ""; openNote(c.dataset.id); }
  });

  /* ================= modes ================= */
  function setMode(m) {
    st.mode = m;
    keep("notes.mode", m);
    panes.className = "panes " + m;
    document.querySelectorAll("#modes button").forEach(function (b) { b.classList.toggle("on", b.dataset.mode === m); });
    $("tools").style.display = m === "read" ? "none" : "";
  }
  $("modes").addEventListener("click", function (ev) { var b = ev.target.closest("button"); if (b) setMode(b.dataset.mode); });

  /* ================= the toolbar ================= */
  function wrap(before, after, placeholder) {
    var a = ed.selectionStart, b = ed.selectionEnd, sel = ed.value.slice(a, b) || placeholder || "";
    ed.setRangeText(before + sel + after, a, b, "end");
    if (!ed.value.slice(a, b).length || sel === placeholder) ed.setSelectionRange(a + before.length, a + before.length + sel.length);
    ed.focus(); changed();
  }
  function prefixLines(make) {
    var v = ed.value, a = v.lastIndexOf("\n", ed.selectionStart - 1) + 1, b = v.indexOf("\n", ed.selectionEnd);
    if (b < 0) b = v.length;
    var lines = v.slice(a, b).split("\n").map(make);
    ed.setRangeText(lines.join("\n"), a, b, "end");
    ed.focus(); changed();
  }
  function insert(text) { ed.setRangeText(text, ed.selectionStart, ed.selectionEnd, "end"); ed.focus(); changed(); }
  var DO = {
    h: function () { prefixLines(function (l) { var m = /^(#{1,5})\s/.exec(l); return m ? (m[1].length >= 3 ? l.replace(/^#+\s/, "") : "#" + l) : "## " + l; }); },
    b: function () { wrap("**", "**", "bold"); },
    i: function () { wrap("*", "*", "italic"); },
    s: function () { wrap("~~", "~~", "struck"); },
    hl: function () { wrap("==", "==", "highlight"); },
    ul: function () { prefixLines(function (l) { return /^\s*[-*]\s/.test(l) ? l.replace(/^(\s*)[-*]\s/, "$1") : "- " + l; }); },
    task: function () { prefixLines(function (l) { return /^\s*- \[[ xX]\]\s/.test(l) ? l.replace(/^(\s*)- \[[ xX]\]\s/, "$1") : "- [ ] " + l.replace(/^\s*[-*]\s/, ""); }); },
    ol: function () { var n = 0; prefixLines(function (l) { n++; return /^\s*\d+\.\s/.test(l) ? l.replace(/^(\s*)\d+\.\s/, "$1") : n + ". " + l; }); },
    quote: function () { prefixLines(function (l) { return /^>\s?/.test(l) ? l.replace(/^>\s?/, "") : "> " + l; }); },
    link: function () { wrap("[[", "]]", ""); openAc(); },
    table: function () { insert("\n| Song | Key | Length |\n| --- | --- | --- |\n|  |  |  |\n"); },
    hr: function () { insert("\n---\n"); },
    date: function () { insert(today()); },
  };
  $("tools").addEventListener("click", function (ev) { var b = ev.target.closest("button"); if (b && DO[b.dataset.do]) DO[b.dataset.do](); });

  /* ================= [[ autocomplete ================= */
  var ac = $("ac"), acItems = [], acSel = 0;
  function caretXY(ta, pos) {
    var div = caretXY.div || (caretXY.div = document.createElement("div"));
    var cs = getComputedStyle(ta);
    ["fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing", "paddingTop", "paddingLeft", "paddingRight",
     "borderWidth", "boxSizing", "tabSize"].forEach(function (k) { div.style[k] = cs[k]; });
    div.style.position = "absolute"; div.style.visibility = "hidden"; div.style.whiteSpace = "pre-wrap";
    div.style.wordWrap = "break-word"; div.style.width = ta.clientWidth + "px"; div.style.top = "0"; div.style.left = "-9999px";
    div.textContent = ta.value.slice(0, pos);
    var span = document.createElement("span"); span.textContent = "​"; div.appendChild(span);
    document.body.appendChild(div);
    var r = { x: span.offsetLeft, y: span.offsetTop };
    div.remove();
    return r;
  }
  function acQuery() {
    var before = ed.value.slice(0, ed.selectionStart), i = before.lastIndexOf("[[");
    if (i < 0) return null;
    var frag = before.slice(i + 2);
    if (/[\]\n]/.test(frag)) return null;
    return { start: i + 2, text: frag };
  }
  function openAc() {
    var qy = acQuery();
    if (!qy) { ac.style.display = "none"; return; }
    var t = qy.text.toLowerCase().split("|")[0];
    acItems = st.notes.filter(function (n) { return !t || n.title.toLowerCase().indexOf(t) >= 0; })
      .sort(function (a, b) { return (a.title.toLowerCase().indexOf(t) - b.title.toLowerCase().indexOf(t)) || (b.mtime - a.mtime); })
      .slice(0, 9);
    var exact = st.byTitle[t];
    if (qy.text.trim() && !exact) acItems.push({ title: qy.text.trim(), create: true });
    if (!acItems.length) { ac.style.display = "none"; return; }
    acSel = 0;
    ac.innerHTML = acItems.map(function (n, i) {
      return '<div data-i="' + i + '" class="' + (i === 0 ? "sel" : "") + '">' + esc(n.title) +
             "<small>" + (n.create ? "new note" : esc(n.folder || "")) + "</small></div>";
    }).join("");
    var xy = caretXY(ed, ed.selectionStart);
    ac.style.left = Math.min(xy.x, ed.clientWidth - 260) + "px";
    ac.style.top = (xy.y - ed.scrollTop + 28) + "px";
    ac.style.display = "block";
  }
  function pickAc(i) {
    var qy = acQuery(), n = acItems[i];
    if (!qy || !n) return;
    var after = ed.value.slice(ed.selectionStart).startsWith("]]") ? "" : "]]";
    ed.setRangeText(n.title + after, qy.start, ed.selectionStart, "end");
    if (!after) ed.setSelectionRange(ed.selectionStart + 2, ed.selectionStart + 2);
    ac.style.display = "none";
    changed();
  }
  ac.addEventListener("mousedown", function (ev) { var d = ev.target.closest("[data-i]"); if (d) { ev.preventDefault(); pickAc(+d.dataset.i); } });

  ed.addEventListener("input", function () { changed(); openAc(); });
  ed.addEventListener("blur", function () { setTimeout(function () { ac.style.display = "none"; }, 120); saveNow(); });
  ed.addEventListener("keydown", function (ev) {
    if (ac.style.display === "block") {
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        acSel = (acSel + (ev.key === "ArrowDown" ? 1 : acItems.length - 1)) % acItems.length;
        ac.querySelectorAll("div").forEach(function (d, i) { d.classList.toggle("sel", i === acSel); });
        return;
      }
      if (ev.key === "Enter" || ev.key === "Tab") { ev.preventDefault(); pickAc(acSel); return; }
      if (ev.key === "Escape") { ac.style.display = "none"; return; }
    }
    if (ev.key === "Tab") {           // indent / outdent list items instead of leaving the editor
      ev.preventDefault();
      if (ev.shiftKey) prefixLines(function (l) { return l.replace(/^( {1,2}|\t)/, ""); });
      else if (ed.selectionStart === ed.selectionEnd && !/^\s*([-*]|\d+\.)\s/.test(ed.value.slice(ed.value.lastIndexOf("\n", ed.selectionStart - 1) + 1))) insert("  ");
      else prefixLines(function (l) { return "  " + l; });
      return;
    }
    if (ev.key === "Enter" && !ev.shiftKey) {   // carry lists and checklists onto the next line
      var v = ed.value, ls = v.lastIndexOf("\n", ed.selectionStart - 1) + 1, line = v.slice(ls, ed.selectionStart);
      var m = /^(\s*)(- \[[ xX]\] |[-*+] |(\d+)\. )(.*)$/.exec(line);
      if (m) {
        ev.preventDefault();
        if (!m[4].trim()) { ed.setRangeText("", ls, ed.selectionStart, "end"); changed(); return; }  // empty item ends the list
        var next = m[2].indexOf("[") >= 0 ? "- [ ] " : m[3] ? (+m[3] + 1) + ". " : m[2];
        insert("\n" + m[1] + next);
      }
    }
    if ((ev.ctrlKey || ev.metaKey) && !ev.shiftKey && !ev.altKey) {
      var k = ev.key.toLowerCase();
      if (k === "b") { ev.preventDefault(); DO.b(); }
      if (k === "i") { ev.preventDefault(); DO.i(); }
      if (k === "l") { ev.preventDefault(); DO.task(); }
    }
  });

  /* ================= keys anywhere ================= */
  document.addEventListener("keydown", function (ev) {
    if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) return;
    var k = ev.key.toLowerCase();
    if (k === "s") { ev.preventDefault(); saveNow(true); }
    else if (k === "k" || k === "p" || k === "o") { ev.preventDefault(); q.focus(); q.select(); }
    else if (k === "n" && !ev.shiftKey) { ev.preventDefault(); newNoteDialog(); }   // the drive's Chromium keeps Ctrl+N; Alt+N below
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.altKey && !ev.ctrlKey && !ev.metaKey && ev.key.toLowerCase() === "n") { ev.preventDefault(); newNoteDialog(); }
    else if (k === "e") { ev.preventDefault(); setMode({ write: "split", split: "read", read: "write" }[st.mode] || "split"); }
  });

  /* ================= start ================= */
  setMode(st.mode);
  api("info").then(function (d) {
    st.info = d.ok ? d : {};
    $("vault-path").textContent = d.vault || "";
    $("vault-path").title = d.vault || "";
  });
  loadTree().then(function () {
    trashCount();
    var want = decodeURIComponent(location.hash.slice(1) || "");
    if (want && st.notes.some(function (n) { return n.id === want; })) openNote(want);
    else showView("v-welcome");
  });
  window.addEventListener("hashchange", function () {
    var want = decodeURIComponent(location.hash.slice(1) || "");
    if (want && (!st.cur || st.cur.id !== want)) openNote(want);
  });
  // pick up notes Philibert (or Obsidian, or another PC) wrote meanwhile
  setInterval(function () { if (!document.hidden) loadTree(); }, 6000);
})();
