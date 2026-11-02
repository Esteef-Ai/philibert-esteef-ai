// Retro Vault controller setups: named profiles (saved on the drive, one mapping per system),
// a drawing of the system's classic pad next to the controller in your hands, and a live monitor
// of what the controller sends. The mapping goes to EmulatorJS (its control labels, like
// "BUTTON_1" or "LEFT_STICK_X:+1") and to the stream of a game someone else is hosting.
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const AXES = ["LEFT_STICK_X", "LEFT_STICK_Y", "RIGHT_STICK_X", "RIGHT_STICK_Y"];
  const BTN = ["BUTTON_1", "BUTTON_2", "BUTTON_3", "BUTTON_4", "LEFT_TOP_SHOULDER", "RIGHT_TOP_SHOULDER",
    "LEFT_BOTTOM_SHOULDER", "RIGHT_BOTTOM_SHOULDER", "SELECT", "START", "LEFT_STICK", "RIGHT_STICK",
    "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"];
  const DEAD = 0.18, PRESS = 0.5;

  // ── what each system has: EmulatorJS control id -> the classic button ──────────
  const DPAD = { 4: "Up", 5: "Down", 6: "Left", 7: "Right" };
  const TABLES = {
    NES: { 8: "A", 0: "B", 2: "Select", 3: "Start", ...DPAD },
    SNES: { 8: "A", 0: "B", 9: "X", 1: "Y", 10: "L", 11: "R", 2: "Select", 3: "Start", ...DPAD },
    Genesis: { 1: "A", 0: "B", 8: "C", 10: "X", 9: "Y", 11: "Z", 2: "Mode", 3: "Start", ...DPAD },
    SMS: { 0: "Button 1 / Start", 8: "Button 2", ...DPAD },
    N64: { 0: "A", 1: "B", 12: "Z", 10: "L", 11: "R", 3: "Start", 4: "D-pad up", 5: "D-pad down", 6: "D-pad left",
      7: "D-pad right", 19: "Stick up", 18: "Stick down", 17: "Stick left", 16: "Stick right", 23: "C up",
      22: "C down", 21: "C left", 20: "C right" },
    GBA: { 8: "A", 0: "B", 10: "L", 11: "R", 2: "Select", 3: "Start", ...DPAD },
    GB: { 8: "A", 0: "B", 2: "Select", 3: "Start", ...DPAD },
    MAME: { 0: "Button 1", 8: "Button 2", 1: "Button 3", 9: "Button 4", 10: "Button 5", 11: "Button 6",
      2: "Insert coin", 3: "Start", ...DPAD },
    NEOGEO: { 0: "A", 8: "B", 1: "C", 9: "D", 2: "Insert coin", 3: "Start", ...DPAD },
  };
  const BASE = { 0: "BUTTON_2", 1: "BUTTON_4", 2: "SELECT", 3: "START", 4: "DPAD_UP", 5: "DPAD_DOWN", 6: "DPAD_LEFT",
    7: "DPAD_RIGHT", 8: "BUTTON_1", 9: "BUTTON_3", 10: "LEFT_TOP_SHOULDER", 11: "RIGHT_TOP_SHOULDER",
    12: "LEFT_BOTTOM_SHOULDER", 13: "RIGHT_BOTTOM_SHOULDER", 16: "LEFT_STICK_X:+1", 17: "LEFT_STICK_X:-1",
    18: "LEFT_STICK_Y:+1", 19: "LEFT_STICK_Y:-1", 20: "RIGHT_STICK_X:+1", 21: "RIGHT_STICK_X:-1",
    22: "RIGHT_STICK_Y:+1", 23: "RIGHT_STICK_Y:-1" };
  // N64: A and B sit where they do on the real pad (the bottom and left face buttons)
  const DEFAULT_OVERRIDE = { N64: { 0: "BUTTON_1", 1: "BUTTON_3" } };
  function defaults(sys) {
    const out = {};
    Object.keys(TABLES[sys] || {}).forEach(id => { out[id] = (DEFAULT_OVERRIDE[sys] || {})[id] || BASE[id] || ""; });
    return out;
  }

  // ── the drawings: viewBox 0 0 420 240 ──────────────────────────────────────────
  const DP = (x, y, ids = [4, 5, 6, 7]) => ({ k: "dpad", x, y, ids });
  const R = (id, x, y, fill, r = 15, t) => ({ k: "r", id, x, y, fill, r, t });
  const P = (id, x, y, t, w = 38, h = 14) => ({ k: "p", id, x, y, t, w, h });
  const BODY = {
    box: '<rect x="28" y="62" width="364" height="126" rx="8"/>',
    dogbone: '<path d="M105 58h210a70 70 0 0 1 0 140h-210a70 70 0 0 1 0-140z"/>',
    n64: '<path d="M70 44h280q34 0 38 34l16 96q4 30-20 32t-34-26l-20-48h-64l-20 92q-6 20-26 20t-26-20l-20-92h-64l-20 48q-10 28-34 26t-20-32l16-96q4-34 38-34z"/>',
    crescent: '<path d="M50 90q160-70 320 0q34 18 28 62t-44 46q-40 0-58-24h-172q-18 24-58 24t-44-46q-6-44 28-62z"/>',
    hand: '<rect x="36" y="42" width="348" height="160" rx="30"/><rect x="128" y="62" width="164" height="112" rx="6" fill="#111a"/>',
    panel: '<rect x="20" y="52" width="380" height="150" rx="6"/>',
  };
  const stick4 = ids => ({ k: "stick", x: 108, y: 128, r: 24, ids });
  const DRAW = {
    NES: { body: "box", fill: "#c9c9c4", items: [DP(92, 125), P(2, 180, 135, "Select"), P(3, 232, 135, "Start"), R(0, 300, 128, "#c8102e", 16), R(8, 350, 128, "#c8102e", 16)] },
    SNES: { body: "dogbone", fill: "#b9b9c4", items: [DP(105, 128), P(2, 182, 138, "Select"), P(3, 232, 138, "Start"), R(1, 288, 128, "#3a9f49", 13), R(9, 318, 100, "#3b5fc0", 13), R(0, 318, 156, "#e0b92e", 13), R(8, 348, 128, "#c8102e", 13), P(10, 92, 50, "L", 70, 12), P(11, 328, 50, "R", 70, 12)] },
    Genesis: { body: "crescent", fill: "#2b2b30", items: [DP(105, 125), P(3, 208, 112, "Start"), R(1, 262, 142, "#555", 14), R(0, 298, 132, "#555", 14), R(8, 334, 122, "#555", 14), R(10, 256, 100, "#444", 10), R(9, 288, 92, "#444", 10), R(11, 320, 84, "#444", 10), P(2, 362, 76, "Mode", 36, 12)] },
    SMS: { body: "box", fill: "#29292e", items: [DP(105, 125), R(0, 288, 128, "#c8102e", 18, "1"), R(8, 340, 128, "#c8102e", 18, "2")] },
    N64: { body: "n64", fill: "#a9acb4", items: [DP(96, 112), { k: "stick", x: 210, y: 150, r: 19, ids: [19, 18, 17, 16] }, P(3, 210, 86, "Start", 30, 12), R(0, 286, 150, "#2f6fd0", 13), R(1, 260, 122, "#37a14a", 13),
      R(23, 338, 62, "#e6b800", 9, "▲"), R(22, 338, 126, "#e6b800", 9, "▼"), R(21, 310, 94, "#e6b800", 9, "◀"), R(20, 366, 94, "#e6b800", 9, "▶"),
      P(10, 88, 40, "L", 62, 10), P(11, 332, 40, "R", 62, 10), P(12, 210, 212, "Z (under the stick)", 92, 10)] },
    GBA: { body: "hand", fill: "#5a4fa8", items: [DP(82, 120), R(0, 322, 134, "#ccc", 13), R(8, 356, 110, "#ccc", 13), P(2, 58, 182, "Select"), P(3, 362, 182, "Start"), P(10, 70, 32, "L", 62, 10), P(11, 350, 32, "R", 62, 10)] },
    GB: { body: "hand", fill: "#b8b5a9", items: [DP(82, 120), R(0, 322, 134, "#8b1d4f", 13), R(8, 356, 110, "#8b1d4f", 13), P(2, 58, 182, "Select"), P(3, 362, 182, "Start")] },
    MAME: { body: "panel", fill: "#26262d", items: [stick4([4, 5, 6, 7]), R(0, 228, 148, "#d32", 14, "1"), R(8, 268, 142, "#fc0", 14, "2"), R(1, 308, 142, "#2b6", 14, "3"), R(9, 228, 104, "#27c", 14, "4"), R(10, 268, 98, "#b4c", 14, "5"), R(11, 308, 98, "#e72", 14, "6"), P(2, 186, 72, "Coin", 36, 12), P(3, 238, 72, "Start", 36, 12)] },
    NEOGEO: { body: "panel", fill: "#18181d", items: [stick4([4, 5, 6, 7]), R(0, 222, 134, "#d32", 16), R(8, 262, 118, "#fc0", 16), R(1, 302, 110, "#2b6", 16), R(9, 342, 112, "#27c", 16), P(2, 212, 72, "Coin", 36, 12), P(3, 264, 72, "Start", 36, 12)] },
  };
  const SYS_NAMES = { NES: "NES", SNES: "SNES", Genesis: "Genesis", SMS: "Master System", N64: "N64", GBA: "GBA", GB: "Game Boy", MAME: "Arcade (MAME)", NEOGEO: "Neo Geo" };

  // ── names of the buttons on the controller in your hands ───────────────────────
  const NAMES = {
    xbox: ["A", "B", "X", "Y", "LB", "RB", "LT", "RT", "View", "Menu", "L3", "R3", "D-up", "D-down", "D-left", "D-right", "Guide"],
    ps: ["Cross", "Circle", "Square", "Triangle", "L1", "R1", "L2", "R2", "Share", "Options", "L3", "R3", "D-up", "D-down", "D-left", "D-right", "PS"],
    nin: ["B", "A", "Y", "X", "L", "R", "ZL", "ZR", "-", "+", "L3", "R3", "D-up", "D-down", "D-left", "D-right", "Home"],
  };
  function family(gp) {
    const id = (gp && gp.id || "").toLowerCase();
    if (gp && gp.mapping !== "standard") return "raw";
    if (/054c|dualshock|dualsense|playstation/.test(id)) return "ps";
    if (/057e|pro controller|joy-?con/.test(id)) return "nin";
    return "xbox";
  }
  function buttonName(i, gp) {
    const f = family(gp);
    return f === "raw" ? "Button " + i : (NAMES[f][i] || "Button " + i);
  }
  function labelIndex(label) {
    const b = BTN.indexOf(label);
    if (b >= 0) return b;
    const m = /^GAMEPAD_(\d+)$/.exec(label || "");
    return m ? +m[1] : -1;
  }
  function parseAxis(label) {
    const m = /^(?:(LEFT_STICK_X|LEFT_STICK_Y|RIGHT_STICK_X|RIGHT_STICK_Y)|EXTRA_STICK_(\d+)):([+-])1$/.exec(label || "");
    return m ? { axis: m[1] ? AXES.indexOf(m[1]) : +m[2], sign: m[3] === "+" ? 1 : -1 } : null;
  }
  function labelName(label, gp) {
    if (!label) return "not set";
    const a = parseAxis(label);
    if (a) {
      if (a.axis > 3 || (gp && gp.mapping !== "standard")) return "Axis " + a.axis + (a.sign > 0 ? " +" : " -");
      return (a.axis < 2 ? "Left stick " : "Right stick ") + (a.axis % 2 ? (a.sign > 0 ? "down" : "up") : (a.sign > 0 ? "right" : "left"));
    }
    const i = labelIndex(label);
    return i >= 0 ? buttonName(i, gp) : label;
  }
  // the drawing has little room: "RS ↑" for "Right stick up"
  function shortName(label, gp) {
    const a = parseAxis(label);
    if (a && a.axis < 4 && !(gp && gp.mapping !== "standard"))
      return (a.axis < 2 ? "LS " : "RS ") + (a.axis % 2 ? (a.sign > 0 ? "↓" : "↑") : (a.sign > 0 ? "→" : "←"));
    return labelName(label, gp);
  }
  const btnLabel = i => BTN[i] || "GAMEPAD_" + i;
  const axisLabel = (i, v) => (AXES[i] || "EXTRA_STICK_" + i) + (v > 0 ? ":+1" : ":-1");
  // how far a mapped input is pressed, 0..1
  function amount(gp, label) {
    if (!gp || !label) return 0;
    const a = parseAxis(label);
    if (a) {
      const v = (gp.axes[a.axis] || 0) * a.sign;
      return v > DEAD ? Math.min(1, v) : 0;
    }
    const b = gp.buttons[labelIndex(label)];
    return b && (b.pressed || b.value > PRESS) ? 1 : 0;
  }

  // ── profiles, on the drive ─────────────────────────────────────────────────────
  const DEFAULT = "Default";
  let DATA = { profiles: { [DEFAULT]: { maps: {} } }, pads: {} };
  let rev = 1, saveTimer = null;
  function normalize(d) {
    const out = { profiles: {}, pads: {} };
    if (d && typeof d.profiles === "object" && d.profiles) {
      Object.keys(d.profiles).forEach(n => {
        const p = d.profiles[n];
        if (p && typeof p === "object") out.profiles[n] = { maps: (p.maps && typeof p.maps === "object") ? p.maps : {} };
      });
    }
    if (!out.profiles[DEFAULT]) out.profiles[DEFAULT] = { maps: {} };
    if (d && d.pads && typeof d.pads === "object") out.pads = d.pads;
    return out;
  }
  function load() {
    return fetch("/retro/api/controllers").then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!d || !d.profiles) { try { d = JSON.parse(localStorage.getItem("rv_controllers")); } catch (e) { d = null; } }
        if (d) { DATA = normalize(d); rev++; if (isOpen()) render(); }
      }).catch(() => {});
  }
  function save() {
    rev++;
    try { localStorage.setItem("rv_controllers", JSON.stringify(DATA)); } catch (e) { /* the drive has it */ }
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      fetch("/retro/api/controllers", { method: "POST", body: JSON.stringify(DATA) })
        .then(r => { if (!r.ok) throw new Error(r.status); })
        .catch(() => toast("Saved on this computer only: restart Philibert to save controller setups to the drive", true));
    }, 250);
  }
  const profileOf = padId => {
    const n = DATA.pads[padId];
    return n && DATA.profiles[n] ? n : DEFAULT;
  };
  function mapFor(padId, sys) {
    const own = DATA.profiles[profileOf(padId)].maps[sys];
    return Object.assign(defaults(sys), own || {});
  }

  // ── into the emulator ──────────────────────────────────────────────────────────
  function apply(win, sys) {
    const em = win && win.EJS_emulator;
    if (!em || !em.controls || !em.gamepadSelection || !TABLES[sys]) return;
    // the Assign tab: this controller is that player. The frame numbers its pads without gaps.
    const gps = pads();
    const sel = em.gamepadSelection;
    Object.keys(window.GAMEPAD_ASSIGN || {}).forEach(real => {
      const pos = gps.findIndex(g => g.index === +real), pl = GAMEPAD_ASSIGN[real];
      if (pos < 0 || !(pl >= 0 && pl < sel.length)) return;
      const key = gps[pos].id + "_" + pos;
      if (sel[pl] === key) return;
      sel.forEach((k, i) => { if (k === key) sel[i] = ""; });
      sel[pl] = key;
      if (em.updateGamepadLabels) em.updateGamepadLabels();
    });
    const sig = rev + "|" + sel.join("|");
    if (win._rvPadSig === sig) return;
    win._rvPadSig = sig;
    for (let s = 0; s < 4; s++) {
      const padId = (sel[s] || "").replace(/_\d+$/, "");
      if (!padId && s > 0) continue;
      const map = mapFor(padId, sys), ctl = em.controls[s] = em.controls[s] || {};
      Object.keys(TABLES[sys]).forEach(id => {
        ctl[id] = ctl[id] || {};
        if (map[id]) ctl[id].value2 = map[id]; else delete ctl[id].value2;
      });
    }
    if (em.checkGamepadInputs) em.checkGamepadInputs();
  }
  setInterval(() => {
    const f = $("emu-iframe"), g = activeGameIdx >= 0 ? LIBRARY[activeGameIdx] : null;
    if (g && f && f.contentWindow) { try { apply(f.contentWindow, g.system); } catch (e) { console.warn("[RVPads]", e); } }
  }, 500);

  // ── the screen ─────────────────────────────────────────────────────────────────
  let sys = "N64", padIdx = -1, listening = null, timer = null, last = "", lastAt = 0;
  const pads = () => (navigator.getGamepads ? Array.from(navigator.getGamepads()).filter(g => g && g.connected !== false) : []);
  const curPad = () => { const l = pads(); return l.find(g => g.index === padIdx) || l[0] || null; };
  const isOpen = () => { const m = $("ctrl-modal"); return m && m.classList.contains("open"); };
  const padIdOf = gp => (gp ? gp.id : "");

  const css = document.createElement("style");
  css.textContent = `
#ctrl-modal .modal{width:min(980px,100%)!important}
.rp-top{display:flex;flex-wrap:wrap;gap:.5rem .75rem;align-items:flex-end;padding:.75rem 1.25rem}
.rp-top label{display:flex;flex-direction:column;gap:.2rem;font-size:.66rem;color:var(--muted);min-width:0;flex:1 1 150px}
.rp-top .form-select{width:100%}
.rp-mon{margin:0 1.25rem;padding:.55rem .8rem;background:var(--surface2);border:1px solid var(--border2);border-radius:8px;min-height:2.5rem}
.rp-now{font-size:.9rem;font-weight:700;color:var(--accent2);min-height:1.2rem;overflow-wrap:anywhere}
.rp-raw{display:flex;flex-wrap:wrap;gap:3px;margin-top:.4rem}
.rp-raw span{font-size:.6rem;padding:1px 5px;border-radius:4px;background:var(--surface3);color:var(--dim)}
.rp-raw span.on{background:var(--accent);color:#fff}
.rp-warn{margin:.5rem 1.25rem 0;font-size:.7rem;line-height:1.5;color:var(--muted)}
.rp-pads{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(320px,100%),1fr));gap:.75rem;padding:.75rem 1.25rem}
.rp-pad h4{margin:0 0 .3rem;font-size:.72rem;color:var(--muted);font-weight:600}
.rp-pad svg{width:100%;height:auto;display:block;background:var(--surface2);border-radius:8px}
.rp-c{cursor:pointer}
.rp-c .rp-s{transition:fill .06s}
.rp-c.on .rp-s,.rp-c.hover .rp-s{fill:#ff6ec7!important;stroke:#fff}
.rp-c.wait .rp-s{fill:#39d0ff!important;stroke:#fff}
.rp-y.on .rp-s{fill:#ff6ec7!important;stroke:#fff}
.rp-y.hover .rp-s{fill:#39d0ff!important;stroke:#fff}
.rp-t{font:600 10px system-ui,sans-serif;fill:#fff;pointer-events:none;paint-order:stroke;stroke:#0009;stroke-width:2.5px}
.rp-tag{font:700 9.5px system-ui,sans-serif;fill:#ffe27a;pointer-events:none;paint-order:stroke;stroke:#000c;stroke-width:3px}
.rp-rows{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(215px,100%),1fr));gap:.35rem;padding:0 1.25rem .9rem}
.rp-row{display:flex;align-items:center;gap:.4rem;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:.3rem .5rem;font-size:.72rem;cursor:pointer;color:var(--text);font-family:inherit;text-align:left}
.rp-row:hover,.rp-row.on{border-color:var(--accent2)}
.rp-row.on{background:var(--surface3)}
.rp-row.wait{border-color:#39d0ff;background:var(--surface3)}
.rp-row b{flex:1;font-weight:600;min-width:0}
.rp-row i{font-style:normal;color:var(--accent2);text-align:right}
.rp-btns{display:flex;flex-wrap:wrap;gap:.4rem;padding:0 1.25rem .9rem}
.rp-btns button{font-size:.68rem;padding:.3rem .65rem}`;
  document.head.appendChild(css);

  function classicSvg(map, gp) {
    const d = DRAW[sys], tag = (id, x, y, a = "middle") => `<text class="rp-tag" x="${x}" y="${y}" text-anchor="${a}">${esc(shortName(map[id], gp))}</text>`;
    const c = (id, inner) => `<g class="rp-c" data-id="${id}">${inner}</g>`;
    const t = (x, y, s) => `<text class="rp-t" x="${x}" y="${y}" text-anchor="middle" dominant-baseline="central">${esc(s)}</text>`;
    let out = "";
    d.items.forEach(it => {
      if (it.k === "dpad") {
        const [u, dn, l, r] = it.ids, w = 15, h = 18;
        out += `<rect x="${it.x - 8}" y="${it.y - 8}" width="16" height="16" fill="#222"/>`;
        out += c(u, `<rect class="rp-s" x="${it.x - w / 2}" y="${it.y - 8 - h}" width="${w}" height="${h}" fill="#222"/>`) + tag(u, it.x, it.y - 31);
        out += c(dn, `<rect class="rp-s" x="${it.x - w / 2}" y="${it.y + 8}" width="${w}" height="${h}" fill="#222"/>`) + tag(dn, it.x, it.y + 37);
        out += c(l, `<rect class="rp-s" x="${it.x - 8 - h}" y="${it.y - w / 2}" width="${h}" height="${w}" fill="#222"/>`) + tag(l, it.x - 30, it.y + 3, "end");
        out += c(r, `<rect class="rp-s" x="${it.x + 8}" y="${it.y - w / 2}" width="${h}" height="${w}" fill="#222"/>`) + tag(r, it.x + 30, it.y + 3, "start");
      } else if (it.k === "stick") {
        const [u, dn, l, r] = it.ids, o = it.r;
        out += `<circle cx="${it.x}" cy="${it.y}" r="${o}" fill="#333"/>`;
        out += c(u, `<path class="rp-s" d="M${it.x - 7} ${it.y - o + 11}l7-10l7 10z" fill="#999"/>`) + tag(u, it.x, it.y - o - 4);
        out += c(dn, `<path class="rp-s" d="M${it.x - 7} ${it.y + o - 11}l7 10l7-10z" fill="#999"/>`) + tag(dn, it.x, it.y + o + 11);
        out += c(l, `<path class="rp-s" d="M${it.x - o + 11} ${it.y - 7}l-10 7l10 7z" fill="#999"/>`) + tag(l, it.x - o - 4, it.y + 3, "end");
        out += c(r, `<path class="rp-s" d="M${it.x + o - 11} ${it.y - 7}l10 7l-10 7z" fill="#999"/>`) + tag(r, it.x + o + 4, it.y + 3, "start");
      } else if (it.k === "r") {
        const name = it.t || TABLES[sys][it.id];
        out += c(it.id, `<circle class="rp-s" cx="${it.x}" cy="${it.y}" r="${it.r}" fill="${it.fill}"/>`) + t(it.x, it.y, name) + tag(it.id, it.x, it.y + it.r + 10);
      } else {
        out += c(it.id, `<rect class="rp-s" x="${it.x - it.w / 2}" y="${it.y - it.h / 2}" width="${it.w}" height="${it.h}" rx="${it.h / 2}" fill="#333"/>`) + t(it.x, it.y, it.t) + tag(it.id, it.x, it.y + it.h / 2 + 10);
      }
    });
    return `<svg viewBox="0 0 420 240" role="img" aria-label="${esc(SYS_NAMES[sys])} controller"><g fill="${d.fill}">${BODY[d.body]}</g>${out}</svg>`;
  }
  function yourSvg(gp) {
    const f = i => buttonName(i, gp);
    const y = (i, inner) => `<g class="rp-y" data-b="${i}">${inner}</g>`;
    const t = (x, yy, s, cls = "rp-t") => `<text class="${cls}" x="${x}" y="${yy}" text-anchor="middle" dominant-baseline="central">${esc(s)}</text>`;
    const round = (i, x, yy, fill, r = 15) => y(i, `<circle class="rp-s" cx="${x}" cy="${yy}" r="${r}" fill="${fill}"/>`) + t(x, yy, f(i));
    const pill = (i, x, yy, w, h) => y(i, `<rect class="rp-s" x="${x - w / 2}" y="${yy - h / 2}" width="${w}" height="${h}" rx="${h / 2}" fill="#3a3d48"/>`) + t(x, yy, f(i));
    const dx = 150, dy = 158, a = 15, l = 19;
    const arm = (i, x, yy, w, h) => y(i, `<rect class="rp-s" x="${x}" y="${yy}" width="${w}" height="${h}" fill="#3a3d48"/>`);
    const stick = (i, x, yy) => `<circle cx="${x}" cy="${yy}" r="25" fill="#23252d"/>` + y(i, `<circle class="rp-s rp-dot" data-st="${i}" cx="${x}" cy="${yy}" r="15" fill="#3a3d48"/>`) + `<text class="rp-t rp-dott" data-st="${i}" x="${x}" y="${yy}" text-anchor="middle" dominant-baseline="central">${esc(f(i))}</text>`;
    return `<svg viewBox="0 0 420 240" role="img" aria-label="Your controller"><path fill="#50535f" d="M95 58h230q40 0 52 40l26 82q10 40-22 44t-48-28l-22-34h-202l-22 34q-16 32-48 28t-22-44l26-82q12-40 52-40z"/>`
      + pill(6, 88, 22, 56, 16) + pill(7, 332, 22, 56, 16) + pill(4, 92, 46, 62, 16) + pill(5, 328, 46, 62, 16)
      + stick(10, 100, 104) + stick(11, 268, 158)
      + `<rect x="${dx - 8}" y="${dy - 8}" width="16" height="16" fill="#3a3d48"/>`
      + arm(12, dx - a / 2, dy - 8 - l, a, l) + arm(13, dx - a / 2, dy + 8, a, l) + arm(14, dx - 8 - l, dy - a / 2, l, a) + arm(15, dx + 8, dy - a / 2, l, a)
      + t(dx, dy - 18, "▲") + t(dx, dy + 18, "▼") + t(dx - 18, dy, "◀") + t(dx + 18, dy, "▶")
      + pill(8, 178, 96, 40, 14) + pill(9, 242, 96, 40, 14) + round(16, 210, 72, "#3a3d48", 11)
      + round(0, 322, 132, "#3d9b49") + round(1, 352, 104, "#c0392b") + round(2, 292, 104, "#2f6fd0") + round(3, 322, 76, "#c9a227") + `</svg>`;
  }
  function render() {
    const host = $("cpsetup"); if (!host) return;
    const list = pads(), gp = curPad(), padId = padIdOf(gp), prof = profileOf(padId), map = mapFor(padId, sys);
    const rows = Object.keys(TABLES[sys]).map(id => `<button type="button" class="rp-row" data-id="${id}"><b>${esc(TABLES[sys][id])}</b><span style="color:var(--dim)">→</span><i>${esc(labelName(map[id], gp))}</i></button>`).join("");
    host.innerHTML = `
      <div class="rp-top">
        <label>Controller<select class="form-select" id="rp-pad">${list.length ? list.map(g => `<option value="${g.index}"${gp && g.index === gp.index ? " selected" : ""}>${esc(g.id.substring(0, 60))}</option>`).join("") : "<option>No controller - plug one in and press a button</option>"}</select></label>
        <label>Setup (profile)<select class="form-select" id="rp-prof">${Object.keys(DATA.profiles).map(n => `<option${n === prof ? " selected" : ""}>${esc(n)}</option>`).join("")}</select></label>
        <label>System<select class="form-select" id="rp-sys">${Object.keys(TABLES).map(s => `<option value="${s}"${s === sys ? " selected" : ""}>${esc(SYS_NAMES[s])}</option>`).join("")}</select></label>
      </div>
      <div class="rp-mon"><div class="rp-now" id="rp-now">Press something on your controller</div><div class="rp-raw" id="rp-raw"></div></div>
      ${gp && gp.mapping !== "standard" ? `<div class="rp-warn">This controller doesn't report a standard layout, so the drawing below is only a guide: go by the names in the monitor. If its mode can be changed, XInput (X mode) usually works best.</div>` : ""}
      <div class="rp-pads">
        <div class="rp-pad"><h4>${esc(SYS_NAMES[sys])} controller, with your button on each. Click one to change it.</h4><div id="rp-classic">${classicSvg(map, gp)}</div></div>
        <div class="rp-pad"><h4>Your controller</h4><div id="rp-your">${yourSvg(gp)}</div></div>
      </div>
      <div class="rp-rows" id="rp-rows">${rows}</div>
      <div class="rp-btns">
        <button class="btn-ghost" id="rp-new">New setup</button>
        <button class="btn-ghost" id="rp-ren"${prof === DEFAULT ? " disabled" : ""}>Rename</button>
        <button class="btn-ghost" id="rp-del"${prof === DEFAULT ? " disabled" : ""}>Delete</button>
        <button class="btn-ghost" id="rp-reset">Reset ${esc(SYS_NAMES[sys])} buttons</button>
      </div>`;
    $("rp-pad").onchange = e => { padIdx = +e.target.value; render(); };
    $("rp-sys").onchange = e => { sys = e.target.value; last = ""; cancelListen(); render(); };
    $("rp-prof").onchange = e => { if (padId) { DATA.pads[padId] = e.target.value; save(); } else toast("Plug a controller in first", true); render(); };
    $("rp-new").onclick = () => {
      const n = askName("Name for the new setup", "");
      if (!n) return;
      DATA.profiles[n] = JSON.parse(JSON.stringify(DATA.profiles[prof]));      // starts as a copy of this one
      if (padId) DATA.pads[padId] = n;
      save(); render();
    };
    $("rp-ren").onclick = () => {
      const n = askName("New name for this setup", prof);
      if (!n || n === prof) return;
      DATA.profiles[n] = DATA.profiles[prof]; delete DATA.profiles[prof];
      Object.keys(DATA.pads).forEach(k => { if (DATA.pads[k] === prof) DATA.pads[k] = n; });
      save(); render();
    };
    $("rp-del").onclick = () => {
      if (!confirm(`Delete the setup "${prof}"?`)) return;
      delete DATA.profiles[prof];
      Object.keys(DATA.pads).forEach(k => { if (DATA.pads[k] === prof) delete DATA.pads[k]; });
      save(); render();
    };
    $("rp-reset").onclick = () => { delete DATA.profiles[prof].maps[sys]; save(); render(); };
    const pick = e => { const el = e.target.closest("[data-id]"); if (el) startListen(el.dataset.id); };
    $("rp-classic").onclick = pick; $("rp-rows").onclick = pick;
    // pointing at a classic button shows what drives it
    const hover = e => {
      document.querySelectorAll(".rp-y.hover,.rp-c.hover").forEach(x => x.classList.remove("hover"));
      const el = e.target.closest("[data-id]"); if (!el) return;
      document.querySelectorAll(`.rp-c[data-id="${el.dataset.id}"]`).forEach(x => x.classList.add("hover"));
      const m = mapFor(padIdOf(curPad()), sys)[el.dataset.id], i = labelIndex(m);
      const a = parseAxis(m), b = i >= 0 ? i : a && a.axis < 4 ? (a.axis < 2 ? 10 : 11) : -1;
      if (b >= 0) document.querySelectorAll(`.rp-y[data-b="${b}"]`).forEach(x => x.classList.add("hover"));
    };
    $("rp-classic").onmouseover = hover; $("rp-rows").onmouseover = hover;
  }
  function askName(q, v) {
    const n = (prompt(q, v) || "").trim().slice(0, 40);
    if (!n) return "";
    if (n !== v && DATA.profiles[n]) { toast("There is already a setup with that name", true); return ""; }
    return n;
  }

  // ── pressing a button to map it ────────────────────────────────────────────────
  function startListen(id) {
    const gp = curPad();
    if (!gp) { toast("Plug a controller in and press a button first", true); return; }
    cancelListen();
    listening = { id, base: gp.buttons.map(b => b.pressed || b.value > PRESS), axes: Array.from(gp.axes), at: Date.now() };
    markListen(true);
  }
  function markListen(on) {
    if (!listening) return;
    document.querySelectorAll(`[data-id="${listening.id}"]`).forEach(x => x.classList.toggle("wait", on));
    const row = document.querySelector(`.rp-row[data-id="${listening.id}"] i`);
    if (row && on) row.textContent = "Press a button…";
  }
  function cancelListen() {
    if (!listening) return;
    markListen(false); listening = null;
    render();
  }
  function assign(id, label) {
    const gp = curPad(), padId = padIdOf(gp), prof = profileOf(padId);
    const maps = DATA.profiles[prof].maps, cur = mapFor(padId, sys);
    const own = maps[sys] = maps[sys] || {};
    // a button drives one thing: whatever used it goes to what this one had
    Object.keys(cur).forEach(k => { if (k !== id && cur[k] === label) { own[k] = cur[id] || ""; toast(TABLES[sys][k] + " and " + TABLES[sys][id] + " swapped"); } });
    own[id] = label;
    listening = null;
    save(); render();
  }
  function checkListen(gp) {
    if (!listening) return;
    if (Date.now() - listening.at > 10000) { cancelListen(); return; }
    for (let i = 0; i < gp.buttons.length; i++) {
      const b = gp.buttons[i], on = b.pressed || b.value > PRESS;
      if (on && !listening.base[i]) { assign(listening.id, btnLabel(i)); return; }
      if (!on) listening.base[i] = false;
    }
    for (let i = 0; i < gp.axes.length; i++) {
      const v = gp.axes[i], was = listening.axes[i] || 0;
      if (Math.abs(v) > 0.7 && Math.abs(was) < 0.4) { assign(listening.id, axisLabel(i, v)); return; }
      if (Math.abs(v) < 0.4) listening.axes[i] = v;
    }
  }

  // ── the live monitor ───────────────────────────────────────────────────────────
  function monitor() {
    if (!isOpen()) { stopMon(); return; }
    const list = pads();
    if (list.length !== monitor.n) { monitor.n = list.length; if (!listening) render(); }
    const gp = curPad(), now = $("rp-now"), raw = $("rp-raw");
    if (!now || !raw) return;
    document.querySelectorAll(".rp-y.on,.rp-c.on,.rp-row.on").forEach(x => x.classList.remove("on"));
    if (!gp) { now.textContent = "No controller seen. Plug one in and press a button."; raw.innerHTML = ""; return; }
    // a pressed button somewhere else selects that controller
    const other = list.find(g => g.index !== gp.index && g.buttons.some(b => b.pressed));
    if (other && !listening) { padIdx = other.index; render(); return; }
    checkListen(gp);
    if (!$("rp-now")) return;
    const map = mapFor(padIdOf(gp), sys), said = [];
    gp.buttons.forEach((b, i) => {
      if (!(b.pressed || b.value > PRESS)) return;
      document.querySelectorAll(`.rp-y[data-b="${i}"]`).forEach(x => x.classList.add("on"));
      said.push(buttonName(i, gp) + (family(gp) === "raw" ? "" : ` (button ${i})`));
    });
    gp.axes.forEach((v, i) => {
      if (Math.abs(v) <= PRESS) return;
      said.push(labelName(axisLabel(i, v), gp) + ` (axis ${i} ${v.toFixed(2)})`);
    });
    [[10, 0, 1], [11, 2, 3]].forEach(([b, ax, ay]) => {
      const dx = (gp.axes[ax] || 0) * 11, dy = (gp.axes[ay] || 0) * 11;
      document.querySelectorAll(`[data-st="${b}"]`).forEach(el => { el.setAttribute("transform", `translate(${dx.toFixed(1)} ${dy.toFixed(1)})`); });
    });
    const hits = [];
    Object.keys(map).forEach(id => {
      if (amount(gp, map[id]) <= 0) return;
      document.querySelectorAll(`.rp-c[data-id="${id}"],.rp-row[data-id="${id}"]`).forEach(x => x.classList.add("on"));
      hits.push(TABLES[sys][id]);
    });
    if (said.length) {
      last = said.join(" + ") + "  →  " + SYS_NAMES[sys] + ": " + (hits.length ? hits.join(" + ") : "nothing");
      lastAt = Date.now();
    }
    if (listening) now.textContent = "Press the button for " + TABLES[sys][listening.id] + "…";
    else now.textContent = last && Date.now() - lastAt < 4000 ? last : "Press something on your controller";
    const chips = gp.buttons.map((b, i) => `<span class="${b.pressed || b.value > PRESS ? "on" : ""}">B${i}</span>`)
      .concat(Array.from(gp.axes).map((v, i) => `<span class="${Math.abs(v) > PRESS ? "on" : ""}">A${i} ${v.toFixed(2)}</span>`)).join("");
    if (raw.innerHTML !== chips) raw.innerHTML = chips;
  }
  function stopMon() { clearInterval(timer); timer = null; listening = null; }

  // ── a stream of a game someone else hosts: this controller -> control ids ──────
  function readPad(gp, system, n) {
    const s = TABLES[system] ? system : "N64", map = mapFor(gp.id, s), v = new Array(n).fill(0);
    Object.keys(map).forEach(id => {
      const a = amount(gp, map[id]);
      if (a > 0) v[id] = +id >= 16 && +id <= 23 ? Math.round(32767 * a) : 1;
    });
    return v;
  }

  window.RVPads = {
    readPad, mapFor, TABLES, defaults, labelName,
    open() {
      const g = activeGameIdx >= 0 ? LIBRARY[activeGameIdx] : null;
      if (g && TABLES[g.system]) sys = g.system;
      render();
      if (!timer) timer = setInterval(monitor, 33);
    }
  };
  load();
})();
