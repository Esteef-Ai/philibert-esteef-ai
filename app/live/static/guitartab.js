/* Philibert TabCrafter: a solo guitar recording -> tablature (nd_guitartab.py does the work).
 * The page: your tabs on the left; a drop zone for a new recording; the strings, tuning and
 * tempo (typed, tapped or listened for); the tab, drawn here so edits are instant; a player
 * for the recording (the tab follows it) and for the tab itself; click a fret to fix it.
 * Also the Audio File Splitter (#split, nd_audiosplit.py): a long audiobook cut into parts. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var st = { installed: false, install: null, internet: true, tunings: [], items: [], cur: null, item: null, tab: null,
             orig: null, undo: [], settings: null, saveT: null, poll: null, sel: null, play: null, speed: 1,
             mode: null, split: null };
  var NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  var TIMES = [[4, 4], [3, 4], [2, 4], [6, 8], [12, 8], [5, 4], [7, 8]];

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return "&#" + c.charCodeAt(0) + ";"; }); }
  function api(op, data) {
    return fetch("/api/guitartab", { method: "POST", headers: { "Content-Type": "application/json" },
                                     body: JSON.stringify(Object.assign({ op: op }, data || {})) }).then(function (r) { return r.json(); })
      .catch(function (e) { return { ok: false, msg: "Philibert could not do that (" + e.message + ")." }; });
  }
  function toast(m) { var t = $("toast"); t.textContent = m; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove("on"); }, 3600); }
  function status(m, cls) { var s = $("status"); s.textContent = m; s.className = cls || ""; }
  function noteName(m) { return NAMES[m % 12] + (Math.floor(m / 12) - 1); }
  function when(s) { return s ? s.slice(0, 16).replace("T", " ") : ""; }

  /* ================= the list ================= */
  function loadList(select) {
    return api("list").then(function (d) {
      st.items = d.items || [];
      drawNav();
      if (select) open(select);
      else if (!st.cur) drawView();
    });
  }
  function drawNav() {
    var n = $("nav");
    var h = '<button class="btn primary" id="new2" type="button"' + (st.installed ? "" : " disabled") + '>+ NEW TAB</button>';
    h += '<button class="item tool' + (st.mode === "split" ? " on" : "") + '" type="button" id="splitNav"><b>✂ Audio File Splitter</b>'
       + "<small>long audio → parts</small></button>";
    if (!st.items.length) h += '<p class="navempty">Your tabs show up here. Drop a recording on the right to make the first one.</p>';
    st.items.forEach(function (it) {
      var sub = it.job && it.job.state === "running" ? '<small class="busy">writing the tab…</small>'
              : it.job && it.job.state === "error" ? '<small class="busy">needs another try</small>'
              : "<small>" + (it.has_tab ? (it.bpm ? it.bpm + " BPM · " : "") + it.strings + " strings" : "no tab yet") + (it.edited ? " · edited" : "") + "</small>";
      h += '<button class="item' + (it.id === st.cur ? " on" : "") + '" type="button" data-id="' + it.id + '"><b>' + esc(it.name) + "</b>" + sub + "</button>";
    });
    n.innerHTML = h;
    $("new2").onclick = pick;
    $("splitNav").onclick = openSplit;
    n.querySelectorAll(".item[data-id]").forEach(function (b) { b.onclick = function () { open(b.dataset.id); }; });
    $("new").disabled = !st.installed;
  }

  /* ================= views ================= */
  function drawView() {
    stop();
    var v = $("view");
    if (st.mode === "split") return drawSplit();
    if (!st.installed) return drawSetup();
    if (!st.cur) {
      v.innerHTML = '<h1>TabCrafter</h1><p class="lead">Give it a recording of a guitar on its own - a DI track, a stem, '
        + "or you playing into a microphone - and it writes the tab: notes, rhythm, and a string and fret for each note the way "
        + "a hand would play it. You check it against the recording and fix what it got wrong.</p>"
        + '<div class="drop" id="drop" tabindex="0" role="button" aria-label="Choose a recording">'
        + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M5 14v5h14v-5"/></svg>'
        + "<b>Drop a guitar recording here</b><span>or click to choose one - .wav, .mp3, .flac or .ogg</span></div>";
      var d = $("drop");
      d.onclick = pick;
      d.onkeydown = function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } };
      status(st.items.length ? st.items.length + " tab" + (st.items.length === 1 ? "" : "s") + " on this drive" : "Ready", "ok");
      return;
    }
    drawItem();
  }

  function drawSetup() {
    var i = st.install || {};
    var running = i.state === "running";
    $("view").innerHTML = '<div class="setup"><h1>Set up TabCrafter</h1>'
      + '<p class="lead">TabCrafter needs its note finder on this computer first. It is about 150 MB to download and 500 MB on the drive, and it is '
      + "only needed once per computer the drive is used on.</p>"
      + '<div class="card"><h2>What it does</h2><ul><li>Finds every note in a solo guitar recording</li>'
      + "<li>Follows the beat from the tempo you give it (typed, or tapped along)</li>"
      + "<li>Picks a string and fret for each note, for 6, 7 or 8 strings in any tuning</li>"
      + "<li>Plays the recording with the tab following along, and lets you fix any note</li></ul>"
      + '<div class="go"><button class="btn primary" id="setup" type="button"' + (running ? " disabled" : "") + ">" + (running ? "SETTING UP…" : "SET UP TABCRAFTER") + "</button>"
      + (running ? '<div class="bar"><i style="width:' + Math.round((i.progress || 0) * 100) + '%"></i></div><span class="note">' + esc(i.line) + "</span>" : "")
      + (!st.internet && !running ? '<span class="note">Turn the INTERNET switch on first - setting up downloads the note finder.</span>' : "")
      + "</div>" + (i.state === "error" ? '<p class="err">' + esc(i.error) + " Try again when the connection is back.</p>" : "") + "</div></div>";
    $("setup").onclick = function () {
      api("install").then(function (d) {
        if (!d.ok) return toast(d.msg);
        pollStatus();
      });
    };
    status(running ? "Setting up: " + (i.line || "") : "Not set up on this computer yet");
  }
  function pollStatus() {
    clearTimeout(st.poll);
    api("status").then(function (d) {
      if (!d.ok) return;
      st.installed = d.installed; st.install = d.install; st.internet = d.internet; st.tunings = d.tunings || [];
      if (!st.cur || !st.installed) drawView();
      drawNav();
      if (d.install && d.install.state === "running") st.poll = setTimeout(pollStatus, 1000);
      else if (st.installed) { toast("TabCrafter is ready - drop a recording to start."); loadList(); }
    });
  }

  /* ================= a new recording ================= */
  function pick() {
    if (!st.installed) return;
    if (st.mode === "split") { st.mode = null; history.replaceState(null, "", "#"); drawNav(); drawView(); }
    $("file").click();
  }
  $("file").onchange = function () { if (this.files[0]) add(this.files[0]); this.value = ""; };
  function add(file) {
    var m = /\.([a-z0-9]+)$/i.exec(file.name);
    var ext = m ? m[1].toLowerCase() : "";
    if (["wav", "mp3", "flac", "ogg"].indexOf(ext) < 0) return toast("TabCrafter reads .wav, .mp3, .flac and .ogg recordings.");
    if (file.size > 200 * 1048576) return toast("That recording is over 200 MB - trim it or save it as an .mp3 first.");
    status("Adding " + file.name + "…");
    var r = new FileReader();
    r.onload = function () {
      var data = String(r.result).split(",")[1] || "";
      api("create", { name: file.name.replace(/\.[^.]+$/, ""), ext: ext, data: data }).then(function (d) {
        if (!d.ok) { status("Couldn't add it"); return toast(d.msg); }
        loadList(d.id);
      });
    };
    r.onerror = function () { toast("That file couldn't be read."); };
    r.readAsDataURL(file);
  }
  document.addEventListener("dragover", function (e) { e.preventDefault(); var d = $("drop"); if (d) d.classList.add("over"); });
  document.addEventListener("dragleave", function (e) { var d = $("drop"); if (d && !e.relatedTarget) d.classList.remove("over"); });
  document.addEventListener("drop", function (e) {
    e.preventDefault();
    var d = $("drop"); if (d) d.classList.remove("over");
    var f = e.dataTransfer && e.dataTransfer.files[0];
    if (f && st.mode === "split") splitUpload(f);
    else if (f && st.installed) add(f);
  });

  /* ================= one recording ================= */
  function open(id) {
    flushSave();
    stop();
    st.cur = id; st.sel = null; st.undo = []; st.mode = null;
    history.replaceState(null, "", "#" + id);
    drawNav();
    $("view").innerHTML = '<div class="skel" style="width:40%"></div><div class="skel"></div><div class="skel" style="width:70%"></div>';
    api("get", { id: id }).then(function (d) {
      if (!d.ok) { st.cur = null; toast(d.msg); return loadList(); }
      st.item = d.item; st.tab = d.tab;
      st.orig = d.tab ? JSON.stringify(d.tab.items) : null;
      var m = d.item;
      st.settings = { strings: m.strings || 6, tuning: m.tuning || "standard", custom: "", bpm: m.bpm || "", time: m.time || [4, 4], steady: !!m.steady };
      if (!st.tunings.some(function (t) { return t.id === st.settings.tuning; })) { st.settings.custom = st.settings.tuning; st.settings.tuning = "custom"; }
      $("audio").src = "/api/guitartab/audio?id=" + encodeURIComponent(id);
      drawItem();
      if (m.job && m.job.state === "running") pollJob();
    });
  }

  function tuningNotes() {
    var s = st.settings;
    if (s.tuning !== "custom") { var t = st.tunings.find(function (x) { return x.id === s.tuning; }); return t ? t.notes : null; }
    return s.customNotes || null;
  }

  function drawItem() {
    var m = st.item, s = st.settings, job = m.job;
    var running = job && job.state === "running";
    var opts = st.tunings.filter(function (t) { return t.notes.length === +s.strings; })
      .map(function (t) { return '<option value="' + t.id + '"' + (t.id === s.tuning ? " selected" : "") + ">" + esc(t.label) + "</option>"; }).join("")
      + '<option value="custom"' + (s.tuning === "custom" ? " selected" : "") + ">Custom…</option>";
    var h = '<h1><input id="name" value="' + esc(m.name) + '" aria-label="Name" maxlength="80"><span class="spacer"></span>'
      + '<button class="btn danger" id="del" type="button">DELETE</button></h1>'
      + '<p class="lead">' + esc(m.file || "") + " · added " + esc(when(m.created)) + "</p>"
      + '<div class="card"><h2>Guitar and tempo</h2><div class="settings">'
      + '<label class="f2">Strings<select id="strings">' + [4, 5, 6, 7, 8, 9].map(function (n) { return '<option' + (n === +s.strings ? " selected" : "") + ">" + n + "</option>"; }).join("") + "</select></label>"
      + '<label class="f2">Tuning (low string first)<select id="tuning">' + opts + "</select></label>"
      + '<label class="f2"' + (s.tuning === "custom" ? "" : " hidden") + ' id="customwrap">Your tuning<input type="text" id="custom" placeholder="e.g. C G C F A D" value="' + esc(s.custom) + '"><span class="hint" id="customhint"></span></label>'
      + '<label class="f2">Tempo (BPM)<div class="bpm"><input type="number" id="bpm" min="30" max="300" step="0.1" value="' + esc(s.bpm) + '" placeholder="?">'
      + '<button class="btn tap" id="tap" type="button" title="Tap along to the recording (or press T)">TAP</button>'
      + '<button class="btn" id="listen" type="button" title="Let TabCrafter guess the tempo">GUESS</button></div><span class="hint" id="taphint">Tap along with the beat, or type it</span></label>'
      + '<label class="f2">Time<select id="time">' + TIMES.map(function (t) { var k = t.join("/"); return '<option' + (k === s.time.join("/") ? " selected" : "") + ">" + k + "</option>"; }).join("") + "</select></label>"
      + '<label class="check"><input type="checkbox" id="steady"' + (s.steady ? " checked" : "") + "> Played to a click (a steady tempo)</label>"
      + "</div>"
      + '<div class="go"><button class="btn primary" id="write" type="button"' + (running ? " disabled" : "") + ">" + (st.tab ? "WRITE THE TAB AGAIN" : "WRITE THE TAB") + "</button>"
      + (running ? '<div class="steps"><span class="' + (job.step === "notes" ? "now" : "done") + '">1 · finding the notes</span><span class="' + (job.step === "tab" ? "now" : "") + '">2 · writing the tab</span></div>'
                 : '<span class="note">' + (st.tab ? "A new tempo or tuning is quick: the notes are already found." : "The first time takes about a second for every few seconds of audio.") + "</span>")
      + "</div>" + (job && job.state === "error" ? '<p class="err">' + esc(job.error) + " Check the tempo and tuning, then write it again.</p>" : "") + "</div>";
    if (st.tab) {
      h += '<div class="player"><button class="btn" id="prec" type="button">▶ RECORDING</button><button class="btn" id="ptab" type="button">▶ TAB</button>'
        + '<button class="btn" id="pstop" type="button" disabled>■ STOP</button><span class="time" id="ptime">0:00</span>'
        + '<label class="speed">SPEED <input type="range" id="speed" min="50" max="100" step="5" value="' + Math.round(st.speed * 100) + '"><span id="speedv">' + Math.round(st.speed * 100) + '%</span></label>'
        + '<span class="spacer"></span><button class="btn" id="undo" type="button" disabled>UNDO</button><button class="btn" id="dl" type="button">DOWNLOAD .TXT</button></div>'
        + '<div class="card"><h2>Tab<span class="right"><span class="note" style="font:11px var(--mono);color:var(--faint)">Click a fret to change it · click a dash to add a note · bar numbers jump the player there</span></span></h2><div class="tab" id="tab"></div></div>';
    } else if (!running) {
      h += '<div class="card"><h2>Tab</h2><p class="lead" style="margin:0">Set the strings, tuning and tempo above, then press <b>Write the tab</b>. '
        + "If you don't know the tempo, play the recording in another player and tap along, or press <b>Guess</b>.</p></div>";
    }
    $("view").innerHTML = h;
    wireItem();
    if (st.tab) drawTab();
    status(running ? "Writing the tab…" : st.tab ? (m.edited ? "Edited · saved" : "Tab written " + when(m.written)) : "Ready to write the tab", running ? "" : "ok");
  }

  function wireItem() {
    var s = st.settings;
    $("name").onchange = function () { api("rename", { id: st.cur, name: this.value }).then(function () { loadList(); }); };
    $("del").onclick = function () {
      if (!confirm("Delete \"" + st.item.name + "\" and its tab?")) return;
      api("delete", { id: st.cur }).then(function (d) {
        if (!d.ok) return toast(d.msg);
        st.cur = null; st.tab = null; history.replaceState(null, "", location.pathname); loadList();
      });
    };
    $("strings").onchange = function () {
      s.strings = +this.value;
      var first = st.tunings.find(function (t) { return t.notes.length === s.strings; });
      s.tuning = first ? first.id : "custom";
      drawItem();
    };
    $("tuning").onchange = function () { s.tuning = this.value; drawItem(); if (s.tuning === "custom") $("custom").focus(); };
    var ci = $("custom");
    function parseCustom() {
      api("tuning", { text: ci.value }).then(function (d) {
        s.custom = ci.value; s.customNotes = d.ok ? d.notes : null;
        $("customhint").textContent = d.ok ? d.names.join(" ") + " - " + d.notes.length + " strings" : (ci.value ? "4 to 9 notes, low string first" : "");
        if (d.ok && d.notes.length !== +s.strings) { s.strings = d.notes.length; $("strings").value = String(s.strings); }
      });
    }
    ci.oninput = function () { clearTimeout(ci.t); ci.t = setTimeout(parseCustom, 250); };
    if (s.tuning === "custom" && ci.value) parseCustom();
    $("bpm").oninput = function () { s.bpm = this.value; };
    $("time").onchange = function () { s.time = this.value.split("/").map(Number); };
    $("steady").onchange = function () { s.steady = this.checked; };
    $("tap").onclick = tap;
    $("listen").onclick = function () {
      var b = this; b.disabled = true; b.textContent = "LISTENING…";
      api("estimate", { id: st.cur }).then(function (d) {
        b.disabled = false; b.textContent = "GUESS";
        if (!d.ok) return toast(d.msg);
        s.bpm = d.bpm; $("bpm").value = d.bpm;
        $("taphint").textContent = "Guessed " + d.bpm + " - if it feels twice too fast or slow, halve or double it";
      });
    };
    $("write").onclick = write;
    if (!st.tab) return;
    $("prec").onclick = function () { playRecording(); };
    $("ptab").onclick = function () { playTab(); };
    $("pstop").onclick = stop;
    $("speed").oninput = function () {
      st.speed = this.value / 100; $("speedv").textContent = this.value + "%";
      $("audio").playbackRate = st.speed;
      if (st.play && st.play.mode === "tab") { var from = st.play.tick(); stop(); playTab(from); }
    };
    $("undo").onclick = undo;
    $("dl").onclick = download;
  }

  /* ================= tempo ================= */
  var taps = [];
  function tap() {
    var now = performance.now();
    if (taps.length && now - taps[taps.length - 1] > 2000) taps = [];
    taps.push(now);
    taps = taps.slice(-9);
    var b = $("tap"); if (b) { b.classList.remove("hit"); void b.offsetWidth; b.classList.add("hit"); }
    var hint = $("taphint");
    if (taps.length < 2) { if (hint) hint.textContent = "Keep tapping…"; return; }
    var gaps = [];
    for (var i = 1; i < taps.length; i++) gaps.push(taps[i] - taps[i - 1]);
    var bpm = Math.round(600000 / (gaps.reduce(function (a, b) { return a + b; }, 0) / gaps.length)) / 10;
    st.settings.bpm = bpm;
    if ($("bpm")) $("bpm").value = bpm;
    if (hint) hint.textContent = taps.length < 5 ? "Keep tapping… " + bpm : bpm + " BPM from " + taps.length + " taps";
  }

  /* ================= writing the tab ================= */
  function write() {
    var s = st.settings;
    var notes = tuningNotes();
    if (!notes) return toast(s.tuning === "custom" ? "That tuning can't be read: give 4 to 9 notes, low string first." : "Pick a tuning first.");
    if (!(s.bpm >= 30 && s.bpm <= 300)) { $("bpm").focus(); return toast("Give the tempo first: type the BPM or tap along."); }
    if (st.item.edited && !confirm("Writing the tab again replaces your edits. Go ahead?")) return;
    var tuning = s.tuning === "custom" ? notes.map(noteName).join(" ") : s.tuning;
    api("transcribe", { id: st.cur, tuning: tuning, bpm: +s.bpm, time: s.time, steady: s.steady }).then(function (d) {
      if (!d.ok) return toast(d.msg);
      st.item = d.item; drawItem(); pollJob(); drawNav();
    });
  }
  function pollJob() {
    clearTimeout(st.poll);
    var id = st.cur;
    st.poll = setTimeout(function () {
      if (st.cur !== id) return;
      api("get", { id: id }).then(function (d) {
        if (st.cur !== id || !d.ok) return;
        var was = st.item.job && st.item.job.step;
        st.item = d.item;
        if (d.item.job && d.item.job.state === "running") {
          if (d.item.job.step !== was) drawItem();
          return pollJob();
        }
        st.tab = d.tab; st.orig = d.tab ? JSON.stringify(d.tab.items) : null; st.undo = [];
        drawItem(); loadList();
        if (d.item.job && d.item.job.state === "error") toast(d.item.job.error);
        else toast("The tab is written - play the recording to check it.");
      });
    }, 900);
  }

  /* ================= drawing the tab ================= */
  function labels(tuning) {
    var S = tuning.length, low = NAMES[tuning[0] % 12];
    return tuning.map(function (m, s) { var n = NAMES[m % 12]; return s === S - 1 && n === low ? n.toLowerCase() : n; });
  }
  function symText(it) { return it.kind === "note" ? it.sym : it.kind === "rest" ? "r" + it.sym : "~" + it.sym; }
  function colWidth(it) {
    var w = 0;
    (it.frets || []).forEach(function (sf) { w = Math.max(w, String(sf[1]).length); });
    return Math.max(w + 1, symText(it).length + 1, Math.floor(it.ticks * 2 / 3));
  }
  function bars(tab) {
    var out = [], bt = tab.bar_ticks;
    tab.items.forEach(function (it, i) {
      var b = Math.floor(it.tick / bt);
      while (out.length <= b) out.push([]);
      out[b].push(i);
    });
    return out;
  }
  function chWidth() {
    var s = document.createElement("span");
    s.style.cssText = "font:14px var(--mono);position:absolute;visibility:hidden;white-space:pre";
    s.textContent = "0000000000";
    document.body.appendChild(s);
    var w = s.getBoundingClientRect().width / 10;
    s.remove();
    return w || 8.4;
  }
  function drawTab() {
    var tab = st.tab, el = $("tab");
    if (!el) return;
    var S = tab.tuning.length, lab = labels(tab.tuning), lw = Math.max.apply(null, lab.map(function (l) { return l.length; }));
    var orig = st.orig ? JSON.parse(st.orig) : [];
    var avail = Math.max(40, Math.floor(el.clientWidth / chWidth()) - lw - 2);
    var rows = [], row = [], used = 0;
    bars(tab).forEach(function (ids, b) {
      var w = ids.reduce(function (a, i) { return a + colWidth(tab.items[i]); }, 0) + 2;
      if (row.length && used + w > avail) { rows.push(row); row = []; used = 0; }
      row.push({ b: b, ids: ids }); used += w;
    });
    if (row.length) rows.push(row);
    var h = "";
    rows.forEach(function (r) {
      h += '<div class="trow"><div class="names"><span class="num"> </span>';
      for (var s = S - 1; s >= 0; s--) h += "<span>" + esc(pad(lab[s], lw, " ", true)) + "|</span>";
      h += '<span class="rh"> </span></div>';
      r.forEach(function (bar) {
        h += '<div class="tbar"><span class="num"><button class="f" data-seek="' + bar.b + '" title="Play from bar ' + (bar.b + 1) + '">' + (bar.b + 1) + "</button></span>";
        for (var s1 = S - 1; s1 >= 0; s1--) h += "<span>-</span>";
        h += '<span class="rh"> </span></div>';
        bar.ids.forEach(function (i) {
          var it = tab.items[i], w = colWidth(it), o = orig[i];
          h += '<div class="col" data-i="' + i + '" style="width:' + w + 'ch"><span class="num"> </span>';
          for (var s2 = S - 1; s2 >= 0; s2--) {
            var sf = (it.frets || []).find(function (x) { return x[0] === s2; });
            if (sf) {
              var edited = !o || !(o.frets || []).some(function (x) { return x[0] === sf[0] && x[1] === sf[1]; });
              var sel = st.sel && st.sel.i === i && st.sel.s === s2;
              h += '<span><button class="f' + (edited ? " edited" : "") + (sel ? " sel" : "") + '" data-i="' + i + '" data-s="' + s2 + '">' + sf[1] + "</button>" + "-".repeat(Math.max(0, w - String(sf[1]).length)) + "</span>";
            } else h += '<span class="dash" data-i="' + i + '" data-s="' + s2 + '">' + "-".repeat(w) + "</span>";
          }
          h += '<span class="rh">' + esc(symText(it)) + "</span></div>";
        });
        h += '<div class="tbar"><span class="num"> </span>';
        for (var s3 = S - 1; s3 >= 0; s3--) h += "<span>|</span>";
        h += '<span class="rh"> </span></div>';
      });
      h += "</div>";
    });
    el.innerHTML = h;
    el.querySelectorAll("button.f[data-s]").forEach(function (b) { b.onclick = function (e) { e.stopPropagation(); editNote(b, +b.dataset.i, +b.dataset.s); }; });
    el.querySelectorAll(".dash").forEach(function (d) { d.onclick = function (e) { e.stopPropagation(); editNote(d, +d.dataset.i, +d.dataset.s); }; });
    el.querySelectorAll("button[data-seek]").forEach(function (b) { b.onclick = function () { seekBar(+b.dataset.seek); }; });
    if ($("undo")) $("undo").disabled = !st.undo.length;
  }
  function pad(s, n, c, left) { s = String(s); while (s.length < n) s = left ? c + s : s + c; return s; }
  var resizeT;
  window.addEventListener("resize", function () { clearTimeout(resizeT); resizeT = setTimeout(function () { if (st.tab) drawTab(); }, 150); });

  /* ================= fixing notes ================= */
  function closePop() { var p = document.querySelector(".pop"); if (p) p.remove(); if (st.sel) { st.sel = null; drawTab(); } }
  document.addEventListener("click", function (e) { var p = document.querySelector(".pop"); if (p && !p.contains(e.target)) closePop(); });
  function change(fn) {
    st.undo.push(JSON.stringify(st.tab.items));
    if (st.undo.length > 100) st.undo.shift();
    fn(st.tab.items);
    drawTab(); scheduleSave();
  }
  function undo() {
    if (!st.undo.length) return;
    st.tab.items = JSON.parse(st.undo.pop());
    closePop(); drawTab(); scheduleSave();
  }
  function editNote(anchor, i, s) {
    closePop();
    var tab = st.tab, it = tab.items[i], tun = tab.tuning;
    if (it.kind === "tie") return toast("That beat holds the note before it - change the note where it starts.");
    var sf = (it.frets || []).find(function (x) { return x[0] === s; });
    var lab = labels(tun);
    var p = document.createElement("div");
    p.className = "pop";
    var h;
    if (sf) {
      var midi = tun[s] + sf[1];
      st.sel = { i: i, s: s }; drawTab();
      var taken = (it.frets || []).map(function (x) { return x[0]; });
      var alts = tun.map(function (o, s2) { return { s: s2, f: midi - o }; })
        .filter(function (a) { return a.s !== s && a.f >= 0 && a.f <= 24 && taken.indexOf(a.s) < 0; });
      h = "<h3>" + esc(lab[s]) + " string, fret " + sf[1] + ' · <span class="name">' + noteName(midi) + "</span></h3>"
        + (alts.length ? '<div class="alts">' + alts.map(function (a) { return '<button class="btn" data-alt="' + a.s + "," + a.f + '" type="button">' + esc(lab[a.s]) + " " + a.f + "</button>"; }).join("") + "</div>"
                        : '<p class="lead" style="margin-bottom:10px;font-size:12px">This note has no other place on the neck here.</p>')
        + '<div class="row">Fret <input type="number" id="pf" min="0" max="24" value="' + sf[1] + '"><button class="btn" id="pset" type="button">SET</button></div>'
        + '<div class="row"><button class="btn danger" id="pdel" type="button">DELETE NOTE</button></div>';
    } else {
      h = "<h3>Add a note on the " + esc(lab[s]) + " string</h3>"
        + '<div class="row">Fret <input type="number" id="pf" min="0" max="24" value="0"><button class="btn primary" id="pset" type="button">ADD</button></div>';
    }
    p.innerHTML = h;
    document.body.appendChild(p);
    var r = anchor.getBoundingClientRect();
    p.style.left = Math.min(window.innerWidth - 276, r.left) + "px";
    p.style.top = (r.bottom + 6 + 200 > window.innerHeight ? Math.max(8, r.top - p.offsetHeight - 6) : r.bottom + 6) + "px";
    p.addEventListener("click", function (e) { e.stopPropagation(); });
    p.querySelectorAll("[data-alt]").forEach(function (b) {
      b.onclick = function () {
        var a = b.dataset.alt.split(",").map(Number);
        change(function (items) { var x = items[i].frets.find(function (q) { return q[0] === s; }); x[0] = a[0]; x[1] = a[1]; });
        closePop();
      };
    });
    var pf = $("pf");
    pf.focus(); pf.select();
    function set() {
      var f = Math.round(+pf.value);
      if (!(f >= 0 && f <= 24)) return toast("A fret from 0 to 24.");
      change(function (items) {
        var cur = items[i];
        if (cur.kind === "rest") { cur.kind = "note"; cur.sym = cur.sym; }
        cur.frets = cur.frets || [];
        var x = cur.frets.find(function (q) { return q[0] === s; });
        if (x) x[1] = f; else cur.frets.push([s, f]);
      });
      closePop();
    }
    $("pset").onclick = set;
    pf.onkeydown = function (e) { if (e.key === "Enter") set(); if (e.key === "Escape") closePop(); };
    if ($("pdel")) $("pdel").onclick = function () {
      change(function (items) {
        var cur = items[i];
        cur.frets = cur.frets.filter(function (q) { return q[0] !== s; });
        if (!cur.frets.length) cur.kind = "rest";
      });
      closePop();
    };
  }
  function scheduleSave() {
    clearTimeout(st.saveT);
    status("Saving…");
    st.saveT = setTimeout(save, 700);
  }
  function save() {
    st.saveT = null;
    if (!st.tab || !st.cur) return;
    var id = st.cur;
    return api("save", { id: id, items: st.tab.items }).then(function (d) {
      if (!d.ok) { status("Not saved: " + (d.msg || "")); return toast(d.msg || "That edit couldn't be saved."); }
      if (st.cur === id) { st.item.edited = true; status("Edited · saved", "ok"); }
      var li = st.items.find(function (x) { return x.id === id; }); if (li && !li.edited) { li.edited = true; drawNav(); }
    });
  }
  function flushSave() { if (st.saveT) { clearTimeout(st.saveT); save(); } }
  window.addEventListener("beforeunload", flushSave);

  /* ================= playing ================= */
  function posFromTime(t) {           // seconds in the recording -> beats from bar 1
    var b = st.tab.beat_times, n = b.length;
    if (n < 2) return 0;
    if (t <= b[0]) return (t - b[0]) / (b[1] - b[0]);
    if (t >= b[n - 1]) return n - 1 + (t - b[n - 1]) / (b[n - 1] - b[n - 2]);
    var lo = 0, hi = n - 1;
    while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (b[mid] <= t) lo = mid; else hi = mid; }
    return lo + (t - b[lo]) / (b[hi] - b[lo]);
  }
  function timeFromPos(p) {
    var b = st.tab.beat_times, n = b.length;
    if (p <= 0) return b[0] + p * (b[1] - b[0]);
    if (p >= n - 1) return b[n - 1] + (p - n + 1) * (b[n - 1] - b[n - 2]);
    var k = Math.floor(p);
    return b[k] + (p - k) * (b[k + 1] - b[k]);
  }
  function itemAt(tick) {
    var items = st.tab.items, lo = 0, hi = items.length - 1, best = -1;
    while (lo <= hi) { var mid = (lo + hi) >> 1; if (items[mid].tick <= tick) { best = mid; lo = mid + 1; } else hi = mid - 1; }
    return best;
  }
  var lastCol = null;
  function mark(tick) {
    var i = itemAt(tick);
    var col = i >= 0 ? document.querySelector('.col[data-i="' + i + '"]') : null;
    if (col === lastCol) return;
    if (lastCol) lastCol.classList.remove("now");
    lastCol = col;
    if (!col) return;
    col.classList.add("now");
    var v = $("view"), r = col.getBoundingClientRect(), vr = v.getBoundingClientRect();
    if (r.bottom > vr.bottom - 20 || r.top < vr.top + 70) v.scrollTo({ top: v.scrollTop + r.top - vr.top - 140, behavior: "smooth" });
  }
  function clock(sec) { sec = Math.max(0, sec); return Math.floor(sec / 60) + ":" + pad(Math.floor(sec % 60), 2, "0", true); }
  function buttons(mode) {
    if (!$("prec")) return;
    $("prec").classList.toggle("on", mode === "rec"); $("ptab").classList.toggle("on", mode === "tab");
    $("prec").textContent = mode === "rec" ? "❚❚ RECORDING" : "▶ RECORDING";
    $("ptab").textContent = mode === "tab" ? "❚❚ TAB" : "▶ TAB";
    $("pstop").disabled = !mode;
  }
  function stop() {
    var p = st.play;
    st.play = null;
    if (p) { clearTimeout(p.raf); if (p.mode === "rec") $("audio").pause(); if (p.ctx) p.ctx.close(); }
    if (lastCol) { lastCol.classList.remove("now"); lastCol = null; }
    buttons(null);
  }
  function playRecording(fromSec) {
    if (st.play && st.play.mode === "rec" && fromSec == null) { stop(); return; }
    stop();
    var a = $("audio");
    if (fromSec != null) a.currentTime = Math.max(0, fromSec);
    a.playbackRate = st.speed;
    a.play().catch(function () { toast("The recording couldn't play."); stop(); });
    var p = st.play = { mode: "rec" };
    p.tick = function () { return posFromTime(a.currentTime) * st.tab.tpb; };
    (function loop() {
      if (st.play !== p) return;
      mark(p.tick());
      $("ptime").textContent = clock(a.currentTime) + " / " + clock(a.duration || 0);
      if (a.ended) return stop();
      p.raf = setTimeout(loop, 33);
    })();
    buttons("rec");
  }
  function pluck(ctx, midi, dur, seed) {
    var sr = ctx.sampleRate, f = 440 * Math.pow(2, (midi - 69) / 12), n = Math.floor(Math.min(dur, 4) * sr) + 1;
    var buf = ctx.createBuffer(1, n, sr), out = buf.getChannelData(0);
    var period = sr / f, p = Math.max(2, Math.floor(period)), frac = period - p;
    var ring = new Float32Array(p), x = seed * 9301 + 49297;
    for (var i = 0; i < p; i++) { x = (x * 9301 + 49297) % 233280; ring[i] = x / 116640 - 1; }
    for (var k = 0; k < 2; k++) for (i = 0; i < p; i++) ring[i] = 0.5 * (ring[i] + ring[(i + 1) % p]);
    var decay = midi < 52 ? 0.996 : 0.994, idx = 0, prev = 0;
    for (i = 0; i < n; i++) {
      var j = idx % p, v = ring[j];
      var nv = decay * (0.5 * (v + ring[(idx + 1) % p]));
      ring[j] = nv * (1 - frac) + prev * frac;           // a fractional delay keeps it in tune
      prev = nv;
      out[i] = v * Math.min(1, i / (0.002 * sr)) * (i > n - sr * 0.03 ? (n - i) / (sr * 0.03) : 1);
      idx++;
    }
    return buf;
  }
  function playTab(fromTick) {
    if (st.play && st.play.mode === "tab" && fromTick == null) { stop(); return; }
    stop();
    var tab = st.tab, items = tab.items;
    var AC = window.AudioContext || window.webkitAudioContext;
    var ctx = new AC();
    var spt = 60 / (tab.bpm * tab.tpb) / st.speed;              // seconds a tick
    var start = fromTick || 0, t0 = ctx.currentTime + 0.15;
    var master = ctx.createGain(); master.gain.value = 0.35; master.connect(ctx.destination);
    var cache = {}, end = 0;
    items.forEach(function (it, i) {
      if (it.kind !== "note" || it.tick < start) return;
      var ticks = it.ticks;
      for (var k = i + 1; k < items.length && items[k].kind === "tie"; k++) ticks += items[k].ticks;
      var dur = Math.max(0.15, ticks * spt);
      it.frets.forEach(function (sf, n) {
        var midi = tab.tuning[sf[0]] + sf[1], key = midi + ":" + Math.round(dur * 4);
        if (!cache[key]) cache[key] = pluck(ctx, midi, Math.round(dur * 4) / 4 + 0.05, midi + n);
        var src = ctx.createBufferSource(); src.buffer = cache[key]; src.connect(master);
        src.start(t0 + (it.tick - start) * spt);
      });
      end = Math.max(end, (it.tick - start + ticks) * spt);
    });
    var p = st.play = { mode: "tab", ctx: ctx };
    p.tick = function () { return start + (ctx.currentTime - t0) / spt; };
    (function loop() {
      if (st.play !== p) return;
      var el = ctx.currentTime - t0;
      mark(p.tick());
      $("ptime").textContent = clock(start * spt * st.speed + el * st.speed) + " (tab)";
      if (el > end + 0.5) return stop();
      p.raf = setTimeout(loop, 33);
    })();
    buttons("tab");
  }
  function seekBar(b) {
    var tick = b * st.tab.bar_ticks;
    if (st.play && st.play.mode === "tab") playTab(tick);
    else playRecording(timeFromPos(tick / st.tab.tpb) - 0.05);
  }
  document.addEventListener("keydown", function (e) {
    var tag = (e.target.tagName || "").toLowerCase();
    var typing = tag === "input" || tag === "select" || tag === "textarea";
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !typing && st.tab) { e.preventDefault(); undo(); return; }
    if (typing) return;
    if (e.key === " " && st.tab) { e.preventDefault(); if (st.play) stop(); else playRecording(); }
    else if (e.key.toLowerCase() === "t" && st.cur) tap();
    else if (e.key === "Escape") closePop();
  });

  /* ================= the Audio File Splitter ================= */
  // A long file (an audiobook) cut into parts without re-encoding: Browse reads it where it is and
  // puts the parts beside it; a dropped file is copied to Philibert first (the browser can't say where
  // it lives), so its parts go to Downloads unless another folder is chosen. The original is only read.
  function openSplit() {
    flushSave(); stop(); closePop();
    st.cur = null; st.item = null; st.tab = null; st.mode = "split";
    if (!st.split) st.split = { file: null, by: "max", parts: 4, minutes: 60, folder: "", preview: null, job: null, busy: "" };
    history.replaceState(null, "", "#split");
    drawNav(); drawSplit();
  }
  function size(b) { return b >= 1073741824 ? (b / 1073741824).toFixed(2) + " GB" : (b / 1048576).toFixed(1) + " MB"; }
  function fact(k, v) { return "<div><small>" + k + "</small><b>" + esc(v) + "</b></div>"; }
  function clockS(sec) { sec = Math.round(sec); return Math.floor(sec / 3600) + ":" + pad(Math.floor(sec / 60) % 60, 2, "0", true) + ":" + pad(sec % 60, 2, "0", true); }
  function drawSplit() {
    var S = st.split, f = S.file, j = S.job, v = $("view"), pv = S.preview;
    var h = '<h1>Audio File Splitter</h1><p class="lead">Cut a long audiobook or podcast into smaller files, so they are easier to queue up '
      + "on a playlist and to keep your place in. The parts are exact copies of the audio - nothing is re-encoded - and they keep the "
      + "book's tags and cover. Your original file is never changed.</p>";
    if (j && j.state === "running") {
      h += '<div class="card"><h2>Splitting ' + esc(j.name || "") + '</h2><div class="go"><div class="bar"><i style="width:' + Math.round((j.progress || 0) * 100)
        + '%"></i></div><span class="note">Part ' + (j.part || 1) + " of " + j.total + "</span></div></div>";
    } else if (j && j.state === "done") {
      h += '<div class="card"><h2>Done: ' + j.files.length + ' parts <span class="right"><button class="btn primary" id="spShow" type="button">SHOW IN FOLDER</button>'
        + '<button class="btn" id="spAgain" type="button">SPLIT ANOTHER</button></span></h2><p class="spfolder">' + esc(j.folder) + '</p><ol class="parts">'
        + j.files.map(function (p) { return "<li><b>" + esc(p.name) + "</b><span>" + esc(p.length) + "</span></li>"; }).join("") + "</ol>"
        + '<p class="note" style="margin-top:10px">' + esc(j.name) + " is still there, untouched.</p></div>";
    } else if (!f) {
      h += '<div class="drop" id="spDrop" tabindex="0" role="button" aria-label="Choose an audio file to split">'
        + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.12 15.88M14.47 14.48 20 20M8.12 8.12 12 12"/></svg>'
        + "<b>" + (S.busy ? esc(S.busy) : "Drop a long audio file here") + "</b><span>" + (S.busy ? "" : "or click to browse - .mp3, .m4b, .m4a, .flac, .ogg, .opus, .wav")
        + "</span></div>";
      if (j && j.state === "error") h += '<p class="err">' + esc(j.error) + "</p>";
    } else {
      h += '<div class="card"><h2>The file <span class="right"><button class="btn" id="spOther" type="button">CHOOSE ANOTHER</button></span></h2><div class="facts">'
        + fact("File", f.name) + fact("Length", f.length) + fact("Size", size(f.size))
        + fact("Format", f.codec.toUpperCase() + (f.kbps ? " · " + f.kbps + " kbps" : "") + (f.channels ? " · " + (f.channels === 1 ? "mono" : "stereo") : ""))
        + (f.title ? fact("Title", f.title) : "") + (f.artist ? fact("Author", f.artist) : "") + fact("Cover", f.cover ? "yes - copied to every part" : "none")
        + (f.dropped ? "" : fact("Where", f.folder)) + "</div></div>"
        + '<div class="card"><h2>How to cut it</h2><div class="settings">'
        + '<label class="f2">Cut by<select id="spBy"><option value="max"' + (S.by === "max" ? " selected" : "") + ">Longest a part may be</option>"
        + '<option value="parts"' + (S.by === "parts" ? " selected" : "") + ">Number of parts</option></select></label>"
        + (S.by === "parts"
          ? '<label class="f2">Parts<input type="number" id="spParts" min="2" max="500" value="' + S.parts + '"><span class="hint">each about ' + clockS(f.duration / Math.max(1, S.parts)) + "</span></label>"
          : '<label class="f2">Minutes per part, at most<input type="number" id="spMin" min="1" max="1440" value="' + S.minutes + '">'
            + '<span class="hint"><a href="#" data-m="30">30 min</a> · <a href="#" data-m="60">1 h</a> · <a href="#" data-m="120">2 h</a> · <a href="#" data-m="180">3 h</a></span></label>')
        + '</div><p class="note" style="margin-top:12px">The parts are all the same length' + (S.by === "max" ? ": as few as fit under that limit" : "") + ".</p></div>"
        + '<div class="card"><h2>The parts <span class="right"><button class="btn" id="spFolder" type="button">CHANGE FOLDER</button></span></h2>'
        + '<p class="spfolder">Saved in ' + esc(pv && pv.folder ? pv.folder : (S.folder || f.folder)) + "</p>"
        + (pv && pv.ok
          ? '<ol class="parts">' + pv.parts.map(function (p) {
              return "<li><b>" + esc(p.name) + "</b><span>" + p.start + " – " + p.end + (p.exists ? " <em>already there</em>" : "") + "</span></li>"; }).join("") + "</ol>"
          : '<p class="err">' + esc(pv ? pv.msg : "") + "</p>")
        + '<div class="go"><button class="btn primary" id="spGo" type="button"' + (pv && pv.ok ? "" : " disabled") + ">SPLIT INTO "
        + (pv && pv.ok ? pv.parts.length + " PARTS" : "PARTS") + "</button>"
        + (j && j.state === "error" ? '<span class="err" style="margin:0">' + esc(j.error) + "</span>" : "") + "</div></div>";
    }
    v.innerHTML = h;
    var d = $("spDrop");
    if (d) { d.onclick = splitBrowse; d.onkeydown = function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); splitBrowse(); } }; }
    if ($("spOther")) $("spOther").onclick = function () { S.file = null; S.preview = null; S.job = null; splitBrowse(); };
    if ($("spAgain")) $("spAgain").onclick = function () { S.file = null; S.preview = null; S.job = null; drawSplit(); };
    if ($("spShow")) $("spShow").onclick = function () { api("split_show", { folder: j.folder }).then(function (r) { if (!r.ok) toast(r.msg); }); };
    if ($("spBy")) $("spBy").onchange = function () { S.by = this.value; splitPreview(); };
    if ($("spParts")) $("spParts").oninput = function () { S.parts = Math.max(2, Math.min(500, parseInt(this.value, 10) || 2)); splitPreview(true); };
    if ($("spMin")) $("spMin").oninput = function () { S.minutes = Math.max(1, parseFloat(this.value) || 1); splitPreview(true); };
    v.querySelectorAll("a[data-m]").forEach(function (a) { a.onclick = function (e) { e.preventDefault(); S.minutes = +a.dataset.m; splitPreview(); }; });
    if ($("spFolder")) $("spFolder").onclick = function () {
      api("split_pick_folder", { start: pv && pv.folder ? pv.folder : "" }).then(function (r) { if (r.ok) { S.folder = r.path; splitPreview(); } });
    };
    if ($("spGo")) $("spGo").onclick = function () { splitStart(false); };
    status(j && j.state === "running" ? "Splitting…" : f ? f.name + " · " + f.length : "Audio File Splitter", "ok");
  }
  function cutArgs() {
    var S = st.split;
    return { path: S.file.path, out_dir: S.folder || "", parts: S.by === "parts" ? S.parts : null, max_minutes: S.by === "max" ? S.minutes : null };
  }
  function splitPreview(typing) {
    var S = st.split;
    clearTimeout(S.pt);
    S.pt = setTimeout(function () {
      api("split_preview", cutArgs()).then(function (r) {
        S.preview = r;
        if (st.mode !== "split" || !S.file) return;
        var el = typing && document.activeElement, id = el && el.id, pos = el && el.value.length;   // keep the box being typed in
        drawSplit();
        if (id && $(id)) { $(id).focus(); try { $(id).setSelectionRange(pos, pos); } catch (e) { /* number boxes have no caret */ } }
      });
    }, typing ? 300 : 0);
  }
  function splitChosen(r) {
    var S = st.split;
    S.busy = "";
    if (!r.ok) { drawSplit(); if (!r.cancelled) toast(r.msg); return; }
    S.file = r; S.job = null; S.folder = ""; S.preview = null;
    if (S.by === "max" && r.duration < S.minutes * 60 * 2) S.by = "parts";      // under two parts' worth: count them instead
    splitPreview();
  }
  function splitBrowse() {
    var S = st.split;
    if (S.busy) return;
    S.busy = "Choose the file in the window that opened…"; drawSplit();
    api("split_pick").then(splitChosen);
  }
  function splitUpload(file) {
    var S = st.split, PIECE = 6 * 1048576, i = 0, token = "";
    if (S.busy || (S.job && S.job.state === "running")) return;
    S.file = null; S.job = null; S.preview = null;
    function next() {
      S.busy = "Reading " + file.name + "… " + Math.round(100 * Math.min(1, i * PIECE / Math.max(1, file.size))) + "%";
      drawSplit();
      var r = new FileReader();
      r.onload = function () {
        api("split_upload", { name: file.name, size: file.size, i: i, token: token, data: String(r.result).split(",")[1] || "" }).then(function (d) {
          if (!d.ok) return splitChosen(d);
          token = d.token; i++;
          if (d.path) return splitChosen(d);
          next();
        });
      };
      r.onerror = function () { splitChosen({ ok: false, msg: "That file couldn't be read." }); };
      r.readAsDataURL(file.slice(i * PIECE, (i + 1) * PIECE));
    }
    next();
  }
  function splitStart(replace) {
    var S = st.split;
    api("split_start", Object.assign(cutArgs(), { replace: replace })).then(function (r) {
      if (!r.ok && r.exists) {
        if (confirm(r.msg + "\n\nReplace them with the new parts? Your original file is not touched.")) splitStart(true);
        return;
      }
      if (!r.ok) return toast(r.msg);
      S.job = { state: "running", progress: 0, part: 1, total: r.total, name: S.file.name };
      drawSplit(); splitPoll();
    });
  }
  function splitPoll() {
    api("split_status").then(function (j) {
      var S = st.split;
      if (!j.ok) return;
      S.job = j;
      if (st.mode === "split") drawSplit();
      if (j.state === "running") setTimeout(splitPoll, 400);
      else if (j.state === "done") toast("Split into " + j.files.length + " parts.");
    });
  }

  /* ================= the text file ================= */
  function tabText() {
    var tab = st.tab, S = tab.tuning.length, lab = labels(tab.tuning), lw = Math.max.apply(null, lab.map(function (l) { return l.length; }));
    var out = [st.item.name, "Tuning: " + tab.tuning.map(noteName).join(" ") + " (" + S + " strings)   Tempo: " + tab.bpm + " BPM   Time: " + tab.time.join("/"), ""];
    var rows = [], row = [], used = 0;
    bars(tab).forEach(function (ids, b) {
      var w = ids.reduce(function (a, i) { return a + colWidth(tab.items[i]); }, 0) + 2;
      if (row.length && used + w > 108 - lw) { rows.push(row); row = []; used = 0; }
      row.push({ b: b, ids: ids }); used += w;
    });
    if (row.length) rows.push(row);
    rows.forEach(function (r) {
      var num = pad("", lw + 1, " "), lines = [], rh = pad("", lw + 1, " ");
      for (var s = S - 1; s >= 0; s--) lines.push(pad(lab[s], lw, " ", true) + "|");
      r.forEach(function (bar) {
        var bw = bar.ids.reduce(function (a, i) { return a + colWidth(tab.items[i]); }, 0) + 2;
        num += pad(String(bar.b + 1), bw, " ");
        rh += " ";
        lines = lines.map(function (l) { return l + "-"; });
        bar.ids.forEach(function (i) {
          var it = tab.items[i], w = colWidth(it);
          lines = lines.map(function (l, k) {
            var sf = (it.frets || []).find(function (x) { return x[0] === S - 1 - k; });
            return l + pad(sf ? String(sf[1]) : "", w, "-");
          });
          rh += pad(symText(it), w, " ");
        });
        lines = lines.map(function (l) { return l + "|"; });
        rh += " ";
      });
      out.push(num.replace(/\s+$/, ""));
      out = out.concat(lines);
      out.push(rh.replace(/\s+$/, ""), "");
    });
    out.push("Rhythm: w whole, h half, q quarter, e 8th, s 16th, t 32nd; . dotted; 3 triplet; r rest; ~ held over.");
    out.push("Written with Philibert TabCrafter.");
    return out.join("\r\n") + "\r\n";
  }
  function download() {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([tabText()], { type: "text/plain" }));
    a.download = (st.item.name || "tab").replace(/[\\/:*?"<>|]+/g, "_") + ".tab.txt";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }

  /* ================= start ================= */
  $("new").onclick = pick;
  $("split").onclick = openSplit;
  api("status").then(function (d) {
    if (!d.ok) { status("Couldn't reach Philibert"); $("view").innerHTML = '<p class="err">TabCrafter couldn\'t reach Philibert (' + esc(d.msg) + "). Close this window and open it again.</p>"; return; }
    st.installed = d.installed; st.install = d.install; st.internet = d.internet; st.tunings = d.tunings || [];
    if (d.install && d.install.state === "running") pollStatus();
    var hash = location.hash.slice(1);                 // guitartab#<id> opens that one
    if (hash === "split") { loadList(); openSplit(); }
    else loadList(/^[a-f0-9]{12}$/.test(hash) ? hash : null);
  });
})();
