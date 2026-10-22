// Atalhos de teclado do extrator. Só agem com a aba Frames aberta e fora de campos de texto.

const TYPING_TAGS = new Set(['INPUT', 'SELECT', 'TEXTAREA']);

export function initShortcuts(actions, isActive) {
  window.addEventListener('keydown', (event) => {
    if (!isActive() || event.ctrlKey || event.metaKey) return;
    if (TYPING_TAGS.has(event.target.tagName) && event.target.type !== 'range') return;

    const key = event.key.toLowerCase();
    const handlers = {
      ' ': actions.togglePlay,
      k: actions.togglePlay,
      c: actions.capture,
      z: actions.toggleLoupe,
      i: actions.markStart,
      o: actions.markEnd,
      b: actions.burst,
      '?': actions.showHelp,
    };

    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      const direction = event.key === 'ArrowLeft' ? -1 : 1;
      event.preventDefault();
      if (event.shiftKey) actions.step(direction * 1);
      else if (event.altKey) actions.step(direction * 0.1);
      else actions.stepFrames(direction);
      return;
    }

    const handler = handlers[event.key === ' ' ? ' ' : key];
    if (handler && !event.altKey) {
      event.preventDefault();
      handler();
    }
  });
}
