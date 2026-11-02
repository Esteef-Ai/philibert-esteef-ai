// Retro Vault code book: the game's cheat codes as a printed booklet. Clicking a code turns it on
// in the running game; the codes in use are saved on the drive and come back next time.
// The codes are libretro-database's, fetched per game by the server and kept on the drive.
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const SYSTEMS = ["NES", "SNES", "Genesis", "SMS", "GB"];        // the cores take these systems' codes
  const NAMES = { NES: "Nintendo Entertainment System", SNES: "Super Nintendo", Genesis: "Genesis / Mega Drive", SMS: "Master System", GB: "Game Boy" };
  const PAGE_LINES = 19;      // lines of print on a page: a long effect takes several
  let book = null, page = 0, active = [], filter = "", wasPaused = false;

  const GG = {
    NES: /^[APZLGITYEOXUKSVN]{6}$|^[APZLGITYEOXUKSVN]{8}$/i,
    GB: /^[0-9A-F]{3}-[0-9A-F]{3}(-[0-9A-F]{3})?$/i,
    SNES: /^[0-9A-F]{4}-[0-9A-F]{4}$/i,
    Genesis: /^[A-Z0-9]{4}-[A-Z0-9]{4}$/i,
    SMS: /^[0-9A-F]{3}-[0-9A-F]{3}(-[0-9A-F]{3})?$/i,
  };
  const game = () => (activeGameIdx >= 0 ? LIBRARY[activeGameIdx] : null);
  const frame = () => { const f = $("emu-iframe"); return f && f.contentWindow; };
  const keyOf = g => "rvcheat_" + padSystem(g) + "_" + (g.title || g.filename || "game").replace(/[^a-zA-Z0-9 _-]/g, "").trim();
  const isGenie = (code, sys) => code.split("+").every(c => (GG[sys] || /$^/).test(c.trim()));

  const css = document.createElement("style");
  css.textContent = `
#book-modal{display:none;position:fixed;inset:0;z-index:700;background:rgba(0,0,0,.86);align-items:center;justify-content:center;padding:.5rem}
#book-modal.open{display:flex}
.bk{width:min(1040px,100%);max-height:100%;display:flex;flex-direction:column;gap:.5rem}
.bk-bar{display:flex;flex-wrap:wrap;gap:.4rem .5rem;align-items:center;color:#ddd;font:12px system-ui,sans-serif}
.bk-bar input{background:#1c1c22;border:1px solid #555;border-radius:5px;color:#eee;padding:.3rem .5rem;font:12px system-ui,sans-serif;min-width:0;flex:1 1 130px}
.bk-bar button,.bk-nav button{background:#2b2b33;border:1px solid #666;border-radius:5px;color:#eee;padding:.3rem .65rem;font:12px system-ui,sans-serif;cursor:pointer}
.bk-bar button:hover,.bk-nav button:hover:not(:disabled){background:#44444f}
.bk-nav button:disabled{opacity:.35;cursor:default}
.bk-use{color:#ffe27a;font-weight:600}
.bk-spread{flex:1;min-height:0;display:flex;background:#f4f1e6;color:#111;border-radius:3px;box-shadow:0 12px 40px #000c;overflow:auto;perspective:1400px}
.bk-page{flex:1 1 50%;min-width:0;padding:1.1rem 1.3rem .7rem;display:flex;flex-direction:column;position:relative;background:#f4f1e6}
.bk-page:first-child{border-right:1px solid #bbb6a6;box-shadow:inset -14px 0 18px -14px #0005}
.bk-page:last-child{box-shadow:inset 14px 0 18px -14px #0005}
.bk-turn .bk-page:last-child{animation:bkturn .22s ease-out}
@keyframes bkturn{from{transform:rotateY(-24deg);transform-origin:left}to{transform:none;transform-origin:left}}
.bk-head{font:900 1.05rem/1.1 "Arial Black",Impact,system-ui,sans-serif;border-bottom:3px double #111;padding-bottom:.25rem;margin-bottom:.4rem;text-transform:uppercase;overflow-wrap:anywhere}
.bk-cols{display:flex;gap:.6rem;font:700 .62rem system-ui,sans-serif;letter-spacing:.06em;color:#555;text-transform:uppercase;margin-bottom:.15rem}
.bk-cols span:first-child{width:7.2rem;flex:none}
.bk-row{display:flex;gap:.6rem;align-items:baseline;width:100%;background:none;border:0;border-bottom:1px dotted #aaa698;padding:.22rem .15rem;text-align:left;cursor:pointer;color:inherit;font:inherit}
.bk-row:hover{background:#e9e4cf}
.bk-row:focus-visible{outline:2px solid #1d3fbf;outline-offset:-2px}
.bk-code{width:7.2rem;flex:none;font:700 .8rem "Courier New",Courier,monospace;overflow-wrap:anywhere}
.bk-eff{font:.76rem/1.25 Georgia,"Times New Roman",serif;flex:1;min-width:0;overflow-wrap:anywhere}
.bk-tag{font:700 .55rem system-ui,sans-serif;color:#777;border:1px solid #aaa;border-radius:3px;padding:0 3px;margin-left:.3rem;white-space:nowrap}
.bk-row.on{background:#fff27a}
.bk-row.on .bk-code{color:#b3121d}
.bk-row.on .bk-eff::before{content:"✓ ";color:#b3121d;font-weight:700}
.bk-foot{margin-top:auto;padding-top:.45rem;text-align:center;font:700 .72rem Georgia,serif;color:#444}
.bk-msg{margin:auto;text-align:center;font:.92rem/1.5 Georgia,serif;max-width:26rem;padding:1rem}
.bk-nav{display:flex;align-items:center;justify-content:center;gap:.6rem;color:#ccc;font:12px system-ui,sans-serif}
.bk-cover{flex:1;min-height:min(62vh,520px);background:repeating-conic-gradient(from 0deg at 50% 118%,#1236b8 0 7deg,#0b2592 7deg 14deg);color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:.8rem;padding:1.5rem;text-align:center;cursor:pointer;border:0;width:100%;font:inherit}
.bk-title{font:900 clamp(2.4rem,9vw,5.2rem)/.95 "Arial Black",Impact,system-ui,sans-serif;color:#ff2a2a;-webkit-text-stroke:2px #fff;paint-order:stroke;letter-spacing:.02em;transform:skewY(-3deg);text-shadow:5px 6px 0 #0a1a66}
.bk-for{font:800 clamp(1rem,3vw,1.5rem) "Arial Black",system-ui,sans-serif;background:#fff;color:#0b2592;padding:.3rem 1rem;transform:rotate(-1deg);overflow-wrap:anywhere;max-width:100%}
.bk-sys{font:700 .95rem system-ui,sans-serif;color:#ffe27a}
.bk-open{font:600 .78rem system-ui,sans-serif;color:#dfe6ff}
.bk-src{font:.62rem system-ui,sans-serif;color:#667}
@media (max-width:720px){.bk-spread{flex-direction:column}.bk-page:first-child{border-right:0;border-bottom:1px solid #bbb6a6}}
@media (prefers-reduced-motion:reduce){.bk-turn .bk-page:last-child{animation:none}}`;
  document.head.appendChild(css);

  const modal = document.createElement("div");
  modal.id = "book-modal";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-label", "Code book");
  document.body.appendChild(modal);

  // ── in the running game ────────────────────────────────────────────────────────
  function applyCodes() {
    const w = frame(), gm = w && w.EJS_emulator && w.EJS_emulator.gameManager;
    if (!gm || !gm.resetCheat) return;
    gm.resetCheat();
    active.forEach((c, i) => gm.setCheat(i, 1, c.code));
  }
  function saveActive(g) {
    fetch("/retro/api/cheats-on", { method: "POST", body: JSON.stringify({ key: keyOf(g), active }) })
      .then(r => { if (!r.ok) throw new Error(r.status); })
      .catch(() => toast("Codes are on for now, but couldn't be saved: restart Philibert", true));
  }
  // Codes saved for this game go back on when it starts (never in a lockstep match: it would desync)
  setInterval(() => {
    const g = game(), w = frame();
    if (!g || !w || !w._ejsReady || w._rvCodes || window._rvNetplay) return;
    w._rvCodes = true;
    if (!SYSTEMS.includes(padSystem(g))) return;
    fetch("/retro/api/cheats-on?key=" + encodeURIComponent(keyOf(g))).then(r => (r.ok ? r.json() : null)).then(d => {
      active = (d && d.active) || [];
      if (active.length) { applyCodes(); toast(active.length + " code" + (active.length > 1 ? "s" : "") + " on from the code book"); }
    }).catch(() => {});
  }, 700);

  // ── the book ───────────────────────────────────────────────────────────────────
  function codes() {
    const own = active.filter(c => c.own).map(c => ({ c: c.code, d: c.desc }));
    const q = filter.toLowerCase();
    return own.concat(book.codes).filter(x => !q || x.d.toLowerCase().includes(q) || x.c.toLowerCase().includes(q));
  }
  function sides(list) {
    const out = [[]];
    let used = 0;
    list.forEach(x => {
      const lines = Math.ceil((x.d.length + 13) / 58) + (x.c.length > 13 ? 1 : 0);
      if (used + lines > PAGE_LINES && out[out.length - 1].length) { out.push([]); used = 0; }
      out[out.length - 1].push(x);
      used += lines;
    });
    return out;
  }
  function row(x, sys) {
    const on = active.some(a => a.code === x.c);
    return `<button type="button" class="bk-row${on ? " on" : ""}" data-code="${esc(x.c)}" data-desc="${esc(x.d)}" aria-pressed="${on}"><span class="bk-code">${esc(x.c)}</span><span class="bk-eff">${esc(x.d)}${isGenie(x.c, sys) ? "" : '<span class="bk-tag">memory code</span>'}</span></button>`;
  }
  function side(list, sys, n, title) {
    const rows = list.length ? `<div class="bk-cols"><span>Code</span><span>Effect</span></div>` + list.map(x => row(x, sys)).join("") : "";
    return `<div class="bk-page"><div class="bk-head">${esc(title)}</div>${rows}<div class="bk-foot">${n}</div></div>`;
  }
  function render(turn) {
    const g = game();
    if (!g || !book) return;
    const sys = padSystem(g), title = book.game || g.title || g.filename;
    const bar = `<div class="bk-bar">
      <input id="bk-find" placeholder="Find a code (lives, invincible...)" value="${esc(filter)}" aria-label="Find a code">
      <input id="bk-own" placeholder="Type your own code, then Enter" aria-label="Type your own code">
      <span class="bk-use">${active.length} in use</span>
      <button id="bk-restart" title="Codes like Start with 9 lives only work from the start of the game">Restart game</button>
      <button id="bk-off"${active.length ? "" : " disabled"}>All off</button>
      <button id="bk-close">Back to the game</button></div>`;
    let body;
    if (page === 0) {
      body = `<button type="button" class="bk-cover" id="bk-open"><span class="bk-title">CODE<br>BOOK</span><span class="bk-for">${esc(title)}</span><span class="bk-sys">for ${esc(NAMES[sys] || sys)}</span><span class="bk-open">${book.ok && book.codes.length ? book.codes.length + " codes inside. Click to open" : "Click to open"}</span></button>`;
    } else if (!book.codes.length && !active.some(c => c.own)) {
      body = `<div class="bk-page"><div class="bk-head">${esc(title)}</div><div class="bk-msg">${esc(book.msg || "This book has no codes for this game.")}<br><br>You can still type a code you know in the box above.</div></div>`;
    } else {
      const all = codes(), pp = sides(all);
      body = all.length
        ? side(pp[page * 2 - 2] || [], sys, page * 2 - 1, title) + side(pp[page * 2 - 1] || [], sys, page * 2, title)
        : `<div class="bk-page"><div class="bk-head">${esc(title)}</div><div class="bk-msg">No code here matches “${esc(filter)}”.</div></div>`;
    }
    const pages = page === 0 ? 0 : Math.max(1, Math.ceil(sides(codes()).length / 2));
    modal.innerHTML = `<div class="bk">${bar}
      <div class="bk-spread${turn ? " bk-turn" : ""}">${body}</div>
      <div class="bk-nav"><button id="bk-prev"${page === 0 ? " disabled" : ""}>◀ Previous page</button>
        <span>${page === 0 ? "Cover" : `Pages ${page * 2 - 1}-${page * 2} of ${pages * 2}`}</span>
        <button id="bk-next"${page >= pages && page > 0 ? " disabled" : ""}>Next page ▶</button></div>
      <div class="bk-src" style="text-align:center;color:#889">Codes: libretro-database (CC BY-SA 4.0). Some only work after Restart game; some may not suit your version of the game.</div></div>`;
    const go = d => { page = Math.max(0, Math.min(page + d, pages || 1)); render(true); };
    $("bk-prev").onclick = () => go(-1);
    $("bk-next").onclick = () => go(1);
    if ($("bk-open")) $("bk-open").onclick = () => { page = 1; render(true); };
    $("bk-close").onclick = close;
    $("bk-off").onclick = () => { active = []; applyCodes(); saveActive(g); render(); };
    $("bk-restart").onclick = () => {
      const w = frame(), gm = w && w.EJS_emulator && w.EJS_emulator.gameManager;
      if (gm) { gm.restart(); applyCodes(); }
      close();
    };
    $("bk-find").oninput = e => {
      filter = e.target.value; page = 1;
      const at = e.target.selectionStart; render();
      const f = $("bk-find"); f.focus(); f.setSelectionRange(at, at);
    };
    $("bk-own").onkeydown = e => {
      if (e.key !== "Enter") return;
      const code = e.target.value.trim().toUpperCase().replace(/\s+/g, "");
      if (!/^[A-Z0-9:+-]{4,80}$/.test(code)) { toast("That doesn't look like a code", true); return; }
      if (!active.some(a => a.code === code)) active.push({ code, desc: "Your own code", own: true });
      applyCodes(); saveActive(g); page = 1; render();
    };
    modal.querySelectorAll(".bk-row").forEach(el => {
      el.onclick = () => {
        const code = el.dataset.code, i = active.findIndex(a => a.code === code);
        if (i >= 0) active.splice(i, 1); else active.push({ code, desc: el.dataset.desc });
        applyCodes(); saveActive(g); render();
      };
    });
  }
  function close() {
    modal.classList.remove("open");
    const w = frame(), em = w && w.EJS_emulator;
    if (em && !wasPaused && em.play) em.play();
    if (w) try { w.focus(); } catch (e) { /* ignore */ }
  }
  document.addEventListener("keydown", e => {
    if (!modal.classList.contains("open") || e.target.tagName === "INPUT") return;
    if (e.key === "ArrowRight" && $("bk-next") && !$("bk-next").disabled) $("bk-next").click();
    else if (e.key === "ArrowLeft" && $("bk-prev") && !$("bk-prev").disabled) $("bk-prev").click();
    else if (e.key === "Escape") { e.stopPropagation(); close(); }
  }, true);

  async function open() {
    const g = game();
    if (!g) { toast("Start a game first", true); return; }
    if (window._rvNetplay) { toast("Codes are off during an online match: they'd put the players out of step", true); return; }
    const w = frame(), em = w && w.EJS_emulator;
    if (em && em.pause) { wasPaused = em.paused; em.pause(); }
    filter = ""; page = 0;
    book = { ok: false, codes: [], msg: "Opening the book..." };
    modal.classList.add("open");
    render();
    const sys = padSystem(g);
    try {
      const d = await fetch(`/retro/api/cheats?system=${encodeURIComponent(sys)}&shelf=${encodeURIComponent(g.system)}&file=${encodeURIComponent(g.filename || g.title || "")}`).then(r => r.json());
      book = { ok: !!d.ok, game: d.game, msg: d.msg, codes: (d.codes || []) };
    } catch (e) {
      book = { ok: false, codes: [], msg: "The code book couldn't be loaded." };
    }
    book.codes.sort((a, b) => isGenie(b.c, sys) - isGenie(a.c, sys));     // Game Genie codes first
    render();
  }

  // the button in the game window's bar, for systems that take codes
  const min = $("emu-minimize-btn");
  if (min) {
    const b = document.createElement("button");
    b.className = "emu-action-btn"; b.id = "emu-book-btn"; b.title = "Code book"; b.style.display = "none";
    b.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 21a2 2 0 0 1 2-2h13v2z"/></svg>Codes';
    b.onclick = open;
    min.parentNode.insertBefore(b, min);
    setInterval(() => {
      const g = game();
      const show = g && SYSTEMS.includes(padSystem(g)) && !window._rvNetplay;
      b.style.display = show ? "" : "none";
    }, 700);
  }
  window.RVBook = { open, SYSTEMS };
})();
