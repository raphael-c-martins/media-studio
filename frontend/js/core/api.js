// Cliente HTTP da API local. Toda ação que altera algo leva o cabeçalho exigido pelo servidor.

const SAFE_METHODS = new Set(['GET', 'HEAD']);

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function readError(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === 'string') return data.detail;
  } catch (_) { /* resposta sem JSON */ }
  return `Erro ${response.status} ao falar com o servidor.`;
}

export async function request(path, { method = 'GET', json, body, timeout = 0, raw = false } = {}) {
  const headers = {};
  if (!SAFE_METHODS.has(method)) headers['X-Media-Studio'] = '1';
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(json);
  }

  const controller = new AbortController();
  const timer = timeout ? setTimeout(() => controller.abort(), timeout) : null;
  let response;
  try {
    response = await fetch(path, { method, headers, body, signal: controller.signal });
  } catch (err) {
    if (err.name === 'AbortError') throw new ApiError('O servidor demorou demais para responder.', 0);
    throw new ApiError('Não foi possível falar com o servidor. Ele está ligado?', 0);
  } finally {
    if (timer) clearTimeout(timer);
  }

  if (!response.ok) throw new ApiError(await readError(response), response.status);
  if (raw) return response;
  const type = response.headers.get('content-type') || '';
  return type.includes('application/json') ? response.json() : response.text();
}

export const api = {
  get: (path, options) => request(path, { ...options, method: 'GET' }),
  post: (path, json, options) => request(path, { ...options, method: 'POST', json }),
  put: (path, json, options) => request(path, { ...options, method: 'PUT', json }),
  del: (path, options) => request(path, { ...options, method: 'DELETE' }),
};

export function triggerDownload(url, filename) {
  const link = document.createElement('a');
  link.href = url;
  if (filename) link.download = filename;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  setTimeout(() => link.remove(), 1000);
}
