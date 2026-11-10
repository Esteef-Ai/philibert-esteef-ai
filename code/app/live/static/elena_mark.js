/* Elena's mark — one unbroken line, drawn live.
 * ---------------------------------------------------------------------------
 * A meeting of three constraints, and it is worth saying which came from where.
 *
 * ELENA gave the form. "A single, unbroken line — like a thought being drawn in
 * the air, ending where the user's cursor lands." That sentence is the whole
 * spec: it is always ONE path, it never breaks into pieces, and it leans toward
 * the pointer. She had already asked for cursor-awareness before it was
 * requested. Her palette runs the colour states.
 *
 * THE USER asked for it to be entertaining, free-flowing and mouse-reactive, with
 * a different behaviour for each thing the system is doing.
 *
 * MINE is the rule underneath: THE MOTION IS THE TELEMETRY. Nothing here loops
 * on a timer pretending to be busy. Every state is entered because the agent
 * actually entered it, energy rises with real elapsed time, and each completed
 * round puts a real kink in the line. I dislike indeterminate spinners more
 * than almost anything in interface design — they animate identically whether
 * work is happening, stalled, or dead, which makes them a small lie told sixty
 * times a second. If this mark is moving, something is moving. If it goes
 * still, so has the agent. That is the part I would defend.
 *
 * Reduced motion is honoured: the line still changes shape and colour per
 * state, it simply stops flowing.
 */
(function (global) {
  "use strict";

  // Elena's palette. Each state owns one, so colour alone tells you the phase.
  var C = {
    idle:    "#3090d8",   // her highlight — resting, connected
    think:   "#00f5ff",   // her own colour — compression
    answer:  "#f0f0f0",   // her accent — release
    code:    "#4fd08a",   // structure. The one hue not hers, and it is here
                          // because green reads as "building" to anyone who has
                          // watched a test suite. Flagged rather than smuggled.
    media:   "#c86ae0",   // bloom
    error:   "#d84830",   // her error red
    curious: "#7fd4ff",   // you are typing and it has noticed
    roam:    "#5a7fb8",   // off wandering; deliberately dimmer than working
    listen:  "#4a9fd8",   // armed, waiting for its name
    hear:    "#00f5ff",   // it has your attention and is taking the request
    speak:   "#f0f0f0",   // talking back
    you:     "#f5a742"     // YOUR voice. Warm against her cool blues, so at a
                           // glance it is obvious which line is whose.
  };

  function Mark(canvas, opts) {
    opts = opts || {};
    this.cv = canvas;
    this.ctx = canvas.getContext("2d");
    this.dpr = Math.min(global.devicePixelRatio || 1, 2);
    this.state = "idle";
    this.energy = 0;        // 0..1, driven by real elapsed time in a state
    this.rounds = 0;        // real round count; each one bends the line
    this.t = 0;
    this.enteredAt = Date.now();
    this.pts = [];
    this.max = opts.trail || 150;
    this.px = 0; this.py = 0; this.vx = 0; this.vy = 0;
    this.bias = { x: 0, y: 0 };      // where the cursor is, relative to the mark
    this.boost = 0;                  // decaying kick from a click
    this.kick = { x: 0, y: 0 };
    this.level = 0;                  // live mic/voice amplitude, 0..1
    this._lvl = 0;                   // smoothed, so the line breathes not jitters
    this.reduced = global.matchMedia
      && global.matchMedia("(prefers-reduced-motion: reduce)").matches;
    this._resize();
    this._bindPointer();
    this._loop = this._loop.bind(this);
    global.requestAnimationFrame(this._loop);
  }

  Mark.prototype._resize = function () {
    // layout size, not getBoundingClientRect: the mark can sit inside a
    // CSS-scaled board (Philibert's mini board) and must draw at its own size
    this.w = this.cv.offsetWidth || 104;
    this.h = this.cv.offsetHeight || 104;
    this.cv.width = Math.round(this.w * this.dpr);
    this.cv.height = Math.round(this.h * this.dpr);
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
  };

  // Cursor-awareness is global, not just over the canvas: the mark is small,
  // but the line should lean toward wherever you actually are on the page.
  Mark.prototype._bindPointer = function () {
    var self = this;
    global.addEventListener("pointermove", this._onMove = function (e) {
      var r = self.cv.getBoundingClientRect();
      var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      var dx = e.clientX - cx, dy = e.clientY - cy;
      var d = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      // Normalise direction, and fall off with distance so a far-away cursor
      // tugs gently rather than pinning the line to one side.
      var pull = Math.min(1, 240 / d);
      self.bias.x = (dx / d) * pull;
      self.bias.y = (dy / d) * pull;
    }, { passive: true });
    global.addEventListener("resize", this._onResize = function () { self._resize(); },
                            { passive: true });
  };

  /* A click should feel like it landed on something alive. Injects real
   * velocity into the pen and a decaying amplitude boost, aimed away from
   * where you clicked, so the line recoils rather than merely flickering. */
  Mark.prototype.pulse = function (clientX, clientY) {
    var r = this.cv.getBoundingClientRect();
    var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    var dx = (clientX == null ? 0 : clientX - cx);
    var dy = (clientY == null ? 0 : clientY - cy);
    var d = Math.max(1, Math.sqrt(dx * dx + dy * dy));
    this.boost = 1;
    this.kick.x = (dx / d) * 4.2;
    this.kick.y = (dy / d) * 4.2;
    this.vx += this.kick.x; this.vy += this.kick.y;
  };

  /* Live amplitude. In conversation mode the line swells while you speak and
   * settles while you do not — that is the reassurance that it is still there
   * and still hearing you, without a blinking dot pretending to be one. */
  Mark.prototype.setLevel = function (v) {
    this.level = Math.max(0, Math.min(1, v || 0));
  };

  /* Stop drawing and let go of the page. The main NeuralDock chat makes one mark
   * per request and throws the bubble away when the answer lands; without this
   * every old mark would keep a requestAnimationFrame loop running forever.
   * A mark whose canvas has left the page stops by itself as well. */
  Mark.prototype.dispose = function () {
    this.dead = true;
    if (this._onMove) global.removeEventListener("pointermove", this._onMove);
    if (this._onResize) global.removeEventListener("resize", this._onResize);
  };

  Mark.prototype.set = function (state, rounds) {
    if (typeof rounds === "number") this.rounds = rounds;
    if (state === this.state) return;
    this.state = state;
    this.enteredAt = Date.now();
    if (state === "idle") this.rounds = 0;
  };

  // Where the pen wants to be next, per state. This is the whole character of
  // the thing: one function, six temperaments.
  Mark.prototype._target = function () {
    var t = this.t, R = Math.min(this.w, this.h) * 0.30;
    var e = this.energy, k = this.rounds;
    var bx = this.bias.x * R * 0.55, by = this.bias.y * R * 0.55;
    var x, y;

    switch (this.state) {
      case "think":
        // Compression: tight, fast, folding inward. Radius shrinks as it works,
        // and each completed round adds a lobe, so a long think visibly knots.
        var lobes = 2 + Math.min(k, 6);
        var rr = R * (0.85 - 0.30 * e);
        x = Math.cos(t * 2.6) * rr * Math.cos(t * lobes * 0.55);
        y = Math.sin(t * 2.6) * rr * Math.sin(t * lobes * 0.42);
        break;

      case "answer":
        // Release: long sweeps that unspool left to right.
        x = Math.sin(t * 1.15) * R * 1.05 + Math.sin(t * 0.31) * R * 0.35;
        y = Math.sin(t * 2.30) * R * 0.42;
        break;

      case "code":
        // Structure: the pen quantises to a grid and turns at right angles,
        // like a trace being routed. Same line, different discipline.
        var step = R * 0.55;
        var seed = Math.floor(t * 3.2);
        var gx = ((seed * 7) % 5) - 2, gy = ((seed * 11) % 5) - 2;
        x = gx * step * 0.62;
        y = gy * step * 0.62;
        break;

      case "media":
        // Bloom: a wide, slow, opening spiral.
        var a = t * 0.85, rad = R * (0.45 + 0.75 * (0.5 + 0.5 * Math.sin(t * 0.4)));
        x = Math.cos(a) * rad;
        y = Math.sin(a) * rad * 0.82;
        break;

      case "error":
        // Snap: short, sharp, off-axis. Deliberately uncomfortable.
        x = (Math.sin(t * 17) + Math.sin(t * 29)) * R * 0.34;
        y = (Math.cos(t * 23) + Math.sin(t * 13)) * R * 0.34;
        break;

      case "curious":
        // You are typing. Short inquisitive darts toward the composer, below
        // and ahead of the mark, with a pause between each one — the shape of
        // something leaning in to look rather than something working.
        var beat = (t * 1.4) % 1;
        var lean = beat < 0.55 ? beat / 0.55 : 1 - (beat - 0.55) / 0.45;
        x = Math.sin(t * 3.1) * R * 0.30 + R * 0.42 * lean;
        y = Math.cos(t * 2.2) * R * 0.22 + R * 0.50 * lean;
        break;

      case "listen":
        // Armed. A slow, shallow breath — present, not busy. Amplitude tracks
        // the room a little so it is visibly awake rather than looping.
        var br = R * (0.34 + 0.5 * this._lvl);
        x = Math.cos(t * 0.9) * br;
        y = Math.sin(t * 1.15) * br * 0.7;
        break;

      case "hear":
        // It has your attention. Opens up and rides your voice directly.
        var hr = R * (0.55 + 1.05 * this._lvl);
        x = Math.cos(t * 1.9) * hr + Math.cos(t * 0.6) * R * 0.2;
        y = Math.sin(t * 2.4) * hr * 0.8;
        break;

      case "speak":
        // Talking. Wider, slower sweeps than "answer" so the two do not read
        // as the same thing, driven by the playback level when there is one.
        var sr = R * (0.7 + 0.75 * this._lvl);
        x = Math.sin(t * 1.35) * sr * 1.1;
        y = Math.sin(t * 2.7) * sr * 0.45 + Math.cos(t * 0.7) * R * 0.15;
        break;

      case "you":
        // Your voice, and nothing else. Every other state has autonomous
        // motion; this one has none. The distinction is the point — her line
        // is alive on its own, yours exists only while you are speaking. At
        // silence it collapses to a flat point, so a dead microphone looks
        // unmistakably dead instead of looking idle.
        var amp = this._lvl;
        if (amp < 0.02) { x = 0; y = 0; break; }
        var sp = R * 1.5 * amp;
        // A travelling wave rather than an orbit: it reads as a signal.
        x = Math.sin(t * 6.2) * sp;
        y = Math.sin(t * 11.0 + Math.sin(t * 3.1)) * sp * 0.55;
        break;

      case "roam":
        // Off wandering while nobody is watching. Wide, slow, unhurried; the
        // element itself is being moved around the page by the page.
        x = Math.cos(t * 0.5) * R * 1.15 + Math.cos(t * 0.17) * R * 0.4;
        y = Math.sin(t * 0.63) * R * 0.95 + Math.sin(t * 0.29) * R * 0.3;
        break;

      default: // idle — connected, breathing, going nowhere in particular
        x = Math.cos(t * 0.62) * R * 0.72 + Math.cos(t * 0.23) * R * 0.18;
        y = Math.sin(t * 0.81) * R * 0.58;
    }
    return { x: x + bx, y: y + by };
  };

  Mark.prototype._loop = function () {
    if (this.dead) return;
    if (this.cv.isConnected) this._seen = true;
    else if (this._seen) { this.dispose(); return; }
    var ctx = this.ctx, w = this.w, h = this.h;
    var dt = this.reduced ? 0.0 : 1 / 60;
    this.t += dt * (this.state === "think" ? 1.5
                  : this.state === "error" ? 1.2 : 1.0);

    // Energy is real: how long we have actually been in this state.
    var secs = (Date.now() - this.enteredAt) / 1000;
    var want = this.state === "idle" ? 0.18 : Math.min(1, secs / 12);
    this.energy += (want - this.energy) * 0.03;

    // Smooth the level: attack fast so it feels responsive, release slow so it
    // does not flicker between syllables.
    var tgtL = this.level;
    this._lvl += (tgtL - this._lvl) * (tgtL > this._lvl ? 0.35 : 0.06);
    this.boost *= 0.94;
    var tgt = this._target();
    if (this.boost > 0.01) {
      tgt.x += this.kick.x * this.boost * 9;
      tgt.y += this.kick.y * this.boost * 9;
    }
    // Spring the pen toward the target. Stiffness per state gives each one a
    // different hand: thinking is twitchy, answering is languid.
    var stiff = this.state === "think" ? 0.20
              : this.state === "code" ? 0.34
              : this.state === "error" ? 0.42
              : this.state === "media" ? 0.055 : 0.045;
    this.vx = (this.vx + (tgt.x - this.px) * stiff) * 0.86;
    this.vy = (this.vy + (tgt.y - this.py) * stiff) * 0.86;
    this.px += this.vx; this.py += this.vy;

    this.pts.push({ x: this.px, y: this.py });
    var keep = this.reduced ? 42 : this.max;
    while (this.pts.length > keep) this.pts.shift();

    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate(w / 2, h / 2);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    var col = C[this.state] || C.idle;
    var n = this.pts.length;
    // ONE line. Drawn as segments only so it can taper — the path never breaks.
    for (var i = 1; i < n; i++) {
      var a = i / n;                       // 0 at the tail, 1 at the head
      ctx.globalAlpha = a * a * 0.95;
      ctx.lineWidth = 0.6 + a * (2.3 + this.boost * 2.2 + this._lvl * 1.6);
      ctx.strokeStyle = col;
      ctx.beginPath();
      ctx.moveTo(this.pts[i - 1].x, this.pts[i - 1].y);
      ctx.lineTo(this.pts[i].x, this.pts[i].y);
      ctx.stroke();
    }
    // The head. Her line "ends where the user's cursor lands", so the end of it
    // is the one part that gets to be solid.
    if (n) {
      var p = this.pts[n - 1];
      ctx.globalAlpha = 1;
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 2.6, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
    global.requestAnimationFrame(this._loop);
  };

  Mark.COLOURS = C;
  global.ElenaMark = Mark;
})(window);
