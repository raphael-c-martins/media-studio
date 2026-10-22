import shutil

import psutil
import yt_dlp
from fastapi import APIRouter

from app import config
from app.downloads.ffmpeg_helper import check_ffmpeg_available
from app.frames.registry import registry

router = APIRouter(tags=["Health"])


@router.get("/health")
@router.get("/api/health")
async def health_check():
    disk = shutil.disk_usage(config.DOWNLOADS_DIR)
    return {
        "status": "healthy",
        "service": "Media Studio",
        "version": config.APP_VERSION,
        "yt_dlp_version": yt_dlp.version.__version__,
        "ffmpeg_available": check_ffmpeg_available(),
        "database_ok": config.DB_PATH.exists(),
        "frame_sessions": len(registry),
        "disk_free_gb": round(disk.free / 1024 ** 3, 1),
        "cpu_percent": psutil.cpu_percent(),
        "memory_percent": psutil.virtual_memory().percent,
    }
