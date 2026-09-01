import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("media_downloader.ffmpeg")

def get_ffmpeg_path() -> Optional[str]:
    """Retorna o caminho do binário do FFmpeg (via imageio-ffmpeg ou PATH do sistema)."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception as e:
        logger.debug(f"imageio-ffmpeg não localizado: {e}")

    # Fallback para PATH global
    path = shutil.which("ffmpeg")
    if path:
        return path

    return None

def check_ffmpeg_available() -> bool:
    """Retorna True se o FFmpeg estiver disponível."""
    return get_ffmpeg_path() is not None

def get_ffmpeg_version() -> str:
    """Retorna a versão instalada do FFmpeg ou mensagem informativa."""
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        return "Não instalado (Conversões básicas utilizarão modo direto do yt-dlp)"
    try:
        res = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=5)
        first_line = res.stdout.splitlines()[0] if res.stdout else "Disponível (FFmpeg integrado)"
        return first_line
    except Exception as e:
        return f"Disponível ({ffmpeg})"
