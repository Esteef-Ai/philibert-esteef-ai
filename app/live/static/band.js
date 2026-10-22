/* Philibert Band Manager: gigs, venues, contacts, songs, setlists, merch, money,
 * reminders - one SQLite file on the drive (nd_band.py, /api/band). Forms are
 * built from FIELDS; deleting goes to the Trash view, from where it comes back.
 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var view = $("view"), nav = $("nav");
  var cache = {}, cur = "overview";
  var CUR = (function () { try { return localStorage.getItem("band.currency") || "$"; } catch (e) { return "$"; } })();

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function api(op, data) {
    return fetch("/api/band", { method: "POST", headers: { "Content-Type": "application/json" },
                                body: JSON.stringify(Object.assign({ op: op }, data || {})) }).then(function (r) { return r.json(); });
  }
  function toast(m) { var t = $("toast"); t.textContent = m; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove("on"); }, 2600); }
  function money(v) { return v == null ? "" : CUR + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function mmss(s) { s = +s || 0; return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }
  function today() { var d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
  function nice(d) {
    if (!d) return "";
    var x = new Date(d + "T12:00:00");
    return isNaN(x) ? d : x.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  }
  function load(t) { return api("list", { table: t }).then(function (d) { cache[t] = d.rows || []; return cache[t]; }); }
  function byId(t, id) { return (cache[t] || []).find(function (r) { return r.id === id; }); }
  function label(t, r) {
    if (!r) return "";
    if (t === "gigs") return r.title || ("Gig at " + ((byId("venues", r.venue_id) || {}).name || "TBA"));
    return r.name || r.title || r.text || ("#" + r.id);
  }

  /* ---------- what each list holds ---------- */
  var FIELDS = {
    gigs: [["date", "Date", "date"], ["title", "Name (optional)", "text"], ["venue_id", "Venue", "ref:venues"],
           ["status", "Status", "select:idea,hold,confirmed,played,cancelled"], ["fee", "Fee", "money"],
           ["deposit_paid", "Deposit paid", "check"], ["load_in", "Load-in", "time"], ["set_time", "Set time", "time"],
           ["set_length", "Set length (minutes)", "number"], ["setlist_id", "Setlist", "ref:setlists"],
           ["contact_id", "Contact", "ref:contacts"], ["notes", "Notes", "area"]],
    venues: [["name", "Name", "text"], ["address", "Address", "text"], ["city", "City", "text"], ["capacity", "Capacity", "number"],
             ["contact_id", "Contact", "ref:contacts"], ["notes", "Notes", "area"]],
    contacts: [["name", "Name", "text"], ["role", "Role (booker, sound, promoter...)", "text"], ["phone", "Phone", "text"],
               ["email", "Email", "text"], ["notes", "Notes", "area"]],
    songs: [["title", "Title", "text"], ["key", "Key", "text"], ["bpm", "BPM", "number"], ["length_sec", "Length (m:ss)", "mmss"], ["notes", "Notes", "area"]],
    merch: [["name", "Item", "text"], ["variant", "Size / colour", "text"], ["price", "Price", "money"], ["cost", "Cost each", "money"],
            ["stock", "In stock", "number"], ["notes", "Notes", "area"]],
    money: [["date", "Date", "date"], ["kind", "Type", "select:income,expense"], ["amount", "Amount", "money"],
            ["category", "Category (fee, gas, gear, food...)", "text"], ["gig_id", "Gig", "ref:gigs"], ["note", "Note", "text"]],
    reminders: [["text", "Reminder", "text"], ["due", "Due", "date"], ["gig_id", "Gig", "ref:gigs"], ["done", "Done", "check"]],
    setlists: [["name", "Name", "text"], ["notes", "Notes", "area"]],
  };
  var COLS = {
    gigs: [["date", "Date", function (r) { return nice(r.date); }], ["title", "Gig", function (r) { return esc(label("gigs", r)); }],
           ["status", "Status", function (r) { return '<span class="pill ' + esc(r.status) + '">' + esc(r.status) + "</span>"; }],
           ["set_time", "Set", function (r) { return esc(r.set_time || ""); }], ["fee", "Fee", function (r) { return money(r.fee); }, "num"]],
    venues: [["name", "Venue"], ["city", "City"], ["capacity", "Capacity", null, "num"], ["contact_id", "Contact", function (r) { return esc(label("contacts", byId("contacts", r.contact_id))); }]],
    contacts: [["name", "Name"], ["role", "Role"], ["phone", "Phone"], ["email", "Email"]],
    songs: [["title", "Song"], ["key", "Key"], ["bpm", "BPM", null, "num"], ["length_sec", "Length", function (r) { return r.length_sec ? mmss(r.length_sec) : ""; }, "num"]],
    merch: [["name", "Item"], ["variant", "Variant"], ["price", "Price", function (r) { return money(r.price); }, "num"],
            ["stock", "Stock", function (r) { return '<span style="color:' + ((r.stock || 0) <= 5 ? "var(--amber)" : "inherit") + '">' + (r.stock == null ? "" : r.stock) + "</span>"; }, "num"]],
    money: [["date", "Date", function (r) { return nice(r.date); }], ["kind", "Type", function (r) { return '<span class="pill ' + r.kind + '">' + r.kind + "</span>"; }],
            ["category", "Category"], ["gig_id", "Gig", function (r) { return esc(label("gigs", byId("gigs", r.gig_id))); }],
            ["amount", "Amount", function (r) { return (r.kind === "expense" ? "−" : "") + money(r.amount); }, "num"]],
    reminders: [["done", "", function (r) { return '<input type="checkbox" data-done="' + r.id + '"' + (r.done ? " checked" : "") + ">"; }],
                ["text", "Reminder"], ["due", "Due", function (r) { return nice(r.due); }]],
  };
  var NAV = [["overview", "Overview", "M3 12l9-8 9 8v8a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"],
             ["gigs", "Gigs", "M4 5h16v15H4zM4 9h16M8 3v4M16 3v4"],
             ["setlists", "Setlists", "M5 6h14M5 12h14M5 18h9"],
             ["songs", "Songs", "M9 18V5l12-2v13M9 18a3 3 0 1 1-3-3 3 3 0 0 1 3 3zM21 16a3 3 0 1 1-3-3 3 3 0 0 1 3 3z"],
             ["venues", "Venues", "M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11zM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"],
             ["contacts", "Contacts", "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.9"],
             ["merch", "Merch", "M4 7l4-3h8l4 3-3 3v10H7V10z"],
             ["money", "Money", "M12 2v20M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"],
             ["reminders", "Reminders", "M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0"],
             ["-"], ["trash", "Trash", "M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15"]];
  var TITLES = { gigs: "gig", venues: "venue", contacts: "contact", songs: "song", merch: "item", money: "entry", reminders: "reminder", setlists: "setlist" };

  function renderNav(counts) {
    nav.innerHTML = NAV.map(function (n) {
      if (n[0] === "-") return '<div class="sep"></div>';
      var c = counts && counts[n[0]] != null ? '<span class="n">' + counts[n[0]] + "</span>" : "";
      return '<a data-v="' + n[0] + '" class="' + (n[0] === cur ? "on" : "") + '"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="' + n[2] + '"/></svg>' + n[1] + c + "</a>";
    }).join("");
  }
  nav.addEventListener("click", function (ev) { var a = ev.target.closest("a[data-v]"); if (a) go(a.dataset.v); });

  function go(v) {
    cur = v;
    try { localStorage.setItem("band.view", v); } catch (e) { /* private */ }
    closeDrawer();
    nav.querySelectorAll("a").forEach(function (a) { a.classList.toggle("on", a.dataset.v === v); });
    if (v === "overview") return overview();
    if (v === "setlists") return setlists();
    if (v === "trash") return trash();
    return listView(v);
  }

  /* ---------- overview ---------- */
  function overview() {
    Promise.all([api("overview"), load("venues")]).then(function (r) {
      var o = r[0];
      renderNav(o.counts);
      var card = function (title, body) { return '<div class="card"><h2>' + title + "</h2>" + body + "</div>"; };
      view.innerHTML = "<h1>Overview</h1><p class=\"lead\">What is coming up, what needs doing, and how the year is going.</p><div class=\"grid\">" +
        card("Next gigs", o.upcoming.length ? o.upcoming.map(function (g) {
          return '<div class="li" data-gig="' + g.id + '"><span class="when">' + esc(nice(g.date)) + '</span><span class="what">' +
                 esc(g.title || ("Gig at " + (g.venue || "TBA"))) + '</span><span class="pill ' + esc(g.status) + '">' + esc(g.status) + "</span></div>";
        }).join("") : '<div class="empty">No gigs booked yet. + NEW GIG at the top right.</div>') +
        card("Due this week", o.due.length ? o.due.map(function (x) {
          return '<div class="li"><input type="checkbox" data-done="' + x.id + '"><span class="what">' + esc(x.text) + '</span><span class="when">' + esc(nice(x.due)) + "</span></div>";
        }).join("") : '<div class="empty">Nothing due. Nice.</div>') +
        card(o.year, '<div class="money3"><div><small>In</small><div class="big good">' + money(o.income) + "</div></div>" +
             '<div><small>Out</small><div class="big bad">' + money(o.expenses) + "</div></div>" +
             '<div><small>Kept</small><div class="big">' + money(o.net) + "</div></div></div>" +
             (o.merch_income ? '<p class="lead" style="margin:8px 0 0">' + money(o.merch_income) + " of it from merch.</p>" : "")) +
        card("Not paid yet", o.unpaid.length ? o.unpaid.map(function (g) {
          return '<div class="li"><span class="when">' + esc(nice(g.date)) + '</span><span class="what">' + esc(g.venue || g.title || "Gig") +
                 "</span>" + '<button class="btn small" data-paid="' + g.id + '" data-fee="' + g.fee + '">LOG ' + esc(money(g.fee)) + "</button></div>";
        }).join("") : '<div class="empty">Every played gig is paid.</div>') +
        card("Low stock", o.low_stock.length ? o.low_stock.map(function (m) {
          return '<div class="li"><span class="what">' + esc(m.name + (m.variant ? " · " + m.variant : "")) + '</span><span class="when" style="color:var(--amber)">' + (m.stock || 0) + " left</span></div>";
        }).join("") : '<div class="empty">Plenty of everything.</div>') +
        "</div>";
    });
  }

  /* ---------- a list ---------- */
  var search = {};
  function listView(t) {
    Promise.all([load(t), load("venues"), load("contacts"), load("gigs"), load("setlists")]).then(function () {
      var rows = cache[t], q = (search[t] || "").toLowerCase();
      if (q) rows = rows.filter(function (r) { return JSON.stringify(r).toLowerCase().indexOf(q) >= 0; });
      var name = NAV.find(function (n) { return n[0] === t; })[1];
      var totals = "";
      if (t === "money") {
        var inn = 0, out = 0;
        rows.forEach(function (r) { if (r.kind === "expense") out += r.amount || 0; else inn += r.amount || 0; });
        totals = '<p class="lead">In ' + money(inn) + " · Out " + money(out) + " · Kept <b>" + money(inn - out) + "</b></p>";
      }
      view.innerHTML = "<h1>" + name + '<button class="btn primary" data-new="' + t + '">+ NEW ' + TITLES[t].toUpperCase() + "</button></h1>" + totals +
        '<div class="toolbar"><input type="search" id="q" placeholder="Search ' + name.toLowerCase() + '" value="' + esc(search[t] || "") + '"></div>' +
        (rows.length ? "<table><thead><tr>" + COLS[t].map(function (c) { return '<th class="' + (c[3] || "") + '">' + c[1] + "</th>"; }).join("") +
          "</tr></thead><tbody>" + rows.map(function (r) {
            return '<tr data-id="' + r.id + '">' + COLS[t].map(function (c) {
              return '<td class="' + (c[3] || "") + '">' + (c[2] ? c[2](r) : esc(r[c[0]] == null ? "" : r[c[0]])) + "</td>";
            }).join("") + "</tr>";
          }).join("") + "</tbody></table>" : '<p class="empty">Nothing here yet.</p>');
      var qi = $("q");
      qi.addEventListener("input", function () { search[t] = qi.value; listView(t); setTimeout(function () { var x = $("q"); x.focus(); x.setSelectionRange(x.value.length, x.value.length); }); });
      view.querySelectorAll("tbody tr").forEach(function (tr) {
        tr.addEventListener("click", function (ev) { if (ev.target.matches("input")) return; edit(t, byId(t, +tr.dataset.id)); });
      });
    });
  }

  /* ---------- the editor drawer ---------- */
  var drawer = $("drawer");
  function closeDrawer() { drawer.classList.remove("on"); }
  $("d-close").addEventListener("click", closeDrawer);
  addEventListener("keydown", function (ev) { if (ev.key === "Escape") closeDrawer(); });

  function input(f, v) {
    var k = f[0], kind = f[2];
    if (kind === "area") return '<textarea name="' + k + '">' + esc(v || "") + "</textarea>";
    if (kind === "check") return '<label><input type="checkbox" name="' + k + '"' + (v ? " checked" : "") + "> " + f[1] + "</label>";
    if (kind.indexOf("select:") === 0) return '<select name="' + k + '">' + kind.slice(7).split(",").map(function (o) {
      return "<option" + (o === v ? " selected" : "") + ">" + o + "</option>"; }).join("") + "</select>";
    if (kind.indexOf("ref:") === 0) {
      var t = kind.slice(4);
      return '<select name="' + k + '"><option value="">-</option>' + (cache[t] || []).map(function (r) {
        return '<option value="' + r.id + '"' + (r.id === v ? " selected" : "") + ">" + esc(label(t, r)) + (t === "gigs" ? " · " + esc(nice(r.date)) : "") + "</option>";
      }).join("") + "</select>";
    }
    if (kind === "mmss") return '<input name="' + k + '" placeholder="3:45" value="' + (v ? mmss(v) : "") + '">';
    var type = { date: "date", time: "time", number: "number", money: "number" }[kind] || "text";
    return '<input name="' + k + '" type="' + type + '"' + (kind === "money" ? ' step="0.01"' : "") + ' value="' + esc(v == null ? "" : v) + '">';
  }
  function read(t) {
    var row = {};
    FIELDS[t].forEach(function (f) {
      var el = drawer.querySelector('[name="' + f[0] + '"]');
      if (!el) return;
      if (f[2] === "check") row[f[0]] = el.checked ? 1 : 0;
      else if (f[2] === "mmss") { var m = /^(\d+)(?::(\d{1,2}))?$/.exec(el.value.trim()); row[f[0]] = m ? (+m[1]) * (m[2] != null ? 60 : 1) + (+(m[2] || 0)) : null; }
      else if (f[2].indexOf("ref:") === 0) row[f[0]] = el.value ? +el.value : null;
      else row[f[0]] = el.value;
    });
    return row;
  }
  function edit(t, r, preset) {
    r = r || {};
    var isNew = !r.id;
    var vals = Object.assign({}, preset || {}, r);
    if (isNew && t === "gigs" && !vals.date) vals.date = today();
    if (isNew && (t === "money") && !vals.date) vals.date = today();
    $("d-title").textContent = (isNew ? "New " : "") + (isNew ? TITLES[t] : label(t, r));
    var fields = FIELDS[t].map(function (f) {
      return '<div class="field' + (f[2] === "check" ? " check" : "") + '">' + (f[2] === "check" ? "" : "<label>" + f[1] + "</label>") + input(f, vals[f[0]]) + "</div>";
    });
    $("d-body").innerHTML = fields.join("") + (!isNew && t === "gigs" ? '<div class="extras">' +
      '<button class="btn small" data-x="ics">ADD TO CALENDAR</button><button class="btn small" data-x="sheet">MAKE A GIG SHEET NOTE</button>' +
      '<button class="btn small" data-x="paid">LOG PAYMENT</button><button class="btn small" data-x="remind">ADD REMINDER</button></div>' : "") +
      (!isNew && t === "merch" ? '<div class="extras"><button class="btn small" data-x="sell">SELL ONE</button></div>' : "");
    $("d-foot").innerHTML = '<button class="btn primary" data-x="save">SAVE</button>' + (isNew ? "" : '<button class="btn danger" data-x="del">DELETE</button>');
    drawer.classList.add("on");
    drawer.onclick = function (ev) {
      var b = ev.target.closest("[data-x]");
      if (!b) return;
      var x = b.dataset.x;
      if (x === "save") {
        var row = read(t);
        if (!isNew) row.id = r.id;
        api("save", { table: t, row: row }).then(function (d) {
          if (!d.ok) { toast(d.msg); return; }
          toast("Saved."); closeDrawer(); go(cur === "overview" ? "overview" : cur);
        });
      }
      if (x === "del") api("delete", { table: t, id: r.id }).then(function () { toast("Moved to Trash."); closeDrawer(); go(cur); });
      if (x === "ics") api("ics", { id: r.id }).then(function (d) {
        if (!d.ok) { toast(d.msg); return; }
        var a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([d.ics], { type: "text/calendar" }));
        a.download = (label("gigs", r) + " " + r.date).replace(/[^\w .-]+/g, "") + ".ics";
        a.click();
        toast("Calendar file saved - open it to add the gig to any calendar.");
      });
      if (x === "paid") logPaid(r.id, r.fee);
      if (x === "remind") edit("reminders", null, { gig_id: r.id, due: r.date, text: "Confirm details for " + label("gigs", r) });
      if (x === "sheet") gigSheet(r);
      if (x === "sell") api("save", { table: "sales", row: { merch_id: r.id, qty: 1, price: r.price } }).then(function () { toast("Sold one."); closeDrawer(); go(cur); });
    };
    var first = drawer.querySelector("input:not([type=checkbox]), select, textarea");
    if (first && isNew) first.focus();
  }
  function logPaid(gid, fee) {
    api("save", { table: "money", row: { kind: "income", amount: fee || 0, category: "Fee", gig_id: gid, date: today() } }).then(function (d) {
      toast(d.ok ? "Payment logged." : d.msg); go(cur);
    });
  }
  function gigSheet(g) {
    var venue = byId("venues", g.venue_id) || {};
    var title = "Gig - " + (venue.name || g.title || "TBA") + " " + g.date;
    fetch("/api/notes", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "create", folder: "Gigs", title: title, template: "Templates/Gig sheet template.md" }) })
      .then(function (r) { return r.json(); }).then(function (d) {
        if (!d.ok) { toast(d.msg || "Could not make the note."); return; }
        // fill the sheet with what the gig already knows
        var N = function (op, x) {
          return fetch("/api/notes", { method: "POST", headers: { "Content-Type": "application/json" },
                                       body: JSON.stringify(Object.assign({ op: op }, x)) }).then(function (r) { return r.json(); });
        };
        var contact = byId("contacts", g.contact_id || venue.contact_id) || {};
        var fill = {
          "Venue / address": [venue.name, venue.address, venue.city].filter(Boolean).join(", "),
          "Contact": [contact.name, contact.phone, contact.email].filter(Boolean).join(" · "),
          "Load-in": g.load_in || "", "Set time": g.set_time || "",
          "Set length": g.set_length ? g.set_length + " min" : "", "Pay": g.fee ? money(g.fee) : "",
        };
        N("read", { id: d.id }).then(function (n) {
          var body = n.body.replace(/^date: .*$/m, "date: " + g.date);
          Object.keys(fill).forEach(function (k) {
            if (fill[k]) body = body.replace("| **" + k + "** | |", "| **" + k + "** | " + fill[k].replace(/\|/g, "/") + " |");
          });
          return N("save", { id: d.id, body: body, hash: n.hash });
        }).then(function () {
          toast("Gig sheet made in Notes: " + d.title);
          window.open("/notes#" + encodeURIComponent(d.id), "philibert-notes", "popup,width=1320,height=880");
        });
      });
  }
  $("new-gig").addEventListener("click", function () { Promise.all([load("venues"), load("contacts"), load("setlists")]).then(function () { edit("gigs"); }); });
  view.addEventListener("click", function (ev) {
    var n = ev.target.closest("[data-new]");
    if (n) { edit(n.dataset.new); return; }
    var g = ev.target.closest("[data-gig]");
    if (g) { Promise.all([load("gigs"), load("contacts"), load("setlists")]).then(function () { edit("gigs", byId("gigs", +g.dataset.gig)); }); return; }
    var p = ev.target.closest("[data-paid]");
    if (p) logPaid(+p.dataset.paid, +p.dataset.fee);
  });
  view.addEventListener("change", function (ev) {
    var d = ev.target.closest("[data-done]");
    if (d) api("save", { table: "reminders", row: { id: +d.dataset.done, done: d.checked ? 1 : 0 } }).then(function () { if (cur === "overview") overview(); });
  });

  /* ---------- setlists: drag songs into order ---------- */
  var openSl = null;
  function setlists() {
    Promise.all([load("setlists"), load("songs")]).then(function () {
      if (!openSl && cache.setlists.length) openSl = cache.setlists[0].id;
      view.innerHTML = '<h1>Setlists<button class="btn primary" data-new="setlists">+ NEW SETLIST</button></h1>' +
        '<p class="lead">Drag songs from your library into a setlist, and drag them again to change the order.</p>' +
        '<div class="sl"><div class="card"><h2>Setlists</h2><div id="sl-list"></div></div>' +
        '<div class="card"><h2 id="sl-name">-</h2><div id="sl-songs"></div><p class="total" id="sl-total"></p></div>' +
        '<div class="card"><h2>Song library <button class="btn small" data-new="songs" style="float:right;margin-top:-4px">+ SONG</button></h2><div id="sl-lib"></div></div></div>';
      $("sl-list").innerHTML = cache.setlists.map(function (s) {
        return '<div class="li" data-sl="' + s.id + '" style="' + (s.id === openSl ? "color:#fff;font-weight:600" : "") + '"><span class="what">' + esc(s.name) + "</span>" +
               '<button class="btn small" data-sledit="' + s.id + '">EDIT</button></div>';
      }).join("") || '<div class="empty">Make your first setlist.</div>';
      $("sl-lib").innerHTML = cache.songs.map(function (s) {
        return '<div class="song" draggable="true" data-song="' + s.id + '"><span class="t">' + esc(s.title) + '</span><span class="k">' +
               esc(s.key || "") + " " + (s.length_sec ? mmss(s.length_sec) : "") + '</span><button class="x" data-add="' + s.id + '" title="Add to the setlist">+</button></div>';
      }).join("") || '<div class="empty">Add the songs you play.</div>';
      showSetlist();
    });
  }
  var slSongs = [];
  function showSetlist() {
    if (!openSl) { $("sl-songs").innerHTML = ""; return; }
    api("setlist", { id: openSl }).then(function (d) {
      if (!d.ok) return;
      slSongs = d.setlist.songs.map(function (s) { return s.id; });
      $("sl-name").textContent = d.setlist.name;
      $("sl-songs").innerHTML = d.setlist.songs.map(function (s, i) {
        return '<div class="song" draggable="true" data-pos="' + i + '"><span class="no">' + (i + 1) + '</span><span class="t">' + esc(s.title) +
               '</span><span class="k">' + esc(s.key || "") + " " + (s.length_sec ? mmss(s.length_sec) : "") + '</span><button class="x" data-rm="' + i + '" title="Take it out">✕</button></div>';
      }).join("") || '<div class="empty">Drag songs here.</div>';
      $("sl-total").textContent = d.setlist.songs.length ? d.setlist.songs.length + " songs · " + mmss(d.setlist.total_sec) + " total" : "";
    });
  }
  function saveOrder() { api("setlist_songs", { id: openSl, songs: slSongs }).then(showSetlist); }
  var dragFrom = null;
  view.addEventListener("dragstart", function (ev) {
    var s = ev.target.closest(".song");
    if (!s) return;
    dragFrom = s.dataset.pos != null ? { pos: +s.dataset.pos } : { song: +s.dataset.song };
    s.classList.add("drag");
  });
  view.addEventListener("dragend", function () { view.querySelectorAll(".drag,.over").forEach(function (e) { e.classList.remove("drag", "over"); }); });
  view.addEventListener("dragover", function (ev) {
    if (!dragFrom || !ev.target.closest("#sl-songs")) return;
    ev.preventDefault();
    view.querySelectorAll(".over").forEach(function (e) { e.classList.remove("over"); });
    var s = ev.target.closest("#sl-songs .song"); if (s) s.classList.add("over");
  });
  view.addEventListener("drop", function (ev) {
    if (!dragFrom || !ev.target.closest("#sl-songs") || !openSl) return;
    ev.preventDefault();
    var s = ev.target.closest("#sl-songs .song"), at = s ? +s.dataset.pos : slSongs.length;
    if (dragFrom.pos != null) { var moved = slSongs.splice(dragFrom.pos, 1)[0]; if (dragFrom.pos < at) at--; slSongs.splice(at, 0, moved); }
    else slSongs.splice(at, 0, dragFrom.song);
    dragFrom = null;
    saveOrder();
  });
  view.addEventListener("click", function (ev) {
    var a = ev.target.closest("[data-add]");
    if (a && openSl) { slSongs.push(+a.dataset.add); saveOrder(); return; }
    var rm = ev.target.closest("[data-rm]");
    if (rm) { slSongs.splice(+rm.dataset.rm, 1); saveOrder(); return; }
    var se = ev.target.closest("[data-sledit]");
    if (se) { ev.stopPropagation(); edit("setlists", byId("setlists", +se.dataset.sledit)); return; }
    var sl = ev.target.closest("[data-sl]");
    if (sl) { openSl = +sl.dataset.sl; setlists(); }
  });

  /* ---------- trash ---------- */
  function trash() {
    api("trash").then(function (d) {
      var items = [];
      Object.keys(d.rows || {}).forEach(function (t) { (d.rows[t] || []).forEach(function (r) { items.push({ t: t, r: r }); }); });
      items.sort(function (a, b) { return b.r.updated - a.r.updated; });
      view.innerHTML = '<h1>Trash</h1><p class="lead">Everything you deleted waits here. Put it back any time.</p>' +
        (items.length ? "<table><thead><tr><th>What</th><th>Kind</th><th></th></tr></thead><tbody>" + items.map(function (x) {
          return "<tr><td>" + esc(label(x.t, x.r)) + "</td><td>" + esc(TITLES[x.t] || x.t) + '</td><td class="num"><button class="btn small" data-restore="' +
                 x.t + ":" + x.r.id + '">PUT BACK</button></td></tr>';
        }).join("") + "</tbody></table>" : '<p class="empty">The trash is empty.</p>');
    });
  }
  view.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-restore]");
    if (!b) return;
    var p = b.dataset.restore.split(":");
    api("restore", { table: p[0], id: +p[1] }).then(function () { toast("Put back."); trash(); });
  });

  /* ---------- start ---------- */
  api("overview").then(function (o) { renderNav(o.counts); });
  var start = "overview";
  try { start = localStorage.getItem("band.view") || "overview"; } catch (e) { /* private */ }
  go(NAV.some(function (n) { return n[0] === start; }) ? start : "overview");
})();
