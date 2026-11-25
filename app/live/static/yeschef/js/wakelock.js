// Keep the screen on while in cook mode.
// Uses the Screen Wake Lock API (needs HTTPS or localhost). Over plain http on a phone it falls
// back to a muted looping video, which keeps many (not all) phones awake.
let want = false;
let lock = null;
let video = null;
let mode = 'off'; // 'lock' | 'video' | 'off'
const listeners = new Set();

export const wakeMode = () => mode;
export const onWake = (fn) => (listeners.add(fn), () => listeners.delete(fn));
const set = (m) => {
  mode = m;
  listeners.forEach((f) => f(m));
};

export async function keepAwake(on) {
  want = on;
  if (on) await acquire();
  else release();
}

async function acquire() {
  if ('wakeLock' in navigator && window.isSecureContext) {
    try {
      lock = await navigator.wakeLock.request('screen');
      lock.addEventListener('release', () => {
        lock = null;
        if (mode === 'lock') set('off');
      });
      set('lock');
      return;
    } catch {
      /* fall through to video */
    }
  }
  startVideo();
}

function startVideo() {
  try {
    if (!video) {
      const c = document.createElement('canvas');
      c.width = c.height = 2;
      const g = c.getContext('2d');
      let n = 0;
      setInterval(() => {
        g.fillStyle = n++ % 2 ? '#000' : '#010101';
        g.fillRect(0, 0, 2, 2);
      }, 1000);
      video = document.createElement('video');
      video.muted = true;
      video.playsInline = true;
      video.setAttribute('playsinline', '');
      video.loop = true;
      video.style.cssText = 'position:fixed;width:1px;height:1px;opacity:0.01;pointer-events:none;bottom:0;left:0';
      video.srcObject = c.captureStream(1);
      document.body.appendChild(video);
    }
    video.play().then(() => set('video')).catch(() => set('off'));
  } catch {
    set('off');
  }
}

function release() {
  lock?.release().catch(() => {});
  lock = null;
  video?.pause();
  set('off');
}

document.addEventListener('visibilitychange', () => {
  if (want && document.visibilityState === 'visible' && !lock) acquire();
});
