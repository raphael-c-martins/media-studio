// Tela "Frames": extração de vídeo e preparo/recorte de fotos com ponto focal e zoom.

import { api, request } from '../core/api.js';
import { $, $$, el, show } from '../core/dom.js';
import { formatShortTime, formatTime, safeFilename } from '../core/format.js';
import { toast } from '../core/toast.js';
import { Gallery } from './gallery.js';
import { initShortcuts } from './shortcuts.js';

const ASPECT_RATIOS = { '16:9': 16 / 9, '9:16': 9 / 16, '1:1': 1, '4:5': 4 / 5 };
const VIDEO_PATTERN = /\.(mp4|mov|mkv|webm|m4v|avi|ogg)$/i;
const IMAGE_PATTERN = /\.(jpg|jpeg|png|webp|heic|heif)$/i;
const RAW_PATTERN = /\.(dng|cr2|cr3|nef|arw|orf|rw2)$/i;

const state = {
  mode: null, // 'video' | 'image' | null
  video: null,
  image: null,
  time: 0,
  fps: 30,
  playing: false,
  playTimer: null,
  fetching: false,
  pendingTime: null,
  burstStart: 0,
  burstEnd: 0,
  samples: [],
  focusX: 0.5,
  focusY: 0.5,
  zoom: 1.0,
  loupe: false,
  loupeZoom: 2.5,
  active: false,
  dragging: null,
};
let gallery;

const videoPath = (suffix = '') => `/api/frames/videos/${encodeURIComponent(state.video.video_id)}${suffix}`;
const imagePath = (suffix = '') => `/api/frames/images/${encodeURIComponent(state.image.image_id)}${suffix}`;

function clampUnit(value) {
  return Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0.5));
}

function getMediaDimensions() {
  const view = $('#frame-view');
  if (state.mode === 'image' && state.image) {
    return { width: state.image.width, height: state.image.height };
  }
  if (state.mode === 'video' && state.video) {
    return { width: state.video.width, height: state.video.height };
  }
  return { width: view.naturalWidth || 0, height: view.naturalHeight || 0 };
}

function computeCropBox(width, height, aspectRatio, focusX, focusY, zoom) {
  if (!width || !height) return null;
  const target = ASPECT_RATIOS[aspectRatio] || (width / height);
  let baseW;
  let baseH;
  if (width / height > target) {
    baseH = height;
    baseW = Math.min(width, Math.max(1, Math.floor(height * target)));
  } else {
    baseW = width;
    baseH = Math.min(height, Math.max(1, Math.floor(width / target)));
  }
  const cropW = zoom === 1 ? baseW : Math.min(width, Math.max(1, Math.round(baseW / zoom)));
  const cropH = zoom === 1 ? baseH : Math.min(height, Math.max(1, Math.round(baseH / zoom)));
  const cx = Math.round(clampUnit(focusX) * width);
  const cy = Math.round(clampUnit(focusY) * height);
  const x = Math.max(0, Math.min(width - cropW, cx - Math.floor(cropW / 2)));
  const y = Math.max(0, Math.min(height - cropH, cy - Math.floor(cropH / 2)));
  return { x, y, cropW, cropH, widthKept: cropW / width };
}

function getCropParams() {
  return {
    format: $('#select-format').value,
    aspect_ratio: $('#select-aspect').value,
    fit_mode: $('#select-fit-mode').value,
    standardize: $('#check-standardize').checked ? 'true' : 'false',
    focus_x: state.focusX.toFixed(4),
    focus_y: state.focusY.toFixed(4),
    zoom: state.zoom.toFixed(2),
  };
}

// ---------------------------------------------------------------- envio e modos

async function closeCurrentMedia() {
  if (state.video) {
    const id = state.video.video_id;
    state.video = null;
    api.del(`/api/frames/videos/${encodeURIComponent(id)}`).catch(() => {});
  }
  if (state.image) {
    const id = state.image.image_id;
    state.image = null;
    api.del(`/api/frames/images/${encodeURIComponent(id)}`).catch(() => {});
  }
  state.mode = null;
}

function setModeUI(mode) {
  const isImage = mode === 'image';
  $('#player').classList.toggle('photo-mode', isImage);
  show($('#timeline-box'), !isImage);
  show($('#meta-fps-wrap'), !isImage);
  show($('#panel-burst'), !isImage);
  show($('#panel-samples-box'), !isImage);
  show($('#image-tools'), isImage);
  if (isImage) show($('#samples-panel'), false);

  $('#meta-duration-label').textContent = isImage ? 'Arquivo' : 'Duração';
  $('#btn-capture').textContent = isImage ? 'Exportar foto cortada' : 'Capturar quadro';
}

function resetFocus(render = true) {
  state.focusX = 0.5;
  state.focusY = 0.5;
  state.zoom = 1.0;
  $('#range-zoom').value = '1';
  if (render) updateCropGuide();
}

async function uploadVideoFile(file) {
  const form = new FormData();
  form.append('file', file);
  const data = await request('/api/frames/videos', { method: 'POST', body: form });
  await closeCurrentMedia();
  state.mode = 'video';
  state.video = data;
  state.fps = Math.round(data.fps) || 30;
  state.time = 0;
  state.burstStart = 0;
  state.burstEnd = 0;
  state.samples = [];

  setModeUI('video');
  $('#check-standardize').checked = false;
  $('#select-fit-mode').value = 'crop';
  resetFocus(false);

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
}

async function uploadImageFile(file) {
  const form = new FormData();
  form.append('file', file);
  const data = await request('/api/frames/images', { method: 'POST', body: form });
  await closeCurrentMedia();
  state.mode = 'image';
  state.image = data;
  state.samples = [];

  setModeUI('image');
  $('#select-aspect').value = '4:5';
  $('#select-fit-mode').value = 'crop';
  $('#check-standardize').checked = true;
  resetFocus(false);

  $('#meta-filename').textContent = data.filename;
  $('#meta-resolution').textContent = `${data.width} x ${data.height}`;
  const notes = [];
  if (data.orientation_applied) notes.push('EXIF corrigido');
  if (data.color_profile && data.color_profile.includes('->')) notes.push('sRGB');
  $('#meta-duration').textContent = notes.length ? `Foto (${notes.join(', ')})` : 'Foto';

  show($('#dropzone'), false);
  show($('#frames-workspace'), true);
  show($('#btn-change-video'), true);
  $('#frame-view').src = `${imagePath('/preview')}?v=${Date.now()}`;
  toast.success('Foto carregada.');
}

async function handleFile(file) {
  if (!file) return;
  if (RAW_PATTERN.test(file.name)) {
    toast.error('Arquivos RAW (.dng) não são suportados diretamente. Converta para JPG, PNG ou HEIC.');
    return;
  }
  const isVideo = VIDEO_PATTERN.test(file.name);
  const isImage = IMAGE_PATTERN.test(file.name);
  if (!isVideo && !isImage) {
    toast.error('Escolha um vídeo (MP4, MOV, MKV, WebM, AVI) ou foto (JPG, PNG, WebP, HEIC).');
    return;
  }

  pause();
  const status = $('#upload-status');
  status.textContent = `Enviando ${file.name}...`;
  show(status, true);
  try {
    if (isImage) {
      await uploadImageFile(file);
    } else {
      await uploadVideoFile(file);
    }
  } catch (err) {
    toast.error(err.message);
  } finally {
    show(status, false);
    $('#video-file').value = '';
  }
}

// ---------------------------------------------------------------- navegação (vídeo)

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
  if (state.mode !== 'video' || !state.video) return;
  state.time = Math.max(0, Math.min(time, state.video.duration));
  updateTimeline();
  loadPreview(state.time);
}

function play() {
  if (state.playing || state.mode !== 'video' || !state.video) return;
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

// ---------------------------------------------------------------- captura e exportação

function addMarker(time) {
  if (!state.video?.duration) return;
  const percent = (time / state.video.duration) * 100;
  $('#markers').append(el('div', { class: 'marker', style: `left:${percent}%`, title: formatTime(time) }));
}

async function imageSize(blob) {
  const bitmap = await createImageBitmap(blob);
  const size = { width: bitmap.width, height: bitmap.height };
  bitmap.close();
  return size;
}

function notifyCropWarnings(rawHeader) {
  if (!rawHeader) return;
  const warnings = rawHeader.split(',').filter(Boolean);
  if (warnings.includes('wide_crop')) {
    toast.warning('A foto é bem larga para 4:5: confira se o veículo não foi cortado nas bordas.');
  }
  if (warnings.includes('low_resolution')) {
    toast.warning('Recorte abaixo de 720x900 px; a imagem pode perder nitidez.');
  }
}

async function captureAt(time) {
  const cropParams = getCropParams();
  const params = new URLSearchParams({ time: time.toFixed(3), ...cropParams });
  const response = await request(`${videoPath('/frame')}?${params}`, { raw: true });
  notifyCropWarnings(response.headers.get('X-Crop-Warnings'));
  const blob = await response.blob();
  const { width, height } = await imageSize(blob);
  gallery.add({ blob, time, timeLabel: formatTime(time), width, height });
  addMarker(time);
}

async function exportImage() {
  if (!state.image) return;
  const cropParams = getCropParams();
  const params = new URLSearchParams(cropParams);
  const response = await request(`${imagePath('/crop')}?${params}`, { raw: true });
  notifyCropWarnings(response.headers.get('X-Crop-Warnings'));
  const blob = await response.blob();
  const { width, height } = await imageSize(blob);
  const ext = blob.type.split('/')[1]?.replace('jpeg', 'jpg') || 'png';
  const stem = safeFilename(state.image.filename.replace(/\.[^.]+$/, ''), 'foto');
  const ratioTag = cropParams.aspect_ratio === 'original' ? 'orig' : cropParams.aspect_ratio.replace(':', 'x');
  gallery.add({
    blob,
    time: Date.now() / 1000,
    timeLabel: `Foto ${width}x${height}`,
    width,
    height,
    filename: `${stem}_${ratioTag}.${ext}`,
    zipName: `${stem}_${ratioTag}.${ext}`,
  });
  toast.success(`Foto pronta (${width} x ${height} px) na galeria.`);
}

async function capture() {
  if (state.mode === 'image' && state.image) {
    try {
      await exportImage();
    } catch (err) {
      toast.error(err.message);
    }
    return;
  }
  if (state.mode === 'video' && state.video) {
    try {
      await captureAt(state.time);
      toast.success(`Quadro ${formatTime(state.time)} capturado.`);
    } catch (err) {
      toast.error(err.message);
    }
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
  if (state.mode !== 'video' || !state.video) return;
  if (state.burstEnd <= state.burstStart) markStart();
  const button = $('#btn-burst');
  button.disabled = true;
  const cropParams = getCropParams();
  const params = new URLSearchParams({
    start: state.burstStart.toFixed(3),
    end: state.burstEnd.toFixed(3),
    count: $('#select-burst-count').value,
    ...cropParams,
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
  if (state.mode !== 'video' || !state.video) return;
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

// ---------------------------------------------------------------- guia de corte, ponto focal e lupa

function updateCropWarning(geom, aspect, fitMode, standardize) {
  const box = $('#crop-warning');
  if (!geom || fitMode === 'contain_blur') {
    show(box, false);
    box.textContent = '';
    return;
  }
  const messages = [];
  if (aspect === '4:5' && geom.widthKept < 0.55) {
    messages.push('Foto larga para 4:5 (corta mais de 45% da largura): confira as pontas do carro ou troque para fundo desfocado.');
  }
  if ((aspect === '4:5' || standardize) && (geom.cropW < 720 || geom.cropH < 900)) {
    messages.push(`Recorte nativo de ${geom.cropW}x${geom.cropH} px (abaixo de 720x900): ampliar para 1080px pode tirar nitidez.`);
  }
  box.textContent = messages.join(' ');
  show(box, messages.length > 0);
}

function updateCropGuide() {
  const aspect = $('#select-aspect').value;
  const fitMode = $('#select-fit-mode').value;
  const standardize = $('#check-standardize').checked;
  const guide = $('#crop-guide');
  const view = $('#frame-view');
  const ratio = ASPECT_RATIOS[aspect];

  $('#zoom-value').textContent = `${state.zoom.toFixed(2)}x`;
  $('#focus-value').textContent = `Foco: ${Math.round(state.focusX * 100)}%, ${Math.round(state.focusY * 100)}%`;

  const { width, height } = getMediaDimensions();
  const geom = computeCropBox(width, height, aspect, state.focusX, state.focusY, state.zoom);
  updateCropWarning(geom, aspect, fitMode, standardize);

  const showBox = Boolean(view.clientWidth && geom && ((ratio && fitMode === 'crop') || state.zoom > 1.0));
  if (!showBox) {
    show(guide, false);
    return;
  }
  const scaleX = view.clientWidth / width;
  const scaleY = view.clientHeight / height;
  guide.style.left = `${view.offsetLeft + geom.x * scaleX}px`;
  guide.style.top = `${view.offsetTop + geom.y * scaleY}px`;
  guide.style.width = `${geom.cropW * scaleX}px`;
  guide.style.height = `${geom.cropH * scaleY}px`;
  show(guide, true);
}

function syncLoupeButtons() {
  for (const id of ['#btn-loupe', '#btn-loupe-image']) {
    const btn = $(id);
    if (btn) btn.setAttribute('aria-pressed', String(state.loupe));
  }
  $('#player').classList.toggle('loupe-active', state.loupe);
}

function toggleLoupe() {
  state.loupe = !state.loupe;
  syncLoupeButtons();
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

function setFocusFromClientPoint(clientX, clientY) {
  const rect = $('#frame-view').getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  state.focusX = clampUnit((clientX - rect.left) / rect.width);
  state.focusY = clampUnit((clientY - rect.top) / rect.height);
  updateCropGuide();
}

function initCropGuideDrag() {
  const guide = $('#crop-guide');
  guide.addEventListener('pointerdown', (e) => {
    if (state.loupe) return;
    const view = $('#frame-view');
    const { width, height } = getMediaDimensions();
    const geom = computeCropBox(width, height, $('#select-aspect').value, state.focusX, state.focusY, state.zoom);
    if (!geom || !view.clientWidth || !view.clientHeight) return;
    e.preventDefault();
    guide.setPointerCapture(e.pointerId);
    guide.classList.add('dragging');
    state.dragging = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      startFocusX: (geom.x + geom.cropW / 2) / width,
      startFocusY: (geom.y + geom.cropH / 2) / height,
      viewW: view.clientWidth,
      viewH: view.clientHeight,
    };
  });

  guide.addEventListener('pointermove', (e) => {
    if (!state.dragging || e.pointerId !== state.dragging.pointerId) return;
    const dx = (e.clientX - state.dragging.startX) / state.dragging.viewW;
    const dy = (e.clientY - state.dragging.startY) / state.dragging.viewH;
    state.focusX = clampUnit(state.dragging.startFocusX + dx);
    state.focusY = clampUnit(state.dragging.startFocusY + dy);
    updateCropGuide();
  });

  const stopDrag = (e) => {
    if (!state.dragging || e.pointerId !== state.dragging.pointerId) return;
    guide.classList.remove('dragging');
    state.dragging = null;
  };
  guide.addEventListener('pointerup', stopDrag);
  guide.addEventListener('pointercancel', stopDrag);
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
  $('#frame-view').addEventListener('click', (e) => {
    if (state.loupe) return;
    if (state.mode === 'image' || e.shiftKey) {
      setFocusFromClientPoint(e.clientX, e.clientY);
      return;
    }
    togglePlay();
  });
  $('#select-rate').addEventListener('change', () => { if (state.playing) { pause(); play(); } });
  $('#select-fps').addEventListener('change', (e) => { state.fps = parseInt(e.target.value, 10) || 30; updateTimeline(); });

  $('#btn-capture').addEventListener('click', capture);
  $('#btn-burst-start').addEventListener('click', markStart);
  $('#btn-burst-end').addEventListener('click', markEnd);
  $('#btn-burst').addEventListener('click', burst);
  $('#btn-samples').addEventListener('click', generateSamples);
  $('#btn-samples-add-all').addEventListener('click', addAllSamples);

  $('#select-aspect').addEventListener('change', updateCropGuide);
  $('#select-fit-mode').addEventListener('change', updateCropGuide);
  $('#check-standardize').addEventListener('change', updateCropGuide);
  $('#range-zoom').addEventListener('input', (e) => {
    state.zoom = Math.max(1, Math.min(4, parseFloat(e.target.value) || 1));
    updateCropGuide();
  });
  $('#btn-focus-reset').addEventListener('click', () => resetFocus(true));
  $('#frame-view').addEventListener('load', updateCropGuide);
  window.addEventListener('resize', updateCropGuide);
  initCropGuideDrag();

  $('#btn-loupe').addEventListener('click', toggleLoupe);
  $('#btn-loupe-image').addEventListener('click', toggleLoupe);
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
  }, () => state.active && state.mode === 'video' && Boolean(state.video) && $('.modal:not(.hidden)') === null);

  // Libera os arquivos temporários no servidor ao fechar a aba.
  window.addEventListener('pagehide', () => {
    if (state.video) {
      fetch(videoPath(), { method: 'DELETE', headers: { 'X-Media-Studio': '1' }, keepalive: true }).catch(() => {});
    }
    if (state.image) {
      fetch(imagePath(), { method: 'DELETE', headers: { 'X-Media-Studio': '1' }, keepalive: true }).catch(() => {});
    }
  });
}
