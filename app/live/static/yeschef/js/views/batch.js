// Batch details: timeline of every step with times, timers, photos, notes, and the result
// (ratings + problems) that feeds troubleshooting forks.
import { esc, fmtTime, fmtDate, fmtClock, stars, toast, openModal, closeModal, bus } from '../ui.js';
import { store, saveBatch, deleteBatch } from '../store.js';
import { jumpToStep, previousStep, completeStep, liveTimers, addTimer, saveRecipeFromBatch } from '../model.js';
import { flourTotal } from '../units.js';
import { timerChip, etaText, ingredientList, unitToggle, stepTypeBadge, empty } from '../components.js';
import { photoGrid } from '../assist.js';
import { PROBLEMS, scenariosFor } from '../scenarios.js';
import { applyScenario } from './recipe.js';

const get = (id) => store.state.batches[id];
export const title = ([id]) => get(id)?.label || 'Batch';

let resultDraft = null;

export function render([id]) {
  const b = get(id);
  if (!b) return empty('Batch not found.', '<a class="btn" href="#/batches">Back</a>');
  const steps = b.recipe.steps;
  const recipeExists = !!store.state.recipes[b.recipeId];
  if (!resultDraft || resultDraft.id !== id) resultDraft = { id, ...(b.result || { crumb: 0, crust: 0, flavor: 0, overall: 0, problems: [], notes: '' }) };
  const r = resultDraft;
  const suggestions = scenariosFor(r.problems || []).filter((s) => s.can(store.state.recipes[b.recipeId] || b.recipe));

  return `
  <div class="page-head" style="--c:${b.color}">
    <div>
      <a class="back" href="#/batches">← Bake</a>
      <h1><span class="dot big"></span> ${esc(b.label)}</h1>
      <p class="muted">${recipeExists ? `<a href="#/recipe/${b.recipeId}">${esc(b.recipe.name)}</a>` : esc(b.recipe.name)} · ${Math.round(
        flourTotal(b.recipe) * b.factor,
      )} g flour · started ${fmtDate(b.createdAt)}</p>
      ${b.status === 'active' ? `<p class="muted small">${etaText(b)}</p>` : ''}
    </div>
    <div class="btn-row">
      ${b.status === 'active' ? `<a class="btn primary big-touch" href="#/cook/${b.id}">Cook mode</a>` : ''}
      <button class="btn" data-action="ask" data-b="${b.id}">💬 Ask</button>
    </div>
  </div>

  <div class="grid-2">
    <section class="card">
      <h2>Timeline</h2>
      <ol class="timeline">
        ${steps
          .map((s, i) => {
            const log = b.log[s.id] || {};
            const state = i < b.current ? (log.skipped ? 'skipped' : 'done') : i === b.current && b.status === 'active' ? 'current' : 'todo';
            const dur = log.startedAt && log.doneAt ? fmtClock(log.doneAt - log.startedAt) : '';
            return `<li class="tl-${state}">
            <div class="tl-head">
              <strong>${i + 1}. ${esc(s.title)}</strong> ${stepTypeBadge(s)}
              <span class="muted small">${log.startedAt ? fmtTime(log.startedAt) : ''}${dur ? ` · took ${dur}` : ''}${state === 'skipped' ? ' · skipped' : ''}</span>
            </div>
            ${state === 'current' ? `<div class="muted small"><span data-elapsed="${log.startedAt}">${fmtClock(Date.now() - log.startedAt)}</span> so far</div>` : ''}
            ${b.status === 'active' && state !== 'current' ? `<button class="link-btn" data-action="jump" data-i="${i}">Go to this step</button>` : ''}
          </li>`;
          })
          .join('')}
      </ol>
      ${
        b.status === 'active'
          ? `<div class="btn-row">
          <button class="btn" data-action="back">← Previous step</button>
          <button class="btn primary" data-action="next">✓ Done with “${esc(steps[b.current]?.title || '')}”</button>
        </div>`
          : `<div class="btn-row"><button class="btn" data-action="reopen">Reopen batch</button></div>`
      }
    </section>

    <div class="stack">
      <section class="card">
        <div class="card-head"><h2>Timers</h2></div>
        ${liveTimers(b).map((t) => timerChip(b, t)).join('') || '<p class="muted">No timers running.</p>'}
        <form class="inline-form" data-submit="timer">
          <input name="label" placeholder="Label (e.g. oven preheat)" aria-label="Timer label">
          <span class="inline-input"><input name="min" type="number" inputmode="decimal" min="0.1" step="any" value="10" aria-label="Minutes"><span>min</span></span>
          <button class="btn">+ Timer</button>
        </form>
      </section>

      <section class="card">
        <div class="card-head"><h2>Ingredients</h2>${unitToggle()}</div>
        ${ingredientList(b.recipe, b.factor, { checkable: true, checked: b.checked || {}, batchId: b.id })}
      </section>
    </div>
  </div>

  <section class="card">
    <div class="card-head"><h2>Photos</h2><button class="btn" data-action="photo" data-b="${b.id}" data-s="${steps[Math.min(b.current, steps.length - 1)]?.id || ''}">📷 Add photo</button></div>
    ${photoGrid(b) || '<p class="muted">Photos you take during the bake show up here, tagged with the step. They can be sent to the photo evaluator once it is set up.</p>'}
  </section>

  <section class="card">
    <h2>Notes</h2>
    <textarea rows="3" class="full" data-change="notes" placeholder="Room temperature, how the dough felt, anything you changed…">${esc(b.notes || '')}</textarea>
  </section>

  <section class="card result">
    <h2>${b.status === 'active' ? 'Result (fill in when it is done)' : 'How did it turn out?'}</h2>
    <div class="ratings">
      <div><span>Crumb</span>${stars(r.crumb, 'crumb')}</div>
      <div><span>Crust</span>${stars(r.crust, 'crust')}</div>
      <div><span>Flavor</span>${stars(r.flavor, 'flavor')}</div>
      <div><span>Overall</span>${stars(r.overall, 'overall')}</div>
    </div>
    <p class="muted small">Anything to fix next time?</p>
    <div class="chips wrap">${PROBLEMS.map(
      (p) => `<button class="chip ${r.problems?.includes(p.id) ? 'on' : ''}" data-action="problem" data-p="${p.id}">${esc(p.label)}</button>`,
    ).join('')}</div>
    <textarea rows="2" class="full" data-input="rnotes" placeholder="What was it like? Compare with the target loaf.">${esc(r.notes || '')}</textarea>
    <div class="btn-row"><button class="btn primary" data-action="save-result">Save result</button></div>

    ${
      suggestions.length
        ? `<div class="suggest">
        <h3>Suggested next tests</h3>
        <p class="muted small">Each creates a fork of “${esc(b.recipe.name)}” with one change.</p>
        ${suggestions
          .map(
            (s) => `<div class="scenario"><div><strong>${esc(s.title)}</strong><p class="muted">${esc(s.why)}</p></div>
            <button class="btn small primary" data-action="make-test" data-s="${s.id}">Create test fork</button></div>`,
          )
          .join('')}
      </div>`
        : ''
    }
  </section>

  <div class="btn-row">
    <button class="btn ghost" data-action="as-recipe">Save this batch's formula as a fork</button>
    <button class="btn ghost danger" data-action="delete">Delete batch</button>
  </div>`;
}

export function unmount() {
  resultDraft = null;
}

export const isBusy = () => false;

export const actions = {
  next(_el, _e, [id]) {
    completeStep(get(id));
    bus.render();
  },
  back(_el, _e, [id]) {
    previousStep(get(id));
    bus.render();
  },
  jump(el, _e, [id]) {
    jumpToStep(get(id), +el.dataset.i);
    bus.render();
  },
  reopen(_el, _e, [id]) {
    const b = get(id);
    b.status = 'active';
    b.current = Math.max(0, b.recipe.steps.length - 1);
    saveBatch(b);
    bus.render();
  },
  rate(el) {
    resultDraft[el.dataset.field] = +el.dataset.value;
    bus.render();
  },
  problem(el) {
    const p = el.dataset.p;
    const list = resultDraft.problems || [];
    resultDraft.problems = list.includes(p) ? list.filter((x) => x !== p) : [...list, p];
    bus.render();
  },
  'save-result'(_el, _e, [id]) {
    const b = get(id);
    const { id: _ignore, ...result } = resultDraft;
    b.result = { ...result, at: Date.now() };
    saveBatch(b);
    toast('Result saved');
    bus.render();
  },
  'make-test'(el, _e, [id]) {
    const b = get(id);
    const base = store.state.recipes[b.recipeId] || b.recipe;
    const fork = applyScenario(base, el.dataset.s);
    toast('Test fork created');
    location.hash = `#/recipe/${fork.id}`;
  },
  'as-recipe'(_el, _e, [id]) {
    const r = saveRecipeFromBatch(get(id));
    location.hash = `#/edit/${r.id}`;
  },
  delete(_el, _e, [id]) {
    if (!confirm('Delete this batch and its timers? Photos stay on disk.')) return;
    deleteBatch(id);
    location.hash = '#/batches';
  },
};

export const changes = {
  notes(el, _e, [id]) {
    const b = get(id);
    b.notes = el.value;
    saveBatch(b);
  },
};
export const inputs = {
  rnotes(el) {
    resultDraft.notes = el.value;
  },
};

export const submits = {
  timer(form, _e, [id]) {
    const fd = new FormData(form);
    const min = parseFloat(fd.get('min'));
    if (!(min > 0)) return toast('Enter minutes');
    const b = get(id);
    addTimer(b, { label: String(fd.get('label') || '').trim() || `${min} min timer`, minutes: min });
    saveBatch(b);
    bus.render();
  },
};

export { openModal, closeModal };
