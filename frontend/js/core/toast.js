// Avisos rápidos no canto da tela. O texto é sempre inserido como texto puro.

import { el } from './dom.js';

const DEFAULT_DURATION = { success: 3500, info: 3500, warning: 5000, error: 7000 };

function show(message, type = 'info', { duration, actions = [] } = {}) {
  const container = document.getElementById('toasts');
  if (!container) return;

  const toast = el('div', { class: `toast toast-${type}`, role: type === 'error' ? 'alert' : 'status' }, [
    el('span', { text: message }),
  ]);
  if (actions.length) {
    toast.append(el('div', { class: 'toast-actions' }, actions.map((action) =>
      el('button', {
        type: 'button', class: 'btn btn-secondary btn-sm', text: action.label,
        onclick: () => { action.onClick(); dismiss(); },
      }),
    )));
  }
  container.append(toast);

  function dismiss() {
    toast.classList.add('leaving');
    setTimeout(() => toast.remove(), 200);
  }
  setTimeout(dismiss, duration ?? DEFAULT_DURATION[type] ?? 4000);
}

export const toast = {
  success: (msg, opts) => show(msg, 'success', opts),
  info: (msg, opts) => show(msg, 'info', opts),
  warning: (msg, opts) => show(msg, 'warning', opts),
  error: (msg, opts) => show(msg, 'error', opts),
};
