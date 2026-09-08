import logging
import re
from typing import Optional
from urllib.parse import quote
import httpx
from fastapi import APIRouter, HTTPException, Response
from app.models import UrlInspectRequest, MediaInfoResponse
from app.services.downloader import extract_media_info

logger = logging.getLogger("media_downloader.api.info")
router = APIRouter(prefix="/api/info", tags=["Info"])

@router.post("/inspect", response_model=MediaInfoResponse)
async def inspect_url(payload: UrlInspectRequest):
    """Inspeciona uma URL e retorna metadados completos e resoluções disponíveis."""
    try:
        info = await extract_media_info(payload.url)
        return info
    except Exception as e:
        logger.error(f"Erro ao inspecionar URL ({payload.url}): {e}")
        raise HTTPException(status_code=400, detail=f"Falha ao obter dados da mídia: {str(e)}")

import unicodedata

@router.head("/download-thumbnail")
@router.head("/download-thumbnail/{filename}")
@router.get("/download-thumbnail")
@router.get("/download-thumbnail/{filename}")
async def download_thumbnail(url: str, title: Optional[str] = None, filename: Optional[str] = None):
    """Faz proxy seguro do download da thumbnail com cabeçalho de download attachment."""
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="URL de miniatura inválida.")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Não foi possível obter a miniatura remota.")

            content_type = resp.headers.get("content-type", "image/jpeg")
            ext = "jpg"
            if "webp" in content_type or ".webp" in url.lower():
                ext = "webp"
            elif "png" in content_type or ".png" in url.lower():
                ext = "png"
            elif "gif" in content_type or ".gif" in url.lower():
                ext = "gif"

            safe_title = re.sub(r'[\r\n\t\\/*?:"<>|;]', "", title or "thumbnail").strip() or "thumbnail"
            full_filename = f"{safe_title} [Thumbnail].{ext}"

            # Transliterar para ASCII seguro sem caracteres proibidos do Windows
            nfkd = unicodedata.normalize('NFKD', full_filename)
            ascii_str = nfkd.encode('ascii', 'ignore').decode('ascii')
            safe_ascii = re.sub(r'[\r\n\t\\/*?:"<>|;]', '', ascii_str).strip() or f"thumbnail.{ext}"
            if not safe_ascii.lower().endswith(f".{ext}".lower()):
                safe_ascii = f"{safe_ascii}.{ext}"

            safe_utf8 = re.sub(r'[\r\n\t\\/*?:"<>|;]', '', full_filename).strip() or safe_ascii
            if not safe_utf8.lower().endswith(f".{ext}".lower()):
                safe_utf8 = f"{safe_utf8}.{ext}"

            encoded_utf8 = quote(safe_utf8, safe='')

            return Response(
                content=resp.content,
                media_type=content_type,
                headers={
                    "Content-Disposition": f'attachment; filename="{safe_ascii}"; filename*=UTF-8\'\'{encoded_utf8}',
                    "Cache-Control": "public, max-age=86400"
                }
            )
    except Exception as e:
        logger.error(f"Erro ao baixar thumbnail ({url}): {e}")
        raise HTTPException(status_code=500, detail="Falha ao transferir miniatura.")
