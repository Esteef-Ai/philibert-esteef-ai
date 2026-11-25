// Settings: this window's preferences, which of Philibert's models help, and backups.
import { esc, toast, bus } from '../ui.js';
import { prefs, setPref, call } from '../store.js';
import { testAlarm } from '../alarm.js';

export const title = () => 'Settings';

let ai = null; // {chat, vision} from Philibert

export function render() {
  const notif = 'Notification' in window ? Notification.permission : 'unsupported';
  return `
  <div class="page-head"><h1>Settings</h1></div>

  <section class="card">
    <h2>This window</h2>
    <label class="toggle"><input type="checkbox" data-change="pref" data-k="sound" ${prefs.sound ? 'checked' : ''}><span>Alarm sound when a timer ends</span></label>
    <label class="toggle"><input type="checkbox" data-change="pref" data-k="vibrate" ${prefs.vibrate ? 'checked' : ''}><span>Vibrate (touch screens)</span></label>
    <label class="toggle"><input type="checkbox" data-change="pref" data-k="showPercent" ${prefs.showPercent ? 'checked' : ''}><span>Show baker's percentages in ingredient lists</span></label>
    <div class="btn-row">
      <button class="btn" data-action="test-alarm">🔔 Test alarm</button>
      ${
        notif === 'default'
          ? '<button class="btn" data-action="notif">Allow notifications</button>'
          : `<span class="muted small">Notifications: ${notif === 'granted' ? 'allowed' : notif === 'denied' ? 'blocked in the browser' : 'not available here'}</span>`
      }
    </div>
  </section>

  <section class="card">
    <h2>Philibert helping</h2>
    <p class="muted">💬 Ask, ✨ Tidy up and 📷 photo checks use Philibert's own models on this computer. Nothing leaves it.</p>
    ${
      ai
        ? `<ul class="plain">
        <li><strong>Questions and tidying up:</strong> ${ai.chat ? esc(ai.chat) : '<span class="muted">no chat model yet - add one in Models</span>'}</li>
        <li><strong>Looking at photos and reading pictures:</strong> ${ai.vision ? esc(ai.vision) : '<span class="muted">no picture model yet - add “Eyes” in Models</span>'}</li>
      </ul>`
        : '<p class="muted">Asking Philibert…</p>'
    }
    <p class="muted small">Recipe links need INTERNET on (top right in Philibert). Screenshots and scanned PDFs are read by the text recognition built into Windows; on a Mac, by the picture model.</p>
  </section>

  <section class="card">
    <h2>Backup</h2>
    <p class="muted">Recipes, batches and photos are kept on the drive in <code>data/yeschef</code>.</p>
    <div class="btn-row">
      <button class="btn" data-action="export">Download backup</button>
      <label class="btn">Restore backup… <input type="file" accept="application/json,.json" hidden data-change="restore"></label>
    </div>
    <p class="muted small">A backup from Bread Lab (the stand-alone version) restores here too.</p>
  </section>`;
}

export function mount() {
  if (ai) return;
  call('ai_status')
    .then((j) => {
      ai = { chat: j.chat, vision: j.vision };
      bus.render();
    })
    .catch(() => {});
}

export const changes = {
  pref(el) {
    setPref(el.dataset.k, el.checked);
  },
  async restore(el) {
    const file = el.files?.[0];
    if (!file) return;
    if (!confirm('Replace all recipes and batches with this backup? The current ones are kept aside on the drive first.')) return;
    try {
      const j = await call('restore', { db: JSON.parse(await file.text()) });
      toast(`Restored ${j.recipes} recipes and ${j.batches} batches`);
      setTimeout(() => location.reload(), 700);
    } catch (e) {
      toast('Restore failed: ' + e.message);
    }
  },
};

export const actions = {
  'test-alarm': () => testAlarm(),
  async notif() {
    await Notification.requestPermission();
    bus.render();
  },
  async export() {
    try {
      const { db } = await call('export');
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([JSON.stringify(db, null, 2)], { type: 'application/json' }));
      a.download = `yes-chef-backup-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) {
      toast('Backup failed: ' + e.message);
    }
  },
};
