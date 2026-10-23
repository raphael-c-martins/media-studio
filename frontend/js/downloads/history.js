// Tela "Histórico": lista, busca e ações sobre os arquivos baixados.

import { api, triggerDownload } from '../core/api.js';
import { $, el, show } from '../core/dom.js';
import { formatBytes, formatDate } from '../core/format.js';
import { toast } from '../core/toast.js';
import { onDownloadEvent } from './queue.js';

const STATUS_LABELS = {
  completed: 'Concluído', error: 'Erro', cancelled: 'Cancelado', queued: 'Na fila', downloading: 'Baixando',
};
const MEDIA_LABELS = { video: 'Vídeo', audio: 'Áudio', image: 'Imagem' };
let searchTimer = null;
let visible = false;

function action(label, onClick, variant = 'btn-secondary') {
  return el('button', { type: 'button', class: `btn ${variant} btn-sm`, text: label, onclick: onClick });
}

async function run(path, options = {}) {
  try {
    await api.post(path, undefined, options);
  } catch (err) {
    toast.error(err.message);
  }
}

async function removeItem(item) {
  const deleteFile = item.status === 'completed' && item.file_name
    && window.confirm(`Apagar também o arquivo "${item.file_name}" do disco?\n\nOK apaga o arquivo. Cancelar remove só do histórico.`);
  try {
    await api.del(`/api/history/${encodeURIComponent(item.id)}?delete_file=${deleteFile ? 'true' : 'false'}`);
    toast.info(deleteFile ? 'Registro e arquivo removidos.' : 'Registro removido do histórico.');
    loadHistory();
  } catch (err) {
    toast.error(err.message);
  }
}

function renderRow(item) {
  const id = encodeURIComponent(item.id);
  const done = item.status === 'completed' && item.file_name;
  const actions = [];
  if (done) {
    actions.push(
      action('Salvar', () => triggerDownload(`/api/history/${id}/file`)),
      action('Abrir', () => run(`/api/history/${id}/open-file`)),
      action('Pasta', () => run(`/api/history/${id}/open-folder`)),
    );
  }
  actions.push(action('Excluir', () => removeItem(item), 'btn-danger'));

  const statusCell = el('td', {}, [el('span', { class: `status-${item.status}`, text: STATUS_LABELS[item.status] || item.status })]);
  if (item.error_message) statusCell.title = item.error_message;

  return el('tr', {}, [
    el('td', {}, [
      el('div', { class: 'cell-title', title: item.title || '', text: item.title || 'Sem título' }),
      el('div', { class: 'muted small', text: item.author || '' }),
    ]),
    el('td', { text: item.platform || '-' }),
    el('td', { text: MEDIA_LABELS[item.media_type] || item.media_type || '-' }),
    el('td', { class: 'num mono', text: formatBytes(item.file_size) }),
    el('td', { class: 'mono', text: formatDate(item.created_at) }),
    statusCell,
    el('td', {}, [el('div', { class: 'row-actions' }, actions)]),
  ]);
}

export async function loadHistory() {
  const params = new URLSearchParams({ limit: '200' });
  const search = $('#history-search').value.trim();
  const platform = $('#history-platform').value;
  if (search) params.set('search', search);
  if (platform !== 'all') params.set('platform', platform);
  try {
    const items = await api.get(`/api/history?${params}`);
    $('#history-body').replaceChildren(...items.map(renderRow));
    show($('#history-empty'), items.length === 0);
  } catch (err) {
    toast.error(err.message);
  }
}

export function setHistoryVisible(isVisible) {
  visible = isVisible;
  if (visible) loadHistory();
}

export function initHistory() {
  $('#btn-history-refresh').addEventListener('click', loadHistory);
  $('#history-platform').addEventListener('change', loadHistory);
  $('#history-search').addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadHistory, 300);
  });
  onDownloadEvent((event) => {
    if (visible && ['download_completed', 'download_error', 'download_cancelled'].includes(event)) loadHistory();
  });
}
