// Shared state, kept by Philibert (nd_yeschef.py, /api/yeschef). Writes are optimistic, queued
// if Philibert is busy or restarting, and retried. Other windows' changes arrive by polling "rev".
const LS_STATE = 'yeschef.state';
const LS_QUEUE = 'yeschef.queue';
const LS_PREFS = 'yeschef.prefs';

export const store = {
  state: { rev: 0, recipes: {}, batches: {}, settings: {} },
  online: false,
  listeners: new Set(),
};

let queue = loadJson(LS_QUEUE, {}); // key "recipes/id" -> {op, ...}

function loadJson(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
}
function persistLocal() {
  try {
    localStorage.setItem(LS_STATE, JSON.stringify(store.state));
    localStorage.setItem(LS_QUEUE, JSON.stringify(queue));
  } catch {
    /* storage full: Philibert has the real copy */
  }
}

// One call to Philibert. Throws with Philibert's message when it says no.
export async function call(op, payload = {}) {
  const r = await fetch('/api/yeschef', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op, ...payload }),
  });
  let j = {};
  try {
    j = await r.json();
  } catch {
    /* not JSON */
  }
  if (!r.ok || j.ok === false) throw Object.assign(new Error(j.msg || j.error || `Philibert answered ${r.status}`), { status: r.status, refused: r.ok });
  return j;
}

export function onChange(fn) {
  store.listeners.add(fn);
  return () => store.listeners.delete(fn);
}
function emit(source) {
  for (const fn of store.listeners) fn(source);
}
function setOnline(v) {
  if (store.online !== v) {
    store.online = v;
    emit('online');
  }
}

export async function load() {
  try {
    store.state = (await call('state')).state;
    applyQueueLocally();
    setOnline(true);
  } catch {
    store.state = loadJson(LS_STATE, store.state);
    setOnline(false);
  }
  persistLocal();
  flush();
}

function applyQueueLocally() {
  for (const [key, op] of Object.entries(queue)) {
    const [coll, id] = key.split('/');
    if (op.op === 'settings') store.state.settings = { ...store.state.settings, ...op.settings };
    else if (op.op === 'delete') delete store.state[coll][id];
    else store.state[coll][id] = op.item;
  }
}

let flushing = false;
async function flush() {
  if (flushing) return;
  flushing = true;
  try {
    for (const [key, op] of Object.entries(queue)) {
      try {
        await call(op.op, op);
      } catch (e) {
        if (!e.refused) throw e; // Philibert unreachable: keep it queued
        console.warn('Yes Chef! write refused', key, e.message); // refused for good: drop it
      }
      if (queue[key] === op) delete queue[key];
      setOnline(true);
    }
  } catch {
    setOnline(false);
  } finally {
    flushing = false;
    persistLocal();
  }
}

function write(key, op) {
  queue[key] = op;
  persistLocal();
  emit('local');
  flush();
}

export function saveRecipe(r) {
  r.updatedAt = Date.now();
  store.state.recipes[r.id] = r;
  write('recipes/' + r.id, { op: 'save', coll: 'recipes', id: r.id, item: r });
}
export function deleteRecipe(id) {
  delete store.state.recipes[id];
  write('recipes/' + id, { op: 'delete', coll: 'recipes', id });
}
export function saveBatch(b) {
  b.updatedAt = Date.now();
  store.state.batches[b.id] = b;
  write('batches/' + b.id, { op: 'save', coll: 'batches', id: b.id, item: b });
}
export function deleteBatch(id) {
  delete store.state.batches[id];
  write('batches/' + id, { op: 'delete', coll: 'batches', id });
}
export function saveSettings(patch) {
  store.state.settings = { ...store.state.settings, ...patch };
  const prev = queue['settings/all']?.settings || {};
  write('settings/all', { op: 'settings', settings: { ...prev, ...patch } });
}

// Changes made in another Yes Chef! window.
export function startSync(intervalMs = 3000) {
  setInterval(async () => {
    if (Object.keys(queue).length) return flush();
    try {
      const { rev } = await call('rev');
      setOnline(true);
      if (rev !== store.state.rev) {
        const next = (await call('state')).state;
        if (Object.keys(queue).length) return;
        store.state = next;
        persistLocal();
        emit('remote');
      }
    } catch {
      setOnline(false);
    }
  }, intervalMs);
}

const DEFAULT_PREFS = { units: 'g', showPercent: true, sound: true, vibrate: true, autoScale: true };
export const prefs = { ...DEFAULT_PREFS, ...loadJson(LS_PREFS, {}) };
export function setPref(k, v) {
  prefs[k] = v;
  localStorage.setItem(LS_PREFS, JSON.stringify(prefs));
  emit('prefs');
}

export function blobToB64(blob) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).split(',')[1] || '');
    fr.onerror = () => reject(new Error('Could not read the file'));
    fr.readAsDataURL(blob);
  });
}

export async function uploadPhoto(blob) {
  const j = await call('photo_add', { type: blob.type || 'image/jpeg', data: await blobToB64(blob) });
  return j.url;
}

// Philibert's own models: 'ask', 'evaluate', 'structure'
export async function aiPost(op, body) {
  return call(op, body);
}
