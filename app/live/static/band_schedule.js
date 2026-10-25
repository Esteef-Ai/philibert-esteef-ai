/* The Band Manager's Schedule: the band calendar, everyone's availability and blackout
 * dates, "find a time" for practices, and a date check for shows and tours. Shared with the
 * band through the Group Board (nd_board.py: avail_*, events, event_save, suggest, check,
 * ask_band); nd_sched.py does the arithmetic. BandSchedule.render(viewElement). */
(function () {
  "use strict";
  var DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  var KINDS = { practice: "Practice", show: "Show", other: "Event" };
  var view, tab = "calendar", st = {}, me = null, members = [], events = [], lastSlots = [], GROUP = "", BAND = null, GIGS = {};
  try { tab = localStorage.getItem("band.schedtab") || tab; } catch (e) { /* private */ }

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function api(op, d) {                       // always the open band's own Group Board group
    return fetch("/api/board", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.assign({ op: op, group: GROUP }, d || {})) })
      .then(function (r) { return r.json(); }).catch(function (e) { return { ok: false, msg: "Philibert could not do that (" + e.message + ")." }; });
  }
  function toast(m) { var t = $("toast"); if (!t) return; t.textContent = m; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove("on"); }, 2800); }
  function iso(d) { return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); }
  function addDays(n) { var d = new Date(); d.setDate(d.getDate() + n); return iso(d); }
  function niceDate(ds) { var d = new Date(ds + "T12:00:00"); return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }); }
  function niceTime(hm) { if (!hm) return ""; var p = hm.split(":"), h = +p[0]; return (h % 12 || 12) + (p[1] !== "00" ? ":" + p[1] : "") + (h < 12 || h === 24 ? " AM" : " PM"); }
  function maps(addr) {
    return addr ? esc(addr) + ' <a class="maps" target="_blank" rel="noopener" href="https://www.google.com/maps/dir/?api=1&destination=' +
      encodeURIComponent(addr) + '">Directions</a>' : "";
  }
  var CSS = ".sch-tabs{display:flex;gap:6px;margin:4px 0 16px;flex-wrap:wrap}.sch-tabs .btn.on{color:#fff;border-color:var(--cyan,#00f2fe);background:rgba(0,242,254,.14)}" +
    ".sch-row{display:grid;grid-template-columns:110px 1fr;gap:10px;align-items:start;padding:8px 0;border-bottom:1px solid var(--line,#1e3054)}" +
    ".sch-row b{padding-top:7px}.sch-wins{display:flex;flex-wrap:wrap;gap:6px;align-items:center}" +
    ".sch-win{display:flex;gap:4px;align-items:center;background:rgba(22,37,68,.6);border:1px solid var(--line,#1e3054);border-radius:7px;padding:3px 6px}" +
    ".sch-win input{background:transparent;border:none;color:inherit;font:inherit;width:96px}.sch-x{background:none;border:none;color:var(--faint,#6f86a8);cursor:pointer}" +
    ".sch-x:hover{color:var(--pink,#ff2e88)}.sch-slot{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center}" +
    ".sch-who{font-size:12.5px;color:var(--dim,#8ea3c4);margin-top:3px;line-height:1.45}.sch-out{color:var(--amber,#f59e0b)}" +
    ".sch-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;align-items:end}" +
    ".sch-form label{display:block;font:600 10px var(--mono,monospace);letter-spacing:.14em;text-transform:uppercase;color:var(--dim,#8ea3c4);margin-bottom:5px}" +
    ".sch-form input,.sch-form select,.sch-form textarea{width:100%;background:#0b1426;border:1px solid var(--line,#1e3054);border-radius:7px;padding:8px 10px;color:inherit;font:inherit}" +
    ".sch-chk{display:flex;gap:12px;flex-wrap:wrap}.sch-chk label{display:flex;gap:5px;align-items:center;text-transform:none;letter-spacing:0;font:13px var(--font,sans-serif);color:inherit}" +
    ".pill.practice{color:#67e8f9;border-color:rgba(103,232,249,.5)}.pill.show{color:#f472b6;border-color:rgba(244,114,182,.5)}.pill.cancelled{color:var(--faint,#6f86a8)}" +
    ".sch-ev.cancelled .what{text-decoration:line-through;opacity:.6}";

  function render(el) {
    view = el;
    if (!$("sch-css")) { var s = document.createElement("style"); s.id = "sch-css"; s.textContent = CSS; document.head.appendChild(s); }
    view.innerHTML = "<h1>Schedule</h1><p class=\"lead\">Loading...</p>";
    fetch("/api/band", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: "bands_list" }) })
      .then(function (r) { return r.json(); }).then(function (b) {
        BAND = (b.bands || []).filter(function (x) { return x.id === b.active; })[0] || null;
        GROUP = (BAND && BAND.board_group) || "";
        return api("status");
      }).then(function (d) {
      st = d;
      // this band isn't linked to a Group Board group yet: pick one of this drive's groups
      if (!GROUP && (d.groups || []).length) {
        view.innerHTML = "<h1>Schedule</h1><p class=\"lead\">Which Group Board group is <b>" + esc(BAND ? BAND.name : "this band") + "</b>? Its members share the " +
          "availability and the band calendar.</p><div class=\"card\" style=\"max-width:520px\"><div class=\"sch-form\"><div><label>Group</label><select id=\"lk-g\">" +
          d.groups.map(function (g) { return '<option value="' + esc(g.id) + '">' + esc(g.name) + "</option>"; }).join("") +
          '</select></div><div><button class="btn primary" id="lk-go">LINK</button></div></div><p class="lead" style="margin-top:10px;font-size:12.5px">' +
          "Not there? Start or join the band's group in the Group Board first.</p></div>";
        $("lk-go").onclick = function () {
          var gname = $("lk-g").selectedOptions[0].textContent;
          var post = function (x) { return fetch("/api/band", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(x) }); };
          post({ op: "bands_link", id: BAND.id, group: $("lk-g").value })
            .then(function () { return BAND.name === "My band" ? post({ op: "bands_rename", id: BAND.id, name: gname }) : null; })   // name it after its group
            .then(function () { if (BAND.name === "My band") location.reload(); else render(view); });
        };
        return;
      }
      if (!d.joined) {
        view.innerHTML = "<h1>Schedule</h1><p class=\"lead\">The schedule is shared with the band through the <b>Group Board</b>: add Group Board from the " +
          "App Store, start your band's group (or join it with the invite code), and come back here. Everyone then fills in when they're usually free, " +
          "and Philibert finds practice times that suit the whole band.</p>";
        return;
      }
      if (!d.online) { view.innerHTML = "<h1>Schedule</h1><p class=\"lead\">The schedule is shared online - turn the Internet on (INTERNET in Philibert Chat).</p>"; return; }
      me = d.member;
      if (BAND && !BAND.board_group) {        // the drive's only group: link it quietly
        fetch("/api/band", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: "bands_link", id: BAND.id, group: d.group.id }) });
        GROUP = d.group.id;
      }
      var bandApi = function (x) { return fetch("/api/band", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(x) }).then(function (r) { return r.json(); }); };
      return bandApi({ op: "gigs_sync" }).catch(function () { return {}; }).then(function () {
        return Promise.all([api("avail_get"), api("events"), bandApi({ op: "list", table: "gigs" }).catch(function () { return {}; })]);
      }).then(function (r) {
        GIGS = {};
        ((r[2] && r[2].rows) || []).forEach(function (g) { if (g.cal_event) GIGS[g.cal_event] = g; });
        if (!r[0].ok) { view.innerHTML = "<h1>Schedule</h1><p class=\"lead\">" + esc(r[0].msg) + "</p>"; return; }
        members = r[0].members; events = r[1].events || [];
        draw();
      });
    });
  }
  function draw() {
    var tabs = [["calendar", "Band calendar"], ["mine", "My availability"], ["find", "Find a practice time"], ["check", "Check dates (shows, tours)"]];
    view.innerHTML = "<h1>Schedule <span class=\"lead\" style=\"font-size:13px;font-weight:400\">" + esc(BAND ? BAND.name : "") +
      (BAND && BAND.name !== st.group.name ? " · Group Board: " + esc(st.group.name) : "") +
      (st.groups && st.groups.length > 1 ? ' · <a href="#" id="relink" style="color:var(--cyan,#00f2fe)">change group</a>' : "") + "</span></h1>" +
      '<div class="sch-tabs">' + tabs.map(function (t) { return '<button class="btn' + (t[0] === tab ? " on" : "") + '" data-tab="' + t[0] + '">' + t[1] + "</button>"; }).join("") +
      '</div><div id="sch-body"></div>';
    if ($("relink")) $("relink").onclick = function (ev) {
      ev.preventDefault();
      fetch("/api/band", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: "bands_link", id: BAND.id, group: "" }) })
        .then(function () { render(view); });
    };
    view.querySelector(".sch-tabs").onclick = function (ev) {
      var b = ev.target.closest("[data-tab]"); if (!b) return;
      tab = b.dataset.tab; try { localStorage.setItem("band.schedtab", tab); } catch (e) { /* private */ }
      draw();
    };
    ({ calendar: calendar, mine: mine, find: find, check: checkDates })[tab]();
  }

  /* ---------- the band calendar ---------- */
  function calendar() {
    var today = addDays(0), up = events.filter(function (e) { return e.date >= today; }), past = events.filter(function (e) { return e.date < today; }).slice(-5);
    var li = function (e) {
      return '<div class="li sch-ev' + (e.cancelled ? " cancelled" : "") + '" data-ev="' + esc(e.id) + '"><span class="when">' + esc(niceDate(e.date)) + " " +
        esc(niceTime(e.start)) + (e.end ? "–" + esc(niceTime(e.end)) : "") + '</span><span class="what">' + esc(e.title) +
        (e.address ? '<div class="sch-who">' + maps(e.address) + "</div>" : "") + (e.notes ? '<div class="sch-who">' + esc(e.notes) + "</div>" : "") +
        '<div class="sch-who">booked by ' + esc(e.by) + (e.gcal_id ? ' · <span style="color:var(--green,#10b981)">on Google Calendar</span>' : "") +
        (e.gcal_error ? ' · <span class="sch-out">' + esc(e.gcal_error) + "</span>" : "") +
        (GIGS[e.id] ? ' · <span style="color:var(--green,#10b981)">a gig in ' + esc(BAND ? BAND.name : "the Band Manager") + "</span>"
          : e.kind === "show" && !e.cancelled ? ' · <a href="#" data-addgig="' + esc(e.id) + '" style="color:var(--cyan,#00f2fe)">add to gigs</a>' : "") + "</div></span>" +
        '<span class="pill ' + (e.cancelled ? "cancelled" : esc(e.kind)) + '">' + (e.cancelled ? "cancelled" : esc(KINDS[e.kind] || e.kind)) + "</span></div>";
    };
    $("sch-body").innerHTML = '<div class="card" id="gcard" style="margin-bottom:12px"><h2>Google Calendar</h2><p class="lead">Checking...</p></div>' +
      '<div style="display:flex;gap:8px;margin-bottom:12px"><button class="btn primary" data-new="practice">+ PRACTICE</button>' +
      '<button class="btn" data-new="show">+ SHOW</button><button class="btn" data-new="other">+ OTHER</button></div>' +
      '<div class="card"><h2>Coming up</h2>' + (up.map(li).join("") || '<div class="empty">Nothing booked yet. Try "Find a practice time".</div>') + "</div>" +
      (past.length ? '<div class="card" style="margin-top:12px"><h2>Recently</h2>' + past.reverse().map(li).join("") + "</div>" : "");
    googleCard();
    $("sch-body").onclick = function (ev) {
      var n = ev.target.closest("[data-new]"), e = ev.target.closest("[data-ev]"), ag = ev.target.closest("[data-addgig]");
      if (ag) {
        ev.preventDefault();
        var x = events.filter(function (y) { return y.id === ag.dataset.addgig; })[0];
        fetch("/api/band", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: "gig_from_event", event: x }) })
          .then(function (r) { return r.json(); }).then(function (d) {
            if (!d.ok) { toast(d.msg); return; }
            GIGS[x.id] = d.row; toast("Added to Gigs - changes there now update the calendar."); draw();
          });
        return;
      }
      if (ev.target.closest("a")) return;
      if (n) eventForm({ kind: n.dataset.new });
      else if (e) eventForm(events.filter(function (x) { return x.id === e.dataset.ev; })[0]);
    };
  }
  function googleCard() {
    api("google_status").then(function (g) {
      var c = $("gcard"); if (!c) return;
      if (!g.ok) { c.innerHTML = "<h2>Google Calendar</h2><p class=\"lead\">" + esc(g.msg) + "</p>"; return; }
      var shared = members.filter(function (m) { return m.google; }).map(function (m) { return m.name; });
      var missing = members.filter(function (m) { return !m.google; }).map(function (m) { return m.name; });
      c.innerHTML = "<h2>Google Calendar</h2>" + (!g.configured ? '<p class="lead">Not set up on the board server yet.</p>'
        : g.connected ? '<p class="lead"><span style="color:var(--green,#10b981)">Connected</span> (by ' + esc(g.by) + ", " + esc(g.tz) + "). Bookings go onto the band's " +
          "Google calendar with everyone invited, and each member's busy times block the scheduler." + (g.error ? ' <span class="sch-out">' + esc(g.error) + "</span>" : "") + "</p>" +
          '<p class="lead" style="font-size:12.5px">Busy times seen for: ' + (shared.length ? esc(shared.join(", ")) : "nobody yet") +
          (missing.length ? ' · <span class="sch-out">not yet: ' + esc(missing.join(", ")) + "</span> (add your Gmail under My availability)" : "") + "</p>" +
          (me.admin ? '<button class="btn small danger" id="g-off">DISCONNECT</button>' : "")
        : '<p class="lead">Connect the band\'s Google account: practices and shows then land in everyone\'s Google Calendar, and appointments in their own ' +
          "calendars block the scheduler (only when they're busy - never what it is).</p>" +
          (me.admin ? '<button class="btn primary" id="g-on">CONNECT GOOGLE CALENDAR</button>' : '<p class="lead">Ask the group\'s admin to connect it.</p>'));
      if ($("g-on")) $("g-on").onclick = function () {
        var tz = ""; try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (x) { /* old browser */ }
        api("google_start", { tz: tz }).then(function (r) {
          if (!r.ok) { toast(r.msg); return; }
          window.open(r.url, "_blank");
          c.querySelector(".lead").textContent = "Sign in with the BAND's Google account in the window that opened, allow both permissions, then come back here.";
          var tries = 0, t = setInterval(function () {
            api("google_status").then(function (x) { if ((x.connected || ++tries > 60) && $("gcard")) { clearInterval(t); if (x.connected) { toast("Google Calendar connected."); googleCard(); } } });
          }, 5000);
        });
      };
      if ($("g-off")) $("g-off").onclick = function () {
        if (!confirm("Disconnect the band's Google account? Events already on Google Calendar stay there; new ones won't be added.")) return;
        api("google_disconnect").then(function () { googleCard(); });
      };
    });
  }
  function eventForm(e) {
    e = e || {};
    var mine = !e.id || e.by_id === me.id || me.admin;
    var d = document.createElement("div");
    d.className = "card"; d.style.marginTop = "14px";
    d.innerHTML = "<h2>" + (e.id ? "Change " : "Book a ") + esc((KINDS[e.kind] || "Event").toLowerCase()) + "</h2>" +
      '<div class="sch-form"><div><label>What</label><select id="ef-kind">' + Object.keys(KINDS).map(function (k) { return '<option value="' + k + '"' + (k === e.kind ? " selected" : "") + ">" + KINDS[k] + "</option>"; }).join("") + "</select></div>" +
      '<div><label>Title</label><input id="ef-title" maxlength="120" value="' + esc(e.title || "") + '" placeholder="' + esc(KINDS[e.kind] || "Event") + '"></div>' +
      '<div><label>Date</label><input id="ef-date" type="date" value="' + esc(e.date || addDays(1)) + '"></div>' +
      '<div><label>Starts</label><input id="ef-start" type="time" value="' + esc(e.start || "19:00") + '"></div>' +
      '<div><label>Ends</label><input id="ef-end" type="time" value="' + esc(e.end || "21:00") + '"></div></div>' +
      '<div class="sch-form" style="margin-top:10px"><div style="grid-column:1/-1"><label>Address (gets a Directions link)</label><input id="ef-addr" maxlength="200" value="' + esc(e.address || "") + '"></div>' +
      '<div style="grid-column:1/-1"><label>Notes</label><textarea id="ef-notes" rows="2" maxlength="2000">' + esc(e.notes || "") + "</textarea></div></div>" +
      '<div style="display:flex;gap:8px;margin-top:12px">' + (mine ? '<button class="btn primary" id="ef-save">' + (e.id ? "SAVE CHANGES" : "BOOK IT") + "</button>" : '<span class="lead">Only ' + esc(e.by) + " or the admin can change this.</span>") +
      (e.id && mine && !e.cancelled ? '<button class="btn danger" id="ef-cancel">CANCEL THIS ' + esc((KINDS[e.kind] || "event").toUpperCase()) + "</button>" : "") +
      '<button class="btn" id="ef-close">CLOSE</button></div><p class="lead" style="margin-top:8px;font-size:12.5px">Everyone in the group gets a phone alert (ntfy) and a desktop note when it\'s booked or changed.</p>';
    var old = $("sch-form"); if (old) old.remove();
    d.id = "sch-form";
    $("sch-body").prepend(d);
    $("ef-close").onclick = function () { d.remove(); };
    var send = function (cancel) {
      var body = { id: e.id || "", kind: $("ef-kind").value, title: $("ef-title").value, date: $("ef-date").value, start: $("ef-start").value,
                   end: $("ef-end").value, address: $("ef-addr").value, notes: $("ef-notes").value, cancelled: !!cancel };
      api("event_save", body).then(function (r) {
        if (!r.ok) { toast(r.msg); return; }
        toast(cancel ? "Cancelled - the band has been told." : e.id ? "Changed - the band has been told." : "Booked - the band has been told.");
        api("events").then(function (x) { events = x.events || []; tab = "calendar"; draw(); });
      });
    };
    if ($("ef-save")) $("ef-save").onclick = function () { send(false); };
    if ($("ef-cancel")) $("ef-cancel").onclick = function () { if (confirm("Cancel it for everyone?")) send(true); };
  }

  /* ---------- my availability ---------- */
  function mine() {
    var m = members.filter(function (x) { return x.id === me.id; })[0] || { weekly: [], blackouts: [] };
    var win = function (w) { return '<span class="sch-win"><input type="time" value="' + esc(w.start) + '" data-s>–<input type="time" value="' + esc(w.end) + '" data-e><button class="sch-x" data-rm title="Remove">✕</button></span>'; };
    $("sch-body").innerHTML = '<div class="card"><h2>When are you usually free?</h2><p class="lead">Add the times you can usually play, day by day. Philibert only suggests practices inside everyone\'s times.</p>' +
      DAYS.map(function (n, i) {
        return '<div class="sch-row" data-day="' + i + '"><b>' + n + '</b><div class="sch-wins">' + m.weekly.filter(function (w) { return +w.day === i; }).map(win).join("") +
          '<button class="btn small" data-add>+ TIME</button></div></div>';
      }).join("") + "</div>" +
      '<div class="card" style="margin-top:12px"><h2>Your Google Calendar</h2><p class="lead">So your own appointments block practice times (e.g. you\'re usually free ' +
      'on Tuesdays, but not this Tuesday): type your Gmail address, then in Google Calendar open <b>Settings</b> → your calendar → <b>Share with specific people</b> → ' +
      'add the band\'s Google account with <b>See only free/busy (hide details)</b>. The band then sees only <i>when</i> you\'re busy, never what it is. ' +
      'You also get practices and shows as Google Calendar invites.</p><div class="sch-form"><div><label>Your Gmail</label>' +
      '<input id="av-email" type="email" maxlength="200" value="' + esc(m.email || "") + '" placeholder="you@example.com"></div></div></div>' +
      '<div class="card" style="margin-top:12px"><h2>Blackout dates</h2><p class="lead">Days you can\'t do anything - holidays, work trips, family things.</p><div id="bo">' +
      m.blackouts.map(boRow).join("") + '</div><button class="btn small" id="bo-add">+ BLACKOUT</button></div>' +
      '<div style="margin-top:14px;display:flex;gap:10px;align-items:center"><button class="btn primary" id="av-save">SAVE MY AVAILABILITY</button>' +
      '<span class="lead" id="av-msg">' + (m.updated ? "Last saved " + new Date(m.updated).toLocaleString() : "Not filled in yet - the others can't plan around you until you do.") + "</span></div>" +
      '<div class="card" style="margin-top:16px"><h2>The band</h2>' + members.map(function (x) {
        return '<div class="li"><span class="what">' + esc(x.name) + '</span><span class="sch-who" style="margin:0 0 0 auto;white-space:nowrap">' + (x.weekly.length ? x.weekly.length + " time" + (x.weekly.length === 1 ? "" : "s") + " a week" : '<span class="sch-out">not filled in</span>') +
          (x.blackouts.length ? " · " + x.blackouts.length + " blackout" + (x.blackouts.length === 1 ? "" : "s") : "") +
          (x.google ? " · Google ✓" : "") + "</span></div>";
      }).join("") + "</div>";
    $("sch-body").onclick = function (ev) {
      if (ev.target.closest("[data-rm]")) { ev.target.closest(".sch-win, .sch-bo").remove(); return; }
      var a = ev.target.closest("[data-add]");
      if (a) a.insertAdjacentHTML("beforebegin", win({ start: "19:00", end: "22:00" }));
    };
    $("bo-add").onclick = function () { $("bo").insertAdjacentHTML("beforeend", boRow({ from: addDays(7), to: addDays(7), note: "" })); };
    $("av-save").onclick = function () {
      var weekly = [];
      view.querySelectorAll(".sch-row").forEach(function (row) {
        row.querySelectorAll(".sch-win").forEach(function (w) {
          var s = w.querySelector("[data-s]").value, e = w.querySelector("[data-e]").value;
          if (s && e && s < e) weekly.push({ day: +row.dataset.day, start: s, end: e });
        });
      });
      var blackouts = [].map.call(view.querySelectorAll(".sch-bo"), function (b) {
        return { from: b.querySelector("[data-f]").value, to: b.querySelector("[data-t]").value || b.querySelector("[data-f]").value, note: b.querySelector("[data-n]").value };
      }).filter(function (b) { return b.from; });
      api("avail_set", { weekly: weekly, blackouts: blackouts, email: ($("av-email") || {}).value || "" }).then(function (r) {
        if (!r.ok) { toast(r.msg); return; }
        toast("Saved.");
        api("avail_get").then(function (x) { members = x.members; draw(); });
      });
    };
  }
  function boRow(b) {
    return '<div class="sch-win sch-bo" style="margin:4px 0;display:inline-flex"><input type="date" value="' + esc(b.from) + '" data-f> to <input type="date" value="' + esc(b.to) + '" data-t>' +
      '<input value="' + esc(b.note || "") + '" data-n maxlength="80" placeholder="why (optional)" style="width:180px"><button class="sch-x" data-rm title="Remove">✕</button></div><br>';
  }

  /* ---------- find a practice time ---------- */
  function find() {
    $("sch-body").innerHTML = '<div class="card"><div class="sch-form">' +
      '<div><label>What</label><select id="f-kind"><option value="practice">Practice</option><option value="other">Other (meeting, recording...)</option></select></div>' +
      '<div><label>How long</label><select id="f-len"><option value="60">1 hour</option><option value="90">1½ hours</option><option value="120" selected>2 hours</option><option value="180">3 hours</option><option value="240">4 hours</option></select></div>' +
      '<div><label>From</label><input type="date" id="f-from" value="' + addDays(1) + '"></div><div><label>To</label><input type="date" id="f-to" value="' + addDays(14) + '"></div>' +
      '<div><label>Not before</label><input type="time" id="f-early" value="10:00"></div><div><label>Done by</label><input type="time" id="f-late" value="23:30"></div></div>' +
      '<div class="sch-form" style="margin-top:10px"><div style="grid-column:1/-1"><label>Who has to be there</label><div class="sch-chk">' +
      members.map(function (m) { return '<label><input type="checkbox" data-req="' + esc(m.id) + '" checked>' + esc(m.name) + (m.weekly.length ? "" : ' <span class="sch-out">(not filled in)</span>') + "</label>"; }).join("") +
      '</div></div></div><div style="margin-top:12px"><button class="btn primary" id="f-go">FIND TIMES</button></div></div><div id="f-out"></div>';
    $("f-go").onclick = function () {
      var req = [].map.call(view.querySelectorAll("[data-req]:checked"), function (c) { return c.dataset.req; });
      $("f-out").innerHTML = '<p class="lead" style="margin-top:12px">Looking...</p>';
      api("suggest", { kind: $("f-kind").value, duration: +$("f-len").value, from: $("f-from").value, to: $("f-to").value,
                       earliest: $("f-early").value, latest: $("f-late").value, required: req.length ? req : ["-none-"], limit: 6 }).then(function (r) {
        if (!r.ok) { $("f-out").innerHTML = '<p class="lead">' + esc(r.msg) + "</p>"; return; }
        lastSlots = r.slots;
        var note = r.google && r.unseen && r.unseen.length ? '<p class="lead sch-out" style="margin-top:10px">Couldn\'t see ' + esc(r.unseen.join(", ")) +
          "'s Google Calendar - they haven't shared free/busy with the band's account yet, so only their usual times count.</p>" : "";
        $("f-out").innerHTML = r.slots.length ? '<div class="card" style="margin-top:12px"><h2>Best times</h2>' + r.slots.map(function (s, i) {
          return '<div class="li sch-slot"><div><b>' + esc(niceDate(s.date)) + " · " + esc(niceTime(s.start)) + "–" + esc(niceTime(s.end)) + "</b>" +
            '<div class="sch-who">Free: ' + esc(s.free.join(", ")) + (s.unknown.length ? ' <span class="sch-out">(' + esc(s.unknown.join(", ")) + " hasn't filled in availability)</span>" : "") + "</div>" +
            (s.missing.length ? '<div class="sch-who sch-out">Can\'t: ' + s.missing.map(function (x) { return esc(x.name) + " - " + esc(x.why); }).join("; ") + "</div>" : "") +
            '</div><button class="btn small" data-book="' + i + '">BOOK</button></div>';
        }).join("") + '<div style="margin-top:12px;display:flex;gap:10px;align-items:center"><button class="btn" id="f-ask">ASK THE BAND (POLL ON THE BOARD)</button>' +
          '<span class="lead" style="font-size:12.5px">Puts the top three in a Group Board poll.</span></div></div>'
          : '<div class="card" style="margin-top:12px"><div class="empty">No time suits everyone who has to be there. Try a longer date range, a shorter practice, or fewer required people.</div></div>';
        $("f-out").insertAdjacentHTML("afterbegin", note);
        if ($("f-ask")) $("f-ask").onclick = askBand;
      });
    };
    $("sch-body").addEventListener("click", function (ev) {
      var b = ev.target.closest("[data-book]"); if (!b) return;
      var s = lastSlots[+b.dataset.book];
      tab = "calendar"; draw();
      eventForm({ kind: $("f-kind") ? $("f-kind").value : "practice", date: s.date, start: s.start, end: s.end });
    });
  }
  function askBand() {
    var top = lastSlots.slice(0, 3).map(function (s) { return niceDate(s.date) + ", " + niceTime(s.start) + "–" + niceTime(s.end); });
    api("ask_band", { title: "When can we practice?", body: "Philibert found these times that suit everyone. Vote for all that work for you.", options: top })
      .then(function (r) { toast(r.ok ? "Poll posted on the Group Board." : r.msg); });
  }

  /* ---------- check dates for shows and tours ---------- */
  function checkDates() {
    $("sch-body").innerHTML = '<div class="card"><p class="lead">Thinking of a show or a tour? See who can\'t make which days. Leave the time empty to check blackout dates only.</p>' +
      '<div class="sch-form"><div><label>From</label><input type="date" id="c-from" value="' + addDays(1) + '"></div><div><label>To</label><input type="date" id="c-to" value="' + addDays(30) + '"></div>' +
      '<div><label>Starts (optional)</label><input type="time" id="c-start"></div><div><label>Ends (optional)</label><input type="time" id="c-end"></div>' +
      '<div><button class="btn primary" id="c-go">CHECK</button></div></div></div><div id="c-out"></div>';
    $("c-go").onclick = function () {
      api("check", { from: $("c-from").value, to: $("c-to").value, start: $("c-start").value, end: $("c-end").value }).then(function (r) {
        if (!r.ok) { $("c-out").innerHTML = '<p class="lead">' + esc(r.msg) + "</p>"; return; }
        var good = r.days.filter(function (x) { return !x.out.length && !x.events.length; }).length;
        $("c-out").innerHTML = '<div class="card" style="margin-top:12px"><h2>' + good + " of " + r.days.length + " days open (everyone can, nothing booked)</h2><table><thead><tr><th>Day</th><th>Can't make it</th><th>Already booked</th></tr></thead><tbody>" +
          r.days.map(function (x) {
            return "<tr><td>" + esc(niceDate(x.date)) + "</td><td>" + (x.out.length ? '<span class="sch-out">' + x.out.map(function (o) { return esc(o.name) + " (" + esc(o.why) + ")"; }).join(", ") + "</span>" : "✓ everyone") +
              "</td><td>" + x.events.map(function (e) { return esc(e.title) + " " + esc(niceTime(e.start)); }).join(", ") + "</td></tr>";
          }).join("") + "</tbody></table></div>";
      });
    };
  }

  window.BandSchedule = { render: render };
})();
