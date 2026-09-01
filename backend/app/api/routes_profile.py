from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from app.services.profile_scanner import scan_profile, ProfileScanResponse

router = APIRouter(prefix="/api/profile", tags=["Profile Scanner"])

class ProfileScanRequest(BaseModel):
    target: str
    platform: Optional[str] = "auto"
    limit: Optional[int] = 18

@router.post("/scan", response_model=ProfileScanResponse)
async def scan_profile_endpoint(req: ProfileScanRequest):
    """Varre um perfil público (Instagram, Twitter/X, YouTube ou TikTok) e retorna galeria de mídias."""
    if not req.target or not req.target.strip():
        raise HTTPException(status_code=400, detail="Informe um nome de usuário (@usuario) ou link do perfil.")

    try:
        data = await scan_profile(
            target=req.target.strip(),
            platform=req.platform or "auto",
            limit=req.limit or 18
        )
        return data
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao varrer perfil: {str(e)}")
