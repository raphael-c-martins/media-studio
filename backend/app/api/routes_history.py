import asyncio
import os
import subprocess
import logging
from typing import List, Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query

from app.database import get_db_connection
from app.models import DownloadItemResponse

logger = logging.getLogger("media_downloader.api.history")
router = APIRouter(prefix="/api/history", tags=["History"])

@router.get("", response_model=List[DownloadItemResponse])
async def get_history(
    search: Optional[str] = Query(None, description="Termo para filtrar título ou autor"),
    platform: Optional[str] = Query(None, description="Filtrar por plataforma"),
    status: Optional[str] = Query(None, description="Filtrar por status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """Consulta o histórico de downloads com filtros parametrizados e seguros."""
    query = "SELECT * FROM downloads WHERE 1=1"
    params = []

    if search:
        query += " AND (title LIKE ? OR author LIKE ? OR url LIKE ?)"
        term = f"%{search}%"
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
        rows = await cursor.fetchall()
        return [DownloadItemResponse(**dict(r)) for r in rows]

@router.delete("/{download_id}", response_model=dict)
async def delete_history_item(download_id: str, delete_file: bool = Query(False)):
    """Remove um registro do histórico e opcionalmente o arquivo local de forma assíncrona."""
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT file_path FROM downloads WHERE id = ?", (download_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Registro não encontrado.")

        file_path = row["file_path"]
        if delete_file and file_path and os.path.exists(file_path):
            try:
                await asyncio.to_thread(os.remove, file_path)
            except Exception as e:
                logger.warning(f"Não foi possível remover o arquivo físico ({file_path}): {e}")

        await db.execute("DELETE FROM downloads WHERE id = ?", (download_id,))
        await db.commit()

    return {"success": True, "message": "Registro removido com sucesso."}

@router.post("/{download_id}/open-folder", response_model=dict)
async def open_file_folder(download_id: str):
    """Abre a pasta do arquivo no Windows Explorer de forma assíncrona."""
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT file_path FROM downloads WHERE id = ?", (download_id,))
        row = await cursor.fetchone()
        if not row or not row["file_path"]:
            raise HTTPException(status_code=404, detail="Caminho do arquivo não localizado.")

        file_path = Path(row["file_path"]).resolve()
        if file_path.exists():
            def _open_sel():
                try:
                    subprocess.Popen(f'explorer /select,"{str(file_path)}"')
                except Exception:
                    os.startfile(str(file_path.parent))
            await asyncio.to_thread(_open_sel)
            return {"success": True, "message": "Pasta aberta com o arquivo selecionado."}
        elif file_path.parent.exists():
            await asyncio.to_thread(os.startfile, str(file_path.parent))
            return {"success": True, "message": "Pasta aberta."}
        else:
            raise HTTPException(status_code=404, detail="Arquivo ou diretório não existe mais no disco.")

@router.post("/{download_id}/open-file", response_model=dict)
async def open_file_media(download_id: str):
    """Abre o arquivo com o reprodutor padrão do sistema de forma assíncrona."""
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT file_path FROM downloads WHERE id = ?", (download_id,))
        row = await cursor.fetchone()
        if not row or not row["file_path"]:
            raise HTTPException(status_code=404, detail="Arquivo não localizado.")

        file_path = Path(row["file_path"]).resolve()
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Arquivo não encontrado no disco.")

        await asyncio.to_thread(os.startfile, str(file_path))
        return {"success": True, "message": "Arquivo aberto no player padrão."}

from fastapi.responses import FileResponse
from app.config import DOWNLOADS_DIR, BASE_DIR

@router.get("/{download_id}/file")
async def download_file_to_browser(download_id: str):
    """Envia o arquivo baixado diretamente para o navegador do usuário (FileResponse)."""
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT file_path, title FROM downloads WHERE id = ?", (download_id,))
        row = await cursor.fetchone()
        if not row or not row["file_path"]:
            raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

        file_path = Path(row["file_path"]).resolve()
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Arquivo físico não existe no disco.")

        return FileResponse(
            path=str(file_path),
            filename=file_path.name,
            media_type="application/octet-stream"
        )

@router.post("/open-folder-global", response_model=dict)
async def open_global_downloads_folder():
    """Abre a pasta de downloads do MediaDownloader no Windows Explorer de forma nativa e infalível."""
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = 'download_folder'")
        row = await cursor.fetchone()
        raw_val = row["value"] if row and row["value"] else "downloads"

        target_dir = Path(raw_val)
        if not target_dir.is_absolute():
            target_dir = (BASE_DIR / target_dir).resolve()
        else:
            target_dir = target_dir.resolve()

        target_dir.mkdir(parents=True, exist_ok=True)

        def _open_native():
            try:
                os.startfile(str(target_dir))
            except Exception:
                subprocess.Popen(f'explorer "{str(target_dir)}"')

        await asyncio.to_thread(_open_native)
        return {"success": True, "message": f"Pasta {target_dir} aberta com sucesso."}


