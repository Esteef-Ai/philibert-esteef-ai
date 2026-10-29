// Stream host: copy everything the emulator plays into a MediaStream, so the game's sound
// can go to the friends watching. Loaded in the emulator frame BEFORE EmulatorJS.
// Anything connected to an AudioContext's speakers is also connected to a
// MediaStreamDestination of that context; window.RVTap.stream() returns its stream.
(function () {
  const taps = new Map();          // AudioContext -> MediaStreamAudioDestinationNode
  const connect = AudioNode.prototype.connect;
  AudioNode.prototype.connect = function (target, ...rest) {
    const out = connect.call(this, target, ...rest);
    try {
      if (target && target === this.context.destination) {
        let tap = taps.get(this.context);
        if (!tap) { tap = this.context.createMediaStreamDestination(); taps.set(this.context, tap); }
        connect.call(this, tap);
      }
    } catch (e) { /* never break the game's sound */ }
    return out;
  };
  window.RVTap = {
    stream() {                     // the most recently created context is the game's
      let last = null;
      taps.forEach(t => { last = t; });
      return last ? last.stream : null;
    }
  };
})();
