// Ingredient kinds, baker's percentages, scaling and unit display.
// Volume figures are approximate (weights are the source of truth).
export const KINDS = {
  flour: { label: 'Flour', gPerCup: 120 },
  water: { label: 'Water', gPerCup: 236.6, liquid: true },
  milk: { label: 'Milk', gPerCup: 242, liquid: true },
  yeast: { label: 'Yeast', gPerTsp: 3.1 },
  salt: { label: 'Salt', gPerTsp: 6, volNote: 'table salt' },
  sugar: { label: 'Sugar', gPerCup: 200 },
  oil: { label: 'Oil', gPerCup: 216 },
  butter: { label: 'Butter / fat', gPerCup: 227 },
  malt: { label: 'Malt', gPerTsp: 3 },
  seeds: { label: 'Seeds', gPerTsp: 3 },
  egg: { label: 'Egg', gPerCup: 243 },
  preferment: { label: 'Pre-ferment', gPerCup: 200 },
  other: { label: 'Other', gPerCup: 200 },
};

const gPerTsp = (kind) => {
  const k = KINDS[kind] || KINDS.other;
  return k.gPerTsp || k.gPerCup / 48;
};

export function flourTotal(recipe) {
  return recipe.ingredients.filter((i) => i.flour).reduce((s, i) => s + (+i.grams || 0), 0);
}
export function doughTotal(recipe) {
  return recipe.ingredients.reduce((s, i) => s + (+i.grams || 0), 0);
}
export function hydration(recipe) {
  const f = flourTotal(recipe);
  if (!f) return 0;
  const liquid = recipe.ingredients
    .filter((i) => KINDS[i.kind]?.liquid)
    .reduce((s, i) => s + (+i.grams || 0), 0);
  return (liquid / f) * 100;
}
export const pct = (recipe, grams) => {
  const f = flourTotal(recipe);
  return f ? (grams / f) * 100 : 0;
};

// ----- formatting -----
const FRACS = [
  [0, ''],
  [0.125, '⅛'],
  [0.25, '¼'],
  [0.333, '⅓'],
  [0.375, '⅜'],
  [0.5, '½'],
  [0.625, '⅝'],
  [0.667, '⅔'],
  [0.75, '¾'],
  [0.875, '⅞'],
  [1, ''],
];
function frac(n) {
  let whole = Math.floor(n);
  const rest = n - whole;
  let best = FRACS[0];
  for (const f of FRACS) if (Math.abs(f[0] - rest) < Math.abs(best[0] - rest)) best = f;
  if (best[0] === 1) {
    whole += 1;
    best = FRACS[0];
  }
  if (!whole && !best[1]) return '0';
  return (whole ? whole + (best[1] ? ' ' : '') : '') + best[1];
}

export function fmtGrams(g) {
  if (g >= 1000) return (Math.round(g)).toLocaleString() + ' g';
  if (g >= 100) return Math.round(g) + ' g';
  if (g >= 10) return (Math.round(g * 10) / 10).toString() + ' g';
  return (Math.round(g * 100) / 100).toString() + ' g';
}

function fmtOz(g) {
  const oz = g / 28.3495;
  if (oz >= 16) {
    const lb = Math.floor(oz / 16);
    return `${lb} lb ${(Math.round((oz - lb * 16) * 10) / 10).toString()} oz`;
  }
  return (oz >= 1 ? Math.round(oz * 10) / 10 : Math.round(oz * 100) / 100) + ' oz';
}

function fmtVol(g, kind) {
  const tsp = g / gPerTsp(kind);
  const note = KINDS[kind]?.volNote ? ` <span class="muted">(${KINDS[kind].volNote})</span>` : '';
  if (tsp >= 12) return `${frac(tsp / 48)} cup${tsp / 48 > 1.06 ? 's' : ''}` + note;
  if (tsp >= 3) {
    const tbsp = tsp / 3;
    const whole = Math.floor(tbsp + 0.06);
    const remTsp = tsp - whole * 3;
    return `${whole} Tbsp${remTsp >= 0.2 ? ' + ' + frac(remTsp) + ' tsp' : ''}` + note;
  }
  return `${frac(tsp)} tsp` + note;
}

export function fmtAmount(g, kind, units) {
  if (!g) return '—';
  if (units === 'oz') return fmtOz(g);
  if (units === 'vol') return fmtVol(g, kind);
  return fmtGrams(g);
}

// Parse a typed amount in the current display unit back to grams. Volume input is in the
// displayed main unit: cups for cup-sized amounts, else tsp.
export function toGrams(value, kind, units, currentGrams) {
  const v = parseFloat(String(value).replace(',', '.'));
  if (!isFinite(v)) return NaN;
  if (units === 'oz') return v * 28.3495;
  if (units === 'vol') {
    const tsp = currentGrams / gPerTsp(kind);
    return tsp >= 12 ? v * 48 * gPerTsp(kind) : v * gPerTsp(kind);
  }
  return v;
}

export function editValue(g, kind, units) {
  if (units === 'oz') return +(g / 28.3495).toFixed(2);
  if (units === 'vol') {
    const tsp = g / gPerTsp(kind);
    return tsp >= 12 ? +(tsp / 48).toFixed(2) : +tsp.toFixed(2);
  }
  return Math.round(g * 10) / 10;
}
export function editUnit(g, kind, units) {
  if (units === 'oz') return 'oz';
  if (units === 'vol') return g / gPerTsp(kind) >= 12 ? 'cups' : 'tsp';
  return 'g';
}

export function scaled(recipe, factor) {
  return { ...recipe, ingredients: recipe.ingredients.map((i) => ({ ...i, grams: (+i.grams || 0) * factor })) };
}
