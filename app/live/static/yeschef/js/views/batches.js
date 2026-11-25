// Bake dashboard: every batch in progress with its current step, timers and ETA.
import { esc, openModal, closeModal, fmtDate, fmtClock, toast, bus } from '../ui.js';
import { store } from '../store.js';
import { activeBatches, batches, recipes, startBatch, completeStep, liveTimers, nextBatchLabel } from '../model.js';
import { flourTotal } from '../units.js';
import { timerChip, etaText, empty, analyze, alertLevel } from '../components.js';
import { startAlerts } from './recipe.js';

export const title = () => 'Bake';

export function render() {
  const active = activeBatches();
  const done = batches().filter((b) => b.status !== 'active');
  return `
  <div class="page-head">
    <h1>Bake</h1>
    <button class="btn primary" data-action="new">+ Start a batch</button>
  </div>
  ${
    active.length
      ? `<div class="batch-grid">${active.map(card).join('')}</div>`
      : empty('Nothing baking right now. Start a batch from a recipe, or here. You can run several batches at once, each with its own timers.')
  }
  ${
    done.length
      ? `<section class="card"><h2>Finished</h2>${done
          .map(
            (b) => `<a class="row-link" href="#/batch/${b.id}" style="--c:${b.color}">
          <span><span class="dot"></span> ${esc(b.label)} · ${esc(b.recipe.name)}</span>
          <span class="muted">${fmtDate(b.createdAt)}${b.result?.overall ? ` · ★ ${b.result.overall}/5` : ' · not rated yet'}</span>
        </a>`,
          )
          .join('')}</section>`
      : ''
  }`;
}

function card(b) {
  const s = b.recipe.steps[b.current];
  const next = b.recipe.steps[b.current + 1];
  const timers = liveTimers(b);
  const started = b.log[s?.id]?.startedAt;
  return `
  <section class="card batch-card" style="--c:${b.color}">
    <div class="batch-top">
      <span class="dot big"></span>
      <div><h2>${esc(b.label)}</h2><div class="muted">${esc(b.recipe.name)} · ${Math.round(flourTotal(b.recipe) * b.factor)} g flour</div></div>
    </div>
    <div class="progress" aria-label="Step ${b.current + 1} of ${b.recipe.steps.length}"><span style="width:${(b.current / b.recipe.steps.length) * 100}%"></span></div>
    <div class="now">
      <div class="muted small">Step ${b.current + 1} of ${b.recipe.steps.length}${started ? ` · <span data-elapsed="${started}">${fmtClock(Date.now() - started)}</span> in this step` : ''}</div>
      <div class="now-title">${esc(s?.title || '')}</div>
      ${s?.check ? `<div class="cue">✔ ${esc(s.check)}</div>` : ''}
    </div>
    ${timers.map((t) => timerChip(b, t)).join('')}
    <div class="muted small">${etaText(b)}</div>
    <div class="btn-row">
      <a class="btn primary" href="#/cook/${b.id}">Cook mode</a>
      <button class="btn" data-action="next" data-b="${b.id}">✓ Done${next ? ` → ${esc(next.title)}` : ''}</button>
      <a class="btn ghost" href="#/batch/${b.id}">Details</a>
    </div>
  </section>`;
}

export const actions = {
  new() {
    const list = recipes();
    if (!list.length) return toast('Create a recipe first');
    openModal(
      'Start a batch',
      `<form data-submit="start">
        <label class="field"><span>Recipe</span><select name="recipe" data-change="pick-recipe">${list
          .map((r) => `<option value="${r.id}">${esc(r.name)}${alertLevel(analyze(r)) === 'read' ? ' ⚠' : ''}</option>`)
          .join('')}</select></label>
        <div id="start-alerts">${startAlerts(list[0])}</div>
        <label class="field"><span>Name</span><input name="label" value="${esc(nextBatchLabel())}"></label>
        <label class="field"><span>Scale</span><select name="mult">
          ${[0.5, 1, 1.5, 2, 3].map((m) => `<option value="${m}" ${m === 1 ? 'selected' : ''}>${m}× recipe</option>`).join('')}
        </select></label>
        <div class="btn-row end"><button type="button" class="btn" data-action="modal-close">Cancel</button><button class="btn primary" data-needs-ack ${
          alertLevel(analyze(list[0])) === 'read' ? 'disabled' : ''
        }>Start and open cook mode</button></div>
      </form>`,
    );
  },
  next(el) {
    const b = store.state.batches[el.dataset.b];
    if (b) completeStep(b);
    bus.render();
  },
};

export const changes = {
  'pick-recipe'(el) {
    const r = store.state.recipes[el.value];
    document.getElementById('start-alerts').innerHTML = startAlerts(r);
    const btn = el.closest('form').querySelector('[data-needs-ack]');
    btn.disabled = alertLevel(analyze(r)) === 'read';
  },
  ack(el) {
    const btn = el.closest('form')?.querySelector('[data-needs-ack]');
    if (btn) btn.disabled = !el.checked;
  },
};

export const submits = {
  start(form) {
    const fd = new FormData(form);
    const r = store.state.recipes[fd.get('recipe')];
    const b = startBatch(r, { factor: +fd.get('mult') || 1, label: String(fd.get('label') || '').trim() });
    closeModal();
    location.hash = `#/cook/${b.id}`;
  },
};
