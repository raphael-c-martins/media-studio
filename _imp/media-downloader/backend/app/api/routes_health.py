import shutil
import psutil
import yt_dlp
from fastapi import APIRouter
from app.config import DOWNLOADS_DIR, DB_PATH
from app.services.ffmpeg_helper import check_ffmpeg_available, get_ffmpeg_version

router = APIRouter(tags=["Health"])

@router.get("/health")
async def health_check():
    """Endpoint de verificação de saúde e diagnóstico do sistema."""
    disk = shutil.disk_usage(DOWNLOADS_DIR)
    free_gb = round(disk.free / (1024**3), 2)
    total_gb = round(disk.total / (1024**3), 2)

    return {
        "status": "healthy",
        "service": "MediaDownloader Pro API",
        "version": "1.0.0",
        "yt_dlp_version": yt_dlp.version.__version__,
        "ffmpeg_available": check_ffmpeg_available(),
        "ffmpeg_info": get_ffmpeg_version(),
        "database_connected": DB_PATH.exists(),
        "storage": {
            "downloads_dir": str(DOWNLOADS_DIR),
            "free_space_gb": free_gb,
            "total_space_gb": total_gb
        },
        "system_metrics": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent
        }
    }
