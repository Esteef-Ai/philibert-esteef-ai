/* Philibert Yo Teach: a teacher's classes, students, live class notes and attendance,
 * class summaries, and lessons / worksheets made as Word + PDF (nd_yoteach.py over one
 * SQLite file on the drive, /api/yoteach). Students go by label ("Student G"); a real
 * name is optional and never leaves this computer.
 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var view = $("view"), nav = $("nav");
  var cur = "today", cache = { students: [], classes: [] }, SET = {}, META = {}, MODELS = [];
  var liveTimer = null, pollTimer = null, selStudent = null, shot = null, lastJob = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function api(op, data) {
    return fetch("/api/yoteach", { method: "POST", headers: { "Content-Type": "application/json" },
                                   body: JSON.stringify(Object.assign({ op: op }, data || {})) }).then(function (r) { return r.json(); })
      .catch(function (e) { var m = "Philibert could not do that (" + e.message + ")."; toast(m); return { ok: false, msg: m }; });
  }
  function toast(m) { var t = $("toast"); t.textContent = m; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove("on"); }, 3200); }
  function clock(ts) { return ts ? new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""; }
  function nice(d) {
    if (!d) return "";
    var x = new Date(d + "T12:00:00");
    return isNaN(x) ? d : x.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  }
  function mins(a, b) { return Math.max(0, Math.round(((b || Date.now() / 1000) - a) / 60)); }
  function student(id) { return cache.students.find(function (s) { return s.id === id; }); }
  function load() {
    return Promise.all([api("list", { table: "students" }), api("list", { table: "classes" }), api("settings")]).then(function (r) {
      cache.students = r[0].rows || []; cache.classes = r[1].rows || [];
      SET = (r[2] && r[2].settings) || {}; META = r[2] || {};
    });
  }
  function loadModels() {
    return fetch("/api/philibert/models", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })
      .then(function (r) { return r.json(); }).then(function (d) {
        MODELS = ((d && d.models) || []).filter(function (m) { return m.installed && (m.kind || "chat") === "chat"; });
        MODELS.default = d && d.default;
      }).catch(function () { MODELS = []; });
  }
  function busy(el) { el.innerHTML = '<div class="skel" style="width:60%"></div><div class="skel"></div><div class="skel" style="width:80%"></div>'; }

  /* ---------- icons ---------- */
  var IC = {
    today: "M4 5h16v15H4zM4 9h16M8 3v4M16 3v4M8 13h3v3H8z",
    make: "M6 3h9l4 4v14H6zM15 3v4h4M9 12h6M12 9v6",
    docs: "M7 3h8l4 4v14H7zM15 3v4h4M10 12h6M10 16h6M4 7v14h11",
    students: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M17 11a3 3 0 1 0 0-6M21 20c0-2.6-1.6-4.8-4-5.6",
    classes: "M3 5h18v11H3zM8 21h8M12 16v5M7 9h6M7 12h10",
    history: "M12 7v5l3 2M3.5 12a8.5 8.5 0 1 0 2.5-6M3 4v4h4",
    settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-2.7-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3.6 15H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.1-2.7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z",
    trash: "M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3",
    lock: "M6 11h12v9H6zM8 11V8a4 4 0 0 1 8 0v3"
  };
  function svg(k) { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="' + IC[k] + '"/></svg>'; }

  var VIEWS = [["today", "Today"], ["make", "Make"], ["docs", "Documents"], ["students", "Students"], ["classes", "Classes"],
               ["history", "History"], "-", ["settings", "Settings"], ["trash", "Trash"]];
  function drawNav(running) {
    nav.innerHTML = VIEWS.map(function (v) {
      if (v === "-") return '<div class="sep"></div>';
      var extra = v[0] === "today" && running ? '<span class="live" title="A class is running"></span>'
        : v[0] === "students" ? '<span class="n">' + cache.students.length + "</span>"
        : v[0] === "classes" ? '<span class="n">' + cache.classes.length + "</span>" : "";
      return '<a tabindex="0" data-v="' + v[0] + '" class="' + (cur === v[0] ? "on" : "") + '">' + svg(v[0]) + esc(v[1]) + extra + "</a>";
    }).join("");
  }
  nav.addEventListener("click", function (e) { var a = e.target.closest("a[data-v]"); if (a) go(a.dataset.v); });
  nav.addEventListener("keydown", function (e) { if (e.key === "Enter") { var a = e.target.closest("a[data-v]"); if (a) go(a.dataset.v); } });
  $("go-make").onclick = function () { go("make"); };

  function go(v, arg) {
    cur = v; clearInterval(liveTimer); clearTimeout(pollTimer); closeDrawer();
    drawNav(go.running);
    ({ today: viewToday, make: viewMake, docs: viewDocs, students: viewStudents, classes: viewClasses,
       history: viewHistory, settings: viewSettings, trash: viewTrash }[v] || viewToday)(arg);
  }

  /* ================= Today ================= */
  function viewToday() {
    busy(view);
    api("today").then(function (t) {
      if (!t.ok) { view.innerHTML = '<div class="empty">' + esc(t.msg) + "</div>"; return; }
      go.running = t.running.length > 0; drawNav(go.running);
      var runningIds = t.running.map(function (s) { return s.class_id; });
      t.classes.forEach(function (c) { c.running = runningIds.indexOf(c.id) >= 0; });
      var todays = t.classes.filter(function (c) { return c.today; }).sort(function (a, b) { return (a.start_time || "99").localeCompare(b.start_time || "99"); });
      var others = t.classes.filter(function (c) { return !c.today; });
      var html = '<h1>Today<span class="pill">' + esc(nice(t.date)) + '</span><span class="right">' +
        '<button class="btn" id="day-sum"' + (t.sessions.length ? "" : " disabled") + '>SUMMARY OF THE DAY</button></span></h1>' +
        '<p class="lead">Start a class when it begins: everybody is marked present, and a tap on a name changes it. Type notes as things happen; ' +
        "Yo Teach keeps the time on each one and writes the class summary from them.</p>";
      t.running.forEach(function (s) { html += liveCard(s); });
      html += '<div class="grid" style="margin-top:14px"><div class="card"><h2>Classes today</h2>' +
        (todays.length ? todays.map(classRow).join("") : '<div class="empty">No classes on today\'s timetable. ' +
          (cache.classes.length ? "Start any class below, or give a class its days in Classes." : 'Add your classes in <a href="#" data-go="classes" style="color:var(--cyan)">Classes</a> first.') + "</div>") +
        (others.length ? '<h2 style="margin-top:14px">Other classes</h2>' + others.map(classRow).join("") : "") +
        '</div><div class="card"><h2>Met today</h2>' +
        (t.sessions.filter(function (s) { return s.ended; }).map(function (s) {
          return '<div class="li click" data-sess="' + s.id + '"><span class="when">' + clock(s.started) + "–" + clock(s.ended) +
            '</span><span class="what">' + esc((s.class || {}).name || "Class") + "<small>" +
            (s.summary ? esc(s.summary.split("\n")[0]) : s.notes.length + " notes · no summary yet") + "</small></span></div>";
        }).join("") || '<div class="empty">Classes you finish today show up here with their summaries.</div>') + "</div></div>" +
        '<div id="day-out"></div>';
      view.innerHTML = html;
      t.running.forEach(wireLive);
      view.querySelectorAll("[data-start]").forEach(function (b) {
        b.onclick = function () {
          b.disabled = true;
          api("start", { class_id: +b.dataset.start }).then(function (r) { if (!r.ok) toast(r.msg); viewToday(); });
        };
      });
      view.querySelectorAll("[data-sess]").forEach(function (el) { el.onclick = function () { openSession(+el.dataset.sess); }; });
      view.querySelectorAll("[data-go]").forEach(function (a) { a.onclick = function (e) { e.preventDefault(); go(a.dataset.go); }; });
      $("day-sum").onclick = function () {
        var b = this; b.disabled = true; b.textContent = "WRITING…";
        $("day-out").innerHTML = '<div class="card" style="margin-top:14px"><div class="progress busy"><i style="width:100%"></i></div><div class="step">The model is reading today\'s notes…</div></div>';
        api("day_summary", { date: t.date }).then(function (r) {
          b.disabled = false; b.textContent = "SUMMARY OF THE DAY";
          $("day-out").innerHTML = '<div class="card" style="margin-top:14px"><h2>Summary of ' + esc(nice(t.date)) +
            '<button class="btn small" id="copy-day">COPY</button></h2><div class="summary">' + esc(r.ok ? r.text : r.msg) + "</div></div>";
          if ($("copy-day")) $("copy-day").onclick = function () { copy(r.text || ""); };
        });
      };
      clearInterval(liveTimer);
      if (t.running.length) liveTimer = setInterval(function () {
        view.querySelectorAll("[data-since]").forEach(function (el) { el.textContent = mins(+el.dataset.since) + " min"; });
      }, 20000);
    });
  }
  function classRow(c) {
    return '<div class="li"><span class="when">' + esc((c.start_time || "") + (c.end_time ? "–" + c.end_time : "")) +
      '</span><span class="what">' + esc(c.name) + "<small>" + esc([c.subject, c.room, c.students.length + " student" + (c.students.length === 1 ? "" : "s")].filter(Boolean).join(" · ")) +
      "</small></span>" + (c.running ? '<span class="pill" style="color:var(--pink);border-color:rgba(255,46,136,.5)">running</span>'
                                      : '<button class="btn small" data-start="' + c.id + '">START</button>') + "</div>";
  }
  function liveCard(s) {
    var opts = s.attendance.map(function (a) { return '<option value="' + a.student_id + '">' + esc(a.label) + "</option>"; }).join("");
    return '<div class="card live-card" data-live="' + s.id + '"><div class="live-head"><span class="dot"></span><h3>' + esc((s.class || {}).name || "Class") +
      '</h3><span class="elapsed" data-since="' + s.started + '">' + mins(s.started) + ' min</span><span class="pill">started ' + clock(s.started) + "</span>" +
      '<span class="acts"><button class="btn" data-sum="' + s.id + '">SUMMARIZE NOW</button><button class="btn primary" data-end="' + s.id + '">END CLASS</button></span></div>' +
      '<div class="field"><input data-topic="' + s.id + '" placeholder="Topic today (optional)" value="' + esc(s.topic || "") + '"></div>' +
      (s.attendance.length ? '<div class="roster">' + s.attendance.map(function (a) {
        return '<button class="chip ' + a.status.replace(" ", "-") + (selStudent === a.student_id ? " sel" : "") + '" data-att="' + a.student_id +
          '" title="Tap to change: present, late, absent, excused, left early. Right-click to write notes about this student."><b>' + esc(a.label) + "</b><span>" + esc(a.status) + "</span></button>";
      }).join("") + "</div>" : '<div class="empty">This class has no students on its list - add them in Classes. Notes still work.</div>') +
      '<div class="notebar"><select data-who><option value="">Whole class</option>' + opts + '</select><select data-kind>' +
      (META.note_kinds || ["note"]).map(function (k) { return "<option>" + esc(k) + "</option>"; }).join("") +
      '</select><input data-text placeholder="Type a note and press Enter" maxlength="2000"><button class="btn primary" data-add>ADD</button></div>' +
      '<div class="feed">' + notesHtml(s.notes) + "</div>" +
      (s.summary ? '<div class="summary" style="margin-top:12px"><small>SUMMARY AT ' + clock(s.summary_at) + "</small>" + esc(s.summary) + "</div>" : "") + "</div>";
  }
  function notesHtml(notes) {
    if (!notes.length) return '<div class="empty">Notes you type show up here, newest first.</div>';
    return notes.slice().reverse().map(function (n) {
      return '<div class="n"><span class="t">' + clock(n.at) + '</span><span class="w">' + esc(n.label || "Whole class") + "<i>" + esc(n.kind || "note") +
        "</i></span><span>" + esc(n.text) + "</span></div>";
    }).join("");
  }
  function wireLive(s) {
    var card = view.querySelector('[data-live="' + s.id + '"]');
    if (!card) return;
    var order = META.statuses || ["present", "late", "absent", "excused", "left early"];
    card.querySelectorAll("[data-att]").forEach(function (b) {
      b.onclick = function () {
        var a = s.attendance.find(function (x) { return x.student_id === +b.dataset.att; });
        var next = order[(order.indexOf(a.status) + 1) % order.length];
        a.status = next; b.className = "chip " + next.replace(" ", "-"); b.querySelector("span").textContent = next;
        api("mark", { session_id: s.id, student_id: a.student_id, status: next }).then(function (r) { if (!r.ok) toast(r.msg); });
      };
      b.oncontextmenu = function (e) {
        e.preventDefault(); selStudent = +b.dataset.att;
        card.querySelector("[data-who]").value = String(selStudent);
        card.querySelectorAll(".chip").forEach(function (c) { c.classList.toggle("sel", +c.dataset.att === selStudent); });
        card.querySelector("[data-text]").focus();
      };
    });
    var input = card.querySelector("[data-text]");
    function add() {
      var text = input.value.trim();
      if (!text) { input.focus(); return; }
      var who = card.querySelector("[data-who]").value;
      input.value = "";
      api("note", { session_id: s.id, student_id: who ? +who : null, kind: card.querySelector("[data-kind]").value, text: text }).then(function (r) {
        if (!r.ok) { toast(r.msg); input.value = text; return; }
        s.notes = r.session.notes; card.querySelector(".feed").innerHTML = notesHtml(s.notes);
      });
      input.focus();
    }
    input.onkeydown = function (e) { if (e.key === "Enter") add(); };
    card.querySelector("[data-add]").onclick = add;
    var topic = card.querySelector("[data-topic]");
    topic.onchange = function () { api("save", { table: "sessions", row: { id: s.id, topic: topic.value } }); };
    card.querySelector("[data-sum]").onclick = function () {
      var b = this; b.disabled = true; b.textContent = "WRITING…";
      api("summarize", { id: s.id }).then(function (r) {
        b.disabled = false; b.textContent = "SUMMARIZE NOW";
        if (!r.ok) { toast(r.msg); return; }
        viewToday();
      });
    };
    card.querySelector("[data-end]").onclick = function () {
      var b = this; b.disabled = true;
      api("end", { id: s.id }).then(function (r) {
        if (!r.ok) { toast(r.msg); b.disabled = false; return; }
        if (r.session.notes.length) {
          toast("Class ended. Writing its summary…");
          api("summarize", { id: s.id }).then(function (x) { if (!x.ok) toast(x.msg); if (cur === "today") viewToday(); });
        } else toast("Class ended.");
        viewToday();
      });
    };
  }

  /* ================= one class meeting ================= */
  function openSession(id) {
    api("session", { id: id }).then(function (r) {
      if (!r.ok) { toast(r.msg); return; }
      var s = r.session;
      openDrawer(((s.class || {}).name || "Class") + " · " + nice(s.date),
        '<div class="field"><label>When</label>' + clock(s.started) + "–" + (s.ended ? clock(s.ended) : "still running") +
        (s.topic ? " · " + esc(s.topic) : "") + "</div>" +
        '<div class="field"><label>Attendance</label>' + (s.attendance.map(function (a) {
          return '<span class="pill" style="margin:0 6px 6px 0;display:inline-block">' + esc(a.label) + ": " + esc(a.status) + "</span>";
        }).join("") || '<span class="empty">nobody on the list</span>') + "</div>" +
        '<div class="field"><label>Summary</label>' + (s.summary ? '<div class="summary">' + esc(s.summary) + "</div>" : '<div class="empty">No summary yet.</div>') + "</div>" +
        '<div class="field"><label>Notes</label><div class="feed" style="max-height:none">' + notesHtml(s.notes) + "</div></div>",
        '<button class="btn primary" id="s-sum">' + (s.summary ? "WRITE THE SUMMARY AGAIN" : "WRITE THE SUMMARY") + "</button>" +
        (s.summary ? '<button class="btn" id="s-copy">COPY SUMMARY</button>' : "") +
        '<span class="spacer"></span><button class="btn danger" id="s-del">DELETE</button>');
      $("s-sum").onclick = function () {
        var b = this; b.disabled = true; b.textContent = "WRITING…";
        api("summarize", { id: s.id }).then(function (x) { if (!x.ok) { toast(x.msg); b.disabled = false; b.textContent = "WRITE THE SUMMARY"; return; } openSession(s.id); });
      };
      if ($("s-copy")) $("s-copy").onclick = function () { copy(s.summary); };
      $("s-del").onclick = function () {
        api("delete", { table: "sessions", id: s.id }).then(function () { toast("Moved to the Trash."); closeDrawer(); go(cur); });
      };
    });
  }
  function copy(text) {
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(function () { toast("Copied."); },
      function () { toast("Could not copy - select the text and copy it."); });
  }

  /* ================= Make ================= */
  var KIND_ORDER = ["lesson", "worksheet", "homework", "project", "assessment", "teacher"];
  var KIND_HELP = { lesson: "Lesson", worksheet: "Worksheet", homework: "Homework", project: "Project", assessment: "Assessment", teacher: "Teacher copy (key, pacing, supports)" };
  function viewMake(pre) {
    pre = pre || {};
    var models = MODELS.filter(function (m) { return !m.vision; });
    var hasModel = !!(SET.writer_model || models.length);
    var html = '<h1>Make a lesson</h1><p class="lead">Pick the student and the topic, tick the documents you want and how long each should take. ' +
      "Each one comes out as its own Word file and PDF, with your format rules applied before it is saved. A screenshot of the assignment " +
      "or the student's page helps the model aim right.</p>" +
      (hasModel ? "" : '<div class="card" style="border-color:rgba(245,158,11,.5)"><b style="color:var(--amber)">No writing model yet.</b> ' +
        'Download one in the Models app (Qwen3 14B on a computer with a big graphics card), then choose it in <a href="#" data-go="settings" style="color:var(--cyan)">Settings</a>.</div>') +
      '<div class="make"><div class="card"><div class="two"><div class="field"><label>Student</label><select id="m-student"><option value="">No particular student</option>' +
      cache.students.filter(function (s) { return s.active !== 0; }).map(function (s) {
        return '<option value="' + s.id + '"' + (pre.student_id === s.id ? " selected" : "") + ">" + esc(s.label) + (s.subject ? " · " + esc(s.subject) : "") + "</option>";
      }).join("") + '</select></div><div class="field"><label>Subject</label><input id="m-subject" placeholder="Spanish 3"></div></div>' +
      '<div class="two"><div class="field"><label>Level</label><input id="m-level" placeholder="e.g. Spanish 3, entry level, senior"></div>' +
      '<div class="field"><label>Writing model</label><select id="m-model">' + modelOptions(models, SET.writer_model) + "</select></div></div>" +
      '<div class="field"><label>Topic</label><input id="m-topic" placeholder="Past perfect subjunctive for emotional reactions to hypothetical situations"></div>' +
      '<div class="field"><label>Anything else the model should know</label><textarea id="m-details" placeholder="e.g. Use the vocabulary from last week. Two reference photos. Research with named sources."></textarea></div>' +
      '<div class="field"><label>Screenshot (optional)</label><div class="shot" id="m-shot" tabindex="0">Drop a picture here, paste it (Ctrl+V), or click to choose one.</div>' +
      '<input type="file" id="m-file" accept="image/*" hidden></div></div>' +
      '<div><div class="card"><h2>Documents</h2><div class="kinds">' + KIND_ORDER.map(function (k) {
        var on = (pre.kinds || ["lesson", "worksheet", "teacher"]).indexOf(k) >= 0;
        return '<label><input type="checkbox" data-kind="' + k + '"' + (on ? " checked" : "") + "> " + KIND_HELP[k] + "</label>" +
          (k === "teacher" ? "<span></span>" : '<input type="number" min="5" max="120" step="5" data-min="' + k + '" value="' + (k === "assessment" || k === "project" ? 30 : 20) + '" title="Minutes"' + (on ? "" : " disabled") + ">");
      }).join("") + '</div><p class="empty" style="margin-top:8px">Minutes set how much goes on the page. They are never printed on a student copy.</p>' +
      '<button class="btn primary" id="m-go" style="width:100%;margin-top:10px;padding:11px"' + (hasModel ? "" : " disabled") + '>MAKE THE DOCUMENTS</button></div>' +
      '<div class="card" id="m-out" style="display:none"></div>' +
      '<div class="private">' + svg("lock") + "<span>Made on your own computers by your own models. Students go by their label; nothing about them goes to the internet.</span></div></div></div>";
    view.innerHTML = html;
    view.querySelectorAll("[data-go]").forEach(function (a) { a.onclick = function (e) { e.preventDefault(); go(a.dataset.go); }; });
    var sel = $("m-student");
    function fill() {
      var s = student(+sel.value);
      $("m-subject").value = (s && s.subject) || $("m-subject").value || "";
      $("m-level").value = (s && s.level) || "";
    }
    sel.onchange = fill; fill();
    if (pre.topic) $("m-topic").value = pre.topic;
    view.querySelectorAll("[data-kind]").forEach(function (c) {
      c.onchange = function () { var n = view.querySelector('[data-min="' + c.dataset.kind + '"]'); if (n) n.disabled = !c.checked; };
    });
    wireShot();
    $("m-go").onclick = makeDocs;
    if (lastJob) watchJob(lastJob);
  }
  function modelOptions(list, chosen) {
    if (!list.length) return '<option value="">No model on this computer yet</option>';
    var pick = chosen || MODELS.default || (list[0] && list[0].tag);
    return list.map(function (m) {
      return '<option value="' + esc(m.tag) + '"' + (m.tag === pick ? " selected" : "") + ">" + esc(m.plain_name || m.label || m.tag) +
        (m.label && m.plain_name ? " (" + esc(m.label) + ")" : "") + "</option>";
    }).join("");
  }
  function wireShot() {
    var box = $("m-shot"), file = $("m-file");
    function show() {
      box.innerHTML = shot ? '<img src="' + shot + '" alt="The screenshot"><button class="btn small" id="m-noshot">REMOVE</button>'
                           : "Drop a picture here, paste it (Ctrl+V), or click to choose one.";
      if ($("m-noshot")) $("m-noshot").onclick = function (e) { e.stopPropagation(); shot = null; show(); };
    }
    function take(f) {
      if (!f || !/^image\//.test(f.type)) { toast("That is not a picture."); return; }
      if (f.size > 12e6) { toast("That picture is too big (12 MB at most)."); return; }
      var r = new FileReader(); r.onload = function () { shot = r.result; show(); }; r.readAsDataURL(f);
    }
    box.onclick = function () { file.click(); };
    box.onkeydown = function (e) { if (e.key === "Enter") file.click(); };
    file.onchange = function () { take(file.files[0]); file.value = ""; };
    box.ondragover = function (e) { e.preventDefault(); box.classList.add("over"); };
    box.ondragleave = function () { box.classList.remove("over"); };
    box.ondrop = function (e) { e.preventDefault(); box.classList.remove("over"); take(e.dataTransfer.files[0]); };
    document.onpaste = function (e) {
      if (cur !== "make") return;
      var it = [].slice.call((e.clipboardData || {}).items || []).find(function (i) { return /^image\//.test(i.type); });
      if (it) take(it.getAsFile());
    };
    show();
  }
  function makeDocs() {
    var kinds = [].slice.call(view.querySelectorAll("[data-kind]:checked")).map(function (c) { return c.dataset.kind; });
    var topic = $("m-topic").value.trim();
    if (!topic) { toast("Give it a topic first."); $("m-topic").focus(); return; }
    if (!kinds.length) { toast("Tick at least one document."); return; }
    var minutes = {};
    kinds.forEach(function (k) { var n = view.querySelector('[data-min="' + k + '"]'); if (n) minutes[k] = +n.value || 20; });
    var vision = MODELS.find(function (m) { return m.vision; });
    if (shot && !(SET.vision_model || vision)) { toast("Reading a screenshot needs a model that can see pictures - add one in the Models app."); return; }
    var req = { student_id: +$("m-student").value || null, subject: $("m-subject").value.trim(), level: $("m-level").value.trim(),
                topic: topic, details: $("m-details").value.trim(), kinds: kinds, minutes: minutes, model: $("m-model").value,
                vision_model: SET.vision_model || (vision && vision.tag) || "", screenshot: shot };
    $("m-go").disabled = true;
    api("make", { request: req }).then(function (r) {
      if (!r.ok) { toast(r.msg); $("m-go").disabled = false; return; }
      lastJob = r.job; watchJob(r.job);
    });
  }
  function watchJob(id) {
    var out = $("m-out");
    if (!out) return;
    out.style.display = "";
    api("job", { id: id }).then(function (j) {
      if (cur !== "make" || !$("m-out")) return;
      if (!j.ok) { lastJob = null; out.style.display = "none"; if ($("m-go")) $("m-go").disabled = false; return; }
      if (j.status === "running") {
        $("m-go").disabled = true;
        var pct = Math.round(100 * (j.done || 0) / Math.max(1, j.total || 1));
        out.innerHTML = "<h2>Working</h2><div class=\"progress busy\"><i style=\"width:" + Math.max(8, pct) + '%"></i></div><div class="step">' + esc(j.step) +
          "…</div><p class=\"empty\">A 14B model takes a minute or two per document. You can leave this page; the work carries on.</p>";
        pollTimer = setTimeout(function () { watchJob(id); }, 1500);
        return;
      }
      $("m-go").disabled = false; lastJob = null;
      if (j.status === "error") { out.innerHTML = '<h2>Could not finish</h2><div class="warn">' + esc(j.error) + "</div>"; return; }
      out.innerHTML = "<h2>Ready<span class=\"pill\" style=\"margin-left:auto\">" + j.result.docs.length + " documents</span></h2>" +
        j.result.docs.map(docHtml).join("") + '<div class="acts" style="margin-top:10px"><button class="btn small" data-folder="' + j.result.docs[0].id + '">OPEN THE FOLDER</button></div>';
      wireDocs(out);
    });
  }
  function docHtml(d) {
    var fixes = d.fixes || [];
    return '<div class="doc"><div class="ic">DOC</div><div class="body"><b>' + esc(d.title) + "</b><small>" +
      esc((META.kinds || {})[d.kind] || d.kind) + (d.minutes && d.kind !== "teacher" ? " · " + d.minutes + " min" : "") +
      (d.created ? " · " + new Date(d.created * 1000).toLocaleDateString() : "") + (d.pages ? " · " + d.pages + " page" + (d.pages > 1 ? "s" : "") : "") + "</small>" +
      (fixes.length ? '<ul class="fixes" title="Changed before saving, to follow your rules">' + fixes.slice(0, 4).map(function (f) { return "<li>Fixed: " + esc(f) + "</li>"; }).join("") + "</ul>" : "") +
      (d.pdf_error ? '<div class="warn">No PDF: ' + esc(d.pdf_error) + ". The Word file is there.</div>" : "") +
      '<div class="acts"><button class="btn small" data-open="' + d.id + '" data-which="docx">OPEN IN WORD</button>' +
      (d.pdf || !d.pdf_error ? '<button class="btn small" data-open="' + d.id + '" data-which="pdf">OPEN PDF</button>' : "") +
      '<button class="btn small" data-edit="' + d.id + '">EDIT TEXT</button></div></div></div>';
  }
  function wireDocs(root) {
    root.querySelectorAll("[data-open]").forEach(function (b) {
      b.onclick = function () { api("open", { id: +b.dataset.open, which: b.dataset.which }).then(function (r) { if (!r.ok) toast(r.msg); }); };
    });
    root.querySelectorAll("[data-folder]").forEach(function (b) {
      b.onclick = function () { api("open", { id: +b.dataset.folder, folder: true }).then(function (r) { if (!r.ok) toast(r.msg); }); };
    });
    root.querySelectorAll("[data-edit]").forEach(function (b) { b.onclick = function () { editDoc(+b.dataset.edit); }; });
  }
  function editDoc(id) {
    api("doc", { id: id }).then(function (r) {
      if (!r.ok) { toast(r.msg); return; }
      var d = r.doc;
      openDrawer("Edit: " + d.title, '<p class="empty" style="margin-bottom:10px">Change the words, then save: the Word file and the PDF are made again from this text, ' +
        "with your rules applied. # starts a heading, - a bullet, | a table row, [space 4] leaves room to write.</p>" +
        '<div class="field"><textarea class="tall" id="e-src">' + esc(d.source || "") + "</textarea></div>",
        '<button class="btn primary" id="e-save">SAVE AND REMAKE THE FILES</button>', true);
      $("e-save").onclick = function () {
        var b = this; b.disabled = true; b.textContent = "MAKING…";
        api("remake", { id: id, source: $("e-src").value }).then(function (x) {
          b.disabled = false; b.textContent = "SAVE AND REMAKE THE FILES";
          if (!x.ok) { toast(x.msg); return; }
          toast(x.doc.pdf_error ? "Word file saved. No PDF: " + x.doc.pdf_error : "Saved. Both files are made again.");
          closeDrawer(); if (cur === "docs") viewDocs();
        });
      };
    });
  }

  /* ================= Documents ================= */
  function viewDocs(sid) {
    busy(view);
    api("docs", sid ? { student_id: sid } : {}).then(function (r) {
      var docs = r.docs || [];
      view.innerHTML = '<h1>Documents</h1><p class="lead">Everything made in Yo Teach, newest first. The files are in Documents › Yo Teach on your drive, a folder per student.</p>' +
        '<div class="toolbar"><select id="d-filter"><option value="">Every student</option>' + cache.students.map(function (s) {
          return '<option value="' + s.id + '"' + (sid === s.id ? " selected" : "") + ">" + esc(s.label) + "</option>";
        }).join("") + '</select><input type="search" id="d-q" placeholder="Search titles"></div><div class="card" id="d-list"></div>';
      function draw() {
        var q = $("d-q").value.toLowerCase();
        var list = docs.filter(function (d) { return !q || (d.title || "").toLowerCase().indexOf(q) >= 0; });
        $("d-list").innerHTML = list.map(function (d) {
          var s = student(d.student_id);
          return docHtml(d).replace("<small>", "<small>" + (s ? esc(s.label) + " · " : ""));
        }).join("") || '<div class="empty">' + (docs.length ? "Nothing matches." : 'Nothing made yet. <a href="#" data-go="make" style="color:var(--cyan)">Make a lesson</a> to start.') + "</div>";
        wireDocs($("d-list"));
        $("d-list").querySelectorAll("[data-go]").forEach(function (a) { a.onclick = function (e) { e.preventDefault(); go(a.dataset.go); }; });
      }
      $("d-filter").onchange = function () { viewDocs(+this.value || null); };
      $("d-q").oninput = draw; draw();
    });
  }

  /* ================= Students ================= */
  var S_FIELDS = [["label", "Label (how Yo Teach names them)", "text", "Student G"], ["name", "Name (optional, stays on this computer)", "text", ""],
                  ["subject", "Subject", "text", "Spanish 3"], ["level", "Level", "text", ""],
                  ["strengths", "Strengths (documented)", "area", ""], ["needs", "Needs (documented)", "area", ""],
                  ["supports", "Supports that work", "area", "e.g. one section at a time; worked example first"],
                  ["accommodations", "Formal accommodations (only official ones)", "area", ""],
                  ["interests", "Interests the student has shown", "text", ""], ["notes", "Notes", "area", ""]];
  function viewStudents() {
    var list = cache.students;
    view.innerHTML = '<h1>Students<span class="right"><button class="btn primary" id="s-new">+ STUDENT</button></span></h1>' +
      '<p class="lead">Each student by a label - Student A, Student G. Only what you write here is used when a lesson is made for them; ' +
      "keep formal accommodations to the official ones.</p>" +
      (list.length ? '<div class="card"><table><thead><tr><th>Label</th><th>Subject</th><th>Level</th><th>Supports</th></tr></thead><tbody>' +
        list.map(function (s) {
          return '<tr data-id="' + s.id + '"><td><b>' + esc(s.label) + "</b>" + (s.name ? '<br><small style="color:var(--faint)">' + esc(s.name) + "</small>" : "") +
            "</td><td>" + esc(s.subject || "") + "</td><td>" + esc(s.level || "") + "</td><td>" + esc((s.supports || "").slice(0, 90)) + "</td></tr>";
        }).join("") + "</tbody></table></div>"
        : '<div class="card"><div class="empty">No students yet. Add each one with <b>+ STUDENT</b>: a label, the subject, and anything documented that a lesson should respect.</div></div>');
    $("s-new").onclick = function () { editStudent({}); };
    view.querySelectorAll("tr[data-id]").forEach(function (tr) { tr.onclick = function () { editStudent(student(+tr.dataset.id)); }; });
  }
  function form(fields, row) {
    return fields.map(function (f) {
      var v = row[f[0]] == null ? "" : row[f[0]];
      return '<div class="field"><label for="f-' + f[0] + '">' + esc(f[1]) + "</label>" +
        (f[2] === "area" ? '<textarea id="f-' + f[0] + '" placeholder="' + esc(f[3] || "") + '">' + esc(v) + "</textarea>"
         : '<input id="f-' + f[0] + '" type="' + (f[2] === "time" ? "time" : f[2] === "number" ? "number" : "text") + '" placeholder="' + esc(f[3] || "") + '" value="' + esc(v) + '">') + "</div>";
    }).join("");
  }
  function collect(fields) { var o = {}; fields.forEach(function (f) { o[f[0]] = $("f-" + f[0]).value.trim(); }); return o; }
  function editStudent(s) {
    openDrawer(s.id ? s.label : "New student", form(S_FIELDS, s),
      '<button class="btn primary" id="f-save">SAVE</button>' + (s.id ? '<button class="btn" id="f-make">MAKE A LESSON</button><button class="btn" id="f-docs">DOCUMENTS</button>' +
      '<span class="spacer"></span><button class="btn danger" id="f-del">DELETE</button>' : ""));
    $("f-save").onclick = function () {
      var row = collect(S_FIELDS); if (s.id) row.id = s.id;
      api("save", { table: "students", row: row }).then(function (r) {
        if (!r.ok) { toast(r.msg); return; }
        toast("Saved."); load().then(function () { closeDrawer(); go("students"); });
      });
    };
    if (s.id) {
      $("f-make").onclick = function () { go("make", { student_id: s.id }); };
      $("f-docs").onclick = function () { go("docs", s.id); };
      $("f-del").onclick = function () {
        api("delete", { table: "students", id: s.id }).then(function () { toast("Moved to the Trash."); load().then(function () { go("students"); }); });
      };
    }
  }

  /* ================= Classes ================= */
  var C_FIELDS = [["name", "Name", "text", "Spanish 1 - Fairfield"], ["subject", "Subject", "text", "Spanish"], ["room", "Room", "text", ""],
                  ["days", "Days", "text", "Mon, Wed, Fri (empty: every day)"], ["start_time", "Starts", "time", ""], ["end_time", "Ends", "time", ""],
                  ["notes", "Notes", "area", ""]];
  function viewClasses() {
    var list = cache.classes;
    view.innerHTML = '<h1>Classes<span class="right"><button class="btn primary" id="c-new">+ CLASS</button></span></h1>' +
      '<p class="lead">A class is anything you take attendance and notes for: a group, a one-to-one slot, a club. Give it its days and times and it shows up on Today.</p>' +
      (list.length ? '<div class="card"><table><thead><tr><th>Name</th><th>Subject</th><th>When</th><th>Summary</th></tr></thead><tbody>' +
        list.map(function (c) {
          return '<tr data-id="' + c.id + '"><td><b>' + esc(c.name) + "</b></td><td>" + esc(c.subject || "") + "</td><td>" +
            esc([c.days, (c.start_time || "") + (c.end_time ? "–" + c.end_time : "")].filter(Boolean).join(" · ")) + "</td><td>" +
            (c.summary_every ? "every " + c.summary_every + " min" : "at the end") + "</td></tr>";
        }).join("") + "</tbody></table></div>"
        : '<div class="card"><div class="empty">No classes yet. Add one with <b>+ CLASS</b> and tick its students.</div></div>');
    $("c-new").onclick = function () { editClass({ students: [] }); };
    view.querySelectorAll("tr[data-id]").forEach(function (tr) {
      tr.onclick = function () { api("class", { id: +tr.dataset.id }).then(function (r) { if (r.ok) editClass(r.class); }); };
    });
  }
  function editClass(c) {
    var every = [[0, "When the class ends"], [10, "Every 10 minutes"], [15, "Every 15 minutes"], [20, "Every 20 minutes"], [30, "Every 30 minutes"]];
    openDrawer(c.id ? c.name : "New class", form(C_FIELDS, c) +
      '<div class="field"><label>Class summary</label><select id="f-every">' + every.map(function (e) {
        return '<option value="' + e[0] + '"' + ((c.summary_every || 0) === e[0] ? " selected" : "") + ">" + e[1] + "</option>";
      }).join("") + '</select><div class="hint">While the class runs, a fresh summary is written this often when there are new notes. ' +
      "It always gets one when it ends.</div></div>" +
      '<div class="field"><label>Students</label>' + (cache.students.length ? '<div class="checks">' + cache.students.map(function (s) {
        return '<label><input type="checkbox" data-st="' + s.id + '"' + ((c.students || []).indexOf(s.id) >= 0 ? " checked" : "") + "> " + esc(s.label) + "</label>";
      }).join("") + "</div>" : '<div class="empty">Add students first - then tick them here.</div>') + "</div>",
      '<button class="btn primary" id="f-save">SAVE</button>' + (c.id ? '<button class="btn" id="f-start">START NOW</button><span class="spacer"></span><button class="btn danger" id="f-del">DELETE</button>' : ""));
    $("f-save").onclick = function () {
      var row = collect(C_FIELDS); if (c.id) row.id = c.id;
      row.summary_every = +$("f-every").value;
      row.students = [].slice.call(document.querySelectorAll("[data-st]:checked")).map(function (x) { return +x.dataset.st; });
      api("save", { table: "classes", row: row }).then(function (r) {
        if (!r.ok) { toast(r.msg); return; }
        toast("Saved."); load().then(function () { closeDrawer(); go("classes"); });
      });
    };
    if (c.id) {
      $("f-start").onclick = function () { api("start", { class_id: c.id }).then(function (r) { if (!r.ok) toast(r.msg); go("today"); }); };
      $("f-del").onclick = function () {
        api("delete", { table: "classes", id: c.id }).then(function () { toast("Moved to the Trash."); load().then(function () { go("classes"); }); });
      };
    }
  }

  /* ================= History ================= */
  function viewHistory() {
    busy(view);
    api("list", { table: "sessions" }).then(function (r) {
      var rows = r.rows || [], byDay = {};
      rows.forEach(function (s) { (byDay[s.date] = byDay[s.date] || []).push(s); });
      var names = {}; cache.classes.forEach(function (c) { names[c.id] = c.name; });
      view.innerHTML = '<h1>History</h1><p class="lead">Every class you have run, by day. Open one to see its attendance, notes and summary.</p>' +
        (Object.keys(byDay).map(function (d) {
          return '<div class="card"><h2>' + esc(nice(d)) + "</h2>" + byDay[d].map(function (s) {
            return '<div class="li click" data-sess="' + s.id + '"><span class="when">' + clock(s.started) + (s.ended ? "–" + clock(s.ended) : " · running") +
              '</span><span class="what">' + esc(names[s.class_id] || "Class") + (s.topic ? " · " + esc(s.topic) : "") + "<small>" +
              esc(s.summary ? s.summary.split("\n")[0] : "no summary") + "</small></span></div>";
          }).join("") + "</div>";
        }).join("") || '<div class="card"><div class="empty">Nothing yet. Classes you start on Today are kept here.</div></div>');
      view.querySelectorAll("[data-sess]").forEach(function (el) { el.onclick = function () { openSession(+el.dataset.sess); }; });
    });
  }

  /* ================= Settings ================= */
  function viewSettings() {
    var chat = MODELS.filter(function (m) { return !m.vision; }), eyes = MODELS.filter(function (m) { return m.vision; });
    view.innerHTML = '<h1>Settings</h1><p class="lead">Which models Yo Teach uses, and the rules every document follows. The rules are given to the model, ' +
      "and the format ones are also checked in code before a file is saved.</p>" +
      '<div class="grid"><div class="card"><h2>Models</h2>' +
      '<div class="field"><label>Writes lessons and worksheets</label><select id="x-writer">' + modelOptions(chat, SET.writer_model) +
      '</select><div class="hint">The biggest model your computer runs well. Qwen3 14B on a GTX 1080 Ti.</div></div>' +
      '<div class="field"><label>Reads screenshots</label><select id="x-vision">' + (eyes.length ? modelOptions(eyes, SET.vision_model)
        : '<option value="">None yet - add "Reads pictures" in the Models app</option>') + "</select></div>" +
      '<div class="field"><label>Writes class summaries</label><select id="x-summary"><option value="">Same as the writing model</option>' +
      chat.map(function (m) { return '<option value="' + esc(m.tag) + '"' + (SET.summary_model === m.tag ? " selected" : "") + ">" + esc(m.plain_name || m.label || m.tag) + "</option>"; }).join("") +
      '</select><div class="hint">A smaller model is fine here and quicker.</div></div>' +
      '<div class="two"><div class="field"><label>School</label><input id="x-school" value="' + esc(SET.school || "") + '"></div>' +
      '<div class="field"><label>Teacher</label><input id="x-teacher" value="' + esc(SET.teacher || "") + '"></div></div>' +
      '<button class="btn primary" id="x-save">SAVE</button></div>' +
      '<div class="card"><h2>Your data</h2><p class="empty">Everything is in one file on this drive, copied once a day before the first change ' +
      "(the last 14 days are kept in exports › Yo Teach backups).</p>" +
      '<div class="acts" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px"><button class="btn" id="x-backup">BACK UP NOW</button>' +
      '<button class="btn" id="x-export">EXPORT (JSON)</button><button class="btn" id="x-import">IMPORT…</button>' +
      '<input type="file" id="x-file" accept=".json,application/json" hidden></div>' +
      '<p class="empty" style="margin-top:8px">Import adds the students and classes from a Yo Teach file (from your other computer, or a starter file). ' +
      "What is already here stays as it is.</p></div></div>" +
      '<div class="card"><h2>Document rules<button class="btn small" id="x-reset">BACK TO THE DEFAULT</button></h2>' +
      '<div class="field"><textarea class="tall" id="x-rules">' + esc(SET.rules || "") + "</textarea></div>" +
      '<button class="btn primary" id="x-save2">SAVE THE RULES</button></div>';
    function save() {
      var s = { writer_model: $("x-writer").value, vision_model: $("x-vision").value, summary_model: $("x-summary").value,
                school: $("x-school").value.trim(), teacher: $("x-teacher").value.trim(), rules: $("x-rules").value };
      api("settings_save", { settings: s }).then(function (r) { if (!r.ok) { toast(r.msg); return; } SET = r.settings; toast("Saved."); });
    }
    $("x-save").onclick = save; $("x-save2").onclick = save;
    $("x-reset").onclick = function () { $("x-rules").value = META.default_rules || ""; toast("The default rules are back - SAVE to keep them."); };
    $("x-backup").onclick = function () { api("backup").then(function (r) { toast(r.ok ? "Backed up: " + r.name : r.msg); }); };
    $("x-export").onclick = function () {
      api("export").then(function (r) {
        if (!r.ok) { toast(r.msg); return; }
        var a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([JSON.stringify(r.data, null, 2)], { type: "application/json" }));
        a.download = "Yo Teach " + new Date().toISOString().slice(0, 10) + ".json"; a.click();
      });
    };
    $("x-import").onclick = function () { $("x-file").click(); };
    $("x-file").onchange = function () {
      var f = this.files[0]; this.value = "";
      if (!f) return;
      f.text().then(function (t) {
        var data; try { data = JSON.parse(t); } catch (e) { toast("That file is not a Yo Teach file."); return; }
        api("import", { data: data }).then(function (r) {
          if (!r.ok) { toast(r.msg); return; }
          toast("Imported: " + r.students + " new students, " + r.classes + " classes" + (r.updated ? ", " + r.updated + " filled in" : "") + ".");
          load().then(function () { go("settings"); });
        });
      });
    };
  }

  /* ================= Trash ================= */
  function viewTrash() {
    busy(view);
    api("trash").then(function (r) {
      var rows = [], names = { students: "Student", classes: "Class", sessions: "Class meeting", docs: "Document", notes: "Note", attendance: "Attendance" };
      Object.keys(r.rows || {}).forEach(function (t) { (r.rows[t] || []).forEach(function (x) { rows.push({ t: t, x: x }); }); });
      view.innerHTML = '<h1>Trash</h1><p class="lead">What you delete waits here. Put it back, or empty the Trash to remove it for good.</p>' +
        '<div class="card">' + (rows.map(function (o) {
          var x = o.x, what = x.label || x.name || x.title || x.text || (x.date ? nice(x.date) : "#" + x.id);
          return '<div class="li"><span class="pill">' + names[o.t] + '</span><span class="what">' + esc(what) +
            '</span><button class="btn small" data-rt="' + o.t + '" data-ri="' + x.id + '">PUT BACK</button></div>';
        }).join("") || '<div class="empty">The Trash is empty.</div>') + "</div>" +
        (rows.length ? '<button class="btn danger" id="t-empty" style="margin-top:12px">EMPTY THE TRASH</button>' : "");
      view.querySelectorAll("[data-rt]").forEach(function (b) {
        b.onclick = function () { api("restore", { table: b.dataset.rt, id: +b.dataset.ri }).then(function () { load().then(viewTrash); }); };
      });
      if ($("t-empty")) $("t-empty").onclick = function () {
        if (!confirm("Remove everything in the Trash for good?")) return;
        api("purge").then(function () { toast("The Trash is empty."); viewTrash(); });
      };
    });
  }

  /* ================= drawer ================= */
  function openDrawer(title, body, foot, wide) {
    $("d-title").textContent = title; $("d-body").innerHTML = body; $("d-foot").innerHTML = foot || "";
    $("drawer").classList.toggle("wide", !!wide); $("drawer").classList.add("on");
    var f = $("d-body").querySelector("input, textarea"); if (f) setTimeout(function () { f.focus(); }, 230);
  }
  function closeDrawer() { $("drawer").classList.remove("on"); }
  $("d-close").onclick = closeDrawer;
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeDrawer(); });

  function tick() { $("clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
  tick(); setInterval(tick, 15000);
  drawNav(false); busy(view);
  function fromHash() {
    var m = location.hash.replace("#", "");
    return VIEWS.some(function (v) { return v[0] === m; }) ? m : "";
  }
  window.addEventListener("hashchange", function () { var m = fromHash(); if (m && m !== cur) go(m); });
  Promise.all([load(), loadModels()]).then(function () { go(fromHash() || "today"); });
})();
