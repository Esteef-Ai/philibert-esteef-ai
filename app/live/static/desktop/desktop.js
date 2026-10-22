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
  var st = { settings: {}, themes: [], apps: [], retro: false, wins: {}, z: 10, active: null, sel: null };
  var THEME_VER = { win95: "95" };

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
  function builtins() {
    var list = [
      { id: "chat", name: "Philibert Chat", icon: "chat", url: "/live/", w: 1280, h: 800, max: true },
      { id: "notes", name: "Notes", icon: "notes", url: "/notes?embed=1", w: 1100, h: 720, title: "Philibert Notes" },
      { id: "suite", name: "ND Suite", icon: "suite", url: "/full", w: 1280, h: 800, max: true },
    ];
    if (st.retro) list.push({ id: "vault", name: "Retro Vault", icon: "vault", internal: comingVault, w: 460, h: 230 });
    list.push({ id: "band", name: "Band Manager", icon: "band", internal: comingBand, w: 460, h: 220 },
              { id: "control", name: "Control Panel", icon: "control", internal: controlPanel, w: 420, h: 470, fixed: true },
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
    var rows = Math.max(1, Math.floor((desk.clientHeight - 8) / GRID_Y));
    return [8 + Math.floor(i / rows) * GRID_X, 6 + (i % rows) * GRID_Y];
  }
  function renderIcons() {
    var saved = st.settings.icons || {};
    iconsEl.innerHTML = allApps().map(function (a, i) {
      var p = saved[a.id] || iconPos(i);
      return '<div class="dicon" role="listitem" tabindex="0" data-id="' + esc(a.id) + '" style="left:' + p[0] + "px;top:" + p[1] + 'px">' +
             '<div class="img">' + iconHtml(a, 32) + '</div><div class="lbl">' + esc(a.name) + "</div></div>";
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
      var x = Math.max(4, Math.min(desk.clientWidth - 76, Math.round((d.offsetLeft - 8) / GRID_X) * GRID_X + 8));
      var y = Math.max(4, Math.min(desk.clientHeight - 70, Math.round((d.offsetTop - 6) / GRID_Y) * GRID_Y + 6));
      d.style.left = x + "px"; d.style.top = y + "px";
      var icons = Object.assign({}, st.settings.icons || {});
      icons[d.dataset.id] = [x, y];
      save({ icons: icons });
    }
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  });

  /* ================= windows ================= */
  function open(id, opts) {
    var app = appById(id);
    if (!app) return;
    closeMenus();
    if (st.wins[id]) { restore(id); focus(id); return st.wins[id]; }
    S.play("open");
    var n = Object.keys(st.wins).length;
    var W = Math.min(app.w || 640, desk.clientWidth - 40), H = Math.min(app.h || 440, desk.clientHeight - 30);
    var x = Math.max(10, (desk.clientWidth - W) / 2 + (n % 6) * 24 - 60), y = Math.max(6, (desk.clientHeight - H) / 2 + (n % 6) * 22 - 50);
    var el = document.createElement("div");
    el.className = "win raised" + (app.max ? " max" : "");
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
    el.classList.add("min");
    el.classList.remove("active");
    if (st.active === id) st.active = null;
    renderTasks();
  }
  function restore(id) { var el = st.wins[id]; if (el) el.classList.remove("min"); }
  function toggleMax(id) { var el = st.wins[id]; if (el) el.classList.toggle("max"); }

  /* ================= taskbar ================= */
  function renderTasks() {
    tasksEl.innerHTML = Object.keys(st.wins).map(function (id) {
      var w = st.wins[id], tb = w.querySelector(".titlebar");
      var title = tb.querySelector(".tt").textContent, ico = tb.querySelector(".ico, img");
      var down = st.active === id && !w.classList.contains("min");
      return '<button class="btn task' + (down ? " down" : "") + '" data-id="' + esc(id) + '" title="' + esc(title) + '">' +
             (ico ? ico.outerHTML : "") + '<span class="tt">' + esc(title) + "</span></button>";
    }).join("");
  }
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
  }
  setInterval(tick, 10000);

  /* ================= Start menu ================= */
  var sm = $("startmenu"), fly = $("flyout"), startBtn = $("start");
  function mi(icon, label, act, sub) {
    return '<li class="mi' + (sub ? " sub" : "") + '" data-act="' + act + '">' + I.svg(icon, 24) + "<span>" + label + "</span></li>";
  }
  function renderStart() {
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
    if (!sm.contains(ev.target) && !fly.contains(ev.target) && !startBtn.contains(ev.target)) closeMenus();
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
    var li = ev.target.closest(".mi");
    if (!li) return;
    var act = li.dataset.act;
    if (act === "find") { closeMenus(); open("notes"); }
    if (act === "help") { closeMenus(); openNote("Philibert/Welcome to Philibert.md"); }
    if (act === "unload") {
      closeMenus();
      api("/api/unload_gpu", { reason: "the Start menu" }).then(function () {
        msgbox("Unload GPU", "The model is off the graphics card. It loads again the next time you ask Philibert something.", "info");
      }).catch(function () { msgbox("Unload GPU", "Could not reach Philibert.", "error"); });
    }
    if (act === "shutdown") { closeMenus(); shutdownDialog(); }
  });
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
  function comingVault(body) {
    body.innerHTML = '<div class="pad coming">' + I.svg("vault", 32) + "<div><h3>Retro Vault</h3>" +
      "<p>Your games arrive in the next update: a library with box art, play with a USB or Bluetooth controller, saves on the drive.</p>" +
      "<p>Put your own games in <b>Entertainment\\Cartridges</b>, one folder per system (for example <b>Cartridges\\SNES</b>).</p></div></div>";
  }
  function comingBand(body) {
    body.innerHTML = '<div class="pad coming">' + I.svg("band", 32) + "<div><h3>Band Manager</h3>" +
      "<p>Gigs, venues, contacts, setlists, merch and money in one place, with reminders. Coming in a later update.</p>" +
      "<p>Until then, Philibert Chat and the Gig sheet and Setlist templates in Notes cover the basics.</p></div></div>";
  }

  function trashWin(body) {
    body.innerHTML = '<div class="explorer"><div class="menubar"><span>File</span><span>Edit</span><span>View</span><span>Help</span></div>' +
      '<div class="rows well" style="margin:0 2px"><div class="row head"><span>Name</span><span>Was in</span><span>Deleted</span></div>' +
      '<div id="trash-rows"></div></div><div class="status sunk" id="trash-status">Loading...</div></div>';
    loadTrash();
  }
  function loadTrash() {
    Promise.all([api("/api/notes", { op: "trash_list" }).catch(function () { return {}; }),
                 api("/api/chats", { op: "trash_list" }).catch(function () { return {}; })]).then(function (r) {
      var rows = (r[0].items || []).map(function (n) {
        return { kind: "note", key: n.name, name: n.title, from: (n.from || "").split("/").slice(0, -1).join("/") || "Notes", at: n.at };
      }).concat((r[1].chats || []).map(function (c) {
        return { kind: "chat", key: c.id, name: c.title, from: c.folder || "Chats", at: c.updated };
      })).sort(function (a, b) { return b.at - a.at; });
      var el = $("trash-rows");
      if (!el) return;
      el.innerHTML = rows.map(function (x, i) {
        return '<div class="row" data-i="' + i + '" title="Double-click to put it back"><span class="n">' +
               I.svg(x.kind === "note" ? "notes" : "chat", 16) + esc(x.name) + "</span><span>" + esc(x.from) +
               "</span><span>" + esc(new Date(x.at * 1000).toLocaleDateString()) + "</span></div>";
      }).join("");
      $("trash-status").textContent = rows.length + " object(s). Double-click one to put it back.";
      el.ondblclick = function (ev) {
        var row = ev.target.closest("[data-i]");
        if (!row) return;
        var x = rows[+row.dataset.i];
        (x.kind === "note" ? api("/api/notes", { op: "restore", name: x.key }) : api("/api/chats", { op: "restore", id: x.key }))
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
    Promise.all([api("/api/notes", { op: "trash_list" }).catch(function () { return {}; }),
                 api("/api/chats", { op: "trash_list" }).catch(function () { return {}; })]).then(function (r) {
      setTrashIcon(((r[0].items || []).length + (r[1].chats || []).length) > 0);
    });
  }

  var WALLPAPERS = [
    { id: "teal", name: "(None) Teal", plain: true }, { id: "slate", name: "(None) Slate", plain: true },
    { id: "plum", name: "(None) Plum", plain: true }, { id: "clouds", name: "Clouds" },
    { id: "boombox", name: "Boombox" }, { id: "esteef", name: "Esteef.Ai" },
  ];
  function wallpapersAllowed() {
    var t = st.themes.find(function (x) { return x.id === st.settings.theme; });
    return !t || t.wallpapers;
  }
  function applyWallpaper(id, target) {
    target = target || desk;
    var art = target.querySelector("#wallart") || target.querySelector(".wallart");
    target.className = target.className.replace(/\bwp-\S+/g, "").trim() + " wp-" + id;
    if (art) {
      art.innerHTML = id === "boombox" ? I.p1(Math.round(Math.min(target.clientWidth, target.clientHeight) * 0.32) || 60, "#004848", "#008080")
                    : id === "esteef" ? '<img src="/live/esteef-ai-e3.svg" alt="" style="width:46%;max-width:640px;filter:drop-shadow(0 0 18px rgba(0,242,254,.35))">'
                    : "";
    }
  }

  function controlPanel(body, el, opts) {
    var tabs = [["themes", "Themes"], ["wallpaper", "Wallpaper"], ["saver", "Screen Saver"], ["sounds", "Sounds"], ["about", "About"]];
    var cur = opts.tab || "themes", draft = Object.assign({}, st.settings);
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
        }).join("") + "</div>";
      } else if (cur === "wallpaper") {
        var allowed = wallpapersAllowed();
        panel.innerHTML = monitor(draft.wallpaper) + "<div>Wallpaper:</div><div class=\"listbox well\">" + WALLPAPERS.map(function (w) {
          var ok = w.plain || allowed;
          return '<div data-wp="' + w.id + '" class="' + (w.id === draft.wallpaper ? "on" : "") + (ok ? "" : " off") + '">' + esc(w.name) +
                 (ok ? "" : " (not installed)") + "</div>";
        }).join("") + "</div>";
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
          '<div><div style="font:bold 20px Montserrat,var(--ui-font);font-style:italic">Philibert ' + (THEME_VER[draft.theme] || "") + "</div>" +
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
      if (th && !th.classList.contains("off")) { draft.theme = th.dataset.theme; draw(); }
      var wp = ev.target.closest("[data-wp]");
      if (wp && !wp.classList.contains("off")) { draft.wallpaper = wp.dataset.wp; draw(); }
      var tr = ev.target.closest("[data-try]");
      if (tr) { var was = S.enabled; S.enabled = true; S.play(tr.dataset.try); S.enabled = was; }
      if (ev.target.closest("[data-preview]")) startSaver();
      if (ev.target.closest("[data-ok]")) { apply(); close("control"); }
      if (ev.target.closest("[data-apply]")) apply();
      if (ev.target.closest("[data-cancel]")) close("control");
    });
    body.addEventListener("change", function (ev) {
      var k = ev.target.dataset.k;
      if (!k) return;
      draft[k] = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
    });
    function apply() {
      var ch = { theme: draft.theme, wallpaper: draft.wallpaper, screensaver: !!draft.screensaver,
                 saver_minutes: +draft.saver_minutes || 10, sounds: !!draft.sounds, boot: !!draft.boot };
      save(ch).then(applySettings);
    }
    draw();
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

  /* ================= settings & start ================= */
  function applySettings() {
    var s = st.settings;
    var t = st.themes.find(function (x) { return x.id === s.theme; }) || {};
    S.enabled = !!s.sounds && t.sounds !== false;
    var wp = s.wallpaper;
    if (!wallpapersAllowed() && !WALLPAPERS.some(function (w) { return w.id === wp && w.plain; })) wp = "teal";
    applyWallpaper(wp);
    var v = THEME_VER[s.theme] || "";
    $("band-ver").textContent = v; $("boot-ver").textContent = v;
  }

  function boot(show) {
    var b = $("boot");
    $("boot-mark").innerHTML = I.p1(120, "#fff", "#2a6ad8");
    if (!show) { S.play("startup"); return; }
    b.hidden = false;
    setTimeout(function () {
      b.style.transition = "opacity .5s"; b.style.opacity = "0";
      S.play("startup");
      setTimeout(function () { b.hidden = true; }, 520);
    }, 2600);
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
    st.settings = d.settings || {}; st.themes = d.themes || []; st.apps = d.apps || []; st.retro = !!d.retro_vault;
    applySettings();
    renderIcons();
    updateTrashIcon();
    boot(st.settings.boot !== false);
  }).catch(function () {
    renderIcons();
    boot(false);
  });

  window.PhilDesktop = { open: open, close: close, msgbox: msgbox, startSaver: startSaver };
})();
