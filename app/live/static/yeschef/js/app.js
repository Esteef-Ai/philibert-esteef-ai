// App shell: routing, event delegation, re-rendering, ticking clocks and alarms.
import { store, load, startSync, onChange, setPref, prefs, saveBatch } from './store.js';
import { $, $$, fmtClock, fmtTime, closeModal, modalOpen, toast, bus } from './ui.js';
import { allLiveTimers, isRinging, timerRemaining, timerAction, activeBatches, eta } from './model.js';
import { timerBar } from './components.js';
import { updateAlarm } from './alarm.js';
import { assistActions, sendAsk } from './assist.js';

import * as recipesView from './views/recipes.js';
import * as recipeView from './views/recipe.js';
import * as editView from './views/edit.js';
import * as batchesView from './views/batches.js';
import * as batchView from './views/batch.js';
import * as cookView from './views/cook.js';
import * as testsView from './views/tests.js';
import * as settingsView from './views/settings.js';
import * as importView from './views/import.js';

const VIEWS = {
  recipes: recipesView,
  recipe: recipeView,
  edit: editView,
  batches: batchesView,
  batch: batchView,
  cook: cookView,
  tests: testsView,
  settings: settingsView,
  import: importView,
};

const NAV = [
  ['recipes', 'Recipes', '📖'],
  ['batches', 'Bake', '⏱'],
  ['tests', 'Tests', '🧪'],
  ['settings', 'Settings', '⚙'],
];

export const route = { name: 'recipes', params: [] };
function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  route.name = VIEWS[parts[0]] ? parts[0] : 'recipes';
  route.params = parts.slice(1);
}
export const go = (hash) => {
  if (location.hash === hash) render();
  else location.hash = hash;
};

const view = () => VIEWS[route.name];

// ---------- rendering ----------
let pendingRemote = false;
function busy() {
  const a = document.activeElement;
  const typing = a && a.closest?.('#view, .modal') && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) && a.type !== 'checkbox';
  return typing || view().isBusy?.() || modalOpen();
}

export function render() {
  pendingRemote = false;
  const v = view();
  const isCook = route.name === 'cook';
  document.body.classList.toggle('cook', isCook);
  const html = v.render(route.params) ?? '';
  const main = $('#view');
  const sameView = main.dataset.view === route.name + '/' + route.params.join('/');
  const y = window.scrollY;
  main.innerHTML = html;
  main.dataset.view = route.name + '/' + route.params.join('/');
  document.title = (v.title?.(route.params) || 'Yes Chef!') + (v.title ? ' · Yes Chef!' : '');
  renderNav();
  renderTimerBar();
  if (sameView) window.scrollTo(0, y);
  else if (!isCook) window.scrollTo(0, 0);
  v.mount?.(route.params, { sameView });
}

function renderNav() {
  const active = { recipe: 'recipes', edit: 'recipes', import: 'recipes', batch: 'batches', cook: 'batches' }[route.name] || route.name;
  const nActive = activeBatches().length;
  $('#nav').innerHTML = NAV.map(
    ([k, label, icon]) =>
      `<a href="#/${k}" class="${active === k ? 'on' : ''}"><span class="ico" aria-hidden="true">${icon}</span><span>${label}</span>${
        k === 'batches' && nActive ? `<span class="pill">${nActive}</span>` : ''
      }</a>`,
  ).join('');
  $('#sync').className = 'sync ' + (store.online ? 'ok' : 'off');
  $('#sync').title = store.online ? 'Saved by Philibert' : 'Philibert is not answering: changes are kept here and saved when it is back';
}

function renderTimerBar() {
  const items = allLiveTimers();
  const hideFor = route.name === 'cook' ? route.params[0] : null;
  const shown = hideFor ? items.filter((x) => x.b.id !== hideFor) : items;
  $('#timerbar').innerHTML = timerBar(shown);
  document.body.classList.toggle('has-timers', shown.length > 0);
}

// ---------- clocks ----------
function tick() {
  const byId = new Map();
  for (const b of activeBatches()) for (const t of b.timers) byId.set(t.id, { b, t });
  for (const el of $$('[data-timer]')) {
    const x = byId.get(el.dataset.timer);
    if (!x) continue;
    el.textContent = fmtClock(timerRemaining(x.t));
    const wrap = el.closest('.timer, .tb-item');
    const ring = isRinging(x.t);
    if (wrap && wrap.classList.contains('ringing') !== ring) {
      // A timer just went off: re-render so its buttons switch to "Done".
      if (!busy()) render();
      else wrap.classList.add('ringing');
    }
  }
  for (const el of $$('[data-eta]')) {
    const b = store.state.batches[el.dataset.eta];
    const e = b && eta(b);
    if (e) el.textContent = `${e.ovenOut ? `Out of oven ~${fmtTime(e.ovenOut)} · ` : ''}All done ~${fmtTime(e.done)}`;
  }
  for (const el of $$('[data-elapsed]')) {
    el.textContent = fmtClock(Date.now() - +el.dataset.elapsed);
  }
  const ringing = allLiveTimers().filter((x) => isRinging(x.t));
  updateAlarm(ringing);
  const first = allLiveTimers()[0];
  const base = document.title.replace(/^(⏰ |\(\d.*?\) )/, '');
  document.title = ringing.length ? '⏰ ' + base : first ? `(${fmtClock(timerRemaining(first.t))}) ` + base : base;
}

// ---------- events ----------
const GLOBAL = {
  ...assistActions,
  'modal-close': () => closeModal(),
  units: (el) => {
    setPref('units', el.dataset.u);
    render();
  },
  timer: (el) => {
    const b = store.state.batches[el.dataset.b];
    if (!b) return;
    timerAction(b, el.dataset.t, el.dataset.op, +el.dataset.arg || 0);
    render();
  },
  'check-ing': (el) => {
    const b = store.state.batches[el.dataset.b];
    if (!b) return;
    b.checked ??= {};
    b.checked[el.dataset.id] = !b.checked[el.dataset.id];
    saveBatch(b);
    // update in place so open drawers/modals keep their state
    el.classList.toggle('on', b.checked[el.dataset.id]);
    el.textContent = b.checked[el.dataset.id] ? '✓' : '';
    el.closest('li')?.classList.toggle('checked', b.checked[el.dataset.id]);
  },
};

function dispatch(kind, ev) {
  const el = ev.target.closest(`[data-${kind}]`);
  if (!el) return;
  const name = el.dataset[kind];
  const v = view();
  const fn = (kind === 'action' ? v.actions : kind === 'change' ? v.changes : v.inputs)?.[name] || (kind === 'action' ? GLOBAL[name] : null);
  if (!fn) return;
  if (kind === 'action' && (el.tagName === 'A' || el.tagName === 'BUTTON')) ev.preventDefault();
  try {
    fn(el, ev, route.params);
  } catch (e) {
    console.error(e);
    toast('Something went wrong: ' + e.message);
  }
}

document.addEventListener('click', (e) => dispatch('action', e));
document.addEventListener('change', (e) => dispatch('change', e));
document.addEventListener('input', (e) => dispatch('input', e));
document.addEventListener('submit', (e) => {
  e.preventDefault();
  const f = e.target.closest('[data-submit]');
  if (f) view().submits?.[f.dataset.submit]?.(f, e, route.params);
});
document.addEventListener('focusout', () => {
  setTimeout(() => {
    if (pendingRemote && !busy()) render();
  }, 50);
});
addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && modalOpen()) closeModal();
  if (e.key === 'Enter' && !e.shiftKey && e.target.closest?.('.ask-form')) {
    e.preventDefault();
    sendAsk();
    return;
  }
  view().onKey?.(e, route.params);
});

addEventListener('hashchange', () => {
  view().unmount?.();
  closeModal();
  parseRoute();
  render();
});

onChange((source) => {
  if (source === 'remote') {
    if (busy()) pendingRemote = true;
    else render();
  } else if (source === 'online') renderNav();
});

// ---------- boot ----------
(async function boot() {
  $('#app').innerHTML = `
    <header class="topbar">
      <a class="brand" href="#/recipes"><img src="/live/yeschef/icon.svg" alt="" width="28" height="28"> Yes Chef!</a>
      <nav id="nav" class="nav"></nav>
      <span id="sync" class="sync" aria-hidden="true"></span>
    </header>
    <div id="timerbar" class="timerbar" aria-live="polite"></div>
    <main id="view" class="view"></main>`;
  bus.render = render;
  parseRoute();
  await load();
  render();
  startSync();
  setInterval(tick, 500);
})();
