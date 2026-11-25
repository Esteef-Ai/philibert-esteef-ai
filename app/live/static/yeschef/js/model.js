// Recipe and batch logic: forks, diffs, batch step tracking, timers and ETAs.
import { store, saveBatch, saveRecipe } from './store.js';
import { uid, BATCH_COLORS } from './ui.js';
import { flourTotal } from './units.js';

export const recipes = () => Object.values(store.state.recipes).sort((a, b) => (a.createdAt || 0) - (b.createdAt || 0));
export const batches = () => Object.values(store.state.batches).sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0));
export const activeBatches = () => batches().filter((b) => b.status === 'active').reverse();

export function children(id) {
  return recipes().filter((r) => r.parentId === id);
}
export function rootOf(r) {
  let cur = r;
  const seen = new Set();
  while (cur?.parentId && store.state.recipes[cur.parentId] && !seen.has(cur.id)) {
    seen.add(cur.id);
    cur = store.state.recipes[cur.parentId];
  }
  return cur;
}
export function family(rootId) {
  const out = [];
  const walk = (id, depth) => {
    const r = store.state.recipes[id];
    if (!r) return;
    out.push({ r, depth });
    for (const c of children(id)) walk(c.id, depth + 1);
  };
  walk(rootId, 0);
  return out;
}

export function newRecipe() {
  return {
    id: uid('r'),
    name: 'New recipe',
    parentId: null,
    hypothesis: '',
    notes: '',
    tags: [],
    yieldNote: '',
    loafWeight: 500,
    createdAt: Date.now(),
    ingredients: [
      { id: uid('i'), name: 'Bread flour', grams: 500, kind: 'flour', flour: true },
      { id: uid('i'), name: 'Water', grams: 340, kind: 'water', flour: false },
      { id: uid('i'), name: 'Instant yeast', grams: 5, kind: 'yeast', flour: false },
      { id: uid('i'), name: 'Salt', grams: 10, kind: 'salt', flour: false },
    ],
    steps: [newStep('Mix')],
  };
}
export function newStep(title = 'New step') {
  return { id: uid('s'), title, detail: '', type: 'active', minutes: null, maxMinutes: null, est: 5, check: '' };
}

export function forkRecipe(parent, { name, hypothesis = '', tags } = {}) {
  const r = structuredClone(parent);
  r.id = uid('r');
  r.parentId = parent.id;
  r.name = name || parent.name + ' (fork)';
  r.hypothesis = hypothesis;
  r.tags = tags || [...new Set([...(parent.tags || []).filter((t) => t !== 'baseline'), 'test'])];
  r.createdAt = Date.now();
  delete r.updatedAt;
  return r;
}

// ---------- diff ----------
export function diffRecipes(a, b) {
  const changes = [];
  const key = (x) => x.id || x.name;
  const ai = new Map(a.ingredients.map((i) => [key(i), i]));
  const bi = new Map(b.ingredients.map((i) => [key(i), i]));
  for (const [k, i] of bi) {
    const p = ai.get(k);
    if (!p) changes.push({ kind: 'add', what: 'ingredient', text: `Added ${i.name} ${round(i.grams)} g` });
    else {
      if (round(p.grams) !== round(i.grams))
        changes.push({ kind: 'change', what: 'ingredient', text: `${i.name}: ${round(p.grams)} g → ${round(i.grams)} g` });
      if (p.name !== i.name) changes.push({ kind: 'change', what: 'ingredient', text: `Renamed ${p.name} → ${i.name}` });
    }
  }
  for (const [k, i] of ai) if (!bi.has(k)) changes.push({ kind: 'remove', what: 'ingredient', text: `Removed ${i.name}` });

  const as = new Map(a.steps.map((s) => [s.id, s]));
  const bs = new Map(b.steps.map((s) => [s.id, s]));
  for (const [k, s] of bs) {
    const p = as.get(k);
    if (!p) changes.push({ kind: 'add', what: 'step', text: `New step: ${s.title}` });
    else {
      if ((p.minutes || 0) !== (s.minutes || 0) || (p.maxMinutes || 0) !== (s.maxMinutes || 0))
        changes.push({ kind: 'change', what: 'step', text: `${s.title}: ${tlabel(p)} → ${tlabel(s)}` });
      if (p.title !== s.title) changes.push({ kind: 'change', what: 'step', text: `Step renamed: ${p.title} → ${s.title}` });
      else if (p.detail !== s.detail) changes.push({ kind: 'change', what: 'step', text: `${s.title}: instructions changed` });
    }
  }
  for (const [k, s] of as) if (!bs.has(k)) changes.push({ kind: 'remove', what: 'step', text: `Removed step: ${s.title}` });
  return changes;
}
const round = (n) => Math.round((+n || 0) * 10) / 10;
const tlabel = (s) => (s.minutes ? (s.maxMinutes && s.maxMinutes !== s.minutes ? `${s.minutes}–${s.maxMinutes} min` : `${s.minutes} min`) : 'no timer');

// ---------- batches ----------
export function nextBatchLabel() {
  const used = new Set(activeBatches().map((b) => b.label));
  for (const c of 'ABCDEFGHIJKLMNOPQRSTUVWXYZ') if (!used.has('Batch ' + c)) return 'Batch ' + c;
  return 'Batch ' + (activeBatches().length + 1);
}
function nextColor() {
  const used = new Set(activeBatches().map((b) => b.color));
  return BATCH_COLORS.find((c) => !used.has(c)) || BATCH_COLORS[activeBatches().length % BATCH_COLORS.length];
}

export function startBatch(recipe, { factor = 1, label, notes = '' } = {}) {
  const b = {
    id: uid('b'),
    recipeId: recipe.id,
    recipe: structuredClone(recipe), // snapshot: later edits to the recipe do not change a running batch
    label: label || nextBatchLabel(),
    color: nextColor(),
    factor,
    createdAt: Date.now(),
    status: 'active',
    current: 0,
    log: {},
    timers: [],
    photos: [],
    checked: {},
    notes,
    result: null,
  };
  enterStep(b, 0);
  saveBatch(b);
  return b;
}

function enterStep(b, idx) {
  b.current = idx;
  const s = b.recipe.steps[idx];
  if (!s) return;
  b.log[s.id] = { ...(b.log[s.id] || {}), startedAt: Date.now(), doneAt: null, skipped: false };
  // Waiting and baking steps start their timer automatically; hands-on steps get a Start button.
  if (s.minutes && (s.type === 'wait' || s.type === 'bake')) addTimer(b, { label: s.title, minutes: s.minutes, stepId: s.id });
}

export function completeStep(b, { skip = false } = {}) {
  const s = b.recipe.steps[b.current];
  if (s) {
    b.log[s.id] = { ...(b.log[s.id] || {}), doneAt: Date.now(), skipped: skip };
    for (const t of b.timers) if (t.stepId === s.id && t.state !== 'dismissed') t.state = 'dismissed';
  }
  if (b.current + 1 >= b.recipe.steps.length) {
    b.current = b.recipe.steps.length;
    b.status = 'done';
    b.finishedAt = Date.now();
  } else enterStep(b, b.current + 1);
  saveBatch(b);
}

export function previousStep(b) {
  if (b.current <= 0) return;
  const cur = b.recipe.steps[b.current];
  if (cur) {
    delete b.log[cur.id];
    for (const t of b.timers) if (t.stepId === cur.id && t.state !== 'dismissed') t.state = 'dismissed';
  }
  if (b.status === 'done') b.status = 'active';
  b.current = Math.min(b.current - 1, b.recipe.steps.length - 1);
  const s = b.recipe.steps[b.current];
  b.log[s.id] = { ...(b.log[s.id] || {}), doneAt: null };
  saveBatch(b);
}

export function jumpToStep(b, idx) {
  if (idx === b.current) return;
  const cur = b.recipe.steps[b.current];
  if (cur) for (const t of b.timers) if (t.stepId === cur.id && t.state !== 'dismissed') t.state = 'dismissed';
  for (let i = 0; i < idx; i++) {
    const s = b.recipe.steps[i];
    if (!b.log[s.id]?.doneAt) b.log[s.id] = { ...(b.log[s.id] || {}), doneAt: Date.now(), skipped: true };
  }
  for (let i = idx; i < b.recipe.steps.length; i++) delete b.log[b.recipe.steps[i].id];
  b.status = 'active';
  enterStep(b, idx);
  saveBatch(b);
}

// ---------- timers ----------
// A timer is "ringing" when it is running and its end time has passed. Ringing is derived,
// not stored, so devices do not fight over writes; a device writes only when you act.
export function addTimer(b, { label, minutes, stepId = null }) {
  const ms = Math.round(minutes * 60000);
  b.timers.push({ id: uid('t'), label, stepId, durationMs: ms, endsAt: Date.now() + ms, remainingMs: null, state: 'running', createdAt: Date.now() });
}
export const timerRemaining = (t) => (t.state === 'paused' ? t.remainingMs : t.endsAt - Date.now());
export const isRinging = (t) => t.state === 'running' && t.endsAt <= Date.now();

export function timerAction(b, timerId, action, arg) {
  const t = b.timers.find((x) => x.id === timerId);
  if (!t) return;
  if (action === 'pause' && t.state === 'running') {
    t.remainingMs = Math.max(0, t.endsAt - Date.now());
    t.state = 'paused';
  } else if (action === 'resume' && t.state === 'paused') {
    t.endsAt = Date.now() + t.remainingMs;
    t.remainingMs = null;
    t.state = 'running';
  } else if (action === 'add') {
    const ms = arg * 60000;
    if (t.state === 'paused') t.remainingMs += ms;
    else t.endsAt = Math.max(t.endsAt, Date.now()) + ms;
    t.durationMs += ms;
    t.state = t.state === 'paused' ? 'paused' : 'running';
  } else if (action === 'dismiss') {
    t.state = 'dismissed';
  } else if (action === 'restart') {
    t.endsAt = Date.now() + t.durationMs;
    t.remainingMs = null;
    t.state = 'running';
  }
  saveBatch(b);
}
export const liveTimers = (b) => b.timers.filter((t) => t.state === 'running' || t.state === 'paused');
export function allLiveTimers() {
  const out = [];
  for (const b of activeBatches()) for (const t of liveTimers(b)) out.push({ b, t });
  return out.sort((x, y) => timerRemaining(x.t) - timerRemaining(y.t));
}

// ---------- estimates ----------
const stepMinutes = (s) => (s.minutes ? s.minutes : s.est || 5);
export function eta(b) {
  const steps = b.recipe.steps;
  if (b.status !== 'active') return null;
  const cur = steps[b.current];
  if (!cur) return null;
  const t = b.timers.find((x) => x.stepId === cur.id && (x.state === 'running' || x.state === 'paused'));
  let ms;
  if (t) ms = Math.max(0, timerRemaining(t));
  else {
    const started = b.log[cur.id]?.startedAt || Date.now();
    ms = Math.max(60000, stepMinutes(cur) * 60000 - (Date.now() - started));
  }
  // "Out of the oven" = end of the last required bake step.
  let lastBake = -1;
  steps.forEach((s, i) => {
    if (s.type === 'bake' && !s.optional) lastBake = i;
  });
  let ovenOut = b.current === lastBake ? Date.now() + ms : null;
  for (let i = b.current + 1; i < steps.length; i++) {
    const s = steps[i];
    if (s.optional) continue;
    ms += stepMinutes(s) * 60000;
    if (i === lastBake) ovenOut = Date.now() + ms;
  }
  return { done: Date.now() + ms, ovenOut };
}

// ---------- results ----------
export function bakesOf(recipeId) {
  return batches().filter((b) => b.recipeId === recipeId && b.result);
}
export function avgRatings(recipeId) {
  const list = bakesOf(recipeId);
  if (!list.length) return null;
  const avg = (k) => {
    const v = list.map((b) => b.result[k]).filter(Boolean);
    return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null;
  };
  return { n: list.length, crumb: avg('crumb'), crust: avg('crust'), flavor: avg('flavor'), overall: avg('overall') };
}

export function saveRecipeFromBatch(b) {
  // Turn a batch whose snapshot was adjusted into a fork of its recipe.
  const parent = store.state.recipes[b.recipeId] || b.recipe;
  const r = forkRecipe(parent, { name: parent.name + ' · from ' + b.label });
  r.ingredients = structuredClone(b.recipe.ingredients);
  r.steps = structuredClone(b.recipe.steps);
  saveRecipe(r);
  return r;
}

export function factorForFlour(recipe, targetFlour) {
  const f = flourTotal(recipe);
  return f ? targetFlour / f : 1;
}
