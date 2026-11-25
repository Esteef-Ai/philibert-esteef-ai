// Turns imported content (site markup or raw text from a page, PDF, Word file or photo)
// into a Yes Chef! recipe: ingredients converted to grams, steps with timers detected.
import { KINDS } from './units.js';
import { uid } from './ui.js';

// ---------- numbers & durations ----------
const UNI = { '½': '1/2', '⅓': '1/3', '⅔': '2/3', '¼': '1/4', '¾': '3/4', '⅕': '1/5', '⅛': '1/8', '⅜': '3/8', '⅝': '5/8', '⅞': '7/8', '⅙': '1/6' };
const WORDNUM = { a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, fifteen: 15, twenty: 20, thirty: 30, forty: 40, 'forty-five': 45, sixty: 60, half: 0.5 };

export function normalize(s) {
  return String(s)
    .replace(/(\d)\s*([½⅓⅔¼¾⅕⅛⅜⅝⅞⅙])/g, (m, d, f) => `${d} ${UNI[f]}`)
    .replace(/[½⅓⅔¼¾⅕⅛⅜⅝⅞⅙]/g, (f) => UNI[f])
    .replace(/(\d)\s*⁄\s*(\d)/g, '$1/$2')
    .replace(/[–—−]/g, '-')
    .replace(/\u00a0/g, ' ');
}

const NUM = String.raw`(?:\d+\s+\d+\/\d+|\d+\/\d+|\d+(?:[.,]\d+)?)`;
export function num(s) {
  s = String(s).trim().replace(',', '.');
  if (WORDNUM[s.toLowerCase()] !== undefined) return WORDNUM[s.toLowerCase()];
  const mixed = s.match(/^(\d+)\s+(\d+)\/(\d+)$/);
  if (mixed) return +mixed[1] + mixed[2] / mixed[3];
  const fr = s.match(/^(\d+)\/(\d+)$/);
  if (fr) return fr[1] / fr[2];
  return parseFloat(s);
}

const UNIT_MIN = (u) => (/^d/i.test(u) ? 1440 : /^h/i.test(u) ? 60 : /^s/i.test(u) ? 1 / 60 : 1);
const DUR_RE = new RegExp(
  String.raw`\b(${NUM}|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty-five|forty|sixty)` +
    String.raw`(?:\s*(?:-|to|or)\s*(${NUM}|two|three|four|five|six|eight|ten|twelve))?\s*` +
    String.raw`(days?|hours?|hrs?|minutes?|mins?|seconds?|secs?)\b` +
    String.raw`(?:\s*(?:and\s*)?(${NUM})\s*(minutes?|mins?)\b)?`,
  'gi',
);

// All durations mentioned in a piece of text, in minutes.
export function durations(text) {
  const t = normalize(text);
  const out = [];
  for (const m of t.matchAll(DUR_RE)) {
    const unit = UNIT_MIN(m[3]);
    let lo = num(m[1]) * unit;
    let hi = m[2] ? num(m[2]) * unit : lo;
    if (m[4]) {
      const extra = num(m[4]);
      lo += extra;
      hi += extra;
    }
    if (!(lo > 0)) continue;
    out.push({ min: Math.round(lo), max: Math.round(Math.max(lo, hi)), raw: m[0], index: m.index });
  }
  if (/half an hour/i.test(t)) out.push({ min: 30, max: 30, raw: 'half an hour', index: t.search(/half an hour/i) });
  if (/\bovernight\b|night before/i.test(t)) out.push({ min: 480, max: 720, raw: 'overnight', index: t.search(/overnight|night before/i), overnight: true });
  return out.sort((a, b) => a.index - b.index);
}

export const fmtDuration = (min) =>
  min >= 2880
    ? `${+(min / 1440).toFixed(1)} days`
    : min >= 120
      ? `${+(min / 60).toFixed(1)} hours`
      : min >= 60
        ? `${Math.floor(min / 60)} h ${min % 60 ? (min % 60) + ' min' : ''}`.trim()
        : `${min} min`;

// ---------- ingredients ----------
const KIND_RULES = [
  ['preferment', /\b(starter|levain|poolish|biga|sponge|pre-?ferment)\b/i],
  ['yeast', /\byeast\b/i],
  ['malt', /\bmalt\b/i],
  ['flour', /\bflour\b|semolina|\bmeal\b|\bdurum\b/i],
  ['milk', /\bmilk\b|buttermilk|\bcream\b/i],
  ['water', /\bwater\b|\bice\b/i],
  ['salt', /\bsalt\b/i],
  ['sugar', /sugar|honey|syrup|molasses/i],
  ['oil', /\boil\b/i],
  ['butter', /butter|lard|shortening|margarine/i],
  ['seeds', /seeds?|sesame|poppy|nigella/i],
  ['egg', /\beggs?\b|\byolks?\b|egg whites?/i],
];
// The ingredient named first wins: "melted butter or vegetable oil" is butter.
export function guessKind(name) {
  let best = 'other';
  let at = Infinity;
  for (const [k, re] of KIND_RULES) {
    const m = name.match(re);
    if (m && m.index < at) {
      at = m.index;
      best = k;
    }
  }
  return best;
}
const gPerTsp = (kind) => {
  const k = KINDS[kind] || KINDS.other;
  return k.gPerTsp || k.gPerCup / 48;
};
const ML_DENSITY = { water: 1, milk: 1.03, oil: 0.92, egg: 1.03, sugar: 0.85, flour: 0.53, salt: 1.2, other: 1 };

const UNIT_RE = String.raw`(cups?|c\.?|tablespoons?|tbsps?|tbs|tbl|T|teaspoons?|tsps?|t|ounces?|oz|pounds?|lbs?|lb|grams?|g|gr|kilograms?|kgs?|kg|milliliters?|millilitres?|ml|liters?|litres?|l|pinch(?:es)?|dash(?:es)?|packets?|packages?|envelopes?|sticks?|large|medium|small)`;
const LEAD_RE = new RegExp(String.raw`^(${NUM})(?:\s*-\s*${NUM})?\s*${UNIT_RE}?\.?(?=\s|$)\s*(?:of\s+)?(.*)$`, 'i');
const TRAIL_RE = new RegExp(String.raw`^(.*?)[\s:\t]+(${NUM})\s*${UNIT_RE}\.?\s*$`, 'i');
const SOFT_RE = /\b(to taste|as desired|as needed|for dusting|for greasing|for the (?:bowl|pan|work surface)|optional)\b/i;

function toGramsFrom(qty, unit, kind) {
  if (!unit) {
    if (kind === 'egg') return qty * 50;
    return null;
  }
  const u = unit.toLowerCase().replace(/\.$/, '');
  if (/^(g|gr|grams?)$/.test(u)) return qty;
  if (/^(kg|kgs|kilograms?)$/.test(u)) return qty * 1000;
  if (/^(oz|ounces?)$/.test(u)) return qty * 28.35;
  if (/^(lb|lbs|pounds?)$/.test(u)) return qty * 453.6;
  if (/^(ml|millilit(er|re)s?)$/.test(u)) return qty * (ML_DENSITY[kind] ?? 1);
  if (/^(l|lit(er|re)s?)$/.test(u)) return qty * 1000 * (ML_DENSITY[kind] ?? 1);
  if (/^(cups?|c)$/.test(u)) return qty * 48 * gPerTsp(kind);
  if (unit === 'T' || /^(tablespoons?|tbsps?|tbs|tbl)$/.test(u)) return qty * 3 * gPerTsp(kind);
  if (unit === 't' || /^(teaspoons?|tsps?)$/.test(u)) return qty * gPerTsp(kind);
  if (/^pinch/.test(u)) return (qty * gPerTsp(kind)) / 16;
  if (/^dash/.test(u)) return (qty * gPerTsp(kind)) / 8;
  if (/^(packets?|packages?|envelopes?)$/.test(u)) return kind === 'yeast' ? qty * 7 : null;
  if (/^sticks?$/.test(u)) return kind === 'butter' ? qty * 113 : null;
  if (/^(large|medium|small)$/.test(u)) return kind === 'egg' ? qty * ({ large: 50, medium: 44, small: 38 }[u]) : null;
  return null;
}

export function parseIngredient(line, group = '') {
  const original = line.replace(/\s+/g, ' ').trim();
  let s = normalize(line)
    .replace(/^\s*[•●▪◦\-*–]\s*/, '')
    .replace(/^\s*\d+[.)]\s+(?=\D)/, '')
    .trim();
  let grams = null;
  let name = s;

  // Table rows: "Bread flour<TAB>600 g"
  if (s.includes('\t')) {
    const [a, ...rest] = s.split(/\t+/);
    const amount = rest.join(' ').trim();
    name = a.trim();
    s = amount ? `${amount} ${name}` : name;
  }
  // Explicit grams anywhere wins: "3 3/4 cups (450 g) bread flour"
  const gm = s.match(/(\d+(?:[.,]\d+)?)\s*(g|grams?|kg)\b/i);
  const kind0 = guessKind(s);
  if (gm) {
    grams = parseFloat(gm[1].replace(',', '.')) * (/kg/i.test(gm[2]) ? 1000 : 1);
  }
  const tabName = name !== s ? name : '';
  let lead = s.match(LEAD_RE);
  let trailName = '';
  if (lead) {
    const rest = lead[3]?.trim() || '';
    const kind = guessKind(rest || s);
    if (grams === null) grams = toGramsFrom(num(lead[1]), lead[2], kind);
  } else {
    const trail = s.match(TRAIL_RE);
    if (trail) {
      const kind = guessKind(trail[1]);
      if (grams === null) grams = toGramsFrom(num(trail[2]), trail[3], kind);
      trailName = trail[1];
    }
  }
  name = cleanName(tabName || trailName || s)
    .replace(/\(\s*see[^)]*\)?/gi, '')
    .replace(/\*+/g, '')
    .trim();
  if (!name) name = original;
  name = name.charAt(0).toUpperCase() + name.slice(1);
  const kind = guessKind(name);
  const soft = SOFT_RE.test(original);
  const optional = /optional|for dusting|for greasing|to taste|as desired|as needed/i.test(original);
  const dusting = /for dusting|for greasing|for the (bowl|pan|work surface)/i.test(original);
  return {
    id: uid('i'),
    name: (group ? group + ': ' : '') + name,
    grams: grams ? Math.round(grams * 10) / 10 : 0,
    kind,
    flour: kind === 'flour' && !dusting,
    optional,
    note: grams && !gm && !/\bg\b|grams/i.test(original) ? `Was: ${original}` : grams ? '' : soft ? (original.match(SOFT_RE)?.[0] || original) : `Was: ${original}`,
    original,
    converted: !!grams && !gm,
    unknown: !grams && !soft,
  };
}

const LEAD_QTY = new RegExp(String.raw`^\s*${NUM}(?:\s*(?:-|to)\s*${NUM})?\s*${UNIT_RE}?\.?(?=\s|$)\s*(?:of\s+)?`, 'i');
function cleanName(s) {
  let n = String(s)
    .replace(/\([^)]*\d[^)]*\)/g, ' ') // "(113g to 152g)", "(about 450 g)"
    .replace(/\(?\b\d+(?:[.,]\d+)?\s*(g|grams?|kg)\b\)?/gi, ' ');
  for (let k = 0; k < 2; k++) n = n.replace(LEAD_QTY, '');
  return n.replace(/^([^(]*)\)/, '$1').replace(/^[,\s]+|[,\s*]+$/g, '').replace(/\s{2,}/g, ' ').trim();
}

const looksLikeIngredient = (l) => {
  const s = normalize(l).replace(/^\s*[•●▪◦\-*]\s*/, '');
  if (s.length > 140) return false;
  if (/\t/.test(s) && /\d|as desired|to taste/i.test(s)) return true;
  if (/^\d{1,2}[.)]\s+[A-Za-z]/.test(s)) return false; // "2. Shared dough" / "1. Mix: ..." are headings or steps
  if (new RegExp(`^${NUM}`).test(s)) return true;
  if (SOFT_RE.test(s) && s.length < 80) return true;
  return new RegExp(String.raw`\s${NUM}\s*(g|grams?|ml|oz|cups?|tsp|tbsp)\.?$`, 'i').test(s);
};

// ---------- steps ----------
const WAIT_RE = /\b(rest(?:ing)?|rise|rising|risen|proof\w*|prov(?:e|ing)|ferment\w*|bulk|chill\w*|refrigerat\w*|fridge|cool(?:ing)?|let (?:it |the dough |them )?(?:sit|stand|rise|rest)|set aside|leave|overnight|autolyse|soak|retard\w*|relax)\b/i;
const BAKE_RE = /\b(bake|baking|oven|roast|broil|grill)\b/i;
const ACTIVE_RE = /\b(knead|mix|stir|whisk|fold|shape|divide|score|beat|pour|transfer|preheat)\b/i;

function classify(text) {
  let d = durations(text);
  if (d.some((x) => !x.overnight) && d.some((x) => x.overnight && x.max > 0)) {
    // "overnight, 12 to 14 hours": the explicit hours win for the timer
    const explicit = d.filter((x) => !x.overnight && x.max >= 240);
    if (explicit.length) d = d.filter((x) => !x.overnight);
  }
  const first = d[0];
  let type = 'active';
  const waitAt = text.search(WAIT_RE);
  const bakeAt = text.search(BAKE_RE);
  // "Let it rise 60 minutes; toward the end, preheat the oven" is a rise, not a bake.
  if (waitAt >= 0 && first && (bakeAt < 0 || waitAt < bakeAt) && !/^\s*(bake|preheat)/i.test(text)) type = 'wait';
  else if (bakeAt >= 0 && first && !/^\s*preheat/i.test(text)) type = 'bake';
  else if (type === 'active' && WAIT_RE.test(text) && (first || /until\b[^.]*\b(doubled|puffy|risen|bubbly|larger|domed)/i.test(text)) && !(ACTIVE_RE.test(text.slice(0, 30)) && !/rest|rise|proof|chill|refrigerat|cool|ferment/i.test(text))) type = 'wait';
  // Pick the duration most likely to be the timer: the one next to a wait/bake word, else the first.
  let pick = first;
  if (d.length > 1) {
    const near = d.find((x) => (type === 'bake' ? BAKE_RE : WAIT_RE).test(text.slice(Math.max(0, x.index - 60), x.index)));
    if (near) pick = near;
  }
  if (pick && pick.max > 0 && pick.min < 1) pick = null;
  const until = text.match(/\b(until [^.;]{4,90})/i)?.[1];
  const temp = text.match(/\b(reaches?|registers?|reads?)\s+(about\s+)?(\d{2,3}\s*[-–]?\s*\d{0,3}\s*°\s*[FC])/i);
  return {
    type,
    minutes: pick ? pick.min : null,
    maxMinutes: pick && pick.max !== pick.min ? pick.max : null,
    check: [until, temp ? `center reads ${temp[3]}` : ''].filter(Boolean).join('; '),
  };
}

function titleFor(text, name) {
  if (name) return name.replace(/[:.]$/, '');
  const colon = text.match(/^([^:.]{2,40}):\s+/);
  if (colon) return colon[1];
  // Use the first real action: skip lead-ins like "In a large bowl," or "When you're ready,".
  const first = text.replace(/\(.*?\)/g, '').split(/(?<=[.!?])\s/)[0];
  const clauses = first.split(/[,;:]\s*/).map((c) => c.trim()).filter(Boolean);
  const clause = clauses.find((c) => !/^(in|using|with|when|once|next|then|meanwhile|after|before|if|while|for|to|at this point)\b/i.test(c) && c.split(/\s+/).length >= 2) || clauses[0] || text;
  const words = clause.split(/\s+/);
  const t = words.slice(0, 6).join(' ').replace(/[,.;:]+$/, '');
  return t.charAt(0).toUpperCase() + t.slice(1) + (words.length > 6 ? '…' : '');
}

// Lines sites put at the end of the instructions that are tips, not steps.
const TIP_RE = /\?|^(want|looking for|store|storing|would|for (added|more|a (softer|crisper))|tips?\b|notes?\b|try\b|substitut|to make (it )?ahead|flour is like|did you know)/i;

export function makeStep({ text, name = '', section = '' }) {
  const t = text.trim();
  const c = classify(t);
  const colon = !name && t.match(/^([^:.]{2,40}):\s+(.+)$/s);
  return {
    id: uid('s'),
    title: (section && !name ? '' : '') + titleFor(t, name),
    detail: colon ? colon[2] : t,
    type: c.type,
    minutes: c.minutes,
    maxMinutes: c.maxMinutes,
    est: c.minutes ? 5 : Math.min(15, Math.max(2, Math.round(t.split(/\s+/).length / 12))),
    check: c.check,
    section: section || '',
  };
}

// ---------- whole documents ----------
const ING_HEAD = /^\s*(?:\d+[.)]\s*)?(ingredients?|what you(?:'|’)?ll need|you(?:'|’)?ll need|you will need)\b/i;
const METHOD_HEAD = /^\s*(?:\d+[.)]\s*)?(instructions|directions|method|preparation|steps|how to make( it)?|procedure)\b/i;
const NOTES_HEAD = /\b(notes?|tips?|variations?|storage|storing|faq|nutrition|discussion|troubleshoot\w*|serving)\b/i;
const NUMBERED = /^\s*(?:step\s*)?(\d{1,2})[.)]\s+(.*)$/i;

const isHeading = (l) => {
  const s = l.trim();
  if (s.length > 70 || /[.;]$/.test(s) || /\t/.test(s)) return false;
  if (/^[•●▪◦\-*]/.test(s)) return false;
  const body = s.replace(NUMBERED, '$2');
  if (/^[a-z]/.test(body) || /\d+\s*(g|ml|cups?|tsp|tbsp)\b/i.test(body)) return false;
  return body.split(/\s+/).length <= 10 && !/[,]$/.test(body);
};

export function parseText(text, { title = '' } = {}) {
  const lines = normalize(text)
    .split(/\r?\n/)
    .map((l) => l.replace(/[ \u00a0]+$/g, '').replace(/^ +/, ''))
    .filter((l) => l.trim() && !/^(ingredients?|item)\s+(amount|quantity)$/i.test(l.trim()) && !/^ingredient\tamount$/i.test(l.trim()));

  const name = title || lines[0]?.trim() || 'Imported recipe';
  let i = title ? 0 : 1;
  const notes = [];
  const ingredients = [];
  const steps = [];

  // Intro text until the ingredients start
  const ingAt = lines.findIndex((l) => ING_HEAD.test(l) && l.length < 60);
  let start = ingAt >= 0 ? ingAt + 1 : -1;
  if (start < 0) start = lines.findIndex((l, k) => k >= i && looksLikeIngredient(l) && looksLikeIngredient(lines[k + 1] || ''));
  if (start < 0) start = i;
  for (let k = i; k < Math.max(i, ingAt >= 0 ? ingAt : start); k++) if (!isHeading(lines[k]) || lines[k].length > 30) notes.push(lines[k]);

  // Ingredient block
  let group = '';
  let k = start;
  for (; k < lines.length; k++) {
    const l = lines[k].trim();
    if (METHOD_HEAD.test(l) && l.length < 60) break;
    if (looksLikeIngredient(l)) {
      ingredients.push(parseIngredient(l, group));
      continue;
    }
    if (/:$/.test(l) && l.length < 40 && !/\d/.test(l)) {
      group = l.replace(/^for (the )?/i, '').replace(/:$/, '').trim();
      group = group.charAt(0).toUpperCase() + group.slice(1);
      continue;
    }
    if (!ingredients.length) continue;
    if (NUMBERED.test(l) || isHeading(l)) break;
    if (/^(important|note|tip)\b/i.test(l)) {
      let note = l;
      while (lines[k + 1] && !isHeading(lines[k + 1]) && !NUMBERED.test(lines[k + 1]) && !/[.!]$/.test(note)) note += ' ' + lines[++k].trim();
      notes.push(note);
      continue;
    }
    break;
  }
  if (k < lines.length && METHOD_HEAD.test(lines[k]) && lines[k].length < 60) k++;

  // Steps, sections and trailing notes
  let section = '';
  let inNotes = false;
  let cur = null;
  const push = () => {
    if (cur && cur.text.trim()) (inNotes ? notes : steps).push(inNotes ? cur.text.trim() : cur);
    cur = null;
  };
  let prevNum = 0;
  for (; k < lines.length; k++) {
    const l = lines[k].trim();
    const nm = l.match(NUMBERED);
    const nextNum = (lines[k + 1] || '').match(NUMBERED);
    // A short title-like line is a section heading ("2. Shared Dough Preparation", "Long Loaves").
    // A numbered one counts as a heading when numbering restarts after it or does not continue.
    const body = nm ? nm[2] : l;
    const titleLike = isHeading(body) && !/:\s*\S/.test(body);
    const heading = titleLike && (!nm || (nextNum && +nextNum[1] === 1) || +nm[1] !== prevNum + 1);
    if (heading) {
      push();
      section = body.trim();
      inNotes = NOTES_HEAD.test(section);
      prevNum = 0;
      continue;
    }
    if (nm) {
      push();
      prevNum = +nm[1];
      cur = { text: nm[2], section, numbered: true };
    } else if (/^[•●▪◦\-*]\s+/.test(l)) {
      push();
      cur = { text: l.replace(/^[•●▪◦\-*]\s+/, ''), section };
    } else if (/^(important|note|tip)\s*:/i.test(l)) {
      push();
      notes.push(l);
    } else if (cur && (cur.numbered || !/[.!?)]$/.test(cur.text.trim()))) {
      cur.text += ' ' + l; // wrapped line
    } else if (cur && l.length && /^[a-z(]/.test(l)) {
      cur.text += ' ' + l;
    } else {
      push();
      cur = { text: l, section };
    }
  }
  push();

  return { name: name.trim(), ingredients, steps: steps.map(makeStep), notes: notes.join('\n') };
}

export function fromStructured(r) {
  const ingredients = [];
  let group = '';
  for (const line of r.ingredients || []) {
    if (/:$/.test(line.trim()) && !/\d/.test(line)) {
      group = line.replace(/^for (the )?/i, '').replace(/:$/, '').trim();
      continue;
    }
    ingredients.push(parseIngredient(line, group));
  }
  // Tips/notes sections that sites put inside the instructions go to notes instead.
  const tips = (r.steps || []).filter((s) => s.section && NOTES_HEAD.test(s.section));
  // Trailing tip-like entries (questions, storage, variations) go to notes too.
  const rest = (r.steps || []).filter((s) => !tips.includes(s));
  for (let k = rest.length - 1; k > 0 && TIP_RE.test(rest[k].text.trim()); k--) tips.push(rest[k]);
  // "The flour/liquid ratio is important…" before the first real step is a note too.
  for (const s of rest) {
    if (!/\b(important|note)\b/i.test(s.text) || durations(s.text).length || /^(combine|mix|stir|place|add|whisk|knead)/i.test(s.text)) break;
    if (/^(the|this|weigh|for best)/i.test(s.text) && s.text.split(/\s+/).length < 40) tips.push(s);
    else break;
  }
  const steps = (r.steps || [])
    .filter((s) => !tips.includes(s))
    .map((s) => makeStep({ text: s.text, name: /^step\s*\d+\.?$/i.test(s.name || '') ? '' : s.name, section: s.section }));
  const notes = [r.description, r.notes, r.yield ? 'Yield: ' + r.yield : '', isoTimes(r), ...tips.map((t) => '• ' + t.text)].filter(Boolean).join('\n');
  return { name: r.name || 'Imported recipe', ingredients, steps, notes };
}

function isoTimes(r) {
  const iso = (v) => {
    const m = String(v || '').match(/P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?/);
    if (!m) return 0;
    return (+m[1] || 0) * 1440 + (+m[2] || 0) * 60 + (+m[3] || 0);
  };
  const t = iso(r.totalTime);
  return t ? `Site says total time: ${fmtDuration(t)}` : '';
}

// Final recipe object as stored by the app.
export function toRecipe(parsed, source) {
  return {
    id: uid('r'),
    name: parsed.name.slice(0, 120),
    parentId: null,
    hypothesis: '',
    notes: parsed.notes || '',
    tags: ['imported'],
    yieldNote: '',
    loafWeight: 500,
    createdAt: Date.now(),
    source,
    ingredients: parsed.ingredients.map(({ original, converted, unknown, ...i }) => i),
    steps: parsed.steps.length ? parsed.steps : [{ id: uid('s'), title: 'Make it', detail: '', type: 'active', minutes: null, maxMinutes: null, est: 5, check: '' }],
  };
}
