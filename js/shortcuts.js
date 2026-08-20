/**
 * FrameStudio - Gerenciador de Atalhos de Teclado (One-Hand Workflow)
 */

class ShortcutsManager {
    constructor(app) {
        this.app = app;
        this.modalElement = document.getElementById('shortcuts-modal');
        this.btnOpenModal = document.getElementById('btn-shortcuts-info');
        this.btnCloseModal = document.getElementById('btn-close-shortcuts-modal');

        this.init();
    }

    init() {
        this.bindGlobalKeys();
        this.bindModalEvents();
    }

    bindGlobalKeys() {
        window.addEventListener('keydown', (e) => {
            // Ignora se estiver digitando em um input ou select
            if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) {
                return;
            }

            const key = e.key.toUpperCase();

            // Play / Pause
            if (e.code === 'Space' || key === 'K') {
                e.preventDefault();
                this.app.togglePlay();
                return;
            }

            // Capturar Frame
            if (key === 'C') {
                e.preventDefault();
                this.app.captureFrame();
                return;
            }

            // Lupa de Inspeção de Foco
            if (key === 'Z') {
                e.preventDefault();
                if (this.app.toggleLoupe) {
                    this.app.toggleLoupe();
                }
                return;
            }

            // Marcar Início do Burst
            if (key === 'I' || e.key === '[') {
                e.preventDefault();
                if (this.app.setBurstStartCurrent) {
                    this.app.setBurstStartCurrent();
                }
                return;
            }

            // Marcar Fim do Burst
            if (key === 'O' || e.key === ']') {
                e.preventDefault();
                if (this.app.setBurstEndCurrent) {
                    this.app.setBurstEndCurrent();
                }
                return;
            }

            // Disparar Sequência (Burst)
            if (key === 'B') {
                e.preventDefault();
                if (this.app.captureBurst) {
                    this.app.captureBurst();
                }
                return;
            }

            // Navegação de Tempo (Frame a Frame e Segundos)
            if (e.key === 'ArrowLeft') {
                e.preventDefault();
                if (e.shiftKey) {
                    this.app.videoEngine.step(-1.0);
                } else if (e.altKey) {
                    this.app.videoEngine.step(-0.1);
                } else {
                    this.app.videoEngine.stepFrames(-1);
                }
                return;
            }

            if (e.key === 'ArrowRight') {
                e.preventDefault();
                if (e.shiftKey) {
                    this.app.videoEngine.step(1.0);
                } else if (e.altKey) {
                    this.app.videoEngine.step(0.1);
                } else {
                    this.app.videoEngine.stepFrames(1);
                }
                return;
            }

            // Atalhos de Modal
            if (e.key === '?' || (e.shiftKey && e.key === '/')) {
                e.preventDefault();
                this.openModal();
                return;
            }

            if (e.key === 'Escape') {
                this.closeModal();
            }
        });
    }

    bindModalEvents() {
        if (this.btnOpenModal) {
            this.btnOpenModal.addEventListener('click', () => this.openModal());
        }

        if (this.btnCloseModal) {
            this.btnCloseModal.addEventListener('click', () => this.closeModal());
        }

        if (this.modalElement) {
            this.modalElement.addEventListener('click', (e) => {
                if (e.target === this.modalElement) {
                    this.closeModal();
                }
            });
        }
    }

    openModal() {
        if (this.modalElement) {
            this.modalElement.classList.remove('hidden');
        }
    }

    closeModal() {
        if (this.modalElement) {
            this.modalElement.classList.add('hidden');
        }
    }
}
