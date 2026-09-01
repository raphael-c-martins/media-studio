// MediaDownloader Pro - Frontend SPA Logic

const API_BASE = ''; // Usa proxy relativo do Vite ou rota raiz

// Estado da Aplicação
const state = {
  currentInspect: null,
  activeQueue: [],
  sseConnected: false,
  settings: {},
  selectedPlatform: 'auto',
  profileData: null,
  selectedProfileItems: new Set()
};

// ==========================================
// SELETOR DE PLATAFORMAS
// ==========================================
function initPlatformPills() {
  const pills = document.querySelectorAll('.pill-btn');
  const input = document.getElementById('url-input');

  const placeholders = {
    auto: 'Cole a URL do vídeo/post ou digite @usuario para varrer perfil...',
    youtube: 'Cole a URL do vídeo, Shorts, Playlist ou canal (@canal)...',
    instagram: 'Cole a URL do Post/Reels ou digite @usuario para varrer perfil...',
    twitter: 'Cole a URL do Tweet ou digite @usuario para varrer posts...',
    tiktok: 'Cole a URL do vídeo ou digite @usuario do TikTok...'
  };

  pills.forEach(pill => {
    pill.addEventListener('click', () => {
      pills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      const plat = pill.getAttribute('data-platform');
      state.selectedPlatform = plat;
      input.placeholder = placeholders[plat] || placeholders.auto;
      input.focus();
    });
  });
}

// ==========================================
// UTILITÁRIOS E TOASTS
// ==========================================
function showToast(message, type = 'info', duration = 4000, actions = []) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  
  const span = document.createElement('span');
  span.innerText = message;
  toast.appendChild(span);

  if (actions && actions.length > 0) {
    const actionsWrapper = document.createElement('div');
    actionsWrapper.className = 'toast-actions';
    actions.forEach(act => {
      const btn = document.createElement('button');
      btn.className = 'toast-btn';
      btn.innerText = act.label;
      btn.onclick = (e) => {
        e.stopPropagation();
        act.onClick();
      };
      actionsWrapper.appendChild(btn);
    });
    toast.appendChild(actionsWrapper);
  }

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

function formatBytes(bytes, decimals = 2) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const dm = decimals < 0 ? 0 : decimals;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function formatDate(isoStr) {
  if (!isoStr) return '-';
  const d = new Date(isoStr);
  return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

// ==========================================
// NAVEGAÇÃO POR ABAS & BRAND HOME
// ==========================================
function navigateToTab(tabId) {
  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabContents = document.querySelectorAll('.tab-content');

  tabBtns.forEach(b => {
    b.classList.toggle('active', b.getAttribute('data-tab') === tabId);
  });
  tabContents.forEach(c => {
    c.classList.toggle('active', c.id === tabId);
  });

  if (tabId === 'history-tab') loadHistory();
  if (tabId === 'settings-tab') loadSettings();
}

function initTabs() {
  const tabBtns = document.querySelectorAll('.tab-btn');
  tabBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const targetTab = btn.getAttribute('data-tab');
      if (targetTab) navigateToTab(targetTab);
    });
  });

  // Botão/Logo da Marca para ir para a Home (Baixar)
  const brandLogoBtn = document.getElementById('brand-logo-btn');
  if (brandLogoBtn) {
    brandLogoBtn.addEventListener('click', () => {
      navigateToTab('download-tab');
    });
  }

  // Minimizar / Expandir Widget Flutuante de Downloads
  const headerBtn = document.getElementById('floating-queue-header-btn');
  const widget = document.getElementById('floating-queue-widget');
  if (headerBtn && widget) {
    headerBtn.addEventListener('click', () => {
      widget.classList.toggle('minimized');
    });
  }
}

// ==========================================
// INSPEÇÃO DE URL / VARREDURA DE PERFIL
// ==========================================
// Helper seguro para tratamento de mensagens de erro HTTP
async function parseResponseError(res, fallback = 'Erro ao processar requisição.') {
  try {
    const data = await res.json();
    return data.detail || data.message || data.error || fallback;
  } catch (e) {
    try {
      const text = await res.text();
      return text && text.length < 200 ? text : fallback;
    } catch (_) {
      return fallback;
    }
  }
}

// ==========================================
// INSPEÇÃO DE URL / VARREDURA DE PERFIL
// ==========================================
async function handleInspect(e) {
  if (e) e.preventDefault();
  const urlInput = document.getElementById('url-input');
  const target = urlInput.value.trim();
  if (!target) return;

  const btnInspect = document.getElementById('btn-inspect');
  const btnText = btnInspect.querySelector('.btn-text');
  const spinner = btnInspect.querySelector('.btn-spinner');

  btnInspect.disabled = true;
  btnText.innerText = 'Processando...';
  spinner.classList.remove('hidden');

  const targetLower = target.toLowerCase();
  
  // Detecção inteligente e universal de modo perfil
  const isProfileMode = target.startsWith('@') ||
    (targetLower.includes('instagram.com/') && !targetLower.includes('/p/') && !targetLower.includes('/reel/') && !targetLower.includes('/stories/') && !targetLower.includes('/tv/')) ||
    (targetLower.includes('twitter.com/') && !targetLower.includes('/status/')) ||
    (targetLower.includes('x.com/') && !targetLower.includes('/status/')) ||
    (targetLower.includes('tiktok.com/@') && !targetLower.includes('/video/')) ||
    (targetLower.includes('youtube.com/@') && !targetLower.includes('watch?v='));

  if (isProfileMode) {
    await handleProfileScan(target, state.selectedPlatform, btnInspect, btnText, spinner);
  } else {
    await handleSingleMediaInspect(target, btnInspect, btnText, spinner);
  }
}

async function handleSingleMediaInspect(url, btnInspect, btnText, spinner) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 15000);

  try {
    const res = await fetch(`${API_BASE}/api/info/inspect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
      signal: controller.signal
    });

    clearTimeout(timeoutId);

    if (!res.ok) {
      const errDetail = await parseResponseError(res, 'Não foi possível analisar a URL informada.');
      throw new Error(errDetail);
    }

    const data = await res.json();
    state.currentInspect = data;
    
    // Ocultar containers anteriores
    document.getElementById('profile-container').classList.add('hidden');
    document.getElementById('preview-container').classList.add('hidden');
    document.getElementById('carousel-container').classList.add('hidden');
    const welcomeSec = document.getElementById('home-welcome-section');
    if (welcomeSec) welcomeSec.classList.add('hidden');

    if (data.is_carousel || (data.carousel_items && data.carousel_items.length > 0)) {
      renderCarousel(data);
      showToast(`Carrossel de ${data.carousel_items.length} mídias identificado!`, 'success');
    } else {
      renderPreview(data);
      showToast('Mídia identificada com sucesso!', 'success');
    }
  } catch (err) {
    const msg = err.name === 'AbortError' ? 'Tempo limite excedido ao inspecionar a mídia.' : err.message;
    showToast(msg, 'error', 5000);
  } finally {
    clearTimeout(timeoutId);
    btnInspect.disabled = false;
    btnText.innerText = 'Buscar';
    spinner.classList.add('hidden');
  }
}

async function handleProfileScan(target, platform, btnInspect, btnText, spinner) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 18000);

  try {
    const res = await fetch(`${API_BASE}/api/profile/scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target, platform, limit: 24 }),
      signal: controller.signal
    });

    clearTimeout(timeoutId);

    if (!res.ok) {
      const errDetail = await parseResponseError(res, 'Erro ao varrer o perfil informado.');
      throw new Error(errDetail);
    }

    const data = await res.json();
    state.profileData = data;
    state.selectedProfileItems.clear();

    // Ocultar preview unitário, carrossel e destaques
    document.getElementById('preview-container').classList.add('hidden');
    document.getElementById('carousel-container').classList.add('hidden');
    const welcomeSec = document.getElementById('home-welcome-section');
    if (welcomeSec) welcomeSec.classList.add('hidden');

    renderProfileGallery(data);
    showToast(`Perfil @${data.username} carregado com sucesso!`, 'success');
  } catch (err) {
    const msg = err.name === 'AbortError' ? 'Tempo limite excedido ao varrer o perfil.' : err.message;
    showToast(msg, 'error', 6000);
  } finally {
    clearTimeout(timeoutId);
    btnInspect.disabled = false;
    btnText.innerText = 'Buscar';
    spinner.classList.add('hidden');
  }
}

// ==========================================
// RENDERIZAÇÃO DE CARROSSEL DE MÍDIAS (INSTAGRAM)
// ==========================================
function renderCarousel(data) {
  const container = document.getElementById('carousel-container');
  document.getElementById('carousel-platform-badge').innerText = data.platform;
  document.getElementById('carousel-author').innerText = `@${data.author || 'Instagram'}`;
  
  const total = data.carousel_items.length;
  const numPhotos = data.carousel_items.filter(i => i.media_type === 'image').length;
  const numVideos = data.carousel_items.filter(i => i.media_type === 'video').length;
  
  let countStr = `${total} itens`;
  if (numPhotos > 0 && numVideos > 0) {
    countStr = `${total} itens (${numPhotos} fotos, ${numVideos} vídeos)`;
  } else if (numPhotos > 0) {
    countStr = `${numPhotos} fotos`;
  } else if (numVideos > 0) {
    countStr = `${numVideos} vídeos`;
  }
  document.getElementById('carousel-total-count').innerText = countStr;
  document.getElementById('carousel-title').innerText = data.title;
  document.getElementById('carousel-description').innerText = data.description || '';

  const grid = document.getElementById('carousel-media-grid');
  grid.innerHTML = '';

  state.selectedCarouselItems = new Set();
  const btnSelected = document.getElementById('btn-download-selected-carousel');
  btnSelected.disabled = true;
  document.getElementById('carousel-selected-count').innerText = '0';

  // Configurar botão de baixar todas
  const btnAll = document.getElementById('btn-download-all-carousel');
  btnAll.onclick = () => downloadCarouselAll(data, btnAll);

  // Configurar botão de baixar selecionadas
  btnSelected.onclick = () => downloadCarouselSelected(data, btnSelected);

  data.carousel_items.forEach((item) => {
    const isVid = item.media_type === 'video';
    const card = document.createElement('div');
    card.className = 'carousel-item-card';

    const mediaElement = isVid
      ? `<video class="carousel-media-video" controls preload="metadata" poster="${item.thumbnail}" playsinline>
           <source src="${item.download_url}" type="video/mp4">
         </video>`
      : `<img src="${item.thumbnail}" alt="Mídia ${item.index}" loading="lazy" />`;

    card.innerHTML = `
      <div class="carousel-thumb-box ${isVid ? 'video-box' : 'photo-box'}">
        <span class="carousel-item-index">#${item.index}</span>
        <span class="carousel-item-badge ${isVid ? 'badge-video' : 'badge-image'}">
          ${isVid ? 'Vídeo' : 'Foto'}
        </span>
        <label class="carousel-item-select">
          <input type="checkbox" class="carousel-select-cb" data-index="${item.index}" data-url="${item.url}" />
        </label>
        ${mediaElement}
      </div>
      <div class="carousel-item-body">
        <div class="carousel-item-actions">
          <button type="button" class="carousel-btn-download" data-index="${item.index}">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
            <span>Baixar ${isVid ? 'Vídeo' : 'Foto'}</span>
          </button>
        </div>
      </div>
    `;

    // Checkbox de seleção
    const cb = card.querySelector('.carousel-select-cb');
    cb.addEventListener('change', () => {
      if (cb.checked) {
        state.selectedCarouselItems.add(item);
      } else {
        state.selectedCarouselItems.delete(item);
      }
      const selCount = state.selectedCarouselItems.size;
      document.getElementById('carousel-selected-count').innerText = selCount;
      btnSelected.disabled = selCount === 0;
    });

    // Botão de download individual
    const btnDown = card.querySelector('.carousel-btn-download');
    btnDown.addEventListener('click', () => {
      downloadCarouselSingleItem(data, item, btnDown);
    });

    grid.appendChild(card);
  });

  container.classList.remove('hidden');
  container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function downloadCarouselAll(data, btnElement) {
  if (!data || !data.url) return;
  if (btnElement) {
    btnElement.disabled = true;
    btnElement.innerHTML = '<span class="btn-spinner"></span> <span>Baixando e compactando em .zip...</span>';
  }

  try {
    const res = await fetch(`${API_BASE}/api/downloads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: data.url,
        format_id: 'carousel_all',
        media_type: 'image'
      })
    });

    if (!res.ok) {
      const errDetail = await parseResponseError(res, 'Erro ao iniciar download do carrossel.');
      throw new Error(errDetail);
    }

    if (btnElement) {
      setTimeout(() => {
        btnElement.disabled = false;
        btnElement.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg><span>Baixar Todas as Mídias</span>';
      }, 6000);
    }
  } catch (err) {
    showToast(err.message, 'error');
    if (btnElement) {
      btnElement.disabled = false;
      btnElement.innerHTML = '<span>Baixar Todas as Mídias</span>';
    }
  }
}

async function downloadCarouselSingleItem(data, item, btnElement) {
  if (btnElement) {
    btnElement.disabled = true;
    btnElement.innerHTML = '<span class="btn-spinner"></span> <span>Baixando...</span>';
  }

  try {
    const res = await fetch(`${API_BASE}/api/downloads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: item.url,
        direct_media_url: item.download_url,
        format_id: 'best',
        media_type: item.media_type,
        custom_title: `${data.author || 'Instagram'}_${data.id}_${item.index}`
      })
    });

    if (!res.ok) {
      const errDetail = await parseResponseError(res, 'Erro ao iniciar download do item.');
      throw new Error(errDetail);
    }
  } catch (err) {
    showToast(err.message, 'error');
    if (btnElement) {
      btnElement.disabled = false;
      btnElement.innerHTML = `<span>Baixar ${item.media_type === 'video' ? 'Vídeo' : 'Foto'}</span>`;
    }
  }
}

async function downloadCarouselSelected(data, btnElement) {
  if (!state.selectedCarouselItems || state.selectedCarouselItems.size === 0) return;
  const items = Array.from(state.selectedCarouselItems);

  if (items.length === 1) {
    const item = items[0];
    const btn = document.querySelector(`.carousel-btn-download[data-index="${item.index}"]`);
    await downloadCarouselSingleItem(data, item, btn || btnElement);
    return;
  }

  if (btnElement) {
    btnElement.disabled = true;
    btnElement.innerHTML = `<span class="btn-spinner"></span> <span>Baixando (${items.length})...</span>`;
  }

  try {
    for (const item of items) {
      await fetch(`${API_BASE}/api/downloads`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: item.url,
          direct_media_url: item.download_url,
          format_id: 'best',
          media_type: item.media_type,
          custom_title: `${data.author || 'Instagram'}_${data.id}_${item.index}`
        })
      });
    }

    showToast(`Baixando ${items.length} mídias selecionadas. Os arquivos serão salvos diretamente no seu navegador...`, 'info', 4000);
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    if (btnElement) {
      setTimeout(() => {
        btnElement.disabled = false;
        btnElement.innerText = `Baixar Selecionadas (${items.length})`;
      }, 4000);
    }
  }
}

function renderPreview(data) {
  const container = document.getElementById('preview-container');
  document.getElementById('preview-title').innerText = data.title;
  document.getElementById('preview-author').innerText = data.author || data.platform;
  document.getElementById('preview-thumbnail').src = data.thumbnail || '';
  
  const isImage = data.media_type === 'image';
  const durationBadge = document.getElementById('preview-duration');
  if (isImage || !data.duration) {
    durationBadge.classList.add('hidden');
  } else {
    durationBadge.classList.remove('hidden');
    durationBadge.innerText = data.duration_string || `${data.duration}s`;
  }
  
  document.getElementById('preview-platform').innerText = data.platform;

  // Adaptar controles para imagem vs vídeo
  const groupQuality = document.getElementById('group-video-quality');
  const groupAudio = document.getElementById('group-audio-format');
  const timeRangeBox = document.querySelector('.time-range-box');
  const btnAI = document.getElementById('btn-quick-ai');
  const btnDownload = document.getElementById('btn-start-download');
  const mediaTypeSelect = document.getElementById('media-type-select');

  if (isImage) {
    if (groupQuality) groupQuality.classList.add('hidden');
    if (groupAudio) groupAudio.classList.add('hidden');
    if (timeRangeBox) timeRangeBox.classList.add('hidden');
    if (btnAI) btnAI.classList.add('hidden');
    if (mediaTypeSelect) mediaTypeSelect.parentElement.classList.add('hidden');
    btnDownload.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
      Baixar Imagem Original (JPG)
    `;
  } else {
    if (groupQuality) groupQuality.classList.remove('hidden');
    if (timeRangeBox) timeRangeBox.classList.remove('hidden');
    if (btnAI) btnAI.classList.remove('hidden');
    if (mediaTypeSelect) mediaTypeSelect.parentElement.classList.remove('hidden');
    btnDownload.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
      Baixar Vídeo Agora
    `;

    // Atualizar seleções de qualidade baseadas nos formatos detectados
    const qualitySelect = document.getElementById('quality-select');
    qualitySelect.innerHTML = '<option value="best">Melhor Disponível (Automático)</option>';
    
    if (data.formats && data.formats.length > 0) {
      data.formats.forEach(f => {
        if (f.resolution && f.has_video) {
          const opt = document.createElement('option');
          opt.value = f.format_id;
          const sizeStr = f.filesize_approx ? ` (~${formatBytes(f.filesize_approx)})` : '';
          opt.innerText = `${f.resolution} - ${f.ext.toUpperCase()}${sizeStr}`;
          qualitySelect.appendChild(opt);
        }
      });
    } else {
      qualitySelect.innerHTML += `
        <option value="1080p">1080p (Full HD)</option>
        <option value="720p">720p (HD)</option>
        <option value="480p">480p (SD)</option>
      `;
    }
  }

  container.classList.remove('hidden');
  container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderProfileGallery(data) {
  const container = document.getElementById('profile-container');
  
  // Detalhes do Perfil
  document.getElementById('profile-avatar').src = data.profile_pic_url || 'https://via.placeholder.com/80';
  document.getElementById('profile-fullname').innerText = data.full_name || data.username;
  document.getElementById('profile-username').innerText = `@${data.username}`;
  document.getElementById('profile-platform-badge').innerText = data.platform;
  document.getElementById('profile-bio').innerText = data.bio || 'Sem biografia informada.';
  document.getElementById('profile-stat-posts').innerText = data.items.length || data.posts_count || 0;
  document.getElementById('profile-stat-followers').innerText = (data.followers_count || 0).toLocaleString('pt-BR');

  // Checkbox de seleção total
  const selectAllCb = document.getElementById('profile-select-all');
  selectAllCb.checked = false;
  document.getElementById('profile-selected-count').innerText = '0';
  document.getElementById('btn-download-selected').disabled = true;

  // Grade de Mídias
  const grid = document.getElementById('profile-media-grid');
  grid.innerHTML = '';

  if (!data.items || data.items.length === 0) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path></svg>
        <p>Nenhuma mídia pública encontrada neste perfil.</p>
      </div>
    `;
  } else {
    data.items.forEach(item => {
      const card = document.createElement('div');
      card.className = 'profile-media-card';
      card.id = `media-card-${item.id}`;

      const typeLabels = {
        video: 'Vídeo',
        reel: 'Reel',
        carousel: 'Carrossel',
        image: 'Foto'
      };

      card.innerHTML = `
        <div class="media-card-thumb-wrapper">
          <input type="checkbox" class="media-card-select-checkbox" data-id="${item.id}" data-url="${item.url}" />
          <img src="${item.thumbnail || 'https://via.placeholder.com/220'}" alt="Mídia do Post" loading="lazy" />
          <span class="media-card-badge">${typeLabels[item.media_type] || 'Mídia'}</span>
        </div>
        <div class="media-card-body">
          <p class="media-card-caption">${item.caption || 'Sem legenda'}</p>
          <div class="media-card-footer">
            <span class="media-card-meta">${item.date || ''}</span>
            <button type="button" class="btn btn-primary btn-sm btn-sm-download" data-url="${item.url}">
              Baixar
            </button>
          </div>
        </div>
      `;

      // Event listener para checkbox
      const cb = card.querySelector('.media-card-select-checkbox');
      cb.addEventListener('change', (e) => {
        if (e.target.checked) {
          state.selectedProfileItems.add(item.url);
        } else {
          state.selectedProfileItems.delete(item.url);
        }
        updateProfileSelectionUI();
      });

      // Event listener para botão Baixar Individual
      const btnDl = card.querySelector('.btn-sm-download');
      btnDl.addEventListener('click', () => {
        downloadSingleItemFromGallery(item.url, btnDl);
      });

      grid.appendChild(card);
    });
  }

  container.classList.remove('hidden');
  container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function updateProfileSelectionUI() {
  const count = state.selectedProfileItems.size;
  document.getElementById('profile-selected-count').innerText = count.toString();
  document.getElementById('btn-download-selected').disabled = count === 0;
}

async function downloadSingleItemFromGallery(url, btnElement) {
  if (btnElement) {
    btnElement.disabled = true;
    btnElement.innerText = 'Enfileirando...';
  }

  try {
    const res = await fetch(`${API_BASE}/api/downloads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: url,
        media_type: 'video',
        quality_preset: 'best'
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Erro ao iniciar download da mídia.');
    }

    showToast('Download adicionado à fila com sucesso!', 'success');
    if (btnElement) {
      btnElement.innerText = 'Baixando';
      btnElement.classList.replace('btn-primary', 'btn-success');
    }
  } catch (err) {
    showToast(err.message, 'error');
    if (btnElement) {
      btnElement.disabled = false;
      btnElement.innerText = 'Baixar';
    }
  }
}

async function handleDownloadSelectedProfile() {
  if (state.selectedProfileItems.size === 0) return;

  const urls = Array.from(state.selectedProfileItems);
  const btn = document.getElementById('btn-download-selected');
  btn.disabled = true;
  btn.innerText = `Enfileirando (${urls.length})...`;

  let successCount = 0;
  for (const url of urls) {
    try {
      await fetch(`${API_BASE}/api/downloads`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url,
          media_type: 'video',
          quality_preset: 'best'
        })
      });
      successCount++;
    } catch (e) {}
  }

  showToast(`${successCount} mídias adicionadas à fila de processamento!`, 'success');
  btn.disabled = false;
  btn.innerText = 'Baixar Selecionados';
}

// ==========================================
// DISPARO DE DOWNLOAD
// ==========================================
async function handleStartDownload(e) {
  e.preventDefault();
  if (!state.currentInspect) {
    showToast('Inspecione uma URL antes de iniciar o download.', 'error');
    return;
  }

  const mediaType = document.getElementById('media-type-select').value;
  const qualitySelect = document.getElementById('quality-select').value;
  const audioFormat = document.getElementById('audio-format-select').value;
  const enableTimeRange = document.getElementById('enable-time-range').checked;
  const timeStart = document.getElementById('time-start').value.trim();
  const timeEnd = document.getElementById('time-end').value.trim();

  const payload = {
    url: state.currentInspect.url,
    media_type: mediaType,
    quality_preset: qualitySelect.startsWith('best') || ['4k', '1080p', '720p', '480p'].includes(qualitySelect) ? qualitySelect : 'best',
    format_id: !['best', '4k', '1080p', '720p', '480p'].includes(qualitySelect) ? qualitySelect : null,
    audio_format: audioFormat,
    time_range_start: enableTimeRange && timeStart ? timeStart : null,
    time_range_end: enableTimeRange && timeEnd ? timeEnd : null,
    download_subtitles: true,
    download_thumbnail: true
  };

  try {
    const res = await fetch(`${API_BASE}/api/downloads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Erro ao enfileirar download.');
    }

    const data = await res.json();
    state.currentDownloadId = data.download_id;

    // Exibir barra de progresso inline na própria aba de download
    const inlineBox = document.getElementById('inline-progress-box');
    if (inlineBox) {
      inlineBox.classList.remove('hidden');
      document.getElementById('inline-status-text').innerText = 'Iniciando download...';
      document.getElementById('inline-status-text').style.color = 'var(--text-primary)';
      document.getElementById('inline-percent-text').innerText = '0%';
      document.getElementById('inline-progress-bar').style.width = '0%';
      document.getElementById('inline-progress-bar').className = 'progress-bar';
      document.getElementById('inline-speed-text').innerText = 'Conectando ao servidor...';
      document.getElementById('inline-eta-text').innerText = '';
    }

    showToast('Download iniciado!', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// ==========================================
// SERVER-SENT EVENTS (SSE) & FILA ATIVA
// ==========================================
function initSSE() {
  const evtSource = new EventSource(`${API_BASE}/api/downloads/stream`);

  evtSource.onopen = () => {
    state.sseConnected = true;
  };

  evtSource.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data);
      handleServerEvent(parsed);
    } catch (e) {
      // Mensagem keepalive
    }
  };

  evtSource.onerror = () => {
    state.sseConnected = false;
  };
}

function triggerBrowserDownload(url) {
  try {
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.setAttribute('download', '');
    document.body.appendChild(a);
    a.click();
    setTimeout(() => a.remove(), 1000);
  } catch (err) {
    console.error('Falha ao disparar download no navegador:', err);
  }
}

function handleServerEvent(payload) {
  const { event, data } = payload;
  if (!event) return;

  if (event === 'download_queued' || event === 'download_started') {
    loadQueue();
  } else if (event === 'download_progress') {
    updateProgressUI(data);
    updateInlineProgress(data);
  } else if (event === 'download_completed') {
    // 1. DISPARAR DOWNLOAD AUTOMÁTICO PARA A CAIXA DE DOWNLOADS DO NAVEGADOR
    if (data.id) {
      triggerBrowserDownload(`${API_BASE}/api/history/${data.id}/file`);
    }

    showToast(`Arquivo salvo no seu computador: ${data.title || 'Mídia'}`, 'success', 6000, [
      {
        label: '📂 Abrir Pasta',
        onClick: () => fetch(`${API_BASE}/api/history/${data.id}/open-folder`, { method: 'POST' })
      }
    ]);

    // 2. Atualizar estado visual no card do carrossel (se houver correspondência de índice)
    const carouselBtns = document.querySelectorAll('.carousel-btn-download');
    carouselBtns.forEach(btn => {
      const idx = btn.getAttribute('data-index');
      if (data.title && (data.title.includes(`_${idx}`) || data.title.endsWith(`_${idx}`))) {
        btn.innerHTML = '<span>✅ Baixado</span>';
        btn.style.backgroundColor = '#059669';
        btn.disabled = false;
      }
    });

    loadQueue();
    loadHistory();
    
    // Atualizar barra inline se for o download atual
    const inlineBox = document.getElementById('inline-progress-box');
    if (inlineBox && (!state.currentDownloadId || state.currentDownloadId === data.id)) {
      document.getElementById('inline-status-text').innerText = 'Concluído e Baixado no PC!';
      document.getElementById('inline-status-text').style.color = 'var(--color-success)';
      document.getElementById('inline-percent-text').innerText = '100%';
      const bar = document.getElementById('inline-progress-bar');
      bar.style.width = '100%';
      bar.classList.add('completed');
      document.getElementById('inline-speed-text').innerText = 'Salvo no navegador e no disco';
      document.getElementById('inline-eta-text').innerText = '';
    }
  } else if (event === 'download_error') {
    showToast(`Erro no download: ${data.error_message}`, 'error', 6000);
    loadQueue();
    loadHistory();

    // Atualizar barra inline em caso de erro
    const inlineBox = document.getElementById('inline-progress-box');
    if (inlineBox && (!state.currentDownloadId || state.currentDownloadId === data.id)) {
      document.getElementById('inline-status-text').innerText = 'Falha no download';
      document.getElementById('inline-status-text').style.color = 'var(--color-danger)';
      const bar = document.getElementById('inline-progress-bar');
      bar.classList.add('error');
      document.getElementById('inline-speed-text').innerText = (data.error_message || '').slice(0, 45) + '...';
    }
  }
}

function updateInlineProgress(data) {
  const inlineBox = document.getElementById('inline-progress-box');
  if (!inlineBox || inlineBox.classList.contains('hidden')) return;

  if (!state.currentDownloadId || state.currentDownloadId === data.id) {
    document.getElementById('inline-status-text').innerText = 'Baixando vídeo...';
    document.getElementById('inline-percent-text').innerText = `${data.progress}%`;
    const bar = document.getElementById('inline-progress-bar');
    bar.style.width = `${data.progress}%`;
    if (data.speed) document.getElementById('inline-speed-text').innerText = `Velocidade: ${data.speed}`;
    if (data.eta) document.getElementById('inline-eta-text').innerText = `Restante: ${data.eta}`;
  }
}

function updateProgressUI(data) {
  const itemEl = document.getElementById(`floating-item-${data.id}`);
  if (!itemEl) return;

  const bar = itemEl.querySelector('.progress-bar');
  const percentText = itemEl.querySelector('.floating-item-percent');
  const speedText = itemEl.querySelector('.floating-item-speed');

  if (bar) bar.style.width = `${data.progress}%`;
  if (percentText) percentText.innerText = `${data.progress}%`;
  if (speedText && data.speed) speedText.innerText = `${data.speed} ${data.eta ? '• ' + data.eta : ''}`;
}

async function loadQueue() {
  try {
    const res = await fetch(`${API_BASE}/api/downloads/queue`);
    if (!res.ok) return;
    const items = await res.json();
    state.activeQueue = items;

    renderFloatingQueue(items);
  } catch (err) {
    console.error('Erro ao carregar fila de downloads:', err);
  }
}

function renderFloatingQueue(items) {
  const widget = document.getElementById('floating-queue-widget');
  const countBadge = document.getElementById('floating-queue-count');
  const listEl = document.getElementById('floating-queue-list');
  if (!widget || !listEl) return;

  if (!items || items.length === 0) {
    widget.classList.add('hidden');
    listEl.innerHTML = '';
    return;
  }

  widget.classList.remove('hidden');
  if (countBadge) countBadge.innerText = items.length;

  listEl.innerHTML = '';
  items.forEach(item => {
    const itemEl = document.createElement('div');
    itemEl.className = 'floating-queue-item';
    itemEl.id = `floating-item-${item.id}`;

    const title = item.title || item.url;
    const prog = item.progress || 0;
    const speed = item.speed || 'Conectando...';
    const eta = item.eta ? `• ${item.eta}` : '';

    itemEl.innerHTML = `
      <div class="floating-item-title" title="${title}">${title}</div>
      <div class="progress-container" style="height: 5px; margin-bottom: 0.35rem;">
        <div class="progress-bar" style="width: ${prog}%;"></div>
      </div>
      <div class="floating-item-progress-row">
        <span class="floating-item-speed">${speed} ${eta}</span>
        <span class="floating-item-percent" style="font-weight: 600; color: #38bdf8;">${prog}%</span>
      </div>
    `;
    listEl.appendChild(itemEl);
  });
}

// ==========================================
// HISTÓRICO DE DOWNLOADS
// ==========================================
async function loadHistory() {
  const search = document.getElementById('history-search').value.trim();
  const platform = document.getElementById('history-filter-platform').value;

  let url = `${API_BASE}/api/history?limit=50`;
  if (search) url += `&search=${encodeURIComponent(search)}`;
  if (platform && platform !== 'all') url += `&platform=${encodeURIComponent(platform)}`;

  try {
    const res = await fetch(url);
    if (!res.ok) return;
    const items = await res.json();

    const tbody = document.getElementById('history-tbody');
    const emptyEl = document.getElementById('history-empty');

    if (items.length === 0) {
      tbody.innerHTML = '';
      emptyEl.classList.remove('hidden');
      return;
    }

    emptyEl.classList.add('hidden');
    tbody.innerHTML = '';

    items.forEach(item => {
      const tr = document.createElement('tr');
      const isOk = item.status === 'completed';
      const statusBadge = isOk 
        ? '<span style="color: var(--color-success); font-weight: 600;">Concluído</span>' 
        : `<span style="color: var(--color-danger); font-weight: 500;">${item.status}</span>`;

      tr.innerHTML = `
        <td>
          <strong>${item.title || 'Sem Título'}</strong>
          <div class="header-hint">${item.author || '-'}</div>
        </td>
        <td>${item.platform || 'Universal'}</td>
        <td>${item.media_type.toUpperCase()} (${item.format_id || 'Padrão'})</td>
        <td>${item.file_size ? formatBytes(item.file_size) : '-'}</td>
        <td>${formatDate(item.created_at)}</td>
        <td>${statusBadge}</td>
        <td class="text-right">
          <div class="table-actions">
            ${isOk ? `<button class="btn btn-sm btn-primary btn-save-browser" data-id="${item.id}" title="Baixar arquivo diretamente para o PC">Salvar no PC</button>` : ''}
            ${isOk ? `<button class="btn btn-sm btn-secondary btn-open-file" data-id="${item.id}" title="Executar no Player do Windows">Reproduzir</button>` : ''}
            ${isOk ? `<button class="btn btn-sm btn-secondary btn-open-folder" data-id="${item.id}" title="Abrir pasta no Windows Explorer">Pasta</button>` : ''}
            <button class="btn btn-sm btn-danger btn-delete-history" data-id="${item.id}" title="Remover do Histórico">Excluir</button>
          </div>
        </td>
      `;
      tbody.appendChild(tr);
    });

    // Ações da tabela
    document.querySelectorAll('.btn-save-browser').forEach(b => {
      b.addEventListener('click', () => {
        const id = b.getAttribute('data-id');
        window.open(`${API_BASE}/api/history/${id}/file`, '_blank');
      });
    });
    document.querySelectorAll('.btn-open-file').forEach(b => {
      b.addEventListener('click', () => fetch(`${API_BASE}/api/history/${b.getAttribute('data-id')}/open-file`, { method: 'POST' }));
    });
    document.querySelectorAll('.btn-open-folder').forEach(b => {
      b.addEventListener('click', () => fetch(`${API_BASE}/api/history/${b.getAttribute('data-id')}/open-folder`, { method: 'POST' }));
    });
    document.querySelectorAll('.btn-delete-history').forEach(b => {
      b.addEventListener('click', async () => {
        const id = b.getAttribute('data-id');
        await fetch(`${API_BASE}/api/history/${id}`, { method: 'DELETE' });
        showToast('Registro removido do histórico.', 'info');
        loadHistory();
      });
    });
  } catch (err) {
    console.error('Erro ao carregar histórico:', err);
  }
}

// ==========================================
// CONFIGURAÇÕES & TEMAS VISUAIS
// ==========================================
function applyTheme(themeName, persist = true) {
  const validThemes = ['default', 'gold', 'monochrome', 'light', 'light-warm'];
  const targetTheme = validThemes.includes(themeName) ? themeName : 'default';

  document.documentElement.setAttribute('data-theme', targetTheme);
  state.currentTheme = targetTheme;

  // Atualizar botões visuais do seletor
  const themeCards = document.querySelectorAll('.theme-card');
  themeCards.forEach(card => {
    card.classList.toggle('active', card.getAttribute('data-theme-val') === targetTheme);
  });

  if (persist) {
    try {
      localStorage.setItem('media_downloader_theme', targetTheme);
      // Salvar silenciosamente no backend também
      fetch(`${API_BASE}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: { theme: targetTheme } })
      }).catch(() => {});
    } catch (_) {}
  }
}

function initThemeSelector() {
  const savedTheme = localStorage.getItem('media_downloader_theme') || 'default';
  applyTheme(savedTheme, false);

  const themeCards = document.querySelectorAll('.theme-card');
  themeCards.forEach(card => {
    card.addEventListener('click', () => {
      const themeVal = card.getAttribute('data-theme-val');
      applyTheme(themeVal, true);
      showToast('Tema visual aplicado!', 'success', 2000);
    });
  });
}

async function loadSettings() {
  try {
    const res = await fetch(`${API_BASE}/api/settings`);
    if (!res.ok) return;
    const settings = await res.json();
    state.settings = settings;

    const folderEl = document.getElementById('setting-download-folder');
    if (folderEl) {
      const fVal = settings.download_folder || '';
      // Se for caminho absoluto que termina com downloads padrão ou relativo, limpa para mostrar placeholder
      if (!fVal || fVal === 'downloads' || fVal.endsWith('\\downloads') || fVal.endsWith('/downloads')) {
        folderEl.value = '';
      } else {
        folderEl.value = fVal;
      }
    }
    if (document.getElementById('setting-default-quality')) {
      document.getElementById('setting-default-quality').value = settings.default_format || 'best';
    }
    if (document.getElementById('setting-default-audio')) {
      document.getElementById('setting-default-audio').value = settings.default_audio_format || 'mp3';
    }
    if (settings.theme) {
      applyTheme(settings.theme, false);
    }
  } catch (err) {
    console.error('Erro ao carregar configurações:', err);
  }
}

async function handleSaveSettings(e) {
  e.preventDefault();
  const folder = document.getElementById('setting-download-folder').value.trim() || 'downloads';
  const quality = document.getElementById('setting-default-quality').value;
  const audio = document.getElementById('setting-default-audio').value;
  const theme = state.currentTheme || 'default';

  const payload = {
    settings: {
      download_folder: folder,
      default_format: quality,
      default_audio_format: audio,
      theme: theme
    }
  };

  try {
    const res = await fetch(`${API_BASE}/api/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error('Falha ao salvar configurações.');
    showToast('Configurações salvas com sucesso!', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function handleBrowseFolder() {
  try {
    const res = await fetch(`${API_BASE}/api/settings/choose-folder`, { method: 'POST' });
    const data = await res.json();
    if (data.success && data.path) {
      document.getElementById('setting-download-folder').value = data.path;
      showToast('Pasta selecionada!', 'success');
    }
  } catch (err) {
    showToast('Não foi possível abrir o seletor de pastas.', 'error');
  }
}

// ==========================================
// INICIALIZAÇÃO GERAL & EVENT LISTENERS
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
  initThemeSelector();
  initTabs();
  initSSE();
  loadQueue();

  // Formulários
  document.getElementById('inspect-form').addEventListener('submit', handleInspect);
  document.getElementById('download-config-form').addEventListener('submit', handleStartDownload);
  const aiForm = document.getElementById('ai-form');
  if (aiForm) aiForm.addEventListener('submit', handleAISummarize);
  document.getElementById('settings-form').addEventListener('submit', handleSaveSettings);

  // Botão Colar Área de Transferência
  document.getElementById('btn-paste-clipboard').addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text && (text.startsWith('http://') || text.startsWith('https://'))) {
        document.getElementById('url-input').value = text;
        handleInspect();
      } else {
        showToast('Nenhuma URL válida encontrada na área de transferência.', 'info');
      }
    } catch (e) {
      showToast('Permissão de leitura da área de transferência negada.', 'info');
    }
  });

  // Botão Abrir Pasta de Downloads no Windows Explorer
  const btnOpenFolder = document.getElementById('btn-open-global-folder');
  if (btnOpenFolder) {
    btnOpenFolder.addEventListener('click', async () => {
      try {
        await fetch(`${API_BASE}/api/history/open-folder-global`, { method: 'POST' });
        showToast('Pasta de downloads aberta no Windows Explorer.', 'success');
      } catch (e) {
        showToast('Erro ao abrir pasta de downloads.', 'error');
      }
    });
  }

  // Alternar Tipo de Mídia (Vídeo / Áudio)
  document.getElementById('media-type-select').addEventListener('change', (e) => {
    const isAudio = e.target.value === 'audio';
    document.getElementById('group-video-quality').classList.toggle('hidden', isAudio);
    document.getElementById('group-audio-format').classList.toggle('hidden', !isAudio);
  });

  // Checkbox de Corte (Time-Range)
  document.getElementById('enable-time-range').addEventListener('change', (e) => {
    document.getElementById('time-range-fields').classList.toggle('hidden', !e.target.checked);
  });

  // Botão Resumo IA Rápido do Card
  document.getElementById('btn-quick-ai').addEventListener('click', () => {
    if (state.currentInspect) {
      document.getElementById('ai-url-input').value = state.currentInspect.url;
      document.getElementById('tab-ai').click();
      document.getElementById('btn-run-ai').click();
    }
  });

  // Atualizar Fila e Histórico
  document.getElementById('btn-refresh-queue').addEventListener('click', loadQueue);
  document.getElementById('btn-refresh-history').addEventListener('click', loadHistory);
  document.getElementById('history-search').addEventListener('input', () => {
    clearTimeout(window._searchTimeout);
    window._searchTimeout = setTimeout(loadHistory, 300);
  });
  document.getElementById('history-filter-platform').addEventListener('change', loadHistory);

  // Seletor de Pasta
  document.getElementById('btn-browse-folder').addEventListener('click', handleBrowseFolder);

  // Inicializar Seletores de Plataforma e Cards Clicáveis
  initPlatformPills();
  initClickableCards();

  // Listeners da Galeria de Perfil
  document.getElementById('profile-select-all').addEventListener('change', (e) => {
    const isChecked = e.target.checked;
    const checkboxes = document.querySelectorAll('.media-card-select-checkbox');
    checkboxes.forEach(cb => {
      cb.checked = isChecked;
      const url = cb.getAttribute('data-url');
      if (isChecked) {
        state.selectedProfileItems.add(url);
      } else {
        state.selectedProfileItems.delete(url);
      }
    });
    updateProfileSelectionUI();
  });

  // Clique na Marca/Logo para voltar à Home (Baixar)
  const brandBtn = document.getElementById('brand-logo-btn');
  if (brandBtn) {
    brandBtn.addEventListener('click', () => {
      document.getElementById('tab-download').click();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
    brandBtn.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        brandBtn.click();
      }
    });
  }

  document.getElementById('btn-download-selected').addEventListener('click', handleDownloadSelectedProfile);
});

// ==========================================
// CARDS DE RECURSOS CLICÁVEIS (HOME)
// ==========================================
function initClickableCards() {
  const cards = document.querySelectorAll('.clickable-card');
  cards.forEach(card => {
    card.addEventListener('click', () => {
      const action = card.getAttribute('data-action');
      if (action === 'platform') {
        const platform = card.getAttribute('data-platform');
        const targetPill = document.querySelector(`.pill-btn[data-platform="${platform}"]`);
        if (targetPill) {
          targetPill.click();
          const input = document.getElementById('url-input');
          input.focus();
          document.getElementById('inspect-form').scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      } else if (action === 'tab') {
        const tabId = card.getAttribute('data-tab');
        const targetTab = document.getElementById(tabId);
        if (targetTab) {
          targetTab.click();
        }
      }
    });
  });
}

