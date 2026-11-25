// One recipe: scaling (auto-scale from any ingredient), units, steps, forks, troubleshooting, history.
import { esc, openModal, closeModal, setModalBody, toast, minutesLabel, fmtDate, bus } from '../ui.js';
import { store, prefs, setPref, saveRecipe, deleteRecipe } from '../store.js';
import { flourTotal, doughTotal, hydration, pct, fmtAmount, fmtGrams, editValue, editUnit, toGrams, KINDS } from '../units.js';
import { forkRecipe, diffRecipes, startBatch, bakesOf, nextBatchLabel, children, rootOf } from '../model.js';
import { unitToggle, stepTypeBadge, empty, alertsPanel, alertItem, analyze } from '../components.js';
import { PROBLEMS, SCENARIOS, scenariosFor } from '../scenarios.js';

const viewState = {}; // per recipe: { factor, loaves }
const vs = (id) => (viewState[id] ??= { factor: 1, loaves: 2 });

const get = (id) => store.state.recipes[id];

export const title = ([id]) => get(id)?.name || 'Recipe';

export function render([id]) {
  const r = get(id);
  if (!r) return empty('Recipe not found.', '<a class="btn" href="#/recipes">Back to recipes</a>');
  const s = vs(id);
  const f = s.factor;
  const parent = r.parentId && get(r.parentId);
  const kids = children(r.id);
  const baseFlour = flourTotal(r);
  const units = prefs.units;
  const history = bakesOf(r.id);
  const loafW = r.loafWeight || 500;

  return `
  <div class="page-head">
    <div>
      <a class="back" href="#/recipes">← Recipes</a>
      <h1>${esc(r.name)}</h1>
      ${parent ? `<p class="muted">Test fork of <a href="#/recipe/${parent.id}">${esc(parent.name)}</a></p>` : ''}
      <div class="tags">${(r.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>
    </div>
    <div class="head-actions">
      <button class="btn primary big-touch" data-action="start">▶ Start a batch</button>
    </div>
  </div>

  <div class="btn-row">
    <a class="btn" href="#/edit/${r.id}">✎ Edit</a>
    <button class="btn" data-action="fork">⑂ Fork to test a change</button>
    <button class="btn" data-action="troubleshoot">🩺 Troubleshoot</button>
    <a class="btn" href="#/tests/${rootOf(r).id}">🧪 Compare family</a>
    <button class="btn ghost danger" data-action="delete">Delete</button>
  </div>

  ${r.hypothesis ? `<div class="callout"><strong>What this version tests:</strong> ${esc(r.hypothesis)}</div>` : ''}
  ${r.notes ? `<div class="callout soft pre">${esc(r.notes)}</div>` : ''}
  ${r.source?.url ? `<p class="muted small">Imported from <a href="${esc(r.source.url)}" target="_blank" rel="noopener">${esc(r.source.site || r.source.url)}</a></p>` : r.source?.name ? `<p class="muted small">Imported from ${esc(r.source.name)}</p>` : ''}
  ${alertsPanel(analyze(r), r, { collapsedChecks: !analyze(r).some((a) => a.level === 'read') })}

  <div class="grid-2">
    <section class="card">
      <div class="card-head">
        <h2>Ingredients</h2>
        ${unitToggle()}
      </div>

      <div class="scale-box">
        <div class="scale-row">
          <span class="lbl">Scale</span>
          <div class="chips">
            ${[0.5, 1, 1.5, 2, 3]
              .map((m) => `<button class="chip ${Math.abs(f - m) < 0.001 ? 'on' : ''}" data-action="mult" data-m="${m}">${m === 0.5 ? '½' : m === 1.5 ? '1½' : m}×</button>`)
              .join('')}
          </div>
        </div>
        <div class="scale-row">
          <label class="lbl" for="flourTotal">Total flour</label>
          <span class="inline-input"><input id="flourTotal" type="number" inputmode="decimal" min="1" step="any" value="${Math.round(baseFlour * f)}" data-change="flour"><span>g</span></span>
        </div>
        <div class="scale-row">
          <label class="lbl" for="loaves">Loaves</label>
          <span class="inline-input"><input id="loaves" type="number" inputmode="numeric" min="1" step="1" value="${s.loaves}" data-change="loaves"><span>×</span></span>
          <span class="inline-input"><input aria-label="Loaf weight in grams" type="number" inputmode="numeric" min="50" step="10" value="${loafW}" data-change="loafw"><span>g dough each</span></span>
          <button class="btn small" data-action="fit-loaves">Fit</button>
        </div>
        <label class="toggle">
          <input type="checkbox" ${prefs.autoScale ? 'checked' : ''} data-change="autoscale">
          <span><strong>Auto-scale</strong> — changing any amount below rescales the whole recipe. Off: the change edits the formula.</span>
        </label>
      </div>

      <table class="ing-table">
        <thead><tr><th>Ingredient</th><th class="num">Amount</th><th class="num">Baker's %</th></tr></thead>
        <tbody>
        ${r.ingredients
          .map((i) => {
            const g = (+i.grams || 0) * f;
            return `<tr>
            <td>${esc(i.name)}${i.optional ? ' <span class="muted">(optional)</span>' : ''}${i.note && i.grams ? `<div class="muted small">${esc(i.note)}</div>` : ''}</td>
            <td class="num">
              ${
                i.grams
                  ? `<span class="inline-input amt"><input type="number" inputmode="decimal" step="any" min="0" value="${editValue(g, i.kind, units)}" data-change="amt" data-id="${i.id}" aria-label="${esc(i.name)} amount"><span>${editUnit(g, i.kind, units)}</span></span>
                     ${units !== 'g' ? `<div class="muted small">${units === 'vol' ? fmtAmount(g, i.kind, 'vol') + ' · ' : ''}${fmtGrams(g)}</div>` : ''}`
                  : `<span class="muted">${esc(i.note || '—')}</span>`
              }
            </td>
            <td class="num">${i.grams ? pct(r, i.grams).toFixed(1) + '%' : ''}</td>
          </tr>`;
          })
          .join('')}
        </tbody>
        <tfoot>
          <tr><td>Total dough</td><td class="num">${fmtAmount(doughTotal(r) * f, 'other', units === 'vol' ? 'g' : units)}</td><td class="num">${(
            (doughTotal(r) / (baseFlour || 1)) *
            100
          ).toFixed(0)}%</td></tr>
          <tr><td>Hydration</td><td></td><td class="num">${hydration(r).toFixed(1)}%</td></tr>
        </tfoot>
      </table>
      ${units === 'vol' ? '<p class="muted small">Cup and spoon amounts are approximate. Weigh when you can.</p>' : ''}
    </section>

    <section class="card">
      <h2>Steps</h2>
      <ol class="steps">
        ${r.steps
          .map(
            (st, n) => `${st.section && st.section !== r.steps[n - 1]?.section ? `<li class="section-head">${esc(st.section)}</li>` : ''}<li>
            <div class="step-head"><strong>${esc(st.title)}</strong> ${stepTypeBadge(st)} ${st.minutes ? `<span class="badge b-time">⏱ ${minutesLabel(st)}</span>` : ''} ${
              st.optional ? '<span class="muted small">optional</span>' : ''
            }</div>
            <div>${esc(st.detail)}</div>
            ${st.check ? `<div class="cue">✔ ${esc(st.check)}</div>` : ''}
          </li>`,
          )
          .join('')}
      </ol>
    </section>
  </div>

  ${parent ? changesCard(parent, r) : ''}

  ${
    kids.length
      ? `<section class="card"><h2>Forks of this recipe</h2>${kids
          .map((k) => `<a class="row-link" href="#/recipe/${k.id}">${esc(k.name)}<span class="muted">${esc(k.hypothesis || '')}</span></a>`)
          .join('')}</section>`
      : ''
  }

  <section class="card">
    <h2>Bake history</h2>
    ${
      history.length
        ? history
            .map(
              (b) => `<a class="row-link" href="#/batch/${b.id}">
          <span>${fmtDate(b.createdAt)} · ${esc(b.label)}</span>
          <span>Crumb ${b.result.crumb || '–'}/5 · Crust ${b.result.crust || '–'}/5 · Overall ${b.result.overall || '–'}/5</span>
          ${b.result.notes ? `<span class="muted">${esc(b.result.notes)}</span>` : ''}
        </a>`,
            )
            .join('')
        : '<p class="muted">No rated bakes yet. Start a batch, then rate it when it is done.</p>'
    }
  </section>`;
}

function changesCard(parent, r) {
  const ch = diffRecipes(parent, r);
  return `<section class="card">
    <h2>Changes from “${esc(parent.name)}”</h2>
    ${
      ch.length
        ? `<ul class="changes">${ch.map((c) => `<li class="ch-${c.kind}">${esc(c.text)}</li>`).join('')}</ul>`
        : '<p class="muted">No differences yet. Edit this fork to make the change you want to test.</p>'
    }
  </section>`;
}

// ---------- scaling ----------
const rerender = () => bus.render();

export const changes = {
  ack(el) {
    const btn = el.closest('form')?.querySelector('[data-needs-ack]');
    if (btn) btn.disabled = !el.checked;
  },
  flour(el, _e, [id]) {
    const r = get(id);
    const v = parseFloat(el.value);
    if (!(v > 0) || !flourTotal(r)) return;
    vs(id).factor = v / flourTotal(r);
    rerender();
  },
  loaves(el, _e, [id]) {
    vs(id).loaves = Math.max(1, parseInt(el.value) || 1);
    fitLoaves(id);
  },
  loafw(el, _e, [id]) {
    const r = get(id);
    const w = Math.max(50, parseFloat(el.value) || 500);
    r.loafWeight = w;
    saveRecipe(r);
    fitLoaves(id);
  },
  autoscale(el) {
    setPref('autoScale', el.checked);
    rerender();
  },
  amt(el, _e, [id]) {
    const r = get(id);
    const ing = r.ingredients.find((i) => i.id === el.dataset.id);
    if (!ing) return;
    const f = vs(id).factor;
    const current = ing.grams * f;
    const g = toGrams(el.value, ing.kind, prefs.units, current);
    if (!(g >= 0)) return rerender();
    if (prefs.autoScale) {
      if (!ing.grams) return rerender();
      vs(id).factor = g / ing.grams;
      toast(`Scaled to ${Math.round(vs(id).factor * 100)}% — everything adjusted`);
    } else {
      ing.grams = g / f;
      saveRecipe(r);
      toast(`${ing.name} changed in the recipe formula`);
    }
    rerender();
  },
};

function fitLoaves(id) {
  const r = get(id);
  const target = vs(id).loaves * (r.loafWeight || 500);
  const total = doughTotal(r);
  if (total) vs(id).factor = target / total;
  rerender();
}

// ---------- actions ----------
export const actions = {
  mult(el, _e, [id]) {
    vs(id).factor = +el.dataset.m;
    rerender();
  },
  'fit-loaves': (_el, _e, [id]) => fitLoaves(id),

  start(_el, _e, [id]) {
    const r = get(id);
    const f = vs(id).factor;
    openModal(
      'Start a batch',
      `<form data-submit="start">
        ${startAlerts(r)}
        <label class="field"><span>Name</span><input name="label" value="${esc(nextBatchLabel())}"></label>
        <label class="field"><span>Total flour (g)</span><input name="flour" type="number" inputmode="decimal" step="any" min="1" value="${Math.round(flourTotal(r) * f)}"></label>
        <p class="muted small">That makes about ${Math.round(doughTotal(r) * f)} g of dough. You can run several batches at once; each gets its own color and timers.</p>
        <label class="field"><span>Notes (optional)</span><textarea name="notes" rows="2" placeholder="Room temperature, flour brand…"></textarea></label>
        <div class="btn-row end"><button type="button" class="btn" data-action="modal-close">Cancel</button><button class="btn primary" ${
          analyze(r).some((a) => a.level === 'read') ? 'disabled data-needs-ack' : ''
        }>Start and open cook mode</button></div>
      </form>`,
    );
  },

  fork(_el, _e, [id]) {
    const r = get(id);
    openModal(
      'Fork to test a change',
      `<form data-submit="fork">
        <p class="muted">A fork is a copy you change in one way, so you can bake it and compare it with the original.</p>
        <label class="field"><span>Name</span><input name="name" value="${esc(r.name)} · test"></label>
        <label class="field"><span>What are you testing?</span><textarea name="hypothesis" rows="3" placeholder="e.g. 70 min final proof will open the crumb"></textarea></label>
        <div class="btn-row end"><button type="button" class="btn" data-action="modal-close">Cancel</button><button class="btn primary">Create fork and edit</button></div>
      </form>`,
    );
  },

  troubleshoot(_el, _e, [id]) {
    tsState.problems = [];
    openModal('Troubleshoot', troubleshootBody(get(id)), { wide: true });
  },
  'ts-problem'(el, _e, [id]) {
    const p = el.dataset.p;
    tsState.problems = tsState.problems.includes(p) ? tsState.problems.filter((x) => x !== p) : [...tsState.problems, p];
    setModalBody(troubleshootBody(get(id)));
  },
  'ts-apply'(el, _e, [id]) {
    const fork = applyScenario(get(id), el.dataset.s);
    closeModal();
    toast('Test fork created');
    location.hash = `#/recipe/${fork.id}`;
  },

  delete(_el, _e, [id]) {
    const r = get(id);
    const kids = children(id);
    if (!confirm(`Delete “${r.name}”?${kids.length ? ` Its ${kids.length} fork(s) will move up to its parent.` : ''} Past batches keep their own copy.`)) return;
    for (const k of kids) {
      k.parentId = r.parentId || null;
      saveRecipe(k);
    }
    deleteRecipe(id);
    location.hash = r.parentId ? `#/recipe/${r.parentId}` : '#/recipes';
  },
};

export const submits = {
  start(form, _e, [id]) {
    const r = get(id);
    const fd = new FormData(form);
    const flour = parseFloat(fd.get('flour'));
    const b = startBatch(r, {
      factor: flour > 0 && flourTotal(r) ? flour / flourTotal(r) : 1,
      label: String(fd.get('label') || '').trim(),
      notes: String(fd.get('notes') || ''),
    });
    closeModal();
    location.hash = `#/cook/${b.id}`;
  },
  fork(form, _e, [id]) {
    const fd = new FormData(form);
    const f = forkRecipe(get(id), { name: String(fd.get('name')).trim(), hypothesis: String(fd.get('hypothesis')).trim() });
    saveRecipe(f);
    closeModal();
    location.hash = `#/edit/${f.id}`;
  },
};

// MUST READ items must be acknowledged before a batch can start.
export function startAlerts(r) {
  const alerts = analyze(r);
  if (!alerts.length) return '';
  const reads = alerts.filter((a) => a.level === 'read');
  return `<div class="start-alerts">
    <ul class="alerts">${alerts.map((a) => alertItem(a, r)).join('')}</ul>
    ${
      reads.length
        ? `<label class="toggle ack"><input type="checkbox" data-change="ack"><span><strong>I've read the MUST READ items</strong> and planned for them.</span></label>`
        : ''
    }
  </div>`;
}

// ---------- troubleshooting ----------
const tsState = { problems: [] };

export function applyScenario(recipe, scenarioId) {
  const sc = SCENARIOS.find((s) => s.id === scenarioId);
  const fork = forkRecipe(recipe, { name: `${recipe.name} · ${sc.short}`, hypothesis: `${sc.title}. ${sc.why}` });
  sc.apply(fork);
  for (const i of fork.ingredients) i.grams = Math.round(i.grams * 10) / 10;
  saveRecipe(fork);
  return fork;
}

export function troubleshootBody(r, preset) {
  const problems = preset || tsState.problems;
  const list = (problems.length ? scenariosFor(problems) : SCENARIOS).filter((s) => s.can(r));
  return `
    <p class="muted">What went wrong? Each suggestion makes a fork with <strong>one</strong> change, so the next bake tells you whether it helped.</p>
    <div class="chips wrap">${PROBLEMS.map(
      (p) => `<button class="chip ${problems.includes(p.id) ? 'on' : ''}" data-action="ts-problem" data-p="${p.id}">${esc(p.label)}</button>`,
    ).join('')}</div>
    <div class="scenarios">
      ${
        list.length
          ? list
              .map(
                (s) => `<div class="scenario">
          <div><strong>${esc(s.title)}</strong><p class="muted">${esc(s.why)}</p></div>
          <button class="btn small primary" data-action="ts-apply" data-s="${s.id}" data-r="${r.id}">Create test fork</button>
        </div>`,
              )
              .join('')
          : '<p class="muted">No automatic suggestion fits this recipe. Use “Fork to test a change” and edit it by hand.</p>'
      }
    </div>`;
}

export { KINDS };
