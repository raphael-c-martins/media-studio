/**
 * FrameStudio - Aplicação Principal (Orquestrador Híbrido com Suporte a OpenCV)
 * Decodificação de alta performance imune a erros de codec do navegador.
 */

document.addEventListener('DOMContentLoaded', () => {
    // Elementos da Interface
    const uploadSection = document.getElementById('upload-section');
    const workspaceSection = document.getElementById('workspace-section');
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('video-file-input');
    const btnChangeVideo = document.getElementById('btn-change-video');

    // Metadados
    const metaFilename = document.getElementById('meta-filename');
    const metaResolution = document.getElementById('meta-resolution');
    const metaDuration = document.getElementById('meta-duration');
    const selectFps = document.getElementById('select-fps');

    // Player e Visualizadores
    const videoElement = document.getElementById('video-element');
    const playerFrameView = document.getElementById('player-frame-view');
    const extractionCanvas = document.getElementById('hidden-extraction-canvas');
    const cropOverlayGuide = document.getElementById('crop-overlay-guide');
    const videoPlayOverlay = document.getElementById('video-play-overlay');
    const currentTimeDisplay = document.getElementById('current-time-display');
    const totalTimeDisplay = document.getElementById('total-time-display');
    const currentFrameNumber = document.getElementById('current-frame-number');
    const totalFramesNumber = document.getElementById('total-frames-number');
    const timelineSlider = document.getElementById('timeline-slider');
    const timelineProgressBar = document.getElementById('timeline-progress-bar');
    const timelineMarkersContainer = document.getElementById('timeline-markers-container');

    // Controles de Playback
    const btnPlayPause = document.getElementById('btn-play-pause');
    const iconPlay = document.getElementById('icon-play');
    const iconPause = document.getElementById('icon-pause');
    const btnStepBackSec = document.getElementById('btn-step-back-sec');
    const btnStepBackTenth = document.getElementById('btn-step-back-tenth');
    const btnStepBackFrame = document.getElementById('btn-step-back-frame');
    const btnStepFwdFrame = document.getElementById('btn-step-fwd-frame');
    const btnStepFwdTenth = document.getElementById('btn-step-fwd-tenth');
    const btnStepFwdSec = document.getElementById('btn-step-fwd-sec');
    const selectPlaybackRate = document.getElementById('select-playback-rate');

    // Captura e Configurações
    const selectFormat = document.getElementById('select-format');
    const selectAspectRatio = document.getElementById('select-aspect-ratio');
    const btnCaptureFrame = document.getElementById('btn-capture-frame');

    // Amostragem Automática
    const btnAutoSample = document.getElementById('btn-auto-sample');
    const selectSampleCount = document.getElementById('select-sample-count');
    const sampleProgressContainer = document.getElementById('sample-progress-container');
    const sampleProgressBar = document.getElementById('sample-progress-bar');
    const sampleProgressText = document.getElementById('sample-progress-text');
    const suggestedSection = document.getElementById('suggested-frames-section');
    const suggestedGrid = document.getElementById('suggested-frames-grid');
    const btnAddAllSuggested = document.getElementById('btn-add-all-suggested');

    // Instâncias e Estados
    const gallery = new GalleryManager();
    let currentVideoFile = null;
    let currentVideoId = null;
    let currentDuration = 0;
    let currentFps = 30;
    let currentTime = 0;
    let isPlaying = false;
    let playTimer = null;
    let suggestedFramesList = [];

    // Objeto App para atalhos
    const app = {
        gallery,
        togglePlay: () => togglePlayState(),
        toggleLoupe: () => toggleLoupeState(),
        setBurstStartCurrent: () => setBurstStartCurrent(),
        setBurstEndCurrent: () => setBurstEndCurrent(),
        captureBurst: () => executeBurstCapture(),
        captureFrame: () => captureCurrentFrame(),
        videoEngine: {
            isLoaded: true,
            step: (dt) => seekToTime(currentTime + dt),
            stepFrames: (df) => seekToTime(currentTime + (df / currentFps))
        }
    };

    const shortcuts = new ShortcutsManager(app);

    // ==========================================
    // Upload & Processamento
    // ==========================================

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => {
        dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            handleVideoFile(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files.length > 0) {
            handleVideoFile(e.target.files[0]);
        }
    });

    if (btnChangeVideo) {
        btnChangeVideo.addEventListener('click', () => {
            fileInput.click();
        });
    }

    async function handleVideoFile(file) {
        if (!file.name.match(/\.(mp4|webm|mov|mkv|ogg|avi|m4v)$/i)) {
            Toast.error('Por favor, selecione um arquivo de vídeo válido.');
            return;
        }

        try {
            Toast.info(`Enviando vídeo para decodificação nativa: ${file.name}...`);
            currentVideoFile = file;

            // Envia para o backend com decodificador OpenCV (suporta 4K, HEVC, ProRes, etc.)
            const formData = new FormData();
            formData.append('file', file);

            const response = await fetch('/api/upload', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error('Falha ao processar o vídeo no servidor.');
            }

            const data = await response.json();
            currentVideoId = data.video_id;
            currentDuration = data.duration;
            currentFps = data.fps || 30;
            currentTime = 0;

            // Atualiza Metadados na UI
            metaFilename.textContent = data.filename;
            metaResolution.textContent = `${data.width} x ${data.height}`;
            metaDuration.textContent = VideoEngine.formatTime(data.duration);
            totalTimeDisplay.textContent = VideoEngine.formatTime(data.duration);

            // Ajusta FPS no seletor
            selectFps.value = String(Math.round(currentFps)) || '30';

            // Alterna visibilidade
            uploadSection.classList.add('hidden');
            workspaceSection.classList.remove('hidden');
            btnChangeVideo.classList.remove('hidden');

            // Configura timeline slider
            timelineSlider.min = 0;
            timelineSlider.max = data.duration;
            timelineSlider.value = 0;
            updateTimelineUI(0, data.duration);

            // Alterna para o visualizador de frame do OpenCV (sem tela preta)
            videoElement.classList.add('hidden');
            playerFrameView.classList.remove('hidden');

            // Carrega o primeiro frame imediatamente
            await updatePlayerFrame(0.001);

            Toast.success('Vídeo decodificado com sucesso!');

            // Dispara amostragem automática de miniaturas
            generateAutoSamples();
        } catch (err) {
            console.error('Erro no upload/decodificação:', err);
            Toast.error(err.message || 'Erro ao decodificar o vídeo.');
        }
    }

    // ==========================================
    // Renderização e Navegação Frame a Frame
    // ==========================================

    let isFetchingFrame = false;
    let pendingTime = null;

    async function updatePlayerFrame(targetTime) {
        if (!currentVideoId) return;

        currentTime = Math.max(0, Math.min(targetTime, currentDuration));
        updateTimelineUI(currentTime, currentDuration);

        if (isFetchingFrame) {
            pendingTime = currentTime;
            return;
        }

        isFetchingFrame = true;
        const frameUrl = `/api/preview?video_id=${currentVideoId}&time=${currentTime.toFixed(2)}`;

        const img = new Image();
        img.onload = () => {
            playerFrameView.src = frameUrl;
            isFetchingFrame = false;
            if (pendingTime !== null) {
                const nextTime = pendingTime;
                pendingTime = null;
                updatePlayerFrame(nextTime);
            }
        };
        img.onerror = () => {
            isFetchingFrame = false;
        };
        img.src = frameUrl;
    }

    function seekToTime(targetTime) {
        timelineSlider.value = targetTime;
        updatePlayerFrame(targetTime);
    }

    // Timeline Slider
    timelineSlider.addEventListener('input', (e) => {
        const target = parseFloat(e.target.value);
        updatePlayerFrame(target);
    });

    function updateTimelineUI(time, duration) {
        currentTimeDisplay.textContent = VideoEngine.formatTime(time);
        
        const percent = duration > 0 ? (time / duration) * 100 : 0;
        timelineProgressBar.style.width = `${percent}%`;

        const currentFrame = Math.floor(time * currentFps);
        const totalFrames = Math.floor(duration * currentFps);
        
        currentFrameNumber.textContent = currentFrame;
        totalFramesNumber.textContent = totalFrames;
    }

    // Controles de Micro-Passo
    btnStepBackSec.addEventListener('click', () => seekToTime(currentTime - 1));
    btnStepBackTenth.addEventListener('click', () => seekToTime(currentTime - 0.1));
    btnStepBackFrame.addEventListener('click', () => seekToTime(currentTime - (1 / currentFps)));
    btnStepFwdFrame.addEventListener('click', () => seekToTime(currentTime + (1 / currentFps)));
    btnStepFwdTenth.addEventListener('click', () => seekToTime(currentTime + 0.1));
    btnStepFwdSec.addEventListener('click', () => seekToTime(currentTime + 1));

    // Playback
    function togglePlayState() {
        if (isPlaying) {
            pauseVideo();
        } else {
            playVideo();
        }
    }

    function playVideo() {
        if (isPlaying || !currentVideoId) return;
        isPlaying = true;
        iconPlay.classList.add('hidden');
        iconPause.classList.remove('hidden');
        videoPlayOverlay.classList.remove('show');

        const rate = parseFloat(selectPlaybackRate.value) || 1.0;
        const intervalMs = Math.round(1000 / (currentFps * rate));

        playTimer = setInterval(() => {
            if (currentTime >= currentDuration) {
                pauseVideo();
                seekToTime(0);
                return;
            }
            seekToTime(currentTime + (1 / currentFps));
        }, intervalMs);
    }

    function pauseVideo() {
        isPlaying = false;
        if (playTimer) {
            clearInterval(playTimer);
            playTimer = null;
        }
        iconPlay.classList.remove('hidden');
        iconPause.classList.add('hidden');
        videoPlayOverlay.classList.add('show');
    }

    playerFrameView.addEventListener('click', togglePlayState);
    btnPlayPause.addEventListener('click', togglePlayState);

    selectPlaybackRate.addEventListener('change', () => {
        if (isPlaying) {
            pauseVideo();
            playVideo();
        }
    });

    selectFps.addEventListener('change', () => {
        currentFps = parseInt(selectFps.value, 10) || 30;
        updateTimelineUI(currentTime, currentDuration);
    });

    // ==========================
    // Guia de Aspect Ratio
    // ==========================
    selectAspectRatio.addEventListener('change', () => {
        updateCropOverlay();
        updatePlayerFrame(currentTime);
    });

    function updateCropOverlay() {
        const ratio = selectAspectRatio.value;
        if (ratio === 'original') {
            cropOverlayGuide.classList.add('hidden');
            return;
        }

        const ratios = {
            '16:9': 16 / 9,
            '9:16': 9 / 16,
            '1:1': 1 / 1,
            '4:5': 4 / 5
        };

        const targetRatio = ratios[ratio];
        if (!targetRatio) {
            cropOverlayGuide.classList.add('hidden');
            return;
        }

        const rect = playerFrameView.getBoundingClientRect();
        const currentRatio = rect.width / rect.height;

        let guideWidth, guideHeight;

        if (currentRatio > targetRatio) {
            guideHeight = rect.height;
            guideWidth = guideHeight * targetRatio;
        } else {
            guideWidth = rect.width;
            guideHeight = guideWidth / targetRatio;
        }

        cropOverlayGuide.style.width = `${guideWidth}px`;
        cropOverlayGuide.style.height = `${guideHeight}px`;
        cropOverlayGuide.classList.remove('hidden');
    }

    window.addEventListener('resize', () => {
        if (!cropOverlayGuide.classList.contains('hidden')) {
            updateCropOverlay();
        }
    });

    // ==========================================
    // Captura de Frames
    // ==========================================

    btnCaptureFrame.addEventListener('click', captureCurrentFrame);

    async function captureCurrentFrame() {
        if (!currentVideoId) {
            Toast.warning('Nenhum vídeo carregado.');
            return;
        }

        try {
            const format = selectFormat.value === 'image/png' ? 'png' : 'jpeg';
            const aspect = selectAspectRatio.value;

            Toast.info('Extraindo frame em resolução nativa...');

            const frameUrl = `/api/frame?video_id=${currentVideoId}&time=${currentTime.toFixed(3)}&format=${format}&aspect_ratio=${aspect}`;
            const response = await fetch(frameUrl);
            if (!response.ok) throw new Error('Erro ao capturar frame no servidor.');

            const blob = await response.blob();
            const dataUrl = URL.createObjectURL(blob);

            // Cria imagem para obter largura/altura exata
            const img = new Image();
            img.onload = () => {
                const timeFormatted = VideoEngine.formatTime(currentTime);
                gallery.addFrame({
                    blob,
                    dataUrl,
                    width: img.naturalWidth,
                    height: img.naturalHeight,
                    time: currentTime,
                    timeFormatted,
                    format: format === 'png' ? 'image/png' : 'image/jpeg'
                });
                addTimelineMarker(currentTime);
            };
            img.src = dataUrl;
        } catch (err) {
            console.error('Erro na captura:', err);
            Toast.error('Erro ao capturar o frame.');
        }
    }

    function addTimelineMarker(time) {
        if (currentDuration <= 0) return;

        const percent = (time / currentDuration) * 100;
        const marker = document.createElement('div');
        marker.className = 'timeline-marker';
        marker.style.left = `${percent}%`;
        marker.title = `Captura: ${VideoEngine.formatTime(time)}`;
        timelineMarkersContainer.appendChild(marker);
    }

    // ==========================================
    // Amostragem Automática
    // ==========================================

    btnAutoSample.addEventListener('click', generateAutoSamples);

    async function generateAutoSamples() {
        if (!currentVideoId) return;

        const count = parseInt(selectSampleCount.value, 10) || 12;
        sampleProgressContainer.classList.remove('hidden');
        sampleProgressBar.style.width = '50%';
        sampleProgressText.textContent = 'Decodificando miniaturas em alta velocidade...';
        btnAutoSample.disabled = true;

        try {
            const response = await fetch(`/api/samples?video_id=${currentVideoId}&count=${count}`);
            if (!response.ok) throw new Error('Erro ao gerar amostras no servidor.');

            const data = await response.json();
            suggestedFramesList = data.samples || [];

            renderSuggestedFrames(suggestedFramesList);
            suggestedSection.classList.remove('hidden');
            Toast.success(`${suggestedFramesList.length} frames sugeridos gerados com sucesso!`);
        } catch (err) {
            console.error('Erro nas amostras:', err);
            Toast.error('Erro ao gerar sugestões automáticas.');
        } finally {
            sampleProgressContainer.classList.add('hidden');
            btnAutoSample.disabled = false;
        }
    }

    function renderSuggestedFrames(samples) {
        suggestedGrid.innerHTML = '';
        samples.forEach((sample) => {
            const card = document.createElement('div');
            card.className = 'suggested-card';
            card.innerHTML = `
                <img src="${sample.dataUrl}" alt="Sugestão ${sample.timeFormatted}" class="suggested-thumb" loading="lazy">
                <div class="suggested-footer">
                    <span class="suggested-time">${sample.timeFormatted}</span>
                    <button class="btn-add-suggested" title="Adicionar à Galeria">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="12" y1="5" x2="12" y2="19"></line>
                            <line x1="5" y1="12" x2="19" y2="12"></line>
                        </svg>
                    </button>
                </div>
            `;

            // Clique na miniatura: navega até o ponto
            card.addEventListener('click', (e) => {
                if (!e.target.closest('.btn-add-suggested')) {
                    seekToTime(sample.time);
                    Toast.info(`Posicionado em ${sample.timeFormatted}`);
                }
            });

            // Clique no +: adiciona frame em resolução nativa na galeria
            const btnAdd = card.querySelector('.btn-add-suggested');
            btnAdd.addEventListener('click', async (e) => {
                e.stopPropagation();
                seekToTime(sample.time);
                await captureCurrentFrame();
            });

            suggestedGrid.appendChild(card);
        });
    }

    btnAddAllSuggested.addEventListener('click', async () => {
        if (suggestedFramesList.length === 0) return;
        Toast.info(`Salvando todos os ${suggestedFramesList.length} frames sugeridos na galeria...`);

        for (const sample of suggestedFramesList) {
            seekToTime(sample.time);
            await captureCurrentFrame();
        }

        Toast.success('Todos os frames sugeridos foram adicionados à galeria!');
    });
}
    // ==========================================
    // Lupa de Inspeção de Foco (Pixel Peeping)
    // ==========================================
    const btnToggleLoupe = document.getElementById('btn-toggle-loupe');
    const magnifierLens = document.getElementById('magnifier-lens');
    const magnifierCanvas = document.getElementById('magnifier-canvas');
    const magnifierZoomLevel = document.getElementById('magnifier-zoom-level');
    let magnifierCtx = magnifierCanvas ? magnifierCanvas.getContext('2d') : null;
    let isLoupeActive = false;
    let loupeZoom = 2.5;

    function toggleLoupeState() {
        isLoupeActive = !isLoupeActive;
        if (btnToggleLoupe) {
            btnToggleLoupe.classList.toggle('active', isLoupeActive);
        }
        if (!isLoupeActive && magnifierLens) {
            magnifierLens.classList.add('hidden');
        }
        Toast.info(isLoupeActive ? 'Lupa de Foco ativada (Passe o mouse na imagem)' : 'Lupa de Foco desativada');
    }

    if (btnToggleLoupe) {
        btnToggleLoupe.addEventListener('click', toggleLoupeState);
    }

    if (playerFrameView && magnifierLens && magnifierCanvas) {
        playerFrameView.addEventListener('mousemove', (e) => {
            if (!isLoupeActive || playerFrameView.classList.contains('hidden')) return;

            const rect = playerFrameView.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            if (mouseX < 0 || mouseX > rect.width || mouseY < 0 || mouseY > rect.height) {
                magnifierLens.classList.add('hidden');
                return;
            }

            magnifierLens.classList.remove('hidden');

            const containerRect = playerFrameView.parentElement.getBoundingClientRect();
            const lensX = e.clientX - containerRect.left;
            const lensY = e.clientY - containerRect.top;

            magnifierLens.style.left = `${lensX}px`;
            magnifierLens.style.top = `${lensY}px`;

            // Desenhar a área ampliada
            const naturalW = playerFrameView.naturalWidth || rect.width;
            const naturalH = playerFrameView.naturalHeight || rect.height;
            const scaleX = naturalW / rect.width;
            const scaleY = naturalH / rect.height;

            const sourceCenterX = mouseX * scaleX;
            const sourceCenterY = mouseY * scaleY;

            const lensW = magnifierCanvas.width;
            const lensH = magnifierCanvas.height;
            const sampleW = lensW / loupeZoom;
            const sampleH = lensH / loupeZoom;

            const sx = Math.max(0, Math.min(naturalW - sampleW, sourceCenterX - sampleW / 2));
            const sy = Math.max(0, Math.min(naturalH - sampleH, sourceCenterY - sampleH / 2));

            magnifierCtx.imageSmoothingEnabled = false; // Máxima nitidez
            magnifierCtx.clearRect(0, 0, lensW, lensH);
            magnifierCtx.drawImage(playerFrameView, sx, sy, sampleW, sampleH, 0, 0, lensW, lensH);
        });

        playerFrameView.addEventListener('mouseleave', () => {
            if (magnifierLens) magnifierLens.classList.add('hidden');
        });

        // Alternar zoom com scroll do mouse
        playerFrameView.addEventListener('wheel', (e) => {
            if (!isLoupeActive) return;
            e.preventDefault();
            if (e.deltaY < 0) {
                loupeZoom = Math.min(6.0, loupeZoom + 0.5);
            } else {
                loupeZoom = Math.max(1.5, loupeZoom - 0.5);
            }
            if (magnifierZoomLevel) {
                magnifierZoomLevel.textContent = `${loupeZoom.toFixed(1)}x`;
            }
        });
    }

    // ==========================================
    // Captura de Sequência (Burst / Carrossel)
    // ==========================================
    const burstStartDisplay = document.getElementById('burst-start-display');
    const burstEndDisplay = document.getElementById('burst-end-display');
    const btnSetBurstStart = document.getElementById('btn-set-burst-start');
    const btnSetBurstEnd = document.getElementById('btn-set-burst-end');
    const selectBurstCount = document.getElementById('select-burst-count');
    const btnCaptureBurst = document.getElementById('btn-capture-burst');

    let burstStartTime = 0;
    let burstEndTime = 0;

    function formatShortTime(t) {
        const mins = Math.floor(t / 60);
        const secs = Math.floor(t % 60);
        const dec = Math.floor((t % 1) * 10);
        return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${dec}s`;
    }

    function setBurstStartCurrent() {
        burstStartTime = currentTime;
        if (burstEndTime < burstStartTime) {
            burstEndTime = Math.min(currentDuration, burstStartTime + 2.0);
            if (burstEndDisplay) burstEndDisplay.textContent = formatShortTime(burstEndTime);
        }
        if (burstStartDisplay) burstStartDisplay.textContent = formatShortTime(burstStartTime);
        Toast.info(`Ponto A (Início) definido em ${formatShortTime(burstStartTime)}`);
    }

    function setBurstEndCurrent() {
        if (currentTime <= burstStartTime) {
            Toast.warning('O Ponto B (Fim) deve ser maior que o Ponto A (Início).');
            return;
        }
        burstEndTime = currentTime;
        if (burstEndDisplay) burstEndDisplay.textContent = formatShortTime(burstEndTime);
        Toast.info(`Ponto B (Fim) definido em ${formatShortTime(burstEndTime)}`);
    }

    if (btnSetBurstStart) btnSetBurstStart.addEventListener('click', setBurstStartCurrent);
    if (btnSetBurstEnd) btnSetBurstEnd.addEventListener('click', setBurstEndCurrent);

    async function executeBurstCapture() {
        if (!currentVideoId) {
            Toast.warning('Carregue um vídeo antes de extrair uma sequência.');
            return;
        }

        if (burstEndTime <= burstStartTime) {
            burstEndTime = Math.min(currentDuration, burstStartTime + 2.0);
            if (burstEndDisplay) burstEndDisplay.textContent = formatShortTime(burstEndTime);
        }

        const count = parseInt(selectBurstCount ? selectBurstCount.value : '6', 10);
        const format = selectFormat ? selectFormat.value.split('/')[1] : 'jpeg';
        const aspectRatio = selectAspectRatio ? selectAspectRatio.value : 'original';

        Toast.info(`Extraindo sequência de ${count} fotos em alta resolução...`);
        btnCaptureBurst.disabled = true;

        try {
            const url = `/api/burst?video_id=${currentVideoId}&start_time=${burstStartTime}&end_time=${burstEndTime}&count=${count}&format=${format}&aspect_ratio=${aspectRatio}`;
            const response = await fetch(url);
            if (!response.ok) throw new Error('Falha ao processar sequência no servidor.');

            const data = await response.json();
            const frames = data.frames || [];

            if (frames.length === 0) {
                Toast.warning('Nenhum frame retornado na sequência.');
                return;
            }

            for (const f of frames) {
                gallery.addFrame({
                    dataUrl: f.dataUrl,
                    time: f.time,
                    timeFormatted: f.timeFormatted,
                    width: f.width,
                    height: f.height,
                    format: format,
                    aspectRatio: aspectRatio
                });
            }

            Toast.success(`${frames.length} fotos da sequência adicionadas à Galeria!`);
        } catch (err) {
            console.error('Erro no burst:', err);
            Toast.error('Erro ao capturar sequência de frames.');
        } finally {
            btnCaptureBurst.disabled = false;
        }
    }

    if (btnCaptureBurst) {
        btnCaptureBurst.addEventListener('click', executeBurstCapture);
    }

});
