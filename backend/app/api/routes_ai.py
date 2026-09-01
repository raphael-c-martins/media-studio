import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

from app.database import get_db_connection
from app.models import AISummaryRequest, AISummaryResponse
from app.services.ai_service import summarize_video

logger = logging.getLogger("media_downloader.api.ai")
router = APIRouter(prefix="/api/ai", tags=["AI Summary"])

@router.post("/summarize", response_model=AISummaryResponse)
async def generate_summary(payload: AISummaryRequest):
    """Gera um resumo e tópicos de inteligência artificial a partir da URL."""
    target_url = payload.url
    if not target_url and payload.download_id:
        async with get_db_connection() as db:
            cursor = await db.execute("SELECT url FROM downloads WHERE id = ?", (payload.download_id,))
            row = await cursor.fetchone()
            if row:
                target_url = row["url"]

    if not target_url:
        raise HTTPException(status_code=400, detail="É necessário fornecer a URL do vídeo ou o ID do download.")

    try:
        summary_res = await summarize_video(
            url=target_url,
            custom_prompt=payload.custom_prompt,
            download_id=payload.download_id
        )
        return summary_res
    except Exception as e:
        logger.error(f"Falha na sumarização por IA: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/summaries", response_model=List[AISummaryResponse])
async def list_summaries(limit: int = Query(20, ge=1, le=100)):
    """Retorna os resumos de IA salvos no banco."""
    async with get_db_connection() as db:
        cursor = await db.execute("""
            SELECT * FROM ai_summaries
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            key_points = [kp for kp in (d.get("key_points") or "").splitlines() if kp.strip()]
            result.append(AISummaryResponse(
                id=d["id"],
                download_id=d.get("download_id"),
                url=d["url"],
                title=d["title"],
                summary=d["summary"],
                key_points=key_points,
                transcript=d.get("transcript"),
                model=d.get("model", "deepseek-chat"),
                created_at=d["created_at"]
            ))
        return result
