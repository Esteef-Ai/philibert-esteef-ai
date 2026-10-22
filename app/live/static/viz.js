/* Elena Live — board + vault renderer.
 * Reads /api/state every 500ms and turns flows/events into motion.
 * Never invents data motion: a bright pulse on a main trace is always a real flow.
 * Ambient life (the shared heartbeat, sparks, filaments, drift) stays dim and off
 * the main traces, on the board and in the vault alike.
 */
(function () {
  "use strict";

  /* ------------------------------------------------------------------ *
   * Constants
   * ------------------------------------------------------------------ */
  var STATE_URL = window.VIZ_STATE_URL || "/api/state";
  var POLL_MS = 500;

  var NODES = ["in", "cpu", "gpu", "ram", "disk", "out", "net"];
  var NODE_LABEL = {
    in: "IN", cpu: "CPU", gpu: "GPU", ram: "RAM",
    disk: "DISK", out: "OUT", net: "NET"
  };

  var KIND_COLOUR = {
    tokens:  "#00f2fe",
    prefill: "#7c3aed",
    spill:   "#7c3aed",
    io:      "#f59e0b",
    request: "#00f2fe",
    tool:    "#10b981",
    vault_read:  "#00f2fe",
    vault_write: "#10b981",
    vault_update:"#f59e0b"
  };
  function kindColour(k) { return KIND_COLOUR[k] || "#00f2fe"; }

  var FOLDER_PALETTE = [
    "#00f2fe", "#7c3aed", "#f59e0b", "#10b981", "#38bdf8",
    "#f472b6", "#a3e635", "#fb7185", "#818cf8", "#34d399"
  ];

  var TASK_STATE = { idle: "idle", think: "think", code: "code", answer: "answer" };

  /* ------------------------------------------------------------------ *
   * Utilities
   * ------------------------------------------------------------------ */
  function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function hashStr(s) {
    var h = 2166136261;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return (h >>> 0) / 4294967295;
  }
  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function rgb(hex) {
    hex = hex.replace("#", "");
    return [
      parseInt(hex.substr(0, 2), 16),
      parseInt(hex.substr(2, 2), 16),
      parseInt(hex.substr(4, 2), 16)
    ];
  }
  function rgba(hex, a) {
    var c = rgb(hex);
    return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + a + ")";
  }
  function mixHex(a, b, t) {
    var A = rgb(a), B = rgb(b);
    var r = Math.round(lerp(A[0], B[0], t)),
        g = Math.round(lerp(A[1], B[1], t)),
        bl = Math.round(lerp(A[2], B[2], t));
    return "rgb(" + r + "," + g + "," + bl + ")";
  }

  /* ------------------------------------------------------------------ *
   * Board canvas — procedural circuit board
   * ------------------------------------------------------------------ */
  var boardCanvas = document.getElementById("board");
  var bctx = boardCanvas.getContext("2d");
  var boardW = 0, boardH = 0, boardDPR = 1;

  // layout (CSS pixels) of chip centres
  var chipLayout = {};
  var CHIP_W = 150, CHIP_H = 46;

  function layoutChips() {
    var W = boardW, H = boardH;
    var cx = W / 2, cy = H / 2;
    // Keep every chip fully inside the board with a margin, at any window width.
    // The base positions are proportions of the board size; clamp the x so a
    // chip never crosses the left/right edge (half of its width plus a margin).
    var MARGIN = 16;
    var xMin = CHIP_W / 2 + MARGIN;
    var xMax = W - CHIP_W / 2 - MARGIN;
    var yMin = CHIP_H / 2 + MARGIN;
    var yMax = H - CHIP_H / 2 - MARGIN;
    function clampX(v) { return v < xMin ? xMin : (v > xMax ? xMax : v); }
    function clampY(v) { return v < yMin ? yMin : (v > yMax ? yMax : v); }
    // If the board is narrower than two chips side by side, the left and right
    // chips share a single safe column so they do not overlap.
    var narrow = xMax < xMin;
    var colLeft  = narrow ? W / 2 : xMin;
    var colRight = narrow ? W / 2 : xMax;
    // Elena in the centre is handled by the mark canvas; board draws her chip body.
    chipLayout = {
      in:   { x: clampX(colLeft),  y: clampY(H * 0.5) },
      cpu:  { x: clampX(W * 0.27), y: clampY(H * 0.28) },
      gpu:  { x: clampX(W * 0.27), y: clampY(H * 0.72) },
      ram:  { x: clampX(W * 0.50), y: clampY(H * 0.85) },
      disk: { x: clampX(W * 0.73), y: clampY(H * 0.72) },
      out:  { x: clampX(colRight), y: clampY(H * 0.5) },
      net:  { x: clampX(W * 0.73), y: clampY(H * 0.28) }
    };
    chipLayout.elena = { x: clampX(cx), y: clampY(cy) };
  }

  // traces between node pairs (both endpoints exist)
  var tracePairs = [
    ["in", "cpu"], ["cpu", "gpu"], ["cpu", "ram"], ["cpu", "disk"],
    ["cpu", "net"], ["cpu", "elena"],
    ["gpu", "elena"], ["ram", "elena"], ["disk", "elena"], ["net", "elena"],
    ["gpu", "out"], ["ram", "disk"], ["cpu", "out"]
  ];
  var traces = {}; // key -> {path, len}

  function traceKey(a, b) { return a < b ? a + "|" + b : b + "|" + a; }

  function buildTraces() {
    traces = {};
    for (var i = 0; i < tracePairs.length; i++) {
      var p = tracePairs[i];
      traces[traceKey(p[0], p[1])] = makeTrace(p[0], p[1]);
    }
  }

  // right-angled PCB routing: horizontal-then-vertical elbow
  function makeTrace(a, b) {
    var A = chipLayout[a], B = chipLayout[b];
    var pts, len = 0;
    if (Math.abs(A.x - B.x) < 2 || Math.abs(A.y - B.y) < 2) {
      pts = [A, B];
    } else {
      // pick elbow point: go from A horizontally to B's x, then down/up to B
      var e = { x: B.x, y: A.y };
      pts = [A, e, B];
    }
    for (var i = 1; i < pts.length; i++) {
      len += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
    }
    return { pts: pts, len: len, a: a, b: b };
  }

  function pointOn(trace, d) {
    d = clamp(d, 0, trace.len);
    var rem = d;
    for (var i = 1; i < trace.pts.length; i++) {
      var p0 = trace.pts[i - 1], p1 = trace.pts[i];
      var seg = Math.hypot(p1.x - p0.x, p1.y - p0.y);
      if (rem <= seg || i === trace.pts.length - 1) {
        var t = seg === 0 ? 0 : rem / seg;
        return { x: p0.x + (p1.x - p0.x) * t, y: p0.y + (p1.y - p0.y) * t };
      }
      rem -= seg;
    }
    return trace.pts[trace.pts.length - 1];
  }

  // static board texture (drawn once per resize into an offscreen canvas)
  var boardTexture = null;

  function buildBoardTexture() {
    var c = document.createElement("canvas");
    c.width = Math.round(boardW * boardDPR);
    c.height = Math.round(boardH * boardDPR);
    var x = c.getContext("2d");
    x.scale(boardDPR, boardDPR);

    x.clearRect(0, 0, boardW, boardH);

    // faint grid
    x.strokeStyle = "rgba(56,189,248,0.05)";
    x.lineWidth = 1;
    var g = 24;
    for (var gx = g; gx < boardW; gx += g) {
      x.beginPath(); x.moveTo(gx, 0); x.lineTo(gx, boardH); x.stroke();
    }
    for (var gy = g; gy < boardH; gy += g) {
      x.beginPath(); x.moveTo(0, gy); x.lineTo(boardW, gy); x.stroke();
    }

    boardVias = [];
    boardMicro = [];
    // random micro-traces
    var rnd = mulberry32(0xC17C);
    x.lineWidth = 1;
    var count = Math.floor((boardW * boardH) / 9000);
    for (var m = 0; m < count; m++) {
      var sx = rnd() * boardW, sy = rnd() * boardH;
      var horiz = rnd() < 0.5;
      var len2 = 20 + rnd() * 90;
      var ex = horiz ? sx + len2 : sx;
      var ey = horiz ? sy : sy + len2;
      x.strokeStyle = "rgba(0,242,254," + (0.03 + rnd() * 0.05) + ")";
      x.beginPath();
      x.moveTo(sx, sy);
      x.lineTo(ex, sy);
      if (!horiz) x.lineTo(ex, ey);
      x.stroke();
      // via at the start
      x.fillStyle = "rgba(0,242,254," + (0.08 + rnd() * 0.1) + ")";
      x.beginPath(); x.arc(sx, sy, 1.5, 0, Math.PI * 2); x.fill();
      boardVias.push({ x: sx, y: sy, main: false, ph: rnd() * 6.28 });
      boardMicro.push({ sx: sx, sy: sy, ex: ex, ey: ey, len: len2 });
    }

    // main traces along the chip pairs
    for (var key in traces) {
      var tr = traces[key];
      drawPath(x, tr.pts);
      x.strokeStyle = "rgba(0,242,254,0.14)";
      x.lineWidth = 1.2;
      x.stroke();
      // corner via
      for (var pi = 0; pi < tr.pts.length; pi++) {
        x.fillStyle = "rgba(0,242,254,0.22)";
        x.beginPath(); x.arc(tr.pts[pi].x, tr.pts[pi].y, 2.2, 0, Math.PI * 2); x.fill();
        x.fillStyle = "rgba(15,23,42,0.9)";
        x.beginPath(); x.arc(tr.pts[pi].x, tr.pts[pi].y, 1.0, 0, Math.PI * 2); x.fill();
        boardVias.push({ x: tr.pts[pi].x, y: tr.pts[pi].y, main: true, ph: rnd() * 6.28 });
      }
    }

    // small components: resistors/capacitors
    for (var comp = 0; comp < 26; comp++) {
      var rx = rnd() * boardW, ry = rnd() * boardH;
      // avoid chip zones
      if (nearChip(rx, ry)) { comp--; continue; }
      x.fillStyle = "rgba(30,58,138,0.35)";
      x.fillRect(rx, ry, 14, 6);
      x.fillStyle = "rgba(148,163,184,0.4)";
      x.fillRect(rx + 3, ry + 2, 1, 2);
      x.fillRect(rx + 7, ry + 2, 1, 2);
      x.fillRect(rx + 11, ry + 2, 1, 2);
    }

    boardTexture = c;
  }

  function nearChip(px, py) {
    for (var id in chipLayout) {
      var c = chipLayout[id];
      var w = id === "elena" ? 210 : CHIP_W;
      var h = id === "elena" ? 210 : CHIP_H;
      if (Math.abs(px - c.x) < w / 2 + 20 && Math.abs(py - c.y) < h / 2 + 20) return true;
    }
    return false;
  }

  function drawPath(ctx, pts) {
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    for (var i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
  }

  /* --------------------------- pulses ------------------------------- */
  var pulses = []; // {trace, d, speed, colour, size, bright}

  function emitPulse(a, b, kind, bright) {
    var key = traceKey(a, b);
    var tr = traces[key];
    if (!tr) return;
    pulses.push({
      trace: tr,
      d: 0,
      speed: 0.35 + 0.5 * Math.random(),
      colour: kindColour(kind),
      size: bright ? 4.2 : 3.0,
      bright: bright
    });
  }

  function addPulsesForFlow(f) {
    var key = traceKey(f.from, f.to);
    var tr = traces[key];
    if (!tr) return;
    var acc = (flowAccum[key] = (flowAccum[key] || 0)) + f.rate * (POLL_MS / 1000);
    var interval = 0.45 - 0.30 * f.rate; // higher rate -> more frequent
    if (acc >= interval) {
      acc -= interval;
      pulses.push({
        trace: tr,
        d: 0,
        speed: 0.45 + 0.6 * f.rate + 0.25 * Math.random(),
        colour: kindColour(f.kind),
        size: 2.6 + 1.6 * f.rate,
        bright: false
      });
    }
    flowAccum[key] = acc;
  }
  var flowAccum = {};

  /* --------------------------- chips -------------------------------- */
  var chipState = {};
  function ensureChip(id) {
    if (!chipState[id]) chipState[id] = { line1: "—", line2: "—", load: 0, loadT: 0 };
    return chipState[id];
  }

  function updateChipTexts(state) {
    var n = state.nodes || {};
    // IN: requests arriving
    var inF = findFlow(state.flows, "in", "cpu");
    var inC = ensureChip("in");
    inC.line1 = "IN";
    inC.line2 = inF ? "req" : "idle";

    // CPU
    var cpu = n.cpu;
    if (cpu && typeof cpu.load === "number") {
      var cc = ensureChip("cpu");
      cc.line1 = "CPU " + Math.round(cpu.load) + "%";
      cc.line2 = cpu.load >= 80 ? "hot" : (cpu.load >= 10 ? "load" : "idle");
      cc.load = cpu.load / 100;
      cc.loadT = 1;
    }

    // GPU
    var gpu = n.gpu;
    if (gpu) {
      var gc = ensureChip("gpu");
      gc.line1 = "GPU " + Math.round(gpu.load) + "%";
      var vt = gpu.vram_total_gb ? (gpu.vram_total_gb / (gpu.vram_used_gb || 0) > 100 ? gpu.vram_total_gb.toFixed(1) : (gpu.vram_total_gb || 0).toFixed(1)) : "0.0";
      gc.line2 = (gpu.vram_used_gb || 0).toFixed(1) + "/" + vt + " GB";
      gc.load = (gpu.load || 0) / 100;
      gc.loadT = 1;
    }

    // RAM
    var ram = n.ram;
    if (ram) {
      var rc = ensureChip("ram");
      var pct = ram.total_gb ? Math.round(100 * ram.used_gb / ram.total_gb) : 0;
      rc.line1 = "RAM " + pct + "%";
      rc.line2 = (ram.used_gb || 0).toFixed(1) + "/" + (ram.total_gb || 0).toFixed(1) + " GB";
      rc.load = ram.total_gb ? clamp(ram.used_gb / ram.total_gb, 0, 1) : 0;
      rc.loadT = 1;
    }

    // DISK
    var d = n.disk;
    if (d) {
      var dc = ensureChip("disk");
      dc.line1 = "DISK";
      dc.line2 = (d.read_mbps || 0).toFixed(1) + "r " + (d.write_mbps || 0).toFixed(1) + "w";
      dc.load = clamp((d.read_mbps + d.write_mbps) / 2000, 0, 1);
      dc.loadT = 1;
    }

    // OUT: tokens
    var outF = findFlow(state.flows, "gpu", "out");
    var oc = ensureChip("out");
    oc.line1 = "OUT";
    oc.line2 = outF ? "tok" : "idle";

    // NET
    var netF = findFlow(state.flows, "net", "cpu") || findFlow(state.flows, "cpu", "net");
    var nc = ensureChip("net");
    nc.line1 = "NET";
    nc.line2 = netF ? "act" : "idle";
  }

  function findFlow(flows, a, b) {
    if (!flows) return null;
    for (var i = 0; i < flows.length; i++) {
      if ((flows[i].from === a && flows[i].to === b) ||
          (flows[i].from === b && flows[i].to === a)) return flows[i];
    }
    return null;
  }

  /* ------------------------------------------------------------------ *
   * Board draw
   * ------------------------------------------------------------------ */
  function resizeBoard() {
    var rect = boardCanvas.parentElement.getBoundingClientRect();
    boardW = Math.max(320, rect.width);
    boardH = Math.max(240, rect.height);
    boardDPR = window.devicePixelRatio || 1;
    boardCanvas.width = Math.round(boardW * boardDPR);
    boardCanvas.height = Math.round(boardH * boardDPR);
    boardCanvas.style.width = boardW + "px";
    boardCanvas.style.height = boardH + "px";
    bctx.setTransform(boardDPR, 0, 0, boardDPR, 0, 0);
    layoutChips();
    buildTraces();
    buildBoardTexture();
  }

  /* ---------- the living substrate ---------- */
  var boardVias = [], boardMicro = [], boardSparks = [], boardFilaments = [];
  var boardDust = null, chipBeat = {}, lastBoardT = 0, nextBoardSpark = 0;

  // heartbeat strength at distance d from Elena (the same clock as the vault)
  function boardBeatAt(d, r1, r2, fade) {
    var w1 = (d - r1) / 40, w2 = r2 > 0 ? (d - r2) / 40 : 9;
    return (Math.exp(-w1 * w1) + 0.6 * Math.exp(-w2 * w2)) * fade;
  }

  function liveBoard() {
    var ctx = bctx, W = boardW, H = boardH;
    var now = performance.now() / 1000;
    var dt = Math.min(0.05, lastBoardT ? now - lastBoardT : 0.016);
    lastBoardT = now;
    var core = chipLayout.elena;
    if (!core || REDUCED_MOTION) { chipBeat = {}; return; }

    var reach = Math.max(Math.hypot(core.x, core.y), Math.hypot(W - core.x, H - core.y),
                         Math.hypot(core.x, H - core.y), Math.hypot(W - core.x, core.y));
    var ph = (now % BEAT_PERIOD) / BEAT_PERIOD;
    var r1 = ph * reach * 1.15, r2 = (ph - 0.07) * reach * 1.15;
    var fade = Math.max(0, 1 - ph * 0.9);

    ctx.globalCompositeOperation = "lighter";

    // drifting dust
    if (!boardDust) {
      var rnd = mulberry32(31);
      boardDust = [];
      for (var i = 0; i < 46; i++) {
        boardDust.push({ x: rnd(), y: rnd(), v: 0.004 + rnd() * 0.01, s: 0.5 + rnd() * 1.1,
                         ph: rnd() * 6.28, sw: rnd() * 6.28 });
      }
    }
    for (var di = 0; di < boardDust.length; di++) {
      var m = boardDust[di];
      m.y -= m.v * dt;
      if (m.y < -0.02) { m.y = 1.02; m.x = Math.random(); }
      var mx = (m.x + 0.012 * Math.sin(now * 0.2 + m.sw)) * W, my = m.y * H;
      ctx.fillStyle = "rgba(170,225,255," + (0.07 + 0.08 * (0.5 + 0.5 * Math.sin(now * 0.9 + m.ph))) + ")";
      ctx.fillRect(mx, my, m.s, m.s);
    }

    // the heartbeat wavefront leaving Elena
    ctx.lineWidth = 1.2;
    ctx.strokeStyle = "rgba(0,242,254," + (0.10 * fade) + ")";
    ctx.beginPath(); ctx.arc(core.x, core.y, r1, 0, Math.PI * 2); ctx.stroke();
    if (r2 > 0) {
      ctx.strokeStyle = "rgba(0,242,254," + (0.06 * fade) + ")";
      ctx.beginPath(); ctx.arc(core.x, core.y, r2, 0, Math.PI * 2); ctx.stroke();
    }

    // main traces warm as the beat crosses them
    for (var key in traces) {
      var tr = traces[key], bsum = 0;
      for (var tp = 0; tp < tr.pts.length; tp++) {
        bsum += boardBeatAt(Math.hypot(tr.pts[tp].x - core.x, tr.pts[tp].y - core.y), r1, r2, fade);
      }
      var tb = bsum / tr.pts.length;
      if (tb < 0.03) continue;
      drawPath(ctx, tr.pts);
      ctx.strokeStyle = "rgba(0,242,254," + (0.16 * tb) + ")";
      ctx.lineWidth = 2.2;
      ctx.stroke();
    }

    // vias light as the beat passes, and twinkle now and then on their own
    for (var vi = 0; vi < boardVias.length; vi++) {
      var v = boardVias[vi];
      var b = boardBeatAt(Math.hypot(v.x - core.x, v.y - core.y), r1, r2, fade);
      var tw = Math.pow(Math.max(0, Math.sin(now * 0.55 + v.ph * 3)), 24) * 0.5;
      var a = b * (v.main ? 0.9 : 0.65) + tw;
      if (a < 0.02) continue;
      var sz = (v.main ? 14 : 10) + b * 12;
      ctx.globalAlpha = Math.min(1, a);
      ctx.drawImage(glowSprite("#00f2fe"), v.x - sz / 2, v.y - sz / 2, sz, sz);
    }
    ctx.globalAlpha = 1;

    // filaments of light that form and fade between nearby vias
    while (boardFilaments.length < 10 && boardVias.length > 2) {
      var fa = boardVias[Math.floor(Math.random() * boardVias.length)], fb = null;
      for (var tries = 0; tries < 14 && !fb; tries++) {
        var c = boardVias[Math.floor(Math.random() * boardVias.length)];
        var dd = Math.hypot(c.x - fa.x, c.y - fa.y);
        if (c !== fa && dd > 60 && dd < 220) fb = c;
      }
      if (!fb) break;
      boardFilaments.push({ a: fa, b: fb, born: now, life: 4 + Math.random() * 4,
                            bend: (Math.random() - 0.5) * 0.6 });
    }
    for (var fi = boardFilaments.length - 1; fi >= 0; fi--) {
      var f = boardFilaments[fi], age = (now - f.born) / f.life;
      if (age >= 1) { boardFilaments.splice(fi, 1); continue; }
      var fx = (f.a.x + f.b.x) / 2 - (f.b.y - f.a.y) * f.bend;
      var fy = (f.a.y + f.b.y) / 2 + (f.b.x - f.a.x) * f.bend;
      var fal = Math.sin(Math.PI * age);
      ctx.strokeStyle = "rgba(120,200,255," + (0.22 * fal) + ")";
      ctx.lineWidth = 0.9;
      ctx.beginPath();
      ctx.moveTo(f.a.x, f.a.y);
      ctx.quadraticCurveTo(fx, fy, f.b.x, f.b.y);
      ctx.stroke();
      // a mote rides the filament while it is lit
      var u = (age * 1.6) % 1, iu = 1 - u;
      var px = iu * iu * f.a.x + 2 * iu * u * fx + u * u * f.b.x;
      var py = iu * iu * f.a.y + 2 * iu * u * fy + u * u * f.b.y;
      ctx.globalAlpha = 0.55 * fal;
      ctx.drawImage(glowSprite("#7dd3fc"), px - 5, py - 5, 10, 10);
      ctx.globalAlpha = 1;
    }

    // faint sparks crawling the micro-traces
    if (now > nextBoardSpark && boardMicro.length) {
      nextBoardSpark = now + 0.22 + Math.random() * 0.45;
      if (boardSparks.length < 22) {
        boardSparks.push({ m: boardMicro[Math.floor(Math.random() * boardMicro.length)],
                           t: 0, speed: 0.35 + Math.random() * 0.45 });
      }
    }
    for (var si = boardSparks.length - 1; si >= 0; si--) {
      var sp = boardSparks[si];
      sp.t += sp.speed * dt;
      if (sp.t >= 1) { boardSparks.splice(si, 1); continue; }
      var mm = sp.m;
      var sx = mm.sx + (mm.ex - mm.sx) * sp.t, sy = mm.sy + (mm.ey - mm.sy) * sp.t;
      ctx.globalAlpha = 0.6 * Math.sin(Math.PI * sp.t);
      ctx.drawImage(glowSprite("#22d3ee"), sx - 5, sy - 5, 10, 10);
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";

    // how strongly the beat touches each chip right now
    chipBeat = {};
    for (var id in chipLayout) {
      var cp = chipLayout[id];
      chipBeat[id] = boardBeatAt(Math.hypot(cp.x - core.x, cp.y - core.y), r1, r2, fade);
    }
  }

  function drawBoard() {
    bctx.clearRect(0, 0, boardW, boardH);
    if (boardTexture) bctx.drawImage(boardTexture, 0, 0, boardW, boardH);
    liveBoard();

    // live trace glow: traces carrying a flow glow brighter
    if (lastState) {
      for (var i = 0; i < lastState.flows.length; i++) {
        var f = lastState.flows[i];
        var key = traceKey(f.from, f.to);
        var tr = traces[key];
        if (!tr) continue;
        drawPath(bctx, tr.pts);
        bctx.strokeStyle = rgba(kindColour(f.kind), 0.10 + 0.30 * f.rate);
        bctx.lineWidth = 1.5 + 2.5 * f.rate;
        bctx.shadowColor = kindColour(f.kind);
        bctx.shadowBlur = 10 * f.rate;
        bctx.stroke();
        bctx.shadowBlur = 0;
      }
    }

    // pulses
    for (var p = pulses.length - 1; p >= 0; p--) {
      var pl = pulses[p];
      pl.d += pl.speed * (POLL_MS / 1000) * 60; // ~units per second scaled
      if (pl.d >= pl.trace.len) { pulses.splice(p, 1); continue; }
      var pos = pointOn(pl.trace, pl.d);
      bctx.beginPath();
      bctx.arc(pos.x, pos.y, pl.size, 0, Math.PI * 2);
      bctx.fillStyle = pl.bright ? "#ffffff" : pl.colour;
      bctx.shadowColor = pl.colour;
      bctx.shadowBlur = pl.bright ? 16 : 8;
      bctx.fill();
      bctx.shadowBlur = 0;
    }

    // chips
    for (var id in chipLayout) {
      if (id === "elena") continue;
      drawChip(id, chipLayout[id]);
    }
  }

  function drawChip(id, pos) {
    var st = ensureChip(id);
    var w = CHIP_W, h = CHIP_H;
    var x = pos.x - w / 2, y = pos.y - h / 2;

    // body
    bctx.fillStyle = "rgba(15,23,42,0.92)";
    roundRect(bctx, x, y, w, h, 6);
    bctx.fill();

    var beat = chipBeat[id] || 0;
    var breath = REDUCED_MOTION ? 0 : 0.5 + 0.5 * Math.sin(performance.now() / 1000 * 0.9 + hashStr(id) * 6.28);
    var lift = Math.min(1, (st.loadT > 0.05 ? st.load : 0) + beat * 0.45 + breath * 0.12);
    var border = mixHex("#1e3a5f", kindColourForChip(id), lift);
    bctx.strokeStyle = border;
    bctx.lineWidth = 1.4;
    bctx.shadowColor = kindColourForChip(id);
    bctx.shadowBlur = 8 * (st.loadT > 0.05 ? st.load : 0) + 3 * breath + 12 * beat;
    roundRect(bctx, x, y, w, h, 6);
    bctx.stroke();
    bctx.shadowBlur = 0;

    // pin stubs
    bctx.strokeStyle = "rgba(0,242,254,0.25)";
    bctx.lineWidth = 1;
    for (var px = x + 10; px < x + w - 6; px += 14) {
      bctx.beginPath(); bctx.moveTo(px, y); bctx.lineTo(px, y - 4); bctx.stroke();
      bctx.beginPath(); bctx.moveTo(px, y + h); bctx.lineTo(px, y + h + 4); bctx.stroke();
    }

    // text
    bctx.textAlign = "left";
    bctx.fillStyle = "#d7e3f4";
    bctx.font = "600 12px 'JetBrains Mono', monospace";
    bctx.fillText(st.line1, x + 12, y + 19);
    bctx.fillStyle = "rgba(142,163,196,0.9)";
    bctx.font = "11px 'JetBrains Mono', monospace";
    bctx.fillText(st.line2, x + 12, y + 35);

    // load bar
    if (st.loadT > 0.02) {
      bctx.fillStyle = "rgba(30,58,95,0.6)";
      bctx.fillRect(x + 12, y + h - 5, w - 24, 2);
      bctx.fillStyle = kindColourForChip(id);
      bctx.fillRect(x + 12, y + h - 5, (w - 24) * st.load, 2);
    }
  }

  function kindColourForChip(id) {
    if (id === "gpu" || id === "ram") return "#7c3aed";
    if (id === "disk") return "#f59e0b";
    return "#00f2fe";
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  /* ------------------------------------------------------------------ *
   * Vault panel — interactive constellation graph
   *
   * World space is centred on 0,0 and a camera (pan + zoom) maps it onto
   * the panel. Notes gather by folder; each folder glows as a faint nebula
   * under its notes. Drag a note to move it, drag empty space to pan,
   * wheel or pinch to zoom, hover for a note's name and links, click to
   * focus its neighbourhood, double-click to frame the whole vault again.
   * ------------------------------------------------------------------ */
  var vaultCanvas = document.getElementById("vault-canvas");
  var vctx = vaultCanvas.getContext("2d");
  var vaultPanel = document.getElementById("vault-panel");
  var vaultW = 0, vaultH = 0, vaultDPR = 1;

  var vaultNotes = [];      // node objects
  var vaultLinks = [];      // {a, b, key, bend, col}
  var vaultById = {};
  var vaultLinksByNote = {};
  var vaultGroups = {};     // folder -> {x, y, spread, n, col, label}
  var groupColour = {};     // folder -> colour, stable once assigned
  var maxDegree = 1;

  var VAULT_PALETTE = [
    "#22d3ee", "#a78bfa", "#f472b6", "#34d399", "#fbbf24",
    "#60a5fa", "#fb7185", "#2dd4bf", "#c084fc", "#facc15",
    "#38bdf8", "#4ade80"
  ];
  var OP_COLOUR = { read: "#00f2fe", write: "#10b981", update: "#f59e0b" };
  var REDUCED_MOTION = !!(window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  function folderOf(id) {
    var i = id.lastIndexOf("/");
    return i < 0 ? "" : id.substr(0, i);
  }
  function folderLabel(folder) {
    if (!folder) return "VAULT";
    var i = folder.lastIndexOf("/");
    return (i < 0 ? folder : folder.substr(i + 1)).replace(/^\d+\s+/, "").toUpperCase();
  }
  function setVaultCount(n) {
    var vc = document.getElementById("vault-count");
    if (!vc) return;
    var b = vc.querySelector("b");
    if (b) b.textContent = String(n); else vc.textContent = String(n);
  }

  function ingestVaultGraph(g) {
    if (!g || !g.notes) return;
    var seen = {};
    var addedNew = false;
    for (var i = 0; i < g.notes.length; i++) {
      var n = g.notes[i];
      seen[n.id] = true;
      if (!vaultById[n.id]) {
        var node = {
          id: n.id,
          title: n.title || n.id.replace(/\.md$/, ""),
          folder: n.folder || folderOf(n.id),
          type: n.type || "",
          links: n.links || [],
          mtime: n.mtime || 0,
          x: 0, y: 0, vx: 0, vy: 0,
          fx: null, fy: null,
          r: 2, deg: 0, col: VAULT_PALETTE[0], hub: false,
          phase: hashStr(n.id + "p") * Math.PI * 2,
          lit: 0,         // 0..1 glow
          litOp: null,    // read | write | update
          ringT: 0,       // 0..1 expanding ring
          halo: 0         // 0..1 fading halo (30s)
        };
        // seed near the note's folder if it already has notes, else inside a disc
        var grp = vaultGroups[node.folder];
        var ang = hashStr(n.id) * Math.PI * 2;
        var rad = grp ? 12 + hashStr(n.id + "r") * 30
                      : Math.sqrt(hashStr(n.id + "r")) * 260;
        node.x = (grp ? grp.x : 0) + Math.cos(ang) * rad;
        node.y = (grp ? grp.y : 0) + Math.sin(ang) * rad;
        vaultNotes.push(node);
        vaultById[n.id] = node;
        addedNew = true;
      } else {
        var ex = vaultById[n.id];
        ex.links = n.links || [];
        ex.title = n.title || ex.title;
        ex.folder = n.folder || ex.folder;
        ex.type = n.type || ex.type;
        ex.mtime = n.mtime || ex.mtime;
      }
    }
    // drop notes that no longer exist
    vaultNotes = vaultNotes.filter(function (nd) { return seen[nd.id]; });
    for (var k in vaultById) if (!seen[k]) delete vaultById[k];
    if (vaultFocus && !vaultById[vaultFocus.id]) vaultFocus = null;
    if (vaultHover && !vaultById[vaultHover.id]) vaultHover = null;

    // folder colours: largest folders first, each keeps its colour for good
    var sizes = {};
    for (var s = 0; s < vaultNotes.length; s++) {
      var f = vaultNotes[s].folder;
      sizes[f] = (sizes[f] || 0) + 1;
    }
    var used = {};
    for (var uf in groupColour) used[groupColour[uf]] = (used[groupColour[uf]] || 0) + 1;
    Object.keys(sizes).sort(function (x, y) { return sizes[y] - sizes[x]; }).forEach(function (fo) {
      if (groupColour[fo]) return;
      var best = VAULT_PALETTE[0], bestUse = 1e9;
      for (var p = 0; p < VAULT_PALETTE.length; p++) {
        var u = used[VAULT_PALETTE[p]] || 0;
        if (u < bestUse) { best = VAULT_PALETTE[p]; bestUse = u; }
      }
      groupColour[fo] = best;
      used[best] = bestUse + 1;
    });

    // links: real wikilinks only, each pair once
    vaultLinks = [];
    vaultLinksByNote = {};
    var keys = {};
    for (var m = 0; m < vaultNotes.length; m++) vaultLinksByNote[vaultNotes[m].id] = [];
    for (var j = 0; j < vaultNotes.length; j++) {
      var src = vaultNotes[j];
      for (var li = 0; li < src.links.length; li++) {
        var tgtId = src.links[li];
        if (!vaultById[tgtId] || tgtId === src.id) continue;
        var key2 = src.id < tgtId ? src.id + "|" + tgtId : tgtId + "|" + src.id;
        if (keys[key2]) continue;
        keys[key2] = true;
        var link = { a: src, b: vaultById[tgtId], key: key2,
                     bend: (hashStr(key2) - 0.5) * 2, col: null };
        vaultLinks.push(link);
        vaultLinksByNote[src.id].push(link);
        vaultLinksByNote[tgtId].push(link);
      }
    }

    // size by degree; hubs are maps of content or the most-linked notes
    maxDegree = 1;
    for (var d = 0; d < vaultNotes.length; d++) {
      var nd = vaultNotes[d];
      nd.deg = vaultLinksByNote[nd.id].length;
      if (nd.deg > maxDegree) maxDegree = nd.deg;
    }
    for (var e = 0; e < vaultNotes.length; e++) {
      var ne = vaultNotes[e];
      ne.col = groupColour[ne.folder] || VAULT_PALETTE[0];
      ne.hub = ne.type === "moc" || ne.deg >= Math.max(8, maxDegree * 0.35);
      ne.r = 1.4 + 3.6 * Math.sqrt(ne.deg / maxDegree) + (ne.hub ? 0.6 : 0);
    }
    for (var q = 0; q < vaultLinks.length; q++) {
      var lq = vaultLinks[q];
      lq.col = lq.a.folder === lq.b.folder ? lq.a.col : mixHexToHex(lq.a.col, lq.b.col, 0.5);
    }
    updateGroups();
    setVaultCount(vaultNotes.length);
    if (addedNew) { sim.alpha = 1; cam.snap = cam.auto; }
    return addedNew;
  }

  var linkSet = {};
  function linkExists(k) { return linkSet[k]; }
  // keep linkSet in sync after rebuild
  function rebuildLinkSet() {
    linkSet = {};
    for (var i = 0; i < vaultLinks.length; i++) linkSet[vaultLinks[i].key] = true;
  }

  function resizeVault() {
    var rect = vaultCanvas.getBoundingClientRect();
    vaultW = Math.max(80, rect.width);
    vaultH = Math.max(80, rect.height);
    vaultDPR = window.devicePixelRatio || 1;
    vaultCanvas.width = Math.round(vaultW * vaultDPR);
    vaultCanvas.height = Math.round(vaultH * vaultDPR);
    vctx.setTransform(vaultDPR, 0, 0, vaultDPR, 0, 0);
  }

  /* ---------- camera ---------- */
  var cam = { x: 0, y: 0, k: 1, auto: true, snap: true };
  function toScreenX(x) { return (x - cam.x) * cam.k + vaultW / 2; }
  function toScreenY(y) { return (y - cam.y) * cam.k + vaultH / 2; }
  function toWorldX(sx) { return (sx - vaultW / 2) / cam.k + cam.x; }
  function toWorldY(sy) { return (sy - vaultH / 2) / cam.k + cam.y; }
  // how much on-screen size grows with zoom: slower than spacing, so zooming
  // in opens the space between notes instead of just enlarging them
  function sizeScale() { return Math.pow(cam.k, 0.55); }

  function frameVault() {
    if (!vaultNotes.length) return;
    // frame the body of the vault, not a stray note at the edge
    var xs = [], ys = [];
    for (var i = 0; i < vaultNotes.length; i++) { xs.push(vaultNotes[i].x); ys.push(vaultNotes[i].y); }
    xs.sort(function (a, b) { return a - b; });
    ys.sort(function (a, b) { return a - b; });
    var lo = Math.floor((xs.length - 1) * 0.04), hi = Math.ceil((xs.length - 1) * 0.96);
    var x0 = xs[lo], x1 = xs[hi], y0 = ys[lo], y1 = ys[hi];
    var mx = (x1 - x0) * 0.08, my = (y1 - y0) * 0.08;
    x0 -= mx; x1 += mx; y0 -= my; y1 += my;
    var pad = 24;
    var k = Math.min((vaultW - pad * 2) / Math.max(40, x1 - x0),
                     (vaultH - pad * 2) / Math.max(40, y1 - y0));
    k = clamp(k, 0.12, 3);
    var gx = (x0 + x1) / 2, gy = (y0 + y1) / 2;
    if (cam.snap) { cam.x = gx; cam.y = gy; cam.k = k; cam.snap = false; return; }
    cam.x += (gx - cam.x) * 0.06;
    cam.y += (gy - cam.y) * 0.06;
    cam.k += (k - cam.k) * 0.06;
  }

  /* ---------- simulation (d3-style forces with cooling) ---------- */
  var sim = { alpha: 1, target: 0 };
  var ALPHA_DECAY = 0.0228;
  var ALPHA_FLOOR = REDUCED_MOTION ? 0 : 0.004;   // a breath of life, never frozen

  function updateGroups() {
    var acc = {};
    for (var i = 0; i < vaultNotes.length; i++) {
      var n = vaultNotes[i];
      var a = acc[n.folder] || (acc[n.folder] = { x: 0, y: 0, n: 0, pts: [] });
      a.x += n.x; a.y += n.y; a.n++; a.pts.push(n);
    }
    var out = {};
    for (var f in acc) {
      var g = acc[f];
      var cx = g.x / g.n, cy = g.y / g.n, sp = 0;
      for (var j = 0; j < g.pts.length; j++) {
        var dx = g.pts[j].x - cx, dy = g.pts[j].y - cy;
        sp += Math.sqrt(dx * dx + dy * dy);
      }
      out[f] = { x: cx, y: cy, n: g.n, spread: g.n ? sp / g.n : 0,
                 col: groupColour[f] || VAULT_PALETTE[0], label: folderLabel(f) };
    }
    vaultGroups = out;
  }

  function stepVault(dt) {
    var n = vaultNotes.length;
    sim.alpha += (sim.target - sim.alpha) * ALPHA_DECAY;
    var alpha = Math.max(sim.alpha, ALPHA_FLOOR);
    if (n && alpha > 0) {
      // many-body repulsion
      for (var r = 0; r < n; r++) {
        var p = vaultNotes[r];
        for (var s = r + 1; s < n; s++) {
          var q = vaultNotes[s];
          var dx = q.x - p.x, dy = q.y - p.y;
          var l = dx * dx + dy * dy;
          if (l > 90000) continue;
          if (l < 4) l = 4;
          var w = -70 * alpha / l;
          p.vx += dx * w; p.vy += dy * w;
          q.vx -= dx * w; q.vy -= dy * w;
        }
      }
      // links: short inside a folder, longer across folders
      for (var li = 0; li < vaultLinks.length; li++) {
        var lk = vaultLinks[li], A = lk.a, B = lk.b;
        var ca = A.deg || 1, cb = B.deg || 1;
        var lx = B.x + B.vx - A.x - A.vx, ly = B.y + B.vy - A.y - A.vy;
        var ll = Math.sqrt(lx * lx + ly * ly) || 1;
        var rest = A.folder === B.folder ? 34 : 80;
        var k = (ll - rest) / ll * alpha / Math.min(ca, cb) * 0.9;
        lx *= k; ly *= k;
        var bias = ca / (ca + cb);
        B.vx -= lx * bias; B.vy -= ly * bias;
        A.vx += lx * (1 - bias); A.vy += ly * (1 - bias);
      }
      // folder cohesion + a weak pull to the middle
      for (var c = 0; c < n; c++) {
        var nd = vaultNotes[c], g = vaultGroups[nd.folder];
        if (g && g.n > 1) {
          nd.vx += (g.x - nd.x) * 0.035 * alpha;
          nd.vy += (g.y - nd.y) * 0.035 * alpha;
        }
        var pull = nd.deg ? 0.018 : 0.06;   // unlinked notes would drift off
        nd.vx -= nd.x * pull * alpha;
        nd.vy -= nd.y * pull * alpha;
      }
      // soft collision so dots never sit on each other
      for (var a1 = 0; a1 < n; a1++) {
        var u = vaultNotes[a1];
        for (var b1 = a1 + 1; b1 < n; b1++) {
          var v = vaultNotes[b1];
          var cx = v.x - u.x, cy = v.y - u.y, min = u.r + v.r + 5;
          var c2 = cx * cx + cy * cy;
          if (c2 < min * min && c2 > 0.0001) {
            var cd = Math.sqrt(c2), push = (min - cd) / cd * 0.35;
            u.x -= cx * push; u.y -= cy * push;
            v.x += cx * push; v.y += cy * push;
          }
        }
      }
      // integrate
      for (var m = 0; m < n; m++) {
        var o = vaultNotes[m];
        if (o.fx !== null) { o.x = o.fx; o.y = o.fy; o.vx = 0; o.vy = 0; continue; }
        o.vx *= 0.6; o.vy *= 0.6;
        o.x += o.vx; o.y += o.vy;
      }
      updateGroups();
    }
    // decay lighting
    for (var z = 0; z < n; z++) {
      var ln = vaultNotes[z];
      if (ln.lit > 0) ln.lit = Math.max(0, ln.lit - dt / 1.2);
      if (ln.ringT > 0) ln.ringT = Math.max(0, ln.ringT - dt / 0.9);
      if (ln.halo > 0) ln.halo = Math.max(0, ln.halo - dt / 30);
    }
    stepPulses(dt);
  }

  /* ---------- light pulses along links ---------- */
  var vaultPulses = [];
  var nextAmbient = 0;
  function spawnPulse(link, fromNote, col, speed) {
    if (vaultPulses.length > 60) return;
    vaultPulses.push({ link: link, t: 0, fwd: link.a === fromNote,
                       col: col || link.col, speed: speed || 0.6 });
  }
  function stepPulses(dt) {
    var now = performance.now() / 1000;
    if (!REDUCED_MOTION && vaultLinks.length && now > nextAmbient) {
      nextAmbient = now + 0.35 + Math.random() * 0.9;
      var lk = vaultLinks[Math.floor(Math.random() * vaultLinks.length)];
      spawnPulse(lk, Math.random() < 0.5 ? lk.a : lk.b, null, 0.25 + Math.random() * 0.25);
    }
    for (var i = vaultPulses.length - 1; i >= 0; i--) {
      var p = vaultPulses[i];
      p.t += dt * p.speed;
      if (p.t >= 1 || !vaultById[p.link.a.id] || !vaultById[p.link.b.id]) vaultPulses.splice(i, 1);
    }
  }

  /* ---------- drawing helpers ---------- */
  var glowCache = {};
  function glowSprite(col) {
    if (glowCache[col]) return glowCache[col];
    var c = document.createElement("canvas");
    c.width = c.height = 64;
    var g = c.getContext("2d");
    var grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, rgba(col, 0.85));
    grad.addColorStop(0.18, rgba(col, 0.35));
    grad.addColorStop(0.5, rgba(col, 0.08));
    grad.addColorStop(1, rgba(col, 0));
    g.fillStyle = grad;
    g.fillRect(0, 0, 64, 64);
    glowCache[col] = c;
    return c;
  }
  // control point of a link's gentle arc, in screen space
  function linkCurve(lk) {
    var ax = lk.a.sx != null ? lk.a.sx : toScreenX(lk.a.x);
    var ay = lk.a.sy != null ? lk.a.sy : toScreenY(lk.a.y);
    var bx = lk.b.sx != null ? lk.b.sx : toScreenX(lk.b.x);
    var by = lk.b.sy != null ? lk.b.sy : toScreenY(lk.b.y);
    var mx = (ax + bx) / 2, my = (ay + by) / 2;
    var dx = bx - ax, dy = by - ay;
    var bend = lk.bend + (REDUCED_MOTION ? 0 : 0.22 * Math.sin(liveNow * 0.55 + lk.bend * 7));
    return { ax: ax, ay: ay, bx: bx, by: by,
             cx: mx - dy * 0.12 * bend, cy: my + dx * 0.12 * bend };
  }
  var liveNow = 0;
  function bezier(c, t) {
    var u = 1 - t;
    return { x: u * u * c.ax + 2 * u * t * c.cx + t * t * c.bx,
             y: u * u * c.ay + 2 * u * t * c.cy + t * t * c.by };
  }
  var stars = null;
  function makeStars() {
    var rnd = mulberry32(7);
    stars = [];
    for (var i = 0; i < 140; i++) {
      stars.push({ x: rnd(), y: rnd(), r: 0.3 + rnd() * 0.9, tw: rnd() * 6.28, depth: 0.15 + rnd() * 0.35 });
    }
  }
  /* ---------- the living layer ----------
     Drawing only: the vault breathes, a lub-dub heartbeat travels out from its
     centre, notes drift and swell, links sway. Computed once per frame into
     nd.sx / nd.sy / nd.swell / nd.beat so links, pulses and notes agree. */
  var BEAT_PERIOD = 6.5;
  function liveVault(now) {
    var n = vaultNotes.length;
    if (!n) return;
    var cx = 0, cy = 0;
    for (var i = 0; i < n; i++) { cx += vaultNotes[i].x; cy += vaultNotes[i].y; }
    cx /= n; cy /= n;
    var maxD = 1;
    for (var j = 0; j < n; j++) {
      var dj = Math.hypot(vaultNotes[j].x - cx, vaultNotes[j].y - cy);
      vaultNotes[j]._d = dj;
      if (dj > maxD) maxD = dj;
    }
    var still = REDUCED_MOTION;
    var ph = (now % BEAT_PERIOD) / BEAT_PERIOD;
    var reach = maxD + 80;
    var r1 = ph * reach * 1.25, r2 = (ph - 0.07) * reach * 1.25;   // lub, then dub
    var fadeBeat = Math.max(0, 1 - ph * 0.9);
    var breath = still ? 1 : 1 + 0.014 * Math.sin(now * 2 * Math.PI / 7.8);
    var scx = toScreenX(cx), scy = toScreenY(cy);
    var drift = Math.min(1.8, 0.9 * sizeScale() + 0.4);
    for (var k = 0; k < n; k++) {
      var nd = vaultNotes[k], d = nd._d;
      var x = toScreenX(nd.x), y = toScreenY(nd.y);
      if (still) { nd.sx = x; nd.sy = y; nd.swell = 1; nd.beat = 0; continue; }
      x = scx + (x - scx) * breath;
      y = scy + (y - scy) * breath;
      x += (Math.sin(now * 0.31 + nd.phase) + 0.7 * Math.sin(now * 0.17 + nd.phase * 2.3)) * drift;
      y += (Math.cos(now * 0.27 + nd.phase) + 0.7 * Math.cos(now * 0.13 + nd.phase * 1.7)) * drift;
      var w1 = (d - r1) / 46, w2 = r2 > 0 ? (d - r2) / 46 : 9;
      var beat = (Math.exp(-w1 * w1) + 0.6 * Math.exp(-w2 * w2)) * fadeBeat;
      nd.sx = x; nd.sy = y;
      nd.beat = beat;
      nd.swell = 1 + 0.08 * Math.sin(now * 1.15 - d * 0.02 + nd.phase * 0.3) + beat * 0.35;
    }
  }

  function neighbourSet(nd) {
    var s = {};
    if (!nd) return null;
    s[nd.id] = true;
    var ls = vaultLinksByNote[nd.id] || [];
    for (var i = 0; i < ls.length; i++) { s[ls[i].a.id] = true; s[ls[i].b.id] = true; }
    return s;
  }

  /* ---------- interaction state ---------- */
  var vaultHover = null, vaultFocus = null, vaultDrag = null;
  var vaultPointers = {}, vaultPinch = null;
  var vaultTouched = false;   // hide the hint after the first interaction

  function drawVault() {
    var now = performance.now() / 1000;
    var ctx = vctx, W = vaultW, H = vaultH;
    if (cam.auto) frameVault();
    var ss = sizeScale();
    var focus = vaultFocus || vaultHover;
    var near = neighbourSet(focus);
    liveNow = now;
    liveVault(now);

    // backdrop: deep radial field, slow polar grid, parallax star dust
    ctx.globalCompositeOperation = "source-over";
    var bg = ctx.createRadialGradient(W / 2, H * 0.45, 0, W / 2, H / 2, Math.max(W, H) * 0.75);
    bg.addColorStop(0, "#0c1c38");
    bg.addColorStop(0.55, "#071226");
    bg.addColorStop(1, "#030812");
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    if (!stars) makeStars();
    for (var si = 0; si < stars.length; si++) {
      var st = stars[si];
      var sx = ((st.x * W - cam.x * cam.k * st.depth * 0.3) % W + W) % W;
      var sy = ((st.y * H - cam.y * cam.k * st.depth * 0.3) % H + H) % H;
      var tw = REDUCED_MOTION ? 0.6 : 0.45 + 0.35 * Math.sin(now * 0.8 + st.tw);
      ctx.fillStyle = "rgba(180,220,255," + (0.18 * tw) + ")";
      ctx.fillRect(sx, sy, st.r, st.r);
    }

    var ox = toScreenX(0), oy = toScreenY(0);
    var rot = REDUCED_MOTION ? 0 : now * 0.012;
    ctx.strokeStyle = "rgba(56,189,248,0.045)";
    ctx.lineWidth = 1;
    for (var rr = 1; rr <= 6; rr++) {
      ctx.beginPath();
      ctx.arc(ox, oy, rr * 90 * cam.k, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.beginPath();
    for (var sp = 0; sp < 12; sp++) {
      var an = rot + sp * Math.PI / 6;
      ctx.moveTo(ox + Math.cos(an) * 40 * cam.k, oy + Math.sin(an) * 40 * cam.k);
      ctx.lineTo(ox + Math.cos(an) * 540 * cam.k, oy + Math.sin(an) * 540 * cam.k);
    }
    ctx.strokeStyle = "rgba(56,189,248,0.03)";
    ctx.stroke();

    ctx.globalCompositeOperation = "lighter";

    // folder nebulae
    for (var gk in vaultGroups) {
      var g = vaultGroups[gk];
      if (g.n < 3) continue;
      var gph = hashStr(gk) * 6.28;
      var gl = REDUCED_MOTION ? 1 : 0.8 + 0.2 * Math.sin(now * 0.45 + gph);
      var gr = Math.max(30, (g.spread * 1.9 + 24) * cam.k) * (REDUCED_MOTION ? 1 : 1 + 0.05 * Math.sin(now * 0.3 + gph));
      var gx = toScreenX(g.x), gy = toScreenY(g.y);
      var dimG = (focus && focus.folder !== gk ? 0.35 : 1) * gl;
      var neb = ctx.createRadialGradient(gx, gy, 0, gx, gy, gr);
      neb.addColorStop(0, rgba(g.col, 0.11 * dimG));
      neb.addColorStop(0.6, rgba(g.col, 0.035 * dimG));
      neb.addColorStop(1, rgba(g.col, 0));
      ctx.fillStyle = neb;
      ctx.beginPath();
      ctx.arc(gx, gy, gr, 0, Math.PI * 2);
      ctx.fill();
    }

    // links
    var lw = clamp(0.55 * Math.sqrt(cam.k), 0.35, 1.3);
    for (var i = 0; i < vaultLinks.length; i++) {
      var lk = vaultLinks[i];
      var c = linkCurve(lk);
      var lit = Math.max(lk.a.lit, lk.b.lit);
      var on = near && (lk.a === focus || lk.b === focus);
      var lb = ((lk.a.beat || 0) + (lk.b.beat || 0)) * 0.5;
      var a = on ? 0.75 : (near ? 0.04 : 0.15 + lit * 0.55 + lb * 0.22);
      ctx.beginPath();
      ctx.moveTo(c.ax, c.ay);
      ctx.quadraticCurveTo(c.cx, c.cy, c.bx, c.by);
      ctx.strokeStyle = rgba(on ? mixHexToHex(lk.col, "#ffffff", 0.25) : lk.col, a);
      ctx.lineWidth = on ? lw * 2.2 : lw * (1 + lit);
      ctx.stroke();
    }

    // pulses: a bright head with a short fading tail
    for (var pi = 0; pi < vaultPulses.length; pi++) {
      var pu = vaultPulses[pi];
      var pc = linkCurve(pu.link);
      var dimP = near && !(near[pu.link.a.id] && near[pu.link.b.id]) ? 0.2 : 1;
      var fade = Math.sin(Math.PI * pu.t) * dimP;
      for (var tl = 0; tl < 5; tl++) {
        var tt = pu.t - tl * 0.025;
        if (tt < 0) break;
        var pt = bezier(pc, pu.fwd ? tt : 1 - tt);
        var size = (tl === 0 ? 11 : 7 - tl) * ss;
        ctx.globalAlpha = fade * (1 - tl / 5);
        ctx.drawImage(glowSprite(pu.col), pt.x - size / 2, pt.y - size / 2, size, size);
      }
    }
    ctx.globalAlpha = 1;

    // notes: glow first (additive), cores on top
    var drawn = [];
    for (var j = 0; j < vaultNotes.length; j++) {
      var nd = vaultNotes[j];
      var x = nd.sx, y = nd.sy, beat = nd.beat || 0;
      var rs = nd.r * ss * (nd.swell || 1);
      var dim = near && !near[nd.id] ? 0.16 : 1;
      var opCol = OP_COLOUR[nd.litOp] || "#00f2fe";
      var gs = rs * (nd.hub ? 9 : 7) * (1 + nd.lit * 0.8 + beat * 0.8);
      ctx.globalAlpha = Math.min(1, 0.55 + nd.lit * 0.45 + beat * 0.35) * dim;
      ctx.drawImage(glowSprite(nd.lit > 0.05 ? opCol : nd.col), x - gs / 2, y - gs / 2, gs, gs);
      drawn.push({ nd: nd, x: x, y: y, rs: rs, dim: dim, opCol: opCol });
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
    for (var d = 0; d < drawn.length; d++) {
      var e = drawn[d], n2 = e.nd;
      // halo (fading ~30s) and event ring
      if (n2.halo > 0) {
        ctx.beginPath();
        ctx.arc(e.x, e.y, e.rs + 5 + (1 - n2.halo) * 14, 0, Math.PI * 2);
        ctx.strokeStyle = rgba(e.opCol, n2.halo * 0.5);
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      if (n2.ringT > 0) {
        ctx.beginPath();
        ctx.arc(e.x, e.y, e.rs + (1 - n2.ringT) * 26, 0, Math.PI * 2);
        ctx.strokeStyle = rgba(e.opCol, n2.ringT * 0.8);
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
      // core
      ctx.globalAlpha = e.dim;
      ctx.beginPath();
      ctx.arc(e.x, e.y, Math.max(0.8, e.rs), 0, Math.PI * 2);
      ctx.fillStyle = n2.lit > 0 ? mixHex(n2.col, "#ffffff", 0.35 + n2.lit * 0.4) : n2.col;
      ctx.fill();
      ctx.beginPath();
      ctx.arc(e.x, e.y, Math.max(0.5, e.rs * 0.42), 0, Math.PI * 2);
      ctx.fillStyle = "rgba(255,255,255," + (n2.hub ? 0.9 : 0.55) + ")";
      ctx.fill();
      // hubs carry a slow orbit
      if (n2.hub) {
        var spin = REDUCED_MOTION ? 0 : now * 0.6 + n2.phase;
        ctx.strokeStyle = rgba(n2.col, 0.55);
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        ctx.arc(e.x, e.y, e.rs + 3.5, spin, spin + 1.9);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(e.x, e.y, e.rs + 3.5, spin + Math.PI, spin + Math.PI + 1.9);
        ctx.stroke();
      }
      if (n2 === vaultFocus) {
        ctx.strokeStyle = "rgba(255,255,255,0.85)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(e.x, e.y, e.rs + 6, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;

    drawVaultLabels(drawn, focus, near);
    setVaultCount(vaultNotes.length);
  }

  // folder names, note titles and the hover card — never overlapping,
  // never clipped by the panel edges
  function drawVaultLabels(drawn, focus, near) {
    var ctx = vctx, W = vaultW, H = vaultH;
    var placed = [];
    function hitsAny(bb) {
      for (var q = 0; q < placed.length; q++) {
        var b = placed[q];
        if (bb.x0 < b.x1 && bb.x1 > b.x0 && bb.y0 < b.y1 && bb.y1 > b.y0) return true;
      }
      return false;
    }
    function shortName(id) {
      var t = String(id).replace(/\.md$/, "");
      var i = t.lastIndexOf("/");
      return i >= 0 ? t.substr(i + 1) : t;
    }
    var hasSpacing = "letterSpacing" in ctx;

    // folder names, like constellation names
    ctx.font = "600 9px 'Inter', system-ui";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    if (hasSpacing) ctx.letterSpacing = "2.5px";
    var gl = [];
    for (var gk in vaultGroups) if (vaultGroups[gk].n >= 4) gl.push(gk);
    gl.sort(function (a, b) { return vaultGroups[b].n - vaultGroups[a].n; });
    for (var gi = 0; gi < gl.length; gi++) {
      var g = vaultGroups[gl[gi]];
      if (focus && focus.folder !== gl[gi]) continue;
      var tw = ctx.measureText(g.label).width;
      var gx = clamp(toScreenX(g.x), tw / 2 + 4, W - tw / 2 - 4);
      var gy = clamp(toScreenY(g.y) - (g.spread * 1.15 + 14) * cam.k - 6, 8, H - 8);
      var bb = { x0: gx - tw / 2 - 4, x1: gx + tw / 2 + 4, y0: gy - 7, y1: gy + 7 };
      if (hitsAny(bb)) continue;
      placed.push(bb);
      // a soft dark outline keeps the name readable over glowing notes
      ctx.lineJoin = "round";
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(3,9,20,0.75)";
      ctx.strokeText(g.label, gx, gy);
      ctx.fillStyle = rgba(g.col, focus ? 0.85 : 0.5);
      ctx.fillText(g.label, gx, gy);
    }
    if (hasSpacing) ctx.letterSpacing = "0px";

    // note titles: the hovered note, the focused note's neighbours, lit
    // notes (most recent first) and, zoomed in, the hubs
    var want = [];
    var lit = [];
    for (var i = 0; i < drawn.length; i++) {
      var e = drawn[i];
      if (e.nd === focus) continue;
      if (near && near[e.nd.id]) want.push(e);
      else if (!near && e.nd.lit > 0.15) lit.push(e);
      else if (!near && e.nd.hub && cam.k > 1.5) want.push(e);
    }
    lit.sort(function (a, b) { return (b.nd.litT || 0) - (a.nd.litT || 0); });
    want = lit.slice(0, 3).concat(want).slice(0, 14);
    ctx.font = "10px 'Inter', system-ui";
    for (var w = 0; w < want.length; w++) {
      var it = want[w], label = shortName(it.nd.id);
      var lw = ctx.measureText(label).width, th = 13, gap = 5;
      var spots = [
        { x: it.x - lw / 2, y: it.y - it.rs - gap - th },
        { x: it.x - lw / 2, y: it.y + it.rs + gap },
        { x: it.x + it.rs + gap, y: it.y - th / 2 },
        { x: it.x - it.rs - gap - lw, y: it.y - th / 2 }
      ];
      for (var s = 0; s < spots.length; s++) {
        var bx = clamp(spots[s].x, 3, W - lw - 3), by = clamp(spots[s].y, 3, H - th - 3);
        var box = { x0: bx - 4, x1: bx + lw + 4, y0: by - 2, y1: by + th + 2 };
        if (hitsAny(box)) continue;
        placed.push(box);
        var la = it.nd.lit > 0.15 ? Math.min(1, it.nd.lit * 1.5) : 0.85;
        ctx.fillStyle = rgba("#030a18", 0.72 * la);
        roundRect(ctx, bx - 4, by - 1, lw + 8, th + 2, 3);
        ctx.fill();
        ctx.fillStyle = rgba(mixHexToHex(it.nd.col, "#ffffff", 0.55), la);
        ctx.textAlign = "left";
        ctx.fillText(label, bx, by + th / 2 + 0.5);
        break;
      }
    }

    // hover / focus card
    if (focus) {
      var fe = null;
      for (var f = 0; f < drawn.length; f++) if (drawn[f].nd === focus) { fe = drawn[f]; break; }
      if (fe) {
        var title = shortName(focus.id);
        var sub = (focus.folder || "vault root") + "  ·  " + focus.deg + (focus.deg === 1 ? " link" : " links");
        ctx.font = "600 12px 'Inter', system-ui";
        var w1 = ctx.measureText(title).width;
        ctx.font = "10px 'JetBrains Mono', ui-monospace, monospace";
        var w2 = ctx.measureText(sub).width;
        var cw = Math.min(W - 16, Math.max(w1, w2) + 22), ch = 42;
        var cx = clamp(fe.x + 14, 8, W - cw - 8);
        var cy = fe.y - ch - 14 < 8 ? fe.y + 14 : fe.y - ch - 14;
        cy = clamp(cy, 8, H - ch - 8);
        ctx.fillStyle = "rgba(4,12,28,0.88)";
        roundRect(ctx, cx, cy, cw, ch, 6);
        ctx.fill();
        ctx.strokeStyle = rgba(focus.col, 0.7);
        ctx.lineWidth = 1;
        roundRect(ctx, cx + 0.5, cy + 0.5, cw - 1, ch - 1, 6);
        ctx.stroke();
        ctx.fillStyle = focus.col;
        ctx.fillRect(cx + 1, cy + 8, 2, ch - 16);
        ctx.textAlign = "left";
        ctx.fillStyle = "#eaf6ff";
        ctx.font = "600 12px 'Inter', system-ui";
        ctx.fillText(title, cx + 11, cy + 15, cw - 18);
        ctx.fillStyle = "rgba(170,200,230,0.75)";
        ctx.font = "10px 'JetBrains Mono', ui-monospace, monospace";
        ctx.fillText(sub, cx + 11, cy + 30, cw - 18);
      }
    }

    if (!vaultTouched && vaultNotes.length) {
      ctx.textAlign = "left";
      ctx.font = "10px 'JetBrains Mono', ui-monospace, monospace";
      ctx.fillStyle = "rgba(150,190,230,0.38)";
      ctx.fillText("drag · scroll to zoom · double-click to frame", 10, H - 10);
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
  }

  function mixHexToHex(a, b, t) {
    var A = rgb(a), B = rgb(b);
    function h(v) { v = Math.round(v); return (v < 16 ? "0" : "") + v.toString(16); }
    return "#" + h(lerp(A[0], B[0], t)) + h(lerp(A[1], B[1], t)) + h(lerp(A[2], B[2], t));
  }

  /* ---------- pointer interaction ---------- */
  function noteAt(sx, sy) {
    var best = null, bestD = 1e9, ss = sizeScale();
    for (var i = 0; i < vaultNotes.length; i++) {
      var n = vaultNotes[i];
      var dx = toScreenX(n.x) - sx, dy = toScreenY(n.y) - sy;
      var d = dx * dx + dy * dy, hit = n.r * ss + 7;
      if (d < hit * hit && d < bestD) { best = n; bestD = d; }
    }
    return best;
  }
  function localXY(ev) {
    var r = vaultCanvas.getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  }
  function pinchState() {
    var ids = Object.keys(vaultPointers);
    var a = vaultPointers[ids[0]], b = vaultPointers[ids[1]];
    return { d: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  }
  function zoomAt(sx, sy, factor) {
    var wx = toWorldX(sx), wy = toWorldY(sy);
    cam.k = clamp(cam.k * factor, 0.12, 8);
    cam.x = wx - (sx - vaultW / 2) / cam.k;
    cam.y = wy - (sy - vaultH / 2) / cam.k;
  }

  vaultCanvas.addEventListener("pointerdown", function (ev) {
    var p = localXY(ev);
    vaultPointers[ev.pointerId] = p;
    vaultTouched = true;
    try { vaultCanvas.setPointerCapture(ev.pointerId); } catch (e) {}
    if (Object.keys(vaultPointers).length === 2) {
      if (vaultDrag && vaultDrag.node) { vaultDrag.node.fx = vaultDrag.node.fy = null; sim.target = 0; }
      vaultDrag = null;
      vaultPinch = pinchState();
      cam.auto = false;
      return;
    }
    var hit = noteAt(p.x, p.y);
    vaultHover = hit;
    vaultDrag = { node: hit, sx: p.x, sy: p.y, lx: p.x, ly: p.y, moved: false };
    if (hit) { hit.fx = hit.x; hit.fy = hit.y; }
    ev.preventDefault();
  });
  vaultCanvas.addEventListener("pointermove", function (ev) {
    var p = localXY(ev);
    if (vaultPointers[ev.pointerId]) vaultPointers[ev.pointerId] = p;
    if (vaultPinch && Object.keys(vaultPointers).length === 2) {
      var ps = pinchState();
      zoomAt(ps.x, ps.y, ps.d / vaultPinch.d);
      cam.x -= (ps.x - vaultPinch.x) / cam.k;
      cam.y -= (ps.y - vaultPinch.y) / cam.k;
      vaultPinch = ps;
      return;
    }
    if (vaultDrag) {
      if (Math.abs(p.x - vaultDrag.sx) + Math.abs(p.y - vaultDrag.sy) > 4) vaultDrag.moved = true;
      if (vaultDrag.node) {
        if (vaultDrag.moved) {
          vaultDrag.node.fx = toWorldX(p.x);
          vaultDrag.node.fy = toWorldY(p.y);
          sim.target = 0.25;
          if (sim.alpha < 0.25) sim.alpha = 0.25;
          cam.auto = false;
        }
      } else if (vaultDrag.moved) {
        cam.x -= (p.x - vaultDrag.lx) / cam.k;
        cam.y -= (p.y - vaultDrag.ly) / cam.k;
        cam.auto = false;
      }
      vaultDrag.lx = p.x; vaultDrag.ly = p.y;
      vaultCanvas.style.cursor = "grabbing";
      return;
    }
    vaultHover = noteAt(p.x, p.y);
    vaultCanvas.style.cursor = vaultHover ? "pointer" : "grab";
  });
  function endPointer(ev) {
    delete vaultPointers[ev.pointerId];
    if (vaultPinch) { if (Object.keys(vaultPointers).length < 2) vaultPinch = null; return; }
    if (!vaultDrag) return;
    var d = vaultDrag;
    vaultDrag = null;
    if (d.node) { d.node.fx = d.node.fy = null; sim.target = 0; }
    if (!d.moved && ev.type === "pointerup") {
      setVaultFocus(d.node && d.node !== vaultFocus ? d.node : null);
    }
    vaultCanvas.style.cursor = vaultHover ? "pointer" : "grab";
  }
  vaultCanvas.addEventListener("pointerup", endPointer);
  vaultCanvas.addEventListener("pointercancel", endPointer);
  vaultCanvas.addEventListener("pointerleave", function () { if (!vaultDrag) vaultHover = null; });
  vaultCanvas.addEventListener("wheel", function (ev) {
    ev.preventDefault();
    vaultTouched = true;
    var p = localXY(ev);
    zoomAt(p.x, p.y, Math.exp(-ev.deltaY * 0.0015));
    cam.auto = false;
  }, { passive: false });
  vaultCanvas.addEventListener("dblclick", function () {
    setVaultFocus(null);
    cam.auto = true;
  });

  // expand to a large view and back
  function setVaultExpanded(on) {
    if (!vaultPanel) return;
    vaultPanel.classList.toggle("expanded", on);
    document.body.classList.toggle("vault-open", on);
    var btn = document.getElementById("vault-expand");
    if (btn) btn.setAttribute("aria-pressed", on ? "true" : "false");
    cam.auto = true;
    requestAnimationFrame(function () { window.dispatchEvent(new Event("resize")); });
  }
  var expandBtn = document.getElementById("vault-expand");
  if (expandBtn) expandBtn.addEventListener("click", function () {
    setVaultExpanded(!vaultPanel.classList.contains("expanded"));
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key !== "Escape") return;
    if (vaultFocus) { setVaultFocus(null); return; }
    if (vaultPanel && vaultPanel.classList.contains("expanded")) setVaultExpanded(false);
  });

  var seenVaultEvents = {}, seenVaultCount = 0;
  // focus a note (or none) and tell the page; the page can focus one by id
  function setVaultFocus(nd) {
    vaultFocus = nd || null;
    window.dispatchEvent(new CustomEvent("vault-focus", { detail: vaultFocus ? vaultFocus.id : null }));
  }
  window.vaultFocusNote = function (id) {
    var nd = vaultById[id] || null;
    vaultFocus = nd;
    if (nd) { cam.auto = false; cam.x = nd.x; cam.y = nd.y; }
    return !!nd;
  };

  function lightVaultNote(noteId, op) {
    if (seenVaultCount > 4000) { seenVaultEvents = {}; seenVaultCount = 0; }
    var nd = vaultById[noteId];
    if (!nd) {
      // new note: appear at its folder, or the middle
      var folder = folderOf(noteId), g = vaultGroups[folder];
      nd = {
        id: noteId,
        title: noteId.replace(/\.md$/, ""),
        folder: folder, type: "",
        links: [], mtime: 0,
        x: g ? g.x : 0, y: g ? g.y : 0,
        vx: (Math.random() - 0.5) * 4, vy: (Math.random() - 0.5) * 4,
        fx: null, fy: null,
        r: 1.6, deg: 0, col: groupColour[folder] || VAULT_PALETTE[0], hub: false,
        phase: hashStr(noteId + "p") * Math.PI * 2,
        lit: 1, litOp: op, ringT: 1, halo: 1
      };
      vaultNotes.push(nd);
      vaultById[noteId] = nd;
      vaultLinksByNote[noteId] = [];
      sim.alpha = Math.max(sim.alpha, 0.3);
      return;
    }
    nd.lit = 1;
    nd.litOp = op;
    nd.litT = performance.now();
    nd.ringT = 1;
    nd.halo = 1;
    // the touch ripples out along the note's links
    var ls = vaultLinksByNote[noteId] || [];
    for (var i = 0; i < ls.length && i < 12; i++) spawnPulse(ls[i], nd, OP_COLOUR[op] || "#00f2fe", 0.9);
  }

  /* ------------------------------------------------------------------ *
   * State polling + dispatch
   * ------------------------------------------------------------------ */
  var lastState = null;
  var lastEventCount = 0;
  var lastTaskKind = "";
  var lastGraphKey = "";

  // A state-coloured halo behind the mark so the chip never looks empty.
  // Sized from the chip's real CSS dimensions each time.
  function drawElenaHalo(col) {
    if (!elenaCanvas) return;
    var r = elenaCanvas.getBoundingClientRect();
    if (r.width < 2) return;
    var dpr = window.devicePixelRatio || 1;
    var W = Math.round(r.width * dpr), H = Math.round(r.height * dpr);
    var halo = document.getElementById("elena-halo");
    if (halo && halo.width !== W) { halo.width = W; halo.height = H; }
    var ctx = halo ? halo.getContext("2d") : null;
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, r.width, r.height);
    var cx = r.width / 2, cy = r.height / 2;
    var rad = Math.min(r.width, r.height) * 0.36;
    // soft radial wash
    var g = ctx.createRadialGradient(cx, cy, rad * 0.15, cx, cy, rad);
    g.addColorStop(0, hexA(col, 0.10));
    g.addColorStop(0.7, hexA(col, 0.04));
    g.addColorStop(1, hexA(col, 0));
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(cx, cy, rad, 0, Math.PI * 2);
    ctx.fill();
    // faint defining ring at the wash's edge
    ctx.strokeStyle = hexA(col, 0.22);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(cx, cy, rad, 0, Math.PI * 2);
    ctx.stroke();
  }
  function hexA(hex, a) {
    var h = hex.replace("#", "");
    var n = parseInt(h, 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }
  function elenaGlow(col, active) {
    if (!elenaCanvas) return;
    elenaCanvas.style.filter =
      "drop-shadow(0 0 " + (active ? 10 : 5) + "px " + col + ")" +
      " drop-shadow(0 0 " + (active ? 26 : 13) + "px " + hexA(col, active ? 0.5 : 0.28) + ")";
  }

  var elenaMark = null;
  var elenaCanvas = document.getElementById("elena-canvas");
  var elenaLineW = 0;   // effective line width at the chip's real pixel size

  // The ElenaMark instance sizes itself from the element's bounding rect
  // ONCE at construction, then only on window resize. Built at DOM-ready
  // the 180px canvas usually has not finished laying out (web fonts,
  // first frame), so it silently falls back to the 104px design space
  // and draws a small arc in the middle of the chip. Re-measure it once
  // the layout has settled so R tracks the real chip size.
  function refitElena() {
    if (!elenaMark || !elenaCanvas) return;
    var r = elenaCanvas.getBoundingClientRect();
    var w = r.width, h = r.height;
    if (w < 20 || h < 20) return;
    var dpr = window.devicePixelRatio || 1;
    elenaCanvas.width  = Math.round(w * dpr);
    elenaCanvas.height = Math.round(h * dpr);
    // The library keeps its own internal w/h for radius maths; mirror the
    // real size into it and set the stroke to the chip's real px so the
    // line is a bold mark, not a hairline.
    if (elenaMark.w !== undefined) elenaMark.w = w;
    if (elenaMark.h !== undefined) elenaMark.h = h;
    if (elenaMark.ctx) elenaMark.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    elenaLineW = Math.max(2.5, Math.min(w, h) * 0.03);
  }
  var chipFrame = document.getElementById("elena-chip").querySelector(".chip-frame");
  // The page's real ids (index.html): the chip carries a .task-dot span inside
  // #task-line, the model line is #task-model, and the readout container is #task-readout.
  var taskLine = document.getElementById("task-line");
  var taskLabel = document.getElementById("task-label");
  var taskModel = document.getElementById("task-model");
  var taskReadout = document.getElementById("task-readout");
  var pillNd = document.getElementById("pill-nd");
  var pillOllama = document.getElementById("pill-ollama");
  var boardOverlay = document.getElementById("board-overlay");
  var overlayBig = document.getElementById("overlay-big");
  var overlaySmall = document.getElementById("overlay-small");
  var vaultPath = document.getElementById("vault-path");
  var statCpu = document.getElementById("stat-cpu");
  var statGpu = document.getElementById("stat-gpu");
  var statVram = document.getElementById("stat-vram");
  var statRam = document.getElementById("stat-ram");
  var statDisk = document.getElementById("stat-disk");
  var statFlowCount = document.getElementById("stat-flow-count");
  var statAge = document.getElementById("stat-age");
  var statClock = document.getElementById("stat-clock");

  var gotState = false;

  function setState(state) {
    lastState = state;

    // first real data: hide the waiting overlay
    if (!gotState) {
      gotState = true;
      if (boardOverlay) boardOverlay.style.display = "none";
    }

    // connectivity pills
    if (pillNd) pillNd.className = "pill " + (state.nd_up ? "up" : "down");
    if (pillOllama) pillOllama.className = "pill " + (state.ollama_up ? "up" : "down");

    // task kind -> mark + chip frame
    var task = state.task || { kind: "idle", label: "idle", job_id: null };
    if (task.kind !== lastTaskKind) {
      lastTaskKind = task.kind;
      var mstate = TASK_STATE[task.kind] || "idle";
      if (elenaMark) elenaMark.set(mstate, task.round || 0);
      if (elenaMark) elenaMark.setLevel(0.35 + 0.5 * (task.kind === "idle" ? 0 : 1));
      chipFrame.className = "chip-frame " + mstate;
      if (taskLine) taskLine.className = "task-line " + mstate;
    }
    // label + status dot (the dot is the .task-dot span inside #task-line)
    if (taskLabel) taskLabel.textContent = task.label || (task.kind || "idle");
    var kindCol = kindColour(task.kind) || "#3090d8";
    var dot = taskLine ? taskLine.querySelector(".task-dot") : null;
    if (dot) dot.style.background = kindCol;
    drawElenaHalo(kindCol);
    elenaGlow(kindCol, task.kind !== "idle");
    // model / spill
    if (taskModel) {
      var mdl = state.model;
      if (mdl && mdl.name) {
        var txt = "model " + mdl.name.split("/").pop();
        if (mdl.spill_pct > 0) txt += "  ·  " + Math.round(mdl.spill_pct) + "% spill";
        taskModel.textContent = txt;
        if (taskReadout) taskReadout.classList.add("has-spill");
      } else {
        taskModel.textContent = "model — none loaded";
        if (taskReadout) taskReadout.classList.remove("has-spill");
      }
    }

    // telemetry readouts
    var n = state.nodes || {};
    if (statClock) statClock.textContent = formatClock(new Date());
    if (statCpu) statCpu.textContent = (n.cpu && typeof n.cpu.load === "number")
      ? Math.round(n.cpu.load) + "%" : "—";
    if (statGpu && n.gpu && typeof n.gpu.load === "number") {
      statGpu.textContent = Math.round(n.gpu.load) + "%";
    }
    if (statVram && n.gpu) {
      statVram.textContent = (n.gpu.vram_used_gb || 0).toFixed(1) + "/" +
        (n.gpu.vram_total_gb || 0).toFixed(1) + " GB";
    }
    if (statRam && n.ram) {
      var rp = n.ram.total_gb ? Math.round(100 * n.ram.used_gb / n.ram.total_gb) : 0;
      statRam.textContent = n.ram.used_gb.toFixed(1) + "/" + n.ram.total_gb + " GB (" + rp + "%)";
    }
    if (statDisk && n.disk) {
      statDisk.textContent = (n.disk.read_mbps || 0).toFixed(1) + "R/" +
        (n.disk.write_mbps || 0).toFixed(1) + "W MB/s";
    }
    if (statFlowCount) statFlowCount.textContent = String((state.flows || []).length);
    if (statAge) {
      var age = (typeof state.t === "number")
        ? Math.max(0, Math.round((Date.now() / 1000 - state.t) * 10) / 10)
        : null;
      statAge.textContent = age == null ? "—" : age.toFixed(1) + "s";
    }

    // vault path — the server does not include it in /api/state,
    // so we fall back to the graph's vault key set by ingestVaultGraph
    if (vaultPath) {
      var vp = (state.vault && state.vault.path) || vaultGraphPath;
      if (vp) vaultPath.textContent = vp;
    }

    // chips
    updateChipTexts(state);

    // flows -> pulses
    if (state.flows) {
      for (var i = 0; i < state.flows.length; i++) addPulsesForFlow(state.flows[i]);
    }

    // events -> one bright burst each (track seen by index since last poll)
    var evs = state.events || [];
    var start = lastEventCount;
    lastEventCount = evs.length;
    for (var e = start; e < evs.length; e++) {
      var ev = evs[e];
      emitPulse(ev.from, ev.to, ev.kind, true);
    }

    // vault graph
    var vg = state.vault || {};
    if (vg.notes != null && vg.notes !== lastGraphKey) {
      // notes count changed: we don't have the full graph here, but the
      // server exposes it via state? We rely on the graph being present
      // in state.vault.graph if provided.
    }

    // vault events -> light notes
    if (vg.events) {
      for (var v = 0; v < vg.events.length; v++) {
        var ev = vg.events[v];
        var evKey = ev.t + "|" + ev.op + "|" + ev.note;
        if (seenVaultEvents[evKey]) continue;   // the list is re-sent every poll
        seenVaultEvents[evKey] = true;
        seenVaultCount++;
        lightVaultNote(ev.note, ev.op);
      }
    }
  }

  // ingest vault graph if the server provides the full graph in state
  function ingestFromState(state) {
    if (state.vault && state.vault.graph && JSON.stringify(state.vault.graph) !== lastGraphKey) {
      lastGraphKey = JSON.stringify(state.vault.graph);
      var hasNew = ingestVaultGraph(state.vault.graph);
      rebuildLinkSet();
      // warm up ONLY when new notes arrived, after the links and link set exist,
      // so the 30s refresh never resets the settled layout
      if (hasNew) {
        if (!vaultW || !vaultH) resizeVault(); // panel size must exist before seeding
        for (var pre = 0; pre < 600; pre++) stepVault(0.016);
        for (var w = 0; w < vaultNotes.length; w++) { vaultNotes[w].vx = 0; vaultNotes[w].vy = 0; }
      }
    }
  }

  /* Re-show the overlay and dim the pills when the data source stops answering.
     Called by poll()'s catch; cleared by setState() on the first good response. */
  var lastGoodPoll = 0;   // performance.now() of the last successful poll
  function markDead() {
    if (performance.now() - lastGoodPoll < POLL_MS * 3) return; // grace: 1 tick
    if (boardOverlay) boardOverlay.classList.add("visible");
    if (overlayBig) overlayBig.textContent = "Waiting for telemetry";
    if (overlaySmall) overlaySmall.textContent = "Polling /api/state once it answers.";
    if (pillNd) pillNd.className = "pill down";
    if (pillOllama) pillOllama.className = "pill down";
  }

  function poll() {
    fetch(STATE_URL, { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (state) {
        lastGoodPoll = performance.now();
        ingestFromState(state);
        setState(state);
        // the page around the board (Philibert's notes panel) reads the same state
        window.dispatchEvent(new CustomEvent("viz-state", { detail: state }));
      })
      .catch(function () { markDead(); /* keep last state; board stays put */ });
    setTimeout(poll, POLL_MS);
  }

  /* ------------------------------------------------------------------ *
   * Frame loop
   * ------------------------------------------------------------------ */
  var lastFrame = performance.now();
  var lastClockSec = -1;
  function formatClock(d) {
    function p(x) { return (x < 10 ? "0" : "") + x; }
    return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }
  function tickClock() {
    var d = new Date();
    if (d.getSeconds() !== lastClockSec) {
      lastClockSec = d.getSeconds();
      if (statClock) statClock.textContent = formatClock(d);
    }
  }
  function frame() {
    var nowMs = performance.now();
    var dt = Math.min(0.05, (nowMs - lastFrame) / 1000);
    lastFrame = nowMs;

    tickClock();
    stepVault(dt);
    drawVault();
    drawBoard();

    requestAnimationFrame(frame);
  }

  /* ------------------------------------------------------------------ *
   * Debug hook
   * ------------------------------------------------------------------ */
  window.vizDebug = function () {
    var lit = 0;
    for (var i = 0; i < vaultNotes.length; i++) if (vaultNotes[i].lit > 0.1) lit++;
    return {
      pulses: pulses.length,
      flows: lastState ? lastState.flows : [],
      vaultNodes: vaultNotes.length,
      vaultLit: lit,
      vaultCam: { x: Math.round(cam.x), y: Math.round(cam.y), k: +cam.k.toFixed(3), auto: cam.auto },
      vaultExtent: (function () {
        var x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
        for (var j = 0; j < vaultNotes.length; j++) {
          var n = vaultNotes[j];
          x0 = Math.min(x0, n.x); x1 = Math.max(x1, n.x); y0 = Math.min(y0, n.y); y1 = Math.max(y1, n.y);
        }
        return vaultNotes.length ? [Math.round(x1 - x0), Math.round(y1 - y0)] : null;
      })(),
      vaultAlpha: +sim.alpha.toFixed(4)
    };
  };

  /* ------------------------------------------------------------------ *
   * Boot
   * ------------------------------------------------------------------ */
  function boot() {
    resizeBoard();
    resizeVault();

    if (elenaCanvas && window.ElenaMark) {
      try {
        elenaMark = new ElenaMark(elenaCanvas, { trail: 700 });
        // The mark sized itself from the canvas rect BEFORE the chip's grid CSS
        // was laid out, so its w/h were near zero and the line drew as a
        // faint hairline. Re-measure now that the chip has its real size.
        refitElena();
        elenaMark.set("idle", 0);
        elenaMark.setLevel(0.3);
        elenaGlow(kindColour("idle"), false);
        drawElenaHalo(kindColour("idle"));
      } catch (e) {
        elenaMark = null;
      }
    }

    window.addEventListener("resize", function () {
      resizeBoard();
      resizeVault();
      refitElena();
      drawElenaHalo(kindColour(lastTaskKind || "idle"));
    });

    poll();
    requestAnimationFrame(frame);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
