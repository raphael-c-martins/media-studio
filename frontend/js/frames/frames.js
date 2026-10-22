// Tela "Frames": envio do vídeo, navegação quadro a quadro, captura, sequência, sugestões e lupa.

import { api, request } from '../core/api.js';
import { $, $$, el, show } from '../core/dom.js';
import { formatShortTime, formatTime } from '../core/format.js';
import { toast } from '../core/toast.js';
import { Gallery } from './gallery.js';
import { initShortcuts } from './shortcuts.js';

const ASPECT_RATIOS = { '16:9': 16 / 9, '9:16': 9 / 16, '1:1': 1, '4:5': 4 / 5 };
const VIDEO_PATTERN = /\.(mp4|mov|mkv|webm|m4v|avi|ogg)$/i;

const state = {
  video: null,
  time: 0,
  fps: 30,
  playing: false,
  playTimer: null,
  fetching: false,
  pendingTime: null,
  burstStart: 0,
  burstEnd: 0,
  samples: [],
  loupe: false,
  loupeZoom: 2.5,
  active: false,
};
let gallery;

const videoPath = (suffix = '') => `/api/frames/videos/${encodeURIComponent(state.video.video_id)}${suffix}`;

// ---------------------------------------------------------------- envio

async function closeCurrentVideo() {
  if (!state.video) return;
  const id = state.video.video_id;
  state.video = null;
  api.del(`/api/frames/videos/${encodeURIComponent(id)}`).catch(() => {});
}

async function handleFile(file) {
  if (!file) return;
  if (!VIDEO_PATTERN.test(file.name)) {
    toast.error('Escolha um arquivo de vídeo (MP4, MOV, MKV, WebM, M4V ou AVI).');
    return;
  }
  pause();
  const status = $('#upload-status');
  status.textContent = `Enviando ${file.name}...`;
  show(status, true);

  const form = new FormData();
  form.append('file', file);
  try {
    const data = await request('/api/frames/videos', { method: 'POST', body: form });
    await closeCurrentVideo();
    state.video = data;
    state.fps = Math.round(data.fps) || 30;
    state.time = 0;
    state.burstStart = 0;
    state.burstEnd = 0;
    state.samples = [];

    $('#meta-filename').textContent = data.filename;
    $('#meta-resolution').textContent = `${data.width} x ${data.height}`;
    $('#meta-duration').textContent = formatTime(data.duration);
    $('#time-total').textContent = formatTime(data.duration);
    const fpsSelect = $('#select-fps');
    if (![...fpsSelect.options].some((o) => o.value === String(state.fps))) {
      fpsSelect.append(el('option', { value: String(state.fps), text: String(state.fps) }));
    }
    fpsSelect.value = String(state.fps);
    $('#timeline').max = data.duration;
    $('#markers').replaceChildren();
    $('#burst-start').textContent = formatShortTime(0);
    $('#burst-end').textContent = formatShortTime(0);
    show($('#samples-panel'), false);

    show($('#dropzone'), false);
    show($('#frames-workspace'), true);
    show($('#btn-change-video'), true);
    seek(0);
    toast.success('Vídeo carregado.');
    generateSamples();
  } catch (err) {
    toast.error(err.message);
  } finally {
    show(status, false);
    $('#video-file').value = '';
  }
}

// ---------------------------------------------------------------- navegação

function updateTimeline() {
  const duration = state.video?.duration || 0;
  $('#time-current').textContent = formatTime(state.time);
  $('#frame-current').textContent = Math.floor(state.time * state.fps);
  $('#frame-total').textContent = Math.floor(duration * state.fps);
  $('#timeline').value = state.time;
}

function loadPreview(time) {
  if (state.fetching) {
    state.pendingTime = time;
    return;
  }
  state.fetching = true;
  const url = `${videoPath('/preview')}?time=${time.toFixed(2)}`;
  const image = new Image();
  image.onload = () => {
    $('#frame-view').src = url;
    state.fetching = false;
    if (state.pendingTime !== null) {
      const next = state.pendingTime;
      state.pendingTime = null;
      loadPreview(next);
    }
  };
  image.onerror = () => { state.fetching = false; };
  image.src = url;
}

function seek(time) {
  if (!state.video) return;
  state.time = Math.max(0, Math.min(time, state.video.duration));
  updateTimeline();
  loadPreview(state.time);
}

function play() {
  if (state.playing || !state.video) return;
  state.playing = true;
  $('#btn-play').textContent = 'Pausar';
  const rate = parseFloat($('#select-rate').value) || 1;
  state.playTimer = setInterval(() => {
    if (state.time >= state.video.duration) {
      pause();
      seek(0);
      return;
    }
    seek(state.time + 1 / state.fps);
  }, Math.round(1000 / (state.fps * rate)));
}

function pause() {
  state.playing = false;
  clearInterval(state.playTimer);
  state.playTimer = null;
  $('#btn-play').textContent = 'Reproduzir';
}

const togglePlay = () => (state.playing ? pause() : play());

// ---------------------------------------------------------------- captura

function addMarker(time) {
  const percent = (time / state.video.duration) * 100;
  $('#markers').append(el('div', { class: 'marker', style: `left:${percent}%`, title: formatTime(time) }));
}

async function imageSize(blob) {
  const bitmap = await createImageBitmap(blob);
  const size = { width: bitmap.width, height: bitmap.height };
  bitmap.close();
  return size;
}

async function captureAt(time) {
  const params = new URLSearchParams({
    time: time.toFixed(3), format: $('#select-format').value, aspect_ratio: $('#select-aspect').value,
  });
  const response = await request(`${videoPath('/frame')}?${params}`, { raw: true });
  const blob = await response.blob();
  const { width, height } = await imageSize(blob);
  gallery.add({ blob, time, timeLabel: formatTime(time), width, height });
  addMarker(time);
}

async function capture() {
  if (!state.video) return;
  try {
    await captureAt(state.time);
    toast.success(`Quadro ${formatTime(state.time)} capturado.`);
  } catch (err) {
    toast.error(err.message);
  }
}

function markStart() {
  if (!state.video) return;
  state.burstStart = state.time;
  if (state.burstEnd <= state.burstStart) {
    state.burstEnd = Math.min(state.video.duration, state.burstStart + 2);
    $('#burst-end').textContent = formatShortTime(state.burstEnd);
  }
  $('#burst-start').textContent = formatShortTime(state.burstStart);
}

function markEnd() {
  if (!state.video) return;
  if (state.time <= state.burstStart) {
    toast.warning('O fim precisa vir depois do início.');
    return;
  }
  state.burstEnd = state.time;
  $('#burst-end').textContent = formatShortTime(state.burstEnd);
}

function dataUrlToBlob(dataUrl) {
  const [header, base64] = dataUrl.split(',');
  const mime = header.match(/data:([^;]+)/)[1];
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  return new Blob([bytes], { type: mime });
}

async function burst() {
  if (!state.video) return;
  if (state.burstEnd <= state.burstStart) markStart();
  const button = $('#btn-burst');
  button.disabled = true;
  const params = new URLSearchParams({
    start: state.burstStart.toFixed(3), end: state.burstEnd.toFixed(3),
    count: $('#select-burst-count').value, format: $('#select-format').value, aspect_ratio: $('#select-aspect').value,
  });
  try {
    const data = await api.get(`${videoPath('/burst')}?${params}`, { timeout: 120000 });
    for (const frame of data.frames) {
      gallery.add({ blob: dataUrlToBlob(frame.data_url), time: frame.time, timeLabel: frame.time_label, width: frame.width, height: frame.height });
      addMarker(frame.time);
    }
    toast.success(`${data.frames.length} quadros da sequência na galeria.`);
  } catch (err) {
    toast.error(err.message);
  } finally {
    button.disabled = false;
  }
}

async function generateSamples() {
  if (!state.video) return;
  const button = $('#btn-samples');
  button.disabled = true;
  button.textContent = 'Gerando...';
  try {
    const data = await api.get(`${videoPath('/samples')}?count=${$('#select-sample-count').value}`, { timeout: 180000 });
    state.samples = data.samples;
    $('#samples-grid').replaceChildren(...data.samples.map((sample) => el('div', { class: 'thumb' }, [
      el('img', { src: sample.data_url, alt: `Sugestão em ${sample.time_label}`, loading: 'lazy', onclick: () => seek(sample.time) }),
      el('div', { class: 'thumb-foot mono' }, [
        el('span', { text: sample.time_label }),
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm', text: 'Adicionar',
          onclick: async () => {
            seek(sample.time);
            try { await captureAt(sample.time); } catch (err) { toast.error(err.message); }
          },
        }),
      ]),
    ])));
    show($('#samples-panel'), data.samples.length > 0);
  } catch (err) {
    toast.error(err.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Gerar sugestões';
  }
}

async function addAllSamples() {
  const button = $('#btn-samples-add-all');
  button.disabled = true;
  let added = 0;
  for (const sample of state.samples) {
    try {
      await captureAt(sample.time);
      added++;
    } catch (err) {
      toast.error(err.message);
      break;
    }
  }
  button.disabled = false;
  if (added) toast.success(`${added} quadros adicionados à galeria.`);
}

// ---------------------------------------------------------------- guia de corte e lupa

function updateCropGuide() {
  const ratio = ASPECT_RATIOS[$('#select-aspect').value];
  const guide = $('#crop-guide');
  const view = $('#frame-view');
  if (!ratio || !view.clientWidth) {
    show(guide, false);
    return;
  }
  const width = view.clientWidth;
  const height = view.clientHeight;
  const [guideWidth, guideHeight] = width / height > ratio ? [height * ratio, height] : [width, width / ratio];
  guide.style.width = `${guideWidth}px`;
  guide.style.height = `${guideHeight}px`;
  show(guide, true);
}

function toggleLoupe() {
  state.loupe = !state.loupe;
  $('#btn-loupe').setAttribute('aria-pressed', String(state.loupe));
  if (!state.loupe) show($('#loupe'), false);
}

function drawLoupe(event) {
  const view = $('#frame-view');
  const lens = $('#loupe');
  if (!state.loupe) return;
  const rect = view.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
    show(lens, false);
    return;
  }
  const playerRect = $('#player').getBoundingClientRect();
  lens.style.left = `${event.clientX - playerRect.left}px`;
  lens.style.top = `${event.clientY - playerRect.top}px`;
  show(lens, true);

  const canvas = $('#loupe-canvas');
  const ctx = canvas.getContext('2d');
  const scaleX = (view.naturalWidth || rect.width) / rect.width;
  const scaleY = (view.naturalHeight || rect.height) / rect.height;
  const sampleWidth = canvas.width / state.loupeZoom;
  const sampleHeight = canvas.height / state.loupeZoom;
  const sx = Math.max(0, Math.min(view.naturalWidth - sampleWidth, x * scaleX - sampleWidth / 2));
  const sy = Math.max(0, Math.min(view.naturalHeight - sampleHeight, y * scaleY - sampleHeight / 2));
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(view, sx, sy, sampleWidth, sampleHeight, 0, 0, canvas.width, canvas.height);
}

// ---------------------------------------------------------------- modais

function closeModals() {
  $$('.modal').forEach((modal) => show(modal, false));
}

// ---------------------------------------------------------------- inicialização

export function setFramesActive(active) {
  state.active = active;
  if (!active) pause();
}

export function initFrames() {
  gallery = new Gallery();
  gallery.render();

  const dropzone = $('#dropzone');
  dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    handleFile(e.dataTransfer.files?.[0]);
  });
  $('#video-file').addEventListener('change', (e) => handleFile(e.target.files?.[0]));
  $('#btn-change-video').addEventListener('click', () => $('#video-file').click());

  $('#timeline').addEventListener('input', (e) => seek(parseFloat(e.target.value)));
  $$('[data-step]').forEach((b) => b.addEventListener('click', () => seek(state.time + parseFloat(b.dataset.step))));
  $$('[data-frames]').forEach((b) => b.addEventListener('click', () => seek(state.time + parseInt(b.dataset.frames, 10) / state.fps)));
  $('#btn-play').addEventListener('click', togglePlay);
  $('#frame-view').addEventListener('click', togglePlay);
  $('#select-rate').addEventListener('change', () => { if (state.playing) { pause(); play(); } });
  $('#select-fps').addEventListener('change', (e) => { state.fps = parseInt(e.target.value, 10) || 30; updateTimeline(); });

  $('#btn-capture').addEventListener('click', capture);
  $('#btn-burst-start').addEventListener('click', markStart);
  $('#btn-burst-end').addEventListener('click', markEnd);
  $('#btn-burst').addEventListener('click', burst);
  $('#btn-samples').addEventListener('click', generateSamples);
  $('#btn-samples-add-all').addEventListener('click', addAllSamples);

  $('#select-aspect').addEventListener('change', updateCropGuide);
  $('#frame-view').addEventListener('load', updateCropGuide);
  window.addEventListener('resize', updateCropGuide);

  $('#btn-loupe').addEventListener('click', toggleLoupe);
  $('#frame-view').addEventListener('mousemove', drawLoupe);
  $('#frame-view').addEventListener('mouseleave', () => show($('#loupe'), false));
  $('#frame-view').addEventListener('wheel', (e) => {
    if (!state.loupe) return;
    e.preventDefault();
    state.loupeZoom = Math.min(6, Math.max(1.5, state.loupeZoom + (e.deltaY < 0 ? 0.5 : -0.5)));
    $('#loupe-zoom').textContent = `${state.loupeZoom.toFixed(1)}x`;
  }, { passive: false });

  $$('[data-close-modal]').forEach((b) => b.addEventListener('click', closeModals));
  $$('.modal').forEach((modal) => modal.addEventListener('click', (e) => { if (e.target === modal) closeModals(); }));
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModals(); });

  initShortcuts({
    togglePlay,
    stepFrames: (frames) => seek(state.time + frames / state.fps),
  }, () => state.active && Boolean(state.video) && $('.modal:not(.hidden)') === null);

  // Libera o arquivo temporário no servidor ao fechar a aba.
  window.addEventListener('pagehide', () => {
    if (state.video) {
      fetch(videoPath(), { method: 'DELETE', headers: { 'X-Media-Studio': '1' }, keepalive: true }).catch(() => {});
    }
  });
}
