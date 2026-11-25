// Tests: compare a recipe family (original + forks) side by side with bake ratings.
import { esc, openModal, bus } from '../ui.js';
import { store } from '../store.js';
import { recipes, family, diffRecipes, avgRatings, rootOf } from '../model.js';
import { flourTotal, hydration, pct } from '../units.js';
import { empty } from '../components.js';
import { troubleshootBody, applyScenario } from './recipe.js';

export const title = () => 'Tests';

const sel = { a: null, b: null };

export function render([rootId]) {
  const all = recipes();
  if (!all.length) return empty('No recipes yet.');
  const roots = all.filter((r) => !r.parentId || !store.state.recipes[r.parentId]);
  const root = store.state.recipes[rootId] ? rootOf(store.state.recipes[rootId]) : roots[0];
  const fam = family(root.id);
  if (!fam.some((x) => x.r.id === sel.a)) sel.a = fam[0]?.r.id;
  if (!fam.some((x) => x.r.id === sel.b)) sel.b = (fam[fam.length - 1] || fam[0]).r.id;

  return `
  <div class="page-head">
    <h1>Tests</h1>
    ${
      roots.length > 1
        ? `<label class="field inline"><span>Recipe family</span><select data-change="root">${roots
            .map((r) => `<option value="${r.id}" ${r.id === root.id ? 'selected' : ''}>${esc(r.name)}</option>`)
            .join('')}</select></label>`
        : ''
    }
  </div>
  <p class="muted">Each fork tests one change. Bake it, rate it, and keep the changes that win.</p>

  <section class="card">
    <h2>${esc(root.name)} family</h2>
    <div class="table-wrap"><table class="cmp">
      <thead><tr><th>Version</th><th>What it tests</th><th class="num">Bakes</th><th class="num">Crumb</th><th class="num">Crust</th><th class="num">Flavor</th><th class="num">Overall</th><th></th></tr></thead>
      <tbody>${fam
        .map(({ r, depth }) => {
          const a = avgRatings(r.id);
          const f = (v) => (v ? v.toFixed(1) : '–');
          const parent = r.parentId && store.state.recipes[r.parentId];
          const n = parent ? diffRecipes(parent, r).length : 0;
          return `<tr>
            <td style="padding-left:${0.6 + depth * 1.1}rem"><a href="#/recipe/${r.id}">${depth ? '└ ' : ''}${esc(r.name)}</a></td>
            <td class="muted">${esc(r.hypothesis || (depth ? '' : 'Baseline'))}${parent ? ` <span class="small">(${n} change${n === 1 ? '' : 's'})</span>` : ''}</td>
            <td class="num">${a?.n || 0}</td><td class="num">${f(a?.crumb)}</td><td class="num">${f(a?.crust)}</td><td class="num">${f(a?.flavor)}</td><td class="num"><strong>${f(a?.overall)}</strong></td>
            <td><button class="btn small" data-action="ts" data-r="${r.id}">🩺</button></td>
          </tr>`;
        })
        .join('')}</tbody>
    </table></div>
  </section>

  <section class="card">
    <div class="card-head">
      <h2>Side by side</h2>
      <div class="btn-row">
        <select data-change="pick" data-k="a" aria-label="First version">${opts(fam, sel.a)}</select>
        <span>vs</span>
        <select data-change="pick" data-k="b" aria-label="Second version">${opts(fam, sel.b)}</select>
      </div>
    </div>
    ${compare(store.state.recipes[sel.a], store.state.recipes[sel.b])}
  </section>`;
}

const opts = (fam, cur) => fam.map(({ r }) => `<option value="${r.id}" ${r.id === cur ? 'selected' : ''}>${esc(r.name)}</option>`).join('');

function compare(a, b) {
  if (!a || !b) return '';
  const names = [...new Map([...a.ingredients, ...b.ingredients].map((i) => [i.id || i.name, i])).values()];
  const find = (r, i) => r.ingredients.find((x) => (x.id || x.name) === (i.id || i.name));
  const rows = names
    .map((i) => {
      const x = find(a, i);
      const y = find(b, i);
      const px = x ? pct(a, x.grams) : null;
      const py = y ? pct(b, y.grams) : null;
      const diff = px == null || py == null ? true : Math.abs(px - py) > 0.05;
      return `<tr class="${diff ? 'diff' : ''}"><td>${esc(i.name)}</td><td class="num">${px == null ? '—' : px.toFixed(1) + '%'}</td><td class="num">${
        py == null ? '—' : py.toFixed(1) + '%'
      }</td></tr>`;
    })
    .join('');
  const changes = diffRecipes(a, b).filter((c) => c.what === 'step');
  return `
    <div class="table-wrap"><table class="cmp">
      <thead><tr><th>Baker's %</th><th class="num">${esc(a.name)}</th><th class="num">${esc(b.name)}</th></tr></thead>
      <tbody>${rows}
        <tr><td><strong>Hydration</strong></td><td class="num">${hydration(a).toFixed(1)}%</td><td class="num">${hydration(b).toFixed(1)}%</td></tr>
        <tr><td>Flour (g)</td><td class="num">${Math.round(flourTotal(a))}</td><td class="num">${Math.round(flourTotal(b))}</td></tr>
      </tbody>
    </table></div>
    ${changes.length ? `<h3>Process differences</h3><ul class="changes">${changes.map((c) => `<li class="ch-${c.kind}">${esc(c.text)}</li>`).join('')}</ul>` : ''}`;
}

export const changes = {
  root(el) {
    location.hash = `#/tests/${el.value}`;
  },
  pick(el) {
    sel[el.dataset.k] = el.value;
    bus.render();
  },
};

export const actions = {
  ts(el) {
    const r = store.state.recipes[el.dataset.r];
    probs = [];
    tsRecipe = r.id;
    openModal('Troubleshoot ' + r.name, troubleshootBody(r, probs), { wide: true });
  },
  'ts-problem'(el) {
    // reuse the recipe page's troubleshooter inside this modal
    const p = el.dataset.p;
    probs = probs.includes(p) ? probs.filter((x) => x !== p) : [...probs, p];
    document.querySelector('.modal-body').innerHTML = troubleshootBody(store.state.recipes[tsRecipe], probs);
  },
  'ts-apply'(el) {
    const f = applyScenario(store.state.recipes[el.dataset.r], el.dataset.s);
    location.hash = `#/recipe/${f.id}`;
  },
};
let tsRecipe = null;
let probs = [];
