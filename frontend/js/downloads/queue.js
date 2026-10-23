// Fila de downloads: eventos em tempo real (SSE), painel flutuante e progresso na tela de download.

import { api, triggerDownload } from '../core/api.js';
import { $, el, show } from '../core/dom.js';
import { toast } from '../core/toast.js';

const listeners = new Set();
let currentDownloadId = null;
let reconnectDelay = 1000;

export function onDownloadEvent(callback) {
  listeners.add(callback);
}

export function trackInline(downloadId) {
  currentDownloadId = downloadId;
  setInline({ visible: true, status: 'Na fila', percent: 0, detail: 'Aguardando a vez...', state: '' });
}

function setInline({ visible = true, status, percent, detail, state }) {
  show($('#inline-progress'), visible);
  if (status !== undefined) $('#inline-status').textContent = status;
  if (percent !== undefined) {
    $('#inline-percent').textContent = `${percent}%`;
    $('#inline-bar').style.width = `${percent}%`;
  }
  if (detail !== undefined) $('#inline-detail').textContent = detail;
  if (state !== undefined) $('#inline-bar').className = `progress-fill ${state}`;
  show($('#btn-cancel-inline'), state === '');
}

export function resetInline() {
  currentDownloadId = null;
  show($('#inline-progress'), false);
}

export async function cancelDownload(downloadId) {
  try {
    await api.del(`/api/downloads/${encodeURIComponent(downloadId)}`);
  } catch (err) {
    toast.error(err.message);
  }
}

function openFolder(downloadId) {
  api.post(`/api/history/${encodeURIComponent(downloadId)}/open-folder`).catch((err) => toast.error(err.message));
}

function renderQueue(items) {
  const panel = $('#queue');
  const list = $('#queue-list');
  show(panel, items.length > 0);
  $('#queue-count').textContent = items.length;
  list.replaceChildren(...items.map((item) => {
    const progress = item.progress || 0;
    return el('div', { class: 'queue-item', id: `queue-${item.id}` }, [
      el('div', { class: 'queue-item-head' }, [
        el('span', { class: 'queue-item-title', title: item.title || item.url, text: item.title || item.url }),
        el('button', {
          type: 'button', class: 'btn btn-link btn-sm', text: 'Cancelar',
          onclick: () => cancelDownload(item.id),
        }),
      ]),
      el('div', { class: 'progress' }, [el('div', { class: 'progress-fill', style: `width:${progress}%` })]),
      el('div', { class: 'queue-item-foot mono' }, [
        el('span', { class: 'queue-speed', text: item.status === 'queued' ? 'Na fila' : [item.speed, item.eta].filter(Boolean).join(' · ') || 'Conectando' }),
        el('span', { class: 'queue-percent', text: `${progress}%` }),
      ]),
    ]);
  }));
}

export async function refreshQueue() {
  try {
    renderQueue(await api.get('/api/downloads/queue'));
  } catch (_) { /* o servidor pode estar reiniciando; a próxima atualização resolve */ }
}

function updateQueueItem(data) {
  const item = document.getElementById(`queue-${data.id}`);
  if (!item) return;
  item.querySelector('.progress-fill').style.width = `${data.progress}%`;
  item.querySelector('.queue-percent').textContent = `${data.progress}%`;
  item.querySelector('.queue-speed').textContent = [data.speed, data.eta].filter(Boolean).join(' · ');
}

function handleEvent({ event, data }) {
  if (!event || event === 'ping' || event === 'connected') return;
  const isCurrent = data && data.id === currentDownloadId;

  switch (event) {
    case 'download_queued':
    case 'download_started':
      refreshQueue();
      if (isCurrent && event === 'download_started') setInline({ status: 'Baixando', detail: 'Conectando...' });
      break;
    case 'download_progress':
      updateQueueItem(data);
      if (isCurrent) {
        setInline({ status: 'Baixando', percent: data.progress, detail: [data.speed, data.eta && `faltam ${data.eta}`].filter(Boolean).join(' · ') });
      }
      break;
    case 'download_completed':
      refreshQueue();
      triggerDownload(`/api/history/${encodeURIComponent(data.id)}/file`);
      toast.success(`Download concluído: ${data.title || data.file_name || 'arquivo'}`, {
        actions: [{ label: 'Abrir pasta', onClick: () => openFolder(data.id) }],
      });
      if (isCurrent) setInline({ status: 'Concluído', percent: 100, detail: data.file_name || '', state: 'done' });
      break;
    case 'download_error':
      refreshQueue();
      toast.error(`Falha no download: ${data.error_message || 'erro desconhecido'}`);
      if (isCurrent) setInline({ status: 'Falhou', detail: (data.error_message || '').slice(0, 120), state: 'failed' });
      break;
    case 'download_cancelled':
      refreshQueue();
      if (isCurrent) resetInline();
      toast.info('Download cancelado.');
      break;
    default:
      break;
  }
  listeners.forEach((callback) => callback(event, data));
}

function connect() {
  const source = new EventSource('/api/downloads/stream');
  source.onopen = () => {
    reconnectDelay = 1000;
    refreshQueue();
  };
  source.onmessage = (message) => {
    try {
      handleEvent(JSON.parse(message.data));
    } catch (_) { /* mensagem de manutenção da conexão */ }
  };
  source.onerror = () => {
    // Reconexão com espera crescente (até 30 s) se o servidor cair ou reiniciar.
    source.close();
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 30000);
  };
}

export function initQueue() {
  $('#queue-toggle').addEventListener('click', () => {
    const panel = $('#queue');
    panel.classList.toggle('collapsed');
    $('#queue-toggle').setAttribute('aria-expanded', String(!panel.classList.contains('collapsed')));
  });
  $('#btn-cancel-inline').addEventListener('click', () => {
    if (currentDownloadId) cancelDownload(currentDownloadId);
  });
  connect();
}
