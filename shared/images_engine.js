/* Philibert Image Generation: the picture engine (ComfyUI), watched and stopped from the page header
   (dev/patching.py IMAGEGEN_ENGINE, shared/nd_imagegen_engine.py).
   ENGINE shows what it is doing (off / ready / drawing, ComfyUI's queue, the graphics card); its panel has
   STOP (the picture being drawn and anything waiting), UNLOAD (give the card back, the engine stays on) and
   TURN OFF. While a picture is drawn a STOP button sits beside it in the header. */
(function () {
  "use strict";
  var head = document.querySelector("header"), editor = document.getElementById("editor");
  if (!head || !editor) return;
  var css = document.createElement("style");
  css.textContent =
    "#eng{font-variant-numeric:tabular-nums} #eng.drawing{border-color:var(--amber);color:var(--amber)}" +
    "#eng-pop{position:fixed;z-index:40;top:54px;right:18px;width:340px;background:var(--panel);border:1px solid var(--line);" +
    "border-radius:10px;padding:14px;box-shadow:0 10px 30px rgba(0,0,0,.45);display:flex;flex-direction:column;gap:8px}" +
    "#eng-pop[hidden]{display:none} #eng-pop h3{margin:0;font:11px var(--mono);letter-spacing:.1em;color:var(--faint)}" +
    "#eng-pop p{margin:0;font-size:13px;line-height:1.45} #eng-pop .k{color:var(--faint)} #eng-pop .row{display:flex;gap:8px;flex-wrap:wrap}" +
    "#eng-pop .tip{font-size:11.5px;color:var(--faint)}";
  document.head.appendChild(css);
  var stopNow = document.createElement("button");
  stopNow.className = "btn danger"; stopNow.id = "eng-stop"; stopNow.type = "button"; stopNow.hidden = true;
  stopNow.textContent = "STOP"; stopNow.title = "Stop the picture being drawn, and anything waiting";
  var pill = document.createElement("button");
  pill.className = "btn"; pill.id = "eng"; pill.type = "button"; pill.textContent = "ENGINE";
  pill.title = "The picture engine (ComfyUI): what it is doing, STOP, UNLOAD, TURN OFF";
  head.insertBefore(stopNow, editor); head.insertBefore(pill, editor);
  var pop = document.createElement("div");
  pop.id = "eng-pop"; pop.hidden = true;
  document.body.appendChild(pop);
  var st = {}, timer = null, acting = false;

  function api(op) {
    return fetch("/api/images", { method: "POST", headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify({ op: op }) }).then(function (r) { return r.json(); });
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function say(m) {
    var t = document.getElementById("toast"); if (!t) return;
    t.textContent = m; t.classList.add("on"); clearTimeout(say.t); say.t = setTimeout(function () { t.classList.remove("on"); }, 3200);
  }
  function label() {
    if (st.remote) return "ENGINE: ON " + String(st.remote).toUpperCase();
    if (!st.running) return st.drawing ? "ENGINE: STARTING" : "ENGINE: OFF";
    var wait = st.waiting_n ? " +" + st.waiting_n + " WAITING" : "";
    if (st.drawing || st.running_n) return "DRAWING" + (st.seconds ? " " + st.seconds + "s" : "") + wait;
    return "ENGINE: READY" + wait + (st.card && st.card.engine_gb ? " · " + st.card.engine_gb + " GB" : "");
  }
  function draw() {
    pill.textContent = label();
    var tabs = document.getElementById("tabs");
    pill.hidden = !!(tabs && tabs.hidden) && !st.running;      // not set up on this computer: nothing to watch
    var drawing = !!(st.drawing || st.running_n || st.waiting_n);
    pill.classList.toggle("drawing", drawing);
    stopNow.hidden = !drawing || !!st.remote;
    if (pop.hidden) return;
    if (st.remote) {
      pop.innerHTML = "<h3>PICTURE ENGINE</h3><p>Pictures are drawn on <b>" + esc(st.remote) + "</b>, with its engine. " +
        "Its own Image Generation window can stop or unload it.</p>";
      return;
    }
    var c = st.card || {};
    pop.innerHTML = "<h3>PICTURE ENGINE (COMFYUI)</h3>" +
      "<p><span class=\"k\">Now:</span> " + (!st.running ? (st.drawing ? "starting up" : "off: the graphics card is free")
        : st.drawing ? "drawing " + esc(st.what || "a picture") + (st.seconds ? ", " + st.seconds + " s so far" : "")
        : st.running_n ? "drawing something sent from the ComfyUI editor" : "ready, nothing being drawn") + "</p>" +
      (st.running ? "<p><span class=\"k\">Queue:</span> " + (st.running_n == null ? "ComfyUI did not say"
        : (st.running_n || 0) + " drawing, " + (st.waiting_n || 0) + " waiting") + "</p>" : "") +
      (c.name ? "<p><span class=\"k\">Graphics card:</span> the engine holds " + c.engine_gb + " GB; " + c.free_gb + " of " + c.total_gb + " GB free</p>" : "") +
      '<div class="row"><button class="btn danger" type="button" data-eng="halt"' + (drawing ? "" : " disabled") + ">STOP</button>" +
      '<button class="btn" type="button" data-eng="unload"' + (st.running && !st.drawing ? "" : " disabled") + ">UNLOAD</button>" +
      '<button class="btn" type="button" data-eng="engine_stop"' + (st.running ? "" : " disabled") + ">TURN OFF</button></div>" +
      '<p class="tip">STOP ends the picture being drawn and clears anything waiting. UNLOAD gives the graphics card back; ' +
      "the engine stays on and the next picture loads its model again. TURN OFF ends the engine; the next picture starts it " +
      "(up to a minute)." + (st.running && st.ours === false ? " This engine was not started by Philibert, so TURN OFF leaves it alone." : "") + "</p>";
  }
  function poll() {
    clearTimeout(timer);
    return api("engine").then(function (d) { if (d && d.ok !== false) st = d; draw(); })
      .catch(function () {}).then(function () {
        var fast = !pop.hidden || st.drawing || st.running_n || st.waiting_n;
        timer = setTimeout(poll, document.hidden ? 15000 : fast ? 1500 : 6000);
      });
  }
  function act(op) {
    if (acting) return;
    acting = true;
    api(op).then(function (d) { say((d && d.msg) || "Done."); })
      .catch(function () { say("Philibert did not answer."); })
      .then(function () { acting = false; poll(); });
  }
  pill.addEventListener("click", function (ev) { ev.stopPropagation(); pop.hidden = !pop.hidden; draw(); poll(); });
  stopNow.addEventListener("click", function () { act("halt"); });
  pop.addEventListener("click", function (ev) {
    ev.stopPropagation();
    var b = ev.target.closest("[data-eng]");
    if (b && !b.disabled) act(b.dataset.eng);
  });
  document.addEventListener("click", function (ev) {
    if (!pop.hidden && !pop.contains(ev.target) && ev.target !== pill) { pop.hidden = true; }
    // a picture was just asked for: show it in the header at once, not at the next slow poll
    if (ev.target.closest && ev.target.closest("#make, #lb-vary, #lb-rf-go, #lb-up")) setTimeout(poll, 400);
  });
  document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
  poll();
})();
