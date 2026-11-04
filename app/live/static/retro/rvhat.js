// Controllers whose D-pad is a "hat": one single axis holding all eight directions (many DirectInput
// pads, like N64-style USB ones). The browser reports it as one axis that rests outside -1..1, so the
// D-pad looked like one button and the game saw it held. Loaded first, in the page and in the emulator
// frame, so everything that reads a controller sees the D-pad as four ordinary buttons.
(function () {
  if (!navigator.getGamepads || window.RVHat) return;
  const real = navigator.getGamepads.bind(navigator);
  let known = {};                        // pad id -> { axis, base (the button number of D-pad up) }
  try { if (window.parent !== window && window.parent.RVHat) known = window.parent.RVHat.known; } catch (e) { /* another site's page */ }
  const button = on => ({ pressed: on, touched: on, value: on ? 1 : 0 });
  // up, down, left, right for the eight positions, clockwise from up
  const DIRS = [[1, 0, 0, 0], [1, 0, 0, 1], [0, 0, 0, 1], [0, 1, 0, 1], [0, 1, 0, 0], [0, 1, 1, 0], [0, 0, 1, 0], [1, 0, 1, 0]];
  function fix(g) {
    if (!g || g.rvHat || g.mapping === "standard") return g;
    let h = known[g.id];
    if (!h) {
      const axis = Array.from(g.axes).findIndex(v => Math.abs(v) > 1.01);      // only a hat at rest does this
      if (axis < 0) return g;
      // The usual D-pad numbers (12-15) when free, so the default mappings just work.
      // A pad already using them keeps its buttons: its D-pad goes after them.
      const n = g.buttons.length;
      h = known[g.id] = { axis, base: n <= 12 ? 12 : Math.max(16, n) };
    }
    const v = g.axes[h.axis], dirs = Math.abs(v) <= 1.01 ? DIRS[Math.round((v + 1) * 3.5)] : null;
    const buttons = Array.from(g.buttons), axes = Array.from(g.axes);
    while (buttons.length < h.base) buttons.push(button(false));
    for (let k = 0; k < 4; k++) buttons[h.base + k] = button(!!(dirs && dirs[k]));
    axes[h.axis] = 0;
    return { id: g.id, index: g.index, mapping: g.mapping, connected: g.connected, timestamp: g.timestamp, axes, buttons, rvHat: true };
  }
  navigator.getGamepads = function () { return Array.from(real()).map(fix); };
  window.RVHat = { fix, known };
})();
