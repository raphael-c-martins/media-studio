// Tela "Baixar": busca de link ou perfil, prévia, carrossel e galeria de perfil.

import { api, triggerDownload } from '../core/api.js';
import { $, $$, el, safeSrc, setBusy, show } from '../core/dom.js';
import { formatBytes, safeFilename } from '../core/format.js';
import { toast } from '../core/toast.js';
import { trackInline } from './queue.js';

const PLATFORM_HINTS = {
  auto: 'https://... ou @usuario',
  youtube: 'Link do vídeo, Shorts, playlist ou @canal',
  instagram: 'Link do post/Reels ou @usuario',
  twitter: 'Link do post ou @usuario',
  tiktok: 'Link do vídeo ou @usuario',
};
const QUALITY_PRESETS = [
  ['best', 'Melhor disponível'], ['4k', '4K (2160p)'], ['1080p', '1080p'], ['720p', '720p'], ['480p', '480p'],
];
const TYPE_LABELS = { video: 'Vídeo', reel: 'Reel', carousel: 'Carrossel', image: 'Foto' };

const state = {
  platform: 'auto',
  media: null,
  defaults: { default_format: 'best', default_audio_format: 'mp3' },
  carouselSelected: new Set(),
  profileSelected: new Set(),
};

export function setDownloadDefaults(settings) {
  state.defaults = { ...state.defaults, ...settings };
}

function detectPlatform(text) {
  const value = (text || '').trim().toLowerCase();
  if (/instagram\.com|instagr\.am/.test(value)) return 'instagram';
  if (/youtube\.com|youtu\.be/.test(value)) return 'youtube';
  if (/twitter\.com|(^|\/\/|www\.)x\.com/.test(value)) return 'twitter';
  if (/tiktok\.com/.test(value)) return 'tiktok';
  return null;
}

function selectPlatform(platform) {
  state.platform = platform;
  $$('#platform-select .seg').forEach((button) => {
    const active = button.dataset.platform === platform;
    button.classList.toggle('active', active);
    button.setAttribute('aria-checked', String(active));
  });
  $('#url-input').placeholder = PLATFORM_HINTS[platform] || PLATFORM_HINTS.auto;
}

function isProfileTarget(target) {
  const lower = target.toLowerCase();
  if (target.startsWith('@')) return true;
  if (lower.includes('instagram.com/')) return !/\/(p|reel|stories|tv)\//.test(lower);
  if (/(twitter|x)\.com\//.test(lower)) return !lower.includes('/status/');
  if (lower.includes('tiktok.com/@')) return !lower.includes('/video/');
  if (lower.includes('youtube.com/@')) return !lower.includes('watch?v=');
  return false;
}

function hideResults() {
  ['#preview-panel', '#carousel-panel', '#profile-panel'].forEach((id) => show($(id), false));
}

async function enqueue(payload) {
  const result = await api.post('/api/downloads', payload, { timeout: 60000 });
  return result.download_id;
}

// ---------------------------------------------------------------- busca

async function handleInspect(event) {
  event?.preventDefault();
  const input = $('#url-input');
  const target = input.value.trim();
  if (!target) {
    toast.info('Cole um link ou digite @usuario.');
    input.focus();
    return;
  }
  const detected = detectPlatform(target);
  if (detected) selectPlatform(detected);

  const button = $('#btn-inspect');
  setBusy(button, true, 'Buscando...');
  try {
    if (isProfileTarget(target)) {
      const data = await api.post('/api/profile/scan', { target, platform: state.platform, limit: 24 }, { timeout: 30000 });
      hideResults();
      renderProfile(data);
    } else {
      const data = await api.post('/api/info/inspect', { url: target }, { timeout: 45000 });
      state.media = data;
      hideResults();
      if (data.is_carousel || data.carousel_items?.length) renderCarousel(data);
      else renderPreview(data);
    }
    show($('#download-hint'), false);
  } catch (err) {
    toast.error(err.message);
  } finally {
    setBusy(button, false);
  }
}

// ---------------------------------------------------------------- mídia única

function renderPreview(data) {
  const isImage = data.media_type === 'image';
  $('#preview-thumb').src = safeSrc(data.thumbnail);
  $('#preview-title').textContent = data.title;
  $('#preview-author').textContent = data.author || '';
  $('#preview-platform').textContent = data.platform;
  const duration = $('#preview-duration');
  duration.textContent = data.duration_string || '';
  show(duration, !isImage && Boolean(data.duration));
  show($('#btn-download-cover'), Boolean(data.thumbnail));

  show($('#field-media-type'), !isImage);
  show($('#field-range'), !isImage);
  $('#media-type').value = 'video';
  show($('#field-quality'), !isImage);
  show($('#field-audio-format'), false);
  $('#audio-format').value = state.defaults.default_audio_format;
  $('#btn-start-download').textContent = isImage ? 'Baixar foto' : 'Baixar';

  const quality = $('#quality');
  const options = QUALITY_PRESETS.map(([value, label]) => el('option', { value, text: label }));
  (data.formats || []).filter((f) => f.has_video && f.resolution).forEach((f) => {
    const size = f.filesize_approx ? ` (~${formatBytes(f.filesize_approx)})` : '';
    options.push(el('option', { value: `id:${f.format_id}`, text: `${f.resolution} ${f.ext.toUpperCase()}${size}` }));
  });
  quality.replaceChildren(...options);
  quality.value = state.defaults.default_format || 'best';

  $('#range-enabled').checked = false;
  show($('#range-inputs'), false);
  show($('#inline-progress'), false);
  show($('#preview-panel'), true);
}

async function handleStartDownload(event) {
  event.preventDefault();
  const media = state.media;
  if (!media) return;
  if (media.is_live) {
    toast.warning('Transmissões ao vivo só podem ser baixadas depois que terminarem.');
    return;
  }

  const quality = $('#quality').value;
  const useRange = $('#range-enabled').checked;
  const isImage = media.media_type === 'image';
  const payload = {
    url: media.url,
    media_type: isImage ? 'image' : $('#media-type').value,
    audio_format: $('#audio-format').value,
    quality_preset: quality.startsWith('id:') ? 'best' : quality,
    format_id: quality.startsWith('id:') ? quality.slice(3) : null,
    time_range_start: useRange ? $('#range-start').value.trim() || null : null,
    time_range_end: useRange ? $('#range-end').value.trim() || null : null,
  };

  const button = $('#btn-start-download');
  setBusy(button, true, 'Enviando...');
  try {
    trackInline(await enqueue(payload));
  } catch (err) {
    toast.error(err.message);
  } finally {
    setBusy(button, false);
  }
}

function downloadCover() {
  const media = state.media;
  if (!media?.thumbnail) return;
  const params = new URLSearchParams({ url: media.thumbnail, title: media.title || 'capa' });
  triggerDownload(`/api/info/thumbnail?${params}`, `${safeFilename(media.title, 'capa')} - capa`);
}

// ---------------------------------------------------------------- carrossel

function updateCarouselButton() {
  const button = $('#btn-carousel-selected');
  button.textContent = `Baixar selecionadas (${state.carouselSelected.size})`;
  button.disabled = state.carouselSelected.size === 0;
}

function carouselPayload(data, item) {
  return {
    url: item.url,
    direct_media_url: item.download_url,
    media_type: item.media_type === 'video' ? 'video' : 'image',
    custom_title: `${data.author || 'instagram'}_${data.id}_${item.index}`,
  };
}

async function downloadCarouselItem(data, item, button) {
  setBusy(button, true, 'Enviando...');
  try {
    await enqueue(carouselPayload(data, item));
    button.textContent = 'Na fila';
    button.classList.add('is-done');
  } catch (err) {
    toast.error(err.message);
    setBusy(button, false);
    return;
  }
  delete button.dataset.label;
}

function renderCarousel(data) {
  const items = data.carousel_items || [];
  const photos = items.filter((i) => i.media_type === 'image').length;
  const videos = items.length - photos;
  $('#carousel-platform').textContent = data.platform;
  $('#carousel-author').textContent = data.author ? `@${data.author}` : '';
  $('#carousel-count').textContent = [photos && `${photos} foto(s)`, videos && `${videos} vídeo(s)`].filter(Boolean).join(', ');
  $('#carousel-title').textContent = data.title;
  $('#carousel-description').textContent = data.description || '';
  state.carouselSelected = new Set();
  updateCarouselButton();

  $('#carousel-grid').replaceChildren(...items.map((item) => {
    const isVideo = item.media_type === 'video';
    const media = isVideo
      ? el('video', { controls: true, preload: 'metadata', playsInline: true, poster: safeSrc(item.thumbnail), src: safeSrc(item.download_url) })
      : el('img', { src: safeSrc(item.thumbnail), alt: `Mídia ${item.index}`, loading: 'lazy' });
    const card = el('div', { class: 'media-card' });
    const checkbox = el('input', {
      type: 'checkbox',
      onchange: (e) => {
        if (e.target.checked) state.carouselSelected.add(item); else state.carouselSelected.delete(item);
        card.classList.toggle('selected', e.target.checked);
        updateCarouselButton();
      },
    });
    const button = el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: isVideo ? 'Baixar vídeo' : 'Baixar foto' });
    button.addEventListener('click', () => downloadCarouselItem(data, item, button));
    card.append(
      el('div', { class: 'media-thumb' }, [
        media,
        el('label', { class: 'check' }, [checkbox, `${item.index}`]),
        el('span', { class: 'tag', text: isVideo ? 'Vídeo' : 'Foto' }),
      ]),
      el('div', { class: 'media-body' }, [el('div', { class: 'media-foot' }, [el('span', { class: 'muted small', text: `Mídia ${item.index}` }), button])]),
    );
    return card;
  }));

  $('#btn-carousel-all').onclick = async (e) => {
    const button = e.currentTarget;
    setBusy(button, true, 'Enviando...');
    try {
      trackInline(await enqueue({ url: data.url, format_id: 'carousel_all', media_type: 'image' }));
      toast.info('Carrossel na fila. O .zip será entregue ao navegador quando terminar.');
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(button, false);
    }
  };
  $('#btn-carousel-selected').onclick = async (e) => {
    const button = e.currentTarget;
    const selected = Array.from(state.carouselSelected);
    setBusy(button, true, 'Enviando...');
    let queued = 0;
    for (const item of selected) {
      try {
        await enqueue(carouselPayload(data, item));
        queued++;
      } catch (err) {
        toast.error(`Mídia ${item.index}: ${err.message}`);
      }
    }
    setBusy(button, false);
    updateCarouselButton();
    if (queued) toast.success(`${queued} mídia(s) na fila.`);
  };
  show($('#carousel-panel'), true);
}

// ---------------------------------------------------------------- perfil

function updateProfileButton() {
  const button = $('#btn-profile-selected');
  button.textContent = `Baixar selecionadas (${state.profileSelected.size})`;
  button.disabled = state.profileSelected.size === 0;
}

function renderProfile(data) {
  $('#profile-avatar').src = safeSrc(data.profile_pic_url);
  $('#profile-name').textContent = data.full_name || data.username;
  $('#profile-username').textContent = `@${data.username}`;
  $('#profile-platform').textContent = data.platform;
  $('#profile-bio').textContent = data.bio || '';
  const followers = (data.followers_count || 0).toLocaleString('pt-BR');
  $('#profile-stats').textContent = `${data.items.length} publicações listadas · ${followers} seguidores`;
  $('#profile-select-all').checked = false;
  state.profileSelected = new Set();
  updateProfileButton();

  const grid = $('#profile-grid');
  if (!data.items.length) {
    grid.replaceChildren(el('p', { class: 'empty', text: 'Nenhuma publicação pública encontrada neste perfil.' }));
  } else {
    grid.replaceChildren(...data.items.map((item) => {
      const card = el('div', { class: 'media-card', dataset: { url: item.url } });
      const checkbox = el('input', {
        type: 'checkbox', class: 'profile-check',
        onchange: (e) => {
          if (e.target.checked) state.profileSelected.add(item.url); else state.profileSelected.delete(item.url);
          card.classList.toggle('selected', e.target.checked);
          updateProfileButton();
        },
      });
      const button = el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Baixar' });
      button.addEventListener('click', async () => {
        setBusy(button, true, 'Enviando...');
        try {
          await enqueue({ url: item.url, media_type: 'video', quality_preset: state.defaults.default_format || 'best' });
          button.textContent = 'Na fila';
          button.classList.add('is-done');
          delete button.dataset.label;
        } catch (err) {
          toast.error(err.message);
          setBusy(button, false);
        }
      });
      card.append(
        el('div', { class: 'media-thumb' }, [
          el('img', { src: safeSrc(item.thumbnail), alt: '', loading: 'lazy' }),
          el('label', { class: 'check' }, [checkbox]),
          el('span', { class: 'tag', text: TYPE_LABELS[item.media_type] || 'Mídia' }),
        ]),
        el('div', { class: 'media-body' }, [
          el('p', { class: 'clamp-2', text: item.caption || 'Sem legenda' }),
          el('div', { class: 'media-foot' }, [el('span', { class: 'muted small', text: item.date || '' }), button]),
        ]),
      );
      return card;
    }));
  }
  show($('#profile-panel'), true);
}

async function downloadSelectedProfile(e) {
  const button = e.currentTarget;
  const urls = Array.from(state.profileSelected);
  setBusy(button, true, `Enviando ${urls.length}...`);
  let queued = 0;
  for (const url of urls) {
    try {
      await enqueue({ url, media_type: 'video', quality_preset: state.defaults.default_format || 'best' });
      queued++;
    } catch (err) {
      toast.error(err.message);
    }
  }
  setBusy(button, false);
  updateProfileButton();
  if (queued) toast.success(`${queued} publicação(ões) na fila.`);
}

// ---------------------------------------------------------------- inicialização

export function initDownloads() {
  $('#inspect-form').addEventListener('submit', handleInspect);
  $('#download-form').addEventListener('submit', handleStartDownload);
  $('#btn-download-cover').addEventListener('click', downloadCover);
  $('#btn-profile-selected').addEventListener('click', downloadSelectedProfile);

  $$('#platform-select .seg').forEach((button) => {
    button.addEventListener('click', () => {
      selectPlatform(button.dataset.platform);
      $('#url-input').focus();
    });
  });

  const input = $('#url-input');
  input.addEventListener('input', () => {
    const detected = detectPlatform(input.value);
    if (detected) selectPlatform(detected);
    else if (!input.value.trim()) selectPlatform('auto');
  });

  $('#btn-paste').addEventListener('click', async () => {
    try {
      const text = (await navigator.clipboard.readText()).trim();
      if (!text) {
        toast.info('A área de transferência está vazia.');
        return;
      }
      input.value = text;
      input.dispatchEvent(new Event('input'));
      handleInspect();
    } catch (_) {
      toast.warning('O navegador não liberou a leitura da área de transferência. Use Ctrl+V no campo.');
    }
  });

  $('#media-type').addEventListener('change', (e) => {
    const isAudio = e.target.value === 'audio';
    show($('#field-quality'), !isAudio);
    show($('#field-audio-format'), isAudio);
  });
  $('#range-enabled').addEventListener('change', (e) => show($('#range-inputs'), e.target.checked));

  $('#profile-select-all').addEventListener('change', (e) => {
    $$('.profile-check').forEach((checkbox) => {
      if (checkbox.checked !== e.target.checked) {
        checkbox.checked = e.target.checked;
        checkbox.dispatchEvent(new Event('change'));
      }
    });
  });
}
