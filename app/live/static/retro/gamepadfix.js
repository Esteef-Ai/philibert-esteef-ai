// Controllers in the emulator frame. Loaded BEFORE EmulatorJS. A pad can be seen by Retro Vault's
// page and not by this frame, so the frame reads whichever of the two sees the most pads.
// EmulatorJS also has two bugs that leave a controller shown by the browser but dead in the game:
//  - it looks a pad up by its browser slot in its own list, so a pad in slot 1 with slot 0 empty
//    (a new pad when another one was paired first) throws on every button press;
//  - a pad the frame can already see when EmulatorJS starts fires "connected" before anything
//    listens, so it is never given to a player.
(function () {
  if (!navigator.getGamepads) return;
  const real = navigator.getGamepads.bind(navigator);
  const others = [window.parent, window.top].filter((w, i, all) => w !== window && all.indexOf(w) === i);
  const list = get => {
    try { return Array.from(get()).filter(g => g && g.connected !== false); }
    catch (e) { return []; }      // never break the game over a controller
  };
  // No empty slots: the pads are numbered 0, 1, 2... as EmulatorJS expects
  navigator.getGamepads = function () {
    const out = [];
    let pads = list(real);
    for (const w of others) {
      const seen = list(() => w.navigator.getGamepads());
      if (seen.length > pads.length) pads = seen;
    }
    for (const g of pads) {
      // the Discord talk button belongs to Discord: the game doesn't see it
      let talk = -1;
      try { talk = window.parent.RVPads.pttButton(g); } catch (e) { /* not set up */ }
      const buttons = talk < 0 ? g.buttons : Array.prototype.map.call(g.buttons, (b, i) => (i === talk ? { pressed: false, touched: false, value: 0 } : b));
      out.push({ id: g.id, index: out.length, mapping: g.mapping, connected: true,
                 timestamp: g.timestamp, axes: g.axes, buttons });
    }
    return out;
  };
  // Give every pad to the next free player, once: "Not Connected" in the emulator's menu sticks
  const seen = new Set();
  window.RVPadAssign = function () {
    const em = window.EJS_emulator;
    if (!em || !em.gamepad || !em.gamepadSelection) return;
    let changed = false;
    em.gamepad.gamepads.forEach(g => {
      if (!g) return;
      const key = g.id + "_" + g.index;
      if (seen.has(key)) return;
      seen.add(key);
      if (em.gamepadSelection.includes(key)) return;
      const free = em.gamepadSelection.indexOf("");
      if (free >= 0) { em.gamepadSelection[free] = key; changed = true; }
    });
    if (changed) em.updateGamepadLabels();
  };
  setInterval(window.RVPadAssign, 500);
  // A side mouse button (held by hand or sent for Discord) over the game must not go Back or Forward
  ["mousedown", "mouseup", "auxclick"].forEach(t => window.addEventListener(t, e => {
    if (e.button === 1 || e.button === 3 || e.button === 4) e.preventDefault();
  }, true));
})();
