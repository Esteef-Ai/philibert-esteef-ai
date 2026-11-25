// Recipe library: each recipe family with its test forks shown as a tree.
import { esc } from '../ui.js';
import { recipes, family, avgRatings, newRecipe, activeBatches } from '../model.js';
import { saveRecipe } from '../store.js';
import { flourTotal, hydration } from '../units.js';
import { etaText, empty, alertBadge, alertLevel, analyze } from '../components.js';

export const title = () => 'Recipes';

const starTxt = (v) => (v ? `★ ${v.toFixed(1)}` : '');

function item({ r, depth }) {
  const avg = avgRatings(r.id);
  return `
  <a class="tree-item" href="#/recipe/${r.id}" style="--depth:${depth}">
    ${depth ? '<span class="branch" aria-hidden="true">└</span>' : ''}
    <span class="ti-main">
      <span class="ti-name">${esc(r.name)} ${alertBadge(alertLevel(analyze(r)), true)}</span>
      <span class="ti-meta">${Math.round(flourTotal(r))} g flour · ${hydration(r).toFixed(0)}% water${
        avg ? ` · ${avg.n} bake${avg.n > 1 ? 's' : ''} ${starTxt(avg.overall)}` : ''
      }</span>
      ${r.hypothesis ? `<span class="ti-hyp">${esc(r.hypothesis)}</span>` : ''}
    </span>
    <span class="tags">${(r.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</span>
  </a>`;
}

export function render() {
  const roots = recipes().filter((r) => !r.parentId || !recipes().some((x) => x.id === r.parentId));
  const active = activeBatches();
  return `
  <div class="page-head">
    <h1>Recipes</h1>
    <div class="btn-row">
      <a class="btn primary" href="#/import">⤓ Import from link, PDF or photo</a>
      <button class="btn" data-action="new">+ New recipe</button>
    </div>
  </div>
  ${
    active.length
      ? `<section class="card active-strip">
      <h2>Baking now</h2>
      ${active
        .map(
          (b) => `<a class="batch-line" href="#/cook/${b.id}" style="--c:${b.color}"><span class="dot"></span>
          <strong>${esc(b.label)}</strong> ${esc(b.recipe.name)} · step ${b.current + 1}/${b.recipe.steps.length}: ${esc(b.recipe.steps[b.current]?.title || '')}
          <span class="muted"> · ${etaText(b)}</span></a>`,
        )
        .join('')}
    </section>`
      : ''
  }
  ${
    roots.length
      ? roots
          .map(
            (root) => `<section class="card family">
        ${family(root.id).map(item).join('')}
      </section>`,
          )
          .join('')
      : empty('No recipes yet.', '<button class="btn primary" data-action="new">Create your first recipe</button>')
  }`;
}

export const actions = {
  new() {
    const r = newRecipe();
    saveRecipe(r);
    location.hash = `#/edit/${r.id}`;
  },
};
