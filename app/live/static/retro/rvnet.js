// Retro Vault online play - client side of the netplay server (G:\RetroNetplay\server).
//
// RVNet: login (Discord popup or guest name), rooms, slots, game choice, ROM check.
// Match: deterministic lockstep. The emulator runs on lockstep.js's virtual clock
// (LS.stepAsync runs exactly one frame). Local controller/keyboard input is caught at
// gameManager.simulateInput and SENT, not applied; a frame only runs when the server's
// bundle (every player's input for that frame) has arrived, so all PCs run the same
// frames with the same input. A state hash every sumEvery frames lets the server spot
// a desync; the leader's state is then loaded by everybody (auto-resync).
(function () {
  "use strict";
  const NINPUT = 24;
  const DEFAULT_SERVER = "https://netvault.tail1801f7.ts.net:8443/netplay";
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) { /* ignore */ } }
  };

  function b64(u8) {
    let s = "";
    for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    return btoa(s);
  }
  function unb64(s) {
    const bin = atob(s), u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return u8;
  }
  function fnv(u8) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < u8.length; i++) { h ^= u8[i]; h = Math.imul(h, 16777619) >>> 0; }
    return h.toString(16);
  }
  async function sha1(buf) {
    const d = await crypto.subtle.digest("SHA-1", buf);
    return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, "0")).join("");
  }
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  // ── one match: the lockstep loop ─────────────────────────────────────────────
  class Match {
    constructor(net, emuWin, go) {
      this.net = net; this.win = emuWin;
      this.gm = emuWin.EJS_emulator.gameManager;
      this.LS = emuWin.LS;
      this.slot = net.mySlot();
      this.delay = go.delay; this.sumEvery = go.sumEvery || 120;
      this.bundles = new Map(); this.wake = null;
      this.resyncAt = null; this.rload = null;
      this.running = true; this.frame = 0;
      this.stats = { stalls: 0, resyncs: 0, fps: 0 };
      this.lastApplied = Array.from({ length: 4 }, () => new Array(NINPUT).fill(0));
      // local input: whatever EmulatorJS would have applied for player 1 is ours to send
      this.local = new Array(NINPUT).fill(0);
      const apply = this.gm.functions.simulateInput;
      this.apply = (p, i, v) => apply(p, i, v);
      this.origSim = this.gm.simulateInput;
      this.gm.simulateInput = (p, i, v) => { if (p === 0 && i >= 0 && i < NINPUT) this.local[i] = v | 0; };
      // the start state: everybody (leader too) loads it before frame 0
      this.gm.loadState(unb64(go.data));
      for (let s = 0; s < 4; s++) for (let i = 0; i < NINPUT; i++) this.apply(s, i, 0);
    }
    onBundle(f, inputs) { this.bundles.set(f, inputs); if (this.wake) { const w = this.wake; this.wake = null; w(); } }
    onResync(at) { this.resyncAt = at; this.stats.resyncs++; if (this.wake) { const w = this.wake; this.wake = null; w(); } }
    onRload(at, data) { this.rload = { at, data }; if (this.wake) { const w = this.wake; this.wake = null; w(); } }
    stop() {
      this.running = false;
      this.gm.simulateInput = this.origSim;
      if (this.wake) this.wake();
      this.LS.auto = true;           // back to normal timing (the emulator keeps running locally)
    }
    waitEvent(ms) { return new Promise(r => { this.wake = r; setTimeout(r, ms); }); }
    async run() {
      const net = this.net, LS = this.LS;
      let t0 = LS.realNow(), framesAt = 0, fpsT = t0;
      while (this.running) {
        const f = this.frame;
        // resync: stop before frame `at`; the leader sends its state, everybody loads it
        if (this.resyncAt !== null && f >= this.resyncAt) {
          if (net.isLeader() && !this._rsent) { this._rsent = true; net.send({ t: "rstate", data: b64(this.gm.getState()) }); }
          while (this.running && !this.rload) await this.waitEvent(250);
          if (!this.running) break;
          this.gm.loadState(unb64(this.rload.data));
          this.rload = null; this.resyncAt = null; this._rsent = false;
          net.emit("resynced", { frame: f });
        }
        // our input for frame f+delay
        net.send({ t: "in", f: f + this.delay, v: this.local.slice() });
        // wait for everybody's input for frame f
        let waited = false;
        while (this.running && !this.bundles.has(f) && this.resyncAt === null) { waited = true; await this.waitEvent(500); }
        if (!this.running) break;
        if (!this.bundles.has(f)) continue;            // a resync came in while waiting
        if (waited) this.stats.stalls++;
        const inputs = this.bundles.get(f); this.bundles.delete(f);
        for (let s = 0; s < 4; s++) {
          const row = inputs[s] || [], last = this.lastApplied[s];
          for (let i = 0; i < NINPUT; i++) { const v = row[i] | 0; if (v !== last[i]) { this.apply(s, i, v); last[i] = v; } }
        }
        const moved = await LS.stepAsync();
        if (moved !== 1) net.emit("warn", { frame: f, moved });
        this.frame = f + 1;
        if (this.frame % this.sumEvery === 0) net.send({ t: "sum", f: this.frame, h: fnv(this.gm.getState()) });
        // keep to real time: 60 frames a second, catching up quickly after a stall
        t0 += 1000 / 60;
        const ahead = t0 - LS.realNow();
        if (ahead > 1) await sleep(ahead); else if (ahead < -250) t0 = LS.realNow();
        if (this.frame - framesAt >= 60) {
          const now = LS.realNow(); this.stats.fps = Math.round((this.frame - framesAt) * 1000 / (now - fpsT));
          framesAt = this.frame; fpsT = now; net.emit("stats", Object.assign({ frame: this.frame }, this.stats));
        }
      }
    }
  }

  // ── the connection + lobby ───────────────────────────────────────────────────
  const RVNet = window.RVNet = {
    server: store.get("rvnet_server") || DEFAULT_SERVER,
    token: store.get("rvnet_token"), name: store.get("rvnet_name"),
    ws: null, me: null, room: null, match: null, go: null, emuWin: null, handlers: {},

    on(t, fn) { (this.handlers[t] = this.handlers[t] || []).push(fn); },
    emit(t, d) { (this.handlers[t] || []).forEach(fn => { try { fn(d); } catch (e) { console.error("[RVNet]", e); } }); },
    send(o) { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(o)); },
    isLeader() { return !!(this.room && this.me && this.room.leader === this.me.uid); },
    mySlot() { const p = this.room && this.me && this.room.players.find(x => x.uid === this.me.uid); return p ? p.slot : 0; },
    setServer(url) { this.server = url.replace(/\/$/, ""); store.set("rvnet_server", this.server); },

    login() {
      const w = window.open(this.server + "/login?origin=" + encodeURIComponent(location.origin), "rvnet_login", "popup,width=520,height=760");
      return new Promise((resolve, reject) => {
        const onMsg = e => {
          if (!e.data || e.data.type !== "rvnet_token") return;
          window.removeEventListener("message", onMsg);
          this.token = e.data.token; this.name = e.data.name;
          store.set("rvnet_token", this.token); store.set("rvnet_name", this.name);
          resolve(this.name);
        };
        window.addEventListener("message", onMsg);
        const t = setInterval(() => { if (w && w.closed) { clearInterval(t); setTimeout(() => reject(new Error("Login window closed")), 500); } }, 800);
      });
    },
    logout() { this.token = this.name = null; store.set("rvnet_token", null); store.set("rvnet_name", null); this.disconnect(); },

    connect(guest) {
      this.disconnect();
      const q = this.token && !guest ? "token=" + encodeURIComponent(this.token) : "guest=" + encodeURIComponent(guest || "Player");
      const url = this.server.replace(/^http/, "ws") + "/ws?" + q;
      return new Promise((resolve, reject) => {
        const ws = this.ws = new WebSocket(url);
        let ok = false;
        ws.onmessage = e => {
          let d; try { d = JSON.parse(e.data); } catch (x) { return; }
          if (d.t === "me") { ok = true; this.me = d; resolve(d); }
          this._handle(d);
        };
        ws.onclose = () => { if (!ok) reject(new Error("Couldn't reach the netplay server")); this._closed(); };
        ws.onerror = () => {};
      });
    },
    disconnect() { if (this.ws) { try { this.ws.close(); } catch (e) { /* ignore */ } } this._closed(); },
    _closed() {
      if (this.match) { this.match.stop(); this.match = null; }
      const was = !!this.room;
      this.ws = null; this.room = null; this.go = null;
      if (was) this.emit("closed");
    },

    create() { this.send({ t: "create" }); },
    join(code) { this.send({ t: "join", code }); },
    leave() { this.send({ t: "leave" }); this.disconnect(); },
    setSlot(uid, slot) { this.send({ t: "slot", uid, slot }); },
    setDelay(n) { this.send({ t: "delay", n }); },
    setMode(mode) { this.send({ t: "mode", mode }); },
    kick(uid) { this.send({ t: "kick", uid }); },
    start() { this.send({ t: "start" }); },
    end() { this.send({ t: "end" }); },
    chat(text) { this.send({ t: "chat", text }); },
    async pickGame(game, romBytes) {         // leader: game = {system,title,file,core}
      this.send({ t: "game", game: Object.assign({}, game, { sha1: await sha1(romBytes) }) });
    },
    async checkRom(romBytes) { this.send({ t: "rom", sha1: romBytes ? await sha1(romBytes) : "" }); },
    sha1,

    // the page calls this once the emulator (booted with lockstep.js) has started
    async emulatorReady(win) {
      this.emuWin = win;
      if (this.mode === "stream") {                    // stream mode: only the host runs the game
        if (this.isLeader() && window.RVStream) {
          while (!win.EJS_emulator.gameManager.getFrameNum || win.EJS_emulator.gameManager.getFrameNum() < 2) await sleep(50);
          window.RVStream.host(win);
          this.emit("playing", { mode: "stream" });
        }
        return;
      }
      if (this.isLeader() && this.starting) {        // ("starting" arrives before the room update)
        this.starting = false;
        const gm = win.EJS_emulator.gameManager;
        while (gm.getFrameNum() < 60) await sleep(50);          // past the core's first frames
        win.LS.auto = false; await sleep(150);
        this.send({ t: "state", data: b64(gm.getState()) });
      }
      this._maybeStart();
    },
    _maybeStart() {
      if (!this.go || !this.emuWin || this.match) return;
      this.emuWin.LS.auto = false;
      this.match = new Match(this, this.emuWin, this.go);
      if (this.early) { this.early.forEach((v, f) => this.match.onBundle(f, v)); this.early = null; }
      this.emit("playing", this.go);
      this.match.run().catch(e => { console.error("[RVNet] match", e); this.emit("warn", { error: String(e) }); });
    },

    _handle(d) {
      switch (d.t) {
        case "room": this.room = d; break;
        case "starting": this.go = null; this.early = null; this.mode = d.mode || "lockstep"; this.starting = this.mode === "lockstep"; break;
        case "go": this.go = d; this._maybeStart(); break;
        case "f":            // bundles can arrive before this PC's emulator has finished booting
          if (this.match) this.match.onBundle(d.f, d.i); else (this.early = this.early || new Map()).set(d.f, d.i);
          break;
        case "resync": if (this.match) this.match.onResync(d.at); break;
        case "rload": if (this.match) this.match.onRload(d.at, d.data); break;
        case "ended": if (this.match) { this.match.stop(); this.match = null; } this.go = null; break;
        case "kicked": this.disconnect(); break;
      }
      this.emit(d.t, d);
    }
  };
})();
