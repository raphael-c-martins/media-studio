/**
 * FrameStudio - Motor de Vídeo & Renderizador de Frames
 * Decodificação de alta performance via HTML5 Video + Canvas 2D.
 * Imune ao problema de tela verde do reprodutor do Windows.
 */

class VideoEngine {
    constructor(videoElement, canvasElement) {
        this.video = videoElement;
        this.canvas = canvasElement || document.createElement('canvas');
        this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
        
        this.currentFile = null;
        this.videoUrl = null;
        this.fps = 30;
        this.isLoaded = false;
        
        // Listeners internos
        this.onTimeUpdateCallback = null;
        this.onLoadedMetadataCallback = null;
        
        this._initEvents();
    }

    _initEvents() {
        this.video.addEventListener('loadedmetadata', () => {
            this.isLoaded = true;
            if (this.onLoadedMetadataCallback) {
                this.onLoadedMetadataCallback({
                    duration: this.video.duration,
                    width: this.video.videoWidth,
                    height: this.video.videoHeight,
                    filename: this.currentFile ? this.currentFile.name : 'video'
                });
            }
        });

        this.video.addEventListener('timeupdate', () => {
            if (this.onTimeUpdateCallback) {
                this.onTimeUpdateCallback(this.video.currentTime, this.video.duration);
            }
        });
    }

    /**
     * Carrega um arquivo de vídeo no player com tratamento resiliente de eventos e codecs.
     * @param {File} file 
     */
    async loadFile(file) {
        if (!file) return;

        if (this.videoUrl) {
            URL.revokeObjectURL(this.videoUrl);
        }

        this.currentFile = file;
        this.isLoaded = false;

        // Garante que o vídeo esteja mudo no carregamento inicial para evitar bloqueios de áudio/autoplay
        this.video.muted = true;
        this.video.playsInline = true;
        this.video.preload = 'auto';

        // Inferência inteligente de MIME type caso o Windows envie vazio ou octet-stream
        let videoBlob = file;
        if (!file.type || file.type === 'application/octet-stream') {
            const ext = (file.name.split('.').pop() || '').toLowerCase();
            const mimeTypes = {
                'mp4': 'video/mp4',
                'm4v': 'video/mp4',
                'webm': 'video/webm',
                'mov': 'video/quicktime',
                'mkv': 'video/x-matroska',
                'ogg': 'video/ogg',
                'ogv': 'video/ogg'
            };
            if (mimeTypes[ext]) {
                videoBlob = new Blob([file], { type: mimeTypes[ext] });
            }
        }

        this.videoUrl = URL.createObjectURL(videoBlob);

        return new Promise((resolve, reject) => {
            let isResolved = false;

            const cleanup = () => {
                this.video.removeEventListener('loadedmetadata', checkSuccess);
                this.video.removeEventListener('loadeddata', checkSuccess);
                this.video.removeEventListener('canplay', checkSuccess);
                this.video.removeEventListener('error', onError);
            };

            const checkSuccess = () => {
                if (isResolved) return;
                // Valida se os metadados essenciais estão prontos
                if (this.video.videoWidth > 0 && !isNaN(this.video.duration) && this.video.duration > 0) {
                    isResolved = true;
                    this.isLoaded = true;
                    cleanup();
                    resolve({
                        duration: this.video.duration,
                        width: this.video.videoWidth,
                        height: this.video.videoHeight,
                        filename: file.name
                    });
                }
            };

            const onError = () => {
                if (isResolved) return;
                isResolved = true;
                cleanup();

                const err = this.video.error;
                let errorMsg = 'Falha ao decodificar o vídeo.';

                if (err) {
                    switch (err.code) {
                        case 1: // MEDIA_ERR_ABORTED
                            errorMsg = 'Carregamento do vídeo foi cancelado.';
                            break;
                        case 2: // MEDIA_ERR_NETWORK
                            errorMsg = 'Erro de leitura do arquivo no disco.';
                            break;
                        case 3: // MEDIA_ERR_DECODE
                            errorMsg = 'Erro na decodificação do vídeo (arquivo corrompido ou codec incompatível).';
                            break;
                        case 4: // MEDIA_ERR_SRC_NOT_SUPPORTED
                            errorMsg = 'Codec não suportado nativamente pelo navegador atual (ex: HEVC/H.265 ou ProRes). Dica: Abra no Microsoft Edge ou converta para MP4 H.264.';
                            break;
                        default:
                            errorMsg = err.message || errorMsg;
                    }
                }

                reject(new Error(errorMsg));
            };

            this.video.addEventListener('loadedmetadata', checkSuccess);
            this.video.addEventListener('loadeddata', checkSuccess);
            this.video.addEventListener('canplay', checkSuccess);
            this.video.addEventListener('error', onError);

            this.video.src = this.videoUrl;
            this.video.load();

            // Verificação imediata se o cache já tiver carregado os metadados
            if (this.video.readyState >= 1 && this.video.videoWidth > 0) {
                checkSuccess();
            }

            // Timeout de segurança tolerante
            setTimeout(() => {
                if (!isResolved) {
                    if (this.video.videoWidth > 0 && this.video.duration > 0) {
                        checkSuccess();
                    } else {
                        isResolved = true;
                        cleanup();
                        reject(new Error('Tempo limite excedido ao processar o vídeo. O arquivo pode estar corrompido ou em codec incompatível.'));
                    }
                }
            }, 10000);
        });
    }

    setFps(fps) {
        this.fps = Number(fps) || 30;
    }

    getFps() {
        return this.fps;
    }

    getCurrentTime() {
        return this.video.currentTime;
    }

    getDuration() {
        return this.video.duration || 0;
    }

    getVideoResolution() {
        return {
            width: this.video.videoWidth || 0,
            height: this.video.videoHeight || 0
        };
    }

    async play() {
        try {
            return await this.video.play();
        } catch (err) {
            console.warn('Reprodução com áudio restrita pelo navegador, reproduzindo em modo mudo:', err);
            this.video.muted = true;
            return await this.video.play();
        }
    }

    pause() {
        this.video.pause();
    }

    async togglePlay() {
        if (this.video.paused) {
            return await this.play();
        } else {
            this.pause();
            return Promise.resolve();
        }
    }

    /**
     * Posiciona o vídeo em um tempo exato com Promise assíncrona e garantia de pintura de frame na GPU.
     * @param {number} targetTime - Tempo em segundos
     * @returns {Promise<number>}
     */
    seekTo(targetTime) {
        return new Promise((resolve) => {
            const duration = this.video.duration || 0;
            const clampedTime = Math.max(0, Math.min(targetTime, duration));
            
            const finishSeek = () => {
                this.video.removeEventListener('seeked', onSeeked);
                // Utiliza requestVideoFrameCallback para garantir que o frame foi pintado na GPU
                if ('requestVideoFrameCallback' in this.video) {
                    this.video.requestVideoFrameCallback(() => resolve(this.video.currentTime));
                } else {
                    setTimeout(() => resolve(this.video.currentTime), 60);
                }
            };

            const onSeeked = () => {
                finishSeek();
            };

            this.video.addEventListener('seeked', onSeeked, { once: true });
            this.video.currentTime = clampedTime;

            // Timeout de segurança tolerante
            setTimeout(() => {
                this.video.removeEventListener('seeked', onSeeked);
                resolve(this.video.currentTime);
            }, 350);
        });
    }

    /**
     * Passo de micro-navegação (frame, décimo ou segundo).
     * @param {number} deltaSeconds - Quantidade em segundos para avançar ou recuar
     */
    step(deltaSeconds) {
        const target = this.video.currentTime + deltaSeconds;
        return this.seekTo(target);
    }

    /**
     * Avança ou recua exatamente 1 frame com base no FPS configurado.
     * @param {number} frameCount - Quantidade de frames (ex: +1 ou -1)
     */
    stepFrames(frameCount) {
        const frameDuration = 1 / this.fps;
        return this.step(frameCount * frameDuration);
    }

    /**
     * Captura o frame atual do vídeo em resolução nativa com suporte a corte de proporção.
     * @param {Object} options 
     * @param {string} options.format - 'image/png' | 'image/jpeg' | 'image/webp'
     * @param {string} options.aspectRatio - 'original' | '16:9' | '9:16' | '1:1' | '4:5'
     * @param {number} options.quality - 0.0 a 1.0 (para jpeg/webp)
     * @returns {Promise<{blob: Blob, dataUrl: string, width: number, height: number, time: number, timeFormatted: string}>}
     */
    async captureCurrentFrame(options = {}) {
        if (!this.isLoaded || this.video.videoWidth === 0) {
            throw new Error('Nenhum vídeo carregado para captura.');
        }

        const format = options.format || 'image/png';
        const quality = options.quality !== undefined ? options.quality : 1.0;
        const aspectRatio = options.aspectRatio || 'original';

        const sourceWidth = this.video.videoWidth;
        const sourceHeight = this.video.videoHeight;

        let cropX = 0;
        let cropY = 0;
        let cropWidth = sourceWidth;
        let cropHeight = sourceHeight;

        // Cálculo de corte (Crop) centralizado se houver proporção customizada
        if (aspectRatio !== 'original') {
            const ratios = {
                '16:9': 16 / 9,
                '9:16': 9 / 16,
                '1:1': 1 / 1,
                '4:5': 4 / 5
            };

            const targetRatio = ratios[aspectRatio];
            if (targetRatio) {
                const currentRatio = sourceWidth / sourceHeight;
                if (currentRatio > targetRatio) {
                    // Corta as laterais (mantém altura máxima)
                    cropHeight = sourceHeight;
                    cropWidth = Math.round(sourceHeight * targetRatio);
                    cropX = Math.round((sourceWidth - cropWidth) / 2);
                    cropY = 0;
                } else {
                    // Corta topo e base (mantém largura máxima)
                    cropWidth = sourceWidth;
                    cropHeight = Math.round(sourceWidth / targetRatio);
                    cropX = 0;
                    cropY = Math.round((sourceHeight - cropHeight) / 2);
                }
            }
        }

        // Configura dimensões exatas do canvas para máxima fidelidade
        this.canvas.width = cropWidth;
        this.canvas.height = cropHeight;

        // Renderização direta do buffer de vídeo (Anti-Tela Verde)
        this.ctx.clearRect(0, 0, cropWidth, cropHeight);
        this.ctx.imageSmoothingEnabled = true;
        this.ctx.imageSmoothingQuality = 'high';

        this.ctx.drawImage(
            this.video,
            cropX, cropY, cropWidth, cropHeight, // Origem
            0, 0, cropWidth, cropHeight          // Destino
        );

        const currentTime = this.video.currentTime;
        const timeFormatted = VideoEngine.formatTime(currentTime);

        return new Promise((resolve) => {
            this.canvas.toBlob((blob) => {
                const dataUrl = this.canvas.toDataURL(format, quality);
                resolve({
                    blob,
                    dataUrl,
                    width: cropWidth,
                    height: cropHeight,
                    time: currentTime,
                    timeFormatted,
                    format
                });
            }, format, quality);
        });
    }

    /**
     * Formata segundos em HH:MM:SS.mmm
     * @param {number} totalSeconds 
     * @returns {string}
     */
    static formatTime(totalSeconds) {
        if (isNaN(totalSeconds) || totalSeconds < 0) totalSeconds = 0;
        
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = Math.floor(totalSeconds % 60);
        const millis = Math.floor((totalSeconds % 1) * 1000);

        const pad = (n, z = 2) => String(n).padStart(z, '0');

        return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}.${pad(millis, 3)}`;
    }

    /**
     * Formata para nome de arquivo curto e limpo (ex: 03.9s ou 01m20s)
     * @param {number} totalSeconds 
     * @returns {string}
     */
    static formatTimeForFilename(totalSeconds) {
        if (isNaN(totalSeconds) || totalSeconds < 0) totalSeconds = 0;

        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = Math.floor(totalSeconds % 60);
        const tenths = Math.floor((totalSeconds % 1) * 10);

        if (hours > 0) {
            return `${hours}h${String(minutes).padStart(2, '0')}m${String(seconds).padStart(2, '0')}s`;
        }
        if (minutes > 0) {
            return `${String(minutes).padStart(2, '0')}m${String(seconds).padStart(2, '0')}s`;
        }
        return `${String(seconds).padStart(2, '0')}.${tenths}s`;
    }
}
