import asyncio
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.database import get_db_connection
from app.downloads.models import DownloadItemResponse, DownloadRequest
from app.downloads.queue_manager import queue_manager
from app.net_guard import UnsafeUrlError, assert_public_url

logger = logging.getLogger("media_studio.api.download")
router = APIRouter(prefix="/api/downloads", tags=["Downloads"])


@router.post("", response_model=dict)
async def create_download(payload: DownloadRequest):
    try:
        await assert_public_url(payload.url)
        if payload.direct_media_url:
            await assert_public_url(payload.direct_media_url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    download_id = await queue_manager.enqueue_download(payload)
    return {"success": True, "download_id": download_id}


@router.get("/queue", response_model=List[DownloadItemResponse])
async def list_active_queue():
    async with get_db_connection() as db:
        cursor = await db.execute(
            "SELECT * FROM downloads WHERE status IN ('queued', 'downloading') ORDER BY created_at ASC"
        )
        return [DownloadItemResponse.from_row(row) for row in await cursor.fetchall()]


@router.delete("/{download_id}", response_model=dict)
async def cancel_download(download_id: str):
    if not await queue_manager.cancel_download(download_id):
        raise HTTPException(status_code=404, detail="Download não encontrado ou já finalizado.")
    return {"success": True}


@router.get("/stream")
async def event_stream(request: Request):
    """Canal SSE com o progresso dos downloads em tempo real."""
    listener = await queue_manager.add_listener()

    async def events():
        try:
            yield 'data: {"event": "connected"}\n\n'
            while not await request.is_disconnected():
                try:
                    message = await asyncio.wait_for(listener.get(), timeout=15.0)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"event": "ping"}\n\n'
        except asyncio.CancelledError:
            pass
        finally:
            queue_manager.remove_listener(listener)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
