// Retro Vault online play - STREAM mode (N64 first): the room's host runs the game,
// everybody else watches a live WebRTC video of it and sends their controller input
// back over a data channel. No desync is possible - there is only one game.
// Signaling (offer/answer/ICE) goes through the netplay server ({t:"sig"}).
// Ports: the host is controller 1; the others get 2, 3, 4 in the order of their room slots.
(function () {
  "use strict";
  const NINPUT = 24;
  // STUN finds a direct route; the server also gives a 12-hour password for the home TURN
  // relay, which carries the stream when two networks can't connect directly
  const STUN = [{ urls: ["stun:stun.cloudflare.com:3478", "stun:stun.l.google.com:19302"] }];
  const iceServers = () => (window.RVNet && RVNet.me && RVNet.me.ice) || STUN;
  const DEAD = 0.18;

  // ── controller -> RetroPad indexes (EmulatorJS simulateInput) ──────────────────
  // standard Gamepad mapping (Xbox layout): A/B/X/Y = bottom/right/left/top
  const PAD = { 0: 0, 1: 8, 2: 1, 3: 9, 4: 10, 5: 11, 6: 12, 7: 13, 8: 2, 9: 3, 12: 4, 13: 5, 14: 6, 15: 7 };
  // keyboard: arrows = analog stick, Z/X = A/B, Enter = Start, A = Z trigger, Q/W = L/R,
  // I/J/K/L = C buttons, T/F/G/H = D-pad
  const KEYS = { KeyZ: 0, KeyX: 1, Enter: 3, KeyA: 12, KeyQ: 10, KeyW: 11, KeyT: 4, KeyG: 5, KeyF: 6, KeyH: 7 };
  const KSTICK = { ArrowRight: 16, ArrowLeft: 17, ArrowDown: 18, ArrowUp: 19, KeyL: 20, KeyJ: 21, KeyK: 22, KeyI: 23 };
  const keys = new Set();
  function axis(v, plus, minus, out) {
    if (Math.abs(v) < DEAD) return;
    if (v > 0) out[plus] = Math.round(32767 * v); else out[minus] = Math.round(-32767 * v);
  }
  function readInput() {
    const v = new Array(NINPUT).fill(0);
    for (const gp of (navigator.getGamepads ? navigator.getGamepads() : [])) {
      if (!gp) continue;
      gp.buttons.forEach((b, i) => { if (PAD[i] !== undefined && (b.pressed || b.value > 0.5)) v[PAD[i]] = 1; });
      axis(gp.axes[0] || 0, 16, 17, v); axis(gp.axes[1] || 0, 18, 19, v);
      axis(gp.axes[2] || 0, 20, 21, v); axis(gp.axes[3] || 0, 22, 23, v);
      break;                                    // the first pad only
    }
    keys.forEach(k => { if (KEYS[k] !== undefined) v[KEYS[k]] = 1; if (KSTICK[k] !== undefined) v[KSTICK[k]] = 32767; });
    return v;
  }
  addEventListener("keydown", e => { if (RVStream.viewing) { keys.add(e.code); if (KEYS[e.code] !== undefined || KSTICK[e.code] !== undefined) e.preventDefault(); } });
  addEventListener("keyup", e => keys.delete(e.code));
  addEventListener("blur", () => keys.clear());

  function preferH264(pc) {
    try {
      const caps = RTCRtpReceiver.getCapabilities("video");
      if (!caps) return;
      const h264 = caps.codecs.filter(c => /h264/i.test(c.mimeType));
      const rest = caps.codecs.filter(c => !/h264/i.test(c.mimeType));
      pc.getTransceivers().forEach(t => { if (t.receiver.track && t.receiver.track.kind === "video" && t.setCodecPreferences && h264.length) t.setCodecPreferences(h264.concat(rest)); });
    } catch (e) { /* the browser picks */ }
  }

  const RVStream = window.RVStream = {
    peers: new Map(), viewing: false, hosting: false,

    // ── host ──────────────────────────────────────────────────────────────────
    async host(emuWin) {
      this.stop();
      this.hosting = true;
      this.win = emuWin;
      const gm = emuWin.EJS_emulator.gameManager;
      this.apply = gm.functions.simulateInput;
      const canvas = emuWin.document.querySelector("#game canvas") || emuWin.document.querySelector("canvas");
      const media = new MediaStream();
      canvas.captureStream(60).getVideoTracks().forEach(t => media.addTrack(t));
      const audio = emuWin.RVTap && emuWin.RVTap.stream();
      if (audio) audio.getAudioTracks().forEach(t => media.addTrack(t));
      this.media = media;
      const room = RVNet.room;
      const guests = room.players.filter(p => p.connected && p.uid !== RVNet.me.uid).sort((a, b) => a.slot - b.slot);
      guests.forEach((p, k) => this._hostPeer(p, k + 1));
      RVNet.emit("streamstats", { role: "host", viewers: guests.length });
    },
    async _hostPeer(player, port) {
      const pc = new RTCPeerConnection({ iceServers: iceServers(), iceTransportPolicy: RVStream.relayOnly ? "relay" : "all" });
      const peer = { pc, port, uid: player.uid, name: player.name, last: new Array(NINPUT).fill(0), inputs: 0 };
      this.peers.set(player.uid, peer);
      this.media.getTracks().forEach(t => pc.addTrack(t, this.media));
      preferH264(pc);
      const dc = pc.createDataChannel("input", { ordered: false, maxRetransmits: 0 });
      dc.onmessage = e => {
        let m; try { m = JSON.parse(e.data); } catch (x) { return; }
        if (m.v) {
          for (let i = 0; i < NINPUT; i++) { const v = m.v[i] | 0; if (v !== peer.last[i]) { this.apply(port, i, v); peer.last[i] = v; } }
          peer.inputs++;
        } else if (m.ping) dc.send(JSON.stringify({ pong: m.ping }));
      };
      pc.onicecandidate = e => { if (e.candidate) RVNet.send({ t: "sig", to: player.uid, data: { ice: e.candidate } }); };
      pc.onconnectionstatechange = () => {
        RVNet.emit("streampeer", { uid: player.uid, name: player.name, state: pc.connectionState, port });
        if (pc.connectionState === "connected") this._bitrate(pc);
        if (pc.connectionState === "failed" || pc.connectionState === "closed")   // let go of their buttons
          for (let i = 0; i < NINPUT; i++) if (peer.last[i]) { this.apply(port, i, 0); peer.last[i] = 0; }
      };
      await pc.setLocalDescription(await pc.createOffer());
      RVNet.send({ t: "sig", to: player.uid, data: { sdp: pc.localDescription, port } });
    },
    async _bitrate(pc) {
      for (const s of pc.getSenders()) {
        if (!s.track || s.track.kind !== "video") continue;
        const p = s.getParameters(); p.encodings = p.encodings && p.encodings.length ? p.encodings : [{}];
        p.encodings[0].maxBitrate = 6000000; p.encodings[0].maxFramerate = 60;
        p.degradationPreference = "maintain-framerate";
        try { await s.setParameters(p); } catch (e) { /* keep defaults */ }
      }
    },

    // ── viewer ────────────────────────────────────────────────────────────────
    view(hostUid) {
      this.stop();
      this.viewing = true; this.hostUid = hostUid;
      const ov = this.overlay = document.createElement("div");
      ov.id = "rv-stream";
      ov.style.cssText = "position:fixed;inset:0;z-index:99990;background:#000;display:flex;align-items:center;justify-content:center";
      ov.innerHTML = `<video id="rv-stream-video" autoplay playsinline style="width:100%;height:100%;object-fit:contain;image-rendering:pixelated"></video>
        <div id="rv-stream-bar" style="position:absolute;left:10px;top:10px;color:#ddd;font:13px system-ui;background:rgba(0,0,0,.6);padding:6px 10px;border-radius:8px">Connecting to the host…</div>
        <div style="position:absolute;right:10px;top:10px;display:flex;gap:6px">
          <button id="rv-stream-full" class="btn-ghost">Full screen</button><button id="rv-stream-leave" class="btn-ghost">Leave</button></div>
        <div style="position:absolute;left:10px;bottom:10px;color:#999;font:12px system-ui;background:rgba(0,0,0,.55);padding:5px 9px;border-radius:8px">
          Controller works as-is · keyboard: arrows = stick, Z/X = A/B, A = Z, Q/W = L/R, Enter = Start, I/J/K/L = C buttons</div>`;
      document.body.appendChild(ov);
      ov.querySelector("#rv-stream-leave").onclick = () => RVNet.leave();
      ov.querySelector("#rv-stream-full").onclick = () => (ov.requestFullscreen ? ov.requestFullscreen() : null);
    },
    async _onOffer(from, data) {
      const pc = new RTCPeerConnection({ iceServers: iceServers(), iceTransportPolicy: RVStream.relayOnly ? "relay" : "all" });
      const peer = { pc, port: data.port, uid: from, dc: null };
      this.peers.set(from, peer);
      const video = document.getElementById("rv-stream-video"), bar = document.getElementById("rv-stream-bar");
      pc.ontrack = e => {
        try { e.receiver.playoutDelayHint = 0; e.receiver.jitterBufferTarget = 0; } catch (x) { /* older browsers */ }
        if (video && video.srcObject !== e.streams[0]) { video.srcObject = e.streams[0]; video.play().catch(() => {}); }
      };
      pc.onicecandidate = e => { if (e.candidate) RVNet.send({ t: "sig", to: from, data: { ice: e.candidate } }); };
      pc.onconnectionstatechange = () => {
        if (bar) bar.textContent = pc.connectionState === "connected" ? "Connected · you are P" + (data.port + 1)
          : pc.connectionState === "failed" ? "Couldn't connect to the host (network blocks a direct link)" : "Connecting… (" + pc.connectionState + ")";
        RVNet.emit("streampeer", { uid: from, state: pc.connectionState, port: data.port });
      };
      pc.ondatachannel = e => {
        const dc = peer.dc = e.channel;
        let last = "", lastSent = 0, rtt = null;
        dc.onmessage = m => { try { const d = JSON.parse(m.data); if (d.pong) rtt = Math.round(performance.now() - d.pong); } catch (x) { /* ignore */ } };
        const tick = () => {
          if (!this.viewing || dc.readyState === "closed") return;
          if (dc.readyState === "open") {
            const v = readInput(), s = v.join(","), now = performance.now();
            if (s !== last || now - lastSent > 100) { dc.send(JSON.stringify({ v })); last = s; lastSent = now; }   // changes at once, and a refresh every 100 ms (the channel may drop a packet)
          }
          setTimeout(tick, 8);
        };
        tick();
        peer.ping = setInterval(() => {
          if (dc.readyState === "open") dc.send(JSON.stringify({ ping: performance.now() }));
          if (bar && pc.connectionState === "connected") bar.textContent = "Connected · you are P" + (data.port + 1) + (rtt !== null ? " · " + rtt + " ms" : "");
          RVNet.emit("streamstats", { role: "viewer", rtt, port: data.port });
        }, 1000);
      };
      await pc.setRemoteDescription(data.sdp);
      await pc.setLocalDescription(await pc.createAnswer());
      RVNet.send({ t: "sig", to: from, data: { sdp: pc.localDescription } });
    },

    // ICE candidates can arrive before the offer/answer they belong to: keep them until
    // that side has its remote description, then add them
    pendingIce: new Map(),
    async _flushIce(uid) {
      const peer = this.peers.get(uid), q = this.pendingIce.get(uid);
      if (!peer || !q || !peer.pc.remoteDescription) return;
      this.pendingIce.delete(uid);
      for (const c of q) { try { await peer.pc.addIceCandidate(c); } catch (e) { /* stale */ } }
    },
    async onSig(d) {
      const data = d.data || {};
      if (data.np) return;                     // the players' direct links (rvnet.js), not the stream
      if (data.sdp && data.sdp.type === "offer") {
        if (this.viewing) { await this._onOffer(d.from, data); await this._flushIce(d.from); }
        return;
      }
      if (data.ice) {
        (this.pendingIce.get(d.from) || this.pendingIce.set(d.from, []).get(d.from)).push(data.ice);
        return this._flushIce(d.from);
      }
      const peer = this.peers.get(d.from);
      if (peer && data.sdp) { await peer.pc.setRemoteDescription(data.sdp); await this._flushIce(d.from); }
    },

    stop() {
      this.peers.forEach(p => { clearInterval(p.ping); try { p.pc.close(); } catch (e) { /* ignore */ } });
      this.peers.clear(); this.pendingIce.clear();
      if (this.overlay) { this.overlay.remove(); this.overlay = null; }
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
      this.viewing = this.hosting = false; keys.clear();
    }
  };

  if (window.RVNet) {
    RVNet.on("sig", d => RVStream.onSig(d).catch(e => console.error("[RVStream]", e)));
    RVNet.on("ended", () => RVStream.stop());
    RVNet.on("closed", () => RVStream.stop());
  }
})();
