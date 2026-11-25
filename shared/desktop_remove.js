  /* Philibert's desktop: select icons and take them off the desktop (dev/patching.py DESKTOP_REMOVE).
     This text replaces ND3's icon handlers (shared/desktop_remove.was.js) inside desktop.js.
     - right-click an icon > Remove from desktop, or drag it onto the Trash, or select it and press Delete
     - drag a box on an empty part of the desktop (left or right button) to select several icons;
       Ctrl+click adds or drops one; a right-button box opens the menu for what it selected
     An App Store app comes back from the App Store; an app Philibert published moves to Apps/.trash on
     the drive and shows in the Trash (DESKTOP_TRASH). Chat, the App Store, Control Panel and the Trash
     itself stay. */
  var KEEP_ICONS = ["chat", "store", "control", "trash", "code", "power"];
  function removable(id) {
    var a = appById(id);
    return !!a && (a.published || KEEP_ICONS.indexOf(id) < 0);
  }
  function selectedIds() {
    return [].map.call(iconsEl.querySelectorAll(".dicon.sel"), function (e) { return e.dataset.id; });
  }
  (function () {
    var css = document.createElement("style");
    css.id = "desktop-remove-css";
    css.textContent =
      "#icons .selbox{position:absolute;z-index:5;pointer-events:none;border:1px dotted rgba(255,255,255,.95);" +
      "background:rgba(255,255,255,.14);box-shadow:0 0 0 1px rgba(0,0,0,.35)}" +
      ".dicon.drop-target .img{outline:2px dotted #ffff80;outline-offset:3px}" +
      ".dicon.drop-target .lbl{outline:1px dotted #ffff80}";
    document.head.appendChild(css);
  })();
  // one at a time: each App Store change rewrites the drive's settings
  function removeIcons(ids) {
    var go = ids.filter(removable), keep = ids.filter(function (id) { return !removable(id); });
    if (!go.length) {
      if (keep.length) msgbox("Remove from desktop", nameList(keep) + (keep.length === 1 ? " stays" : " stay") +
        " on the desktop: Philibert needs " + (keep.length === 1 ? "it." : "them."), "info");
      return Promise.resolve();
    }
    var failed = [], published = 0;
    return go.reduce(function (p, id) {
      return p.then(function () {
        var a = appById(id);
        close(id);
        if (a.published) published++;
        return api("/api/desktop", a.published ? { op: "app_remove", id: id.slice(4) } : { op: "store_remove", id: id })
          .then(function (r) { if (!r || !r.ok) failed.push(a.name + ((r && r.msg) ? " (" + r.msg + ")" : "")); })
          .catch(function () { failed.push(a.name); });
      });
    }, Promise.resolve()).then(function () {
      return api("/api/desktop", { op: "state" }).then(function (d) {
        if (d.ok) { st.installed = d.installed; st.apps = d.apps; }
      }).catch(function () {});
    }).then(function () {
      renderIcons(); renderTasks();
      var n = go.length - failed.length;
      if (failed.length) msgbox("Remove from desktop", "These could not be removed: " + failed.join(", ") + ".", "error");
      if (n > 0) {
        S.play("close");
        notify("Desktop", (n === 1 ? "1 icon" : n + " icons") + " removed. " +
          (published < n ? "Add App Store apps back from the App Store. " : "") +
          (published ? "Apps you published are in the Trash: Put back brings them back." : "") +
          (keep.length ? " " + nameList(keep) + (keep.length === 1 ? " stays." : " stay.") : ""));
      }
      if (published) updateTrashIcon();
    });
  }
  function nameList(ids) {
    return ids.map(function (id) { var a = appById(id); return a ? a.name : id; }).join(", ");
  }
  function iconMenu(ids, x, y, anchor) {
    var can = ids.filter(removable), items;
    if (ids.length === 1) {
      var id = ids[0];
      items = [{ label: "Open", run: function () { open(id); } }, "-"];
      if (id === "trash") items.push({ label: "Empty Trash", run: emptyTrash });
      else items.push({ label: "Remove from desktop", off: !can.length, run: function () { removeIcons(ids); } });
    } else {
      items = [{ label: "Open " + ids.length + " items", run: function () { ids.forEach(function (i) { open(i); }); } }, "-",
               { label: can.length === ids.length ? "Remove " + ids.length + " from desktop"
                   : "Remove " + can.length + " of " + ids.length + " from desktop", off: !can.length,
                 run: function () { removeIcons(ids); } }];
    }
    dropMenu(anchor, items);
    fly.style.left = Math.max(0, Math.min(x, innerWidth - fly.offsetWidth - 4)) + "px";
    fly.style.top = Math.max(0, Math.min(y, innerHeight - fly.offsetHeight - 4)) + "px";
  }
  var eatMenu = false;        // the browser's own contextmenu event after a right-button box
  iconsEl.addEventListener("contextmenu", function (ev) {
    if (eatMenu) { eatMenu = false; ev.preventDefault(); return; }
    var d = ev.target.closest(".dicon");
    if (!d) return;
    ev.preventDefault();
    if (!d.classList.contains("sel")) select(d);
    iconMenu(selectedIds(), ev.clientX, ev.clientY, d);
  });
  desk.addEventListener("contextmenu", function (ev) {
    if (eatMenu) { eatMenu = false; ev.preventDefault(); }
  });
  iconsEl.addEventListener("keydown", function (ev) {
    var d = ev.target.closest(".dicon");
    if (d && ev.key === "Enter") open(d.dataset.id);
    if (d && ev.key === "Delete") { ev.preventDefault(); removeIcons(selectedIds()); }
  });
  // a box on an empty part of the desktop selects the icons it touches
  desk.addEventListener("pointerdown", function (ev) {
    closeMenus();
    var empty = ev.target === desk || ev.target === iconsEl || ev.target.id === "wallart";
    if (!empty || (ev.button !== 0 && ev.button !== 2)) return;
    var add = ev.ctrlKey || ev.metaKey, before = add ? selectedIds() : [];
    if (!add) select(null);
    var box = iconsEl.getBoundingClientRect(), sx = ev.clientX, sy = ev.clientY, band = null, right = ev.button === 2;
    function mv(e) {
      if (!band && Math.abs(e.clientX - sx) + Math.abs(e.clientY - sy) < 5) return;
      if (!band) { band = document.createElement("div"); band.className = "selbox"; iconsEl.appendChild(band); }
      var l = Math.min(sx, e.clientX), t = Math.min(sy, e.clientY), r = Math.max(sx, e.clientX), b = Math.max(sy, e.clientY);
      band.style.left = l - box.left + iconsEl.scrollLeft + "px"; band.style.top = t - box.top + iconsEl.scrollTop + "px";
      band.style.width = r - l + "px"; band.style.height = b - t + "px";
      iconsEl.querySelectorAll(".dicon").forEach(function (d) {
        var q = d.getBoundingClientRect();
        var hit = q.left < r && q.right > l && q.top < b && q.bottom > t;
        d.classList.toggle("sel", hit || before.indexOf(d.dataset.id) >= 0);
      });
    }
    function up(e) {
      removeEventListener("pointermove", mv); removeEventListener("pointerup", up);
      if (!band) return;
      band.remove();
      var ids = selectedIds();
      if (right) {
        eatMenu = true;
        setTimeout(function () { eatMenu = false; }, 400);
        if (ids.length) iconMenu(ids, e.clientX, e.clientY, iconsEl.querySelector('.dicon[data-id="' + ids[ids.length - 1] + '"]'));
      }
    }
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  });
  // drag icons around (every selected one moves together); they land on the grid and the place is
  // remembered. Dropped on the Trash, they come off the desktop.
  iconsEl.addEventListener("pointerdown", function (ev) {
    var d = ev.target.closest(".dicon");
    if (!d || ev.button !== 0) return;
    if (ev.ctrlKey || ev.metaKey) { d.classList.toggle("sel"); return; }
    if (!d.classList.contains("sel")) select(d);
    else d.focus({ preventScroll: true });
    var group = [].slice.call(iconsEl.querySelectorAll(".dicon.sel"));
    var from = group.map(function (e) { return [e.offsetLeft, e.offsetTop]; });
    var trash = iconsEl.querySelector('.dicon[data-id="trash"]');
    if (trash && group.indexOf(trash) >= 0) trash = null;        // the Trash can't go in itself
    var sx = ev.clientX, sy = ev.clientY, moved = false, over = false;
    function mv(e) {
      var dx = e.clientX - sx, dy = e.clientY - sy;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 5) return;
      moved = true;
      group.forEach(function (g, i) {
        g.classList.add("dragging");
        g.style.left = from[i][0] + dx + "px"; g.style.top = from[i][1] + dy + "px";
      });
      if (trash) {
        var q = trash.getBoundingClientRect();
        over = e.clientX >= q.left && e.clientX <= q.right && e.clientY >= q.top && e.clientY <= q.bottom;
        trash.classList.toggle("drop-target", over);
      }
    }
    function up() {
      removeEventListener("pointermove", mv); removeEventListener("pointerup", up);
      group.forEach(function (g) { g.classList.remove("dragging"); });
      if (!moved) return;
      if (over) {
        trash.classList.remove("drop-target");
        group.forEach(function (g, i) { g.style.left = from[i][0] + "px"; g.style.top = from[i][1] + "px"; });
        removeIcons(group.map(function (g) { return g.dataset.id; }));
        return;
      }
      var box = iconsEl.getBoundingClientRect(), GX = gridX(), GY = gridY();
      var icons = Object.assign({}, st.settings.icons || {}), sh = T().shell;
      icons[sh] = Object.assign({}, icons[sh] || {});
      group.forEach(function (g) {
        var x = Math.max(4, Math.min(box.width - 76, Math.round((g.offsetLeft - 8) / GX) * GX + 8));
        var y = Math.max(4, Math.min(box.height - 70, Math.round((g.offsetTop - 6) / GY) * GY + 6));
        g.style.left = x + "px"; g.style.top = y + "px";
        icons[sh][g.dataset.id] = [x, y];
      });
      save({ icons: icons });
    }
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  });
