// Photos and AI help, shared by the batch page and cook mode.
import { esc, openModal, setModalBody, toast, shrinkImage, bus } from './ui.js';
import { store, saveBatch, uploadPhoto, aiPost } from './store.js';

// ----- photos -----
export function pickPhoto(batchId, stepId) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  input.capture = 'environment';
  input.onchange = async () => {
    const file = input.files?.[0];
    if (!file) return;
    toast('Uploading photo…');
    try {
      const url = await uploadPhoto(await shrinkImage(file));
      const b = store.state.batches[batchId];
      b.photos ??= [];
      b.photos.push({ url, stepId, at: Date.now() });
      saveBatch(b);
      toast('Photo saved');
      bus.render();
    } catch (e) {
      toast('Photo upload failed: ' + e.message);
    }
  };
  input.click();
}

export function photoGrid(b, stepId) {
  const list = (b.photos || []).filter((p) => !stepId || p.stepId === stepId);
  if (!list.length) return '';
  return `<div class="photos">${list
    .map((p) => {
      const step = b.recipe.steps.find((s) => s.id === p.stepId);
      const idx = b.photos.indexOf(p);
      return `<figure class="photo">
        <a href="${esc(p.url)}" target="_blank" rel="noopener"><img src="${esc(p.url)}" alt="${esc(step?.title || 'Photo')}" loading="lazy"></a>
        <figcaption>${esc(step?.title || '')}
          <button class="btn small" data-action="evaluate" data-b="${b.id}" data-p="${idx}">${p.evaluation ? 'Re-check' : 'Evaluate'}</button>
        </figcaption>
        ${p.evaluation ? `<div class="ai-answer small">${fmtAnswer(p.evaluation)}</div>` : ''}
      </figure>`;
    })
    .join('')}</div>`;
}

export async function evaluate(batchId, idx) {
  const b = store.state.batches[batchId];
  const p = b?.photos?.[idx];
  if (!p) return;
  openModal('Photo check', `<img class="modal-photo" src="${esc(p.url)}" alt=""><p class="muted">Philibert is looking at it… (the first look can take a minute while the picture model loads)</p>`);
  try {
    const { answer, model } = await aiPost('evaluate', { photoUrl: p.url, batchId, stepId: p.stepId });
    p.evaluation = answer;
    saveBatch(b);
    setModalBody(`<img class="modal-photo" src="${esc(p.url)}" alt=""><div class="ai-answer">${fmtAnswer(answer)}</div><p class="muted small">Philibert looked at it with ${esc(model || 'its picture model')}.</p>`);
  } catch (e) {
    setModalBody(`<img class="modal-photo" src="${esc(p.url)}" alt=""><div class="callout warn">${esc(e.message)}</div>`);
  }
}

// ----- ask -----
const chats = {}; // per batch/recipe: [{role, content}]

export function openAsk({ batchId, recipeId }) {
  const key = batchId || recipeId || 'general';
  chats[key] ??= [];
  const enabled = true; // Philibert says so itself if it has no model
  openModal('Ask Philibert', askBody(key, enabled), { wide: true });
  document.querySelector('.ask-form')?.setAttribute('data-key', key);
  document.querySelector('.ask-form')?.setAttribute('data-batch', batchId || '');
  document.querySelector('.ask-form')?.setAttribute('data-recipe', recipeId || '');
  document.querySelector('.ask-form textarea')?.focus();
}

function askBody(key, enabled) {
  const log = chats[key];
  return `
    ${enabled ? '' : '<div class="callout warn">The local LLM is not turned on yet. Set it up in <a href="#/settings">Settings → AI helpers</a>.</div>'}
    <div class="chat">${
      log.length
        ? log.map((m) => `<div class="msg ${m.role}">${m.role === 'assistant' ? fmtAnswer(m.content) : esc(m.content)}</div>`).join('')
        : '<p class="muted">Ask anything about this bake: “Dough feels too sticky, what now?”, “Is 30 minutes enough for the bench rest?”</p>'
    }</div>
    <form class="ask-form" data-key="${esc(key)}" onsubmit="return false">
      <textarea rows="2" placeholder="Type your question" ${enabled ? '' : 'disabled'}></textarea>
      <button class="btn primary" data-action="ask-send" ${enabled ? '' : 'disabled'}>Ask</button>
    </form>`;
}

export async function sendAsk() {
  const form = document.querySelector('.ask-form');
  const ta = form?.querySelector('textarea');
  const q = ta?.value.trim();
  if (!q) return;
  const key = form.dataset.key;
  const batchId = form.dataset.batch || undefined;
  const recipeId = form.dataset.recipe || undefined;
  const history = chats[key].slice();
  chats[key].push({ role: 'user', content: q });
  chats[key].push({ role: 'assistant', content: '…' });
  rerenderAsk(key, batchId, recipeId);
  try {
    const { answer } = await aiPost('ask', { question: q, batchId, recipeId, history });
    chats[key][chats[key].length - 1].content = answer;
  } catch (e) {
    chats[key][chats[key].length - 1].content = '⚠ ' + e.message;
  }
  rerenderAsk(key, batchId, recipeId);
}

function rerenderAsk(key, batchId, recipeId) {
  setModalBody(askBody(key, true));
  const form = document.querySelector('.ask-form');
  form?.setAttribute('data-batch', batchId || '');
  form?.setAttribute('data-recipe', recipeId || '');
  const chat = document.querySelector('.chat');
  if (chat) chat.scrollTop = chat.scrollHeight;
  form?.querySelector('textarea')?.focus();
}

// Plain text with simple line breaks and **bold**; everything escaped first.
export function fmtAnswer(t) {
  return esc(t)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>');
}

export const assistActions = {
  photo: (el) => pickPhoto(el.dataset.b, el.dataset.s),
  evaluate: (el) => evaluate(el.dataset.b, +el.dataset.p),
  ask: (el) => openAsk({ batchId: el.dataset.b, recipeId: el.dataset.r }),
  'ask-send': () => sendAsk(),
};
