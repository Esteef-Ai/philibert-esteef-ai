// Troubleshooting scenarios. Each one makes a single, explained change to a fork of the recipe,
// so one bake tests one idea. Problems map to the scenarios most likely to help.
import { flourTotal } from './units.js';
import { uid } from './ui.js';

export const PROBLEMS = [
  { id: 'dense', label: 'Crumb too dense / tight' },
  { id: 'chewy', label: 'Too chewy / hard to eat' },
  { id: 'gummy', label: 'Gummy or damp crumb' },
  { id: 'pale', label: 'Crust too pale' },
  { id: 'thick', label: 'Crust too thick / hard' },
  { id: 'flat', label: 'Spread flat / weak shape' },
  { id: 'collapsed', label: 'Collapsed when scored or baked' },
  { id: 'tore', label: 'Burst or tore on the side' },
  { id: 'bland', label: 'Flavor is flat' },
];

const findStep = (r, re) => r.steps.find((s) => re.test(s.id) || re.test(s.title));
const findIng = (r, pred) => r.ingredients.find(pred);
const bump = (s, d) => {
  s.minutes = Math.max(1, (s.minutes || 0) + d);
  if (s.maxMinutes) s.maxMinutes = Math.max(s.minutes, s.maxMinutes + d);
};

export const SCENARIOS = [
  {
    id: 'proof-longer',
    short: 'longer final proof',
    problems: ['dense', 'tore'],
    title: 'Proof longer',
    why: 'Under-proofed loaves bake up tight and can burst on the side. Give the final proof 15 more minutes and use the poke test.',
    can: (r) => !!findStep(r, /proof/i),
    apply(r) {
      const s = findStep(r, /^proof$|final proof/i) || findStep(r, /proof/i);
      bump(s, 15);
      s.check = 'Floured finger poke ½ inch: fills back slowly, leaves a slight dent';
    },
  },
  {
    id: 'bulk-longer',
    short: 'longer bulk',
    problems: ['dense', 'bland'],
    title: 'Longer bulk rise',
    why: 'A short bulk rise leaves the dough under-aerated. Let it go until fully doubled, about 15 minutes more.',
    can: (r) => !!findStep(r, /bulk/i),
    apply(r) {
      const list = r.steps.filter((s) => /bulk/i.test(s.id + s.title) && s.minutes);
      bump(list[list.length - 1] || findStep(r, /bulk/i), 15);
    },
  },
  {
    id: 'hydration-up',
    short: '+2% water',
    problems: ['dense', 'chewy'],
    title: 'Add 2% water',
    why: 'A little more water gives a softer, more open crumb. Small step so the shape still holds.',
    can: (r) => !!findIng(r, (i) => i.kind === 'water'),
    apply(r) {
      findIng(r, (i) => i.kind === 'water').grams += flourTotal(r) * 0.02;
    },
  },
  {
    id: 'hydration-down',
    short: '−2% water',
    problems: ['flat'],
    title: 'Remove 2% water',
    why: 'A dough that spreads may be too wet for the flour. Pull back a little water.',
    can: (r) => !!findIng(r, (i) => i.kind === 'water'),
    apply(r) {
      const w = findIng(r, (i) => i.kind === 'water');
      w.grams = Math.max(0, w.grams - flourTotal(r) * 0.02);
    },
  },
  {
    id: 'softer-flour',
    short: '25% AP flour',
    problems: ['chewy', 'thick'],
    title: 'Swap 25% of bread flour for all-purpose',
    why: 'Lower protein flour gives a more tender bite while keeping enough strength.',
    can: (r) => !!findIng(r, (i) => i.flour && /bread/i.test(i.name)),
    apply(r) {
      const bf = findIng(r, (i) => i.flour && /bread/i.test(i.name));
      const move = Math.round(flourTotal(r) * 0.25);
      const take = Math.min(move, bf.grams);
      bf.grams -= take;
      const ap = findIng(r, (i) => i.flour && /all.?purpose|\bap\b/i.test(i.name));
      if (ap) ap.grams += take;
      else r.ingredients.splice(r.ingredients.indexOf(bf) + 1, 0, { id: 'apflour', name: 'All-purpose flour', grams: take, kind: 'flour', flour: true });
    },
  },
  {
    id: 'more-fat',
    short: '+1% oil',
    problems: ['chewy', 'thick'],
    title: 'Add 1% more oil',
    why: 'Fat tenderizes the crumb and softens the bite. Too much softens the crust, so keep it small.',
    can: (r) => !!findIng(r, (i) => i.kind === 'oil' || i.kind === 'butter'),
    apply(r) {
      findIng(r, (i) => i.kind === 'oil' || i.kind === 'butter').grams += flourTotal(r) * 0.01;
    },
  },
  {
    id: 'no-malt',
    short: 'no diastatic malt',
    problems: ['gummy'],
    title: 'Remove diastatic malt',
    why: 'Most US bread flour is already malted. Extra diastatic malt can make the crumb gummy.',
    can: (r) => !!findIng(r, (i) => i.kind === 'malt' && i.grams > 0),
    apply(r) {
      r.ingredients = r.ingredients.filter((i) => i.kind !== 'malt');
    },
  },
  {
    id: 'bake-longer',
    short: 'bake +3 min',
    problems: ['gummy', 'pale'],
    title: 'Bake 3 minutes longer',
    why: 'Under-baked bread stays damp inside. Bake until the center reads 208–210°F.',
    can: (r) => r.steps.some((s) => s.type === 'bake' && s.minutes && !s.optional),
    apply(r) {
      const list = r.steps.filter((s) => s.type === 'bake' && s.minutes && !s.optional);
      bump(list[list.length - 1], 3);
    },
  },
  {
    id: 'bake-shorter',
    short: 'bake −3 min',
    problems: ['thick'],
    title: 'Bake 3 minutes shorter',
    why: 'A long bake thickens the crust. Pull it once the center hits 208°F.',
    can: (r) => r.steps.some((s) => s.type === 'bake' && s.minutes && !s.optional),
    apply(r) {
      const list = r.steps.filter((s) => s.type === 'bake' && s.minutes && !s.optional);
      bump(list[list.length - 1], -3);
    },
  },
  {
    id: 'more-sugar',
    short: '+0.5% sugar',
    problems: ['pale'],
    title: 'Add 0.5% sugar',
    why: 'More sugar browns the crust faster without changing the crumb much.',
    can: (r) => true,
    apply(r) {
      const s = findIng(r, (i) => i.kind === 'sugar');
      const add = flourTotal(r) * 0.005;
      if (s) s.grams += add;
      else r.ingredients.push({ id: uid('i'), name: 'Sugar', grams: add, kind: 'sugar', flour: false });
    },
  },
  {
    id: 'proof-shorter',
    short: 'shorter final proof',
    problems: ['collapsed', 'flat'],
    title: 'Proof 10 minutes less',
    why: 'Over-proofed loaves deflate when scored and spread. Bake when the poke springs back slowly but still fills.',
    can: (r) => !!findStep(r, /proof/i),
    apply(r) {
      bump(findStep(r, /^proof$|final proof/i) || findStep(r, /proof/i), -10);
    },
  },
  {
    id: 'poolish',
    short: 'overnight poolish',
    problems: ['bland', 'dense'],
    title: 'Add an overnight poolish',
    why: 'A pre-ferment of 25% of the flour, 12–14 hours ahead, adds flavor and extensibility and lightens the crumb. Many NY bakeries use one.',
    can: (r) => !r.ingredients.some((i) => /poolish/i.test(i.name)) && !!findIng(r, (i) => i.kind === 'water') && flourTotal(r) > 0,
    apply(r) {
      const f = flourTotal(r);
      const pf = Math.round(f * 0.25);
      const mainFlour = r.ingredients.find((i) => i.flour && /bread/i.test(i.name)) || r.ingredients.find((i) => i.flour);
      const water = findIng(r, (i) => i.kind === 'water');
      const yeast = findIng(r, (i) => i.kind === 'yeast');
      const take = Math.min(pf, mainFlour.grams);
      mainFlour.grams -= take;
      water.grams = Math.max(0, water.grams - take);
      const pyeast = +(f * 0.0005).toFixed(2);
      if (yeast) yeast.grams = Math.max(0, yeast.grams - pyeast);
      r.ingredients.unshift(
        { id: 'poolish-flour', name: 'Poolish: bread flour', grams: take, kind: 'flour', flour: true },
        { id: 'poolish-water', name: 'Poolish: water', grams: take, kind: 'water', flour: false },
        { id: 'poolish-yeast', name: 'Poolish: instant yeast', grams: pyeast, kind: 'yeast', flour: false, note: 'A pinch' },
      );
      r.steps.unshift(
        { id: 'poolish-mix', title: 'Mix poolish (night before)', detail: 'Stir the poolish flour, water and pinch of yeast into a smooth paste. Cover.', type: 'active', minutes: null, maxMinutes: null, est: 3, check: '' },
        { id: 'poolish-wait', title: 'Poolish ferments', detail: 'Leave at room temperature (68–72°F).', type: 'wait', minutes: 720, maxMinutes: 840, est: 5, check: 'Bubbly, domed or just starting to dip in the middle' },
      );
      const mix = r.steps.find((s) => !s.id.startsWith('poolish') && (/^mix/i.test(s.id) || /^mix/i.test(s.title)));
      if (mix) mix.detail = 'Add the poolish with the rest of the ingredients. ' + mix.detail;
    },
  },
];

export const scenariosFor = (problemIds) => SCENARIOS.filter((s) => s.problems.some((p) => problemIds.includes(p)));
