import logging
import re
import unicodedata
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from app import config
from app.downloads.downloader import extract_media_info
from app.downloads.models import MediaInfoResponse, UrlInspectRequest
from app.net_guard import DownloadTooLargeError, UnsafeUrlError, assert_public_url, fetch_public_bytes

logger = logging.getLogger("media_studio.api.info")
router = APIRouter(prefix="/api/info", tags=["Info"])

IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


def content_disposition(filename: str) -> str:
    """Cabeçalho de download com nome ASCII e versão UTF-8 (RFC 5987)."""
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r'[\r\n\t\\/*?:"<>|;]', "", ascii_name).strip() or "arquivo"
    utf8_name = re.sub(r'[\r\n\t\\/*?:"<>|;]', "", filename).strip() or ascii_name
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(utf8_name, safe='')}"


@router.post("/inspect", response_model=MediaInfoResponse)
async def inspect_url(payload: UrlInspectRequest):
    try:
        await assert_public_url(payload.url)
        return await extract_media_info(payload.url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Falha ao inspecionar %s: %s", payload.url, exc)
        raise HTTPException(status_code=400, detail=f"Falha ao obter dados da mídia: {exc}") from exc


@router.get("/thumbnail")
async def download_thumbnail(url: str, title: Optional[str] = None):
    """Baixa a capa de uma mídia e entrega como arquivo. Só aceita imagens de sites públicos."""
    try:
        content, content_type = await fetch_public_bytes(url, config.MAX_THUMBNAIL_BYTES, timeout=20.0)
    except (UnsafeUrlError, DownloadTooLargeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Falha ao baixar capa: %s", exc)
        raise HTTPException(status_code=502, detail="Não foi possível baixar a capa.") from exc

    mime = content_type.split(";")[0].strip().lower()
    if mime not in IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="O endereço não devolveu uma imagem.")
    base = re.sub(r'[\r\n\t\\/*?:"<>|;]', "", title or "capa").strip()[:120] or "capa"
    return Response(
        content=content,
        media_type=mime,
        headers={"Content-Disposition": content_disposition(f"{base} - capa.{IMAGE_TYPES[mime]}")},
    )
