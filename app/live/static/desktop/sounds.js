/* Desktop sounds, synthesised on the spot with Web Audio: original tones in the
 * spirit of each era (a warm startup chord, a ding, soft clicks), so no recorded
 * sound - and nothing of Microsoft's or Apple's - ships on the drive.
 *
 *   PhilSounds.play("startup" | "ding" | "open" | "close" | "minimize" | "error" | "shutdown")
 *   PhilSounds.enabled = false   mutes them all
 */
(function () {
  "use strict";
  var ctx = null;
  function ac() {
    if (!ctx) {
      var C = window.AudioContext || window.webkitAudioContext;
      if (!C) return null;
      ctx = new C();
    }
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  // one voice: oscillator -> gentle low-pass -> envelope -> master
  function tone(a, t0, freq, dur, opts) {
    opts = opts || {};
    var o = a.createOscillator(), g = a.createGain(), f = a.createBiquadFilter();
    o.type = opts.type || "triangle";
    o.frequency.setValueAtTime(freq, t0);
    if (opts.slide) o.frequency.exponentialRampToValueAtTime(opts.slide, t0 + dur);
    if (opts.detune) o.detune.value = opts.detune;
    f.type = "lowpass";
    f.frequency.value = opts.cut || 2400;
    var peak = opts.vol == null ? 0.18 : opts.vol, att = opts.att || 0.01;
    g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(peak, t0 + att);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    o.connect(f); f.connect(g); g.connect(master(a));
    o.start(t0); o.stop(t0 + dur + 0.05);
  }
  var out = null;
  function master(a) {
    if (!out) {
      out = a.createGain();
      out.gain.value = 0.55;
      // a short, soft echo gives the 90s "big room" feel without a sample
      var d = a.createDelay(), fb = a.createGain(), wet = a.createGain();
      d.delayTime.value = 0.19; fb.gain.value = 0.28; wet.gain.value = 0.22;
      out.connect(a.destination);
      out.connect(d); d.connect(fb); fb.connect(d); d.connect(wet); wet.connect(a.destination);
    }
    return out;
  }

  var SOUNDS = {
    // a slow major-ninth swell with a rising sparkle: "the machine is awake"
    startup: function (a, t) {
      [[130.81, 0], [196.0, 0.05], [261.63, 0.1], [329.63, 0.18], [392.0, 0.26], [587.33, 0.34]].forEach(function (n) {
        tone(a, t + n[1], n[0], 3.2 - n[1], { type: "sine", vol: 0.12, att: 0.6, cut: 1800 });
        tone(a, t + n[1], n[0] * 2, 2.6 - n[1], { type: "triangle", vol: 0.035, att: 0.5, detune: 6 });
      });
      [783.99, 987.77, 1174.66, 1567.98].forEach(function (f, i) {
        tone(a, t + 0.9 + i * 0.16, f, 1.3, { type: "sine", vol: 0.05, att: 0.02, cut: 4000 });
      });
    },
    // 3.11: a quick bright arpeggio and a held chord
    startup_win311: function (a, t) {
      [523.25, 659.25, 783.99, 1046.5].forEach(function (f, i) {
        tone(a, t + i * 0.09, f, 0.5, { type: "square", vol: 0.05, cut: 1800 });
      });
      [523.25, 659.25, 783.99].forEach(function (f) { tone(a, t + 0.4, f, 1.1, { type: "triangle", vol: 0.08 }); });
    },
    // XP: a soft, wide pad that blooms upward
    startup_xp: function (a, t) {
      [[220, 0], [277.18, 0.25], [329.63, 0.5], [440, 0.75], [554.37, 1.0], [659.25, 1.2]].forEach(function (n) {
        tone(a, t + n[1], n[0], 3.0 - n[1] * 0.5, { type: "sine", vol: 0.09, att: 0.4, cut: 2200 });
        tone(a, t + n[1], n[0] * 1.5, 2.2, { type: "triangle", vol: 0.025, att: 0.6, detune: -8 });
      });
    },
    // the Mac family: one big, round major chord - our own, not Apple's
    startup_mac: function (a, t) {
      [130.81, 196.0, 261.63, 329.63, 392.0, 523.25].forEach(function (f, i) {
        tone(a, t, f, 2.6, { type: i % 2 ? "triangle" : "sine", vol: 0.1, att: 0.005, cut: 2600 });
      });
    },
    // 11: a soft, airy four-note rise
    startup_win11: function (a, t) {
      [[392.0, 0], [523.25, 0.12], [659.25, 0.24], [783.99, 0.36]].forEach(function (n) {
        tone(a, t + n[1], n[0], 1.8, { type: "sine", vol: 0.09, att: 0.08, cut: 3000 });
      });
    },
    // phones: a short bright chime
    startup_phone: function (a, t) {
      tone(a, t, 1046.5, 0.5, { type: "sine", vol: 0.12 });
      tone(a, t + 0.1, 1567.98, 0.7, { type: "sine", vol: 0.09 });
    },
    // the 64: a quick chip-tune arpeggio, square waves like its sound chip
    startup_c64: function (a, t) {
      [261.63, 329.63, 392.0, 523.25, 392.0, 523.25, 659.25, 1046.5].forEach(function (f, i) {
        tone(a, t + i * 0.07, f, 0.12, { type: "square", vol: 0.05, cut: 3500 });
      });
    },
    ding: function (a, t) {
      tone(a, t, 1318.5, 0.6, { type: "sine", vol: 0.16 });
      tone(a, t + 0.09, 1975.5, 0.7, { type: "sine", vol: 0.1 });
    },
    open: function (a, t) { tone(a, t, 520, 0.12, { type: "triangle", vol: 0.1, slide: 780 }); },
    close: function (a, t) { tone(a, t, 700, 0.12, { type: "triangle", vol: 0.09, slide: 420 }); },
    minimize: function (a, t) { tone(a, t, 640, 0.18, { type: "sine", vol: 0.08, slide: 260 }); },
    error: function (a, t) {
      tone(a, t, 220, 0.25, { type: "square", vol: 0.07, cut: 900 });
      tone(a, t + 0.12, 164.8, 0.3, { type: "square", vol: 0.07, cut: 900 });
    },
    // the startup chord in reverse, settling down
    shutdown: function (a, t) {
      [[587.33, 0], [392.0, 0.18], [329.63, 0.34], [261.63, 0.5], [196.0, 0.66]].forEach(function (n) {
        tone(a, t + n[1], n[0], 1.6, { type: "sine", vol: 0.1, att: 0.05, cut: 1600 });
      });
    },
  };

  window.PhilSounds = {
    enabled: true,
    play: function (name) {
      if (!this.enabled || !SOUNDS[name]) return;
      try {
        var a = ac();
        if (a) SOUNDS[name](a, a.currentTime + 0.02);
      } catch (e) { /* no audio device: stay quiet */ }
    },
  };
})();
