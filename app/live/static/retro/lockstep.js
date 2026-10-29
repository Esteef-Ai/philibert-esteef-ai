// Lockstep frame control for EmulatorJS - loaded BEFORE loader.js.
// 1. Virtual clock: performance.now() only moves when we run a frame (+1/60 s), so
//    RetroArch's frame limiter always sees a perfectly timed frame - real timing never
//    decides whether a frame runs.
// 2. The emulator's frame callback (requestAnimationFrame) is queued; LS.step() runs
//    exactly one emulated frame. LS.auto=true lets a 60 Hz timer drive it (normal play).
(function () {
  const realNow = performance.now.bind(performance);
  const realRaf = window.requestAnimationFrame.bind(window);
  let vt = realNow();
  const LS = window.LS = { q: [], auto: true, steps: 0, realNow };
  performance.now = () => vt;
  window.requestAnimationFrame = cb => { LS.q.push(cb); return LS.q.length; };
  const flush = () => { const q = LS.q; LS.q = []; for (const cb of q) cb(vt); return q.length; };
  const frameNum = () => { try { return window.EJS_emulator.gameManager.getFrameNum(); } catch (e) { return -1; } };
  // One emulated frame. The clock moves ONCE (20 ms: always past the limiter's 16.67 ms
  // threshold - 1/60 s isn't exact in floating point - and never far enough for two), then
  // frame callbacks are handed over until the frame has run. Not every callback runs a
  // frame, but a second frame can't happen because the clock didn't move again.
  LS.step = function () {
    const f = frameNum();
    vt += 20;
    let n = 0;
    for (let i = 0; i < 12; i++) {
      n += flush();
      if (f < 0 || frameNum() !== f) break;
    }
    LS.steps++;
    return frameNum() - f;          // 1 = one frame ran
  };
  // The reliable form: move the clock once, then keep handing over callbacks AND yielding
  // to the page until that one frame has run (synchronous steps only land every other time).
  LS.stepAsync = async function (timeoutMs = 2000) {
    const f = frameNum();
    vt += 20;
    const t0 = realNow();
    while (frameNum() === f && realNow() - t0 < timeoutMs) {
      flush();
      await new Promise(r => setTimeout(r, 0));
    }
    LS.steps++;
    return frameNum() - f;
  };
  (function pump() {                     // auto mode: one frame per real display frame
    if (LS.auto) LS.step();
    realRaf(pump);
  })();
})();
