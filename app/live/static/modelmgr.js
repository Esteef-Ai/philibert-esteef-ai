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
  /* Your other computers (nd_modelshare): share this one's models over Tailscale, or use a bigger one's */
  function drawShare(s) {
    if (!s || s.ok === false && !s.tailscale_ip && s.msg) { $("share").innerHTML = ""; return; }
    var html = '<div class="share"><b>Your other computers</b>';
    if (s.host) {
      html += "<p>This computer uses the models on your other computer while it can reach it, and its own when it cannot. " +
        (s.using_host ? '<span class="ok">Connected now' + (s.host_models ? " · " + s.host_models.length + " models there" : "") + ".</span>"
                      : '<span class="off">Not reachable right now - using this computer\'s own models.</span>') + "</p>" +
        '<div class="row2"><span class="addr">' + esc(s.host.split("/k-")[0]) + '</span><button class="btn danger" id="sh-off">STOP USING IT</button></div>' +
        "<p><b>Notes and app data</b> - " + (s.sync_with
          ? "kept in step with your other computer: your notes, Philibert's memory, Yo Teach and Band Manager sync both ways every 5 minutes while it is reachable. " +
            (s.sync_last ? '<span class="' + (s.sync_last.ok ? "ok" : "off") + '">' + esc(s.sync_last.text) + " (" + new Date(s.sync_last.at * 1000).toLocaleTimeString() + ")</span>" : "")
          : "each computer keeps its own. Turn this on to keep them in step (your other computer must allow it too).") + "</p>" +
        '<div class="row2">' + (s.sync_with
          ? '<button class="btn" id="sy-now"' + (s.sync_running ? " disabled" : "") + '>SYNC NOW</button><button class="btn danger" id="sy-off">STOP SYNCING</button>'
          : '<button class="btn primary" id="sy-on">KEEP NOTES AND APP DATA IN STEP</button>') + "</div>";
    } else if (s.sharing) {
      html += "<p>Your other computers can use this computer's models. On the other computer, open Models and paste this address " +
        "(both need Tailscale signed in to your account). Only running models is allowed through it.</p>" +
        '<div class="row2"><span class="addr" id="sh-addr">' + esc(s.address) + '</span><button class="btn" id="sh-copy">COPY</button>' +
        '<button class="btn" id="sh-new" title="Make a new address; the old one stops working">NEW ADDRESS</button><button class="btn danger" id="sh-stop">STOP SHARING</button></div>' +
        "<p><b>Notes and app data</b> - " + (s.sync_share
          ? "your other computers can keep their notes, Philibert's memory, Yo Teach and Band Manager in step with this one, through the same address. Keep the address private: it opens your notes too."
          : "only the models are shared. Allow this to let your other computers keep their notes and app data in step with this one.") + "</p>" +
        '<div class="row2">' + (s.sync_share ? '<button class="btn danger" id="sy-unshare">STOP SHARING NOTES AND DATA</button>'
          : '<button class="btn" id="sy-share">ALSO SHARE NOTES AND APP DATA</button>') + "</div>" +
        "<p><b>Your phone</b> - " + (s.phone
          ? "open this address in your phone's browser (Tailscale on, signed in to your account) to chat with Philibert here and have it draw pictures. " +
            "Read only: from the phone it can look things up, not change anything."
          : "chat with Philibert on this computer from your phone's browser, over Tailscale.") + "</p>" +
        '<div class="row2">' + (s.phone
          ? '<span class="addr">' + esc(s.phone_address) + '</span><button class="btn" id="ph-copy">COPY</button><button class="btn danger" id="ph-off">TURN OFF</button>'
          : '<button class="btn" id="ph-on">OPEN A PHONE CHAT</button>') + "</div>";
    } else {
      html += "<p>A small laptop can use the models of a bigger computer you own, over Tailscale (a free private link between your own devices). " +
        (s.tailscale_ip ? "" : "Tailscale is not running on this computer yet. ") + "On the big computer, share; on the small one, paste the address it shows.</p>" +
        '<div class="row2"><button class="btn primary" id="sh-on"' + (s.tailscale_ip ? "" : " disabled") + ">SHARE THIS COMPUTER'S MODELS</button></div>" +
        '<div class="row2" style="margin-top:10px"><input id="sh-in" placeholder="http://100.x.y.z:11500/k-... from your other computer">' +
        '<button class="btn" id="sh-go">USE ITS MODELS</button></div>';
    }
    $("share").innerHTML = html + "</div>";
    function act(d, msg) { post("/api/modelshare", d).then(function (r) { if (r.ok === false) toast(r.msg); else if (msg) toast(msg); else if (r.sync_last) toast(r.sync_last.text); drawShare(r.ok === false ? s : r); load(); }); }
    if ($("sh-on")) $("sh-on").onclick = function () { act({ op: "share", on: true }, "Sharing. Paste the address on your other computer."); };
    if ($("sh-stop")) $("sh-stop").onclick = function () { act({ op: "share", on: false }, "Stopped sharing."); };
    if ($("sh-new")) $("sh-new").onclick = function () { act({ op: "share", on: true, new_key: true }, "New address - the old one no longer works."); };
    if ($("sh-copy")) $("sh-copy").onclick = function () { navigator.clipboard.writeText(s.address).then(function () { toast("Copied."); }); };
    if ($("sh-go")) $("sh-go").onclick = function () { act({ op: "connect", address: $("sh-in").value }, "Connected - the chat now uses your other computer's models."); };
    if ($("sy-share")) $("sy-share").onclick = function () { act({ op: "sync_share", on: true }, "Your other computers can now sync with this one."); };
    if ($("sy-unshare")) $("sy-unshare").onclick = function () { act({ op: "sync_share", on: false }, "Notes and app data are no longer shared."); };
    if ($("sy-on")) $("sy-on").onclick = function () { toast("Syncing - the first time can take a minute..."); act({ op: "sync_with", on: true }); };
    if ($("sy-off")) $("sy-off").onclick = function () { act({ op: "sync_with", on: false }, "Stopped syncing. Each computer keeps what it has."); };
    if ($("sy-now")) $("sy-now").onclick = function () { toast("Syncing..."); act({ op: "sync_now" }); };
    if ($("ph-on")) $("ph-on").onclick = function () { act({ op: "phone", on: true }, "Open the address on your phone."); };
    if ($("ph-off")) $("ph-off").onclick = function () { act({ op: "phone", on: false }, "Phone chat is off."); };
    if ($("ph-copy")) $("ph-copy").onclick = function () { navigator.clipboard.writeText(s.phone_address).then(function () { toast("Copied."); }); };
    if ($("sh-off")) $("sh-off").onclick = function () { act({ op: "disconnect" }, "Back to this computer's own models."); };
  }
  post("/api/modelshare", { op: "status" }).then(drawShare).catch(function () {});

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
