/**
 * FrameStudio - Amostrador Automático de Frames (Sugestões Inteligentes)
 * Gera miniaturas distribuídas uniformemente ao longo do vídeo de forma assíncrona.
 */

class AutoSampler {
    constructor() {
        this.isProcessing = false;
        this.cancelRequested = false;
    }

    /**
     * Gera uma grade de frames sugeridos para o vídeo fornecido.
     * @param {File} videoFile - Arquivo do vídeo
     * @param {number} sampleCount - Quantidade de frames (ex: 6, 12, 24)
     * @param {Function} onProgress - Callback de progresso (percent, current, total)
     * @returns {Promise<Array<{time: number, timeFormatted: string, dataUrl: string, blob: Blob}>>}
     */
    async generateSamples(videoFile, sampleCount = 12, onProgress = null) {
        if (!videoFile) return [];
        if (this.isProcessing) {
            this.cancel();
        }

        this.isProcessing = true;
        this.cancelRequested = false;

        // Inferência inteligente de MIME type
        let videoBlob = videoFile;
        if (!videoFile.type || videoFile.type === 'application/octet-stream') {
            const ext = (videoFile.name.split('.').pop() || '').toLowerCase();
            const mimeTypes = {
                'mp4': 'video/mp4',
                'm4v': 'video/mp4',
                'webm': 'video/webm',
                'mov': 'video/quicktime',
                'mkv': 'video/x-matroska',
                'ogg': 'video/ogg'
            };
            if (mimeTypes[ext]) {
                videoBlob = new Blob([videoFile], { type: mimeTypes[ext] });
            }
        }

        const videoUrl = URL.createObjectURL(videoBlob);
        const tempVideo = document.createElement('video');
        tempVideo.muted = true;
        tempVideo.playsInline = true;
        tempVideo.preload = 'auto';
        
        // Elemento anexado ao DOM fora de vista para forçar o Chromium a decodificar na GPU
        tempVideo.style.position = 'fixed';
        tempVideo.style.left = '-9999px';
        tempVideo.style.top = '-9999px';
        tempVideo.style.width = '320px';
        tempVideo.style.height = '180px';
        tempVideo.style.opacity = '0';
        tempVideo.style.pointerEvents = 'none';
        document.body.appendChild(tempVideo);

        const tempCanvas = document.createElement('canvas');
        const ctx = tempCanvas.getContext('2d', { willReadFrequently: true });

        const samples = [];

        try {
            // Carrega metadados do vídeo temporário
            await new Promise((resolve, reject) => {
                const onReady = () => {
                    tempVideo.removeEventListener('loadedmetadata', onReady);
                    tempVideo.removeEventListener('canplay', onReady);
                    tempVideo.removeEventListener('error', onError);
                    resolve();
                };
                const onError = () => {
                    tempVideo.removeEventListener('loadedmetadata', onReady);
                    tempVideo.removeEventListener('canplay', onReady);
                    tempVideo.removeEventListener('error', onError);
                    reject(new Error('Erro ao processar amostragem do vídeo.'));
                };

                tempVideo.addEventListener('loadedmetadata', onReady);
                tempVideo.addEventListener('canplay', onReady);
                tempVideo.addEventListener('error', onError);
                tempVideo.src = videoUrl;
                tempVideo.load();

                if (tempVideo.readyState >= 1) {
                    onReady();
                }
            });

            const duration = tempVideo.duration;
            if (!duration || duration <= 0) {
                throw new Error('Duração inválida do vídeo.');
            }

            // Define resolução da miniatura (máxima fidelidade com proporção original)
            const width = tempVideo.videoWidth || 640;
            const height = tempVideo.videoHeight || 360;
            tempCanvas.width = width;
            tempCanvas.height = height;

            // Calcula tempos de amostragem com margem inicial e final (ex: de 2% a 98% da duração)
            const margin = duration * 0.02;
            const effectiveDuration = duration - (margin * 2);
            const step = sampleCount > 1 ? effectiveDuration / (sampleCount - 1) : 0;

            for (let i = 0; i < sampleCount; i++) {
                if (this.cancelRequested) {
                    break;
                }

                const targetTime = sampleCount === 1 ? duration / 2 : margin + (i * step);

                // Aguarda o seek e a pintura do frame na GPU
                await new Promise((resolve) => {
                    const finish = () => {
                        tempVideo.removeEventListener('seeked', onSeeked);
                        if ('requestVideoFrameCallback' in tempVideo) {
                            tempVideo.requestVideoFrameCallback(() => resolve());
                        } else {
                            setTimeout(resolve, 80);
                        }
                    };

                    const onSeeked = () => {
                        finish();
                    };

                    tempVideo.addEventListener('seeked', onSeeked, { once: true });
                    tempVideo.currentTime = targetTime;

                    setTimeout(() => {
                        tempVideo.removeEventListener('seeked', onSeeked);
                        resolve();
                    }, 350);
                });

                // Desenha no canvas
                ctx.clearRect(0, 0, width, height);
                ctx.drawImage(tempVideo, 0, 0, width, height);

                const dataUrl = tempCanvas.toDataURL('image/jpeg', 0.9);
                const timeFormatted = VideoEngine.formatTime(targetTime);

                samples.push({
                    time: targetTime,
                    timeFormatted,
                    dataUrl,
                    width,
                    height
                });

                if (onProgress) {
                    const percent = Math.round(((i + 1) / sampleCount) * 100);
                    onProgress(percent, i + 1, sampleCount);
                }

                // Libera micro-tarefas da thread principal para manter UI 100% responsiva
                await new Promise((r) => setTimeout(r, 10));
            }
        } finally {
            this.isProcessing = false;
            URL.revokeObjectURL(videoUrl);
            tempVideo.src = '';
            if (tempVideo.parentElement) {
                tempVideo.remove();
            }
        }

        return samples;
    }

    cancel() {
        if (this.isProcessing) {
            this.cancelRequested = true;
        }
    }
}
