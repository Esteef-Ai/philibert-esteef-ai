/* Philibert Band Manager: gigs, tours, venues, contacts, suppliers, songs,
 * setlists, merch, money, bills, reminders - one SQLite file on the drive
 * (nd_band.py, /api/band). Forms are built from FIELDS; deleting goes to the
 * Trash view, from where it comes back. The currency lives in the band file, so
 * the chat and this page always agree on it.
 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var view = $("view"), nav = $("nav");
  var cache = {}, cur = "overview";
  var CURRENCY = "USD", FMT = null;
  function setCurrency(code) {
    CURRENCY = code || "USD";
    try { FMT = new Intl.NumberFormat(undefined, { style: "currency", currency: CURRENCY }); } catch (e) { FMT = null; }
  }
  setCurrency("USD");

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
  function money(v) {
    if (v == null) return "";
    return FMT ? FMT.format(Number(v)) : CURRENCY + " " + Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
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
    if (t === "bills") return r.what || ((byId("suppliers", r.supplier_id) || {}).name || "Bill");
    return r.name || r.title || r.text || ("#" + r.id);
  }

  /* ---------- what each list holds ---------- */
  var FIELDS = {
    gigs: [["date", "Date", "date"], ["title", "Name (optional)", "text"], ["venue_id", "Venue", "ref:venues"],
           ["status", "Status", "select:idea,hold,confirmed,played,cancelled"], ["fee", "Fee", "money"],
           ["deposit_paid", "Deposit paid", "check"], ["load_in", "Load-in", "time"], ["set_time", "Set time", "time"],
           ["set_length", "Set length (minutes)", "number"], ["setlist_id", "Setlist", "ref:setlists"],
           ["contact_id", "Contact", "ref:contacts"], ["tour_id", "Tour", "ref:tours"], ["notes", "Notes", "area"]],
    venues: [["name", "Name", "text"], ["address", "Address", "text"], ["city", "City", "text"], ["capacity", "Capacity", "number"],
             ["contact_id", "Contact", "ref:contacts"], ["notes", "Notes", "area"]],
    contacts: [["name", "Name", "text"], ["role", "Role (booker, sound, promoter...)", "text"], ["phone", "Phone", "text"],
               ["email", "Email", "text"], ["notes", "Notes", "area"]],
    songs: [["title", "Title", "text"], ["key", "Key", "text"], ["bpm", "BPM", "number"], ["length_sec", "Length (m:ss)", "mmss"], ["notes", "Notes", "area"]],
    merch: [["name", "Item", "text"], ["variant", "Size / colour", "text"], ["price", "Price", "money"], ["cost", "Cost each", "money"],
            ["stock", "In stock", "number"], ["supplier_id", "Made by", "ref:suppliers"], ["notes", "Notes", "area"]],
    money: [["date", "Date", "date"], ["kind", "Type", "select:income,expense"], ["amount", "Amount", "money"],
            ["category", "Category (fee, gas, gear, food...)", "text"], ["gig_id", "Gig", "ref:gigs"], ["tour_id", "Tour", "ref:tours"],
            ["supplier_id", "Supplier", "ref:suppliers"], ["note", "Note", "text"]],
    reminders: [["text", "Reminder", "text"], ["due", "Due", "date"], ["gig_id", "Gig", "ref:gigs"], ["done", "Done", "check"]],
    setlists: [["name", "Name", "text"], ["notes", "Notes", "area"]],
    tours: [["name", "Name", "text"], ["starts", "Starts (optional - the first gig)", "date"],
            ["ends", "Ends (optional - the last gig)", "date"], ["notes", "Notes", "area"]],
    suppliers: [["name", "Name", "text"], ["kind", "What they do (van hire, print, PA...)", "text"], ["person", "Person to ask for", "text"],
                ["phone", "Phone", "text"], ["email", "Email", "text"], ["website", "Website", "text"], ["notes", "Notes", "area"]],
    bills: [["what", "What for", "text"], ["supplier_id", "Supplier", "ref:suppliers"], ["amount", "Amount", "money"], ["due", "Due", "date"],
            ["category", "Category (van, print, gear...)", "text"], ["tour_id", "Tour", "ref:tours"], ["gig_id", "Gig", "ref:gigs"],
            ["paid", "Paid (books it in Money)", "check"], ["paid_on", "Paid on", "date"], ["note", "Note", "text"]],
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
    suppliers: [["name", "Supplier"], ["kind", "Does"], ["person", "Ask for"], ["phone", "Phone"], ["email", "Email"]],
    bills: [["paid", "Paid", function (r) { return '<input type="checkbox" data-billpaid="' + r.id + '"' + (r.paid ? " checked" : "") + ">"; }],
            ["due", "Due", function (r) {
              var late = !r.paid && r.due && r.due < today();
              return '<span style="color:' + (late ? "var(--pink)" : "inherit") + '">' + esc(nice(r.due)) + (late ? " · late" : "") + "</span>"; }],
            ["supplier_id", "Supplier", function (r) { return esc(label("suppliers", byId("suppliers", r.supplier_id))); }],
            ["what", "What for"], ["amount", "Amount", function (r) { return money(r.amount); }, "num"]],
    reminders: [["done", "", function (r) { return '<input type="checkbox" data-done="' + r.id + '"' + (r.done ? " checked" : "") + ">"; }],
                ["text", "Reminder"], ["due", "Due", function (r) { return nice(r.due); }]],
  };
  var NAV = [["overview", "Overview", "M3 12l9-8 9 8v8a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"],
             ["gigs", "Gigs", "M4 5h16v15H4zM4 9h16M8 3v4M16 3v4"],
             ["tours", "Tours", "M3 17h2l2-6h10l2 6h2M7 17a2 2 0 1 0 4 0M13 17a2 2 0 1 0 4 0M9 11V7h6v4"],
             ["setlists", "Setlists", "M5 6h14M5 12h14M5 18h9"],
             ["songs", "Songs", "M9 18V5l12-2v13M9 18a3 3 0 1 1-3-3 3 3 0 0 1 3 3zM21 16a3 3 0 1 1-3-3 3 3 0 0 1 3 3z"],
             ["venues", "Venues", "M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11zM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"],
             ["contacts", "Contacts", "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.9"],
             ["suppliers", "Suppliers", "M3 21V9l9-6 9 6v12M9 21v-6h6v6"],
             ["merch", "Merch", "M4 7l4-3h8l4 3-3 3v10H7V10z"],
             ["money", "Money", "M12 2v20M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"],
             ["bills", "Bills", "M6 2h12v20l-3-2-3 2-3-2-3 2zM9 7h6M9 11h6M9 15h4"],
             ["reminders", "Reminders", "M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0"],
             ["-"], ["settings", "Settings & backup", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"],
             ["trash", "Trash", "M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15"]];
  var TITLES = { gigs: "gig", venues: "venue", contacts: "contact", songs: "song", merch: "item", money: "entry", reminders: "reminder",
                 setlists: "setlist", tours: "tour", suppliers: "supplier", bills: "bill" };

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
    if (v === "tours") return tours();
    if (v === "settings") return settingsView();
    return listView(v);
  }

  /* ---------- overview ---------- */
  function overview() {
    Promise.all([api("overview"), load("venues")]).then(function (r) {
      var o = r[0];
      setCurrency(o.currency);
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
        card("Bills to pay", o.bills_due.length ? o.bills_due.map(function (b) {
          var late = b.due && b.due < today();
          return '<div class="li"><span class="when" style="' + (late ? "color:var(--pink)" : "") + '">' + esc(b.due ? nice(b.due) : "no date") +
                 '</span><span class="what">' + esc(b.supplier || b.what || "Bill") + '</span><button class="btn small" data-paybill="' + b.id +
                 '">MARK PAID · ' + esc(money(b.amount)) + "</button></div>";
        }).join("") : '<div class="empty">Nothing owed in the next two weeks.</div>') +
        (o.tours.length ? card("Tours", o.tours.map(function (x) {
          return '<div class="li" data-tour="' + x.id + '"><span class="when">' + esc(nice(x.starts)) + '</span><span class="what">' + esc(x.name) +
                 " · " + x.gig_count + " gigs</span><span class=\"when\" style=\"text-align:right\">" + esc(money(x.net)) + "</span></div>";
        }).join("")) : "") +
        card("Low stock", o.low_stock.length ? o.low_stock.map(function (m) {
          return '<div class="li"><span class="what">' + esc(m.name + (m.variant ? " · " + m.variant : "")) + '</span><span class="when" style="color:var(--amber)">' + (m.stock || 0) + " left</span></div>";
        }).join("") : '<div class="empty">Plenty of everything.</div>') +
        "</div>";
    });
  }

  /* ---------- a list ---------- */
  var search = {};
  function listView(t) {
    Promise.all([load(t), load("venues"), load("contacts"), load("gigs"), load("setlists"), load("tours"), load("suppliers")]).then(function () {
      var rows = cache[t], q = (search[t] || "").toLowerCase();
      if (q) rows = rows.filter(function (r) { return JSON.stringify(r).toLowerCase().indexOf(q) >= 0; });
      var name = NAV.find(function (n) { return n[0] === t; })[1];
      var totals = "";
      if (t === "money") {
        var inn = 0, out = 0;
        rows.forEach(function (r) { if (r.kind === "expense") out += r.amount || 0; else inn += r.amount || 0; });
        totals = '<p class="lead">In ' + money(inn) + " · Out " + money(out) + " · Kept <b>" + money(inn - out) + "</b></p>";
      }
      if (t === "bills") {
        var owed = 0, late = 0;
        rows.forEach(function (r) { if (!r.paid) { owed += r.amount || 0; if (r.due && r.due < today()) late += r.amount || 0; } });
        totals = '<p class="lead">Still to pay <b>' + money(owed) + "</b>" + (late ? ' · <span style="color:var(--pink)">' + money(late) + " of it late</span>" : "") +
                 ". Tick PAID and it goes into Money as an expense.</p>";
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
      (!isNew && t === "merch" ? '<div class="extras"><button class="btn small" data-x="sell">SELL ONE</button></div>' : "") +
      (!isNew && t === "suppliers" ? '<div class="extras"><button class="btn small" data-x="bill">+ BILL FROM THEM</button></div>' : "");
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
          toast(t === "bills" && row.paid && !(r.paid) ? "Saved, and booked in Money." : "Saved.");
          closeDrawer();
          if (cur === "tours" && openTour) tourDetail(openTour); else go(cur);
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
      if (x === "bill") edit("bills", null, { supplier_id: r.id, due: today() });
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
  function refs() { return Promise.all(["venues", "contacts", "setlists", "gigs", "tours", "suppliers"].map(load)); }
  $("new-gig").addEventListener("click", function () { refs().then(function () { edit("gigs", null, cur === "tours" && openTour ? { tour_id: openTour } : null); }); });
  view.addEventListener("click", function (ev) {
    var n = ev.target.closest("[data-new]");
    if (n) { var pre = n.dataset.pre ? JSON.parse(n.dataset.pre) : null; refs().then(function () { edit(n.dataset.new, null, pre); }); return; }
    var pb = ev.target.closest("[data-paybill]");
    if (pb) { api("save", { table: "bills", row: { id: +pb.dataset.paybill, paid: 1 } }).then(function (d) { toast(d.ok ? "Paid, and booked in Money." : d.msg); go(cur); }); return; }
    var tg = ev.target.closest("[data-tour]");
    if (tg) { cur = "tours"; nav.querySelectorAll("a").forEach(function (a) { a.classList.toggle("on", a.dataset.v === "tours"); }); tourDetail(+tg.dataset.tour); return; }
    var g = ev.target.closest("[data-gig]");
    if (g) { refs().then(function () { edit("gigs", byId("gigs", +g.dataset.gig)); }); return; }
    var p = ev.target.closest("[data-paid]");
    if (p) logPaid(+p.dataset.paid, +p.dataset.fee);
  });
  view.addEventListener("change", function (ev) {
    var d = ev.target.closest("[data-done]");
    if (d) api("save", { table: "reminders", row: { id: +d.dataset.done, done: d.checked ? 1 : 0 } }).then(function () { if (cur === "overview") overview(); });
    var bp = ev.target.closest("[data-billpaid]");
    if (bp) api("save", { table: "bills", row: { id: +bp.dataset.billpaid, paid: bp.checked ? 1 : 0 } }).then(function (x) {
      toast(!x.ok ? x.msg : bp.checked ? "Paid, and booked in Money." : "Not paid: the expense went to the Trash.");
      if (cur === "tours" && openTour) tourDetail(openTour); else go(cur);
    });
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

  /* ---------- tours: a run of gigs, and what it kept ---------- */
  var openTour = null;
  function tours() {
    openTour = null;
    Promise.all([load("tours"), api("overview")]).then(function (r) {
      setCurrency(r[1].currency);
      return Promise.all(cache.tours.map(function (x) { return api("tour", { id: x.id }); }));
    }).then(function (all) {
      var cards = all.filter(function (d) { return d.ok; }).map(function (d) {
        var x = d.tour;
        return '<div class="card li" data-tour="' + x.id + '" style="display:block"><h2>' + esc(x.name) + "</h2>" +
               '<p class="lead" style="margin-bottom:10px">' + (x.starts ? esc(nice(x.starts)) + " – " + esc(nice(x.ends)) : "No dates yet") +
               " · " + x.gigs.length + " gigs</p>" +
               '<div class="money3"><div><small>In</small><div class="big good" style="font-size:19px">' + money(x.income) + "</div></div>" +
               '<div><small>Out</small><div class="big bad" style="font-size:19px">' + money(x.expenses) + "</div></div>" +
               '<div><small>Kept</small><div class="big" style="font-size:19px">' + money(x.net) + "</div></div></div>" +
               (x.owed ? '<p class="lead" style="margin:8px 0 0;color:var(--amber)">' + money(x.owed) + " in bills still to pay</p>" : "") + "</div>";
      });
      view.innerHTML = '<h1>Tours<button class="btn primary" data-new="tours">+ NEW TOUR</button></h1>' +
        '<p class="lead">A tour gathers gigs, and the money and bills that go with them. Put a gig on a tour from the gig itself.</p>' +
        (cards.length ? '<div class="grid">' + cards.join("") + "</div>" : '<p class="empty">No tours yet.</p>');
    });
  }
  function tourDetail(id) {
    openTour = id;
    Promise.all([api("tour", { id: id }), load("bills"), load("suppliers"), load("tours"), load("venues")]).then(function (r) {
      if (!r[0].ok) { toast(r[0].msg); return tours(); }
      var x = r[0].tour;
      var bills = cache.bills.filter(function (b) { return b.tour_id === id; });
      view.innerHTML = '<h1><a class="btn small" data-v-back="1" style="margin:0">‹ TOURS</a>' + esc(x.name) +
        '<button class="btn" data-edittour="' + id + '">EDIT TOUR</button></h1>' +
        '<p class="lead">' + (x.starts ? esc(nice(x.starts)) + " – " + esc(nice(x.ends)) : "No dates yet") + " · fees booked " + money(x.fees) +
        (x.merch_income ? " · merch " + money(x.merch_income) : "") + "</p>" +
        '<div class="grid" style="margin-bottom:18px"><div class="card"><h2>Money</h2><div class="money3">' +
        '<div><small>In</small><div class="big good">' + money(x.income) + "</div></div>" +
        '<div><small>Out</small><div class="big bad">' + money(x.expenses) + "</div></div>" +
        '<div><small>Kept</small><div class="big">' + money(x.net) + "</div></div></div>" +
        (x.owed ? '<p class="lead" style="margin:8px 0 0;color:var(--amber)">' + money(x.owed) + " in bills still to pay</p>" : "") + "</div></div>" +
        '<h1 style="font-size:16px">Gigs<button class="btn small" data-new="gigs" data-pre=\'' + JSON.stringify({ tour_id: id }) + '\'>+ GIG ON THIS TOUR</button></h1>' +
        (x.gigs.length ? "<table><thead><tr><th>Date</th><th>Venue</th><th>Status</th><th class=\"num\">Fee</th></tr></thead><tbody>" + x.gigs.map(function (g) {
          return '<tr data-gig="' + g.id + '"><td>' + esc(nice(g.date)) + "</td><td>" + esc(g.title || [g.venue, g.city].filter(Boolean).join(", ") || "TBA") +
                 '</td><td><span class="pill ' + esc(g.status) + '">' + esc(g.status) + '</span></td><td class="num">' + money(g.fee) + "</td></tr>";
        }).join("") + "</tbody></table>" : '<p class="empty">No gigs on this tour yet.</p>') +
        '<h1 style="font-size:16px;margin-top:22px">Bills<button class="btn small" data-new="bills" data-pre=\'' + JSON.stringify({ tour_id: id, due: today() }) + '\'>+ BILL</button></h1>' +
        (bills.length ? "<table><thead><tr>" + COLS.bills.map(function (c) { return '<th class="' + (c[3] || "") + '">' + c[1] + "</th>"; }).join("") +
          "</tr></thead><tbody>" + bills.map(function (b) {
            return '<tr data-bill="' + b.id + '">' + COLS.bills.map(function (c) {
              return '<td class="' + (c[3] || "") + '">' + (c[2] ? c[2](b) : esc(b[c[0]] == null ? "" : b[c[0]])) + "</td>"; }).join("") + "</tr>";
          }).join("") + "</tbody></table>" : '<p class="empty">No bills for this tour.</p>');
    });
  }
  view.addEventListener("click", function (ev) {
    if (ev.target.closest("[data-v-back]")) { tours(); return; }
    var et = ev.target.closest("[data-edittour]");
    if (et) { edit("tours", byId("tours", +et.dataset.edittour)); return; }
    var bl = ev.target.closest("tr[data-bill]");
    if (bl && !ev.target.matches("input")) refs().then(function () { load("bills").then(function () { edit("bills", byId("bills", +bl.dataset.bill)); }); });
  });

  /* ---------- settings & backup ---------- */
  function settingsView() {
    Promise.all([api("settings"), api("backups")]).then(function (r) {
      var st = r[0], bk = r[1];
      setCurrency(st.settings.currency);
      var opts = st.currencies.indexOf(st.settings.currency) < 0 ? [st.settings.currency].concat(st.currencies) : st.currencies;
      view.innerHTML = '<h1>Settings &amp; backup</h1><p class="lead">Everything here lives in the band file on your drive.</p>' +
        '<div class="grid"><div class="card"><h2>Currency &amp; units</h2><div class="field"><label>Money is shown in</label><select id="cur">' +
        opts.map(function (c) { return "<option" + (c === st.settings.currency ? " selected" : "") + ">" + c + "</option>"; }).join("") +
        '</select></div><p class="lead" style="margin:0 0 12px">Example: ' + esc(money(1234.5)) + ". Changing it relabels the amounts; it doesn't convert them.</p>" +
        '<div class="field"><label>Measurements and weights</label><select id="units">' + Object.keys(st.units).map(function (u) {
          return '<option value="' + u + '"' + (u === st.settings.units ? " selected" : "") + ">" + u.charAt(0).toUpperCase() + u.slice(1) +
                 " (" + esc(st.units[u]) + ")</option>";
        }).join("") + '</select></div><p class="lead" style="margin:0">Philibert uses these for stage sizes, gear weights and driving distances.</p></div>' +
        '<div class="card"><h2>Export</h2><p class="lead">Every list as a spreadsheet (one CSV per list, in a zip) - for your accountant, or to keep.</p>' +
        '<button class="btn primary" id="export">EXPORT FOR A SPREADSHEET</button></div>' +
        '<div class="card"><h2>Backups</h2><p class="lead">Philibert keeps a copy each day before the first change (the last 14), in <code>data\\exports\\Band backups</code> on your drive.</p>' +
        '<button class="btn primary" id="backup-now">BACK UP NOW</button></div></div>' +
        '<h1 style="font-size:16px;margin-top:22px">Saved backups</h1>' +
        (bk.backups.length ? "<table><thead><tr><th>Backup</th><th>Kind</th><th class=\"num\">Size</th><th></th></tr></thead><tbody>" + bk.backups.map(function (b) {
          return "<tr><td>" + esc(new Date(b.when * 1000).toLocaleString()) + "</td><td>" + (b.auto ? "daily" : "yours") + '</td><td class="num">' +
                 Math.max(1, Math.round(b.size / 1024)) + ' KB</td><td class="num"><button class="btn small" data-restorebk="' + esc(b.name) + '">RESTORE</button></td></tr>';
        }).join("") + "</tbody></table>" : '<p class="empty">No backups yet - the first one is made with your first change today.</p>');
      $("cur").addEventListener("change", function () {
        api("settings_save", { settings: { currency: $("cur").value } }).then(function (d) {
          if (!d.ok) { toast(d.msg); return; }
          setCurrency(d.settings.currency); toast("Money is shown in " + d.settings.currency + " now."); settingsView();
        });
      });
      $("units").addEventListener("change", function () {
        api("settings_save", { settings: { units: $("units").value } }).then(function (d) {
          toast(d.ok ? "Measurements: " + d.settings.units + "." : d.msg); settingsView();
        });
      });
      $("backup-now").addEventListener("click", function () { api("backup").then(function (d) { toast(d.ok ? "Backed up." : d.msg); settingsView(); }); });
      $("export").addEventListener("click", function () {
        api("export").then(function (d) {
          if (!d.ok) { toast(d.msg); return; }
          var bin = atob(d.zip), u8 = new Uint8Array(bin.length);
          for (var i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
          var a = document.createElement("a");
          a.href = URL.createObjectURL(new Blob([u8], { type: "application/zip" }));
          a.download = d.name; a.click();
          toast("Saved " + d.name + ".");
        });
      });
    });
  }
  view.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-restorebk]");
    if (!b) return;
    if (!confirm("Put the band file back to this backup? What you have now is backed up first, so you can undo it.")) return;
    api("restore_backup", { name: b.dataset.restorebk }).then(function (d) { toast(d.ok ? "Restored. What you had is saved as a backup too." : d.msg); settingsView(); });
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
  api("overview").then(function (o) { setCurrency(o.currency); renderNav(o.counts); });
  var start = "overview";
  try { start = localStorage.getItem("band.view") || "overview"; } catch (e) { /* private */ }
  go(NAV.some(function (n) { return n[0] === start; }) ? start : "overview");
})();
