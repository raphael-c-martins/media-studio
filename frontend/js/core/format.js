export function formatBytes(bytes) {
  if (!bytes) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** index;
  return `${value.toLocaleString('pt-BR', { maximumFractionDigits: index ? 1 : 0 })} ${units[index]}`;
}

export function formatDate(iso) {
  if (!iso) return '-';
  // O servidor grava em UTC sem fuso; o "Z" garante a conversão para o horário local.
  const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`);
  return `${date.toLocaleDateString('pt-BR')} ${date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`;
}

const pad = (value, size = 2) => String(value).padStart(size, '0');

export function formatTime(totalSeconds) {
  const seconds = Number.isFinite(totalSeconds) && totalSeconds > 0 ? totalSeconds : 0;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  const millis = Math.floor((seconds % 1) * 1000);
  return `${pad(hours)}:${pad(minutes)}:${pad(secs)}.${pad(millis, 3)}`;
}

export function formatShortTime(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60);
  const secs = Math.floor(totalSeconds % 60);
  const tenths = Math.floor((totalSeconds % 1) * 10);
  return `${pad(minutes)}:${pad(secs)}.${tenths}`;
}

/** Tempo curto para nome de arquivo: 03.9s, 01m20s, 1h02m05s. */
export function timeForFilename(totalSeconds) {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = Math.floor(totalSeconds % 60);
  const tenths = Math.floor((totalSeconds % 1) * 10);
  if (hours) return `${hours}h${pad(minutes)}m${pad(secs)}s`;
  if (minutes) return `${pad(minutes)}m${pad(secs)}s`;
  return `${pad(secs)}.${tenths}s`;
}

export function safeFilename(name, fallback = 'arquivo') {
  const clean = String(name || '')
    .normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, '').replace(/\s+/g, ' ').trim().slice(0, 120);
  return clean || fallback;
}
