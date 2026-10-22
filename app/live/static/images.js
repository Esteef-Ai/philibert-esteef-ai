/* Philibert Image Generation: the drive's ComfyUI add-on (nd_imagegen.py, /api/images).
 * Not set up on this computer: this computer's rating and a SET UP button.
 * Set up: a prompt, a size, MAKE IT, and the gallery in data\images on the drive.
 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var body = $("body"), st = null, size = "square", busy = false, list = [];
  var SIZE_NAMES = { square: ["Square", "album cover, socials"], poster: ["Poster", "gig flyer, portrait"],
                     banner: ["Banner", "header, landscape"], story: ["Story", "phone, tall"] };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function api(op, data) {
    return fetch("/api/images", { method: "POST", headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify(Object.assign({ op: op }, data || {})) }).then(function (r) { return r.json(); });
  }
  function toast(m) { var t = $("toast"); t.textContent = m; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove("on"); }, 2800); }
  function src(name) { return "/api/images/file?name=" + encodeURIComponent(name); }

  function load() {
    api("status").then(function (d) {
      st = d;
      $("editor").hidden = !d.installed;
      if (!d.installed) return setupView();
      studio();
    });
  }

  /* ---------- not set up on this computer ---------- */
  var poll = null;
  function setupView() {
    var s = st.setup || {}, running = s.state === "running", blocked = st.rating === "red" && /Intel chip|driver/.test(st.why);
    body.innerHTML = '<div class="setup"><h1>Image Generation</h1>' +
      '<p class="lead">Make album covers, gig posters and banners from a description - on this computer, with nothing sent anywhere. ' +
      "It runs ComfyUI from your drive.</p>" +
      '<div class="rating ' + esc(st.rating) + '">This computer: ' + esc(st.rating) + "</div>" +
      '<p class="lead">' + esc(st.why) + "</p>" +
      '<dl class="facts"><dt>Download</dt><dd>about 10 GB the first time: the picture engine (3 GB) and a picture model (7 GB)' +
      (st.checkpoints.length ? " - you already have a model, so about 3 GB" : "") + "</dd>" +
      "<dt>Space on the drive</dt><dd>about 13 GB</dd><dt>Set up</dt><dd>once for each computer you use it on; the pictures and models are shared</dd></dl>" +
      (running ? '<div class="bar"><div id="bar"></div></div><p class="status" id="sline"></p>'
               : (s.state === "error" ? '<p class="status err">' + esc(s.error) + "</p>" : "") +
                 '<button class="btn primary go" id="setup-go"' + (blocked ? " disabled" : "") + ">" +
                 (s.state === "error" ? "TRY AGAIN" : "SET UP ON THIS COMPUTER") + "</button>" +
                 (st.rating === "red" && !blocked ? '<p class="lead" style="margin-top:8px;color:var(--amber)">It will work, but slowly.</p>' : "")) +
      "</div>";
    if (running) {
      $("bar").style.width = Math.round((s.progress || 0) * 100) + "%";
      $("sline").textContent = s.line || "";
      clearTimeout(poll);
      poll = setTimeout(function () { api("status").then(function (d) { st = d; if (d.installed) { toast("Image Generation is ready."); load(); } else setupView(); }); }, 1500);
      return;
    }
    var go = $("setup-go");
    if (go) go.addEventListener("click", function () {
      api("install").then(function (d) { if (!d.ok) { toast(d.msg); return; } load(); });
    });
  }

  /* ---------- set up: prompt + gallery ---------- */
  function studio() {
    body.innerHTML = '<div class="main" style="height:100%">' +
      '<aside><h1>Make a picture</h1><p class="lead">Describe it: what is in it, the style, the light, the colours.</p>' +
      '<h2>What to draw</h2><textarea id="prompt" placeholder="A vintage gig poster: a saxophone player on a rooftop at dusk, neon city behind, bold 1970s colours"></textarea>' +
      "<h2>Size</h2><div class=\"sizes\">" + Object.keys(SIZE_NAMES).map(function (k) {
        var wh = st.sizes[k], sc = 22 / Math.max(wh[0], wh[1]);
        return '<div class="size' + (k === size ? " on" : "") + '" data-size="' + k + '"><i style="width:' + Math.round(wh[0] * sc) + "px;height:" +
               Math.round(wh[1] * sc) + 'px"></i><div>' + SIZE_NAMES[k][0] + "<small>" + SIZE_NAMES[k][1] + "</small></div></div>";
      }).join("") + "</div>" +
      '<details><summary>MORE</summary><h2>Leave out</h2><input id="neg" placeholder="text, watermark, extra fingers">' +
      (st.checkpoints.length > 1 ? '<h2>Model</h2><select id="model">' + st.checkpoints.map(function (c) { return "<option>" + esc(c) + "</option>"; }).join("") + "</select>" : "") +
      '<h2>Seed (the same seed and prompt make the same picture)</h2><input id="seed" type="number" placeholder="random"></details>' +
      '<button class="btn primary go" id="make">MAKE IT</button><p class="status" id="status"></p>' +
      '<p class="lead" style="margin-top:14px;font-size:12px">Pictures are saved in <code>data\\images</code> on your drive.</p></aside>' +
      '<section><h1>Gallery</h1><div class="gal" id="gal"></div></section></div>';
    body.querySelectorAll("[data-size]").forEach(function (el) {
      el.addEventListener("click", function () { size = el.dataset.size; body.querySelectorAll("[data-size]").forEach(function (x) { x.classList.toggle("on", x === el); }); });
    });
    $("make").addEventListener("click", make);
    $("prompt").addEventListener("keydown", function (ev) { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) make(); });
    gallery();
  }
  function gallery(pending) {
    api("list").then(function (d) {
      list = d.images || [];
      var g = $("gal");
      if (!g) return;
      g.innerHTML = (pending ? '<figure class="pending"><span id="pend">drawing…</span></figure>' : "") + list.map(function (im, i) {
        return '<figure data-i="' + i + '"><img loading="lazy" src="' + src(im.name) + '" alt=""><figcaption>' + esc(im.prompt || im.name) + "</figcaption></figure>";
      }).join("") || '<p class="empty">Nothing yet. Describe a picture on the left and press MAKE IT.</p>';
    });
  }
  function make() {
    if (busy) return;
    var p = $("prompt").value.trim();
    if (!p) { $("prompt").focus(); toast("Say what to draw first."); return; }
    busy = true;
    var b = $("make"), s = $("status"), t0 = Date.now();
    b.disabled = true; s.className = "status";
    var tick = setInterval(function () {
      var sec = Math.round((Date.now() - t0) / 1000);
      s.textContent = (sec < 8 && !st.running ? "Starting the picture engine… " : "Drawing… ") + sec + "s";
      var pe = $("pend"); if (pe) pe.textContent = "drawing… " + sec + "s";
    }, 500);
    gallery(true);
    api("generate", { prompt: p, negative: ($("neg") || {}).value || "", size: size, seed: ($("seed") || {}).value || null,
                      model: ($("model") || {}).value || null }).then(function (d) {
      clearInterval(tick); busy = false; b.disabled = false;
      if (!d.ok) { s.className = "status err"; s.textContent = d.msg; gallery(); return; }
      st.running = true;
      s.textContent = "Done in " + Math.round((Date.now() - t0) / 1000) + "s.";
      gallery();
    }).catch(function () { clearInterval(tick); busy = false; b.disabled = false; s.className = "status err"; s.textContent = "Philibert stopped answering."; });
  }

  /* ---------- one picture ---------- */
  var cur = null;
  body.addEventListener("click", function (ev) {
    var f = ev.target.closest("figure[data-i]");
    if (!f) return;
    cur = list[+f.dataset.i];
    $("lb-img").src = src(cur.name);
    $("lb-prompt").textContent = cur.prompt || "(made in ComfyUI's editor)";
    $("lb-meta").textContent = [cur.w && cur.h ? cur.w + " × " + cur.h : "", cur.seed ? "seed " + cur.seed : "",
                                new Date(cur.when * 1000).toLocaleString()].filter(Boolean).join(" · ");
    $("lb-save").href = src(cur.name); $("lb-save").download = cur.name;
    $("lb").classList.add("on");
  });
  function closeLb() { $("lb").classList.remove("on"); }
  $("lb-close").addEventListener("click", closeLb);
  addEventListener("keydown", function (ev) { if (ev.key === "Escape") closeLb(); });
  $("lb-again").addEventListener("click", function () {
    closeLb();
    if (cur && $("prompt")) { $("prompt").value = cur.prompt || ""; if (cur.seed && $("seed")) $("seed").value = cur.seed; $("prompt").focus(); }
  });
  $("lb-del").addEventListener("click", function () {
    if (!cur) return;
    api("delete", { name: cur.name }).then(function (d) { toast(d.ok ? "Deleted (it waits in data\\images\\.trash)." : "Could not delete it."); closeLb(); gallery(); });
  });
  $("editor").addEventListener("click", function () {
    var b = $("editor"); b.textContent = "STARTING…";
    api("start").then(function (d) {
      b.textContent = "OPEN COMFYUI (ADVANCED)";
      if (!d.ok) { toast(d.msg); return; }
      st.running = true;
      window.open(d.editor, "philibert-comfyui", "popup,width=1400,height=900");
    });
  });

  load();
})();
