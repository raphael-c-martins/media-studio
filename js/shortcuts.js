/**
 * FrameStudio - Módulo de Atalhos de Teclado
 * Gerenciamento ergonômico de atalhos para edição ágil e precisa.
 */

class ShortcutsManager {
    constructor(app) {
        this.app = app;
        this.modal = document.getElementById('shortcuts-modal');
        this.btnOpen = document.getElementById('btn-shortcuts');
        this.btnClose = document.getElementById('shortcuts-btn-close');

        this._initEvents();
    }

    _initEvents() {
        if (this.btnOpen) {
            this.btnOpen.addEventListener('click', () => this.openModal());
        }

        if (this.btnClose) {
            this.btnClose.addEventListener('click', () => this.closeModal());
        }

        if (this.modal) {
            this.modal.addEventListener('click', (e) => {
                if (e.target === this.modal) {
                    this.closeModal();
                }
            });
        }

        window.addEventListener('keydown', (e) => this._handleKeyDown(e));
    }

    _handleKeyDown(e) {
        // Ignora atalhos se o foco estiver em inputs/selects
        const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
        if (activeTag === 'input' && document.activeElement.type !== 'range') return;
        if (activeTag === 'textarea' || activeTag === 'select') return;

        // Tecla ESC: Fechar qualquer modal aberto
        if (e.key === 'Escape') {
            this.closeModal();
            if (this.app.gallery) {
                this.app.gallery.closeModal();
            }
            return;
        }

        // Tecla ?: Abrir modal de atalhos
        if (e.key === '?' || (e.shiftKey && e.key === '/')) {
            e.preventDefault();
            this.toggleModal();
            return;
        }

        // Se o workspace não estiver visível (nenhum vídeo carregado), ignora atalhos de playback
        if (!this.app.videoEngine || !this.app.videoEngine.isLoaded) return;

        // Play / Pause (Espaço ou K)
        if (e.code === 'Space' || e.key.toLowerCase() === 'k') {
            e.preventDefault();
            this.app.togglePlay();
            return;
        }

        // Capturar Frame (Tecla C)
        if (e.key.toLowerCase() === 'c') {
            e.preventDefault();
            this.app.captureFrame();
            return;
        }

        // Navegação de Linha do Tempo (Setas Esquerda / Direita)
        if (e.key === 'ArrowLeft') {
            e.preventDefault();
            if (e.shiftKey) {
                this.app.videoEngine.step(-1); // -1s
            } else if (e.altKey) {
                this.app.videoEngine.step(-0.1); // -0.1s
            } else {
                this.app.videoEngine.stepFrames(-1); // -1 frame
            }
            return;
        }

        if (e.key === 'ArrowRight') {
            e.preventDefault();
            if (e.shiftKey) {
                this.app.videoEngine.step(1); // +1s
            } else if (e.altKey) {
                this.app.videoEngine.step(0.1); // +0.1s
            } else {
                this.app.videoEngine.stepFrames(1); // +1 frame
            }
            return;
        }
    }

    openModal() {
        if (this.modal) this.modal.classList.remove('hidden');
    }

    closeModal() {
        if (this.modal) this.modal.classList.add('hidden');
    }

    toggleModal() {
        if (this.modal) {
            this.modal.classList.toggle('hidden');
        }
    }
}
