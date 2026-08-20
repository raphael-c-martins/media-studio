/**
 * FrameStudio - Gerenciador da Galeria de Capturas
 * Exibição, zoom em alta definição, download individual e exportação em lote ZIP.
 */

class GalleryManager {
    constructor() {
        this.frames = [];
        this.gridElement = document.getElementById('gallery-grid');
        this.emptyStateElement = document.getElementById('gallery-empty-state');
        this.counterElement = document.getElementById('gallery-counter');
        this.btnDownloadZip = document.getElementById('btn-download-zip');
        this.btnClearGallery = document.getElementById('btn-clear-gallery');

        // Elementos do Modal de Inspeção
        this.modal = document.getElementById('preview-modal');
        this.modalImg = document.getElementById('modal-preview-img');
        this.modalTitle = document.getElementById('modal-frame-title');
        this.modalInfo = document.getElementById('modal-frame-info');
        this.modalBtnDownload = document.getElementById('modal-btn-download');
        this.modalBtnClose = document.getElementById('modal-btn-close');

        this.currentPreviewFrame = null;

        this._initEvents();
    }

    _initEvents() {
        if (this.btnClearGallery) {
            this.btnClearGallery.addEventListener('click', () => {
                if (this.frames.length === 0) return;
                if (confirm(`Deseja realmente limpar todos os ${this.frames.length} frames capturados?`)) {
                    this.clear();
                    Toast.info('Galeria de capturas limpa.');
                }
            });
        }

        if (this.btnDownloadZip) {
            this.btnDownloadZip.addEventListener('click', () => this.downloadAllAsZip());
        }

        if (this.modalBtnClose) {
            this.modalBtnClose.addEventListener('click', () => this.closeModal());
        }

        if (this.modal) {
            this.modal.addEventListener('click', (e) => {
                if (e.target === this.modal) {
                    this.closeModal();
                }
            });
        }

        if (this.modalBtnDownload) {
            this.modalBtnDownload.addEventListener('click', () => {
                if (this.currentPreviewFrame) {
                    this.downloadFrame(this.currentPreviewFrame);
                }
            });
        }
    }

    /**
     * Adiciona um novo frame capturado à galeria.
     * @param {Object} frameData 
     */
    addFrame(frameData) {
        const id = 'frame_' + Date.now() + '_' + Math.random().toString(36).substr(2, 5);
        const ext = frameData.format === 'image/jpeg' ? 'jpg' : (frameData.format === 'image/webp' ? 'webp' : 'png');
        const filename = `frame_${VideoEngine.formatTimeForFilename(frameData.time)}.${ext}`;

        const frame = {
            id,
            filename,
            blob: frameData.blob,
            dataUrl: frameData.dataUrl,
            width: frameData.width,
            height: frameData.height,
            time: frameData.time,
            timeFormatted: frameData.timeFormatted,
            format: frameData.format,
            ext
        };

        this.frames.unshift(frame); // Adiciona no início
        this.render();
        Toast.success(`Frame [${frame.timeFormatted}] capturado com sucesso!`);
    }

    /**
     * Remove um frame específico.
     * @param {string} id 
     */
    removeFrame(id) {
        this.frames = this.frames.filter(f => f.id !== id);
        this.render();
        Toast.info('Frame removido da galeria.');
    }

    /**
     * Limpa toda a galeria.
     */
    clear() {
        this.frames = [];
        this.render();
    }

    getFramesCount() {
        return this.frames.length;
    }

    /**
     * Renderiza a grade de capturas.
     */
    render() {
        const count = this.frames.length;
        this.counterElement.textContent = count;

        if (count === 0) {
            this.emptyStateElement.classList.remove('hidden');
            this.gridElement.classList.add('hidden');
            this.btnDownloadZip.disabled = true;
            this.btnClearGallery.disabled = true;
            this.gridElement.innerHTML = '';
            return;
        }

        this.emptyStateElement.classList.add('hidden');
        this.gridElement.classList.remove('hidden');
        this.btnDownloadZip.disabled = false;
        this.btnClearGallery.disabled = false;

        this.gridElement.innerHTML = '';

        this.frames.forEach((frame, index) => {
            const card = document.createElement('div');
            card.className = 'gallery-card';
            card.innerHTML = `
                <div class="gallery-thumb-wrapper">
                    <img src="${frame.dataUrl}" alt="Frame ${frame.timeFormatted}" class="gallery-thumb" loading="lazy">
                    <div class="gallery-thumb-overlay">
                        <button class="btn btn-primary btn-sm btn-zoom" title="Inspecionar em Alta Resolução">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <circle cx="11" cy="11" r="8"></circle>
                                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                                <line x1="11" y1="8" x2="11" y2="14"></line>
                                <line x1="8" y1="11" x2="14" y2="11"></line>
                            </svg>
                            Zoom
                        </button>
                    </div>
                </div>
                <div class="gallery-info">
                    <div class="gallery-meta-row">
                        <span class="gallery-time">${frame.timeFormatted}</span>
                        <span class="gallery-res">${frame.width}x${frame.height}</span>
                    </div>
                    <div class="gallery-actions-row">
                        <button class="btn btn-primary btn-sm btn-download-single" style="flex: 1;">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                                <polyline points="7 10 12 15 17 10"></polyline>
                                <line x1="12" y1="15" x2="12" y2="3"></line>
                            </svg>
                            Baixar
                        </button>
                        <button class="btn btn-danger-outline btn-sm btn-remove-single" title="Excluir da Galeria">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                            </svg>
                        </button>
                    </div>
                </div>
            `;

            // Eventos dos botões do card
            const btnZoom = card.querySelector('.btn-zoom');
            const btnDownload = card.querySelector('.btn-download-single');
            const btnRemove = card.querySelector('.btn-remove-single');

            btnZoom.addEventListener('click', () => this.openModal(frame));
            btnDownload.addEventListener('click', () => this.downloadFrame(frame));
            btnRemove.addEventListener('click', () => this.removeFrame(frame.id));

            this.gridElement.appendChild(card);
        });
    }

    /**
     * Abre o modal de inspeção em alta resolução.
     * @param {Object} frame 
     */
    openModal(frame) {
        this.currentPreviewFrame = frame;
        this.modalImg.src = frame.dataUrl;
        this.modalTitle.textContent = `Frame em Alta Resolução (${frame.ext.toUpperCase()})`;
        this.modalInfo.textContent = `${frame.width}x${frame.height} px • Timestamp: ${frame.timeFormatted}`;
        this.modal.classList.remove('hidden');
    }

    closeModal() {
        this.modal.classList.add('hidden');
        this.modalImg.src = '';
        this.currentPreviewFrame = null;
    }

    /**
     * Realiza o download individual de um frame.
     * @param {Object} frame 
     */
    downloadFrame(frame) {
        const link = document.createElement('a');
        link.href = frame.dataUrl;
        link.download = frame.filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        Toast.success(`Download iniciado: ${frame.filename}`);
    }

    /**
     * Compacta todos os frames em um arquivo .ZIP ou baixa diretamente caso haja apenas 1 frame.
     * Caso JSZip não esteja disponível (offline total), realiza download sequencial automático.
     */
    async downloadAllAsZip() {
        const count = this.frames.length;
        if (count === 0) {
            Toast.warning('Nenhum frame para exportar.');
            return;
        }

        // Se for apenas 1 frame, baixa direto a imagem sem zipar
        if (count === 1) {
            this.downloadFrame(this.frames[0]);
            return;
        }

        // Se for mais de 1 frame e JSZip estiver disponível
        if (typeof JSZip !== 'undefined') {
            const zip = new JSZip();

            Toast.info(`Compactando ${count} frames em arquivo .ZIP...`);

            this.frames.forEach((frame, idx) => {
                const indexPadded = String(idx + 1).padStart(2, '0');
                const filename = `frame_${indexPadded}_${VideoEngine.formatTimeForFilename(frame.time)}.${frame.ext}`;
                
                // Adiciona diretamente na raiz do ZIP (sem subpastas aninhadas)
                if (frame.blob) {
                    zip.file(filename, frame.blob);
                } else if (frame.dataUrl && frame.dataUrl.includes(',')) {
                    const base64Data = frame.dataUrl.split(',')[1];
                    zip.file(filename, base64Data, { base64: true });
                }
            });

            try {
                const content = await zip.generateAsync({ type: 'blob' });
                const zipUrl = URL.createObjectURL(content);
                const link = document.createElement('a');
                link.href = zipUrl;
                link.download = `frames_extraidos_${Date.now()}.zip`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                setTimeout(() => URL.revokeObjectURL(zipUrl), 1000);

                Toast.success(`${count} frames baixados em .ZIP com sucesso!`);
                return;
            } catch (err) {
                console.error('Erro ao gerar ZIP, iniciando fallback sequencial:', err);
            }
        }

        // Fallback Sequencial Resiliente
        Toast.info(`Baixando ${count} frames individualmente...`);
        for (let i = 0; i < count; i++) {
            const frame = this.frames[i];
            this.downloadFrame(frame);
            await new Promise((r) => setTimeout(r, 200));
        }
        Toast.success(`Todos os ${count} frames foram baixados!`);
    }
}
