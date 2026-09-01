import logging
from fastapi import APIRouter, HTTPException
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
