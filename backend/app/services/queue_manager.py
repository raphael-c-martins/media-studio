import asyncio
import glob
import json
import logging
import os
import re
import uuid
import httpx
import yt_dlp
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Set, Optional

from app.config import BASE_DIR, DOWNLOADS_DIR, MAX_CONCURRENT_DOWNLOADS
from app.database import get_db_connection
from app.models import DownloadRequest, DownloadItemResponse
from app.services.downloader import (
    extract_media_info,
    build_download_options,
    detect_platform,
)

logger = logging.getLogger("media_downloader.queue")

class QueueManager:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.cancel_events: Dict[str, asyncio.Event] = {}
        self.listeners: Set[asyncio.Queue] = set()
        self.workers: List[asyncio.Task] = []
        self._running = False

    async def start(self):
        """Inicia os workers da fila em segundo plano."""
        if self._running:
            return
        self._running = True
        for i in range(MAX_CONCURRENT_DOWNLOADS):
            task = asyncio.create_task(self._worker_loop(i))
            self.workers.append(task)
        logger.info(f"QueueManager iniciado com {MAX_CONCURRENT_DOWNLOADS} workers.")

    async def stop(self):
        """Para os workers de forma graciosa."""
        self._running = False
        for task in self.workers:
            task.cancel()
        for cancel_event in self.cancel_events.values():
            cancel_event.set()
        logger.info("QueueManager finalizado.")

    async def add_listener(self) -> asyncio.Queue:
        """Adiciona um canal de escuta para Server-Sent Events (SSE)."""
        q = asyncio.Queue()
        self.listeners.add(q)
        return q

    def remove_listener(self, q: asyncio.Queue):
        """Remove um canal de escuta SSE."""
        self.listeners.discard(q)

    async def broadcast(self, event_type: str, data: Dict[str, Any]):
        """Transmite uma mensagem para todos os clientes conectados via SSE."""
        payload = json.dumps({"event": event_type, "data": data})
        dead_listeners = set()
        for q in self.listeners:
            try:
                q.put_nowait(payload)
            except Exception:
                dead_listeners.add(q)
        for dead in dead_listeners:
            self.listeners.discard(dead)

    async def enqueue_download(self, req: DownloadRequest) -> str:
        """Insere um novo download na fila e persiste o registro inicial."""
        download_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        platform = detect_platform(req.url)

        # Obter metadados preliminares
        title = req.custom_title or "Carregando metadados..."
        author = platform
        thumbnail = ""
        duration = 0

        try:
            info = await extract_media_info(req.url)
            title = req.custom_title or info.title
            author = info.author or platform
            thumbnail = info.thumbnail or ""
            duration = info.duration or 0
        except Exception as e:
            logger.warning(f"Não foi possível obter metadados iniciais antes do download: {e}")

        # Salvar no SQLite
        async with get_db_connection() as db:
            await db.execute("""
                INSERT INTO downloads (
                    id, url, title, author, platform, format_id, media_type,
                    file_path, file_size, duration, thumbnail, status, progress,
                    time_range_start, time_range_end, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                download_id, req.url, title, author, platform,
                req.format_id or req.quality_preset, req.media_type,
                "", 0, duration, thumbnail, "queued", 0.0,
                req.time_range_start, req.time_range_end, created_at
            ))
            await db.commit()

        # Adicionar à fila em memória
        cancel_event = asyncio.Event()
        self.cancel_events[download_id] = cancel_event
        await self.queue.put((download_id, req))

        await self.broadcast("download_queued", {
            "id": download_id,
            "url": req.url,
            "title": title,
            "author": author,
            "platform": platform,
            "status": "queued",
            "progress": 0.0
        })

        return download_id

    async def cancel_download(self, download_id: str) -> bool:
        """Cancela um download em andamento ou pendente."""
        if download_id in self.cancel_events:
            self.cancel_events[download_id].set()

        if download_id in self.active_tasks:
            self.active_tasks[download_id].cancel()

        async with get_db_connection() as db:
            await db.execute("""
                UPDATE downloads
                SET status = 'cancelled', completed_at = ?
                WHERE id = ?
            """, (datetime.utcnow().isoformat(), download_id))
            await db.commit()

        await self.broadcast("download_cancelled", {"id": download_id, "status": "cancelled"})
        return True

    async def _worker_loop(self, worker_id: int):
        """Loop contínuo de cada worker para consumir downloads da fila."""
        while self._running:
            try:
                download_id, req = await self.queue.get()
                cancel_event = self.cancel_events.get(download_id, asyncio.Event())

                if cancel_event.is_set():
                    self.queue.task_done()
                    continue

                # Criar uma task filha para o processamento, preservando a worker_loop
                process_task = asyncio.create_task(
                    self._process_download(download_id, req, cancel_event)
                )
                self.active_tasks[download_id] = process_task

                try:
                    await process_task
                except asyncio.CancelledError:
                    logger.info(f"Download {download_id} cancelado.")
                except Exception as ex:
                    logger.error(f"Erro no processamento do download {download_id}: {ex}", exc_info=True)
                    await self._handle_error(download_id, str(ex))
                finally:
                    self.active_tasks.pop(download_id, None)
                    self.cancel_events.pop(download_id, None)
                    self.queue.task_done()

            except asyncio.CancelledError:
                if not self._running:
                    break
                logger.warning(f"Worker {worker_id} recebeu CancelledError, mantendo loop ativo...")
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Erro no worker {worker_id}: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _process_download(self, download_id: str, req: DownloadRequest, cancel_event: asyncio.Event):
        """Executa o download de um item com monitoramento de progresso."""
        # Atualizar status para downloading
        async with get_db_connection() as db:
            # Buscar pasta de destino das configurações
            cursor = await db.execute("SELECT value FROM settings WHERE key = 'download_folder'")
            row = await cursor.fetchone()
            raw_folder = row["value"] if row and row["value"] else DOWNLOADS_DIR
            target_folder = Path(raw_folder)
            if not target_folder.is_absolute():
                target_folder = (BASE_DIR / target_folder).resolve()
            else:
                target_folder = target_folder.resolve()
            target_folder.mkdir(parents=True, exist_ok=True)

            await db.execute("UPDATE downloads SET status = 'downloading' WHERE id = ?", (download_id,))
            await db.commit()

        await self.broadcast("download_started", {"id": download_id, "status": "downloading"})

        last_percent = 0.0
        downloaded_file_path = ""
        final_filesize = 0
        # Caminho capturado pelo postprocessor_hook (arquivo FINAL, pós-merge)
        postprocessed_filepath = ""

        # Capturar referência do event loop do asyncio ANTES de entrar no thread pool
        # para evitar 'There is no current event loop in thread' dentro do progress_hook
        main_loop = asyncio.get_running_loop()

        def progress_hook(d: Dict[str, Any]):
            nonlocal last_percent, final_filesize
            if cancel_event.is_set():
                raise Exception("Download cancelado pelo usuário.")

            if d["status"] == "downloading":
                total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes", 0)
                speed_bytes = d.get("speed") or 0
                eta_sec = d.get("eta") or 0

                percent = round((downloaded / total_bytes * 100), 1) if total_bytes > 0 else 0.0
                speed_str = f"{speed_bytes / (1024*1024):.2f} MB/s" if speed_bytes > 1024*1024 else f"{speed_bytes / 1024:.1f} KB/s"
                eta_str = f"{int(eta_sec)}s" if eta_sec else ""

                if percent != last_percent and (percent - last_percent >= 0.5 or percent == 100):
                    last_percent = percent
                    asyncio.run_coroutine_threadsafe(
                        self._update_progress(download_id, percent, speed_str, eta_str, total_bytes),
                        main_loop
                    )

            elif d["status"] == "finished":
                final_filesize = d.get("total_bytes", 0)

        def postprocessor_hook(d: Dict[str, Any]):
            """Captura o caminho FINAL após pós-processamento (merge, conversão etc)."""
            nonlocal postprocessed_filepath
            if d.get("status") == "finished":
                fp = d.get("info_dict", {}).get("filepath", "")
                if fp and Path(fp).exists():
                    postprocessed_filepath = str(Path(fp).resolve())

        # 1. Se direct_media_url for fornecido (URL direta de CDN já extraída)
        if req.direct_media_url:
            import httpx
            ext = "mp4" if req.media_type == "video" else "jpg"
            if ".mp4" in req.direct_media_url.lower():
                ext = "mp4"
            elif ".jpg" in req.direct_media_url.lower() or ".jpeg" in req.direct_media_url.lower():
                ext = "jpg"
            elif ".webp" in req.direct_media_url.lower():
                ext = "webp"

            safe_title = re.sub(r'[\\/*?:"<>|]', "", req.custom_title or f"download_{download_id[:8]}").strip()
            file_name = f"{safe_title}.{ext}"
            file_path = target_folder / file_name

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            }
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, headers=headers) as client:
                resp = await client.get(req.direct_media_url)
                if resp.status_code != 200:
                    raise ValueError(f"Falha ao transferir mídia direta (HTTP {resp.status_code}).")
                file_path.write_bytes(resp.content)

            downloaded_file_path = str(file_path)
            final_filesize = file_path.stat().st_size
            title = req.custom_title or file_path.stem

        # 2. Executar download direto e especializado do Instagram para carrosséis/posts
        elif "instagram.com" in req.url.lower() and ("/p/" in req.url.lower() or "/reel/" in req.url.lower() or "/tv/" in req.url.lower()):
            from app.services.instagram_helper import download_instagram_media_direct
            async def _insta_progress(percent, msg, file_p):
                await self._update_progress(download_id, percent, "Download Direto", "", 0)
                
            downloaded_file_path = await download_instagram_media_direct(
                req.url, target_folder, req.custom_title, _insta_progress
            )
            final_filesize = Path(downloaded_file_path).stat().st_size if Path(downloaded_file_path).exists() else 0
            title = req.custom_title or Path(downloaded_file_path).stem
        else:
            # Montar opções e executar no thread pool via yt-dlp com fallback para Instagram
            def _run_ytdl():
                opts = build_download_options(req, target_folder, progress_hook, cancel_event)
                # Registrar postprocessor_hook para capturar o caminho final (pós-merge)
                opts["postprocessor_hooks"] = [postprocessor_hook]
                with yt_dlp.YoutubeDL(opts) as ydl:
                    # Verificar se é live stream em andamento para não travar a fila
                    pre_info = ydl.extract_info(req.url, download=False)
                    if pre_info and pre_info.get("is_live"):
                        raise ValueError("Transmissões ao vivo (lives) em andamento não podem ser baixadas enquanto o streaming estiver ativo. Aguarde o encerramento da transmissão.")
                    info_dict = ydl.extract_info(req.url, download=True)
                    return info_dict

            try:
                info = await asyncio.to_thread(_run_ytdl)
                title = info.get("title") if info else None

                # Prioridade para capturar o caminho final correto:
                # 1. postprocessor_hook (mais confiável - caminho pós-merge/conversão)
                if postprocessed_filepath and Path(postprocessed_filepath).exists():
                    downloaded_file_path = postprocessed_filepath
                # 2. requested_downloads do info_dict (yt-dlp moderno)
                elif info and info.get("requested_downloads"):
                    rd = info["requested_downloads"][0]
                    fp = rd.get("filepath") or rd.get("filename", "")
                    if fp and Path(fp).exists():
                        downloaded_file_path = str(Path(fp).resolve())
                # 3. Fallback: computar o nome final a partir do outtmpl
                if not downloaded_file_path or not Path(downloaded_file_path).exists():
                    import glob
                    video_id = info.get("id", "") if info else ""
                    safe_title = (title or "").replace("/", "_").replace("\\", "_")
                    # Buscar pelo padrão do outtmpl: "titulo [id].ext"
                    patterns = [
                        str(target_folder / f"*{video_id}*.mp4"),
                        str(target_folder / f"*{video_id}*.webm"),
                        str(target_folder / f"*{video_id}*.mkv"),
                        str(target_folder / f"*{video_id}*.mp3"),
                        str(target_folder / f"*{video_id}*.m4a"),
                    ]
                    for pattern in patterns:
                        candidates = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
                        # Filtrar fragmentos temporários (ex: .f251-1.webm, .f140.m4a)
                        valid = [c for c in candidates if not re.search(r'\.f\d+[-.]', Path(c).name)]
                        if valid:
                            downloaded_file_path = str(Path(valid[0]).resolve())
                            break

            except Exception as ydl_err:
                if "instagram.com" in req.url.lower() and "no video formats" in str(ydl_err).lower():
                    from app.services.instagram_helper import download_instagram_media_direct
                    downloaded_file_path = await download_instagram_media_direct(
                        req.url, target_folder, req.custom_title
                    )
                    final_filesize = Path(downloaded_file_path).stat().st_size if Path(downloaded_file_path).exists() else 0
                    title = req.custom_title or Path(downloaded_file_path).stem
                else:
                    raise ydl_err

        # Garantir que file_path é absoluto e computar tamanho final
        if downloaded_file_path:
            abs_path = Path(downloaded_file_path).resolve()
            if abs_path.exists():
                downloaded_file_path = str(abs_path)
                final_filesize = abs_path.stat().st_size
            else:
                logger.warning(f"Arquivo final não encontrado no disco: {downloaded_file_path}")

        completed_at = datetime.utcnow().isoformat()

        async with get_db_connection() as db:
            await db.execute("""
                UPDATE downloads
                SET status = 'completed', progress = 100.0, speed = '', eta = '',
                    file_path = ?, file_size = ?, title = COALESCE(?, title), completed_at = ?
                WHERE id = ?
            """, (downloaded_file_path, final_filesize, title, completed_at, download_id))
            await db.commit()

        await self.broadcast("download_completed", {
            "id": download_id,
            "status": "completed",
            "progress": 100.0,
            "file_path": downloaded_file_path,
            "title": title
        })

    async def _update_progress(self, download_id: str, progress: float, speed: str, eta: str, file_size: int):
        """Atualiza o progresso em tempo real e notifica via broadcast."""
        async with get_db_connection() as db:
            await db.execute("""
                UPDATE downloads
                SET progress = ?, speed = ?, eta = ?, file_size = CASE WHEN ? > 0 THEN ? ELSE file_size END
                WHERE id = ?
            """, (progress, speed, eta, file_size, file_size, download_id))
            await db.commit()

        await self.broadcast("download_progress", {
            "id": download_id,
            "progress": progress,
            "speed": speed,
            "eta": eta,
            "file_size": file_size
        })

    async def _handle_error(self, download_id: str, error_msg: str):
        """Trata e persiste falhas de download."""
        async with get_db_connection() as db:
            await db.execute("""
                UPDATE downloads
                SET status = 'error', error_message = ?, completed_at = ?
                WHERE id = ?
            """, (error_msg, datetime.utcnow().isoformat(), download_id))
            await db.commit()

        await self.broadcast("download_error", {
            "id": download_id,
            "status": "error",
            "error_message": error_msg
        })

# Instância global do gerenciador de fila
queue_manager = QueueManager()
