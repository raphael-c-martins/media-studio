import asyncio
import logging
from typing import List
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.database import get_db_connection
from app.models import DownloadRequest, DownloadItemResponse
from app.services.queue_manager import queue_manager

logger = logging.getLogger("media_downloader.api.download")
router = APIRouter(prefix="/api/downloads", tags=["Downloads"])

@router.post("", response_model=dict)
async def create_download(payload: DownloadRequest):
    """Enfileira um novo download."""
    try:
        download_id = await queue_manager.enqueue_download(payload)
        return {"success": True, "download_id": download_id, "message": "Download adicionado à fila com sucesso."}
    except Exception as e:
        logger.error(f"Erro ao enfileirar download: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/queue", response_model=List[DownloadItemResponse])
async def list_active_queue():
    """Retorna a lista de downloads atualmente em fila ou em execução."""
    async with get_db_connection() as db:
        cursor = await db.execute("""
            SELECT * FROM downloads
            WHERE status IN ('queued', 'downloading')
            ORDER BY created_at ASC
        """)
        rows = await cursor.fetchall()
        return [DownloadItemResponse(**dict(r)) for r in rows]

@router.delete("/{download_id}", response_model=dict)
async def cancel_download(download_id: str):
    """Cancela um download ativo ou pendente."""
    success = await queue_manager.cancel_download(download_id)
    if not success:
        raise HTTPException(status_code=404, detail="Download não encontrado ou já finalizado.")
    return {"success": True, "message": "Download cancelado com sucesso."}

@router.get("/stream")
async def event_stream(request: Request):
    """Canal Server-Sent Events (SSE) para transmissão de progresso em tempo real."""
    listener_queue = await queue_manager.add_listener()

    async def event_generator():
        try:
            # Mensagem inicial de conexão estabelecida
            yield "data: {\"event\": \"connected\", \"message\": \"Conexão SSE estabelecida\"}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # Aguarda nova mensagem com timeout para manter heartbeat
                    message = await asyncio.wait_for(listener_queue.get(), timeout=15.0)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    # Enviar ping/keep-alive para manter o canal aberto
                    yield "data: {\"event\": \"ping\"}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            queue_manager.remove_listener(listener_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
