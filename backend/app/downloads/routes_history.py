import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.database import get_db_connection, get_setting
from app.downloads.models import DownloadItemResponse
from app.downloads.routes_info import content_disposition
from app.downloads.storage import StorageError, is_allowed_media_file, resolve_download_folder

logger = logging.getLogger("media_studio.api.history")
router = APIRouter(prefix="/api/history", tags=["History"])


async def _file_path_of(download_id: str) -> str:
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT file_path FROM downloads WHERE id = ?", (download_id,))
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Registro não encontrado.")
    return row["file_path"] or ""


async def _media_file(download_id: str) -> Path:
    file_path = await _file_path_of(download_id)
    if not is_allowed_media_file(file_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no disco.")
    return Path(file_path).resolve()


@router.get("", response_model=List[DownloadItemResponse])
async def get_history(
    search: Optional[str] = Query(None, max_length=200),
    platform: Optional[str] = Query(None, max_length=40),
    status: Optional[str] = Query(None, max_length=20),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    query = "SELECT * FROM downloads WHERE 1=1"
    params: list = []
    if search:
        term = f"%{search}%"
        query += " AND (title LIKE ? OR author LIKE ? OR url LIKE ?)"
        params.extend([term, term, term])
    if platform and platform.lower() != "all":
        query += " AND platform = ?"
        params.append(platform)
    if status and status.lower() != "all":
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    async with get_db_connection() as db:
        cursor = await db.execute(query, tuple(params))
        return [DownloadItemResponse.from_row(row) for row in await cursor.fetchall()]


@router.delete("/{download_id}", response_model=dict)
async def delete_history_item(download_id: str, delete_file: bool = Query(False)):
    file_path = await _file_path_of(download_id)
    if delete_file and is_allowed_media_file(file_path):
        try:
            await asyncio.to_thread(os.remove, file_path)
            logger.info("Arquivo apagado a pedido do usuário: %s", file_path)
        except OSError as exc:
            logger.warning("Não foi possível apagar %s: %s", file_path, exc)
    async with get_db_connection() as db:
        await db.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
        await db.commit()
    return {"success": True}


@router.post("/{download_id}/open-folder", response_model=dict)
async def open_file_folder(download_id: str):
    path = await _media_file(download_id)
    await asyncio.to_thread(subprocess.Popen, ["explorer", f"/select,{path}"])
    return {"success": True}


@router.post("/{download_id}/open-file", response_model=dict)
async def open_file_media(download_id: str):
    path = await _media_file(download_id)
    await asyncio.to_thread(os.startfile, str(path))
    return {"success": True}


@router.get("/{download_id}/file")
async def download_file_to_browser(download_id: str):
    path = await _media_file(download_id)
    return FileResponse(
        path=str(path),
        media_type="application/octet-stream",
        headers={"Content-Disposition": content_disposition(path.name)},
    )


@router.post("/open-downloads-folder", response_model=dict)
async def open_downloads_folder():
    try:
        folder = resolve_download_folder(await get_setting("download_folder"))
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    folder.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(os.startfile, str(folder))
    return {"success": True}
