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
