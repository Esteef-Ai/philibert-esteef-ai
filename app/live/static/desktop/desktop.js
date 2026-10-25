/* Philibert's retro desktop (Full edition): icons, windows, taskbar, Start menu,
 * boot screen, screen saver, Control Panel, Trash and Shut Down.
 *
 * Apps are either pages (an iframe: Philibert Chat, Notes, ND Suite, apps in
 * <drive>/Apps) or built in here (Control Panel, Trash, the "coming soon" ones).
 * Settings live on the drive via /api/desktop, so both PCs share them.
 * The theme is CSS (win95.css today); this file is theme-neutral.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var I = window.PhilIcons, S = window.PhilSounds;
  var desk = $("desk"), winsEl = $("windows"), iconsEl = $("icons"), tasksEl = $("tasks");
  var st = { settings: {}, themes: [], apps: [], retro: false, installed: null, wins: {}, z: 10, active: null, sel: null };
  /* Every theme: its shell (taskbar / Program Manager / Mac menu bar / phone home
     screen / Commodore 64 screen), its name for Philibert, the boot screen and
     start-up sound. Wallpapers are in wallpapers.js; the look is the theme's CSS. */
  var THEMES = {
    win311:  { shell: "progman", family: "win", ver: "3.11", name: "Philibert for Workgroups 3.11", boot: "w311", sound: "startup_win311" },
    win95:   { shell: "taskbar", family: "win", ver: "95", name: "Philibert 95", boot: "clouds", sound: "startup" },
    winxp:   { shell: "taskbar", family: "win", ver: "xp", name: "Philibert XP", boot: "xp", sound: "startup_xp" },
    win11:   { shell: "taskbar", family: "win", ver: "11", name: "Philibert 11", boot: "w11", sound: "startup_win11" },
    os8:     { shell: "menubar", family: "mac", ver: "8", name: "Philibert OS 8", boot: "os8", sound: "startup_mac" },
    os9:     { shell: "menubar", family: "mac", ver: "9", name: "Philibert OS 9", boot: "os8", sound: "startup_mac" },
    macos:   { shell: "menubar", family: "mac", ver: "", name: "Philibert for macOS", boot: "macos", sound: "startup_mac", dock: true },
    ios:     { shell: "phone", family: "phone", ver: "", name: "Philibert for iOS", boot: "ios", sound: "startup_phone" },
    android: { shell: "phone", family: "phone", ver: "", name: "Philibert for Android", boot: "android", sound: "startup_phone" },
    c64:     { shell: "c64", family: "c64", ver: "64", name: "Philibert 64", boot: "c64", sound: "startup_c64" },
    redhat:  { shell: "taskbar", family: "linux", ver: "Linux", name: "Philibert Linux", boot: "redhat", sound: "startup_redhat" },
  };
  Object.keys(THEMES).forEach(function (k) { THEMES[k].wall = (window.PhilWalls.themes[k] || ["teal"]); });
  function T() { return THEMES[st.settings.theme] || THEMES.win95; }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function api(path, body) {
    return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json(); });
  }
  function save(changes) {
    Object.assign(st.settings, changes);
    return api("/api/desktop", { op: "save", settings: changes }).then(function (d) {
      if (d.ok) st.settings = d.settings;
    }).catch(function () {});
  }

  /* ================= the apps ================= */
  // added from the App Store? (a drive set up before the Store has every app)
  function has(id) { return !st.installed || st.installed.indexOf(id) >= 0; }
  function builtins() {
    var list = [
      { id: "chat", name: "Philibert Chat", icon: "chat", url: "/live/", w: 1280, h: 800, max: true },
      { id: "store", name: "App Store", icon: "store", internal: storeWin, w: 640, h: 560, title: "Esteef.Ai App Store" },
    ];
    if (has("notes")) list.push({ id: "notes", name: "Notes", icon: "notes", url: "/notes?embed=1", w: 1100, h: 720, title: "Philibert Notes" });
    if (has("files")) list.push({ id: "files", name: "Files", icon: "files", url: "/files", w: 1080, h: 700, title: "Philibert Files" });
    if (has("models")) list.push({ id: "models", name: "Models", icon: "models", url: "/modelmgr", w: 940, h: 720, title: "Philibert Models" });
    if (has("images") && st.imagegen) list.push({ id: "images", name: "Image Generation", icon: "images", url: "/images", w: 1240, h: 800, title: "Philibert Image Generation" });
    if (has("vault") && st.retro) list.push({ id: "vault", name: "Retro Vault", icon: "vault", url: "/retro/", w: 1240, h: 800, max: true });
    if (has("band")) list.push({ id: "band", name: "Band Manager", icon: "band", url: "/band?embed=1", w: 1180, h: 760, title: "Philibert Band Manager" });
    if (has("board")) list.push({ id: "board", name: "Group Board", icon: "board", url: "/board", w: 1100, h: 760, title: "Group Board" });
    if (has("feedback")) list.push({ id: "feedback", name: "Feedback Shooter", icon: "feedback", url: "/feedback", w: 900, h: 720, title: "Feedback Shooter" });
    var sh = THEMES[st.settings.theme] ? THEMES[st.settings.theme].shell : "taskbar";
    if (sh === "phone" || sh === "c64")          // no Start menu there: shutting down is an app
      list.push({ id: "power", name: "Shut Down", icon: "shutdown", action: function () { shutdownDialog(); } });
    list.push({ id: "control", name: "Control Panel", icon: "control", internal: controlPanel, w: 420, h: 470, fixed: true },
              { id: "trash", name: "Trash", icon: "trash", internal: trashWin, w: 560, h: 380 });
    return list;
  }
  function allApps() {
    return builtins().concat(st.apps.map(function (a) {
      return { id: "app:" + a.id, name: a.name, icon: "app", img: a.icon, url: a.url, w: 980, h: 680, published: true };
    }));
  }
  function appById(id) { return allApps().find(function (a) { return a.id === id; }); }
  function iconHtml(app, size) {
    return app.img ? '<img src="' + esc(app.img) + '" alt="" width="' + size + '" height="' + size + '">' : I.svg(app.icon, size);
  }

  /* ================= desktop icons ================= */
  var GRID_X = 78, GRID_Y = 76;
  function iconPos(i) {
    var sh = T().shell;
    if (sh === "progman") {                    // rows inside the Program Manager group
      var cols = Math.max(1, Math.floor((iconsEl.clientWidth - 8) / 84));
      return [8 + (i % cols) * 84, 8 + Math.floor(i / cols) * 70];
    }
    if (sh === "phone") {                      // a home-screen grid under the status bar
      var pc = Math.max(4, Math.min(8, Math.floor(desk.clientWidth / 110)));
      var pw = desk.clientWidth / pc;
      return [Math.round((i % pc) * pw + (pw - 84) / 2), 70 + Math.floor(i / pc) * 112];
    }
    var rows = Math.max(1, Math.floor((desk.clientHeight - 8) / GRID_Y));
    if (sh === "menubar")                      // the Mac way: down the right-hand side
      return [desk.clientWidth - 84 - Math.floor(i / rows) * GRID_X, 10 + (i % rows) * GRID_Y];
    return [8 + Math.floor(i / rows) * GRID_X, 6 + (i % rows) * GRID_Y];
  }
  function renderIcons() {
    // positions are per shell: a Mac layout is not a Windows one
    var saved = (st.settings.icons || {})[T().shell] || {};
    iconsEl.innerHTML = allApps().map(function (a, i) {
      var p = saved[a.id] || iconPos(i);
      return '<div class="dicon" role="listitem" tabindex="0" data-id="' + esc(a.id) + '" style="left:' + p[0] + "px;top:" + p[1] + 'px">' +
             '<div class="img tile t-' + esc(a.id.replace(/[^a-z0-9]/g, "")) + '">' + iconHtml(a, 32) + '</div><div class="lbl">' + esc(a.name) + "</div></div>";
    }).join("");
  }
  function select(el) {
    iconsEl.querySelectorAll(".sel").forEach(function (e) { e.classList.remove("sel"); });
    if (el) { el.classList.add("sel"); el.focus({ preventScroll: true }); }
  }
  iconsEl.addEventListener("dblclick", function (ev) {
    var d = ev.target.closest(".dicon");
    if (d) open(d.dataset.id);
  });
  // apps ND publishes appear by themselves; right-click one to take it off the desktop
  function refreshApps() {
    api("/api/desktop", { op: "state" }).then(function (d) {
      if (d.ok && JSON.stringify(d.apps) !== JSON.stringify(st.apps)) { st.apps = d.apps; renderIcons(); }
    }).catch(function () {});
  }
  setInterval(refreshApps, 15000);
  addEventListener("focus", refreshApps);
  iconsEl.addEventListener("contextmenu", function (ev) {
    var d = ev.target.closest(".dicon");
    if (!d) return;
    ev.preventDefault();
    select(d);
    var id = d.dataset.id, app = appById(id);
    var items = [{ label: "Open", run: function () { open(id); } }];
    if (id === "trash") items.push("-", { label: "Empty Trash", run: emptyTrash });
    if (app && app.published) items.push("-", { label: "Remove from desktop", run: function () {
      api("/api/desktop", { op: "app_remove", id: id.slice(4) }).then(function (r) {
        if (!r.ok) { msgbox("Remove", r.msg || "Could not remove it.", "error"); return; }
        close(id); refreshApps();
      });
    } });
    dropMenu(d, items);
    fly.style.left = Math.min(ev.clientX, innerWidth - fly.offsetWidth - 4) + "px";
    fly.style.top = Math.min(ev.clientY, innerHeight - fly.offsetHeight - 4) + "px";
  });
  iconsEl.addEventListener("keydown", function (ev) {
    var d = ev.target.closest(".dicon");
    if (d && ev.key === "Enter") open(d.dataset.id);
  });
  desk.addEventListener("pointerdown", function (ev) {
    closeMenus();
    if (ev.target === desk || ev.target === iconsEl || ev.target.id === "wallart") select(null);
  });
  // drag icons around; they land on the grid and the place is remembered
  iconsEl.addEventListener("pointerdown", function (ev) {
    var d = ev.target.closest(".dicon");
    if (!d || ev.button !== 0) return;
    select(d);
    var sx = ev.clientX, sy = ev.clientY, ox = d.offsetLeft, oy = d.offsetTop, moved = false;
    function mv(e) {
      var dx = e.clientX - sx, dy = e.clientY - sy;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 5) return;
      moved = true;
      d.classList.add("dragging");
      d.style.left = ox + dx + "px"; d.style.top = oy + dy + "px";
    }
    function up() {
      removeEventListener("pointermove", mv); removeEventListener("pointerup", up);
      d.classList.remove("dragging");
      if (!moved) return;
      var box = iconsEl.getBoundingClientRect();
      var x = Math.max(4, Math.min(box.width - 76, Math.round((d.offsetLeft - 8) / GRID_X) * GRID_X + 8));
      var y = Math.max(4, Math.min(box.height - 70, Math.round((d.offsetTop - 6) / GRID_Y) * GRID_Y + 6));
      d.style.left = x + "px"; d.style.top = y + "px";
      var icons = Object.assign({}, st.settings.icons || {}), sh = T().shell;
      icons[sh] = Object.assign({}, icons[sh] || {});
      icons[sh][d.dataset.id] = [x, y];
      save({ icons: icons });
    }
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  });

  /* ================= windows ================= */
  function open(id, opts) {
    var app = appById(id);
    if (!app) return;
    closeMenus();
    if (app.action) { app.action(); return; }
    var sh = T().shell;
    if (st.wins[id]) { restore(id); focus(id); return st.wins[id]; }
    S.play("open");
    var n = Object.keys(st.wins).length;
    var W = Math.min(app.w || 640, desk.clientWidth - 40), H = Math.min(app.h || 440, desk.clientHeight - 30);
    var x = Math.max(10, (desk.clientWidth - W) / 2 + (n % 6) * 24 - 60), y = Math.max(6, (desk.clientHeight - H) / 2 + (n % 6) * 22 - 50);
    var el = document.createElement("div");
    // phones and the 64 open every app full-screen
    el.className = "win raised" + (app.max || sh === "phone" || sh === "c64" ? " max" : "");
    el.dataset.id = id;
    el.style.cssText = "left:" + x + "px;top:" + y + "px;width:" + W + "px;height:" + H + "px";
    el.innerHTML =
      '<div class="titlebar">' + iconHtml(app, 16) + '<span class="tt">' + esc(app.title || app.name) + "</span>" +
      '<button class="btn tbtn" data-act="min" aria-label="Minimise">&#9601;</button>' +
      (app.fixed ? "" : '<button class="btn tbtn" data-act="max" aria-label="Maximise">&#9633;</button>') +
      '<button class="btn tbtn close" data-act="close" aria-label="Close">&#10005;</button></div>' +
      '<div class="wbody' + (app.internal ? " face" : "") + '"><div class="shield"></div></div>' +
      (app.fixed ? "" : '<div class="grip"></div>');
    winsEl.appendChild(el);
    var body = el.querySelector(".wbody");
    if (app.url) {
      var f = document.createElement("iframe");
      f.src = app.url; f.title = app.name;
      body.appendChild(f);
      // C64: Esc is RUN/STOP - back to the BASIC screen even with the app focused. Keys
      // inside a frame never reach this page, so listen in the frame (same origin) and
      // in the frames it holds (Philibert Chat has one).
      var hookEsc = function (fr) {
        try {
          var w = fr.contentWindow;
          if (!w || w.__philEsc) return;
          w.__philEsc = true;
          w.addEventListener("keydown", function (ev) {
            if (ev.key === "Escape" && T().shell === "c64" && st.wins[id]) { minimize(id); renderC64(); }
          });
          var inner = function () { w.document.querySelectorAll("iframe").forEach(function (x) {
            x.addEventListener("load", function () { hookEsc(x); }); hookEsc(x); }); };
          if (w.document.readyState === "loading") w.addEventListener("DOMContentLoaded", inner); else inner();
        } catch (e) { /* another site's page: it keeps its own keys */ }
      };
      f.addEventListener("load", function () { hookEsc(f); });
    } else if (app.internal) {
      app.internal(body, el, opts || {});
      if (!body.querySelector(".shield")) {       // the app replaced the body: put the click shield back
        var sh = document.createElement("div");
        sh.className = "shield";
        body.prepend(sh);
      }
    }
    st.wins[id] = el;
    wireWindow(el, id);
    focus(id);
    renderTasks();
    return el;
  }

  function wireWindow(el, id) {
    var tb = el.querySelector(".titlebar");
    el.addEventListener("pointerdown", function () { focus(id); }, true);
    el.querySelector(".shield").addEventListener("pointerdown", function () { focus(id); });
    tb.addEventListener("dblclick", function (ev) { if (!ev.target.closest("button") && el.querySelector('[data-act="max"]')) toggleMax(id); });
    tb.addEventListener("click", function (ev) {
      var b = ev.target.closest("button");
      if (!b) return;
      if (b.dataset.act === "close") close(id);
      if (b.dataset.act === "min") minimize(id);
      if (b.dataset.act === "max") toggleMax(id);
    });
    tb.addEventListener("pointerdown", function (ev) {
      if (ev.target.closest("button") || el.classList.contains("max") || ev.button !== 0) return;
      var sx = ev.clientX, sy = ev.clientY, ox = el.offsetLeft, oy = el.offsetTop;
      document.body.classList.add("dragging");
      function mv(e) {
        el.style.left = Math.max(-el.offsetWidth + 60, Math.min(desk.clientWidth - 60, ox + e.clientX - sx)) + "px";
        el.style.top = Math.max(0, Math.min(desk.clientHeight - 20, oy + e.clientY - sy)) + "px";
      }
      function up() { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); document.body.classList.remove("dragging"); }
      addEventListener("pointermove", mv); addEventListener("pointerup", up);
    });
    var grip = el.querySelector(".grip");
    if (grip) grip.addEventListener("pointerdown", function (ev) {
      ev.preventDefault();
      var sx = ev.clientX, sy = ev.clientY, ow = el.offsetWidth, oh = el.offsetHeight;
      document.body.classList.add("dragging");
      function mv(e) {
        el.style.width = Math.max(240, ow + e.clientX - sx) + "px";
        el.style.height = Math.max(140, oh + e.clientY - sy) + "px";
      }
      function up() { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); document.body.classList.remove("dragging"); }
      addEventListener("pointermove", mv); addEventListener("pointerup", up);
    });
  }

  function focus(id) {
    var el = st.wins[id];
    if (!el) return;
    if (st.active !== id) {
      Object.keys(st.wins).forEach(function (k) { st.wins[k].classList.toggle("active", k === id); });
      el.style.zIndex = ++st.z;
      st.active = id;
      renderTasks();
    }
  }
  function close(id) {
    var el = st.wins[id];
    if (!el) return;
    S.play("close");
    el.remove();
    delete st.wins[id];
    if (st.active === id) {
      st.active = null;
      var top = Object.keys(st.wins).filter(function (k) { return !st.wins[k].classList.contains("min"); })
        .sort(function (a, b) { return st.wins[b].style.zIndex - st.wins[a].style.zIndex; })[0];
      if (top) focus(top);
    }
    renderTasks();
  }
  function minimize(id) {
    var el = st.wins[id];
    if (!el) return;
    S.play("minimize");
    if (T().shell === "menubar" && !T().dock) {   // classic Mac: roll the window up into its title bar
      el.classList.toggle("shade");
      return;
    }
    el.classList.add("min");                     // macOS: into the Dock; phones, the 64: back home
    el.classList.remove("active");
    if (st.active === id) st.active = null;
    renderTasks();
  }
  function restore(id) { var el = st.wins[id]; if (el) el.classList.remove("min"); }
  function toggleMax(id) { var el = st.wins[id]; if (el) el.classList.toggle("max"); }

  /* ================= taskbar ================= */
  function winInfo(id) {
    var tb = st.wins[id].querySelector(".titlebar");
    var ico = tb.querySelector(".ico, img");
    return { title: tb.querySelector(".tt").textContent, ico: ico ? ico.outerHTML : "" };
  }
  function renderTasks() {
    var sh = T().shell, ids = Object.keys(st.wins);
    if (sh === "taskbar") {
      tasksEl.innerHTML = ids.map(function (id) {
        var w = winInfo(id), down = st.active === id && !st.wins[id].classList.contains("min");
        return '<button class="btn task' + (down ? " down" : "") + '" data-id="' + esc(id) + '" title="' + esc(w.title) + '">' +
               w.ico + '<span class="tt">' + esc(w.title) + "</span></button>";
      }).join("");
    } else if (sh === "progman") {             // 3.11: minimised windows sit as icons along the bottom
      $("minicons").innerHTML = ids.filter(function (id) { return st.wins[id].classList.contains("min"); }).map(function (id) {
        var w = winInfo(id);
        return '<div class="dicon mini" data-id="' + esc(id) + '"><div class="img">' + w.ico.replace(/width="16" height="16"/, 'width="32" height="32"') +
               '</div><div class="lbl">' + esc(w.title) + "</div></div>";
      }).join("");
    } else if (sh === "menubar") {             // Mac: the window menu at the right of the menu bar
      var a = st.active && st.wins[st.active] ? winInfo(st.active) : null;
      $("mb-apps").innerHTML = a ? a.ico + "<span>" + esc(a.title) + "</span>" : I.svg("chat", 16) + "<span>Finder</span>";
      if (T().dock) renderDock();
    } else if (sh === "phone") {
      renderDock();
    } else if (sh === "c64" && !(st.active && st.wins[st.active] && !st.wins[st.active].classList.contains("min"))) {
      renderC64();
    }
  }
  $("minicons").addEventListener("dblclick", function (ev) {
    var d = ev.target.closest(".dicon");
    if (d) { restore(d.dataset.id); focus(d.dataset.id); renderTasks(); }
  });
  tasksEl.addEventListener("click", function (ev) {
    var b = ev.target.closest(".task");
    if (!b) return;
    var id = b.dataset.id, el = st.wins[id];
    if (el.classList.contains("min")) { restore(id); focus(id); }
    else if (st.active === id) minimize(id);
    else focus(id);
  });
  function tick() {
    var d = new Date();
    $("clock").textContent = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    $("clock").title = d.toLocaleDateString([], { weekday: "long", year: "numeric", month: "long", day: "numeric" });
    $("mb-clock").textContent = $("clock").textContent;
    $("mb-clock").title = $("clock").title;
  }
  setInterval(tick, 10000);

  /* ================= Start menu ================= */
  var sm = $("startmenu"), fly = $("flyout"), startBtn = $("start");
  function mi(icon, label, act, sub) {
    return '<li class="mi' + (sub ? " sub" : "") + '" data-act="' + act + '">' + I.svg(icon, 24) + "<span>" + label + "</span></li>";
  }
  function renderStart() {
    var old = sm.querySelector(".sm-right");
    if (old) old.remove();
    if (st.settings.theme === "winxp") {
      // XP: the boombox as the user tile, pinned apps left, places right, Turn Off below
      $("sm-head").innerHTML = '<span class="tile">' + I.p1(42, "#fff", "#2b6fd6") + "</span><b>Philibert</b>";
      $("sm-list").innerHTML = mi("chat", "<b>Philibert Chat</b>", "chat") + mi("notes", "<b>Notes</b>", "notes") +
        '<li class="sep"></li>' + mi("programs", "All <u>P</u>rograms", "programs", true);
      var right = document.createElement("ul");
      right.className = "sm-right";
      right.innerHTML = mi("docs", "My <b>Notes</b>", "docs", true) + mi("control", "Control Panel", "control") +
        mi("help", "Help and Support", "help") + mi("find", "Search", "find");
      sm.querySelector(".sm-main").appendChild(right);
      $("sm-foot").innerHTML = '<button class="xpf" data-act="unload">' + I.svg("gpu", 22) + "Unload GPU</button>" +
        '<button class="xpf off" data-act="shutdown">' + I.svg("shutdown", 22) + "Turn Off Philibert</button>";
      return;
    }
    if (st.settings.theme === "win11") {
      // 11: a centred panel - search, pinned apps in a grid, recent notes, the user and power
      $("sm-head").innerHTML = '<input class="w11-search" placeholder="Search for apps, settings and notes" id="w11-q">';
      $("sm-list").innerHTML = '<li class="w11-h">Pinned</li><li class="w11-grid">' + allApps().map(function (a) {
        return '<button class="w11-app" data-app="' + esc(a.id) + '">' + iconHtml(a, 32) + "<span>" + esc(a.name) + "</span></button>";
      }).join("") + '</li><li class="w11-h">Recommended</li><li class="w11-rec" id="w11-rec"></li>';
      $("sm-foot").innerHTML = '<span class="w11-user">' + I.p1(26, "#fff", "#3c8cff") + "<b>Philibert</b></span>" +
        '<button class="w11-pow" data-act="shutdown" title="Power">' + I.svg("shutdown", 20) + "</button>";
      recentNotes().then(function (notes) {
        var r = $("w11-rec");
        if (r) r.innerHTML = notes.slice(0, 6).map(function (n) {
          return '<button class="w11-doc" data-note="' + esc(n.id) + '">' + I.svg("notes", 24) + "<span>" + esc(n.title) + "</span></button>";
        }).join("") || '<span class="none">Your recent notes show up here.</span>';
      });
      return;
    }
    $("sm-head").innerHTML = ""; $("sm-foot").innerHTML = "";
    $("sm-list").innerHTML =
      mi("programs", "<u>P</u>rograms", "programs", true) +
      mi("docs", "<u>D</u>ocuments", "docs", true) +
      mi("settings", "<u>S</u>ettings", "settings", true) +
      mi("find", "<u>F</u>ind", "find") +
      mi("help", "<u>H</u>elp", "help") +
      '<li class="sep"></li>' +
      mi("gpu", "<u>U</u>nload GPU", "unload") +
      mi("shutdown", "Sh<u>u</u>t Down...", "shutdown");
  }
  function closeMenus() {
    sm.hidden = true; fly.hidden = true;
    fly.classList.remove("drop");
    document.querySelectorAll(".mb.open, #mb-apps.open").forEach(function (e) { e.classList.remove("open"); });
    startBtn.classList.remove("down");
    startBtn.setAttribute("aria-expanded", "false");
    sm.querySelectorAll(".open").forEach(function (e) { e.classList.remove("open"); });
  }
  startBtn.addEventListener("click", function (ev) {
    ev.stopPropagation();
    if (!sm.hidden) { closeMenus(); return; }
    renderStart();
    sm.hidden = false;
    startBtn.classList.add("down");
    startBtn.setAttribute("aria-expanded", "true");
  });
  document.addEventListener("pointerdown", function (ev) {
    if (!sm.contains(ev.target) && !fly.contains(ev.target) && !startBtn.contains(ev.target) &&
        !ev.target.closest(".mb, #mb-apps")) closeMenus();
  });
  function showFly(li, items) {
    sm.querySelectorAll(".open").forEach(function (e) { e.classList.remove("open"); });
    li.classList.add("open");
    fly.innerHTML = "<ul>" + (items.length ? items.map(function (it, i) {
      return '<li class="mi" data-i="' + i + '">' + (it.html || I.svg(it.icon || "app", 16)) + "<span>" + esc(it.label) + "</span></li>";
    }).join("") : '<li class="none">(Empty)</li>') + "</ul>";
    fly.hidden = false;
    var r = li.getBoundingClientRect();
    fly.style.left = r.right - 3 + "px";
    fly.style.top = Math.min(r.top - 3, innerHeight - 30 - fly.offsetHeight) + "px";
    fly.onclick = function (ev) {
      var x = ev.target.closest("[data-i]");
      if (x) { closeMenus(); items[+x.dataset.i].run(); }
    };
  }
  sm.addEventListener("input", function (ev) {
    if (ev.target.id !== "w11-q") return;
    var q = ev.target.value.toLowerCase();
    sm.querySelectorAll(".w11-app").forEach(function (b) { b.hidden = q && b.textContent.toLowerCase().indexOf(q) < 0; });
  });
  sm.addEventListener("keydown", function (ev) {
    if (ev.target.id !== "w11-q" || ev.key !== "Enter") return;
    var first = [].find.call(sm.querySelectorAll(".w11-app"), function (b) { return !b.hidden; });
    if (first) first.click();
  });
  sm.addEventListener("mouseover", function (ev) {
    var li = ev.target.closest(".mi");
    if (!li || li.classList.contains("open")) return;
    var act = li.dataset.act;
    if (act === "programs") {
      showFly(li, allApps().map(function (a) {
        return { label: a.name, html: iconHtml(a, 16), run: function () { open(a.id); } };
      }));
    } else if (act === "docs") {
      api("/api/notes", { op: "tree" }).then(function (d) {
        var notes = (d.notes || []).slice().sort(function (a, b) { return b.mtime - a.mtime; }).slice(0, 10);
        if (!li.classList.contains("open") && sm.hidden) return;
        showFly(li, notes.map(function (n) {
          return { label: n.title, icon: "notes", run: function () { openNote(n.id); } };
        }));
      });
      li.classList.add("open");
    } else if (act === "settings") {
      showFly(li, [
        { label: "Control Panel", icon: "control", run: function () { open("control"); } },
        { label: "Wallpaper", icon: "settings", run: function () { open("control", { tab: "wallpaper" }); } },
        { label: "Screen Saver", icon: "settings", run: function () { open("control", { tab: "saver" }); } },
      ]);
    } else {
      fly.hidden = true;
      sm.querySelectorAll(".open").forEach(function (e) { e.classList.remove("open"); });
    }
  });
  sm.addEventListener("click", function (ev) {
    var w11a = ev.target.closest("[data-app]"), w11n = ev.target.closest("[data-note]");
    if (w11a) { closeMenus(); open(w11a.dataset.app); return; }
    if (w11n) { closeMenus(); openNote(w11n.dataset.note); return; }
    var li = ev.target.closest(".mi, .xpf, .w11-pow");
    if (!li) return;
    var act = li.dataset.act;
    if (act === "find") { closeMenus(); open("notes"); }
    if (act === "help") { closeMenus(); openNote("Philibert/Welcome to Philibert.md"); }
    if (act === "unload") { closeMenus(); unloadGpu(); }
    if (act === "control") { closeMenus(); open("control"); }
    if (act === "chat") { closeMenus(); open("chat"); }
    if (act === "notes") { closeMenus(); open("notes"); }
    if (act === "shutdown") { closeMenus(); shutdownDialog(); }
  });
  /* ---------- drop-down menus: the Mac menu bar and 3.11's Program Manager ---------- */
  function dropMenu(anchor, items) {
    closeMenus();
    anchor.classList.add("open");
    fly.innerHTML = "<ul>" + items.map(function (it, i) {
      if (it === "-") return '<li class="sep"></li>';
      return '<li class="mi' + (it.off ? " off" : "") + '" data-i="' + i + '">' + (it.icon ? I.svg(it.icon, 16) : "") +
             "<span>" + esc(it.label) + "</span>" + (it.key ? '<kbd>' + esc(it.key) + "</kbd>" : "") + "</li>";
    }).join("") + "</ul>";
    fly.hidden = false;
    fly.classList.add("drop");
    var r = anchor.getBoundingClientRect();
    fly.style.left = Math.min(r.left, innerWidth - fly.offsetWidth - 4) + "px";
    fly.style.top = r.bottom + "px";
    fly.onclick = function (ev) {
      var x = ev.target.closest("[data-i]");
      if (!x || x.classList.contains("off")) return;
      closeMenus();
      items[+x.dataset.i].run();
    };
  }
  function recentNotes() {
    return api("/api/notes", { op: "tree" }).then(function (d) {
      return (d.notes || []).slice().sort(function (a, b) { return b.mtime - a.mtime; }).slice(0, 8);
    }).catch(function () { return []; });
  }
  function closeActive() { if (st.active) close(st.active); }
  function cleanUp() {
    var icons = Object.assign({}, st.settings.icons || {});
    delete icons[T().shell];
    save({ icons: icons }).then(renderIcons);
  }
  function aboutItem() {
    return { label: (T().shell === "menubar" ? "About This Philibert…" : "About Philibert…"), icon: "help",
             run: function () { open("control", { tab: "about" }); } };
  }
  var MAC_MENUS = {
    philibert: function (cb) {
      recentNotes().then(function (notes) {
        cb([aboutItem(), "-"].concat(allApps().map(function (a) {
          return { label: a.name, icon: a.img ? "app" : a.icon, run: function () { open(a.id); } };
        }), ["-", { label: "Recent Notes", off: true }], notes.map(function (n) {
          return { label: "   " + n.title, icon: "notes", run: function () { openNote(n.id); } };
        }), ["-", { label: "Unload GPU", icon: "gpu", run: unloadGpu }]));
      });
    },
    File: function (cb) {
      cb([{ label: "New Chat", key: "", run: function () { open("chat"); } },
          { label: "New Note", run: function () { open("notes"); } }, "-",
          { label: "Close Window", off: !st.active, run: closeActive }]);
    },
    View: function (cb) {
      cb([{ label: "Clean Up", run: cleanUp }, { label: "Control Panels", run: function () { open("control"); } }]);
    },
    Special: function (cb) {
      cb([{ label: "Open Trash", run: function () { open("trash"); } }, "-",
          { label: "Restart", run: function () { location.reload(); } },
          { label: "Shut Down", run: shutdownDialog }]);
    },
  };
  function renderMenubar() {
    $("mb-left").innerHTML = '<button class="mb" data-m="philibert" title="Philibert">' + I.p1(16, "#000", "#fff") + "</button>" +
      ["File", "View", "Special"].map(function (m) { return '<button class="mb" data-m="' + m + '">' + m + "</button>"; }).join("");
  }
  $("mb-left").addEventListener("pointerdown", function (ev) {
    var b = ev.target.closest(".mb");
    if (!b) return;
    ev.stopPropagation();
    if (b.classList.contains("open")) { closeMenus(); return; }
    MAC_MENUS[b.dataset.m](function (items) { dropMenu(b, items); });
  });
  $("mb-apps").addEventListener("pointerdown", function (ev) {
    ev.stopPropagation();
    var b = $("mb-apps");
    if (b.classList.contains("open")) { closeMenus(); return; }
    var ids = Object.keys(st.wins);
    dropMenu(b, (ids.length ? ids.map(function (id) {
      return { label: winInfo(id).title, run: function () { restore(id); st.wins[id].classList.remove("shade"); focus(id); } };
    }) : [{ label: "No windows open", off: true }]).concat(["-", { label: "Hide Others", run: function () {
      Object.keys(st.wins).forEach(function (id) { if (id !== st.active) st.wins[id].classList.add("min"); });
    } }, { label: "Show All", run: function () { Object.keys(st.wins).forEach(restore); } }]));
  });
  var PM_MENUS = {
    File: function () {
      return [{ label: "Open Philibert Chat", run: function () { open("chat"); } },
              { label: "Open Notes", run: function () { open("notes"); } }, "-",
              { label: "Unload GPU", run: unloadGpu }, "-",
              { label: "Exit Philibert...", run: shutdownDialog }];
    },
    Options: function () { return [{ label: "Control Panel", run: function () { open("control"); } }, { label: "Arrange Icons", run: cleanUp }]; },
    Window: function () {
      var ids = Object.keys(st.wins);
      return ids.length ? ids.map(function (id, i) {
        return { label: (i + 1) + " " + winInfo(id).title, run: function () { restore(id); focus(id); renderTasks(); } };
      }) : [{ label: "(no windows open)", off: true }];
    },
    Help: function () { return [{ label: "Contents", run: function () { openNote("Philibert/Welcome to Philibert.md"); } }, aboutItem()]; },
  };
  $("pm-menu").innerHTML = Object.keys(PM_MENUS).map(function (m) { return '<button class="mb" data-m="' + m + '">' + m + "</button>"; }).join("");
  $("pm-menu").addEventListener("pointerdown", function (ev) {
    var b = ev.target.closest(".mb");
    if (!b) return;
    ev.stopPropagation();
    if (b.classList.contains("open")) { closeMenus(); return; }
    dropMenu(b, PM_MENUS[b.dataset.m]());
  });
  function unloadGpu() {
    api("/api/unload_gpu", { reason: "the desktop menu" }).then(function () {
      msgbox("Unload GPU", "The model is off the graphics card. It loads again the next time you ask Philibert something.", "info");
    }).catch(function () { msgbox("Unload GPU", "Could not reach Philibert.", "error"); });
  }

  function openNote(id) {
    var w = open("notes");
    var f = w && w.querySelector("iframe");
    if (f) {
      var go = function () { try { f.contentWindow.location.hash = encodeURIComponent(id); } catch (e) { /* not ready */ } };
      if (f.contentDocument && f.contentDocument.readyState === "complete") go();
      else f.addEventListener("load", go, { once: true });
    }
  }

  /* ================= small dialogs ================= */
  var dlgN = 0;
  function dialog(title, icon, html, w, h) {
    var id = "dlg" + (++dlgN);
    var el = document.createElement("div");
    el.className = "win raised";
    el.dataset.id = id;
    var W = w || 360, H = h || 170;
    el.style.cssText = "left:" + (desk.clientWidth - W) / 2 + "px;top:" + (desk.clientHeight - H) / 2.4 + "px;width:" + W + "px;height:" + H + "px;min-height:0";
    el.innerHTML = '<div class="titlebar">' + I.svg(icon || "app", 16) + '<span class="tt">' + esc(title) + '</span>' +
                   '<button class="btn tbtn close" data-act="close" aria-label="Close">&#10005;</button></div>' +
                   '<div class="wbody face"><div class="shield"></div>' + html + "</div>";
    winsEl.appendChild(el);
    st.wins[id] = el;
    wireWindow(el, id);
    focus(id);
    return { el: el, close: function () { el.remove(); delete st.wins[id]; if (st.active === id) st.active = null; renderTasks(); } };
  }
  function msgbox(title, text, kind) {
    S.play(kind === "error" ? "error" : "ding");
    var d = dialog(title, kind === "error" ? "shutdown" : "help",
      '<div class="msgbox"><div class="q">' + (kind === "error" ? "!" : "i") + "</div><div>" + esc(text) + "</div></div>" +
      '<div class="dlg-foot" style="justify-content:center"><button class="btn" data-ok>OK</button></div>', 380, 150);
    d.el.querySelector("[data-ok]").addEventListener("click", d.close);
    d.el.querySelector('[data-act="close"]').addEventListener("click", d.close);
    d.el.querySelector("[data-ok]").focus();
  }

  /* ================= Shut Down ================= */
  function shutdownDialog() {
    var d = dialog("Shut Down Philibert", "shutdown",
      '<div class="msgbox"><div style="flex:none">' + I.svg("shutdown", 32) + '</div><div>Are you sure you want to:' +
      '<div class="radio">' +
      '<label><input type="radio" name="sd" value="off" checked> Shut down Philibert?</label>' +
      '<label><input type="radio" name="sd" value="restart"> Restart the desktop?</label>' +
      '<label><input type="radio" name="sd" value="slim"> Switch to Philibert Chat (the simple view)?</label>' +
      "</div></div></div>" +
      '<div class="dlg-foot"><button class="btn" data-yes>Yes</button><button class="btn" data-no>No</button></div>', 380, 200);
    var done = d.close;
    d.el.querySelector("[data-no]").addEventListener("click", done);
    d.el.querySelector('[data-act="close"]').addEventListener("click", done);
    d.el.querySelector("[data-yes]").addEventListener("click", function () {
      var v = d.el.querySelector('input[name="sd"]:checked').value;
      done();
      if (v === "restart") { location.reload(); return; }
      if (v === "slim") { location.href = "/live/"; return; }
      S.play("shutdown");
      $("safe").hidden = false;
      setTimeout(function () { api("/api/desktop", { op: "shutdown" }).catch(function () {}); }, 1600);
    });
  }

  /* ================= built-in apps ================= */
  function trashWin(body) {
    body.innerHTML = '<div class="explorer"><div class="menubar"><span>File</span><span>Edit</span><span>View</span><span>Help</span>' +
      '<button class="btn" id="trash-empty" style="margin-left:auto;min-width:0;padding:2px 10px">Empty Trash</button></div>' +
      '<div class="rows well" style="margin:0 2px"><div class="row head"><span>Name</span><span>Was in</span><span>Deleted</span></div>' +
      '<div id="trash-rows"></div></div><div class="status sunk" id="trash-status">Loading...</div></div>';
    $("trash-empty").addEventListener("click", emptyTrash);
    loadTrash();
  }
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

  // plain ones come with every theme; the rest are the theme's "wallpapers" download
  var WALLPAPERS = window.PhilWalls.list;
  function themeWallpapers(themeId) {
    var t = THEMES[themeId || st.settings.theme] || THEMES.win95;
    return t.wall.map(function (id) { return Object.assign({ id: id }, WALLPAPERS[id]); });
  }
  function wallpapersAllowed(themeId) {
    var t = st.themes.find(function (x) { return x.id === (themeId || st.settings.theme); });
    return !t || t.wallpapers;
  }
  function applyWallpaper(id, target) {
    target = target || desk;
    var art = target.querySelector("#wallart") || target.querySelector(".wallart");
    var w = WALLPAPERS[id] || WALLPAPERS.teal;
    target.className = target.className.replace(/\bwp-\S+/g, "").trim() + " wp-" + id;
    target.style.setProperty("background", w.bg || "#008080", "important");
    if (art) art.innerHTML = w.art ? w.art(target.clientWidth, target.clientHeight) : "";
    st.wallpaper = id;
  }

  function controlPanel(body, el, opts) {
    var tabs = [["themes", "Themes"], ["wallpaper", "Wallpaper"], ["you", "You"], ["saver", "Screen Saver"], ["sounds", "Sounds"], ["about", "About"]];
    var cur = opts.tab || "themes", draft = Object.assign({}, st.settings);
    // You: the name Philibert calls you, the Internet switch, and the band's currency and
    // measurements. They live with the app (config) and in the band file, not desktop.json.
    var you = null, youWas = null, UNITS = { imperial: "Imperial (feet and inches, pounds, miles)", metric: "Metric (metres, kilograms, kilometres)" };
    Promise.all([api("/api/desktop", { op: "you" }).catch(function () { return {}; }),
                 api("/api/band", { op: "settings" }).catch(function () { return {}; })]).then(function (r) {
      var bs = (r[1] && r[1].settings) || {};
      you = { user_name: r[0].user_name || "", online: !!r[0].online, currency: bs.currency || "USD", units: bs.units || "imperial",
              currencies: (r[1] && r[1].currencies) || ["USD"] };
      youWas = JSON.stringify(you);
      if (cur === "you") draw();
    });
    body.innerHTML = '<div style="display:flex;flex-direction:column;height:100%"><div class="tabs">' +
      tabs.map(function (t) { return '<button class="tab' + (t[0] === cur ? " on" : "") + '" data-tab="' + t[0] + '">' + t[1] + "</button>"; }).join("") +
      '</div><div class="tabpanel" id="cp-panel"></div><div class="dlg-foot"><button class="btn" data-ok>OK</button>' +
      '<button class="btn" data-cancel>Cancel</button><button class="btn" data-apply>Apply</button></div></div>';
    var panel = body.querySelector("#cp-panel");
    function monitor(wp) {
      return '<div class="monitor raised"><div class="scr sunk"><div class="mini wp-' + wp + '"><div class="wallart" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center"></div></div></div><div class="base raised"></div></div>';
    }
    function draw() {
      if (cur === "themes") {
        panel.innerHTML = monitor(draft.wallpaper) + "<div>Theme:</div><div class=\"listbox well\">" + st.themes.map(function (t) {
          return '<div data-theme="' + t.id + '" class="' + (t.id === draft.theme ? "on" : "") + (t.ready ? "" : " off") + '">' +
                 esc(t.name) + (t.ready ? "" : " (coming soon)") + "</div>";
        }).join("") + "</div>" + (draft.theme !== st.settings.theme ? "<div style=\"margin-top:6px\">Philibert restarts its desktop to change the theme.</div>" : "");
      } else if (cur === "wallpaper") {
        var allowed = wallpapersAllowed(draft.theme);
        panel.innerHTML = monitor(draft.wallpaper) + "<div>Wallpaper:</div><div class=\"listbox well\">" + themeWallpapers(draft.theme).map(function (w) {
          var ok = w.plain || allowed;
          return '<div data-wp="' + w.id + '" class="' + (w.id === draft.wallpaper ? "on" : "") + (ok ? "" : " off") + '">' + esc(w.name) +
                 (ok ? "" : " (not installed)") + "</div>";
        }).join("") + "</div>";
      } else if (cur === "you") {
        if (!you) { panel.innerHTML = "<div>Loading...</div>"; return; }
        var curs = you.currencies.indexOf(you.currency) < 0 ? [you.currency].concat(you.currencies) : you.currencies;
        panel.innerHTML =
          '<div class="field"><label>Your name: <input data-you="user_name" maxlength="40" style="width:170px" value="' + esc(you.user_name) + '"></label></div>' +
          '<div class="field" style="margin-top:-4px">Philibert calls you this in the chat.</div>' +
          '<div class="field"><label><input type="checkbox" data-you="online"' + (you.online ? " checked" : "") +
          "> Let Philibert use the Internet</label></div>" +
          '<div class="field" style="margin-top:-4px">Web search, web pages, box art and updates. Off, nothing leaves this computer.</div>' +
          '<div class="field"><label>Money in: <select data-you="currency">' + curs.map(function (c) {
            return "<option" + (c === you.currency ? " selected" : "") + ">" + c + "</option>"; }).join("") + "</select></label></div>" +
          '<div class="field"><label>Measurements: <select data-you="units">' + Object.keys(UNITS).map(function (u) {
            return '<option value="' + u + '"' + (u === you.units ? " selected" : "") + ">" + UNITS[u] + "</option>"; }).join("") + "</select></label></div>" +
          '<div class="field">The Band Manager and the chat use these.</div>';
      } else if (cur === "saver") {
        panel.innerHTML = '<div class="field"><b>Philibert Constellation</b> - your notes drawn as stars.</div>' +
          '<div class="field"><label><input type="checkbox" data-k="screensaver"' + (draft.screensaver ? " checked" : "") + "> Use the screen saver</label></div>" +
          '<div class="field"><label>Wait: <input type="number" min="1" max="60" style="width:52px" data-k="saver_minutes" value="' + draft.saver_minutes + '"> minutes</label></div>' +
          '<div class="field"><button class="btn" data-preview>Preview</button></div>';
      } else if (cur === "sounds") {
        var t = st.themes.find(function (x) { return x.id === draft.theme; }) || {};
        panel.innerHTML = '<div class="field"><label><input type="checkbox" data-k="sounds"' + (draft.sounds ? " checked" : "") + (t.sounds === false ? " disabled" : "") +
          "> Play sounds</label></div>" + (t.sounds === false ? '<div class="field">This theme was installed without its sounds.</div>' : "") +
          '<div class="field"><label><input type="checkbox" data-k="boot"' + (draft.boot ? " checked" : "") + "> Show the start-up screen</label></div>" +
          '<div class="field">Try them: ' + ["startup", "ding", "open", "close", "error", "shutdown"].map(function (s) {
            return '<button class="btn" style="min-width:0;margin:2px" data-try="' + s + '">' + s + "</button>";
          }).join("") + "</div>";
      } else {
        panel.innerHTML = '<div style="display:flex;gap:14px;align-items:center;margin-bottom:12px">' + I.p1(56, "#000080", "#c0c0c0") +
          '<div><div style="font:bold 20px Montserrat,var(--ui-font);font-style:italic">' + esc((THEMES[draft.theme] || THEMES.win95).name) + "</div>" +
          "<div>by Esteef.Ai</div></div></div>" +
          '<div class="field">Edition: <b>Full</b> (the desktop)</div>' +
          '<div class="field" id="about-ver">Version: ...</div>' +
          '<div class="field">Everything runs from this drive. Your notes, chats and settings stay on it.</div>' +
          '<div class="field"><img src="/live/esteef-ai-e3.svg" alt="Esteef.Ai" style="height:28px"></div>';
        api("/api/philibert/version", {}).then(function (v) { var e = $("about-ver"); if (e) e.textContent = "Version: " + (v.version || "?"); }).catch(function () {});
      }
      var mini = panel.querySelector(".mini");
      if (mini) { mini.style.width = desk.clientWidth + "px"; mini.style.height = desk.clientHeight + "px";
                  mini.style.transform = "scale(" + 150 / desk.clientWidth + "," + 110 / desk.clientHeight + ")";
                  applyWallpaper(draft.wallpaper, mini); }
    }
    body.addEventListener("click", function (ev) {
      var t = ev.target.closest("[data-tab]");
      if (t) { cur = t.dataset.tab; body.querySelectorAll(".tab").forEach(function (b) { b.classList.toggle("on", b === t); }); draw(); return; }
      var th = ev.target.closest("[data-theme]");
      if (th && !th.classList.contains("off")) {
        draft.theme = th.dataset.theme;
        draft.wallpaper = (themeWallpapers(draft.theme)[0] || { id: "teal" }).id;   // each theme starts on its own
        draw();
      }
      var wp = ev.target.closest("[data-wp]");
      if (wp && !wp.classList.contains("off")) { draft.wallpaper = wp.dataset.wp; draw(); }
      var tr = ev.target.closest("[data-try]");
      if (tr) { var was = S.enabled; S.enabled = true; S.play(tr.dataset.try); S.enabled = was; }
      if (ev.target.closest("[data-preview]")) startSaver();
      if (ev.target.closest("[data-ok]")) { apply(); close("control"); }
      if (ev.target.closest("[data-apply]")) apply();
      if (ev.target.closest("[data-cancel]")) close("control");
    });
    body.addEventListener("input", function (ev) {
      var y = ev.target.dataset.you;
      if (y && you) you[y] = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
    });
    body.addEventListener("change", function (ev) {
      var y = ev.target.dataset.you;
      if (y && you) { you[y] = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value; return; }
      var k = ev.target.dataset.k;
      if (!k) return;
      draft[k] = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
    });
    function apply() {
      var ch = { theme: draft.theme, wallpaper: draft.wallpaper, screensaver: !!draft.screensaver,
                 saver_minutes: +draft.saver_minutes || 10, sounds: !!draft.sounds, boot: !!draft.boot };
      var newTheme = ch.theme !== st.settings.theme;
      if (newTheme) ch.parked = (st.settings.parked || []).concat(Object.keys(st.wins)).filter(function (id, i, a) {
        return id !== "control" && a.indexOf(id) === i;
      });
      var jobs = [save(ch)];
      if (you && JSON.stringify(you) !== youWas) {
        jobs.push(api("/api/set_config", { user_name: String(you.user_name || "").trim().slice(0, 40), online: !!you.online }));
        jobs.push(api("/api/band", { op: "settings_save", settings: { currency: you.currency, units: you.units } }));
        youWas = JSON.stringify(you);
      }
      Promise.all(jobs).then(function () {
        if (newTheme) location.reload();       // a new theme boots like the real thing
        else applySettings();
      });
    }
    draw();
  }

  /* ================= the Esteef.Ai App Store ================= */
  // Adding an app puts its icon on the desktop; removing one only takes the icon away -
  // nothing made with it is deleted. The core (Chat, the Store, Control Panel, Trash) stays.
  function storeWin(body) {
    body.innerHTML = '<div class="store"><div class="st-head">' + I.svg("store", 32) +
      "<div><b>Esteef.Ai App Store</b><span>Add the apps you want on your desktop. Removing one only takes its icon away - " +
      "nothing you made with it is deleted, and you can add it back any time.</span></div></div>" +
      '<div class="st-list well" id="st-list">Loading...</div>' +
      '<div class="st-upd raised"><span class="ico-wrap">' + I.svg("settings", 24) + '</span><div class="msg"><b>Philibert updates</b>' +
      '<span id="st-ver">Checking which version this drive has...</span></div><button class="btn" id="st-update">Update...</button></div></div>';
    api("/api/philibert/version", {}).then(function (v) {
      var e = $("st-ver");
      if (e) e.textContent = "This drive has version " + (v.version || "?") + ". Updating uses the Internet; your chats, notes and models are kept.";
    }).catch(function () { var e = $("st-ver"); if (e) e.textContent = "Updating uses the Internet; your chats, notes and models are kept."; });
    $("st-update").addEventListener("click", function () { updatePhilibert(this); });
    drawStore();
  }
  function drawStore() {
    api("/api/desktop", { op: "store" }).then(function (d) {
      var el = $("st-list");
      if (!el) return;
      el.innerHTML = (d.apps || []).map(function (a) {
        var needs = a.id === "vault" && !st.retro;
        return '<div class="st-app"><div class="st-ico">' + I.svg(a.id, 32) + '</div><div><b>' + esc(a.name) + "</b>" +
          (a.installed ? ' <span class="on">&#10003; on your desktop</span>' : "") + '<div class="about">' + esc(a.about) +
          (needs ? " <i>Needs the Retro Vault option from Philibert Setup.</i>" : "") + "</div></div>" +
          (a.installed ? '<button class="btn" data-st-rm="' + esc(a.id) + '">Remove</button>'
                       : '<button class="btn" data-st-add="' + esc(a.id) + '"' + (needs ? " disabled" : "") + ">Add</button>") + "</div>";
      }).join("");
      el.onclick = function (ev) {
        var add = ev.target.closest("[data-st-add]"), rm = ev.target.closest("[data-st-rm]");
        if (!add && !rm) return;
        var id = (add || rm).dataset[add ? "stAdd" : "stRm"];
        if (rm) close(id);
        api("/api/desktop", { op: add ? "store_add" : "store_remove", id: id }).then(function (r) {
          if (!r.ok) { msgbox("App Store", r.msg || "That did not work.", "error"); return; }
          st.installed = r.installed;
          if (add) S.play("ding");
          renderIcons(); renderTasks(); drawStore();
        });
      };
    });
  }
  // a private copy: GitHub's device sign-in, the code shown right in the Store
  function githubSignin(msg) {
    return api("/api/philibert/github_start", {}).then(function (s) {
      if (!s.ok) { msg.textContent = s.message || "Could not start signing in to GitHub."; return false; }
      msg.innerHTML = "This copy is shared privately, so updating needs your GitHub sign-in. A GitHub page has opened (if not, go to " +
        esc(s.uri) + ") - type this code there: <b class=\"st-code\">" + esc(s.user_code) + "</b>";
      var until = Date.now() + 15 * 60 * 1000, wait = (s.interval || 5) * 1000;
      return new Promise(function (done) {
        (function poll() {
          if (Date.now() > until) { msg.textContent = "The GitHub code expired. Press Update to try again."; done(false); return; }
          setTimeout(function () {
            api("/api/philibert/github_poll", {}).then(function (p) {
              if (p.state === "ok") done(true);
              else if (p.state === "slow_down") { wait += 5000; poll(); }
              else if (p.state === "pending") poll();
              else { msg.textContent = p.message || "GitHub sign-in did not finish."; done(false); }
            }).catch(poll);
          }, wait);
        })();
      });
    });
  }
  function updatePhilibert(b) {
    var msg = $("st-ver");
    if (!confirm("Check for a newer version of Philibert and install it?\n\nThis uses the Internet. Your chats, notes and models are not touched.")) return;
    b.disabled = true; msg.textContent = "Checking for a newer version...";
    var run = function () { return api("/api/philibert/update", {}).catch(function (e) { return { ok: false, message: String(e) }; }); };
    run().then(function (r) {
      if (!r.need_signin) return r;
      return githubSignin(msg).then(function (ok) { if (!ok) return null; msg.textContent = "Updating..."; return run(); });
    }).then(function (r) {
      b.disabled = false;
      if (!r) return;
      msg.textContent = r.message || (r.ok ? "Done." : "The update did not work.");
      if (r.ok) S.play("ding");
    });
  }

  /* ================= Group Board: news on the desktop ================= */
  // Once a minute (the board only answers while the Internet is on): a badge on the
  // board's icon with how many new posts and replies there are, and a pop-up by the tray
  // for ones not shown yet. Opening the board marks them read (it tells the server).
  var boardShown = 0;
  function boardNews() {
    if (!has("board")) return;
    api("/api/board", { op: "changes_all" }).then(function (d) {
      if (!d || !d.ok) return;
      var items = d.items || [];
      var ic = iconsEl.querySelector('[data-id="board"] .img');
      if (ic) {
        var b = ic.querySelector(".badge");
        if (!items.length) { if (b) b.remove(); }
        else { if (!b) { b = document.createElement("span"); b.className = "badge"; ic.appendChild(b); } b.textContent = items.length > 9 ? "9+" : items.length; }
      }
      var fresh = items.filter(function (i) { return i.at > boardShown; });
      if (!fresh.length) return;
      boardShown = Math.max.apply(null, fresh.map(function (i) { return i.at; }));
      var last = fresh[fresh.length - 1];
      notify("Group Board" + (last.group_name ? " \u00b7 " + last.group_name : ""), fresh.length === 1 ? last.by + " posted in \u201c" + last.title + "\u201d"
                                               : fresh.length + " new posts - latest from " + last.by, function () { open("board"); });
    }).catch(function () {});
  }
  function notify(title, text, onClick) {
    var n = document.createElement("div");
    n.className = "notify raised";
    n.innerHTML = "<b>" + esc(title) + "</b><span>" + esc(text) + "</span>";
    n.addEventListener("click", function () { n.remove(); if (onClick) onClick(); });
    document.body.appendChild(n);
    S.play("ding");
    setTimeout(function () { n.remove(); }, 9000);
  }
  setInterval(boardNews, 60000);
  setTimeout(boardNews, 8000);
  window.addEventListener("message", function (ev) {        // the board page: "I've shown everything"
    if (ev.origin === location.origin && ev.data === "board-seen") boardNews();
  });

  /* ================= parked windows ================= */
  // Changing the theme reloads the page (it boots like the real thing), so the windows that
  // were open wait in the tray by the clock, highlighted, until they are clicked.
  var parkedEl = $("parked");
  function renderParked() {
    var ids = (st.settings.parked || []).filter(function (id) { return appById(id); });
    parkedEl.innerHTML = ids.map(function (id) {
      var a = appById(id);
      return '<button type="button" data-id="' + esc(id) + '" title="' + esc(a.name) + ' - parked when the theme changed. Click to open it.">' +
             iconHtml(a, 16) + (parkedEl.classList.contains("float") ? "<span>" + esc(a.name) + "</span>" : "") + "</button>";
    }).join("");
  }
  parkedEl.addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-id]");
    if (!b) return;
    var id = b.dataset.id;
    save({ parked: (st.settings.parked || []).filter(function (x) { return x !== id; }) }).then(renderParked);
    b.remove();
    open(id);
  });
  function placeParked(shell) {
    parkedEl.classList.toggle("float", shell !== "taskbar" && shell !== "menubar");
    if (shell === "taskbar") $("tray").insertBefore(parkedEl, $("clock"));
    else if (shell === "menubar") $("mb-right").insertBefore(parkedEl, $("mb-clock"));
    else document.body.appendChild(parkedEl);
  }

  /* ================= screen saver: Philibert Constellation ================= */
  var saver = $("saver"), idleAt = Date.now(), saverOn = false, saverRaf = 0;
  function startSaver() {
    if (saverOn) return;
    saverOn = true;
    saver.hidden = false;
    var ctx = saver.getContext("2d"), w, h, stars = [], links = [], t0 = performance.now(), armedAt = Date.now();
    function size() { w = saver.width = innerWidth; h = saver.height = innerHeight; }
    size();
    api("/api/notes", { op: "tree" }).then(function (d) {
      var notes = (d.notes || []).slice(0, 220);
      var byTitle = {};
      notes.forEach(function (n, i) { byTitle[n.title.toLowerCase()] = i; });
      notes.forEach(function (n) {
        stars.push({ x: (Math.random() - 0.5) * 2, y: (Math.random() - 0.5) * 2, z: Math.random() * 1 + 0.15,
                     t: n.title, hue: 180 + (n.folder.length * 37) % 140 });
      });
      for (var i = 0; i < 160; i++) stars.push({ x: (Math.random() - 0.5) * 2, y: (Math.random() - 0.5) * 2, z: Math.random() + 0.1, dust: true });
      for (var j = 1; j < notes.length; j++) if (notes[j].folder === notes[j - 1].folder) links.push([j - 1, j]);
    }).catch(function () {
      for (var i = 0; i < 200; i++) stars.push({ x: (Math.random() - 0.5) * 2, y: (Math.random() - 0.5) * 2, z: Math.random() + 0.1, dust: true });
    });
    function frame(now) {
      if (!saverOn) return;
      var dt = Math.min(0.05, (now - (frame.last || now)) / 1000);
      frame.last = now;
      ctx.fillStyle = "rgba(0,0,8,0.35)";
      ctx.fillRect(0, 0, w, h);
      var cx = w / 2, cy = h / 2, f = Math.min(w, h) * 0.55, pts = [];
      stars.forEach(function (s, i) {
        s.z -= dt * (s.dust ? 0.12 : 0.07);
        if (s.z < 0.08) { s.z = 1.15; s.x = (Math.random() - 0.5) * 2; s.y = (Math.random() - 0.5) * 2; }
        var px = cx + s.x / s.z * f, py = cy + s.y / s.z * f, a = Math.min(1, (1.15 - s.z) * 1.4);
        pts[i] = [px, py, a];
        if (s.dust) { ctx.fillStyle = "rgba(180,220,255," + a * 0.7 + ")"; ctx.fillRect(px, py, 1.5, 1.5); return; }
        var r = Math.min(5, Math.max(1.2, 3.2 / s.z));
        ctx.fillStyle = "hsla(" + s.hue + ",100%,70%," + a + ")";
        ctx.beginPath(); ctx.arc(px, py, r, 0, 6.283); ctx.fill();
        if (s.z < 0.45 && a > 0.4) {
          ctx.fillStyle = "rgba(220,240,255," + (a * 0.8) + ")";
          ctx.font = Math.round(Math.min(16, 9 + 2 / s.z)) + "px Montserrat, sans-serif";
          ctx.fillText(s.t, px + r + 4, py + 4);
        }
      });
      ctx.lineWidth = 1;
      links.forEach(function (l) {
        var a = pts[l[0]], b = pts[l[1]];
        if (!a || !b || Math.hypot(a[0] - b[0], a[1] - b[1]) > f * 0.5) return;
        ctx.strokeStyle = "rgba(0,242,254," + Math.min(a[2], b[2]) * 0.25 + ")";
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      });
      // the boombox drifts by now and then
      var k = ((now - t0) / 1000 % 40) / 40;
      if (k < 0.3) {
        ctx.globalAlpha = Math.sin(k / 0.3 * Math.PI) * 0.5;
        ctx.drawImage(boomImg, w * (1.1 - k * 4), h * 0.7 - 40, 80, 80);
        ctx.globalAlpha = 1;
      }
      saverRaf = requestAnimationFrame(frame);
    }
    ctx.fillStyle = "#000"; ctx.fillRect(0, 0, w, h);
    saverRaf = requestAnimationFrame(frame);
    function stop(ev) {
      if (Date.now() - armedAt < 600) return;          // the click that started a preview
      if (ev.type === "pointermove" && Math.abs(ev.movementX) + Math.abs(ev.movementY) < 3) return;
      saverOn = false;
      cancelAnimationFrame(saverRaf);
      saver.hidden = true;
      idleAt = Date.now();
      ["pointermove", "pointerdown", "keydown"].forEach(function (t) { removeEventListener(t, stop, true); });
    }
    ["pointermove", "pointerdown", "keydown"].forEach(function (t) { addEventListener(t, stop, true); });
    addEventListener("resize", size, { once: true });
  }
  var boomImg = new Image();
  boomImg.src = "data:image/svg+xml;utf8," + encodeURIComponent(I.p1(80, "#00f2fe", "#000008").replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" '));
  ["pointermove", "pointerdown", "keydown", "wheel"].forEach(function (t) {
    addEventListener(t, function () { idleAt = Date.now(); }, { passive: true, capture: true });
  });
  setInterval(function () {
    // a window with a page in it does not report activity here; count focus inside it as activity
    if (document.activeElement && document.activeElement.tagName === "IFRAME" && document.hasFocus()) idleAt = Date.now();
    if (st.settings.screensaver && !saverOn && Date.now() - idleAt > (st.settings.saver_minutes || 10) * 60000) startSaver();
  }, 5000);

  /* ================= the Dock (macOS) and the phone home screen's dock ================= */
  var DOCK = ["chat", "notes", "band", "vault", "suite", "control", "trash"];
  function renderDock() {
    var t = T(), apps = DOCK.filter(function (id) { return appById(id); });
    if (t.shell === "phone") apps = apps.filter(function (id) { return ["chat", "notes", "band", "vault"].indexOf(id) >= 0; });
    var mins = t.dock ? Object.keys(st.wins).filter(function (id) { return st.wins[id].classList.contains("min"); }) : [];
    $("dock").innerHTML = apps.map(function (id) {
      var a = appById(id);
      return '<button class="dk' + (st.wins[id] ? " running" : "") + '" data-id="' + id + '" title="' + esc(a.name) + '"><span class="tile t-' + id + '">' +
             iconHtml(a, 40) + "</span>" + (t.shell === "phone" ? "" : '<i class="dot"></i>') + "</button>";
    }).join("") + (mins.length ? '<span class="dksep"></span>' + mins.map(function (id) {
      var w = winInfo(id);
      return '<button class="dk min" data-id="' + id + '" title="' + esc(w.title) + '"><span class="tile">' + w.ico.replace(/width="16" height="16"/, 'width="40" height="40"') + "</span></button>";
    }).join("") : "");
  }
  $("dock").addEventListener("click", function (ev) {
    var b = ev.target.closest(".dk");
    if (!b) return;
    var id = b.dataset.id;
    if (st.wins[id] && st.wins[id].classList.contains("min")) { restore(id); focus(id); }
    else if (st.wins[id] && st.active === id && T().shell !== "phone") minimize(id);
    else open(id);
    renderDock();
  });

  /* ================= phones: status bar, home, back, recent apps ================= */
  function goHome() { Object.keys(st.wins).forEach(function (id) { st.wins[id].classList.add("min"); }); st.active = null; renderTasks(); }
  function phoneTick() {
    $("ph-time").textContent = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }).replace(/\s?[AP]M$/i, "");
  }
  setInterval(phoneTick, 15000);
  phoneTick();
  $("ph-home").addEventListener("click", goHome);
  $("ph-bar").addEventListener("click", goHome);
  $("ph-back").addEventListener("click", function () { if (st.active) { minimize(st.active); } });
  $("ph-recents").addEventListener("click", function () {
    var ids = Object.keys(st.wins), r = $("ph-cards");
    if (!r.hidden) { r.hidden = true; return; }
    r.innerHTML = (ids.length ? ids.map(function (id) {
      var w = winInfo(id);
      return '<div class="card" data-id="' + id + '"><div class="ct">' + w.ico + "<span>" + esc(w.title) + '</span><button data-x="' + id + '" aria-label="Close">&#10005;</button></div><div class="cb"></div></div>';
    }).join("") : '<p class="none">No recent apps</p>') + (ids.length ? '<button class="clearall">Clear all</button>' : "");
    r.hidden = false;
  });
  $("ph-cards").addEventListener("click", function (ev) {
    var x = ev.target.closest("[data-x]"), c = ev.target.closest(".card"), r = $("ph-cards");
    if (ev.target.closest(".clearall")) { Object.keys(st.wins).forEach(close); r.hidden = true; return; }
    if (x) { close(x.dataset.x); r.hidden = true; return; }
    if (c) { restore(c.dataset.id); focus(c.dataset.id); r.hidden = true; return; }
    r.hidden = true;
  });

  /* ================= the Commodore 64: load a program from the disk listing ================= */
  var c64sel = 0;
  function c64name(a) { return a.name.toUpperCase().replace(/[^A-Z0-9 .!-]/g, "").slice(0, 16); }
  function renderC64() {
    var apps = allApps();
    var blocks = function (i) { return String(12 + (i * 37) % 180).padEnd(5, " "); };
    $("c64-list").innerHTML = '<p>LOAD"$",8</p><p>SEARCHING FOR $</p><p>LOADING</p><p>READY.</p><p>LIST</p><p>&nbsp;</p>' +
      '<p class="inv">0 "PHILIBERT DISK  " ES 2A</p>' +
      apps.map(function (a, i) {
        return '<p class="prg' + (i === c64sel ? " sel" : "") + '" data-id="' + esc(a.id) + '" data-i="' + i + '">' + blocks(i) +
               '"' + esc(c64name(a)) + '"' + " ".repeat(Math.max(1, 17 - c64name(a).length)) + "PRG</p>";
      }).join("") + "<p>" + (664 - apps.length * 23) + " BLOCKS FREE.</p><p>READY.</p>" +
      '<p id="c64-type"></p><p class="c64-cur">&#9608;</p>' +
      '<p class="hint">CLICK A PROGRAM, OR USE THE ARROW KEYS AND RETURN. RUN/STOP (ESC) GOES BACK.</p>';
  }
  function c64run(id) {
    var a = appById(id);
    if (!a) return;
    var line = 'LOAD"' + c64name(a) + '",8,1', ty = $("c64-type"), n = 0;
    ty.textContent = "";
    var iv = setInterval(function () {
      n++;
      ty.textContent = line.slice(0, n);
      if (n >= line.length) {
        clearInterval(iv);
        ty.innerHTML = esc(line) + "<br>SEARCHING FOR " + esc(c64name(a)) + "<br>LOADING<br>READY.<br>RUN";
        $("c64").classList.add("loading");
        setTimeout(function () { $("c64").classList.remove("loading"); ty.textContent = ""; open(id); }, 700);
      }
    }, 28);
  }
  $("c64-list").addEventListener("click", function (ev) {
    var p = ev.target.closest(".prg");
    if (p) { c64sel = +p.dataset.i; renderC64(); c64run(p.dataset.id); }
  });
  addEventListener("keydown", function (ev) {
    if (T().shell !== "c64") return;
    if (st.active && !st.wins[st.active].classList.contains("min")) {
      if (ev.key === "Escape") { minimize(st.active); renderC64(); }
      return;
    }
    var n = allApps().length;
    if (ev.key === "ArrowDown") { c64sel = (c64sel + 1) % n; renderC64(); ev.preventDefault(); }
    if (ev.key === "ArrowUp") { c64sel = (c64sel + n - 1) % n; renderC64(); ev.preventDefault(); }
    if (ev.key === "Enter") c64run(allApps()[c64sel].id);
  });

  /* ================= settings & start ================= */
  function applySettings() {
    var s = st.settings;
    var t = st.themes.find(function (x) { return x.id === s.theme; }) || {};
    S.enabled = !!s.sounds && t.sounds !== false;
    var loaded = applyTheme();
    var wp = s.wallpaper, mine = themeWallpapers();
    if (!mine.some(function (w) { return w.id === wp && (w.plain || wallpapersAllowed()); })) {
      wp = (mine.find(function (w) { return w.plain || wallpapersAllowed(); }) || { id: "teal" }).id;
    }
    applyWallpaper(wp);
    renderTasks();
    return loaded;
  }

  /* Each theme's start-up screen, in its era's idiom - our own drawing every time. */
  var BOOTS = {
    clouds: function (t) {
      return '<div class="boot-sky"><i class="cl c1"></i><i class="cl c2"></i><i class="cl c3"></i><i class="cl c4"></i><i class="cl c5"></i></div>' +
        '<div class="boot-logo"><span class="boot-mark">' + I.p1(120, "#fff", "#2a6ad8") + '</span>' +
        '<div class="boot-word"><b>Philibert</b><span>' + t.ver + "</span></div></div>" +
        '<div class="boot-by">Esteef<b>.Ai</b></div><div class="boot-bar"><i></i></div>';
    },
    me: function (t) {
      return '<div class="boot-sky me"></div><div class="boot-logo"><span class="boot-mark">' + I.p1(120, "#fff", "#3a5a8a") + "</span>" +
        '<div class="boot-word"><b>Philibert</b><span>Me</span></div></div><div class="boot-by">Esteef<b>.Ai</b> · Millennium Edition</div>' +
        '<div class="boot-bar"><i></i></div>';
    },
    xp: function () {
      return '<div class="xp-boot"><div class="xp-logo">' + I.p1(70, "#fff", "#000") + '<div><span class="xp-e">Esteef.Ai</span>' +
        '<div class="xp-word"><i>philibert</i><sup>xp</sup></div></div></div><div class="xp-bar"><i></i><i></i><i></i></div>' +
        '<div class="xp-foot">Esteef.Ai</div></div>';
    },
    w311: function () {
      return '<div class="w311-boot"><div class="w311-box">' + I.p1(96, "#000080", "#fff") + '<div><div class="w311-a">Philibert</div>' +
        '<div class="w311-b">for Workgroups</div><div class="w311-c">Version 3.11</div></div></div>' +
        '<div class="w311-by">Esteef.Ai &nbsp;·&nbsp; Your assistant, on a drive</div></div>';
    },
    sys7: function () {
      return '<div class="mac-boot sys7"><div class="mac-happy">' + I.p1(64, "#000", "#fff") + '</div>' +
        '<div class="mac-welcome"><b>Welcome to Philibert</b><span>Esteef.Ai</span></div></div>';
    },
    os8: function (t) {
      return '<div class="mac-boot os8"><div class="mac-splash">' + I.p1(72, "#3a3a8a", "#fff") +
        '<div class="mac-name">Philibert OS ' + t.ver + '</div><div class="mac-by">Esteef.Ai</div>' +
        '<div class="mac-prog"><i></i></div><div class="mac-starting">Starting Up…</div></div></div>';
    },
    w11: function () {
      return '<div class="w11-boot">' + I.p1(110, "#3c8cff", "#000") + '<div class="w11-spin"><i></i><i></i><i></i><i></i><i></i></div>' +
        '<div class="w11-by">Philibert 11 &middot; Esteef.Ai</div></div>';
    },
    macos: function () {
      return '<div class="mod-boot">' + I.p1(110, "#fff", "#000") + '<div class="mod-bar"><i></i></div></div>';
    },
    ios: function () {
      return '<div class="mod-boot">' + I.p1(120, "#fff", "#000") + '<div class="mod-by">Philibert &middot; Esteef.Ai</div></div>';
    },
    android: function () {
      return '<div class="and-boot"><div class="and-dots"><i></i><i></i><i></i><i></i></div><div class="and-word">Philibert</div>' +
        '<div class="mod-by">by Esteef.Ai</div></div>';
    },
    redhat: function () {
      var steps = ["Mounting the Philibert drive", "Checking your notes vault", "Starting the model server", "Starting Philibert Chat",
                   "Bringing up the desktop"];
      return '<div class="rh-boot"><p class="rh-w">Welcome to <b>Philibert</b> Linux</p><p>Press \'I\' to enter interactive startup.</p>' +
        steps.map(function (s, i) {
          return '<p style="animation-delay:' + (0.35 + i * 0.38).toFixed(2) + 's">' + s + ':<span class="ok">[  <b>OK</b>  ]</span></p>';
        }).join("") + '<p class="rh-by" style="animation-delay:2.3s">Esteef.Ai</p></div>';
    },
    c64: function () {
      return '<div class="c64-boot"><div class="c64-scr"><p>    **** PHILIBERT 64 BASIC V2 ****</p><p> 64K RAM SYSTEM  38911 BASIC BYTES FREE</p>' +
        '<p>&nbsp;</p><p>READY.</p><p class="c64-cur">&#9608;</p></div></div>';
    },
  };
  function boot(show) {
    var t = T(), b = $("boot");
    if (!show) { S.play(t.sound); return; }
    b.innerHTML = BOOTS[t.boot](t);
    b.className = "boot-" + t.boot;
    b.hidden = false;
    b.style.opacity = "1";
    setTimeout(function () {
      b.style.transition = "opacity .5s"; b.style.opacity = "0";
      S.play(t.sound);
      setTimeout(function () { b.hidden = true; }, 520);
    }, 2800);
  }

  /* Put the chosen theme on: its stylesheet, shell, names and labels. */
  function applyTheme() {
    var id = st.settings.theme in THEMES ? st.settings.theme : "win95", t = THEMES[id];
    var css = $("theme-css"), href = "/live/desktop/" + id + ".css", loaded = Promise.resolve();
    if (css.getAttribute("href") !== href) {
      // icons are placed from the layout, so wait until the theme's CSS is in
      loaded = new Promise(function (ok) {
        css.addEventListener("load", ok, { once: true });
        css.addEventListener("error", ok, { once: true });
        setTimeout(ok, 1500);
      });
      css.setAttribute("href", href);
    }
    document.body.className = "theme-" + id + " shell-" + t.shell + " family-" + t.family + (t.dock ? " has-dock" : "");
    document.title = t.name;
    $("taskbar").hidden = t.shell !== "taskbar";
    $("menubar").hidden = t.shell !== "menubar";
    $("progman").hidden = t.shell !== "progman";
    $("phone").hidden = t.shell !== "phone";
    $("c64").hidden = t.shell !== "c64";
    $("dock").hidden = !t.dock && t.shell !== "phone";
    if (t.shell === "progman") document.querySelector("#progman .pm-body").appendChild(iconsEl);
    else desk.insertBefore(iconsEl, $("minicons"));
    if (t.shell === "menubar") renderMenubar();
    placeParked(t.shell);
    if (t.shell === "phone" || t.dock) renderDock();
    // the 64's screen sits in the desk's own layer, under the windows a program opens in
    if (t.shell === "c64") { desk.insertBefore($("c64"), winsEl); renderC64(); }
    $("start-label").textContent = id === "winxp" ? "philibert" : "Philibert";
    $("start-mark").innerHTML = id === "winxp" ? I.p1(20, "#fff", "#3c9a3c")
                              : id === "win11" ? I.p1(22, "#3c8cff", "#fff") : id === "redhat" ? I.p1(20, "#cc0000", "#f0f0f0")
                              : I.p1(18, "#000", "#c0c0c0");
    $("band-ver").textContent = t.ver;
    $("safe-text").textContent = t.family === "mac" ? "You may now unplug your Philibert drive safely."
                                                    : "It's now safe to unplug your Philibert drive.";
    return loaded;
  }

  $("start-mark").innerHTML = I.p1(18, "#000", "#c0c0c0");
  // the E3 wordmark is unreadable at tray size: a small badge from it - the E in its orbit, the node at bottom left
  $("tray-e3").innerHTML = '<svg viewBox="0 0 20 16" width="20" height="16" aria-label="Esteef.Ai">' +
    '<ellipse cx="10" cy="8" rx="8.5" ry="5.5" fill="none" stroke="#008080" stroke-width="1.6"/>' +
    '<text x="10" y="11.6" text-anchor="middle" font-family="Montserrat,Arial,sans-serif" font-weight="800" font-size="10" fill="#000">E</text>' +
    '<circle cx="3.6" cy="11.4" r="1.9" fill="#ff2e88" stroke="#000" stroke-width=".6"/></svg>';
  $("tray-e3").addEventListener("click", function () { open("control", { tab: "about" }); });
  tick();
  addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") closeMenus();
    if (ev.key === "Meta" || (ev.ctrlKey && ev.key === "Escape")) { ev.preventDefault(); startBtn.click(); }
  });
  addEventListener("resize", function () { if (!st.settings.icons || !Object.keys(st.settings.icons).length) renderIcons(); });

  api("/api/desktop", { op: "state" }).then(function (d) {
    st.settings = d.settings || {}; st.themes = d.themes || []; st.apps = d.apps || []; st.retro = !!d.retro_vault; st.imagegen = !!d.image_gen;
    st.installed = d.installed || null;
    // the modern themes get modern icons in their platform's shape; the rest stay 90s pixels
    I.style = { win11: "tile", macos: "squircle", ios: "squircle", android: "circle" }[st.settings.theme] || "pixel";
    boot(st.settings.boot !== false);
    applySettings().then(function () {
      applyWallpaper(desk.className.replace(/.*\bwp-(\S+).*/, "$1"));   // sized now the layout is final
      renderIcons();
      renderParked();
      updateTrashIcon();
    });
  }).catch(function () {
    renderIcons();
    boot(false);
  });

  window.PhilDesktop = { open: open, close: close, msgbox: msgbox, startSaver: startSaver };
})();
