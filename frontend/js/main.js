// Ponto de entrada: navegação entre as abas e inicialização dos módulos.

import { $$ } from './core/dom.js';
import { initDownloads } from './downloads/downloads.js';
import { initHistory, setHistoryVisible } from './downloads/history.js';
import { initQueue } from './downloads/queue.js';
import { initSettings, loadSettings } from './downloads/settings.js';
import { initFrames, setFramesActive } from './frames/frames.js';

const ROUTES = { '#baixar': 'download', '#historico': 'history', '#frames': 'frames', '#configuracoes': 'settings' };

function route() {
  const view = ROUTES[window.location.hash] || 'download';
  $$('.view').forEach((section) => section.classList.toggle('hidden', section.dataset.view !== view));
  $$('.tab').forEach((tab) => {
    const active = tab.dataset.view === view;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
  });
  setHistoryVisible(view === 'history');
  setFramesActive(view === 'frames');
  if (view === 'settings') loadSettings();
}

initSettings();
initDownloads();
initHistory();
initQueue();
initFrames();
loadSettings();

window.addEventListener('hashchange', route);
route();
