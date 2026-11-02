// Controllers in the emulator frame. Loaded BEFORE EmulatorJS, which has two bugs that leave a
// controller shown by the browser but dead in the game:
//  - it looks a pad up by its browser slot in its own list, so a pad in slot 1 with slot 0 empty
//    (a new pad when another one was paired first) throws on every button press;
//  - a pad the frame can already see when EmulatorJS starts fires "connected" before anything
//    listens, so it is never given to a player.
(function () {
  if (!navigator.getGamepads) return;
  const real = navigator.getGamepads.bind(navigator);
  // No empty slots: the pads are numbered 0, 1, 2... as EmulatorJS expects
  navigator.getGamepads = function () {
    const out = [];
    for (const g of real()) {
      if (!g || g.connected === false) continue;
      out.push({ id: g.id, index: out.length, mapping: g.mapping, connected: true,
                 timestamp: g.timestamp, axes: g.axes, buttons: g.buttons });
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
})();
