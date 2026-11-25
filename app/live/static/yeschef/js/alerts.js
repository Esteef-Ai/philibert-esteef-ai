// Read-ahead analysis. Finds the things in a recipe that catch you out if you only read one step
// at a time: long or overnight waits, make-ahead pre-ferments, fridge time, early preheats,
// ingredients that are divided, room-temperature prep, special equipment, and explicit warnings.
//
// level 'read'  = MUST READ  (can wreck the timing or the bake if missed)
// level 'check' = MUST CHECK (verify before or during the step)
import { durations, fmtDuration } from './importer.js';

const LONG_WAIT = 240; // minutes
const EQUIPMENT = [
  ['stand mixer', /stand mixer|dough hook/i],
  ['Dutch oven', /dutch oven|cast[- ]iron pot|combo cooker/i],
  ['baking stone or steel', /baking (stone|steel)|pizza (stone|steel)/i],
  ['instant-read thermometer', /thermometer|internal temp|208|210\s*°|reads? \d{3}/i],
  ['proofing basket', /banneton|proofing basket|brotform/i],
  ['razor or lame', /\blame\b|razor/i],
  ['kitchen scale', /\bscale\b|weigh/i],
  ['steam pan', /steam pan|pan of (boiling )?water|ice cubes? (in|into) (a|the) pan/i],
  ['spray bottle', /spray bottle|\bmist\b/i],
  ['loaf pan', /loaf pan|bread pan|pullman/i],
  ['couche', /couche/i],
  ['peel', /\bpeel\b/i],
];

const WARN_SENT = /\b(do not|don't|never|avoid|careful|be sure|make sure|important|must|critical|warning|caution)\b/i;

export function analyze(recipe) {
  const out = [];
  const steps = recipe.steps || [];
  const all = [recipe.notes || '', ...steps.map((s) => `${s.title}. ${s.detail} ${s.check || ''}`)].join('\n');
  const add = (level, title, text, stepId = null, extra = {}) => {
    if (out.some((a) => a.title === title && a.stepId === stepId)) return;
    out.push({ id: `${level}:${title}:${stepId || ''}`, level, title, text, stepId, ...extra });
  };
  const idx = (s) => steps.indexOf(s) + 1;

  // --- long waits, overnight, fridge time ---
  for (const s of steps) {
    const text = `${s.title}. ${s.detail}`;
    const d = durations(text);
    const longest = Math.max(s.maxMinutes || 0, s.minutes || 0, ...d.map((x) => x.max));
    const overnight = d.some((x) => x.overnight);
    const fridge = /refrigerat|fridge|cold (retard|ferment|proof)|retard/i.test(text);
    if (overnight || longest >= LONG_WAIT) {
      add('read', overnight ? 'Overnight wait' : `Long wait: ${fmtDuration(longest)}`, `Step ${idx(s)} “${s.title}” takes ${overnight ? 'overnight' : 'up to ' + fmtDuration(longest)}. Plan your start time around it.`, s.id);
    } else if (fridge && longest >= 60) {
      add('read', 'Fridge time', `Step ${idx(s)} “${s.title}” needs ${fmtDuration(longest)} in the fridge. Make room before you start.`, s.id);
    }
    if (/\b(day|night) before|a day ahead|in advance|ahead of time|make[- ]ahead|\b(24|36|48|72) hours?\b/i.test(text)) {
      add('read', 'Start ahead', `Step ${idx(s)} “${s.title}” has to be done ahead of time: “${sentenceWith(text, /day before|night before|ahead|advance|\b\d{2} hours?/i)}”`, s.id);
    }
    if (/until\b/i.test(text) && !s.minutes && (s.type === 'wait' || /\b(rise|proof|ferment|double|puffy|bubbly)/i.test(text))) {
      add('check', 'Goes by look, not the clock', `Step ${idx(s)} “${s.title}”: ${s.check || sentenceWith(text, /until/i)}. Times vary with room temperature.`, s.id);
    }
  }

  // --- pre-ferments and starters ---
  const pf = (recipe.ingredients || []).find((i) => i.kind === 'preferment' || /\b(starter|levain|poolish|biga|sponge)\b/i.test(i.name));
  if (pf || /\b(poolish|biga|levain|sourdough starter|active starter|pre-?ferment)\b/i.test(all)) {
    add('read', 'Needs a pre-ferment or starter', `${pf ? `“${pf.name}”` : 'This recipe'} has to be made or fed hours before you mix the dough (often the night before).`, steps.find((s) => /poolish|biga|levain|starter|sponge|pre-?ferment/i.test(s.title + s.detail))?.id || null);
  }

  // --- preheat that must start during an earlier step ---
  for (const s of steps) {
    const text = `${s.title}. ${s.detail}`;
    if (!/\bpre-?heat(?!ed)/i.test(text)) continue;
    const d = durations(sentenceWith(text, /pre-?heat/i));
    let mins = Math.max(/^\s*pre-?heat/i.test(s.title) ? s.minutes || 0 : 0, ...d.map((x) => x.max), 0);
    if (!mins) mins = /dutch oven|stone|steel|cast iron/i.test(all) ? 45 : 20;
    const i = steps.indexOf(s);
    // Preheat mentioned inside a long enough rest: do it during that rest.
    if (s.type === 'wait' && (s.minutes || 0) >= mins && !/^\s*pre-?heat/i.test(s.title)) {
      add('check', `Preheat during this rest (${mins} min)`, `Start heating the oven partway through step ${i + 1} “${s.title}” so it is hot when the dough is ready.`, s.id);
      continue;
    }
    // Walk back through earlier steps to find where the preheat has to begin.
    let acc = 0;
    let at = i;
    for (let k = i - 1; k >= 0 && acc < mins; k--) {
      acc += steps[k].minutes || steps[k].est || 5;
      at = k;
    }
    if (at < i) {
      add('check', `Start the preheat early (${mins} min)`, `The oven needs about ${mins} minutes. Start preheating during step ${at + 1} “${steps[at].title}”, not when you reach step ${i + 1}.`, s.id, { showAtStepId: steps[at].id });
    } else {
      add('check', `Preheat takes ${mins} min`, `Allow about ${mins} minutes for the oven at step ${i + 1}.`, s.id);
    }
  }

  // --- ingredient prep ---
  const divided = (recipe.ingredients || []).filter((i) => /divided|reserved|separated|plus (more|extra)|\bsplit\b/i.test(`${i.name} ${i.note || ''}`));
  if (divided.length) add('check', 'Divided ingredients', `${divided.map((i) => i.name).join(', ')} ${divided.length > 1 ? 'are' : 'is'} used in more than one step. Don't add it all at once.`);
  const salted = steps.find((s) => /hold back|reserve|set aside .{0,30}(salt|water|flour|oil)|add (the )?(salt|oil) (later|after)/i.test(s.detail));
  if (salted) add('check', 'Something is held back', `Step ${idx(salted)} “${salted.title}”: ${sentenceWith(salted.detail, /hold back|reserve|set aside|later|after/i)}`, salted.id);
  const ingText = (recipe.ingredients || []).map((i) => i.name + ' ' + (i.note || '')).join('\n');
  const roomTemp =
    /room[- ]temp|softened/i.test(ingText) ||
    steps.some((s) => sentences(s.detail).some((x) => /(butter|eggs?|milk|cream cheese|starter)[^.]{0,40}(room temperature|softened)|(room temperature|softened)[^.]{0,20}(butter|eggs?|milk)/i.test(x)));
  if (roomTemp) {
    add('check', 'Room-temperature ingredients', 'Some ingredients need to be at room temperature. Take them out 30–60 minutes before you start.');
  }
  const ingNames = (recipe.ingredients || []).map((i) => i.name).join('\n');
  const waterTemp = (ingNames + '\n' + all).match(/\b((?:luke)?warm|hot|cold|ice|\d{2,3}\s*°\s*[FC])[^.\n]{0,30}\bwater\b|\bwater\b[^.\n]{0,30}(\d{2,3}\s*°\s*[FC]|\b(?:luke)?warm\b|\bhot\b|\bcold\b)/i);
  if (waterTemp) add('check', 'Water temperature matters', `“${waterTemp[0].trim()}”. Too hot can kill the yeast; too cold slows the rise.`);

  // --- explicit warnings in the text ---
  let warnCount = 0;
  for (const s of steps) {
    for (const sent of sentences(s.detail)) {
      if (warnCount >= 6) break;
      if (WARN_SENT.test(sent) && sent.length < 220 && !/don'?t (stress|worry|fuss|panic|be afraid)|if you don'?t have|no need to|not necessarily/i.test(sent)) {
        add('check', `Watch out: ${s.title}`, sent, s.id);
        warnCount++;
        break;
      }
    }
  }
  for (const line of (recipe.notes || '').split('\n')) {
    if (/^\s*(important|note|warning|caution)\s*:/i.test(line)) add('read', 'Note from the recipe', line.replace(/^\s*\w+\s*:\s*/, ''));
  }

  // --- equipment ---
  const eq = EQUIPMENT.filter(([, re]) => re.test(all)).map(([n]) => n);
  if (eq.length) add('check', 'Equipment', `Have ready: ${eq.join(', ')}.`);

  // --- total time ---
  const total = steps.filter((s) => !s.optional).reduce((t, s) => t + (s.maxMinutes || s.minutes || s.est || 5), 0);
  if (total >= 300) add(total >= 480 ? 'read' : 'check', `About ${fmtDuration(total)} start to finish`, `Count back from when you want to eat it. The longest waits are what set the schedule.`);

  // MUST READ first
  return out.sort((a, b) => (a.level === b.level ? 0 : a.level === 'read' ? -1 : 1));
}

export function alertLevel(alerts) {
  return alerts.some((a) => a.level === 'read') ? 'read' : alerts.length ? 'check' : null;
}

function sentences(text) {
  return String(text || '')
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}
function sentenceWith(text, re) {
  return sentences(text).find((s) => re.test(s)) || String(text).slice(0, 160);
}
