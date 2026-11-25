// Small UI helpers shared by all views.

// app.js sets bus.render so views can re-render without importing the app shell.
export const bus = { render: () => {} };
export const esc = (v) =>
  String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

export const uid = (p = '') => p + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function toast(msg, ms = 2600) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => {
    el.classList.remove('show');
    setTimeout(() => el.remove(), 300);
  }, ms);
}

// Modal: returns a close() function. `body` is HTML; actions inside use data-action as usual.
let modalClose = null;
export function openModal(title, body, { wide = false, onClose } = {}) {
  closeModal();
  const wrap = document.createElement('div');
  wrap.className = 'modal-wrap';
  wrap.innerHTML = `
    <div class="modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <header class="modal-head"><h2>${esc(title)}</h2>
        <button class="icon-btn" data-action="modal-close" aria-label="Close">✕</button></header>
      <div class="modal-body">${body}</div>
    </div>`;
  wrap.addEventListener('mousedown', (e) => {
    if (e.target === wrap) closeModal();
  });
  document.body.appendChild(wrap);
  modalClose = () => {
    wrap.remove();
    modalClose = null;
    onClose?.();
  };
  const first = wrap.querySelector('input,select,textarea');
  if (first && matchMedia('(pointer:fine)').matches) first.focus();
  return closeModal;
}
export function closeModal() {
  modalClose?.();
}
export const modalOpen = () => !!modalClose;
export function setModalBody(html) {
  const b = document.querySelector('.modal-body');
  if (b) b.innerHTML = html;
}

export function fmtClock(ms) {
  const neg = ms < 0;
  let s = Math.round(Math.abs(ms) / 1000);
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  s -= m * 60;
  const body = h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
  return (neg ? '+' : '') + body;
}

export const fmtTime = (t) => new Date(t).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
export const fmtDate = (t) =>
  new Date(t).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) + ' ' + fmtTime(t);

export function minutesLabel(step) {
  if (!step.minutes) return '';
  return step.maxMinutes && step.maxMinutes !== step.minutes ? `${step.minutes}–${step.maxMinutes} min` : `${step.minutes} min`;
}

export const BATCH_COLORS = ['#d97706', '#2563eb', '#059669', '#db2777', '#7c3aed', '#0891b2', '#b45309', '#dc2626'];

export function stars(n, name) {
  return `<span class="stars" role="radiogroup">${[1, 2, 3, 4, 5]
    .map(
      (i) =>
        `<button type="button" class="star ${i <= (n || 0) ? 'on' : ''}" data-action="rate" data-field="${name}" data-value="${i}" aria-label="${i} of 5">★</button>`,
    )
    .join('')}</span>`;
}

// Resize a phone photo before upload so it is quick to send and store.
export async function shrinkImage(file, max = 1600) {
  try {
    const url = URL.createObjectURL(file);
    const img = await new Promise((res, rej) => {
      const i = new Image();
      i.onload = () => res(i);
      i.onerror = rej;
      i.src = url;
    });
    const scale = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement('canvas');
    c.width = Math.round(img.naturalWidth * scale);
    c.height = Math.round(img.naturalHeight * scale);
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    URL.revokeObjectURL(url);
    return await new Promise((res) => c.toBlob(res, 'image/jpeg', 0.85));
  } catch {
    return file; // fall back to the original if the browser cannot decode it
  }
}
