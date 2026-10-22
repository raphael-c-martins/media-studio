// Galeria de quadros capturados: visualização, download individual e .zip.

import { triggerDownload } from '../core/api.js';
import { $, el, show } from '../core/dom.js';
import { timeForFilename } from '../core/format.js';
import { toast } from '../core/toast.js';
import { createZip } from '../core/zip.js';

const EXTENSIONS = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp' };

export class Gallery {
  constructor() {
    this.frames = [];
    this.current = null;
    $('#btn-gallery-zip').addEventListener('click', () => this.downloadAll());
    $('#btn-gallery-clear').addEventListener('click', () => {
      if (this.frames.length && window.confirm(`Remover os ${this.frames.length} quadros da galeria?`)) this.clear();
    });
    $('#frame-modal-download').addEventListener('click', () => this.current && this.download(this.current));
  }

  /** @param {{blob: Blob, time: number, timeLabel: string, width: number, height: number}} frame */
  add(frame) {
    const ext = EXTENSIONS[frame.blob.type] || 'png';
    const item = {
      ...frame,
      id: crypto.randomUUID(),
      ext,
      url: URL.createObjectURL(frame.blob),
      filename: `frame_${timeForFilename(frame.time)}.${ext}`,
    };
    this.frames.unshift(item);
    this.render();
    return item;
  }

  remove(id) {
    const item = this.frames.find((f) => f.id === id);
    if (item) URL.revokeObjectURL(item.url);
    this.frames = this.frames.filter((f) => f.id !== id);
    this.render();
  }

  clear() {
    this.frames.forEach((f) => URL.revokeObjectURL(f.url));
    this.frames = [];
    this.render();
  }

  open(item) {
    this.current = item;
    $('#frame-modal-img').src = item.url;
    $('#frame-modal-title').textContent = item.filename;
    $('#frame-modal-info').textContent = `${item.width} x ${item.height} px · ${item.timeLabel}`;
    show($('#frame-modal'), true);
  }

  download(item) {
    triggerDownload(item.url, item.filename);
  }

  async downloadAll() {
    if (!this.frames.length) return;
    if (this.frames.length === 1) {
      this.download(this.frames[0]);
      return;
    }
    const ordered = [...this.frames].sort((a, b) => a.time - b.time);
    const files = ordered.map((frame, index) => ({
      name: `frame_${String(index + 1).padStart(2, '0')}_${timeForFilename(frame.time)}.${frame.ext}`,
      data: frame.blob,
    }));
    try {
      const zip = await createZip(files);
      const url = URL.createObjectURL(zip);
      triggerDownload(url, `frames_${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.zip`);
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      toast.success(`${files.length} quadros salvos em .zip.`);
    } catch (err) {
      toast.error(`Não foi possível gerar o .zip: ${err.message}`);
    }
  }

  render() {
    const count = this.frames.length;
    $('#gallery-count').textContent = count;
    show($('#gallery-empty'), count === 0);
    show($('#gallery-grid'), count > 0);
    $('#btn-gallery-zip').disabled = count === 0;
    $('#btn-gallery-clear').disabled = count === 0;

    $('#gallery-grid').replaceChildren(...this.frames.map((item) => el('div', { class: 'thumb' }, [
      el('img', { src: item.url, alt: `Quadro em ${item.timeLabel}`, loading: 'lazy', onclick: () => this.open(item) }),
      el('div', { class: 'thumb-foot mono' }, [
        el('span', { text: item.timeLabel }),
        el('span', { class: 'muted', text: `${item.width}x${item.height} ${item.ext.toUpperCase()}` }),
      ]),
      el('div', { class: 'thumb-actions' }, [
        el('button', { type: 'button', class: 'btn btn-secondary btn-sm', text: 'Baixar', onclick: () => this.download(item) }),
        el('button', { type: 'button', class: 'btn btn-danger btn-sm', text: 'Remover', onclick: () => this.remove(item.id) }),
      ]),
    ])));
  }
}
