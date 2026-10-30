// Retro Vault "Online" window: login, rooms, player slots, game choice, ROM check, start.
// Uses rvnet.js (RVNet) and the page's own helpers: LIBRARY, SYS_MAP, launchGame,
// openModal/closeModal, toast, esc, cleanName.
(function () {
  "use strict";
  const LOCKSTEP_SYSTEMS = ["NES", "SNES", "Genesis", "SMS", "GB", "GBA", "MAME", "NEOGEO"];   // proven deterministic (FBNeo: byte-identical, 2026-10-29)
  const STREAM_ONLY = ["N64"];          // not deterministic in EmulatorJS: the host streams it

  const $ = id => document.getElementById(id);

  // ── markup ──────────────────────────────────────────────────────────────────
  const css = document.createElement("style");
  css.textContent = `
#online-modal .ol-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0}
#online-modal input,#online-modal select{background:var(--surface3,#222);border:1px solid var(--border2,#444);color:inherit;border-radius:6px;padding:6px 9px;font:inherit}
#online-modal .ol-code{font:700 1.5rem/1 monospace;letter-spacing:.18em;color:var(--accent2,#b794f4);cursor:pointer}
#online-modal .ol-pl{display:flex;align-items:center;gap:8px;padding:6px 8px;border-bottom:1px solid var(--border,#333)}
#online-modal .ol-pl .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#online-modal .ol-ok{color:#4ade80}#online-modal .ol-bad{color:#ff7070}#online-modal .ol-dim{color:var(--dim,#888);font-size:.8rem}
#online-modal .ol-games{max-height:200px;overflow:auto;border:1px solid var(--border,#333);border-radius:6px;margin-top:6px}
#online-modal .ol-g{padding:5px 9px;cursor:pointer;display:flex;gap:8px}#online-modal .ol-g:hover{background:var(--surface3,#2a2a3a)}
#online-modal h3{margin:14px 0 4px;font-size:.8rem;letter-spacing:.06em;text-transform:uppercase;color:var(--dim,#999)}
#ol-hud{position:fixed;right:10px;bottom:10px;z-index:99999;background:rgba(0,0,0,.72);color:#ddd;font:12px monospace;padding:4px 8px;border-radius:6px;display:none;pointer-events:none}`;
  document.head.appendChild(css);

  const modal = document.createElement("div");
  modal.className = "modal-overlay"; modal.id = "online-modal";
  modal.innerHTML = `<div class="modal" style="max-width:620px">
  <div class="modal-hdr"><h2>ONLINE PLAY</h2><button class="modal-close" data-close="online-modal">x</button></div>
  <div class="modal-body" id="ol-body" style="max-height:70vh;overflow:auto"></div>
  <div class="modal-footer"><span class="ol-dim" id="ol-status" style="margin-right:auto"></span><button class="btn-ghost" data-close="online-modal">Close</button></div></div>`;
  document.body.appendChild(modal);
  modal.querySelectorAll("[data-close]").forEach(el => el.addEventListener("click", () => closeModal("online-modal")));
  const hud = document.createElement("div"); hud.id = "ol-hud"; document.body.appendChild(hud);

  const tb = document.getElementById("tb-controller");
  if (tb) {
    const b = document.createElement("button");
    b.className = "tb-btn"; b.id = "tb-online"; b.title = "Play together online (2-4 players)";
    b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6"/><path d="M15 15.5c.6-.3 1.3-.5 2-.5 2.5 0 4.5 2 4.5 4.5"/></svg>Online';
    b.onclick = () => { openModal("online-modal"); render(); };
    tb.parentNode.insertBefore(b, tb);
  }

  // ── helpers ─────────────────────────────────────────────────────────────────
  let busy = false, gameFilter = "";
  const status = t => { $("ol-status").textContent = t || ""; };
  const libIndex = g => LIBRARY.findIndex(x => x.system === g.system && x.filename === g.file);
  async function romBytes(g) {
    const url = g.romPath ? (g.romPath.startsWith("http") ? g.romPath : location.origin + g.romPath)
                          : location.origin + "/retro/roms/" + g.system + "/" + encodeURIComponent(g.filename);
    const r = await fetch(url);
    if (!r.ok) throw new Error("couldn't read " + g.filename);
    if (g.system !== "NEOGEO") return r.arrayBuffer();
    // Neo Geo: the game only runs the same everywhere with the same parent + BIOS, so they count too
    const parts = [await r.arrayBuffer()];
    for (const f of [g.parent ? g.parent + ".zip" : null, "neogeo.zip"].filter(Boolean)) {
      const x = await fetch("/retro/neogeo/" + f);
      if (x.ok) parts.push(await x.arrayBuffer());
    }
    return await new Blob(parts).arrayBuffer();
  }

  // ── rendering ───────────────────────────────────────────────────────────────
  function render() {
    const body = $("ol-body"); if (!body) return;
    const R = RVNet.room;
    if (!RVNet.me) {
      body.innerHTML = `
        <p>Up to 4 players: you and 3 friends. Everyone needs the <b>same game file</b> in their own Retro Vault; the leader picks the game.</p>
        <div class="ol-row">${RVNet.token
          ? `<span>Logged in as <b>${esc(RVNet.name || "")}</b></span><button class="btn-primary" id="ol-go">Go online</button><button class="btn-ghost" id="ol-logout">Log out</button>`
          : `<button class="btn-primary" id="ol-login">Log in with Discord</button>`}</div>
        <h3>Or join a friend's room as a guest</h3>
        <div class="ol-row"><input id="ol-guest" placeholder="Your name" maxlength="20" style="width:140px">
          <input id="ol-gcode" placeholder="Room code" maxlength="6" style="width:110px;text-transform:uppercase">
          <button class="btn-ghost" id="ol-gjoin">Join</button></div>
        <h3>Server</h3><div class="ol-row"><input id="ol-server" style="flex:1" value="${esc(RVNet.server)}"></div>`;
      $("ol-server").onchange = e => RVNet.setServer(e.target.value.trim());
      if ($("ol-login")) $("ol-login").onclick = async () => {
        try { status("Waiting for Discord..."); await RVNet.login(); status(""); render(); } catch (e) { status(e.message); }
      };
      if ($("ol-logout")) $("ol-logout").onclick = () => { RVNet.logout(); render(); };
      if ($("ol-go")) $("ol-go").onclick = () => goOnline(null);
      $("ol-gjoin").onclick = () => {
        const n = $("ol-guest").value.trim(), c = $("ol-gcode").value.trim().toUpperCase();
        if (!n || c.length < 4) { status("Enter your name and the room code"); return; }
        goOnline(n, c);
      };
      return;
    }
    if (!R) {
      body.innerHTML = `<div class="ol-row"><span>Online as <b>${esc(RVNet.me.name)}</b></span></div>
        <div class="ol-row">${RVNet.me.guest ? "" : '<button class="btn-primary" id="ol-create">Create a room</button>'}
          <input id="ol-code" placeholder="Room code" maxlength="6" style="width:110px;text-transform:uppercase"><button class="btn-ghost" id="ol-join">Join</button>
          <button class="btn-ghost" id="ol-off" style="margin-left:auto">Go offline</button></div>`;
      const tryIt = p => p.catch(e => status(e.message));
      if ($("ol-create")) $("ol-create").onclick = () => tryIt(RVNet.create());
      $("ol-join").onclick = () => tryIt(RVNet.join($("ol-code").value.trim().toUpperCase()));
      $("ol-off").onclick = () => { RVNet.disconnect(); render(); };
      return;
    }
    const lead = RVNet.isLeader(), playing = R.status !== "lobby";
    const stream = R.mode === "stream";
    const allOk = R.game && (stream ? R.players.find(p => p.uid === R.leader).rom === true
                                    : R.players.filter(p => p.connected).every(p => p.rom === true));
    let h = `<div class="ol-row"><span class="ol-dim">Room code</span><span class="ol-code" id="ol-copy" title="Click to copy">${esc(R.code)}</span>
      <span class="ol-dim">${playing ? "Playing" : "Share the code with your friends"}</span>
      <button class="btn-ghost" id="ol-leave" style="margin-left:auto">Leave</button></div><h3>Players</h3>`;
    R.players.forEach(p => {
      const rom = !R.game ? "" : stream && p.uid !== R.leader ? '<span class="ol-dim" title="Watches the stream from the host - no game file needed">watches</span>' : p.rom === true ? '<span class="ol-ok" title="Same game file">✓ game</span>'
        : p.rom === false ? '<span class="ol-bad" title="Different or missing game file">✗ game</span>' : '<span class="ol-dim">checking…</span>';
      const slotSel = lead && !playing
        ? `<select data-uid="${esc(p.uid)}" class="ol-slot">${[0, 1, 2, 3].map(s => `<option value="${s}"${s === p.slot ? " selected" : ""}>P${s + 1}</option>`).join("")}</select>`
        : `<b>P${p.slot + 1}</b>`;
      // others: the direct link when there is one, else the way through the server
      const link = p.uid !== RVNet.me.uid && RVNet.mesh.peers.get(p.uid);
      const lag = link && link.open
        ? `<span class="${link.rtt > 120 ? "ol-bad" : "ol-ok"}" title="Direct link to this player (round trip)">⇄ ${link.rtt == null ? "…" : link.rtt + " ms"} direct</span>`
        : p.lag == null ? "" : `<span class="${p.lag > 120 ? "ol-bad" : "ol-dim"}" title="Round trip to the server">${p.lag} ms${p.uid === RVNet.me.uid ? "" : " via server"}</span>`;
      h += `<div class="ol-pl">${slotSel}<span class="nm">${esc(p.name)}${p.uid === R.leader ? " 👑" : ""}${p.connected ? "" : " (left)"}</span>${lag}${rom}
        ${lead && !playing && p.uid !== RVNet.me.uid ? `<button class="btn-ghost ol-kick" data-uid="${esc(p.uid)}" title="Remove">✕</button>` : ""}</div>`;
    });
    h += `<h3>Game</h3><div class="ol-row">${R.game ? `<b>${esc(R.game.title)}</b> <span class="ol-dim">${esc(R.game.system)}</span>` : '<span class="ol-dim">Not chosen yet</span>'}</div>
      <div class="ol-dim">${stream ? "Stream mode: the host runs the game and the others watch a live video and play with their own controller. Only the host needs the game file."
                                   : "Everyone runs the game in sync on their own PC - everyone needs the same game file."}</div>`;
    if (lead && !playing) {
      const games = LIBRARY.filter(g => (LOCKSTEP_SYSTEMS.includes(g.system) || STREAM_ONLY.includes(g.system)) && g.romPath &&
        (!gameFilter || (g.title + " " + g.system).toLowerCase().includes(gameFilter)));
      h += `<input id="ol-gf" placeholder="Search your games…" value="${esc(gameFilter)}" style="width:100%">
        <div class="ol-games">${games.slice(0, 200).map(g => `<div class="ol-g" data-i="${LIBRARY.indexOf(g)}"><span class="ol-dim" style="width:58px">${esc(g.system)}</span><span>${esc(g.title)}</span></div>`).join("") || '<div class="ol-g ol-dim">No matching games</div>'}</div>
        <div class="ol-row"><span class="ol-dim">Mode</span><select id="ol-mode"${R.game && STREAM_ONLY.includes(R.game.system) ? " disabled" : ""}>
          <option value="lockstep"${stream ? "" : " selected"}>Everyone runs it (in sync)</option>
          <option value="stream"${stream ? " selected" : ""}>Host streams it</option></select>
          <span class="ol-dim">${R.game && STREAM_ONLY.includes(R.game.system) ? "N64 is always streamed" : ""}</span></div>
        <div class="ol-row" style="margin-top:10px"><span class="ol-dim">Input delay</span>
          <select id="ol-delay" title="How far ahead each press is played. Too small for the slowest player's lag and the game keeps pausing.">
            <option value="auto"${R.auto ? " selected" : ""}>Auto - ${R.autoDelay || R.delay} frames (${Math.round((R.autoDelay || R.delay) * 16.7)} ms)</option>
            ${[2, 3, 4, 5, 6, 8, 10, 12, 15].map(n => `<option value="${n}"${!R.auto && n === R.delay ? " selected" : ""}>${n} frames (${Math.round(n * 16.7)} ms)</option>`).join("")}</select>
          <button class="btn-primary" id="ol-start" style="margin-left:auto"${allOk ? "" : " disabled"}>Start match</button></div>
        ${R.auto && !stream ? `<div class="ol-row"><span class="ol-dim">Feel</span>
          <select id="ol-feel" title="Auto delay plus 0, 1 or 2 frames: a little more delay means fewer pauses when the connection hiccups">
            ${["Lowest lag", "Balanced", "Smoothest"].map((t, n) => `<option value="${n}"${n === (R.feel == null ? 1 : R.feel) ? " selected" : ""}>${t}</option>`).join("")}</select>
          <span class="ol-dim">${["Least delay - can stutter when the line hiccups", "One frame of headroom", "Two frames of headroom - steadiest"][R.feel == null ? 1 : R.feel]}</span></div>` : ""}`;
    } else if (lead && playing) {
      h += `<div class="ol-row"><button class="btn-ghost" id="ol-end">End match</button></div>`;
    } else if (!playing) {
      h += `<div class="ol-dim">The leader picks the game and starts the match.</div>`;
    }
    body.innerHTML = h;
    $("ol-copy").onclick = () => navigator.clipboard && navigator.clipboard.writeText(R.code).then(() => toast("Room code copied"));
    $("ol-leave").onclick = () => { RVNet.leave(); render(); };
    body.querySelectorAll(".ol-slot").forEach(s => s.onchange = () => RVNet.setSlot(s.dataset.uid, +s.value));
    body.querySelectorAll(".ol-kick").forEach(b => b.onclick = () => RVNet.kick(b.dataset.uid));
    if ($("ol-gf")) { $("ol-gf").oninput = e => { gameFilter = e.target.value.toLowerCase(); render(); const f = $("ol-gf"); f.focus(); f.setSelectionRange(f.value.length, f.value.length); }; }
    body.querySelectorAll(".ol-g[data-i]").forEach(el => el.onclick = async () => {
      const g = LIBRARY[+el.dataset.i]; if (!g || busy) return;
      busy = true; status("Reading " + g.title + "…");
      try {
        const sys = SYS_MAP[g.system] || {};
        RVNet.setMode(STREAM_ONLY.includes(g.system) ? "stream" : "lockstep");
        await RVNet.pickGame({ system: g.system, title: g.title, file: g.filename, core: sys.core || "" }, await romBytes(g));
        status("");
      } catch (e) { status(e.message); }
      busy = false;
    });
    if ($("ol-delay")) $("ol-delay").onchange = e => RVNet.setDelay(e.target.value === "auto" ? "auto" : +e.target.value);
    if ($("ol-feel")) $("ol-feel").onchange = e => RVNet.setFeel(+e.target.value);
    if ($("ol-mode")) $("ol-mode").onchange = e => RVNet.setMode(e.target.value);
    if ($("ol-start")) $("ol-start").onclick = () => RVNet.start();
    if ($("ol-end")) $("ol-end").onclick = () => RVNet.end();
  }

  async function goOnline(guest, code) {
    try {
      status("Connecting…");
      await RVNet.connect(guest);
      status("");
      if (code) RVNet.join(code);
      render();
    } catch (e) { status(e.message); }
  }

  // ── events ──────────────────────────────────────────────────────────────────
  let checking = false;
  RVNet.on("room", async R => {
    render();
    // a game was chosen (or the same one again): the server has no answer for MY copy yet -
    // check it (the leader's own check is done by pickGame)
    const mine = RVNet.me && R.players.find(p => p.uid === RVNet.me.uid);
    if (R.game && !RVNet.isLeader() && R.mode !== "stream" && mine && mine.rom == null && !checking) {
      checking = true;
      const i = libIndex(R.game);
      const g = i >= 0 ? LIBRARY[i] : LIBRARY.find(x => x.system === R.game.system && x.title === R.game.title);
      try { await RVNet.checkRom(g ? await romBytes(g) : null); }
      catch (e) { await RVNet.checkRom(null); }
      finally { checking = false; }
      if (!g) toast("You don't have " + R.game.title + " (" + R.game.system + ") in Retro Vault", true);
    }
  });
  RVNet.on("error", d => { status(d.msg); toast(d.msg, true); });
  RVNet.on("me", () => render());
  // out of the room: the game window (if any) closes and the Online window shows where you are
  const backToLobby = () => {
    if (window._rvNetplay || window._rvStreamHost) closeEmu();
    window._rvNetplay = window._rvStreamHost = false; hud.style.display = "none";
    openModal("online-modal"); render();
  };
  RVNet.on("closed", backToLobby);
  RVNet.on("offline", () => render());
  RVNet.on("mesh", () => { if (!RVNet.match) render(); });
  RVNet.on("kicked", () => toast("The leader removed you from the room", true));
  RVNet.on("starting", d => {
    const g = d.game;
    if (d.mode === "stream" && !RVNet.isLeader()) {          // watch the host's stream
      closeModal("online-modal");
      RVStream.view(d.host);
      return;
    }
    window._rvStreamHost = d.mode === "stream";
    let i = libIndex(g);
    if (i < 0) i = LIBRARY.findIndex(x => x.system === g.system && x.title === g.title);
    if (i < 0) { toast("You don't have that game", true); RVNet.leave(); return; }
    closeModal("online-modal");
    window._rvNetplay = d.mode !== "stream";
    launchGame(i);
    hud.style.display = "block"; hud.textContent = "Online: starting…";
  });
  RVNet.on("playing", d => { hud.textContent = d && d.mode === "stream" ? "Streaming: waiting for viewers…" : "Online: P" + (RVNet.mySlot() + 1); });
  RVNet.on("streampeer", p => {
    if (!RVStream.hosting) return;
    const live = [...RVStream.peers.values()].filter(x => x.pc.connectionState === "connected").length;
    hud.style.display = "block";
    hud.textContent = `Streaming to ${live} of ${RVStream.peers.size}`;
    if (p.state === "connected") toast((p.name || "A friend") + " is watching as P" + (p.port + 1));
    if (p.state === "failed") toast("Couldn't connect to " + (p.name || "a friend") + " - their network blocks a direct link", true);
  });
  let slowSeen = 0;
  RVNet.on("playing", () => { slowSeen = 0; });
  RVNet.on("stats", s => {
    if (RVNet.mode !== "stream" && s.frame > 300 && s.fps < 45 && ++slowSeen === 3)
      toast("The match keeps pausing for a slow connection - end it and pick a bigger Input delay (or Host streams it)", true);
    hud.textContent = `Online P${RVNet.mySlot() + 1} · ${s.fps} fps · ${s.directPct >= 50 ? "direct" : "via server"} · waits ${s.stalls}` + (s.resyncs ? ` · resyncs ${s.resyncs}` : "");
  });
  RVNet.on("resync", () => toast("Re-syncing players…"));
  RVNet.on("ended", d => { backToLobby(); toast((d && d.why ? d.why + " - " : "") + "Match ended - back in the room"); });
  RVNet.on("chat", d => toast(d.name + ": " + d.text));
  // closing the game window during a match: the leader ends it (everybody back in the room,
  // ready for the next game); anyone else leaves it and can create or join another room
  setInterval(() => {
    const open = $("emu-modal") && $("emu-modal").classList.contains("open");
    if (RVNet.match && !open) {
      if (RVNet.isLeader()) { RVNet.match.stop(); RVNet.match = null; RVNet.end(); }
      else { RVNet.leave(); toast("You left the online match"); }
    }
    if (RVStream.hosting && !open) { RVStream.stop(); RVNet.end(); toast("Stream ended"); }
  }, 1000);
})();
