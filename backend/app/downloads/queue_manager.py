import asyncio
import glob
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yt_dlp

from app import config
from app.database import get_db_connection, get_setting, utc_now
from app.downloads.downloader import build_download_options, detect_platform, extract_media_info, is_instagram_post
from app.downloads.models import DownloadRequest
from app.downloads.storage import StorageError, resolve_download_folder, safe_filename, unique_path
from app.net_guard import download_public_file

logger = logging.getLogger("media_studio.queue")

DIRECT_EXTENSIONS = (".mp4", ".webm", ".jpg", ".jpeg", ".png", ".webp")


class DownloadCancelled(Exception):
    pass


class QueueManager:
    def __init__(self):
        self.queue: "asyncio.Queue[Tuple[str, DownloadRequest]]" = asyncio.Queue()
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.cancel_events: Dict[str, asyncio.Event] = {}
        self.listeners: Set[asyncio.Queue] = set()
        self.workers: List[asyncio.Task] = []
        self._running = False

    async def start(self):
        if self._running:
            return
        self.queue = asyncio.Queue()
        self._running = True
        self.workers = [asyncio.create_task(self._worker_loop(i)) for i in range(config.MAX_CONCURRENT_DOWNLOADS)]
        logger.info("Fila iniciada com %s workers.", config.MAX_CONCURRENT_DOWNLOADS)

    async def stop(self):
        self._running = False
        for event in self.cancel_events.values():
            event.set()
        for task in self.workers:
            task.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers = []

    async def add_listener(self) -> asyncio.Queue:
        listener: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.listeners.add(listener)
        return listener

    def remove_listener(self, listener: asyncio.Queue):
        self.listeners.discard(listener)

    async def broadcast(self, event_type: str, data: Dict[str, Any]):
        payload = json.dumps({"event": event_type, "data": data}, ensure_ascii=False)
        for listener in list(self.listeners):
            try:
                listener.put_nowait(payload)
            except asyncio.QueueFull:
                self.listeners.discard(listener)

    async def enqueue_download(self, req: DownloadRequest) -> str:
        download_id = str(uuid.uuid4())
        platform = detect_platform(req.url)
        title, author, thumbnail, duration = req.custom_title or "Carregando informações...", platform, "", 0

        if not req.direct_media_url:
            try:
                info = await extract_media_info(req.url)
                title = req.custom_title or info.title
                author = info.author or platform
                thumbnail = info.thumbnail or ""
                duration = info.duration or 0
            except Exception as exc:
                logger.warning("Metadados iniciais indisponíveis: %s", exc)

        async with get_db_connection() as db:
            await db.execute(
                """
                INSERT INTO downloads (
                    id, url, title, author, platform, format_id, media_type, file_path, file_size,
                    duration, thumbnail, status, progress, time_range_start, time_range_end, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '', 0, ?, ?, 'queued', 0.0, ?, ?, ?)
                """,
                (download_id, req.url, title, author, platform, req.format_id or req.quality_preset,
                 req.media_type, duration, thumbnail, req.time_range_start, req.time_range_end, utc_now()),
            )
            await db.commit()

        self.cancel_events[download_id] = asyncio.Event()
        await self.queue.put((download_id, req))
        await self.broadcast("download_queued", {
            "id": download_id, "title": title, "author": author, "platform": platform,
            "status": "queued", "progress": 0.0,
        })
        return download_id

    async def cancel_download(self, download_id: str) -> bool:
        async with get_db_connection() as db:
            cursor = await db.execute(
                "UPDATE downloads SET status = 'cancelled', completed_at = ? "
                "WHERE id = ? AND status IN ('queued', 'downloading')",
                (utc_now(), download_id),
            )
            await db.commit()
            changed = cursor.rowcount or 0
        if not changed:
            return False
        if download_id in self.cancel_events:
            self.cancel_events[download_id].set()
        if download_id in self.active_tasks:
            self.active_tasks[download_id].cancel()
        await self.broadcast("download_cancelled", {"id": download_id, "status": "cancelled"})
        return True

    async def _worker_loop(self, worker_id: int):
        while self._running:
            try:
                download_id, req = await self.queue.get()
            except asyncio.CancelledError:
                break
            cancel_event = self.cancel_events.get(download_id)
            try:
                if cancel_event is None or cancel_event.is_set():
                    continue
                task = asyncio.create_task(self._process_download(download_id, req, cancel_event))
                self.active_tasks[download_id] = task
                try:
                    await task
                except asyncio.CancelledError:
                    if not self._running:
                        break
                    logger.info("Download %s cancelado.", download_id)
                except DownloadCancelled:
                    logger.info("Download %s cancelado durante a transferência.", download_id)
                except Exception as exc:
                    logger.error("Falha no download %s: %s", download_id, exc, exc_info=True)
                    await self._handle_error(download_id, str(exc))
            finally:
                self.active_tasks.pop(download_id, None)
                self.cancel_events.pop(download_id, None)
                self.queue.task_done()

    async def _target_folder(self) -> Path:
        raw = await get_setting("download_folder", str(config.DOWNLOADS_DIR))
        try:
            folder = resolve_download_folder(raw)
        except StorageError as exc:
            logger.warning("Pasta de download salva é inválida (%s). Usando a pasta padrão.", exc)
            folder = config.DOWNLOADS_DIR.resolve()
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    async def _process_download(self, download_id: str, req: DownloadRequest, cancel_event: asyncio.Event):
        target_folder = await self._target_folder()
        async with get_db_connection() as db:
            await db.execute("UPDATE downloads SET status = 'downloading' WHERE id = ?", (download_id,))
            await db.commit()
        await self.broadcast("download_started", {"id": download_id, "status": "downloading"})

        if req.direct_media_url:
            file_path, title = await self._download_direct(download_id, req, target_folder)
        elif is_instagram_post(req.url):
            file_path, title = await self._download_instagram(download_id, req, target_folder)
        else:
            file_path, title = await self._download_with_ytdlp(download_id, req, target_folder, cancel_event)

        file_size = 0
        if file_path and Path(file_path).exists():
            file_path = str(Path(file_path).resolve())
            file_size = Path(file_path).stat().st_size
        else:
            logger.warning("Arquivo final não encontrado: %s", file_path)

        async with get_db_connection() as db:
            await db.execute(
                """
                UPDATE downloads
                SET status = 'completed', progress = 100.0, speed = '', eta = '',
                    file_path = ?, file_size = ?, title = COALESCE(?, title), completed_at = ?
                WHERE id = ? AND status = 'downloading'
                """,
                (file_path or "", file_size, title, utc_now(), download_id),
            )
            await db.commit()

        await self.broadcast("download_completed", {
            "id": download_id, "status": "completed", "progress": 100.0, "title": title,
            "file_name": Path(file_path).name if file_path else None,
        })

    async def _download_direct(self, download_id: str, req: DownloadRequest, folder: Path):
        lower = req.direct_media_url.lower().split("?")[0]
        ext = next((e.lstrip(".") for e in DIRECT_EXTENSIONS if lower.endswith(e)), None)
        ext = ext or ("mp4" if req.media_type == "video" else "jpg")
        stem = safe_filename(req.custom_title or f"download_{download_id[:8]}")
        destination = unique_path(folder, stem, ext)
        await download_public_file(req.direct_media_url, destination, config.MAX_DIRECT_MEDIA_BYTES)
        return str(destination), req.custom_title or destination.stem

    async def _download_instagram(self, download_id: str, req: DownloadRequest, folder: Path):
        from app.downloads.instagram_helper import download_instagram_media_direct

        async def _progress(percent: float, _message: str):
            await self._update_progress(download_id, percent, "Transferência direta", "", 0)

        path = await download_instagram_media_direct(req.url, folder, req.custom_title, _progress)
        return path, req.custom_title or Path(path).stem

    async def _download_with_ytdlp(self, download_id: str, req: DownloadRequest, folder: Path,
                                   cancel_event: asyncio.Event):
        loop = asyncio.get_running_loop()
        last_percent = 0.0
        final_path = ""

        def progress_hook(d: Dict[str, Any]):
            nonlocal last_percent
            if cancel_event.is_set():
                raise DownloadCancelled("Download cancelado pelo usuário.")
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes", 0)
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0
            percent = round(done / total * 100, 1) if total else 0.0
            if percent - last_percent >= 0.5 or percent == 100:
                last_percent = percent
                speed_text = f"{speed / 1048576:.2f} MB/s" if speed > 1048576 else f"{speed / 1024:.1f} KB/s"
                asyncio.run_coroutine_threadsafe(
                    self._update_progress(download_id, percent, speed_text, f"{int(eta)}s" if eta else "", total),
                    loop,
                )

        def postprocessor_hook(d: Dict[str, Any]):
            nonlocal final_path
            if d.get("status") == "finished":
                path = (d.get("info_dict") or {}).get("filepath", "")
                if path and Path(path).exists():
                    final_path = str(Path(path).resolve())

        def _run():
            opts = build_download_options(req, folder, progress_hook)
            opts["postprocessor_hooks"] = [postprocessor_hook]
            with yt_dlp.YoutubeDL(opts) as ydl:
                preview = ydl.extract_info(req.url, download=False)
                if preview and preview.get("is_live"):
                    raise ValueError("Transmissões ao vivo em andamento não podem ser baixadas. Aguarde o fim da live.")
                return ydl.extract_info(req.url, download=True)

        try:
            info = await asyncio.to_thread(_run)
        except yt_dlp.utils.DownloadError as exc:
            if cancel_event.is_set():
                raise DownloadCancelled() from exc
            if "instagram.com" in req.url.lower() and "no video formats" in str(exc).lower():
                return await self._download_instagram(download_id, req, folder)
            raise

        title = info.get("title") if info else None
        if not final_path and info and info.get("requested_downloads"):
            requested = info["requested_downloads"][0]
            candidate = requested.get("filepath") or requested.get("filename", "")
            if candidate and Path(candidate).exists():
                final_path = str(Path(candidate).resolve())
        if not final_path and info:
            final_path = self._find_by_video_id(folder, str(info.get("id", "")))
        return final_path, title

    @staticmethod
    def _find_by_video_id(folder: Path, video_id: str) -> str:
        if not video_id:
            return ""
        pattern = str(folder / f"*{glob.escape(video_id)}*")
        candidates = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        valid = [c for c in candidates
                 if Path(c).suffix.lower() in (".mp4", ".webm", ".mkv", ".mp3", ".m4a", ".opus", ".wav", ".flac")
                 and not re.search(r"\.f\d+[-.]", Path(c).name)]
        return str(Path(valid[0]).resolve()) if valid else ""

    async def _update_progress(self, download_id: str, progress: float, speed: str, eta: str, file_size: int):
        async with get_db_connection() as db:
            await db.execute(
                """
                UPDATE downloads SET progress = ?, speed = ?, eta = ?,
                    file_size = CASE WHEN ? > 0 THEN ? ELSE file_size END
                WHERE id = ? AND status = 'downloading'
                """,
                (progress, speed, eta, file_size, file_size, download_id),
            )
            await db.commit()
        await self.broadcast("download_progress", {
            "id": download_id, "progress": progress, "speed": speed, "eta": eta, "file_size": file_size,
        })

    async def _handle_error(self, download_id: str, error_msg: str):
        message = error_msg[:500]
        async with get_db_connection() as db:
            await db.execute(
                "UPDATE downloads SET status = 'error', error_message = ?, completed_at = ? "
                "WHERE id = ? AND status != 'cancelled'",
                (message, utc_now(), download_id),
            )
            await db.commit()
        await self.broadcast("download_error", {"id": download_id, "status": "error", "error_message": message})


queue_manager = QueueManager()
