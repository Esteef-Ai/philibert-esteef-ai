/* Philibert Models: chat models (Ollama, /api/philibert/models|pull|remove) and picture
 * models (/api/images), each in plain words (models.json / pins.json plain_name, good_for). */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var chat = null, img = null, poll = null;
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function post(url, d) { return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(d || {}) }).then(function (r) { return r.json(); }); }
  function toast(m) { var t = $("toast"); t.textContent = m; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove("on"); }, 3000); }
  function gb(x) { return x >= 1 ? x.toFixed(1) + " GB" : Math.max(1, Math.round(x * 1000)) + " MB"; }
  var FIT = { green: "suits this computer", yellow: "works here, slowly", red: "too big for this computer" };

  function kindOf(m) {
    if (m.kind === "embed") return "notes";
    if (/vl:|vision/i.test(m.tag || "")) return "eyes";
    return "chat";
  }
  function chatFit(m) {
    var g = (chat && chat.gpu_gb) || 0, need = m.min_gpu_gb || 0;
    if (!g) return "yellow";
    return need <= g ? "green" : need <= g * 1.6 ? "yellow" : "red";
  }
  function load() {
    return Promise.all([post("/api/philibert/models"), post("/api/images", { op: "status" }).catch(function () { return {}; })]).then(function (r) {
      chat = r[0]; img = r[1]; draw();
      var busy = (chat.models || []).some(function (m) { return m.pull && ["done", "error"].indexOf(m.pull.status) < 0; }) ||
                 (img.download && img.download.state === "running");
      clearTimeout(poll);
      if (busy) poll = setTimeout(load, 1500);
    });
  }
  function row(o) {
    return '<div class="row"><div><b>' + esc(o.plain) + '</b><span class="real">' + esc(o.real) + "</span>" +
      '<div class="good">' + esc(o.good) + "</div>" + (o.score ? '<div class="meta"><span style="color:#a78bfa">' + esc(o.score) + "</span></div>" : "") +
      '<div class="meta">' + (o.size ? "<span>" + gb(o.size) + "</span>" : "") +
      (o.fit ? '<span class="fit ' + o.fit + '">' + FIT[o.fit] + "</span>" : "") +
      (o.installed ? '<span class="tag on">ON THE DRIVE</span>' : "") + (o.keep ? '<span class="tag keep">PHILIBERT NEEDS IT</span>' : "") + "</div>" +
      (o.progress != null ? '<div class="bar"><div style="width:' + Math.round(o.progress * 100) + '%"></div></div>' : "") +
      (o.error ? '<div class="note">' + esc(o.error) + "</div>" : "") + "</div>" +
      "<div>" + (o.progress != null ? '<span class="real">downloading…</span>'
        : o.installed ? (o.keep || o.ro ? "" : '<button class="btn danger" data-rm="' + esc(o.key) + '">REMOVE</button>')
        : '<button class="btn primary" data-add="' + esc(o.key) + '">ADD</button>') + "</div></div>";
  }
  function draw() {
    var groups = { chat: [], eyes: [], notes: [] };
    (chat.models || []).forEach(function (m) {
      var p = m.pull && ["done", "error"].indexOf(m.pull.status) < 0 ? m.pull : null;
      groups[kindOf(m)].push(row({
        key: "c:" + m.tag, plain: m.plain_name || m.label || m.tag, real: (m.label || "") + " · " + m.tag,
        good: m.good_for || (m.extra ? "On this computer, not in the catalog." : ""), size: m.size_gb, score: m.score,
        fit: m.extra ? null : chatFit(m), installed: m.installed, keep: !!m.required,
        progress: p ? (p.total ? p.done / p.total : 0) : null, error: m.pull && m.pull.status === "error" ? m.pull.error : ""
      }));
    });
    var dl = (img && img.download) || {};
    var native = chat.images;                    // native ND: its ComfyUI's files, managed there
    var pics = native ? native.map(function (m) {
      return row({ key: "n:" + m.file, plain: m.plain_name, real: m.name, good: m.good_for, size: (m.size || 0) / 1e9,
                   installed: m.installed, ro: true });
    }) : ((img && img.models) || []).map(function (m) {
      var going = dl.state === "running" && dl.id === m.id;
      return row({ key: "i:" + m.id, plain: m.plain_name || m.name, real: m.name + (m.own ? " · your own file" : ""), good: m.good_for || m.about,
                   size: (m.size || 0) / 1e9, fit: m.own ? null : m.fit, installed: m.installed, keep: !!m.own,
                   progress: going ? dl.progress || 0 : null, error: dl.state === "error" && dl.id === m.id ? dl.error : "" });
    });
    $("body").innerHTML =
      "<h2>Talking and thinking</h2>" + groups.chat.join("") +
      "<h2>Seeing pictures</h2>" + groups.eyes.join("") +
      "<h2>Finding notes</h2>" + groups.notes.join("") +
      "<h2>Making pictures (Image Generation)</h2>" + (pics.join("") || '<p class="lead">No picture models are listed on this drive yet - updating Philibert from the App Store brings the list.</p>') +
      (native ? '<p class="note">These are the picture models in ComfyUI on this PC - add or remove them in ComfyUI\'s models folder.</p>' : "") +
      (!native && img && img.installed === false && pics.length ? '<p class="note">Image Generation isn\'t set up on this computer yet - the models can download now, and its app sets up the rest.</p>' : "");
  }
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest("[data-add]"), r = ev.target.closest("[data-rm]");
    if (a) {
      var k = a.dataset.add; a.disabled = true;
      (k.indexOf("c:") === 0 ? post("/api/philibert/pull", { tag: k.slice(2) }) : post("/api/images", { op: "model_download", id: k.slice(2) }))
        .then(function (d) { if (d.ok === false) toast(d.error || d.msg || "Could not start the download."); load(); });
    }
    if (r) {
      var key = r.dataset.rm;
      if (!confirm("Remove this model from the drive? You can add it again later (it downloads again).")) return;
      (key.indexOf("c:") === 0 ? post("/api/philibert/remove", { tag: key.slice(2) }) : post("/api/images", { op: "model_remove", id: key.slice(2) }))
        .then(function (d) { toast(d.ok === false ? (d.error || d.msg) : "Removed."); load(); });
    }
  });
  load();
})();
