// Cook mode: full-screen, screen stays on, one big card per step with scroll-snap,
// a large Done button, and quick switching between batches running at the same time.
import { esc, fmtClock, minutesLabel, openModal, bus } from '../ui.js';
import { store, saveBatch, prefs, setPref } from '../store.js';
import { completeStep, previousStep, jumpToStep, addTimer, liveTimers, activeBatches, timerRemaining, isRinging } from '../model.js';
import { timerChip, etaText, ingredientList, unitToggle, stepTypeBadge, empty, analyze, alertBadge, alertItem } from '../components.js';
import { keepAwake, wakeMode, onWake } from '../wakelock.js';
import { photoGrid } from '../assist.js';

const get = (id) => store.state.batches[id];
export const title = ([id]) => (get(id) ? 'Cooking ' + get(id).label : 'Cook mode');

let lastScrolled = '';
let offWake = null;

const WAKE_TEXT = {
  lock: ['☀ Screen stays on', 'ok'],
  video: ['☀ Screen on (backup mode)', 'meh'],
  off: ['Screen may sleep', 'off'],
};
const wakeBadge = () => {
  const [t, c] = WAKE_TEXT[wakeMode()];
  return `<span class="wake ${c}" id="wake" title="${t}${c === 'off' ? ' — open the https address on your phone to keep it on' : ''}">${t.slice(0, 1)}<span class="wake-txt">${t.slice(1)}</span></span>`;
};

export function render([id]) {
  const b = get(id);
  if (!b) return empty('Batch not found.', '<a class="btn" href="#/batches">Back</a>');
  const steps = b.recipe.steps;
  const others = activeBatches().filter((x) => x.id !== b.id);
  const cur = steps[b.current];
  const next = steps[b.current + 1];
  const done = b.status !== 'active';
  const alerts = analyze(b.recipe);

  return `
  <div class="cook-wrap" style="--c:${b.color}">
    <header class="cook-head">
      <a class="icon-btn" href="#/batch/${b.id}" aria-label="Leave cook mode">✕</a>
      <div class="cook-title"><span class="dot"></span><strong>${esc(b.label)}</strong><span class="muted small">${esc(b.recipe.name)}</span></div>
      ${wakeBadge()}
      <button class="btn small" data-action="ingredients">Ingredients</button>
      <button class="btn small" data-action="ask" data-b="${b.id}" aria-label="Ask for help">💬</button>
    </header>

    ${
      others.length
        ? `<nav class="cook-switch" aria-label="Other batches">${others
            .map((o) => {
              const t = liveTimers(o).sort((x, y) => timerRemaining(x) - timerRemaining(y))[0];
              return `<a class="sw ${t && isRinging(t) ? 'ringing' : ''}" href="#/cook/${o.id}" style="--c:${o.color}"><span class="dot"></span>${esc(o.label)} · ${esc(
                o.recipe.steps[o.current]?.title || '',
              )}${t ? ` <span class="sw-clock" data-timer="${t.id}">${fmtClock(timerRemaining(t))}</span>` : ''}</a>`;
            })
            .join('')}</nav>`
        : ''
    }

    <div class="cook-steps" id="cook-steps">
      ${steps.map((s, i) => stepCard(b, s, i, alerts)).join('')}
      ${
        done
          ? `<section class="cook-card finished" data-i="${steps.length}">
          <h2>All done 🎉</h2>
          <p>Let it cool fully, then rate the bake so the next test can build on it.</p>
          <a class="btn primary big-touch" href="#/batch/${b.id}">Rate this bake</a>
        </section>`
          : ''
      }
      <div class="cook-spacer"></div>
    </div>

    <footer class="cook-foot">
      <button class="btn big-touch" data-action="back" ${b.current === 0 ? 'disabled' : ''} aria-label="Previous step">←</button>
      ${
        done
          ? `<a class="btn primary big-touch grow" href="#/batch/${b.id}">Rate this bake</a>`
          : `<button class="btn primary big-touch grow" data-action="next">✓ Done${next ? `<span class="next-hint">Next: ${esc(next.title)}</span>` : '<span class="next-hint">Finish batch</span>'}</button>`
      }
    </footer>
    <div class="cook-eta muted small">${done ? '' : etaText(b)}</div>
  </div>`;
}

function stepCard(b, s, i, alerts) {
  const state = b.status !== 'active' || i < b.current ? 'past' : i === b.current ? 'current' : 'future';
  const log = b.log[s.id] || {};
  const timers = b.timers.filter((t) => t.stepId === s.id && (t.state === 'running' || t.state === 'paused'));
  const ad = state === 'current' ? liveTimers(b).filter((t) => !t.stepId) : [];
  const own = alerts.filter((a) => a.stepId === s.id && !a.showAtStepId);
  // Heads-up: things for later steps that have to start now, and MUST READs in the next 3 steps.
  const ahead =
    state === 'current'
      ? alerts.filter((a) => {
          if (a.showAtStepId === s.id) return true;
          const at = b.recipe.steps.findIndex((x) => x.id === a.stepId);
          return a.level === 'read' && at > i && at <= i + 3 && !a.showAtStepId;
        })
      : [];
  const lvl = own.some((a) => a.level === 'read') ? 'read' : own.length ? 'check' : null;
  return `
  <section class="cook-card ${state}" data-i="${i}" ${state === 'current' ? 'aria-current="step"' : ''}>
    <div class="cc-top">
      <span class="cc-num">${state === 'past' ? (log.skipped ? '–' : '✓') : i + 1}</span>
      ${stepTypeBadge(s)}
      ${s.minutes ? `<span class="badge b-time">⏱ ${minutesLabel(s)}</span>` : ''}
      ${s.optional ? '<span class="muted small">optional</span>' : ''}
      ${state !== 'past' ? alertBadge(lvl, true) : ''}
    </div>
    ${s.section && s.section !== b.recipe.steps[i - 1]?.section ? `<div class="cc-section">${esc(s.section)}</div>` : ''}
    <h2>${esc(s.title)}</h2>
    ${ahead.length ? `<ul class="alerts heads-up">${ahead.map((a) => alertItem({ ...a, title: '⏭ Heads-up: ' + a.title }, b.recipe)).join('')}</ul>` : ''}
    <p class="cc-detail">${esc(s.detail)}</p>
    ${s.check ? `<div class="cue big">✔ Ready when: ${esc(s.check)}</div>` : ''}
    ${state !== 'past' && own.length ? `<ul class="alerts">${own.map((a) => alertItem(a, null)).join('')}</ul>` : ''}
    ${
      state === 'current'
        ? `
      ${timers.map((t) => timerChip(b, t, { big: true })).join('')}
      ${ad.map((t) => timerChip(b, t)).join('')}
      ${
        s.minutes && !timers.length
          ? `<button class="btn big-touch" data-action="start-timer" data-s="${s.id}">⏱ Start ${s.minutes} min timer</button>`
          : ''
      }
      ${log.startedAt ? `<div class="muted small">On this step for <span data-elapsed="${log.startedAt}">${fmtClock(Date.now() - log.startedAt)}</span></div>` : ''}
      <div class="btn-row">
        <button class="btn" data-action="quick-timer">+ Timer</button>
        <button class="btn" data-action="photo" data-b="${b.id}" data-s="${s.id}">📷 Photo</button>
        ${s.optional ? `<button class="btn ghost" data-action="skip">Skip</button>` : ''}
      </div>
      ${photoGrid(b, s.id)}`
        : state === 'future'
          ? `<button class="link-btn" data-action="jump" data-i="${i}">Jump to this step</button>`
          : ''
    }
  </section>`;
}

export function mount([id], { sameView }) {
  const b = get(id);
  if (!b) return;
  if (!sameView) keepAwake(true);
  offWake?.();
  offWake = onWake(() => {
    const el = document.getElementById('wake');
    if (el) el.outerHTML = wakeBadge();
  });
  const key = `${id}:${b.current}:${b.status}`;
  const target = document.querySelector('.cook-card.current') || document.querySelector('.cook-card.finished');
  if (target && key !== lastScrolled) {
    target.scrollIntoView({ behavior: lastScrolled.startsWith(id + ':') ? 'smooth' : 'auto', block: 'start' });
    lastScrolled = key;
  } else if (sameView && target) {
    // keep position on remote refresh
  }
}

export function unmount() {
  keepAwake(false);
  offWake?.();
  offWake = null;
  lastScrolled = '';
}

export function onKey(e, [id]) {
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || document.querySelector('.modal')) return;
  if (e.key === 'ArrowRight' || e.key === 'n') actions.next(null, e, [id]);
  if (e.key === 'ArrowLeft' || e.key === 'p') actions.back(null, e, [id]);
}

export const actions = {
  next(_el, _e, [id]) {
    const b = get(id);
    if (!b || b.status !== 'active') return;
    const s = b.recipe.steps[b.current];
    const t = b.timers.find((x) => x.stepId === s.id && x.state === 'running' && timerRemaining(x) > 60000);
    if (t && !confirm(`The timer still has ${fmtClock(timerRemaining(t))} left. Move on anyway?`)) return;
    completeStep(b);
    bus.render();
  },
  back(_el, _e, [id]) {
    previousStep(get(id));
    bus.render();
  },
  skip(_el, _e, [id]) {
    completeStep(get(id), { skip: true });
    bus.render();
  },
  jump(el, _e, [id]) {
    const b = get(id);
    const s = b.recipe.steps[+el.dataset.i];
    if (!confirm(`Jump to “${s.title}”? Steps before it will be marked skipped.`)) return;
    jumpToStep(b, +el.dataset.i);
    bus.render();
  },
  'start-timer'(el, _e, [id]) {
    const b = get(id);
    const s = b.recipe.steps.find((x) => x.id === el.dataset.s);
    addTimer(b, { label: s.title, minutes: s.minutes, stepId: s.id });
    saveBatch(b);
    bus.render();
  },
  'quick-timer'(_el, _e, [id]) {
    openModal(
      'Add a timer',
      `<form data-submit="quick-timer">
        <label class="field"><span>Label</span><input name="label" placeholder="e.g. Preheat oven"></label>
        <div class="chips wrap">${[1, 3, 5, 10, 15, 20, 30, 45, 60]
          .map((m) => `<button class="chip" type="button" data-action="qt-min" data-m="${m}">${m} min</button>`)
          .join('')}</div>
        <label class="field"><span>Minutes</span><input name="min" type="number" inputmode="decimal" min="0.1" step="any" value="10"></label>
        <div class="btn-row end"><button type="button" class="btn" data-action="modal-close">Cancel</button><button class="btn primary">Start timer</button></div>
      </form>`,
    );
  },
  'qt-min'(el) {
    const input = document.querySelector('.modal input[name=min]');
    if (input) input.value = el.dataset.m;
  },
  ingredients(_el, _e, [id]) {
    const b = get(id);
    openModal(
      `${b.label} ingredients`,
      `<div class="card-head">${unitToggle()}</div>
       ${ingredientList(b.recipe, b.factor, { checkable: true, checked: b.checked || {}, batchId: b.id })}
       <p class="muted small">Tick each one as you weigh it out.</p>`,
    );
  },
  units(el, _e, params) {
    // Unit toggle inside the ingredients drawer: re-open it in the new unit.
    setPref('units', el.dataset.u);
    if (document.querySelector('.modal')) actions.ingredients(null, null, params);
    else bus.render();
  },
};

export const submits = {
  'quick-timer'(form, _e, [id]) {
    const fd = new FormData(form);
    const min = parseFloat(fd.get('min'));
    if (!(min > 0)) return;
    const b = get(id);
    addTimer(b, { label: String(fd.get('label') || '').trim() || `${min} min`, minutes: min });
    saveBatch(b);
    document.querySelector('[data-action=modal-close]')?.click();
    bus.render();
  },
};

export { prefs };
