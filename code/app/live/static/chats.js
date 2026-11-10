/* Philibert's chat history: saved chats, folders, rename, delete (recoverable),
 * search, and "continue in a new chat" (the old chat becomes background for the
 * new one). The chat itself lives in the iframe; the two talk by postMessage.
 * Storage is /api/chats (nd_chats.py) on the drive.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var list = $("cp-list"), frame = $("chat-frame"), menu = $("cp-menu");
  var st = { chats: [], folders: [], cur: null, q: "", hits: null, trash: false, ready: false,
             open: JSON.parse(load("phil.chatFolders", "{}")) };
  var toast = function (m) { (window.philToast || alert)(m); };

  function load(k, d) { try { var v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } }
  function keep(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function api(op, data) {
    return fetch("/api/chats", { method: "POST", headers: { "Content-Type": "application/json" },
                                 body: JSON.stringify(Object.assign({ op: op }, data || {})) })
      .then(function (r) { return r.json(); });
  }
  function tell(msg) { frame.contentWindow.postMessage(msg, location.origin); }

  /* ---------- the list ---------- */
  function refresh() {
    return api("list").then(function (d) {
      if (!d.ok) return;
      st.chats = d.chats; st.folders = d.folders;
      render();
    });
  }

  function bucket(t) {
    var now = new Date(), d = new Date(t * 1000);
    var day = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
    if (t >= day) return "Today";
    if (t >= day - 86400) return "Yesterday";
    if (t >= day - 6 * 86400) return "Previous 7 days";
    if (d.getFullYear() === now.getFullYear()) return d.toLocaleString(undefined, { month: "long" });
    return String(d.getFullYear());
  }

  function row(c) {
    return '<div class="cp-row' + (c.id === st.cur ? " active" : "") + '" draggable="true" data-id="' + esc(c.id) +
           '" title="' + esc(c.preview || c.title) + '"><span class="t">' + esc(c.title) +
           '</span><button class="more" type="button" aria-label="Chat options" data-more="' + esc(c.id) + '">⋯</button></div>';
  }

  function render() {
    if (st.trash) return renderTrash();
    var chats = st.hits || st.chats;
    if (st.q && !st.hits) {
      var q = st.q.toLowerCase();
      chats = chats.filter(function (c) { return c.title.toLowerCase().indexOf(q) >= 0; });
    }
    var html = "";
    if (!st.q) {
      st.folders.forEach(function (f) {
        var inside = st.chats.filter(function (c) { return c.folder === f; }), closed = !st.open[f];
        html += '<div class="cp-row folder' + (closed ? " closed" : "") + '" data-folder="' + esc(f) + '">' +
                '<svg class="chev" viewBox="0 0 10 10"><path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>' +
                '<span class="t">' + esc(f) + '</span><span class="n">' + inside.length + '</span>' +
                '<button class="more" type="button" aria-label="Folder options" data-fmore="' + esc(f) + '">⋯</button></div>' +
                '<div class="cp-kids' + (closed ? " closed" : "") + '">' +
                (inside.length ? inside.map(row).join("") : '<div class="cp-empty">Drag chats here.</div>') + "</div>";
      });
      chats = chats.filter(function (c) { return !c.folder; });
    }
    var last = null;
    chats.forEach(function (c) {
      var b = st.q ? (st.hits ? "Found in" : "Matching") : bucket(c.updated);
      if (b !== last) { html += '<div class="cp-group">' + esc(b) + "</div>"; last = b; }
      html += row(c);
    });
    if (!html) html = st.q ? '<div class="cp-empty">No chat matches “' + esc(st.q) + '”.</div>'
                           : '<div class="cp-empty">Your chats are saved here as you go. Start one on the right.</div>';
    list.innerHTML = html;
  }

  function renderTrash() {
    api("trash_list").then(function (d) {
      var items = d.chats || [];
      list.innerHTML = '<div class="cp-group">Recently deleted</div>' + (items.length ? items.map(function (c) {
        return '<div class="cp-row" data-restore="' + esc(c.id) + '" title="Put it back"><span class="t">' + esc(c.title) +
               '</span><button class="more" type="button" data-restore="' + esc(c.id) + '">PUT BACK</button></div>';
      }).join("") : '<div class="cp-empty">Nothing deleted.</div>');
    });
  }

  /* ---------- opening, new ---------- */
  function openChat(id) {
    if (id === st.cur) return;
    tell({ type: "phil-chat-open", id: id });
  }
  function newChat(refs, folder) {
    tell({ type: "phil-chat-new", refs: refs || [], folder: folder || "" });
  }

  list.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-restore]");
    if (b) {
      api("restore", { id: b.dataset.restore }).then(function () {
        st.trash = false; $("cp-trash").textContent = "Recently deleted";
        refresh(); openChat(b.dataset.restore);
      });
      return;
    }
    var more = ev.target.closest("[data-more]");
    if (more) { ev.stopPropagation(); chatMenu(more.dataset.more, more); return; }
    var fmore = ev.target.closest("[data-fmore]");
    if (fmore) { ev.stopPropagation(); folderMenu(fmore.dataset.fmore, fmore); return; }
    var r = ev.target.closest(".cp-row");
    if (!r || r.querySelector("input")) return;
    if (r.dataset.folder != null) {
      st.open[r.dataset.folder] = !st.open[r.dataset.folder];
      keep("phil.chatFolders", JSON.stringify(st.open));
      render();
    } else if (r.dataset.id) openChat(r.dataset.id);
  });
  list.addEventListener("contextmenu", function (ev) {
    var r = ev.target.closest(".cp-row");
    if (!r) return;
    ev.preventDefault();
    if (r.dataset.id) chatMenu(r.dataset.id, null, ev.clientX, ev.clientY);
    else if (r.dataset.folder != null) folderMenu(r.dataset.folder, null, ev.clientX, ev.clientY);
  });
  $("cp-new").addEventListener("click", function () { newChat(); });

  /* ---------- rename in place ---------- */
  function inlineEdit(rowEl, value, done) {
    var t = rowEl.querySelector(".t");
    var inp = document.createElement("input");
    inp.className = "cp-edit"; inp.value = value; inp.spellcheck = false;
    t.replaceWith(inp);
    inp.focus(); inp.select();
    var finished = false;
    function finish(save) {
      if (finished) return;
      finished = true;
      var v = inp.value.trim();
      if (save && v && v !== value) done(v); else render();
    }
    inp.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); finish(true); }
      if (e.key === "Escape") finish(false);
    });
    inp.addEventListener("blur", function () { finish(true); });
  }
  function findRow(attr, v) {
    return [].slice.call(list.querySelectorAll(".cp-row")).find(function (r) { return r.dataset[attr] === v; });
  }
  function renameChat(id) {
    var c = st.chats.find(function (x) { return x.id === id; });
    var r = findRow("id", id);
    if (!c || !r) return;
    inlineEdit(r, c.title, function (v) {
      api("rename", { id: id, title: v }).then(function (d) {
        if (!d.ok) { toast(d.msg); return; }
        tell({ type: "phil-chat-renamed", id: id, title: d.title });
        refresh();
      });
    });
  }

  /* ---------- menus ---------- */
  function showMenu(items, anchor, x, y) {
    menu.innerHTML = items.map(function (it, i) {
      if (it === "-") return "<hr>";
      if (it.label) return '<div class="lbl">' + esc(it.label) + "</div>";
      return '<div data-i="' + i + '"' + (it.danger ? ' class="danger"' : "") + ">" + esc(it.text) + "</div>";
    }).join("");
    menu.style.display = "block";
    if (anchor) { var a = anchor.getBoundingClientRect(); x = a.left; y = a.bottom + 4; }
    var r = menu.getBoundingClientRect();
    menu.style.left = Math.max(8, Math.min(x, innerWidth - r.width - 8)) + "px";
    menu.style.top = Math.max(8, Math.min(y, innerHeight - r.height - 8)) + "px";
    menu.onclick = function (ev) {
      var d = ev.target.closest("[data-i]");
      if (!d) return;
      menu.style.display = "none";
      items[+d.dataset.i].run();
    };
  }
  document.addEventListener("click", function (ev) { if (!menu.contains(ev.target)) menu.style.display = "none"; });
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") menu.style.display = "none"; });

  function chatMenu(id, anchor, x, y) {
    var c = st.chats.find(function (x) { return x.id === id; }) || { title: "", folder: "" };
    var items = [
      { label: c.title },
      { text: "Open", run: function () { openChat(id); } },
      { text: "Rename", run: function () { renameChat(id); } },
      { text: "Continue in a new chat", run: function () { newChat([id], c.folder); toast("New chat started with “" + c.title + "” as background."); } },
      "-", { label: "Move to" },
    ];
    if (c.folder) items.push({ text: "No folder", run: function () { moveChat(id, ""); } });
    st.folders.filter(function (f) { return f !== c.folder; }).forEach(function (f) {
      items.push({ text: f, run: function () { moveChat(id, f); } });
    });
    items.push({ text: "New folder…", run: function () { newFolder(id); } });
    items.push("-", { text: "Delete", danger: true, run: function () { deleteChat(id); } });
    showMenu(items, anchor, x, y);
  }
  function folderMenu(f, anchor, x, y) {
    showMenu([
      { label: f },
      { text: "New chat in this folder", run: function () { newChat([], f); } },
      { text: "Rename folder", run: function () {
          var r = findRow("folder", f);
          if (r) inlineEdit(r, f, function (v) {
            api("folder_rename", { old: f, new: v }).then(function () {
              if (st.open[f]) { st.open[v] = true; delete st.open[f]; keep("phil.chatFolders", JSON.stringify(st.open)); }
              refresh();
            });
          });
        } },
      "-",
      { text: "Delete folder (keeps its chats)", danger: true, run: function () {
          api("folder_delete", { name: f }).then(refresh);
        } },
    ], anchor, x, y);
  }

  function moveChat(id, folder) {
    api("move", { id: id, folder: folder }).then(function (d) {
      if (!d.ok) { toast(d.msg); return; }
      if (folder) { st.open[folder] = true; keep("phil.chatFolders", JSON.stringify(st.open)); }
      tell({ type: "phil-chat-moved", id: id, folder: folder });
      refresh();
    });
  }
  function deleteChat(id) {
    api("delete", { id: id }).then(function (d) {
      if (!d.ok) { toast(d.msg); return; }
      tell({ type: "phil-chat-deleted", id: id });
      toast("Deleted. “Recently deleted” at the bottom puts it back.");
      refresh();
    });
  }
  function newFolder(moveId) {
    var name = "New folder", n = 2;
    while (st.folders.indexOf(name) >= 0) name = "New folder " + n++;
    api("folder_create", { name: name }).then(function () {
      st.open[name] = true; keep("phil.chatFolders", JSON.stringify(st.open));
      return moveId ? api("move", { id: moveId, folder: name }) : null;
    }).then(refresh).then(function () {
      var r = findRow("folder", name);
      if (r) inlineEdit(r, name, function (v) { api("folder_rename", { old: name, new: v }).then(refresh); });
    });
  }
  $("cp-newfolder").addEventListener("click", function () { newFolder(null); });

  /* drag a chat onto a folder (or onto the chat list's empty space for no folder) */
  list.addEventListener("dragstart", function (ev) {
    var r = ev.target.closest(".cp-row[data-id]");
    if (r) ev.dataTransfer.setData("text/x-chat", r.dataset.id);
  });
  list.addEventListener("dragover", function (ev) {
    var t = ev.target.closest(".cp-row.folder");
    list.querySelectorAll(".drop").forEach(function (e) { if (e !== t) e.classList.remove("drop"); });
    if (t) { ev.preventDefault(); t.classList.add("drop"); }
  });
  list.addEventListener("drop", function (ev) {
    var t = ev.target.closest(".cp-row.folder"), id = ev.dataTransfer.getData("text/x-chat");
    list.querySelectorAll(".drop").forEach(function (e) { e.classList.remove("drop"); });
    if (t && id) { ev.preventDefault(); moveChat(id, t.dataset.folder); }
  });

  /* ---------- search: titles at once, the conversations after a pause ---------- */
  var sTimer = null;
  $("cp-q").addEventListener("input", function () {
    st.q = this.value.trim(); st.hits = null; st.trash = false;
    render();
    clearTimeout(sTimer);
    if (st.q.length >= 2) sTimer = setTimeout(function () {
      var q = st.q;
      api("search", { q: q }).then(function (d) { if (st.q === q) { st.hits = d.chats || []; render(); } });
    }, 250);
  });
  $("cp-trash").addEventListener("click", function () {
    st.trash = !st.trash;
    this.textContent = st.trash ? "← Back to chats" : "Recently deleted";
    render();
  });

  /* ---------- the chat page tells us what happened ---------- */
  window.addEventListener("message", function (ev) {
    if (ev.origin !== location.origin || ev.source !== frame.contentWindow || !ev.data) return;
    var m = ev.data;
    if (m.type === "phil-chat-ready") {
      st.ready = true;
      refresh().then(function () {
        var last = load("phil.chat", "");
        if (last && st.chats.some(function (c) { return c.id === last; })) tell({ type: "phil-chat-open", id: last });
      });
    }
    if (m.type === "phil-chat-opened") {
      st.cur = m.id || null;
      keep("phil.chat", st.cur || "");
      render();
    }
    if (m.type === "phil-chat-saved") {
      st.cur = m.id;
      keep("phil.chat", m.id);
      refresh();
    }
    if (m.type === "phil-busy") toast("Philibert is still answering. Wait for it, or press Stop, then switch chats.");
  });
  refresh();
})();
