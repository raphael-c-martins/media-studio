import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("media_downloader.ffmpeg")

# Cache interno para evitar chamadas repetidas ao static-ffmpeg
_cached_ffmpeg_dir: Optional[str] = None


def _resolve_static_ffmpeg() -> Optional[str]:
    """Tenta localizar o diretório com ffmpeg + ffprobe via static-ffmpeg."""
    global _cached_ffmpeg_dir
    if _cached_ffmpeg_dir:
        return _cached_ffmpeg_dir

    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
        # Após add_paths(), os binários ficam acessíveis via shutil.which
        ffmpeg_exe = shutil.which("ffmpeg")
        ffprobe_exe = shutil.which("ffprobe")
        if ffmpeg_exe and ffprobe_exe:
            # Retornar o diretório que contém ambos
            ffmpeg_dir = str(Path(ffmpeg_exe).parent)
            _cached_ffmpeg_dir = ffmpeg_dir
            logger.info(f"static-ffmpeg: binários localizados em {ffmpeg_dir}")
            return ffmpeg_dir
    except Exception as e:
        logger.debug(f"static-ffmpeg não disponível: {e}")

    return None


def get_ffmpeg_path() -> Optional[str]:
    """Retorna o diretório contendo ffmpeg + ffprobe para uso com ffmpeg_location do yt-dlp.

    Prioridade:
      1. static-ffmpeg (fornece ffmpeg + ffprobe juntos, essencial para o yt-dlp)
      2. imageio-ffmpeg (fornece apenas ffmpeg, sem ffprobe - usado como fallback)
      3. PATH do sistema
    """
    # 1. static-ffmpeg: fornece ffmpeg + ffprobe (melhor opção para yt-dlp)
    static_dir = _resolve_static_ffmpeg()
    if static_dir:
        return static_dir

    # 2. imageio-ffmpeg: só tem ffmpeg, sem ffprobe
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            ffmpeg_dir = str(Path(exe).parent)
            # Verificar se ffprobe também existe nessa pasta
            ffprobe_candidate = Path(ffmpeg_dir) / "ffprobe.exe"
            if ffprobe_candidate.exists():
                return ffmpeg_dir
            # Sem ffprobe nessa pasta, retornar o diretório do executável mesmo assim
            logger.warning(
                "imageio-ffmpeg fornece apenas ffmpeg (sem ffprobe). "
                "O pós-processamento do yt-dlp pode falhar em operações de merge."
            )
            return ffmpeg_dir
    except Exception as e:
        logger.debug(f"imageio-ffmpeg não localizado: {e}")

    # 3. Fallback para PATH global
    ffmpeg_sys = shutil.which("ffmpeg")
    ffprobe_sys = shutil.which("ffprobe")
    if ffmpeg_sys:
        if not ffprobe_sys:
            logger.warning("ffmpeg encontrado no PATH, mas ffprobe ausente.")
        return str(Path(ffmpeg_sys).parent)

    return None


def check_ffmpeg_available() -> bool:
    """Retorna True se o FFmpeg estiver disponível."""
    return get_ffmpeg_path() is not None


def check_ffprobe_available() -> bool:
    """Retorna True se o FFprobe estiver disponível (essencial para yt-dlp)."""
    ffmpeg_dir = get_ffmpeg_path()
    if not ffmpeg_dir:
        return False
    ffprobe = shutil.which("ffprobe") or (Path(ffmpeg_dir) / "ffprobe.exe").exists()
    return bool(ffprobe)


def get_ffmpeg_version() -> str:
    """Retorna a versão instalada do FFmpeg ou mensagem informativa."""
    ffmpeg_dir = get_ffmpeg_path()
    if not ffmpeg_dir:
        return "Não instalado (Conversões básicas utilizarão modo direto do yt-dlp)"

    ffmpeg_exe = shutil.which("ffmpeg") or str(Path(ffmpeg_dir) / "ffmpeg.exe")
    try:
        res = subprocess.run(
            [ffmpeg_exe, "-version"],
            capture_output=True, text=True, timeout=5
        )
        first_line = res.stdout.splitlines()[0] if res.stdout else "Disponível (FFmpeg integrado)"
        has_probe = check_ffprobe_available()
        probe_status = " | ffprobe: OK" if has_probe else " | ffprobe: AUSENTE"
        return f"{first_line}{probe_status}"
    except Exception:
        return f"Disponível ({ffmpeg_dir})"
