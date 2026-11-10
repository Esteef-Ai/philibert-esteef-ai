// Retro Vault freeze reports: when a running game stops, a small log goes to the drive
// (Entertainment/saves/freeze-reports) for the player to send on. It records the game and the state of
// the emulator, never anything else, and does nothing to the game. A game stuck inside the emulator stops
// this page's timers too, so a worker outside the page watches for its heartbeat.
(function () {
  "use strict";
  const STOP_SECS = 8, HUNG_SECS = 12, HUNG_HIDDEN_SECS = 120, QUEUE = "rv_freeze_queue";
  let win = null, started = 0, lastFrame = -1, lastMove = 0, reported = false, hiddenSince = 0;
  let errors = [], fps = [], fpsFrame = -1, fpsAt = 0, gpu = "", lost = false;

  const frameWin = () => { const f = document.getElementById("emu-iframe"); return f && f.contentWindow; };
  const em = () => { try { return win && win.EJS_emulator; } catch (e) { return null; } };
  const game = () => (activeGameIdx >= 0 ? LIBRARY[activeGameIdx] : null);
  const frames = () => { try { return em().gameManager.getFrameNum(); } catch (e) { return -1; } };

  function send(report) {
    return fetch("/retro/api/freeze-report", { method: "POST", body: JSON.stringify(report) })
      .then(r => { if (!r.ok) throw new Error(r.status); return true; })
      .catch(() => {                // an older server, or a moment's trouble: it goes with the next one
        try {
          const q = JSON.parse(localStorage.getItem(QUEUE) || "[]");
          q.push(report);
          localStorage.setItem(QUEUE, JSON.stringify(q.slice(-10)));
        } catch (e) { /* nothing more to do */ }
        return false;
      });
  }
  function flushQueue() {
    let q = [];
    try { q = JSON.parse(localStorage.getItem(QUEUE) || "[]"); localStorage.removeItem(QUEUE); } catch (e) { return; }
    q.forEach(send);
  }
  function snapshot(kind, extra) {
    const g = game(), e = em(), mod = e && e.Module;
    let contextLost = lost;
    try { const c = win.document.querySelector("canvas"); const gl = c && (c.getContext("webgl2") || c.getContext("webgl")); if (gl) contextLost = gl.isContextLost(); } catch (x) { /* ignore */ }
    return Object.assign({
      kind, at: new Date().toISOString(),
      game: g ? g.title || g.filename : "", file: g ? g.filename : "", system: g ? g.system : "",
      core: (() => { try { return win.EJS_core; } catch (x) { return ""; } })(),
      played_seconds: started ? Math.round((Date.now() - started) / 1000) : 0,
      frame: frames(), recent_fps: fps.slice(-12),
      wasm_mb: mod && mod.HEAPU8 ? Math.round(mod.HEAPU8.length / 1048576) : null,
      js_heap_mb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null,
      context_lost: contextLost, paused: !!(e && e.paused),
      page_visible: document.visibilityState === "visible", window_focused: document.hasFocus(),
      minimized_in_app: !!(document.getElementById("emu-modal") && document.getElementById("emu-modal").classList.contains("emu-bg")),
      online: window._rvNetplay ? "lockstep" : window._rvStreamHost ? "stream host" : "",
      controllers: navigator.getGamepads ? Array.from(navigator.getGamepads()).filter(Boolean).length : 0,
      gpu, browser: navigator.userAgent, errors: errors.slice(-15),
    }, extra || {});
  }
  function report(kind, extra, say) {
    send(snapshot(kind, extra));
    if (say) toast("The game stopped responding. A freeze report was saved in Entertainment\\saves\\freeze-reports", true);
  }

  // ── a new game: listen in its frame ────────────────────────────────────────────
  function watch(w) {
    win = w; started = Date.now(); lastFrame = -1; lastMove = Date.now(); reported = false; hiddenSince = 0;
    errors = []; fps = []; fpsFrame = -1; fpsAt = 0; gpu = ""; lost = false;
    const note = s => { errors.push(new Date().toISOString().slice(11, 19) + " " + String(s).slice(0, 300)); if (errors.length > 40) errors.shift(); };
    try {
      w.addEventListener("error", e => note("error: " + e.message));
      w.addEventListener("unhandledrejection", e => note("rejected: " + (e.reason && e.reason.message || e.reason)));
      const ce = w.console.error.bind(w.console);
      w.console.error = (...a) => { note("console: " + a.join(" ")); ce(...a); };
    } catch (e) { /* the frame went away */ }
  }
  function hookCanvas() {
    try {
      const c = win.document.querySelector("canvas");
      if (!c || c._rvFreeze) return;
      c._rvFreeze = true;
      const gl = c.getContext("webgl2") || c.getContext("webgl");
      const info = gl && gl.getExtension("WEBGL_debug_renderer_info");
      if (info) gpu = String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL));
      c.addEventListener("webglcontextlost", () => { lost = true; report("graphics_lost", {}, true); });
    } catch (e) { /* ignore */ }
  }

  // ── a page lock-up: a worker watches for the heartbeat ─────────────────────────
  let dog = null;
  try {
    const src = `let last=Date.now(),snap=null,limit=${HUNG_SECS},told=false,base="";
onmessage=e=>{const d=e.data;base=d.base||base;
  if(d.off){snap=null;told=false;return;}
  const gap=(Date.now()-last)/1000;
  if(told&&snap)fetch(base+"/retro/api/freeze-report",{method:"POST",body:JSON.stringify(Object.assign({},snap,{kind:"page_recovered",at:new Date().toISOString(),stuck_seconds:Math.round(gap)}))}).catch(()=>{});
  told=false;last=Date.now();snap=d.snap;limit=d.limit;};
setInterval(()=>{if(!snap||told)return;const gap=(Date.now()-last)/1000;if(gap<limit)return;told=true;
  fetch(base+"/retro/api/freeze-report",{method:"POST",body:JSON.stringify(Object.assign({},snap,{kind:"page_hung",at:new Date().toISOString(),note:"This page stopped running. The details are from just before that.",stuck_seconds:Math.round(gap)}))}).catch(()=>{});},2000);`;
    dog = new Worker(URL.createObjectURL(new Blob([src], { type: "application/javascript" })));
  } catch (e) { dog = null; }

  // ── once a second ──────────────────────────────────────────────────────────────
  setInterval(() => {
    const w = game() ? frameWin() : null;
    let ready = false;
    try { ready = !!(w && w._ejsReady && w.EJS_emulator && w.EJS_emulator.gameManager); } catch (e) { /* ignore */ }
    if (!ready) { if (win && dog) dog.postMessage({ off: true }); win = null; return; }
    if (w !== win) watch(w);
    hookCanvas();
    const now = Date.now(), f = frames(), hidden = document.visibilityState !== "visible", e = em();
    if (fpsFrame >= 0 && now - fpsAt >= 10000) { fps.push(Math.round((f - fpsFrame) / ((now - fpsAt) / 1000))); if (fps.length > 30) fps.shift(); fpsFrame = f; fpsAt = now; }
    if (fpsFrame < 0) { fpsFrame = f; fpsAt = now; }
    if (dog) dog.postMessage({ base: location.origin, limit: hidden ? HUNG_HIDDEN_SECS : HUNG_SECS, snap: snapshot("page_hung") });

    const moved = f !== lastFrame;
    if (moved) {
      if (reported) report("game_recovered", { stuck_seconds: Math.round((now - lastMove) / 1000) });
      else if (hiddenSince && now - hiddenSince > 5000) report("paused_in_background", { stuck_seconds: Math.round((now - hiddenSince) / 1000) });
      reported = false; hiddenSince = 0; lastFrame = f; lastMove = now;
      return;
    }
    // not a freeze: paused on purpose, in the background, a lockstep match waiting for a player, or still starting
    if (e.paused || window._rvNetplay || f < 60) { lastMove = now; hiddenSince = 0; return; }
    if (hidden) { hiddenSince = hiddenSince || lastMove; lastMove = now; return; }
    if (!reported && now - lastMove >= STOP_SECS * 1000) {
      reported = true;
      report("game_stopped", { stuck_seconds: Math.round((now - lastMove) / 1000) }, true);
    }
  }, 1000);
  setTimeout(flushQueue, 5000);
})();
