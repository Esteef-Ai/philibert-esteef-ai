/* Philibert Files: the drive's Philibert folder (nd_files.py, /api/files). Mostly for the
 * pictures Image Generation makes. Philibert's own program folders are read-only; Delete
 * goes to the desktop Trash. Click selects, Ctrl/Shift-click adds, double-click opens. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var cur = { path: "data/images", items: [], read_only: false, parent: null }, sel = new Set(), last = -1;
  var clip = null;       // {mode: "copy"|"cut", paths: [...]}
  try { cur.path = localStorage.getItem("files.path") || cur.path; } catch (e) { /* private */ }

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function api(op, d) {
    return fetch("/api/files", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ op: op }, d || {})) })
      .then(function (r) { return r.json(); });
  }
  function toast(m) { var t = $("toast"); t.textContent = m; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove("on"); }, 2600); }
  function src(p) { return "/api/files/file?path=" + encodeURIComponent(p); }
  function size(b) { return b >= 1e9 ? (b / 1e9).toFixed(1) + " GB" : b >= 1e6 ? (b / 1e6).toFixed(1) + " MB" : b >= 1e3 ? Math.round(b / 1e3) + " KB" : b + " B"; }

  function go(path) {
    return api("list", { path: path }).then(function (d) {
      if (!d.ok) { toast(d.msg); if (path) return go(""); return; }
      cur = d; sel.clear(); last = -1;
      try { localStorage.setItem("files.path", d.path); } catch (e) { /* private */ }
      draw();
    });
  }
  function draw() {
    var parts = cur.path ? cur.path.split("/") : [];
    $("crumbs").innerHTML = '<a data-go="">Philibert</a>' + parts.map(function (p, i) {
      return " / <a data-go=\"" + esc(parts.slice(0, i + 1).join("/")) + "\">" + esc(p) + "</a>"; }).join("") +
      (cur.read_only ? '<span class="ro">READ-ONLY - Philibert\'s own</span>' : "");
    document.querySelectorAll("#places a").forEach(function (a) { a.classList.toggle("on", a.dataset.go === cur.path); });
    $("grid").innerHTML = cur.items.map(function (it, i) {
      var cut = clip && clip.mode === "cut" && clip.paths.indexOf(it.path) >= 0;
      var ext = (it.name.split(".").pop() || "").slice(0, 4);
      return '<div class="it' + (sel.has(it.path) ? " sel" : "") + (cut ? " cut" : "") + '" data-i="' + i + '" title="' + esc(it.name) + '">' +
        '<div class="th">' + (it.image ? '<img loading="lazy" src="' + src(it.path) + '" alt="">'
          : '<div class="ic ' + (it.dir ? "folder" : "file") + '">' + (it.dir ? "" : "<span>" + esc(ext) + "</span>") + "</div>") + "</div>" +
        '<div class="nm">' + esc(it.name) + '</div><div class="mt">' + (it.dir ? "folder" : size(it.size)) + "</div></div>";
    }).join("") || '<div class="empty">This folder is empty.</div>';
    status();
  }
  function status() {
    var n = cur.items.length, s = sel.size;
    $("count").textContent = n + " item" + (n === 1 ? "" : "s") + (s ? " · " + s + " selected" : "");
    $("clip").textContent = clip ? clip.paths.length + " ready to " + (clip.mode === "cut" ? "move" : "copy") + " - PASTE in the folder you want" : "";
    var ro = cur.read_only, any = s > 0, one = s === 1;
    $("b-up").disabled = cur.parent === null;
    $("b-new").disabled = ro; $("b-paste").disabled = ro || !clip;
    $("b-copy").disabled = !any; $("b-cut").disabled = !any || ro; $("b-del").disabled = !any || ro;
    $("b-ren").disabled = !one || ro;
    $("b-save").disabled = !one || selected()[0].dir;
  }
  function selected() { return cur.items.filter(function (it) { return sel.has(it.path); }); }

  // Selection changes the items' classes in place. Redrawing the grid on every click
  // (as before) replaced the item under the mouse, so WebKit (the Mac window) never saw
  // a double-click and folders could not be opened there (2026-10-25).
  function paintSel() {
    [].forEach.call($("grid").querySelectorAll(".it"), function (el) {
      el.classList.toggle("sel", sel.has(cur.items[+el.dataset.i].path));
    });
    status();
  }
  function openItem(it) {
    if (it.dir) go(it.path);
    else if (it.image) viewer(it);
    else location.href = src(it.path) + "&download=1";
  }
  var lastClick = { i: -1, t: 0 };
  $("grid").addEventListener("click", function (ev) {
    var el = ev.target.closest(".it");
    if (!el) { sel.clear(); last = -1; paintSel(); return; }
    var i = +el.dataset.i, it = cur.items[i];
    // our own double-click: two clicks on the same item, whatever the engine does with dblclick
    var now = Date.now(), twice = lastClick.i === i && now - lastClick.t < 450 && !ev.shiftKey && !ev.ctrlKey && !ev.metaKey;
    lastClick = twice ? { i: -1, t: 0 } : { i: i, t: now };
    if (twice) { openItem(it); return; }
    if (ev.shiftKey && last >= 0) {
      var a = Math.min(last, i), b = Math.max(last, i);
      if (!ev.ctrlKey) sel.clear();
      for (var k = a; k <= b; k++) sel.add(cur.items[k].path);
    } else if (ev.ctrlKey || ev.metaKey) {
      if (sel.has(it.path)) sel.delete(it.path); else sel.add(it.path);
      last = i;
    } else { sel.clear(); sel.add(it.path); last = i; }
    paintSel();
  });
  $("grid").addEventListener("keydown", function (ev) {        // Enter opens what is selected
    if (ev.key === "Enter" && sel.size === 1) { var it = selected()[0]; if (it) openItem(it); }
  });
  document.addEventListener("click", function (ev) { var g = ev.target.closest("[data-go]"); if (g) go(g.dataset.go); });

  function copyCut(mode) { if (!sel.size) return; clip = { mode: mode, paths: Array.from(sel) }; toast(sel.size + (mode === "cut" ? " cut" : " copied")); draw(); }
  function paste() {
    if (!clip || cur.read_only) return;
    api(clip.mode === "cut" ? "move" : "copy", { paths: clip.paths, dest: cur.path }).then(function (d) {
      if (!d.ok) { toast(d.msg); return; }
      toast((clip.mode === "cut" ? "Moved " : "Copied ") + d.done.length);
      if (clip.mode === "cut") clip = null;
      go(cur.path);
    });
  }
  function del() {
    var s = selected(); if (!s.length || cur.read_only) return;
    if (!confirm("Move " + (s.length === 1 ? '"' + s[0].name + '"' : s.length + " items") + " to the Trash? You can put them back from the desktop Trash.")) return;
    api("trash", { paths: s.map(function (x) { return x.path; }) }).then(function (d) { toast(d.ok ? "Moved to the Trash" : d.msg); go(cur.path); });
  }
  function ren() {
    var s = selected(); if (s.length !== 1 || cur.read_only) return;
    var n = prompt("New name:", s[0].name); if (!n || n === s[0].name) return;
    api("rename", { path: s[0].path, name: n }).then(function (d) { if (!d.ok) toast(d.msg); go(cur.path); });
  }
  $("b-up").addEventListener("click", function () { if (cur.parent !== null) go(cur.parent); });
  $("b-new").addEventListener("click", function () {
    var n = prompt("Name of the new folder:", "New folder"); if (!n) return;
    api("mkdir", { path: cur.path, name: n }).then(function (d) { if (!d.ok) toast(d.msg); go(cur.path); });
  });
  $("b-copy").addEventListener("click", function () { copyCut("copy"); });
  $("b-cut").addEventListener("click", function () { copyCut("cut"); });
  $("b-paste").addEventListener("click", paste);
  $("b-ren").addEventListener("click", ren);
  $("b-del").addEventListener("click", del);
  $("b-save").addEventListener("click", function () { var s = selected()[0]; if (s && !s.dir) location.href = src(s.path) + "&download=1"; });
  document.addEventListener("keydown", function (ev) {
    if ($("lb").classList.contains("on")) {
      if (ev.key === "Escape") closeViewer();
      if (ev.key === "ArrowRight") step(1);
      if (ev.key === "ArrowLeft") step(-1);
      return;
    }
    if (ev.target.matches("input,textarea")) return;
    var c = ev.ctrlKey || ev.metaKey;
    if (c && ev.key.toLowerCase() === "c") copyCut("copy");
    else if (c && ev.key.toLowerCase() === "x" && !cur.read_only) copyCut("cut");
    else if (c && ev.key.toLowerCase() === "v") paste();
    else if (c && ev.key.toLowerCase() === "a") { ev.preventDefault(); cur.items.forEach(function (it) { sel.add(it.path); }); draw(); }
    else if (ev.key === "Delete") del();
    else if (ev.key === "F2") { ev.preventDefault(); ren(); }
    else if (ev.key === "Backspace" && cur.parent !== null) go(cur.parent);
  });

  /* the picture viewer */
  var vi = -1;
  function pics() { return cur.items.filter(function (x) { return x.image; }); }
  function viewer(it) { vi = pics().indexOf(it); show(); $("lb").classList.add("on"); }
  function show() {
    var p = pics()[vi]; if (!p) return;
    $("lb-img").src = src(p.path);
    var cap = p.name + "  ·  " + (vi + 1) + " of " + pics().length;
    $("lb-cap").textContent = cap;
    if (p.card) fetch(src(p.path.replace(/\.png$/i, ".json"))).then(function (r) { return r.json(); }).then(function (c) {
      if (pics()[vi] === p && c.prompt) $("lb-cap").textContent = "“" + c.prompt + "”  ·  " + (c.model || "") + "  ·  " + cap;
    }).catch(function () {});
  }
  function step(d) { var n = pics().length; if (!n) return; vi = (vi + d + n) % n; show(); }
  function closeViewer() { $("lb").classList.remove("on"); }
  $("lb-x").addEventListener("click", closeViewer);
  $("lb-pv").addEventListener("click", function () { step(-1); });
  $("lb-nx").addEventListener("click", function () { step(1); });

  go(cur.path);
})();
