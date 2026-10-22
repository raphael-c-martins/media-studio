// Atalhos básicos do extrator: espaço reproduz/pausa e as setas andam um quadro.
// Só agem com a aba Frames aberta e fora de campos de texto.

const TYPING_TAGS = new Set(['INPUT', 'SELECT', 'TEXTAREA']);

export function initShortcuts(actions, isActive) {
  window.addEventListener('keydown', (event) => {
    if (!isActive() || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    if (TYPING_TAGS.has(event.target.tagName) && event.target.type !== 'range') return;

    if (event.key === ' ') {
      event.preventDefault();
      actions.togglePlay();
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      actions.stepFrames(event.key === 'ArrowLeft' ? -1 : 1);
    }
  });
}
