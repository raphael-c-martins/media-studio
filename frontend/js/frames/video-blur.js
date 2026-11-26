// Controle da aba Frames para mascaras de placa com rastreamento, corte e exportacao MP4.

import { $, el, show } from '../core/dom.js';
import { formatShortTime, safeFilename } from '../core/format.js';
import { request, triggerDownload } from '../core/api.js';
import { toast } from '../core/toast.js';

const LOW_CONF_THRESHOLD = 0.55;
const HANDLES = ['nw', 'ne', 'sw', 'se'];

const clamp01 = (v) => Math.max(0, Math.min(1, Number.isFinite(v) ? v : 0));

function clampBox(x, y, w, h) {
  const cw = Math.max(0.01, Math.min(1, w));
  const ch = Math.max(0.01, Math.min(1, h));
  const cx = Math.max(0, Math.min(1 - cw, x));
  const cy = Math.max(0, Math.min(1 - ch, y));
  return { x: cx, y: cy, w: cw, h: ch };
}

export function resolveBoxAtTime(keyframes, t) {
  if (!keyframes || !keyframes.length) return null;
  if (keyframes.length === 1) {
    const kf = keyframes[0];
    return kf.visible === false ? null : { ...clampBox(kf.x, kf.y, kf.w, kf.h), confidence: kf.confidence ?? 1 };
  }
  const first = keyframes[0];
  const last = keyframes[keyframes.length - 1];
  if (t < first.t - 1e-4 || t > last.t + 1e-4) return null;
  if (t <= first.t + 1e-4) {
    return first.visible === false ? null : { ...clampBox(first.x, first.y, first.w, first.h), confidence: first.confidence ?? 1 };
  }
  if (t >= last.t - 1e-4) {
    return last.visible === false ? null : { ...clampBox(last.x, last.y, last.w, last.h), confidence: last.confidence ?? 1 };
  }

  let lo = 0;
  let hi = keyframes.length - 2;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (keyframes[mid].t <= t) lo = mid + 1;
    else hi = mid - 1;
  }
  const idx = Math.max(0, Math.min(keyframes.length - 2, hi));
  const k0 = keyframes[idx];
  const k1 = keyframes[idx + 1];

  if (Math.abs(t - k1.t) <= 1e-4) {
    return k1.visible === false ? null : { ...clampBox(k1.x, k1.y, k1.w, k1.h), confidence: k1.confidence ?? 1 };
  }
  if (k0.visible === false) return null;
  if (k1.visible === false) {
    return { ...clampBox(k0.x, k0.y, k0.w, k0.h), confidence: k0.confidence ?? 1 };
  }
  const dt = k1.t - k0.t;
  const alpha = dt > 1e-6 ? Math.max(0, Math.min(1, (t - k0.t) / dt)) : 0;
  const box = clampBox(
    k0.x + (k1.x - k0.x) * alpha,
    k0.y + (k1.y - k0.y) * alpha,
    k0.w + (k1.w - k0.w) * alpha,
    k0.h + (k1.h - k0.h) * alpha,
  );
  return { ...box, confidence: Math.min(k0.confidence ?? 1, k1.confidence ?? 1) };
}

export function initVideoBlur(hooks) {
  const state = {
    tracks: [],
    nextId: 1,
    activeTrackId: null,
    drawMode: false,
    busy: false,
    trimStart: 0,
    trimEnd: 0,
    muteAudio: false,
    applyCrop: false,
    drag: null,
    exportAbort: null,
    exportBlobUrl: null,
    exportFilename: '',
  };

  const overlay = $('#blur-overlay');
  const player = $('#player');
  const view = $('#frame-view');

  const activeTrack = () => state.tracks.find((tr) => tr.id === state.activeTrackId) || null;

  function revokeExportUrl() {
    const videoEl = $('#video-export-preview');
    if (videoEl) {
      videoEl.pause();
      videoEl.removeAttribute('src');
      videoEl.load();
    }
    if (state.exportBlobUrl) {
      URL.revokeObjectURL(state.exportBlobUrl);
      state.exportBlobUrl = null;
    }
  }

  function setDrawMode(enabled) {
    state.drawMode = Boolean(enabled);
    player.classList.toggle('blur-drawing', state.drawMode);
    $('#btn-blur-draw').setAttribute('aria-pressed', String(state.drawMode));
    $('#btn-blur-draw').textContent = state.drawMode ? 'Cancelar marcação' : 'Marcar placa';
  }

  function upsertKeyframe(track, kf) {
    const roundedT = Number(kf.t.toFixed(4));
    const nextKf = { ...kf, t: roundedT };
    const idx = track.keyframes.findIndex((item) => Math.abs(item.t - roundedT) < 0.02);
    if (idx >= 0) track.keyframes[idx] = nextKf;
    else track.keyframes.push(nextKf);
    track.keyframes.sort((a, b) => a.t - b.t);
  }

  function syncOverlay() {
    const video = hooks.getVideo();
    if (!video || !view.clientWidth || !view.clientHeight) {
      show(overlay, false);
      return;
    }
    overlay.style.left = `${view.offsetLeft}px`;
    overlay.style.top = `${view.offsetTop}px`;
    overlay.style.width = `${view.clientWidth}px`;
    overlay.style.height = `${view.clientHeight}px`;
    const visible = state.drawMode || state.tracks.length > 0;
    show(overlay, visible);
    if (visible) renderOverlayBoxes();
  }

  function renderOverlayBoxes() {
    const t = hooks.getTime();
    const nodes = [];
    for (const track of state.tracks) {
      const box = resolveBoxAtTime(track.keyframes, t);
      if (!box) continue;
      const isActive = track.id === state.activeTrackId;
      const isLow = (box.confidence ?? 1) < LOW_CONF_THRESHOLD;
      const cls = ['blur-box', isActive ? 'active' : '', isLow ? 'low-conf' : ''].filter(Boolean).join(' ');
      const boxEl = el('div', {
        class: cls,
        dataset: { trackId: track.id },
        style: `left:${box.x * 100}%;top:${box.y * 100}%;width:${box.w * 100}%;height:${box.h * 100}%`,
      }, [
        el('span', { class: 'blur-box-label', text: track.label }),
      ]);
      if (isActive) {
        for (const corner of HANDLES) {
          boxEl.append(el('span', { class: `blur-handle blur-handle-${corner}`, dataset: { handle: corner } }));
        }
      }
      boxEl.addEventListener('pointerdown', (e) => startBoxDrag(e, track, box));
      boxEl.addEventListener('click', (e) => e.stopPropagation());
      nodes.push(boxEl);
    }
    if (state.drag?.type === 'draw' && state.drag.draftEl) {
      nodes.push(state.drag.draftEl);
    }
    overlay.replaceChildren(...nodes);
  }

  function renderPanel() {
    const listEl = $('#blur-track-list');
    show(listEl, state.tracks.length > 0);
    $('#btn-blur-clear').disabled = state.tracks.length === 0 || state.busy;

    listEl.replaceChildren(...state.tracks.map((track) => {
      const itemCls = track.id === state.activeTrackId ? 'track-item active' : 'track-item';
      const kfCount = track.keyframes.length;
      const lowCount = track.keyframes.filter((k) => k.visible !== false && (k.confidence ?? 1) < LOW_CONF_THRESHOLD).length;
      const meta = lowCount > 0 ? `${kfCount} pts (${lowCount} incertos)` : `${kfCount} pts`;
      return el('div', { class: itemCls }, [
        el('button', {
          type: 'button',
          class: 'track-select',
          text: `${track.label} · ${meta}`,
          onclick: () => { state.activeTrackId = track.id; renderPanel(); renderOverlayBoxes(); },
        }),
        el('button', {
          type: 'button',
          class: 'btn btn-ghost btn-sm',
          text: 'Remover',
          disabled: state.busy,
          onclick: () => removeTrack(track.id),
        }),
      ]);
    }));

    const track = activeTrack();
    show($('#blur-active-controls'), Boolean(track));
    if (!track) return;

    $('#select-blur-style').value = track.style;
    $('#range-blur-strength').value = String(track.strength);
    $('#blur-strength-value').textContent = String(track.strength);
    const marginPct = Math.round(track.margin * 100);
    $('#range-blur-margin').value = String(marginPct);
    $('#blur-margin-value').textContent = `${marginPct}%`;

    const t = hooks.getTime();
    const boxHere = resolveBoxAtTime(track.keyframes, t);
    $('#btn-blur-hide-from').textContent = boxHere ? 'Ocultar daqui' : 'Reexibir aqui';

    const lowPoints = track.keyframes.filter((k) => k.visible !== false && (k.confidence ?? 1) < LOW_CONF_THRESHOLD);
    show($('#btn-blur-next-low'), lowPoints.length > 0);
    $('#btn-blur-next-low').textContent = `Ponto incerto (${lowPoints.length})`;

    const visiblePts = track.keyframes.filter((k) => k.visible !== false).length;
    $('#blur-track-status').textContent = `${visiblePts}/${track.keyframes.length} pontos visíveis`;

    for (const id of ['#btn-blur-track-all', '#btn-blur-track-forward', '#btn-blur-hide-from', '#btn-blur-draw', '#btn-export-video']) {
      const btn = $(id);
      if (btn) btn.disabled = state.busy;
    }
  }

  function removeTrack(trackId) {
    state.tracks = state.tracks.filter((tr) => tr.id !== trackId);
    if (state.activeTrackId === trackId) {
      state.activeTrackId = state.tracks[0]?.id || null;
    }
    renderPanel();
    syncOverlay();
  }

  function startBoxDrag(event, track, startBox) {
    if (state.drawMode || state.busy) return;
    event.preventDefault();
    event.stopPropagation();
    hooks.pause();
    state.activeTrackId = track.id;
    const handle = event.target?.dataset?.handle || null;
    const rect = overlay.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    player.classList.add('blur-editing');
    event.currentTarget.setPointerCapture(event.pointerId);
    state.drag = {
      type: handle ? 'resize' : 'move',
      handle,
      pointerId: event.pointerId,
      trackId: track.id,
      startX: event.clientX,
      startY: event.clientY,
      rect,
      startBox: { ...startBox },
      currentBox: { ...startBox },
    };
    renderPanel();
    renderOverlayBoxes();
  }

  function handleOverlayPointerDown(event) {
    if (!state.drawMode || state.busy) return;
    event.preventDefault();
    event.stopPropagation();
    hooks.pause();
    const rect = overlay.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x0 = clamp01((event.clientX - rect.left) / rect.width);
    const y0 = clamp01((event.clientY - rect.top) / rect.height);
    const draftEl = el('div', { class: 'blur-box-draft', style: `left:${x0 * 100}%;top:${y0 * 100}%;width:0%;height:0%` });
    overlay.append(draftEl);
    overlay.setPointerCapture(event.pointerId);
    state.drag = { type: 'draw', pointerId: event.pointerId, rect, x0, y0, x1: x0, y1: y0, draftEl };
  }

  function handlePointerMove(event) {
    const drag = state.drag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (drag.type === 'draw') {
      drag.x1 = clamp01((event.clientX - drag.rect.left) / drag.rect.width);
      drag.y1 = clamp01((event.clientY - drag.rect.top) / drag.rect.height);
      const left = Math.min(drag.x0, drag.x1);
      const top = Math.min(drag.y0, drag.y1);
      const width = Math.abs(drag.x1 - drag.x0);
      const height = Math.abs(drag.y1 - drag.y0);
      drag.draftEl.style.left = `${left * 100}%`;
      drag.draftEl.style.top = `${top * 100}%`;
      drag.draftEl.style.width = `${width * 100}%`;
      drag.draftEl.style.height = `${height * 100}%`;
      return;
    }

    const dx = (event.clientX - drag.startX) / drag.rect.width;
    const dy = (event.clientY - drag.startY) / drag.rect.height;
    let { x, y, w, h } = drag.startBox;
    if (drag.type === 'move') {
      x = Math.max(0, Math.min(1 - w, x + dx));
      y = Math.max(0, Math.min(1 - h, y + dy));
    } else {
      const right = x + w;
      const bottom = y + h;
      if (drag.handle.includes('w')) {
        x = Math.max(0, Math.min(right - 0.015, x + dx));
        w = right - x;
      }
      if (drag.handle.includes('e')) {
        w = Math.max(0.015, Math.min(1 - x, w + dx));
      }
      if (drag.handle.includes('n')) {
        y = Math.max(0, Math.min(bottom - 0.015, y + dy));
        h = bottom - y;
      }
      if (drag.handle.includes('s')) {
        h = Math.max(0.015, Math.min(1 - y, h + dy));
      }
    }
    drag.currentBox = clampBox(x, y, w, h);
    const track = state.tracks.find((tr) => tr.id === drag.trackId);
    if (track) {
      upsertKeyframe(track, { t: hooks.getTime(), ...drag.currentBox, visible: true, source: 'manual', confidence: 1 });
      renderOverlayBoxes();
    }
  }

  function handlePointerUp(event) {
    const drag = state.drag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    state.drag = null;
    player.classList.remove('blur-editing');

    if (drag.type === 'draw') {
      drag.draftEl.remove();
      const left = Math.min(drag.x0, drag.x1);
      const top = Math.min(drag.y0, drag.y1);
      const width = Math.abs(drag.x1 - drag.x0);
      const height = Math.abs(drag.y1 - drag.y0);
      if (width < 0.01 || height < 0.01) {
        toast.info('Arraste uma área maior sobre a placa.');
        return;
      }
      const box = clampBox(left, top, width, height);
      const id = `placa-${state.nextId}`;
      const label = `Placa ${state.nextId}`;
      state.nextId += 1;
      const t = hooks.getTime();
      state.tracks.push({
        id,
        label,
        style: 'pixelate',
        strength: 16,
        margin: 0.15,
        keyframes: [{ t: Number(t.toFixed(4)), ...box, visible: true, source: 'manual', confidence: 1 }],
      });
      state.activeTrackId = id;
      setDrawMode(false);
      renderPanel();
      syncOverlay();
      toast.success(`${label} marcada. Clique em "Rastrear vídeo" para acompanhar o movimento.`);
      return;
    }

    renderPanel();
    syncOverlay();
  }

  async function runTrack(direction) {
    const video = hooks.getVideo();
    const track = activeTrack();
    if (!video || !track || state.busy) return;
    hooks.pause();
    const t = hooks.getTime();
    let box = resolveBoxAtTime(track.keyframes, t);
    if (!box) {
      toast.warning('A máscara está oculta neste quadro. Clique em "Reexibir aqui" antes de rastrear.');
      return;
    }

    state.busy = true;
    renderPanel();
    try {
      const payload = {
        anchor_time: t,
        box: { x: box.x, y: box.y, w: box.w, h: box.h },
        start_time: direction === 'forward' ? t : state.trimStart,
        end_time: state.trimEnd || video.duration,
        direction,
      };
      const res = await request(hooks.getVideoPath('/track'), { method: 'POST', json: payload, timeout: 0 });
      if (direction === 'forward') {
        const preserved = track.keyframes.filter((k) => k.t < t - 0.005);
        track.keyframes = [...preserved, ...res.keyframes].sort((a, b) => a.t - b.t);
      } else {
        track.keyframes = res.keyframes;
      }
      const warn = res.low_confidence_frames > 0
        ? ` (${res.low_confidence_frames} quadro(s) incerto(s) para conferir)`
        : '';
      toast.success(`Rastreamento concluído: ${res.visible_frames} quadros cobertos${warn}.`);
    } catch (err) {
      toast.error(err.message);
    } finally {
      state.busy = false;
      renderPanel();
      syncOverlay();
    }
  }

  function toggleVisibilityAtCurrentTime() {
    const track = activeTrack();
    if (!track || state.busy) return;
    const t = hooks.getTime();
    const current = resolveBoxAtTime(track.keyframes, t);
    if (current) {
      track.keyframes = track.keyframes.filter((k) => !(k.t > t + 0.005 && k.source === 'auto'));
      upsertKeyframe(track, { t, x: current.x, y: current.y, w: current.w, h: current.h, visible: false, source: 'manual', confidence: 1 });
      toast.info(`${track.label} oculta a partir de ${formatShortTime(t)}.`);
    } else {
      const ref = [...track.keyframes].reverse().find((k) => k.visible !== false) || { x: 0.4, y: 0.4, w: 0.2, h: 0.1 };
      upsertKeyframe(track, { t, x: ref.x, y: ref.y, w: ref.w, h: ref.h, visible: true, source: 'manual', confidence: 1 });
      toast.info(`${track.label} reexibida em ${formatShortTime(t)}. Arraste para ajustar.`);
    }
    renderPanel();
    syncOverlay();
  }

  function jumpToNextLowConfidence() {
    const track = activeTrack();
    if (!track) return;
    const t = hooks.getTime();
    const lows = track.keyframes.filter((k) => k.visible !== false && (k.confidence ?? 1) < LOW_CONF_THRESHOLD);
    if (!lows.length) return;
    const next = lows.find((k) => k.t > t + 0.02) || lows[0];
    hooks.seek(next.t, { exact: true });
  }

  function updateTrimDisplay() {
    $('#trim-start').textContent = formatShortTime(state.trimStart);
    $('#trim-end').textContent = formatShortTime(state.trimEnd);
  }

  async function exportVideo() {
    const video = hooks.getVideo();
    if (!video || state.busy) return;
    hooks.pause();

    const crop = hooks.getCropParams();
    const payload = {
      tracks: state.tracks.map((tr) => ({
        id: tr.id,
        label: tr.label,
        style: tr.style,
        strength: tr.strength,
        margin: tr.margin,
        keyframes: tr.keyframes,
      })),
      trim_start: state.trimStart,
      trim_end: state.trimEnd,
      mute_audio: state.muteAudio,
      apply_crop: state.applyCrop,
      aspect_ratio: crop.aspect_ratio,
      focus_x: parseFloat(crop.focus_x),
      focus_y: parseFloat(crop.focus_y),
      zoom: parseFloat(crop.zoom),
      standardize: crop.standardize === 'true',
      fit_mode: crop.fit_mode,
    };

    const btn = $('#btn-export-video');
    state.busy = true;
    btn.textContent = 'Exportando MP4...';
    state.exportAbort = new AbortController();
    renderPanel();

    try {
      const response = await request(hooks.getVideoPath('/export-video'), {
        method: 'POST',
        json: payload,
        raw: true,
        timeout: 0,
        signal: state.exportAbort.signal,
      });
      const blob = await response.blob();
      revokeExportUrl();
      state.exportBlobUrl = URL.createObjectURL(blob);
      const stem = safeFilename(video.filename.replace(/\.[^.]+$/, ''), 'video');
      state.exportFilename = `${stem}_editado.mp4`;

      const w = response.headers.get('X-Export-Width') || '?';
      const h = response.headers.get('X-Export-Height') || '?';
      const dur = response.headers.get('X-Export-Duration') || '?';
      const aud = response.headers.get('X-Export-Audio') || 'none';
      const audText = aud === 'kept' ? 'com áudio' : (aud === 'muted' ? 'áudio silenciado' : 'sem faixa de áudio');
      $('#video-export-info').textContent = `${w} x ${h} px · ${dur} s · ${audText}`;

      const previewVideo = $('#video-export-preview');
      previewVideo.src = state.exportBlobUrl;
      show($('#video-export-modal'), true);
      toast.success('Vídeo MP4 pronto para revisar e baixar.');
    } catch (err) {
      if (err.name !== 'AbortError') toast.error(err.message);
    } finally {
      state.exportAbort = null;
      state.busy = false;
      btn.textContent = 'Exportar vídeo (MP4)';
      renderPanel();
    }
  }

  function reset() {
    if (state.exportAbort) {
      state.exportAbort.abort();
      state.exportAbort = null;
    }
    revokeExportUrl();
    state.tracks = [];
    state.nextId = 1;
    state.activeTrackId = null;
    state.busy = false;
    state.trimStart = 0;
    state.trimEnd = 0;
    state.muteAudio = false;
    state.applyCrop = false;
    state.drag = null;
    $('#check-mute-audio').checked = false;
    $('#check-video-apply-crop').checked = false;
    setDrawMode(false);
    updateTrimDisplay();
    renderPanel();
    syncOverlay();
  }

  function onVideoLoaded(videoData) {
    reset();
    state.trimStart = 0;
    state.trimEnd = videoData.duration;
    updateTrimDisplay();
  }

  function onModalClosed() {
    if (state.exportAbort) {
      state.exportAbort.abort();
      state.exportAbort = null;
    }
    revokeExportUrl();
  }

  // Ligação dos eventos de interface
  overlay.addEventListener('pointerdown', handleOverlayPointerDown);
  window.addEventListener('pointermove', handlePointerMove);
  window.addEventListener('pointerup', handlePointerUp);
  window.addEventListener('pointercancel', handlePointerUp);

  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(() => syncOverlay()).observe(view);
  }

  $('#btn-blur-draw').addEventListener('click', () => {
    if (state.busy) return;
    const next = !state.drawMode;
    if (next) {
      hooks.pause();
      hooks.seek(hooks.getTime(), { exact: true });
    }
    setDrawMode(next);
    syncOverlay();
  });

  $('#btn-blur-clear').addEventListener('click', () => {
    if (state.busy || !state.tracks.length) return;
    state.tracks = [];
    state.activeTrackId = null;
    setDrawMode(false);
    renderPanel();
    syncOverlay();
  });

  $('#select-blur-style').addEventListener('change', (e) => {
    const track = activeTrack();
    if (track) track.style = e.target.value;
  });

  $('#range-blur-strength').addEventListener('input', (e) => {
    const track = activeTrack();
    if (!track) return;
    track.strength = parseInt(e.target.value, 10) || 16;
    $('#blur-strength-value').textContent = String(track.strength);
  });

  $('#range-blur-margin').addEventListener('input', (e) => {
    const track = activeTrack();
    if (!track) return;
    const pct = parseInt(e.target.value, 10) || 0;
    track.margin = pct / 100;
    $('#blur-margin-value').textContent = `${pct}%`;
  });

  $('#btn-blur-track-all').addEventListener('click', () => runTrack('both'));
  $('#btn-blur-track-forward').addEventListener('click', () => runTrack('forward'));
  $('#btn-blur-hide-from').addEventListener('click', toggleVisibilityAtCurrentTime);
  $('#btn-blur-next-low').addEventListener('click', jumpToNextLowConfidence);

  $('#btn-trim-start').addEventListener('click', () => {
    const video = hooks.getVideo();
    if (!video) return;
    state.trimStart = hooks.getTime();
    if (state.trimEnd <= state.trimStart + 0.1) state.trimEnd = video.duration;
    updateTrimDisplay();
  });

  $('#btn-trim-end').addEventListener('click', () => {
    const t = hooks.getTime();
    if (t <= state.trimStart + 0.1) {
      toast.warning('O fim do corte precisa vir depois do início.');
      return;
    }
    state.trimEnd = t;
    updateTrimDisplay();
  });

  $('#btn-trim-reset').addEventListener('click', () => {
    const video = hooks.getVideo();
    state.trimStart = 0;
    state.trimEnd = video ? video.duration : 0;
    updateTrimDisplay();
  });

  $('#check-mute-audio').addEventListener('change', (e) => { state.muteAudio = e.target.checked; });
  $('#check-video-apply-crop').addEventListener('change', (e) => { state.applyCrop = e.target.checked; });
  $('#btn-export-video').addEventListener('click', exportVideo);
  $('#btn-video-export-download').addEventListener('click', () => {
    if (state.exportBlobUrl) triggerDownload(state.exportBlobUrl, state.exportFilename || 'video_editado.mp4');
  });

  return {
    reset,
    onVideoLoaded,
    onTimeChange: () => {
      if (state.tracks.length > 0) renderOverlayBoxes();
    },
    syncOverlay,
    isDrawing: () => state.drawMode,
    hasTracks: () => state.tracks.length > 0,
    isBusy: () => state.busy,
    onModalClosed,
  };
}
