// Tela "Configurações" e tema.

import { api } from '../core/api.js';
import { $ } from '../core/dom.js';
import { toast } from '../core/toast.js';
import { setDownloadDefaults } from './downloads.js';

const THEMES = ['system', 'light', 'dark'];
const THEME_LABELS = { system: 'Tema: sistema', light: 'Tema: claro', dark: 'Tema: escuro' };
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
let currentTheme = 'system';

export function applyTheme(theme) {
  currentTheme = THEMES.includes(theme) ? theme : 'system';
  const root = document.documentElement;
  root.dataset.theme = currentTheme;
  root.classList.toggle('prefers-dark', darkQuery.matches);
  $('#btn-theme').textContent = THEME_LABELS[currentTheme];
  try { localStorage.setItem('media-studio-theme', currentTheme); } catch (_) { /* armazenamento bloqueado */ }
}

async function saveTheme(theme) {
  applyTheme(theme);
  $('#setting-theme').value = theme;
  try {
    await api.put('/api/settings', { theme });
  } catch (err) {
    toast.error(err.message);
  }
}

export async function loadSettings() {
  try {
    const settings = await api.get('/api/settings');
    $('#setting-folder').value = settings.download_folder || '';
    $('#setting-quality').value = settings.default_format;
    $('#setting-audio').value = settings.default_audio_format;
    $('#setting-theme').value = settings.theme;
    applyTheme(settings.theme);
    setDownloadDefaults(settings);
  } catch (err) {
    toast.error(err.message);
  }
}

async function handleSave(event) {
  event.preventDefault();
  const payload = {
    download_folder: $('#setting-folder').value.trim(),
    default_format: $('#setting-quality').value,
    default_audio_format: $('#setting-audio').value,
    theme: $('#setting-theme').value,
  };
  try {
    const result = await api.put('/api/settings', payload);
    if (result.settings?.download_folder) $('#setting-folder').value = result.settings.download_folder;
    applyTheme(payload.theme);
    setDownloadDefaults(payload);
    toast.success('Configurações salvas.');
  } catch (err) {
    toast.error(err.message);
  }
}

export function initSettings() {
  let saved = 'system';
  try { saved = localStorage.getItem('media-studio-theme') || 'system'; } catch (_) { /* armazenamento bloqueado */ }
  applyTheme(saved);
  darkQuery.addEventListener('change', () => applyTheme(currentTheme));

  $('#settings-form').addEventListener('submit', handleSave);
  $('#btn-theme').addEventListener('click', () => {
    saveTheme(THEMES[(THEMES.indexOf(currentTheme) + 1) % THEMES.length]);
  });
  $('#btn-choose-folder').addEventListener('click', async () => {
    try {
      const result = await api.post('/api/settings/choose-folder', undefined, { timeout: 130000 });
      if (result.success && result.path) $('#setting-folder').value = result.path;
    } catch (err) {
      toast.error(err.message);
    }
  });
  $('#btn-open-downloads-folder').addEventListener('click', async () => {
    try {
      await api.post('/api/history/open-downloads-folder');
    } catch (err) {
      toast.error(err.message);
    }
  });
}
