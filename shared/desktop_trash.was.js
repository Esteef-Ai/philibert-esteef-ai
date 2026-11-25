  // Permanent: each source deletes for good what its trash holds (one item, or all)
  function purge(x) {
    return x.kind === "note" ? api("/api/notes", { op: "purge", name: x.key })
      : x.kind === "band" ? api("/api/band", Object.assign({ op: "purge" }, bandKey(x.key)))
      : x.kind === "file" ? api("/api/files", { op: "purge", id: x.key })
      : api("/api/chats", { op: "purge", id: x.key });
  }
  function emptyTrash() {
    trashSources().then(function (r) {
      var n = (r[0].items || []).length + (r[1].chats || []).length + bandRows(r[2]).length + (r[3].items || []).length;
      if (!n) { msgbox("Empty Trash", "The Trash is already empty.", "info"); return; }
      if (!confirm("Delete the " + n + " item" + (n === 1 ? "" : "s") + " in the Trash for good?\n\nThis can't be undone.")) return;
      Promise.all([api("/api/notes", { op: "purge" }), api("/api/chats", { op: "purge" }),
                   api("/api/band", { op: "purge", all_bands: true }), api("/api/files", { op: "purge" })].map(function (p) { return p.catch(function () { return {}; }); }))
        .then(function () { S.play("ding"); loadTrash(); updateTrashIcon(); });
    });
  }
  // the Band Manager's deleted rows, as Trash rows: what it was, and which list it came from
  var BAND_LISTS = { gigs: "Gigs", tours: "Tours", venues: "Venues", contacts: "Contacts", suppliers: "Suppliers", songs: "Songs",
                     setlists: "Setlists", merch: "Merch", money: "Money", bills: "Bills", reminders: "Reminders", sales: "Sales" };
  function bandRows(d) {
    var out = [], bands = (d && d.bands) || (d && d.rows ? [{ id: "", name: "", rows: d.rows }] : []);
    bands.forEach(function (b) {
      Object.keys(b.rows || {}).forEach(function (t) {
        (b.rows[t] || []).forEach(function (r) {
          var name = r.name || r.title || r.text || r.what ||
                     (t === "gigs" ? "Gig on " + r.date : t === "money" ? (r.kind || "entry") + " " + (r.amount || "") + " " + (r.category || "") : "#" + r.id);
          out.push({ kind: "band", key: b.id + "|" + t + ":" + r.id, name: name,
                     from: "Band Manager \u203a " + (bands.length > 1 && b.name ? b.name + " \u203a " : "") + (BAND_LISTS[t] || t), at: r.updated || 0 });
        });
      });
    });
    return out;
  }
  function bandKey(k) { var b = k.split("|"), t = b[1].split(":"); return { band: b[0], table: t[0], id: +t[1] }; }
  function trashSources() {
    return Promise.all([api("/api/notes", { op: "trash_list" }).catch(function () { return {}; }),
                        api("/api/chats", { op: "trash_list" }).catch(function () { return {}; }),
                        api("/api/band", { op: "trash", all_bands: true }).catch(function () { return {}; }),
                        api("/api/files", { op: "trash_list" }).catch(function () { return {}; })]);
  }
  function loadTrash() {
    trashSources().then(function (r) {
      var rows = (r[0].items || []).map(function (n) {
        return { kind: "note", key: n.name, name: n.title, from: (n.from || "").split("/").slice(0, -1).join("/") || "Notes", at: n.at };
      }).concat((r[1].chats || []).map(function (c) {
        return { kind: "chat", key: c.id, name: c.title, from: c.folder || "Chats", at: c.updated };
      })).concat(bandRows(r[2])).concat((r[3].items || []).map(function (f) {
        return { kind: "file", key: f.id, name: f.name, from: "Files \u203a " + (f.from || "Philibert"), at: f.at };
      })).sort(function (a, b) { return b.at - a.at; });
      var el = $("trash-rows");
      if (!el) return;
      el.innerHTML = rows.map(function (x, i) {
        return '<div class="row" data-i="' + i + '" title="Double-click to put it back"><span class="n">' +
               I.svg(x.kind === "note" ? "notes" : x.kind === "band" ? "band" : x.kind === "file" ? "files" : "chat", 16) + esc(x.name) + "</span><span>" + esc(x.from) +
               "</span><span>" + esc(new Date(x.at * 1000).toLocaleDateString()) + "</span></div>";
      }).join("");
      $("trash-status").textContent = rows.length + " object(s). Double-click one to put it back; right-click to delete it for good.";
      el.oncontextmenu = function (ev) {
        var row = ev.target.closest("[data-i]");
        if (!row) return;
        ev.preventDefault();
        var x = rows[+row.dataset.i];
        dropMenu(row, [{ label: "Put back", run: function () { row.dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); } }, "-",
          { label: "Delete forever", run: function () {
            if (!confirm('Delete "' + x.name + '" for good? This can\'t be undone.')) return;
            purge(x).then(function () { loadTrash(); updateTrashIcon(); });
          } }]);
        fly.style.left = Math.min(ev.clientX, innerWidth - fly.offsetWidth - 4) + "px";
        fly.style.top = Math.min(ev.clientY, innerHeight - fly.offsetHeight - 4) + "px";
      };
      el.ondblclick = function (ev) {
        var row = ev.target.closest("[data-i]");
        if (!row) return;
        var x = rows[+row.dataset.i];
        (x.kind === "note" ? api("/api/notes", { op: "restore", name: x.key })
         : x.kind === "band" ? api("/api/band", Object.assign({ op: "restore" }, bandKey(x.key)))
         : x.kind === "file" ? api("/api/files", { op: "restore", id: x.key })
         : api("/api/chats", { op: "restore", id: x.key }))
          .then(function () { S.play("ding"); loadTrash(); updateTrashIcon(); });
      };
      setTrashIcon(rows.length > 0);
    });
  }
  function setTrashIcon(full) {
    var d = iconsEl.querySelector('[data-id="trash"] .img');
    if (d) d.innerHTML = I.svg(full ? "trash_full" : "trash", 32);
  }
  function updateTrashIcon() {
    trashSources().then(function (r) {
      setTrashIcon(((r[0].items || []).length + (r[1].chats || []).length + bandRows(r[2]).length + (r[3].items || []).length) > 0);
    });
  }
