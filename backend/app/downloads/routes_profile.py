from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.downloads.profile_scanner import ProfileScanResponse, scan_profile
from app.net_guard import UnsafeUrlError, assert_public_url

router = APIRouter(prefix="/api/profile", tags=["Profile"])


class ProfileScanRequest(BaseModel):
    target: str = Field(..., min_length=1, max_length=300)
    platform: Literal["auto", "youtube", "instagram", "twitter", "tiktok"] = "auto"
    limit: int = Field(18, ge=1, le=48)


@router.post("/scan", response_model=ProfileScanResponse)
async def scan_profile_endpoint(req: ProfileScanRequest):
    target = req.target.strip()
    try:
        if target.lower().startswith(("http://", "https://")):
            await assert_public_url(target)
        return await scan_profile(target=target, platform=req.platform, limit=req.limit)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Erro ao carregar o perfil: {exc}") from exc
