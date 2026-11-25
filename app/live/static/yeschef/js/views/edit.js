// Recipe editor. Works on a draft copy; nothing is saved until you press Save.
import { esc, uid, toast, bus } from '../ui.js';
import { store, saveRecipe } from '../store.js';
import { KINDS, flourTotal, hydration } from '../units.js';
import { newStep } from '../model.js';
import { empty } from '../components.js';

let draft = null;
let dirty = false;

export const title = () => 'Edit recipe';
export const isBusy = () => dirty;

function ensureDraft(id) {
  if (!draft || draft.id !== id) {
    const r = store.state.recipes[id];
    draft = r ? structuredClone(r) : null;
    dirty = false;
  }
  return draft;
}

export function unmount() {
  if (dirty && draft && confirm('Save your changes to this recipe before leaving?')) saveRecipe(draft);
  draft = null;
  dirty = false;
}

export function render([id]) {
  const r = ensureDraft(id);
  if (!r) return empty('Recipe not found.', '<a class="btn" href="#/recipes">Back</a>');
  const kindOpts = (k) => Object.entries(KINDS).map(([v, o]) => `<option value="${v}" ${v === k ? 'selected' : ''}>${o.label}</option>`).join('');

  return `
  <div class="page-head sticky-head">
    <div><a class="back" href="#/recipe/${r.id}">← Back</a><h1>Edit recipe</h1></div>
    <div class="btn-row"><button class="btn" data-action="cancel">Cancel</button><button class="btn primary" data-action="save">Save</button></div>
  </div>

  <section class="card form-grid">
    <label class="field span-2"><span>Name</span><input value="${esc(r.name)}" data-input="field" data-f="name"></label>
    <label class="field"><span>Tags (comma separated)</span><input value="${esc((r.tags || []).join(', '))}" data-input="tags"></label>
    <label class="field"><span>Yield</span><input value="${esc(r.yieldNote || '')}" data-input="field" data-f="yieldNote" placeholder="2 long loaves"></label>
    <label class="field"><span>Dough per loaf (g)</span><input type="number" inputmode="numeric" value="${r.loafWeight || 500}" data-input="num" data-f="loafWeight"></label>
    ${
      r.parentId
        ? `<label class="field span-2"><span>What this version tests</span><textarea rows="2" data-input="field" data-f="hypothesis">${esc(r.hypothesis || '')}</textarea></label>`
        : ''
    }
    <label class="field span-2"><span>Notes</span><textarea rows="2" data-input="field" data-f="notes">${esc(r.notes || '')}</textarea></label>
  </section>

  <section class="card">
    <div class="card-head"><h2>Ingredients</h2><span class="muted" id="edit-stats">${stats(r)}</span></div>
    <p class="muted small">Amounts in grams for the base recipe. Tick “Flour” for every flour so baker's percentages are right.</p>
    <div class="edit-list">
      ${r.ingredients
        .map(
          (i, n) => `<div class="edit-row ing">
        <input class="grow" value="${esc(i.name)}" data-input="ing" data-i="${n}" data-f="name" aria-label="Ingredient name">
        <span class="inline-input"><input type="number" inputmode="decimal" step="any" min="0" value="${i.grams}" data-input="ing-num" data-i="${n}" data-f="grams" aria-label="Grams"><span>g</span></span>
        <select data-change="ing-kind" data-i="${n}" aria-label="Kind">${kindOpts(i.kind)}</select>
        <label class="mini"><input type="checkbox" ${i.flour ? 'checked' : ''} data-change="ing-bool" data-i="${n}" data-f="flour"> Flour</label>
        <label class="mini"><input type="checkbox" ${i.optional ? 'checked' : ''} data-change="ing-bool" data-i="${n}" data-f="optional"> Optional</label>
        <input class="note" value="${esc(i.note || '')}" placeholder="Note" data-input="ing" data-i="${n}" data-f="note" aria-label="Note">
        <span class="row-btns">
          <button class="icon-btn" data-action="move" data-list="ingredients" data-i="${n}" data-d="-1" aria-label="Move up">↑</button>
          <button class="icon-btn" data-action="move" data-list="ingredients" data-i="${n}" data-d="1" aria-label="Move down">↓</button>
          <button class="icon-btn danger" data-action="remove" data-list="ingredients" data-i="${n}" aria-label="Remove">✕</button>
        </span>
      </div>`,
        )
        .join('')}
    </div>
    <button class="btn" data-action="add-ing">+ Add ingredient</button>
  </section>

  <section class="card">
    <h2>Steps</h2>
    <p class="muted small"><strong>Wait</strong> and <strong>Oven</strong> steps start their timer automatically during a bake. <strong>Hands-on</strong> steps with minutes get a Start button.</p>
    <div class="edit-list">
      ${r.steps
        .map(
          (s, n) => `<div class="edit-row step">
        <span class="step-num">${n + 1}</span>
        <div class="step-fields">
          <input class="grow" value="${esc(s.title)}" data-input="step" data-i="${n}" data-f="title" aria-label="Step title">
          <textarea rows="2" data-input="step" data-i="${n}" data-f="detail" aria-label="Instructions" placeholder="Instructions">${esc(s.detail)}</textarea>
          <div class="step-opts">
            <select data-change="step-sel" data-i="${n}" data-f="type" aria-label="Step type">
              ${[
                ['active', 'Hands-on'],
                ['wait', 'Wait'],
                ['bake', 'Oven'],
              ]
                .map(([v, l]) => `<option value="${v}" ${s.type === v ? 'selected' : ''}>${l}</option>`)
                .join('')}
            </select>
            <span class="inline-input"><input type="number" inputmode="numeric" min="0" value="${s.minutes ?? ''}" data-input="step-num" data-i="${n}" data-f="minutes" aria-label="Timer minutes"><span>min</span></span>
            <span class="inline-input"><span>to</span><input type="number" inputmode="numeric" min="0" value="${s.maxMinutes ?? ''}" data-input="step-num" data-i="${n}" data-f="maxMinutes" aria-label="Maximum minutes"><span>min</span></span>
            ${!s.minutes ? `<span class="inline-input"><span>takes ~</span><input type="number" inputmode="numeric" min="0" value="${s.est ?? 5}" data-input="step-num" data-i="${n}" data-f="est" aria-label="Estimated minutes"><span>min</span></span>` : ''}
            <label class="mini"><input type="checkbox" ${s.optional ? 'checked' : ''} data-change="step-bool" data-i="${n}" data-f="optional"> Optional</label>
          </div>
          <input value="${esc(s.check || '')}" placeholder="How to tell it's ready (e.g. doubled, 208°F inside)" data-input="step" data-i="${n}" data-f="check" aria-label="Readiness cue">
        </div>
        <span class="row-btns col">
          <button class="icon-btn" data-action="move" data-list="steps" data-i="${n}" data-d="-1" aria-label="Move up">↑</button>
          <button class="icon-btn" data-action="move" data-list="steps" data-i="${n}" data-d="1" aria-label="Move down">↓</button>
          <button class="icon-btn danger" data-action="remove" data-list="steps" data-i="${n}" aria-label="Remove">✕</button>
        </span>
      </div>`,
        )
        .join('')}
    </div>
    <button class="btn" data-action="add-step">+ Add step</button>
  </section>

  <div class="btn-row end"><button class="btn" data-action="cancel">Cancel</button><button class="btn primary" data-action="save">Save</button></div>`;
}

const stats = (r) => `${Math.round(flourTotal(r))} g flour · ${hydration(r).toFixed(1)}% hydration`;
const mark = () => {
  dirty = true;
  const s = document.getElementById('edit-stats');
  if (s && draft) s.textContent = stats(draft);
};
const numOrNull = (v) => (v === '' || v == null ? null : Math.max(0, parseFloat(v)));

export const inputs = {
  field(el) {
    draft[el.dataset.f] = el.value;
    mark();
  },
  num(el) {
    draft[el.dataset.f] = numOrNull(el.value);
    mark();
  },
  tags(el) {
    draft.tags = el.value.split(',').map((t) => t.trim()).filter(Boolean);
    mark();
  },
  ing(el) {
    draft.ingredients[+el.dataset.i][el.dataset.f] = el.value;
    mark();
  },
  'ing-num'(el) {
    draft.ingredients[+el.dataset.i][el.dataset.f] = numOrNull(el.value) ?? 0;
    mark();
  },
  step(el) {
    draft.steps[+el.dataset.i][el.dataset.f] = el.value;
    mark();
  },
  'step-num'(el) {
    draft.steps[+el.dataset.i][el.dataset.f] = numOrNull(el.value);
    mark();
  },
};

export const changes = {
  'ing-kind'(el) {
    const i = draft.ingredients[+el.dataset.i];
    i.kind = el.value;
    i.flour = el.value === 'flour';
    mark();
    bus.render();
  },
  'ing-bool'(el) {
    draft.ingredients[+el.dataset.i][el.dataset.f] = el.checked;
    mark();
  },
  'step-sel'(el) {
    draft.steps[+el.dataset.i][el.dataset.f] = el.value;
    mark();
  },
  'step-bool'(el) {
    draft.steps[+el.dataset.i][el.dataset.f] = el.checked;
    mark();
  },
};

export const actions = {
  'add-ing'() {
    draft.ingredients.push({ id: uid('i'), name: '', grams: 0, kind: 'other', flour: false });
    mark();
    bus.render();
    const rows = document.querySelectorAll('.edit-row.ing input.grow');
    rows[rows.length - 1]?.focus();
  },
  'add-step'() {
    draft.steps.push(newStep());
    mark();
    bus.render();
    const rows = document.querySelectorAll('.edit-row.step input.grow');
    rows[rows.length - 1]?.select();
  },
  move(el) {
    const list = draft[el.dataset.list];
    const i = +el.dataset.i;
    const j = i + +el.dataset.d;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    mark();
    bus.render();
  },
  remove(el) {
    draft[el.dataset.list].splice(+el.dataset.i, 1);
    mark();
    bus.render();
  },
  save() {
    if (!draft.name.trim()) return toast('Give the recipe a name');
    draft.ingredients = draft.ingredients.filter((i) => i.name.trim());
    for (const s of draft.steps) {
      if (s.maxMinutes && s.minutes && s.maxMinutes < s.minutes) s.maxMinutes = s.minutes;
      if (!s.minutes) s.maxMinutes = null;
    }
    saveRecipe(draft);
    const id = draft.id;
    dirty = false;
    draft = null;
    toast('Saved');
    location.hash = `#/recipe/${id}`;
  },
  cancel() {
    const id = draft.id;
    dirty = false;
    draft = null;
    location.hash = `#/recipe/${id}`;
  },
};
