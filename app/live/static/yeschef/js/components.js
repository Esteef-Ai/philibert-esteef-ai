// Pieces of UI shared by several views.
import { esc, fmtClock, fmtTime } from './ui.js';
import { timerRemaining, isRinging, liveTimers, eta } from './model.js';
import { fmtAmount, pct } from './units.js';
import { prefs } from './store.js';
export { analyze, alertLevel } from './alerts.js';

export function timerChip(b, t, { big = false, controls = true } = {}) {
  const rem = timerRemaining(t);
  const ring = isRinging(t);
  return `
  <div class="timer ${big ? 'big' : ''} ${ring ? 'ringing' : ''} ${t.state}" style="--c:${b.color}" data-timer-wrap="${t.id}">
    <div class="timer-main">
      <span class="timer-label">${esc(t.label)}</span>
      <span class="timer-clock" data-timer="${t.id}" data-batch="${b.id}">${fmtClock(rem)}</span>
    </div>
    ${
      controls
        ? `<div class="timer-ctl">
      ${
        ring
          ? `<button class="btn small primary" data-action="timer" data-op="dismiss" data-b="${b.id}" data-t="${t.id}">Done</button>
             <button class="btn small" data-action="timer" data-op="add" data-arg="5" data-b="${b.id}" data-t="${t.id}">+5</button>`
          : `${
              t.state === 'paused'
                ? `<button class="btn small" data-action="timer" data-op="resume" data-b="${b.id}" data-t="${t.id}" aria-label="Resume">▶</button>`
                : `<button class="btn small" data-action="timer" data-op="pause" data-b="${b.id}" data-t="${t.id}" aria-label="Pause">❚❚</button>`
            }
             <button class="btn small" data-action="timer" data-op="add" data-arg="1" data-b="${b.id}" data-t="${t.id}">+1</button>
             <button class="btn small" data-action="timer" data-op="add" data-arg="5" data-b="${b.id}" data-t="${t.id}">+5</button>
             <button class="btn small ghost" data-action="timer" data-op="dismiss" data-b="${b.id}" data-t="${t.id}" aria-label="Stop timer">✕</button>`
      }
    </div>`
        : ''
    }
  </div>`;
}

export function timerBar(items) {
  if (!items.length) return '';
  return `<div class="timerbar-inner">${items
    .map(
      ({ b, t }) => `
    <a class="tb-item ${isRinging(t) ? 'ringing' : ''} ${t.state}" href="#/cook/${b.id}" style="--c:${b.color}">
      <span class="dot"></span><span class="tb-batch">${esc(b.label)}</span>
      <span class="tb-label">${esc(t.label)}</span>
      <span class="tb-clock" data-timer="${t.id}" data-batch="${b.id}">${fmtClock(timerRemaining(t))}</span>
    </a>`,
    )
    .join('')}</div>`;
}

export function etaText(b) {
  const e = eta(b);
  if (!e) return '';
  return `<span data-eta="${b.id}">${e.ovenOut ? `Out of oven ~${fmtTime(e.ovenOut)} · ` : ''}All done ~${fmtTime(e.done)}</span>`;
}

export function ingredientList(recipe, factor, { checkable = false, checked = {}, batchId = '' } = {}) {
  return `<ul class="ing-list">${recipe.ingredients
    .map((i) => {
      const g = (+i.grams || 0) * factor;
      const amt = g ? fmtAmount(g, i.kind, prefs.units) : esc(i.note || '—');
      const on = checked[i.id];
      return `<li class="${on ? 'checked' : ''}">
        ${checkable ? `<button class="check ${on ? 'on' : ''}" data-action="check-ing" data-b="${batchId}" data-id="${i.id}" aria-label="Measured ${esc(i.name)}">${on ? '✓' : ''}</button>` : ''}
        <span class="ing-name">${esc(i.name)}${i.optional ? ' <span class="muted">(optional)</span>' : ''}</span>
        <span class="ing-amt">${amt}</span>
        ${prefs.showPercent && i.grams ? `<span class="ing-pct">${pct(recipe, i.grams).toFixed(1)}%</span>` : ''}
      </li>`;
    })
    .join('')}</ul>`;
}

export function unitToggle() {
  const u = prefs.units;
  return `<div class="seg" role="group" aria-label="Units">
    ${[
      ['g', 'Grams'],
      ['oz', 'Ounces'],
      ['vol', 'Cups/spoons'],
    ]
      .map(([k, l]) => `<button class="${u === k ? 'on' : ''}" data-action="units" data-u="${k}">${l}</button>`)
      .join('')}
  </div>`;
}

export function stepTypeBadge(s) {
  const map = { active: ['Hands-on', 'b-active'], wait: ['Wait', 'b-wait'], bake: ['Oven', 'b-bake'] };
  const [l, c] = map[s.type] || map.active;
  return `<span class="badge ${c}">${l}</span>`;
}

export const empty = (msg, action = '') => `<div class="empty"><p>${msg}</p>${action}</div>`;

// ---------- MUST READ / MUST CHECK ----------
export function alertBadge(level, small = false) {
  if (!level) return '';
  return `<span class="badge ${level === 'read' ? 'b-read' : 'b-check'}${small ? '' : ' big-badge'}">${level === 'read' ? '⚠ MUST READ' : '☑ MUST CHECK'}</span>`;
}

export function alertItem(a, recipe) {
  const idx = recipe ? recipe.steps.findIndex((s) => s.id === a.stepId) : -1;
  return `<li class="alert alert-${a.level}">
    <span class="badge ${a.level === 'read' ? 'b-read' : 'b-check'}">${a.level === 'read' ? 'MUST READ' : 'MUST CHECK'}</span>
    <div><strong>${esc(a.title)}</strong>${idx >= 0 ? ` <span class="muted small">· step ${idx + 1}</span>` : ''}<div>${esc(a.text)}</div></div>
  </li>`;
}

export function alertsPanel(alerts, recipe, { heading = 'Before you start', collapsedChecks = false } = {}) {
  if (!alerts.length) return '';
  const reads = alerts.filter((a) => a.level === 'read');
  const checks = alerts.filter((a) => a.level === 'check');
  return `<section class="card alerts-card ${reads.length ? 'has-read' : ''}">
    <div class="card-head"><h2>${esc(heading)}</h2><span>${alertBadge(reads.length ? 'read' : 'check')}</span></div>
    <p class="muted small">Found by reading the whole recipe ahead: things that are easy to miss if you go one step at a time.</p>
    <ul class="alerts">${reads.map((a) => alertItem(a, recipe)).join('')}</ul>
    ${
      checks.length
        ? collapsedChecks
          ? `<details><summary>${checks.length} thing${checks.length > 1 ? 's' : ''} to check</summary><ul class="alerts">${checks.map((a) => alertItem(a, recipe)).join('')}</ul></details>`
          : `<ul class="alerts">${checks.map((a) => alertItem(a, recipe)).join('')}</ul>`
        : ''
    }
  </section>`;
}

export function liveTimersOf(b) {
  return liveTimers(b);
}
