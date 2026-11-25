// Timer alarm: repeating beeps (Web Audio), vibration and a system notification.
import { prefs } from './store.js';

let ctx = null;
let loop = null;
const notified = new Set();

export function unlockAudio() {
  try {
    ctx ??= new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === 'suspended') ctx.resume();
  } catch {
    /* no audio available */
  }
}
addEventListener('pointerdown', unlockAudio, { capture: true });
addEventListener('keydown', unlockAudio, { capture: true });

function beep(freq = 880, at = 0, len = 0.18) {
  if (!ctx) return;
  const t = ctx.currentTime + at;
  const o = ctx.createOscillator();
  const g = ctx.createGain();
  o.type = 'sine';
  o.frequency.value = freq;
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(0.5, t + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, t + len);
  o.connect(g).connect(ctx.destination);
  o.start(t);
  o.stop(t + len + 0.05);
}

function pattern() {
  if (prefs.sound) {
    beep(880, 0);
    beep(1175, 0.22);
    beep(880, 0.44);
  }
  if (prefs.vibrate && navigator.vibrate) navigator.vibrate([250, 120, 250]);
}

export function testAlarm() {
  unlockAudio();
  pattern();
}

// ringing: list of {b, t}. Starts/stops the loop and fires one notification per timer.
export function updateAlarm(ringing) {
  if (ringing.length && !loop) {
    pattern();
    loop = setInterval(pattern, 1600);
  } else if (!ringing.length && loop) {
    clearInterval(loop);
    loop = null;
  }
  for (const { b, t } of ringing) {
    if (notified.has(t.id)) continue;
    notified.add(t.id);
    notify(`${b.label}: ${t.label}`, 'Timer done');
  }
}

async function notify(title, body) {
  if (!('Notification' in window) || Notification.permission !== 'granted' || document.visibilityState === 'visible') return;
  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg) reg.showNotification(title, { body, tag: title, renotify: true, icon: '/live/yeschef/icon.svg' });
    else new Notification(title, { body });
  } catch {
    /* ignore */
  }
}
