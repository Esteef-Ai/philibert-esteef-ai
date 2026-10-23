/* The model picker - one for native NeuralDock's top mp-bar and for the chat page
 * (native and Philibert). It replaces a <select> on screen but keeps it underneath:
 * picking a model sets the select's value and fires "change", so the page's own
 * code goes on working. Each row says what the model is in plain words, its size,
 * score and whether it suits this computer; from the row you use it, download it
 * or delete it. Data: /api/philibert/models | pull | remove (nd_philibert.py over
 * the drive's models.json or ND's nd_models.json).
 *
 *   PhilModelPicker.attach(selectEl, { prefix: "ollama:", api: fn(path, body) })
 */
(function () {
  "use strict";
  var CSS = ".mp-btn{display:inline-flex;align-items:center;gap:8px;max-width:340px;padding:5px 10px;border-radius:6px;cursor:pointer;" +
    "background:rgba(10,20,40,.85);border:1px solid rgba(0,242,254,.35);color:#d7e3f4;font:12px 'Inter',system-ui,sans-serif;white-space:nowrap}" +
    ".mp-btn:hover{border-color:#00f2fe}.mp-btn b{color:#fff;font-weight:600;overflow:hidden;text-overflow:ellipsis}" +
    ".mp-btn i{font-style:normal;color:#8ea3c4;font:10.5px 'JetBrains Mono',Consolas,monospace;overflow:hidden;text-overflow:ellipsis}" +
    ".mp-btn::after{content:'\\25BE';color:#00f2fe;margin-left:2px}" +
    ".mp-panel{position:fixed;z-index:99999;width:min(520px,94vw);max-height:72vh;overflow:auto;background:#0d1729;border:1px solid #1e3054;" +
    "border-radius:10px;box-shadow:0 18px 50px rgba(0,0,0,.6);padding:6px;font:13px 'Inter',system-ui,sans-serif;color:#d7e3f4;text-align:left}" +
    ".mp-h{font:600 10px 'Inter',sans-serif;letter-spacing:.16em;text-transform:uppercase;color:#6f86a8;margin:10px 8px 4px}" +
    ".mp-row{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;padding:8px 10px;border-radius:7px;cursor:pointer;border:1px solid transparent}" +
    ".mp-row:hover{background:rgba(0,242,254,.06)}.mp-row.on{background:rgba(0,242,254,.12);border-color:rgba(0,242,254,.45)}" +
    ".mp-row.dl{cursor:default}.mp-row b{color:#fff;font-size:13.5px}.mp-row .mp-lb{font:10.5px 'JetBrains Mono',Consolas,monospace;color:#6f86a8;margin-left:6px}" +
    ".mp-row .mp-gf{color:#8ea3c4;font-size:11.5px;line-height:1.4;margin-top:2px}" +
    ".mp-row .mp-mt{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px;font:10.5px 'JetBrains Mono',Consolas,monospace;color:#6f86a8}" +
    ".mp-row .mp-sc{color:#a78bfa}.mp-row .mp-ft.green{color:#10b981}.mp-row .mp-ft.yellow{color:#f59e0b}.mp-row .mp-ft.red{color:#ff2e88}" +
    ".mp-row .mp-bar{height:4px;border-radius:2px;background:#162544;margin-top:5px;overflow:hidden;width:180px}.mp-row .mp-bar div{height:100%;background:#00f2fe}" +
    ".mp-acts{display:flex;gap:6px}.mp-b{font:10.5px 'JetBrains Mono',Consolas,monospace;letter-spacing:.06em;padding:5px 9px;border-radius:5px;cursor:pointer;" +
    "border:1px solid #1e3054;background:rgba(22,37,68,.6);color:#8ea3c4}.mp-b:hover{color:#00f2fe;border-color:rgba(0,242,254,.5)}" +
    ".mp-b.get{background:#00f2fe;color:#04131c;border-color:#00f2fe;font-weight:600}.mp-b.del:hover{color:#ff2e88;border-color:rgba(255,46,136,.6)}" +
    ".mp-panel *::before,.mp-panel *::after{content:none!important}.mp-panel span,.mp-panel div{box-shadow:none}" +
    ".mp-msg{font:11px 'JetBrains Mono',Consolas,monospace;color:#f59e0b;padding:6px 10px}";
  var FIT = { green: "suits this computer", yellow: "works here, slowly", red: "too big for this computer" };

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function defaultApi(path, body) {
    return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json(); });
  }
  function same(a, b) {
    var n = function (t) { t = String(t || ""); return t.split("/").pop().indexOf(":") >= 0 ? t : t + ":latest"; };
    return n(a).toLowerCase() === n(b).toLowerCase();
  }

  function attach(sel, opts) {
    if (!sel || sel.__mp) return;
    sel.__mp = true;
    opts = opts || {};
    var prefix = opts.prefix || "";
    var call = opts.api || (typeof window.api === "function" ? window.api : defaultApi);
    if (!document.getElementById("mp-css")) {
      var st = document.createElement("style"); st.id = "mp-css"; st.textContent = CSS; document.head.appendChild(st);
    }
    var btn = document.createElement("button");
    btn.type = "button"; btn.className = "mp-btn"; btn.title = "Choose, download or delete a model";
    sel.style.display = "none";
    sel.parentNode.insertBefore(btn, sel.nextSibling);
    var panel = null, data = null, poll = null, msg = "";

    function current() { var v = sel.value || ""; return v.indexOf(prefix) === 0 ? v.slice(prefix.length) : v; }
    function byTag(t) { return ((data && data.models) || []).find(function (m) { return same(m.tag, t); }); }
    function label() {
      var t = current(), m = byTag(t);
      var opt = sel.selectedOptions && sel.selectedOptions[0];
      var name = m ? (m.plain_name || m.label || t) : (opt && opt.value ? opt.textContent.replace(/^⬇\s*/, "").split("  ·")[0] : "Choose a model");
      btn.innerHTML = "<b>" + esc(name) + "</b>" + (m && m.label ? "<i>" + esc(m.label) + "</i>" : "");
    }
    function load() {
      return call("/api/philibert/models", {}).then(function (d) { data = d || {}; label(); return d; }).catch(function () { data = data || {}; label(); });
    }
    function fit(m) {
      var g = (data && data.gpu_gb) || 0, need = m.min_gpu_gb || 0;
      if (m.extra || !g) return "";
      return need <= g ? "green" : need <= g * 1.6 ? "yellow" : "red";
    }
    function row(m) {
      var p = m.pull && ["done", "error"].indexOf(m.pull.status) < 0 ? m.pull : null;
      var on = m.installed && same(m.tag, current()), f = fit(m);
      var acts = p ? '<span class="mp-lb">downloading…</span>'
        : m.installed ? (m.required ? '<span class="mp-lb">always kept</span>' : '<button class="mp-b del" data-del="' + esc(m.tag) + '">DELETE</button>')
        : '<button class="mp-b get" data-get="' + esc(m.tag) + '">DOWNLOAD ' + (m.size_gb ? m.size_gb + " GB" : "") + "</button>";
      return '<div class="mp-row' + (on ? " on" : "") + (m.installed ? "" : " dl") + '" data-use="' + (m.installed ? esc(m.tag) : "") + '" title="' + esc(m.tag) + '">' +
        "<div><b>" + esc(m.plain_name || m.label || m.tag.split("/").pop()) + '</b><span class="mp-lb">' + esc(m.label || m.tag.split("/").pop()) + "</span>" +
        (m.good_for ? '<div class="mp-gf">' + esc(m.good_for) + "</div>" : m.extra ? '<div class="mp-gf">On this computer, not in the catalog.</div>' : "") +
        '<div class="mp-mt">' + (m.size_gb ? "<span>" + m.size_gb + " GB</span>" : "") + (f ? '<span class="mp-ft ' + f + '">● ' + FIT[f] + "</span>" : "") +
        (m.score ? '<span class="mp-sc">' + esc(m.score) + "</span>" : "") + "</div>" +
        (p ? '<div class="mp-bar"><div style="width:' + (p.total ? Math.round(100 * p.done / p.total) : 0) + '%"></div></div>' : "") +
        (m.pull && m.pull.status === "error" ? '<div class="mp-gf" style="color:#ff2e88">' + esc(m.pull.error || "download failed") + "</div>" : "") +
        '</div><div class="mp-acts">' + acts + "</div></div>";
    }
    function draw() {
      if (!panel) return;
      var ms = ((data && data.models) || []).filter(function (m) { return (m.kind || "chat") === "chat" && !m.vision; });
      var eyes = ((data && data.models) || []).filter(function (m) { return m.vision && (m.kind || "chat") === "chat"; });
      var size = function (a, b) { return (a.size_gb || 0) - (b.size_gb || 0); };
      var have = ms.filter(function (m) { return m.installed; }).sort(size), get = ms.filter(function (m) { return !m.installed; }).sort(size);
      // anything else the page's own list offers (ND's custom .gguf models)
      var other = [].filter.call(sel.options, function (o) {
        var v = o.value.indexOf(prefix) === 0 ? o.value.slice(prefix.length) : o.value;
        return o.value && !byTag(v) && !o.dataset.dl;
      });
      panel.innerHTML = (msg ? '<div class="mp-msg">' + esc(msg) + "</div>" : "") +
        '<div class="mp-h">On this computer</div>' + (have.map(row).join("") || '<div class="mp-msg">No chat model yet - download one below.</div>') +
        (other.length ? '<div class="mp-h">Your own models</div>' + other.map(function (o) {
          return '<div class="mp-row' + (o.value === sel.value ? " on" : "") + '" data-opt="' + esc(o.value) + '"><div><b>' + esc(o.textContent) + "</b></div><div></div></div>";
        }).join("") : "") +
        (eyes.length ? '<div class="mp-h">Seeing pictures</div>' + eyes.map(row).join("") : "") +
        (get.length ? '<div class="mp-h">Download</div>' + get.map(row).join("") : "") +
        '<div class="mp-h"><a href="/modelmgr" target="_blank" style="color:#00f2fe;text-decoration:none">Open the Model Manager \u2192</a></div>';
    }
    function busy() { return ((data && data.models) || []).some(function (m) { return m.pull && ["done", "error"].indexOf(m.pull.status) < 0; }); }
    function refresh() {
      clearTimeout(poll);
      return load().then(function () { draw(); if (busy()) poll = setTimeout(refresh, 1500); });
    }
    function place() {
      var r = btn.getBoundingClientRect(), w = Math.min(520, innerWidth * 0.94);
      panel.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + "px";
      panel.style.top = (r.bottom + 6) + "px";
      panel.style.maxHeight = Math.max(200, innerHeight - r.bottom - 20) + "px";
    }
    function open() {
      if (panel) { close(); return; }
      panel = document.createElement("div"); panel.className = "mp-panel";
      panel.innerHTML = '<div class="mp-msg" style="color:#8ea3c4">Loading…</div>';
      document.body.appendChild(panel); place(); msg = "";
      refresh();
      panel.addEventListener("click", onClick);
    }
    function close() { if (panel) { panel.remove(); panel = null; } }
    function use(tag) {
      var v = prefix + tag;
      var have = [].some.call(sel.options, function (o) { return o.value === v; });
      if (!have) { var o = document.createElement("option"); o.value = v; o.textContent = tag; sel.appendChild(o); }
      sel.value = v;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
      label(); close();
    }
    function onClick(ev) {
      ev.stopPropagation();
      var g = ev.target.closest("[data-get]"), d = ev.target.closest("[data-del]"), u = ev.target.closest("[data-use]"), o = ev.target.closest("[data-opt]");
      if (g) {
        var m = byTag(g.dataset.get) || {};
        if (!confirm("Download " + (m.plain_name || m.label || g.dataset.get) + " (" + (m.size_gb || "?") + " GB) from the Internet?" + (m.note ? "\n\n" + m.note : ""))) return;
        g.disabled = true;
        call("/api/philibert/pull", { tag: g.dataset.get }).then(function (r) { msg = r && r.ok === false ? (r.error || r.msg || "Could not start the download.") : ""; refresh(); });
        return;
      }
      if (d) {
        var dm = byTag(d.dataset.del) || {};
        if (!confirm("Delete " + (dm.plain_name || dm.label || d.dataset.del) + " (" + (dm.size_gb || "?") + " GB) from this computer?\n\n" +
                     "It frees the space; you can download it again later.")) return;
        var was = same(d.dataset.del, current());
        call("/api/philibert/remove", { tag: d.dataset.del }).then(function (r) {
          if (r && r.ok === false) { msg = r.error || r.msg || "Could not delete it."; draw(); return; }
          msg = "";
          [].slice.call(sel.options).forEach(function (op) { if (same(op.value.slice(prefix.length), d.dataset.del)) op.remove(); });
          load().then(function () {
            if (was) {                              // it was answering: the next one on the computer takes over
              var next = ((data && data.models) || []).filter(function (x) { return x.installed && (x.kind || "chat") === "chat" && !x.vision; })
                .sort(function (a, b) { return (a.size_gb || 0) - (b.size_gb || 0); })[0];
              if (next) { var keep = panel; use(next.tag); if (keep) open(); }
            }
            draw();
            if (typeof opts.onChange === "function") opts.onChange();
          });
        });
        return;
      }
      if (o) { sel.value = o.dataset.opt; sel.dispatchEvent(new Event("change", { bubbles: true })); label(); close(); return; }
      if (u && u.dataset.use) use(u.dataset.use);
    }
    btn.addEventListener("click", function (ev) { ev.stopPropagation(); open(); });
    document.addEventListener("click", function (ev) { if (panel && !panel.contains(ev.target) && ev.target !== btn) close(); });
    addEventListener("keydown", function (ev) { if (ev.key === "Escape") close(); });
    addEventListener("resize", function () { if (panel) place(); });
    sel.addEventListener("change", label);
    new MutationObserver(label).observe(sel, { childList: true });
    setInterval(label, 2000);                     // the page may set .value without an event
    load();
    return { refresh: refresh, open: open, close: close };
  }
  window.PhilModelPicker = { attach: attach };
})();
