// Import a recipe from a link, a file (PDF, Word, photo/screenshot, text) or pasted text.
// Shows a review with MUST READ / MUST CHECK alerts before saving.
import { esc, toast, shrinkImage, bus } from '../ui.js';
import { saveRecipe, call, blobToB64 } from '../store.js';
import { parseText, fromStructured, toRecipe } from '../importer.js';
import { analyze } from '../alerts.js';
import { alertsPanel } from '../components.js';
import { fmtGrams } from '../units.js';

const st = { tab: 'link', busy: '', error: '', result: null, off: new Set(), url: '', text: '' };

export const title = () => 'Import a recipe';
export const isBusy = () => !!st.busy;

export function render() {
  return `
  <div class="page-head">
    <div><a class="back" href="#/recipes">← Recipes</a><h1>Import a recipe</h1></div>
  </div>
  ${st.result ? review() : chooser()}`;
}

function chooser() {
  const tab = st.tab;
  return `
  <section class="card">
    <div class="seg wide-seg" role="tablist">
      ${[
        ['link', '🔗 Link'],
        ['file', '📄 File or photo'],
        ['text', '📋 Paste text'],
      ]
        .map(([k, l]) => `<button role="tab" class="${tab === k ? 'on' : ''}" data-action="tab" data-t="${k}">${l}</button>`)
        .join('')}
    </div>

    ${
      tab === 'link'
        ? `<form data-submit="url" class="import-form">
        <label class="field"><span>Recipe page address</span>
          <input name="url" type="url" inputmode="url" placeholder="https://www.example.com/italian-bread-recipe" value="${esc(st.url)}" required></label>
        <button class="btn primary big-touch" ${st.busy ? 'disabled' : ''}>Import from link</button>
        <p class="muted small">Works with most recipe sites. Needs INTERNET on in Philibert. If a site blocks it, save the page as a PDF and add that, or paste the text.</p>
      </form>`
        : tab === 'file'
          ? `<div class="drop" id="drop" data-action="pick-file" tabindex="0" role="button" aria-label="Choose a file">
          <div class="drop-icon" aria-hidden="true">📄</div>
          <strong>Drop a PDF, Word file or screenshot here</strong>
          <span class="muted">or click to choose · paste a screenshot with Ctrl+V</span>
          <span class="muted small">PDF · Word (.docx) · PNG/JPG/WebP · text</span>
        </div>
        <div class="btn-row">
          <button class="btn" data-action="pick-file">Choose file</button>
          <button class="btn" data-action="take-photo">📷 Photo of a cookbook page</button>
        </div>
        <p class="muted small">Photos and scanned PDFs are read with the text recognition built into Windows on the PC. Check the numbers after importing.</p>`
          : `<form data-submit="text" class="import-form">
        <label class="field"><span>Recipe text</span>
          <textarea name="text" rows="12" placeholder="Paste the whole recipe: title, ingredients and instructions">${esc(st.text)}</textarea></label>
        <button class="btn primary big-touch" ${st.busy ? 'disabled' : ''}>Read recipe</button>
      </form>`
    }
    ${st.busy ? `<div class="busy"><span class="spinner" aria-hidden="true"></span>${esc(st.busy)}</div>` : ''}
    ${st.error ? `<div class="callout warn">${esc(st.error)}</div>` : ''}
  </section>`;
}

// ---------- review ----------
function current() {
  const p = st.result.parsed;
  return { ...p, steps: p.steps.filter((s) => !st.off.has(s.section || '')) };
}

function review() {
  const { parsed, source, method } = st.result;
  const recipe = toRecipe(current(), source);
  const alerts = analyze(recipe);
  const sections = [...new Set(parsed.steps.map((s) => s.section || ''))];
  const unknown = parsed.ingredients.filter((i) => i.unknown).length;
  const ocr = /OCR/.test(method || '');
  let lastSection = null;

  return `
  <section class="card">
    <div class="card-head">
      <div>
        <div class="muted small">From ${source.url ? `<a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(source.site || new URL(source.url).hostname)}</a>` : esc(source.name || 'pasted text')} · ${esc(method || 'recipe data')}</div>
      </div>
      <div class="btn-row">
        <button class="btn" data-action="ai-tidy" title="Philibert's chat model re-reads the original and sorts out ingredients and steps">✨ Tidy up with Philibert</button>
        <button class="btn ghost" data-action="restart">Start over</button>
      </div>
    </div>
    <label class="field"><span>Name</span><input value="${esc(parsed.name)}" data-input="name"></label>
    ${ocr ? '<div class="callout warn">Read from an image. Text recognition can misread numbers (for example 7 g as 1 g). Check every amount below against the original.</div>' : ''}
    ${st.busy ? `<div class="busy"><span class="spinner" aria-hidden="true"></span>${esc(st.busy)}</div>` : ''}
    ${st.error ? `<div class="callout warn">${esc(st.error)}</div>` : ''}
  </section>

  ${alertsPanel(alerts, recipe, { heading: 'Read this before you start' })}

  ${
    sections.length > 1
      ? `<section class="card">
      <h2>Sections</h2>
      <p class="muted small">This recipe has several parts. Untick the ones you don't want as steps, for example a second baking method.</p>
      ${sections
        .map(
          (s) => `<label class="toggle"><input type="checkbox" data-change="section" data-s="${esc(s)}" ${st.off.has(s) ? '' : 'checked'}><span>${esc(s || 'Main steps')} <span class="muted small">(${
            parsed.steps.filter((x) => (x.section || '') === s).length
          } steps)</span></span></label>`,
        )
        .join('')}
    </section>`
      : ''
  }

  <div class="grid-2">
    <section class="card">
      <h2>Ingredients</h2>
      ${unknown ? `<p class="callout warn small">${unknown} amount${unknown > 1 ? 's' : ''} could not be converted to grams. Fill them in or fix them after saving.</p>` : ''}
      <table class="ing-table">
        <thead><tr><th>Ingredient</th><th class="num">Grams</th></tr></thead>
        <tbody>${parsed.ingredients
          .map(
            (i, n) => `<tr class="${i.unknown ? 'flag' : ''}">
          <td>${esc(i.name)}${i.flour ? ' <span class="badge b-time">flour</span>' : ''}
            ${i.original && i.original !== i.name ? `<div class="muted small">${i.converted ? 'Converted from' : 'Text'}: “${esc(i.original)}”</div>` : ''}</td>
          <td class="num"><span class="inline-input amt"><input type="number" inputmode="decimal" step="any" min="0" value="${i.grams || ''}" data-change="grams" data-i="${n}" aria-label="${esc(i.name)} grams"><span>g</span></span></td>
        </tr>`,
          )
          .join('')}</tbody>
      </table>
      <p class="muted small">Total flour ${fmtGrams(parsed.ingredients.filter((i) => i.flour).reduce((s, i) => s + i.grams, 0))}</p>
    </section>

    <section class="card">
      <h2>Steps <span class="muted small">(${recipe.steps.length})</span></h2>
      <ol class="steps">
        ${current()
          .steps.map((s) => {
            const head = s.section !== lastSection && s.section ? `<li class="section-head">${esc(s.section)}</li>` : '';
            lastSection = s.section;
            const flagged = alerts.filter((a) => a.stepId === s.id);
            return `${head}<li>
            <div class="step-head"><strong>${esc(s.title)}</strong>
              <span class="badge ${s.type === 'wait' ? 'b-wait' : s.type === 'bake' ? 'b-bake' : 'b-active'}">${s.type === 'wait' ? 'Wait' : s.type === 'bake' ? 'Oven' : 'Hands-on'}</span>
              ${s.minutes ? `<span class="badge b-time">⏱ ${s.minutes}${s.maxMinutes ? '–' + s.maxMinutes : ''} min</span>` : ''}
              ${flagged.map((a) => `<span class="badge ${a.level === 'read' ? 'b-read' : 'b-check'}">${a.level === 'read' ? 'MUST READ' : 'MUST CHECK'}</span>`).join('')}
            </div>
            <div>${esc(s.detail)}</div>
            ${s.check ? `<div class="cue">✔ ${esc(s.check)}</div>` : ''}
          </li>`;
          })
          .join('')}
      </ol>
    </section>
  </div>

  ${parsed.notes ? `<section class="card"><h2>Notes</h2><p class="pre">${esc(parsed.notes)}</p></section>` : ''}

  <div class="btn-row end sticky-foot">
    <button class="btn" data-action="save" data-edit="1">Save and edit</button>
    <button class="btn primary big-touch" data-action="save">Save recipe</button>
  </div>`;
}

// ---------- running imports ----------
async function run(label, fn) {
  st.busy = label;
  st.error = '';
  bus.render();
  try {
    const out = await fn();
    st.off = new Set();
    const parsed = out.kind === 'structured' ? fromStructured(out.recipe) : parseText(out.text || '', { title: out.title || '' });
    if (!parsed.ingredients.length && !parsed.steps.length) throw new Error('No recipe found in that. Try pasting the text instead.');
    st.result = { parsed, source: out.source || { type: 'text' }, method: out.kind === 'structured' ? 'recipe data from the site' : out.method, raw: out.text || '' };
    // Leftover "notes / tips" sections are already moved to notes by the parser.
  } catch (e) {
    st.error = e.message;
  } finally {
    st.busy = '';
    bus.render();
  }
}

export async function importFileObj(file) {
  if (!file) return;
  st.tab = 'file';
  const isImg = file.type.startsWith('image/');
  await run(isImg ? 'Reading the picture… (text recognition, a few seconds)' : `Reading ${file.name}…`, async () => {
    const blob = isImg ? await shrinkImage(file, 2400) : file;
    const name = isImg ? (file.name || 'screenshot').replace(/\.\w+$/, '') + '.jpg' : file.name;
    return call('import_file', { name, type: blob.type || 'application/octet-stream', data: await blobToB64(blob) });
  });
}

function pick(capture) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = capture ? 'image/*' : '.pdf,.docx,.txt,.md,.html,.htm,image/*,application/pdf';
  if (capture) input.capture = 'environment';
  input.onchange = () => importFileObj(input.files?.[0]);
  input.click();
}

export const actions = {
  tab(el) {
    st.tab = el.dataset.t;
    st.error = '';
    bus.render();
  },
  'pick-file': () => pick(false),
  'take-photo': () => pick(true),
  restart() {
    st.result = null;
    st.error = '';
    bus.render();
  },
  save(el) {
    const p = current();
    p.name = p.name.trim() || 'Imported recipe';
    const r = toRecipe(p, st.result.source);
    saveRecipe(r);
    st.result = null;
    st.url = '';
    st.text = '';
    toast('Recipe saved');
    location.hash = el.dataset.edit ? `#/edit/${r.id}` : `#/recipe/${r.id}`;
  },
  async 'ai-tidy'() {
    const raw = st.result.raw || [st.result.parsed.name, ...st.result.parsed.ingredients.map((i) => i.original), ...st.result.parsed.steps.map((s) => s.detail), st.result.parsed.notes].join('\n');
    const keep = st.result;
    await run('Philibert is tidying up the recipe… (can take a minute)', async () => {
      const j = await call('structure', { text: raw });
      return { kind: 'structured', recipe: j.recipe, source: keep.source, text: raw };
    });
    if (!st.result) st.result = keep;
    else st.result.method = (keep.method || '') + ' · tidied by Philibert';
    bus.render();
  },
};

export const changes = {
  grams(el) {
    const i = st.result.parsed.ingredients[+el.dataset.i];
    i.grams = Math.max(0, parseFloat(el.value) || 0);
    i.unknown = !i.grams && i.unknown;
    if (i.grams) i.note = i.note?.startsWith('Was:') ? i.note : i.original && i.original !== i.name ? `Was: ${i.original}` : i.note;
  },
  section(el) {
    const s = el.dataset.s;
    if (el.checked) st.off.delete(s);
    else st.off.add(s);
    bus.render();
  },
};
export const inputs = {
  name(el) {
    st.result.parsed.name = el.value;
  },
};

export const submits = {
  url(form) {
    st.url = String(new FormData(form).get('url') || '').trim();
    run('Fetching the page…', () => call('import_url', { url: st.url }));
  },
  text(form) {
    st.text = String(new FormData(form).get('text') || '');
    if (!st.text.trim()) return toast('Paste the recipe text first');
    run('Reading the recipe…', async () => ({ kind: 'text', text: st.text, source: { type: 'text' }, method: 'pasted text' }));
  },
};

// Drag-and-drop and Ctrl+V paste of screenshots/files while this page is open.
export function mount() {
  const drop = document.getElementById('drop');
  if (drop) {
    drop.addEventListener('dragover', (e) => {
      e.preventDefault();
      drop.classList.add('over');
    });
    drop.addEventListener('dragleave', () => drop.classList.remove('over'));
    drop.addEventListener('drop', (e) => {
      e.preventDefault();
      drop.classList.remove('over');
      importFileObj(e.dataTransfer.files?.[0]);
    });
  }
  document.addEventListener('paste', onPaste);
}
export function unmount() {
  document.removeEventListener('paste', onPaste);
}
function onPaste(e) {
  if (st.result || st.busy) return;
  const file = [...(e.clipboardData?.files || [])][0];
  if (file) {
    e.preventDefault();
    importFileObj(file);
    return;
  }
  const text = e.clipboardData?.getData('text') || '';
  if (st.tab !== 'text' && /^https?:\/\/\S+$/.test(text.trim()) && !e.target.closest?.('input,textarea')) {
    st.tab = 'link';
    st.url = text.trim();
    bus.render();
  }
}
