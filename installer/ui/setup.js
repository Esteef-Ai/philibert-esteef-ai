/* Philibert Setup - the wizard.
 *
 * Talks to installer/app.py through pywebview's js_api. Opened in a plain
 * browser (no pywebview), it uses a stand-in API with sample data so every
 * page can be looked at and checked without installing anything.
 */
(function () {
  "use strict";

  var THEMES = [
    { id: "win311", name: "Windows 3.11" }, { id: "win95", name: "Windows 95", locked: true },
    { id: "winxp", name: "Windows XP" }, { id: "win11", name: "Windows 11" },
    { id: "os8", name: "Mac OS 8" }, { id: "os9", name: "Mac OS 9.2" }, { id: "macos", name: "macOS" },
    { id: "ios", name: "iOS" }, { id: "android", name: "Android" }, { id: "c64", name: "Commodore 64" }
  ];
  var SIZE = { theme: 6, sounds: 3, wallpapers: 18, retro: 150, imagegen: 13000 };     // MB, for the totals
  var PC_GB = { windows: 2.5, mac: 0.8 };

  var state = {
    page: 0, info: null, places: [], catalog: [], pcs: "both", edition: "slim",
    themes: {}, retro: true, imagegen: false, igrating: null, dest: "", place: null, verdict: null, speed: null,
    models: {}, checklist: [], checks: {}, installing: false, result: null
  };
  THEMES.forEach(function (t) { state.themes[t.id] = { on: true, sounds: true, wallpapers: true }; });

  /* ---------- the API (pywebview, or a stand-in in a browser) ---------- */
  var mock = {
    survey: function () {
      // made-up example hardware for previewing the wizard in a browser
      return { os: "windows", arch: "amd64", cpu: "Example 8-Core Processor", ram_gb: 32,
               gpus: [{ name: "Example GeForce RTX (16 GB)", vram_gb: 16 }],
               fast_gb: 16, fast_kind: "Example GeForce RTX (16 GB)" };
    },
    places: function () {
      return [
        { path: "D:\\", label: "Philibert", fs: "exFAT", free_gb: 896.4, total_gb: 931.5, bus: "USB", external: true, system: false },
        { path: "E:\\", label: "Backup", fs: "NTFS", free_gb: 1790.1, total_gb: 1863.0, bus: "USB", external: true, system: false },
        { path: "C:\\", label: "", fs: "NTFS", free_gb: 373.0, total_gb: 931.5, bus: "NVMe", external: false, system: true }];
    },
    catalog: function () {
      function m(tag, label, size, need, rating, why, extra) {
        return Object.assign({ tag: tag, label: label, size_gb: size, need_gb: need, rating: rating, why: why, note: "" }, extra || {});
      }
      return [
        m("qwen3.5:4b", "Qwen3.5 4B", 3.3, 4.0, "green", "Runs fully on the graphics card - fast.", { auto: true, note: "Fast on any computer." }),
        m("qwen3:8b", "Qwen3 8B", 5.2, 5.9, "green", "Runs fully on the graphics card - fast.", { auto: true, note: "The everyday tier." }),
        m("qwen3:14b", "Qwen3 14B", 9.3, 10.1, "green", "Runs fully on the graphics card - fast.", { auto: true, note: "Sharper answers." }),
        m("hf.co/x/27b", "Qwen3.8 27B", 13.7, 14.6, "green", "Runs fully on the graphics card - fast.", { note: "The strongest for a 16 GB card." }),
        m("hf.co/x/27b-def", "Qwen3.8 27B Defiance", 15.7, 16.6, "yellow", "Fits with a little on the processor - works, somewhat slower."),
        m("hf.co/x/27b-q6", "Qwen3.8 27B Defiance Q6", 25.9, 27.0, "yellow", "Fits with much of it on the processor - works, but slowly."),
        m("qwen2.5vl:7b", "Qwen2.5-VL 7B (vision)", 6.0, 6.7, "green", "Runs fully on the graphics card - fast.", { required: true, locked: true, note: "Reads pictures." }),
        m("nomic-embed-text", "nomic-embed-text", 0.3, 0.9, "green", "Runs fully on the graphics card - fast.", { required: true, locked: true, kind: "embed", note: "Searches your notes." })];
    },
    default_model: function () { return "qwen3:14b"; },
    imagegen_rating: function () { return { rating: "green", backend: "cu130", why: "NVIDIA card with 16 GB: about 10-30 seconds a picture." }; },
    check_place: function (path, pcs) {
      var p = mock.places().filter(function (x) { return path.indexOf(x.path) === 0; })[0] || mock.places()[0];
      var ntfsMac = p.fs === "NTFS" && pcs.indexOf("mac") >= 0;
      return { fs: p.fs, free_gb: p.free_gb, external: p.external, system: p.system,
               verdict: ntfsMac ? { ok: false, message: "Windows only: a Mac can read NTFS but cannot save to it. Back up the drive and reformat it as exFAT, or choose Windows only." }
                                : { ok: true, message: p.fs === "exFAT" ? "Works on both Windows and Mac." : "Works on Windows." },
               speed: p.external ? { write_mbs: 29.1, read_mbs: 36.5 } : { write_mbs: 570.6, read_mbs: 1009.8 } };
    },
    choose_folder: function () { return "D:\\Music\\Philibert"; },
    checklist: function () {
      return [
        { id: "gpu", title: "Graphics driver", detail: "Example GeForce RTX - its driver is installed. Nothing to do.", kind: "info" },
        { id: "shortcut", title: "A Philibert shortcut on this computer's desktop", detail: "Optional. The only thing Setup would put on this computer.", kind: "optional", value: false }];
    },
    start_install: function (plan) { mock._t0 = Date.now(); mock._plan = plan; return true; },
    progress: function () {
      var t = (Date.now() - mock._t0) / 1000, steps = ["Copying Philibert onto the drive", "Setting up Philibert for this computer",
        "Getting what the other computers need", "Making room for your notes", "Getting the AI models and voices", "Finishing"];
      var step = Math.min(5, Math.floor(t / 2)), pct = (t % 2) / 2;
      return { steps: steps.map(function (s) { return { title: s }; }), step: step, step_pct: step === 1 ? -1 : pct,
               overall: Math.min(1, t / 12), detail: step === 4 ? "Model 1 of 3: qwen3:14b - 3.1 of 9.3 GB" : "Ollama - 412 of 1,402 MB  (17.5 MB/s)",
               done: t > 12, error: "", warnings: [] };
    },
    github_status: function () { return { needed: /[?&]signin=1/.test(location.search), device: true, signed_in: false }; },
    github_start: function () { return { ok: true, user_code: "WDJB-MJHT", uri: "https://github.com/login/device", interval: 1 }; },
    github_poll: function () { return { state: "ok", user: "tester" }; },
    github_token: function () { return { state: "ok", user: "tester" }; },
    cancel: function () { return true; },
    open_philibert: function () { return true; },
    close: function () { return true; }
  };
  function api(name) {
    var args = Array.prototype.slice.call(arguments, 1);
    if (window.pywebview && window.pywebview.api && window.pywebview.api[name]) return window.pywebview.api[name].apply(null, args);
    return Promise.resolve(mock[name].apply(null, args));
  }

  /* ---------- pages ---------- */
  var pages = Array.prototype.slice.call(document.querySelectorAll("section.page"));
  var rail = document.getElementById("rail");
  var nextBtn = document.getElementById("next"), backBtn = document.getElementById("back"), msg = document.getElementById("msg");
  var $ = function (id) { return document.getElementById(id); };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function pcsList() { return state.pcs === "both" ? ["windows", "mac"] : [state.pcs]; }
  function gb(x) { return x >= 10 ? Math.round(x) + " GB" : (Math.round(x * 10) / 10) + " GB"; }

  rail.innerHTML = pages.map(function (p, i) {
    return '<li data-i="' + i + '"><span class="n">' + (i + 1) + "</span>" + esc(p.getAttribute("data-title")) + "</li>";
  }).join("");

  function show(i) {
    state.page = i;
    pages.forEach(function (p, k) { p.classList.toggle("on", k === i); });
    Array.prototype.forEach.call(rail.children, function (li, k) {
      li.className = k < i ? "done" : (k === i ? "on" : "");
    });
    backBtn.classList.toggle("hide", i === 0 || i === 9);
    backBtn.textContent = i === 8 ? "Cancel" : "Back";
    nextBtn.textContent = i === 7 ? "Install" : (i === 9 ? "Open Philibert" : "Next");
    nextBtn.classList.toggle("hide", i === 8);
    msg.textContent = "";
    var enter = ENTER[i]; if (enter) enter();
    validate();
    $("main").scrollTop = 0;
  }

  /* ---------- signing in (only when this Philibert's repository is private) ---------- */
  var gh = { needed: false, ok: false, polling: null };
  function ghDone(user) {
    gh.ok = true;
    clearTimeout(gh.polling);
    $("signin").classList.add("ok");
    $("gh-device").classList.add("hide"); $("gh-tokenbox").classList.add("hide");
    $("gh-msg").innerHTML = '<span class="good">Signed in as ' + esc(user || "you") + ".</span> You can go on.";
    validate();
  }
  api("github_status").then(function (s) {
    gh.needed = !!(s && s.needed);
    if (!gh.needed) return;
    $("signin").classList.remove("hide");
    if (!s.device) {                      // no OAuth app set up yet: the token box is the way in
      $("gh-device").classList.add("hide");
      $("gh-tokenbox").open = true;
    }
    if (s.offline) $("gh-msg").innerHTML = '<span class="warn">Setup cannot reach GitHub. Check the Internet connection.</span>';
    if (s.signed_in) ghDone(s.user);
    validate();
  });
  $("gh-start").addEventListener("click", function () {
    $("gh-msg").textContent = "";
    api("github_start").then(function (d) {
      if (!d.ok) { $("gh-msg").innerHTML = '<span class="bad">' + esc(d.message) + "</span>"; return; }
      $("gh-code").textContent = d.user_code;
      $("gh-codebox").classList.remove("hide");
      var every = Math.max(1, d.interval || 5) * 1000;
      (function tick() {
        gh.polling = setTimeout(function () {
          api("github_poll").then(function (r) {
            if (r.state === "ok") return ghDone(r.user);
            if (r.state === "slow_down") every += 5000;
            if (r.state === "pending" || r.state === "slow_down") return tick();
            $("gh-wait").textContent = "";
            $("gh-msg").innerHTML = '<span class="bad">' + esc(r.message || (r.state === "expired" ? "The code ran out. Click Sign in again." :
              r.state === "denied" ? "The sign-in was not approved." : "Signing in did not work.")) + "</span>";
          });
        }, every);
      })();
    });
  });
  $("gh-use").addEventListener("click", function () {
    api("github_token", $("gh-token").value).then(function (r) {
      if (r.state === "ok") ghDone(r.user);
      else $("gh-msg").innerHTML = '<span class="bad">' + esc(r.message) + "</span>";
    });
  });

  function validate() {
    var ok = true, why = "";
    if (state.page === 0 && gh.needed && !gh.ok) { ok = false; why = "Sign in to GitHub to continue."; }
    if (state.page === 4) {
      ok = !!(state.dest && state.verdict && state.verdict.ok && state.place && state.place.free_gb > needGB() + 2);
      if (state.place && state.place.free_gb <= needGB() + 2) why = "Not enough free space for what you picked (" + gb(needGB()) + " needed).";
      else if (state.verdict && !state.verdict.ok) why = "This drive's format does not suit the computers you picked.";
      else if (!state.dest) why = "Pick a drive or a folder.";
    }
    if (state.page === 6) {
      var need = state.checklist.filter(function (c) { return c.kind === "required"; });
      ok = need.every(function (c) { return state.checks[c.id]; });
      if (!ok) why = "Tick each item to confirm you have read it.";
    }
    nextBtn.disabled = !ok;
    if (why) msg.textContent = why;
  }

  /* ---------- sizes ---------- */
  function fullMB() {
    if (state.edition !== "full") return 0;
    var mb = 0;
    THEMES.forEach(function (t) {
      var s = state.themes[t.id]; if (!s.on) return;
      mb += SIZE.theme + (s.sounds ? SIZE.sounds : 0) + (s.wallpapers ? SIZE.wallpapers : 0);
    });
    return mb + (state.retro ? SIZE.retro : 0) + (state.imagegen ? SIZE.imagegen : 0);
  }
  function modelsGB() {
    return state.catalog.reduce(function (a, m) { return a + (state.models[m.tag] ? m.size_gb : 0); }, 0);
  }
  function needGB() {
    var pc = pcsList().reduce(function (a, p) { return a + PC_GB[p]; }, 0);
    return pc + modelsGB() + fullMB() / 1024 + 0.5;
  }

  /* ---------- page entries ---------- */
  var ENTER = {
    1: function () {
      var i = state.info; if (!i) return;
      var gpus = (i.gpus || []).map(function (g) { return esc(g.name) + " (" + gb(g.vram_gb) + ")"; }).join("<br>") || "none found";
      $("facts").innerHTML = "<dt>System</dt><dd>" + (i.os === "mac" ? "macOS" : "Windows") + " &middot; " + esc(i.arch) + "</dd>" +
        "<dt>Processor</dt><dd>" + esc(i.cpu || "-") + "</dd><dt>Memory</dt><dd>" + gb(i.ram_gb) + "</dd>" +
        "<dt>Graphics</dt><dd>" + gpus + "</dd>";
      $("fastnote").innerHTML = i.fast_gb ? 'AI models run at full speed in <b class="good">' + gb(i.fast_gb) + "</b> on the " + esc(i.fast_kind) + "."
        : '<span class="warn">No graphics card the models can use - they will run on the processor, more slowly. The small models work well.</span>';
    },
    3: function () {
      renderThemes();
      if (!state.igrating) api("imagegen_rating").then(function (r) {
        state.igrating = r;
        var c = { green: "var(--green)", yellow: "var(--amber)", red: "var(--pink)" }[r.rating] || "inherit";
        $("igrate").innerHTML = '<br><b style="color:' + c + '">This computer: ' + r.rating + "</b> - " + esc(r.why) +
          " Each other computer sets it up from the desktop icon.";
        if (!r.backend) { $("imagegen").checked = false; $("imagegen").disabled = true; state.imagegen = false; renderThemes(); }
      });
    },
    4: function () { renderPlaces(); },
    5: function () { renderModels(); },
    6: function () { renderChecklist(); },
    7: function () { renderReview(); }
  };

  /* which computers */
  Array.prototype.forEach.call($("pcs").children, function (c) {
    c.addEventListener("click", function () {
      state.pcs = c.getAttribute("data-pc");
      Array.prototype.forEach.call($("pcs").children, function (x) { x.classList.toggle("sel", x === c); });
      state.verdict = null;
    });
  });

  /* edition + themes */
  Array.prototype.forEach.call($("editions").children, function (c) {
    c.addEventListener("click", function () {
      state.edition = c.getAttribute("data-ed");
      Array.prototype.forEach.call($("editions").children, function (x) { x.classList.toggle("sel", x === c); });
      $("fullopts").classList.toggle("hide", state.edition !== "full");
      renderThemes();
    });
  });
  function renderThemes() {
    $("themes").innerHTML = THEMES.map(function (t) {
      var s = state.themes[t.id];
      return '<div class="row" data-t="' + t.id + '"><input type="checkbox" data-k="on" ' + (s.on ? "checked" : "") + (t.locked ? " disabled" : "") + '>' +
        '<div class="t"><b>' + esc(t.name) + "</b>" + (t.locked ? "<small>The default theme - always included.</small>" : "") + "</div>" +
        '<label class="ck"><input type="checkbox" data-k="sounds" ' + (s.sounds ? "checked" : "") + (s.on ? "" : " disabled") + "> Sounds</label>" +
        '<label class="ck"><input type="checkbox" data-k="wallpapers" ' + (s.wallpapers ? "checked" : "") + (s.on ? "" : " disabled") + "> Wallpapers</label>" +
        '<span class="sz">' + (s.on ? (SIZE.theme + (s.sounds ? SIZE.sounds : 0) + (s.wallpapers ? SIZE.wallpapers : 0)) + " MB" : "-") + "</span></div>";
    }).join("");
    $("themesize").textContent = state.edition === "full" ? "about " + Math.round(fullMB()) + " MB in all" : "";
  }
  $("themes").addEventListener("change", function (ev) {
    var row = ev.target.closest(".row"); if (!row) return;
    state.themes[row.getAttribute("data-t")][ev.target.getAttribute("data-k")] = ev.target.checked;
    renderThemes();
  });
  $("retro").addEventListener("change", function () { state.retro = $("retro").checked; renderThemes(); });
  $("imagegen").addEventListener("change", function () { state.imagegen = $("imagegen").checked; renderThemes(); });

  /* where */
  function renderPlaces() {
    $("places").innerHTML = state.places.map(function (p, i) {
      var kind = p.system ? "This computer's main disk" : (p.external ? "External drive" : "Internal drive");
      return '<div class="card' + (state.place && state.place.path === p.path ? " sel" : "") + '" data-i="' + i + '">' +
        (p.external ? '<span class="tag">PORTABLE</span>' : "") +
        "<h3>" + esc(p.path.replace(/\\$/, "")) + " " + esc(p.label || "") + "</h3>" +
        '<div class="note">' + kind + " &middot; " + esc(p.fs) + "</div>" +
        '<div class="size">' + gb(p.free_gb) + " free of " + gb(p.total_gb) + "</div></div>";
    }).join("");
    $("destpath").textContent = state.dest || "-";
    renderVerdict();
  }
  $("places").addEventListener("click", function (ev) {
    var c = ev.target.closest(".card"); if (!c) return;
    var p = state.places[+c.getAttribute("data-i")];
    choose(p.path.replace(/[\\/]$/, "") + (p.path.indexOf("/") === 0 && p.path !== "/" ? "/Philibert" : "\\Philibert"), p);
  });
  $("pickfolder").addEventListener("click", function () {
    api("choose_folder").then(function (f) { if (f) choose(f, null); });
  });
  function choose(dest, place) {
    state.dest = dest; state.place = place; state.verdict = null; state.speed = null;
    renderPlaces();
    $("verdict").className = "verdict"; $("verdict").innerHTML = "Checking the drive&hellip;";
    api("check_place", dest, pcsList()).then(function (r) {
      state.place = Object.assign({}, place || {}, r); state.verdict = r.verdict; state.speed = r.speed;
      renderPlaces(); validate();
    });
  }
  function renderVerdict() {
    var v = state.verdict, el = $("verdict");
    if (!v) { if (!state.dest) el.className = "verdict hide"; return; }
    var sp = state.speed, speedTxt = "";
    if (sp && sp.read_mbs) {
      var slow = sp.read_mbs < 100;
      speedTxt = "<br>Speed: reads " + Math.round(sp.read_mbs) + " MB/s, writes " + Math.round(sp.write_mbs) + " MB/s. " +
        (slow ? '<span class="warn">This is a hard-drive speed: a big model takes several minutes to load the first time each session. An SSD makes that seconds.</span>'
              : '<span class="good">Fast - models load quickly.</span>');
    }
    el.className = "verdict " + (v.ok ? "ok" : "no");
    el.innerHTML = (v.ok ? '<b class="good">This drive works.</b> ' : '<b class="bad">This drive will not work as it is.</b> ') + esc(v.message) + speedTxt;
  }

  /* models */
  function renderModels() {
    var gpu = state.info && state.info.fast_gb;
    $("models").innerHTML = state.catalog.filter(function (m) { return m.kind !== "embed" || true; }).map(function (m) {
      return '<div class="row" data-tag="' + esc(m.tag) + '"><input type="checkbox" ' + (state.models[m.tag] ? "checked" : "") + (m.locked ? " disabled" : "") + ">" +
        '<i class="dot ' + m.rating + '" title="' + esc(m.why) + '"></i>' +
        '<div class="t"><b>' + esc(m.label) + "</b>" + (m.locked ? ' <span class="note">&middot; always included</span>' : "") +
        "<small>" + esc(m.why) + (m.note ? " " + esc(m.note) : "") + "</small></div>" +
        '<span class="sz">' + gb(m.size_gb) + "</span></div>";
    }).join("");
    var total = modelsGB();
    $("modeltotal").textContent = gb(total) + " of models";
    var sp = state.speed, big = state.catalog.filter(function (m) { return state.models[m.tag] && !m.locked; })
      .reduce(function (a, m) { return Math.max(a, m.size_gb); }, 0);
    $("loadnote").innerHTML = sp && sp.read_mbs && big ? "On the drive you picked, the biggest model you chose loads in about " +
      Math.max(1, Math.round(big * 1024 / sp.read_mbs / 60)) + " minute" + (Math.round(big * 1024 / sp.read_mbs / 60) > 1 ? "s" : "") + " the first time each session." : "";
  }
  $("models").addEventListener("change", function (ev) {
    var row = ev.target.closest(".row"); if (!row) return;
    state.models[row.getAttribute("data-tag")] = ev.target.checked;
    renderModels();
  });

  /* checklist */
  function renderChecklist() {
    var req = state.checklist.filter(function (c) { return c.kind !== "info"; });
    $("checklead").textContent = state.checklist.some(function (c) { return c.kind === "required"; })
      ? "A few things Philibert needs from this computer. Tick each one to confirm."
      : "Nothing needs installing on this computer. Everything Philibert needs goes onto the drive.";
    $("checklist").innerHTML = state.checklist.map(function (c) {
      var box = c.kind === "info" ? '<span class="dot green"></span>'
        : '<input type="checkbox" data-id="' + c.id + '" ' + (state.checks[c.id] ? "checked" : "") + ">";
      return '<div class="row">' + box + '<div class="t"><b>' + esc(c.title) + "</b><small>" + esc(c.detail) + "</small></div>" +
        '<span class="sz">' + (c.kind === "required" ? "needed" : c.kind === "optional" ? "optional" : "ok") + "</span></div>";
    }).join("");
    $("checkall").checked = req.length > 0 && req.every(function (c) { return state.checks[c.id]; });
    $("checkall").disabled = req.length === 0;
  }
  $("checklist").addEventListener("change", function (ev) {
    if (!ev.target.getAttribute("data-id")) return;
    state.checks[ev.target.getAttribute("data-id")] = ev.target.checked;
    renderChecklist(); validate();
  });
  $("checkall").addEventListener("change", function () {
    state.checklist.forEach(function (c) { if (c.kind !== "info") state.checks[c.id] = $("checkall").checked; });
    renderChecklist(); validate();
  });

  /* review */
  function plan() {
    var themes = {};
    THEMES.forEach(function (t) { if (state.themes[t.id].on) themes[t.id] = { sounds: state.themes[t.id].sounds, wallpapers: state.themes[t.id].wallpapers }; });
    return { dest: state.dest, pcs: pcsList(), edition: state.edition,
             full: state.edition === "full" ? { themes: themes, retro_vault: state.retro, image_gen: state.imagegen, default_theme: "win95",
                                              themes_offered: THEMES.map(function (t) { return t.id; }) } : {},
             models: state.catalog.filter(function (m) { return state.models[m.tag]; }).map(function (m) { return m.tag; }),
             shortcut: !!state.checks.shortcut };
  }
  function renderReview() {
    var p = plan(), names = state.catalog.filter(function (m) { return state.models[m.tag]; }).map(function (m) { return m.label; });
    $("review").innerHTML =
      "<dt>Where</dt><dd>" + esc(p.dest) + "</dd>" +
      "<dt>For</dt><dd>" + (p.pcs.length === 2 ? "Windows and Mac" : p.pcs[0] === "mac" ? "Mac" : "Windows") + "</dd>" +
      "<dt>Edition</dt><dd>" + (p.edition === "full" ? "Full - " + Object.keys(p.full.themes).length + " themes" + (p.full.retro_vault ? ", Retro Vault" : "") + (p.full.image_gen ? ", Image Generation" : "") : "Slim") + "</dd>" +
      "<dt>Models</dt><dd>" + esc(names.join(", ")) + "</dd>" +
      "<dt>Download</dt><dd>about " + gb(needGB()) + "</dd>" +
      "<dt>On this computer</dt><dd>" + (p.shortcut ? "a desktop shortcut" : "nothing") + "</dd>";
  }

  /* installing */
  var poll = null;
  function startInstall() {
    show(8);
    api("start_install", plan()).then(function () { poll = setInterval(tick, 400); });
  }
  function tick() {
    api("progress").then(function (s) {
      if (!s) return;
      $("b1").style.width = Math.round((s.overall || 0) * 100) + "%";
      var sweep = (s.step_pct || 0) < 0;
      $("b2w").classList.toggle("sweep", sweep);
      $("b2").style.width = sweep ? "" : Math.round(Math.max(0, s.step_pct || 0) * 100) + "%";
      $("instdetail").textContent = s.detail || "";
      $("inststeps").innerHTML = (s.steps || []).map(function (st, k) {
        return '<li class="' + (k < s.step || s.done ? "done" : k === s.step ? "on" : "") + '">' + esc(st.title) + "</li>";
      }).join("");
      if (s.error || s.done) {
        clearInterval(poll);
        state.result = s;
        finish(s);
      }
    });
  }
  function finish(s) {
    show(9);
    if (s.error) {
      $("donetitle").textContent = s.error === "cancelled" ? "Setup stopped" : "Setup stopped";
      $("donelead").textContent = s.error === "cancelled" ? "Nothing is lost: run Setup again and it continues where it stopped."
        : s.error + " Run Setup again and it continues where it stopped.";
      $("donefacts").innerHTML = "";
      nextBtn.textContent = "Close";
      return;
    }
    var p = plan(), win = p.pcs.indexOf("windows") >= 0, mac = p.pcs.indexOf("mac") >= 0;
    $("donelead").textContent = "Everything is on " + p.dest + ". Philibert runs offline from now on.";
    $("donefacts").innerHTML =
      (win ? "<dt>On Windows</dt><dd>Double-click <b>Start-Windows.bat</b> in that folder.</dd>" : "") +
      (mac ? "<dt>On a Mac</dt><dd>Double-click <b>Start-Mac.command</b>. The first start on a Mac finishes setting up there (with the Internet, once).</dd>" : "") +
      (p.edition === "full" ? "<dt>Full edition</dt><dd>Philibert opens on the retro desktop (Windows 95 to start; the other themes and Retro Vault arrive with Philibert updates). Philibert Chat is an icon on it.</dd>" : "") +
      "<dt>Your games</dt><dd>" + (p.edition === "full" && p.full.retro_vault ? "Put your own games in <b>Entertainment\\Cartridges</b>, one folder per system." : "-") + "</dd>";
    $("donewarn").textContent = (s.warnings || []).join(" ");
  }

  /* ---------- navigation ---------- */
  nextBtn.addEventListener("click", function () {
    if (state.page === 7) { startInstall(); return; }
    if (state.page === 9) {
      if (state.result && !state.result.error) api("open_philibert", state.dest);
      api("close");
      return;
    }
    show(state.page + 1);
  });
  backBtn.addEventListener("click", function () {
    if (state.page === 8) {                      // installing: stop, keep what is downloaded
      if (confirm("Stop installing? What is already downloaded stays on the drive; run Setup again to continue.")) {
        backBtn.disabled = true; api("cancel");
      }
      return;
    }
    if (state.page > 0) show(state.page - 1);
  });

  /* ---------- start ---------- */
  function boot() {
    Promise.all([api("survey"), api("places"), api("catalog"), api("default_model"), api("checklist")]).then(function (r) {
      state.info = r[0]; state.places = r[1]; state.catalog = r[2]; state.checklist = r[4];
      state.catalog.forEach(function (m) { state.models[m.tag] = !!(m.locked || m.tag === r[3]); });
      state.checklist.forEach(function (c) { if (c.kind === "optional") state.checks[c.id] = !!c.value; });
      var first = state.places.filter(function (p) { return p.external; })[0];
      if (first) choose(first.path.replace(/[\\/]$/, "") + "\\Philibert", first);
      var m = /[?&]page=(\d+)/.exec(location.search);
      show(m ? +m[1] : 0);
      if (m && +m[1] === 3 && /full/.test(location.search)) document.querySelector('[data-ed="full"]').click();
      if (m && +m[1] === 8) startInstall();
    });
  }
  if (window.pywebview) boot(); else window.addEventListener("pywebviewready", boot);
  setTimeout(function () { if (!state.info) boot(); }, 600);     // a plain browser: the stand-in API
})();
