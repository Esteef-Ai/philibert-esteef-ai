/* Philibert Image Generation: the drive's ComfyUI add-on (nd_imagegen.py, /api/images).
 * Not set up on this computer: this computer's rating and SET UP.
 * Set up: CREATE (model, style, prompt, size, 1-4 variations), GALLERY (data\images on
 * the drive) and MODELS (download the ones you want; each says if it suits this computer).
 * The quick version lives in Philibert Chat; this is the full one.
 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var body = $("body"), st = null, tab = "create", busy = false, list = [], fresh = [];
  var form = { model: null, style: "none", size: "square", count: 1, prompt: "", negative: "", seed: "", steps: "", cfg: "" };
  var SIZE_NAMES = { square: ["Square", "album cover, socials"], poster: ["Poster", "gig flyer, portrait"],
                     banner: ["Banner", "header, landscape"], story: ["Story", "phone, tall"] };
  try { Object.assign(form, JSON.parse(localStorage.getItem("img.form") || "{}")); } catch (e) { /* private */ }
  function keep() { try { localStorage.setItem("img.form", JSON.stringify(form)); } catch (e) { /* private */ } }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function api(op, data) {
    return fetch("/api/images", { method: "POST", headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify(Object.assign({ op: op }, data || {})) }).then(function (r) { return r.json(); });
  }
  function toast(m) { var t = $("toast"); t.textContent = m; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove("on"); }, 3200); }
  function src(name) { return "/api/images/file?name=" + encodeURIComponent(name); }
  function gb(b) { return b >= 1e9 ? (b / 1e9).toFixed(1) + " GB" : Math.max(1, Math.round(b / 1e6)) + " MB"; }
  var showMore = false;
  function groups() {
    var out = [];
    (st.more_styles || []).forEach(function (s) {
      var g = out.find(function (x) { return x[0] === s.group; });
      if (!g) { g = [s.group, []]; out.push(g); }
      g[1].push(s);
    });
    return out;
  }
  function moreName() {           // a More style that is chosen shows up beside the quick ones
    var m = (st.more_styles || []).find(function (s) { return s.id === form.style; });
    return m && !showMore ? m.name : "";
  }
  function sdxlOk() { return pictureModels().some(function (m) { return m.kind === "sdxl"; }); }
  function model(id) { return (st.models || []).find(function (m) { return m.id === id; }); }
  function pictureModels() { return (st.models || []).filter(function (m) { return m.installed && (m.kind === "zimage" || m.kind === "sdxl"); }); }
  var FIT = { green: "suits this computer", yellow: "works here, slowly", red: "too big for this computer" };

  function load() {
    return api("status").then(function (d) {
      st = d;
      $("editor").hidden = !d.installed;
      $("tabs").hidden = !d.installed;
      if (!d.installed) return setupView();
      if (!form.model || !model(form.model) || !model(form.model).installed) form.model = d.default_model;
      if (!pictureModels().length && tab === "create") tab = "models";
      show(tab);
    });
  }
  $("tabs").addEventListener("click", function (ev) {
    var b = ev.target.closest("[data-tab]");
    if (b) show(b.dataset.tab);
  });
  function show(t) {
    tab = t;
    document.querySelectorAll("#tabs button").forEach(function (b) { b.classList.toggle("on", b.dataset.tab === t); });
    if (t === "models") return modelsView();
    if (t === "gallery") return galleryView();
    createView();
  }

  /* ---------- not set up on this computer ---------- */
  var poll = null;
  function setupView() {
    var s = st.setup || {}, running = s.state === "running", blocked = st.rating === "red" && /Intel chip|driver/.test(st.why);
    body.innerHTML = '<div style="overflow:auto;height:100%"><div class="card setup"><h1>Image Generation</h1>' +
      '<p class="lead">Album covers, gig posters, banners and band photos from a description - made on this computer, nothing sent anywhere. ' +
      "It runs ComfyUI from your drive.</p>" +
      '<p style="margin:14px 0 4px" class="rating ' + esc(st.rating) + '">THIS COMPUTER: ' + esc(st.rating).toUpperCase() + "</p>" +
      '<p class="lead">' + esc(st.why) + "</p>" +
      '<dl class="facts"><dt>Download</dt><dd>the picture engine (about 3.5 GB), then a picture model: Z-Image Turbo (21 GB) on a card ' +
      "with 12 GB or more, SDXL (7 GB) otherwise. More models are in MODELS later.</dd>" +
      "<dt>Set up</dt><dd>once for each computer you use it on; the pictures and models on the drive are shared</dd></dl>" +
      (running ? '<div class="bar"><div id="bar"></div></div><p class="status" id="sline"></p>'
               : (s.state === "error" ? '<p class="status err">' + esc(s.error) + "</p>" : "") +
                 '<button class="btn primary go" id="setup-go"' + (blocked ? " disabled" : "") + ">" +
                 (s.state === "error" ? "TRY AGAIN" : "SET UP ON THIS COMPUTER") + "</button>" +
                 (st.rating === "red" && !blocked ? '<p class="tip" style="color:var(--amber)">It will work, but slowly.</p>' : "")) +
      "</div></div>";
    if (running) {
      $("bar").style.width = Math.round((s.progress || 0) * 100) + "%";
      $("sline").textContent = s.line || "";
      clearTimeout(poll);
      poll = setTimeout(load, 1500);
      return;
    }
    var go = $("setup-go");
    if (go) go.addEventListener("click", function () {
      api("install").then(function (d) { if (!d.ok) { toast(d.msg); return; } load(); });
    });
  }

  /* ---------- CREATE ---------- */
  function createView() {
    var ms = pictureModels(), m = model(form.model) || ms[0] || {};
    var z = m.kind === "zimage";
    body.innerHTML = '<div class="main">' +
      "<aside><h1>Make a picture</h1>" +
      "<h2>Model</h2><select id=\"f-model\">" + ms.map(function (x) {
        return '<option value="' + esc(x.id) + '"' + (x.id === m.id ? " selected" : "") + ">" + esc(x.name) + "</option>"; }).join("") +
      '</select><p class="tip">' + esc(m.about || "") + ' <a href="#" id="to-models" style="color:var(--cyan)">More models</a></p>' +
      "<h2>Style</h2><div class=\"chips\">" + st.styles.map(function (s) {
        return '<span class="chip' + (s.id === form.style ? " on" : "") + '" data-style="' + s.id + '">' + esc(s.name) + "</span>"; }).join("") +
      (moreName() ? '<span class="chip on" data-style="' + esc(form.style) + '">' + esc(moreName()) + "</span>" : "") +
      '<span class="chip more" id="more-styles">' + (showMore ? "FEWER STYLES" : "MORE STYLES…") + "</span></div>" +
      (showMore ? '<div class="morestyles">' + groups().map(function (g) {
        return '<div class="k">' + esc(g[0]) + '</div><div class="chips">' + g[1].map(function (s) {
          return '<span class="chip' + (s.id === form.style ? " on" : "") + '" data-style="' + s.id + '">' + esc(s.name) + "</span>"; }).join("") + "</div>";
      }).join("") + "</div>" : "") +
      "<h2>What to draw</h2><textarea id=\"f-prompt\" placeholder=\"" + (z
        ? 'A vintage gig poster: a saxophone player on a rooftop at dusk, the city in neon behind. The words &quot;FRIDAY 9PM&quot; across the top.'
        : "saxophone player on a rooftop at dusk, neon city, vintage gig poster, bold colours") + '">' + esc(form.prompt) + "</textarea>" +
      '<p class="tip">' + (z ? "Describe it in sentences: what is in it, where, the light, the mood. Put any words that should appear in the picture in &quot;quotes&quot;."
                             : "Short phrases separated by commas work best: subject, setting, style, light, colours.") + "</p>" +
      "<h2>Leave out</h2><textarea class=\"neg\" id=\"f-neg\" placeholder=\"" + (z ? "umbrellas, people in the background" : "text, extra fingers, frame") +
      "\">" + esc(form.negative) + "</textarea>" +
      (z ? '<p class="tip" id="neg-note"' + (String(form.negative || "").trim() ? "" : " hidden") + ' style="color:var(--amber)">Z-Image Turbo can\'t leave things out - '
           + "it is built for speed and ignores this list. " + (sdxlOk() ? '<a href="#" id="use-sdxl" style="color:var(--cyan)">Use SDXL for this picture</a>'
           : "SDXL or Juggernaut (in Models) can.") + "</p>" : "") +
      "<h2>Size</h2><div class=\"sizes\">" + Object.keys(SIZE_NAMES).map(function (k) {
        var wh = st.sizes[k], sc = 22 / Math.max(wh[0], wh[1]);
        return '<div class="size' + (k === form.size ? " on" : "") + '" data-size="' + k + '"><i style="width:' + Math.round(wh[0] * sc) + "px;height:" +
               Math.round(wh[1] * sc) + 'px"></i><div>' + SIZE_NAMES[k][0] + "<small>" + SIZE_NAMES[k][1] + "</small></div></div>";
      }).join("") + "</div>" +
      "<h2>How many</h2><div class=\"seg\">" + [1, 2, 3, 4].map(function (n) {
        return '<button type="button" data-count="' + n + '" class="' + (n === +form.count ? "on" : "") + '">' + n + "</button>"; }).join("") + "</div>" +
      '<p class="tip">More than one gives variations to choose from.</p>' +
      "<details><summary>ADVANCED</summary><div class=\"row2\" style=\"margin-top:8px\">" +
      '<div><label>SEED</label><input id="f-seed" type="number" placeholder="random" value="' + esc(form.seed) + '"></div>' +
      '<div><label>STEPS</label><input id="f-steps" type="number" min="1" max="60" placeholder="' + (st.defaults[m.kind] || {}).steps + '" value="' + esc(form.steps) + '"></div>' +
      '<div><label>GUIDANCE</label><input id="f-cfg" type="number" step="0.5" min="1" max="15" ' + (z ? "disabled placeholder=\"1\"" : 'placeholder="' + ((st.defaults.sdxl || {}).cfg) + '" value="' + esc(form.cfg) + '"') + "></div>" +
      '</div><p class="tip">The same seed and prompt make the same picture. ' + (z ? "Z-Image Turbo always uses guidance 1." : "Guidance: how closely it follows the words (5-7 is usual).") + "</p></details>" +
      '<button class="btn primary go" id="make"' + (ms.length ? "" : " disabled") + ">MAKE IT</button>" +
      '<p class="status" id="status"></p></aside>' +
      '<section class="pane"><h1 id="fresh-h"' + (fresh.length ? "" : " hidden") + ">Just made</h1><div class=\"gal fresh\" id=\"fresh\"></div>" +
      '<h1 style="margin-top:18px">Recent</h1><div class="gal" id="recent"></div></section></div>';
    drawFresh(); recent();
    $("f-model").addEventListener("change", function () { form.model = this.value; form.steps = ""; form.cfg = ""; keep(); createView(); });
    $("to-models").addEventListener("click", function (ev) { ev.preventDefault(); show("models"); });
    body.querySelectorAll("[data-style]").forEach(function (el) { el.addEventListener("click", function () { form.style = el.dataset.style; keep(); createView(); }); });
    $("more-styles").addEventListener("click", function () { showMore = !showMore; createView(); });
    if ($("neg-note")) $("f-neg").addEventListener("input", function () { $("neg-note").hidden = !this.value.trim(); });
    if ($("use-sdxl")) $("use-sdxl").addEventListener("click", function (ev) {
      ev.preventDefault();
      var x = pictureModels().find(function (m) { return m.kind === "sdxl"; });
      if (x) { form.model = x.id; form.steps = ""; form.cfg = ""; keep(); createView(); toast("Using " + x.name + " - it leaves out what you list."); }
    });
    body.querySelectorAll("[data-size]").forEach(function (el) { el.addEventListener("click", function () { form.size = el.dataset.size; keep(); createView(); }); });
    body.querySelectorAll("[data-count]").forEach(function (el) { el.addEventListener("click", function () { form.count = +el.dataset.count; keep(); createView(); }); });
    ["prompt", "neg", "seed", "steps", "cfg"].forEach(function (k) {
      var el = $("f-" + k); if (!el) return;
      el.addEventListener("input", function () { form[k === "neg" ? "negative" : k] = el.value; keep(); });
    });
    $("f-prompt").addEventListener("keydown", function (ev) { if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) make(); });
    $("make").addEventListener("click", function () { make(); });
  }
  function figs(items) {
    return items.map(function (im, i) {
      return '<figure data-name="' + esc(im.name) + '"><img loading="lazy" src="' + src(im.name) + '" alt=""><figcaption>' +
             esc(im.prompt || im.name) + "</figcaption></figure>";
    }).join("");
  }
  function drawFresh(pending) {
    var el = $("fresh"); if (!el) return;
    $("fresh-h").hidden = !(fresh.length || pending);
    el.innerHTML = (pending ? new Array(pending + 1).join('<figure class="pending" style="aspect-ratio:1"><span class="pend">drawing…</span></figure>') : "") + figs(fresh);
  }
  function recent() {
    api("list").then(function (d) {
      list = d.images || [];
      var el = $("recent"); if (!el) return;
      el.innerHTML = figs(list.slice(0, 12)) || '<p class="empty">Nothing yet. Describe a picture on the left and press MAKE IT.</p>';
    });
  }
  function make(over) {
    if (busy) return;
    var o = Object.assign({}, form, over || {});
    if (!String(o.prompt || "").trim()) { var p = $("f-prompt"); if (p) p.focus(); toast("Say what to draw first."); return; }
    busy = true;
    if (tab !== "create") show("create");
    var b = $("make"), s = $("status"), t0 = Date.now();
    b.disabled = true; s.className = "status";
    var tick = setInterval(function () {
      var sec = Math.round((Date.now() - t0) / 1000);
      s.textContent = (sec < 10 && !st.running ? "Starting the picture engine… " : "Drawing… ") + sec + "s";
      document.querySelectorAll(".pend").forEach(function (x) { x.textContent = "drawing… " + sec + "s"; });
    }, 500);
    drawFresh(+o.count || 1);
    api("generate", { prompt: o.prompt, negative: o.negative || "", model: o.model, style: o.style, size: o.size, count: o.count,
                      seed: o.seed || null, steps: o.steps || null, cfg: o.cfg || null }).then(function (d) {
      clearInterval(tick); busy = false; b.disabled = false;
      if (!d.ok) { s.className = "status err"; s.textContent = d.msg; drawFresh(); return; }
      st.running = true;
      fresh = d.images.concat(fresh).slice(0, 8);
      s.textContent = (d.images.length > 1 ? d.images.length + " pictures" : "Done") + " in " + Math.round((Date.now() - t0) / 1000) + "s.";
      drawFresh(); recent();
    }).catch(function () { clearInterval(tick); busy = false; b.disabled = false; s.className = "status err"; s.textContent = "Philibert stopped answering."; });
  }

  /* ---------- GALLERY ---------- */
  function galleryView() {
    body.innerHTML = '<section class="pane"><h1>Gallery</h1><p class="lead">Everything made here, newest first. Saved in <code>data\\images</code> on your drive.</p>' +
      '<div class="gal" id="gal"></div></section>';
    api("list").then(function (d) {
      list = d.images || [];
      $("gal").innerHTML = figs(list) || '<p class="empty">Nothing yet.</p>';
    });
  }

  /* ---------- MODELS ---------- */
  var mpoll = null;
  function modelsView() {
    var dl = st.download || {};
    body.innerHTML = '<section class="pane"><h1>Models</h1><p class="lead">Download the ones you want; each one says whether it suits this computer. ' +
      "They live in <code>models\\image</code> on the drive and work on every computer it is plugged into.</p>" +
      '<div class="models">' + st.models.map(function (m) {
        var going = dl.state === "running" && dl.id === m.id;
        return '<div class="card"><h3>' + esc(m.name) + (m.recommended ? ' <span class="tag rec">RECOMMENDED</span>' : "") +
          (m.installed ? ' <span class="tag inst">ON THE DRIVE</span>' : "") + "</h3>" +
          '<div class="meta">' + (m.size ? gb(m.size) + " · " : "") + esc(m.licence || "") + "</div>" +
          '<p class="lead" style="font-size:12.5px">' + esc(m.about || "") + "</p>" +
          (m.own ? "" : '<p style="margin:10px 0" class="rating ' + m.fit + '">' + FIT[m.fit] + "</p>") +
          (going ? '<div class="bar"><div style="width:' + Math.round((dl.progress || 0) * 100) + '%"></div></div><p class="tip">' + esc(dl.line || "") + "</p>"
                 : m.own ? "" : m.installed ? '<button class="btn danger small" data-rm="' + esc(m.id) + '">REMOVE</button>'
                 : '<button class="btn small" data-dl="' + esc(m.id) + '"' + (dl.state === "running" ? " disabled" : "") + ">DOWNLOAD</button>") +
          (m.source ? ' <a class="btn small" href="' + esc(m.source) + '" target="_blank" rel="noopener">ABOUT</a>' : "") + "</div>";
      }).join("") + "</div>" + (dl.state === "error" ? '<p class="status err">' + esc(dl.error) + "</p>" : "") + "</section>";
    clearTimeout(mpoll);
    if (dl.state === "running") mpoll = setTimeout(function () { api("status").then(function (d) { st = d; if (tab === "models") modelsView(); }); }, 1500);
    if (dl.state === "done" && dl.id && !modelsView.said) { modelsView.said = dl.id; toast((model(dl.id) || {}).name + " is ready."); }
  }
  body.addEventListener("click", function (ev) {
    var d = ev.target.closest("[data-dl]");
    if (d) { modelsView.said = null; api("model_download", { id: d.dataset.dl }).then(function (r) { if (!r.ok) toast(r.msg); load(); }); return; }
    var r = ev.target.closest("[data-rm]");
    if (r) {
      var m = model(r.dataset.rm);
      if (!confirm("Remove " + m.name + " from the drive? It frees " + gb(m.size) + "; you can download it again.")) return;
      api("model_remove", { id: r.dataset.rm }).then(function () { toast(m.name + " removed."); load(); });
      return;
    }
    var f = ev.target.closest("figure[data-name]");
    if (f) openLb(f.dataset.name);
  });

  /* ---------- one picture ---------- */
  var cur = null;
  function refineBox(on) {
    $("lb-refine").hidden = !on;
    $("lb-rf-go").disabled = false; $("lb-rf-go").textContent = "REFINE";
    if (on) { $("lb-rf-text").value = ""; $("lb-rf-text").focus(); }
  }
  $("lb-ref").addEventListener("click", function () { refineBox($("lb-refine").hidden); });
  $("lb-rf-go").addEventListener("click", function () {
    var t = $("lb-rf-text").value.trim();
    if (!t) { $("lb-rf-text").focus(); return; }
    var b = $("lb-rf-go"), t0 = Date.now(), name = cur.name;
    b.disabled = true; b.textContent = "REFINING…";
    var tick = setInterval(function () { b.textContent = "REFINING… " + Math.round((Date.now() - t0) / 1000) + "s"; }, 500);
    api("refine", { name: name, prompt: t, strength: +$("lb-rf-strength").value, count: +$("lb-rf-count").value }).then(function (d) {
      clearInterval(tick);
      if (!d.ok) { b.disabled = false; b.textContent = "REFINE"; toast(d.msg); return; }
      fresh = d.images.concat(fresh).slice(0, 8);
      closeLb(); show("create");
      toast((d.images.length > 1 ? d.images.length + " refined versions" : "Refined") + " in " + Math.round((Date.now() - t0) / 1000) + "s.");
    });
  });
  function openLb(name) {
    cur = list.concat(fresh).find(function (x) { return x.name === name; }) || { name: name };
    $("lb-img").src = src(cur.name);
    $("lb-prompt").textContent = cur.prompt || "(made in ComfyUI's editor)";
    $("lb-meta").textContent = [cur.model, cur.w && cur.h ? cur.w + " × " + cur.h : "", cur.seed ? "seed " + cur.seed : "",
                                cur.upscaled_from ? "4x" : ""].filter(Boolean).join(" · ");
    $("lb-save").href = src(cur.name); $("lb-save").download = cur.name;
    $("lb-up").hidden = !!cur.upscaled_from;
    $("lb-vary").hidden = !cur.prompt;
    refineBox(false);
    $("lb").classList.add("on");
  }
  function closeLb() { $("lb").classList.remove("on"); }
  $("lb-close").addEventListener("click", closeLb);
  addEventListener("keydown", function (ev) { if (ev.key === "Escape") closeLb(); });
  $("lb-again").addEventListener("click", function () {
    closeLb();
    if (!cur) return;
    form.prompt = cur.prompt || ""; form.seed = cur.seed || ""; if (cur.style) form.style = cur.style;
    if (cur.model_id && model(cur.model_id) && model(cur.model_id).installed) form.model = cur.model_id;
    keep(); show("create");
  });
  $("lb-vary").addEventListener("click", function () {
    closeLb();
    make({ prompt: cur.prompt, style: cur.style || "none", model: cur.model_id || form.model, count: 4, seed: "",
           size: cur.w > cur.h ? "banner" : cur.h > cur.w ? "poster" : "square" });
  });
  $("lb-up").addEventListener("click", function () {
    var b = $("lb-up"); b.disabled = true; b.textContent = "MAKING IT BIGGER…";
    api("upscale", { name: cur.name }).then(function (d) {
      b.disabled = false; b.textContent = "MAKE IT 4x BIGGER";
      if (!d.ok) { toast(d.msg); if (/Models/.test(d.msg)) { closeLb(); show("models"); } return; }
      toast("Saved the 4x version."); closeLb(); if (tab === "gallery") galleryView(); else recent();
    });
  });
  $("lb-del").addEventListener("click", function () {
    if (!cur) return;
    api("delete", { name: cur.name }).then(function (d) {
      toast(d.ok ? "Deleted (it waits in data\\images\\.trash)." : "Could not delete it.");
      fresh = fresh.filter(function (x) { return x.name !== cur.name; });
      closeLb(); show(tab);
    });
  });
  $("editor").addEventListener("click", function () {
    var b = $("editor"); b.textContent = "STARTING…";
    api("start").then(function (d) {
      b.textContent = "COMFYUI EDITOR";
      if (!d.ok) { toast(d.msg); return; }
      st.running = true;
      window.open(d.editor, "philibert-comfyui", "popup,width=1400,height=900");
    });
  });

  load();
})();
