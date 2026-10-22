import asyncio
import os
import re
import logging
from typing import Dict, Any, Optional, Callable, List
from pathlib import Path
import yt_dlp

from app.config import DOWNLOADS_DIR
from app.models import MediaInfoResponse, FormatOption, DownloadRequest
from app.services.ffmpeg_helper import get_ffmpeg_path

logger = logging.getLogger("media_downloader.downloader")

def detect_platform(url: str) -> str:
    """Identifica a plataforma a partir da URL."""
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "YouTube"
    elif "instagram.com" in url_lower:
        return "Instagram"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "Twitter / X"
    elif "tiktok.com" in url_lower:
        return "TikTok"
    elif "facebook.com" in url_lower or "fb.watch" in url_lower:
        return "Facebook"
    elif "reddit.com" in url_lower or "redd.it" in url_lower:
        return "Reddit"
    elif "twitch.tv" in url_lower:
        return "Twitch"
    elif "vimeo.com" in url_lower:
        return "Vimeo"
    elif "bilibili.com" in url_lower:
        return "Bilibili"
    return "Universal"

def get_base_ydl_opts() -> Dict[str, Any]:
    """Opções base seguras para o yt-dlp."""
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "logtostderr": False,
        "extract_flat": False,
        "concurrent_fragment_downloads": 4,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        }
    }

    ffmpeg_bin = get_ffmpeg_path()
    if ffmpeg_bin:
        opts["ffmpeg_location"] = ffmpeg_bin

    return opts


async def extract_media_info(url: str) -> MediaInfoResponse:
    """Extrai informações e formatos disponíveis de um vídeo ou post de forma assíncrona."""
    # 1. Tentar extrator especializado do Instagram para posts/reels/fotos/carrosséis
    if "instagram.com" in url.lower() and ("/p/" in url.lower() or "/reel/" in url.lower() or "/tv/" in url.lower()):
        from app.services.instagram_helper import extract_instagram_post_info
        try:
            insta_info = await extract_instagram_post_info(url)
            if insta_info:
                return insta_info
        except Exception as e:
            logger.warning(f"Extrator primário do Instagram falhou: {e}")

    def _extract():
        opts = get_base_ydl_opts()
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.to_thread(_extract)
    except Exception as e:
        # Fallback de emergência para Instagram caso yt-dlp reporte No video formats found
        if "instagram.com" in url.lower():
            from app.services.instagram_helper import extract_instagram_post_info
            insta_info = await extract_instagram_post_info(url)
            if insta_info:
                return insta_info
        raise ValueError(f"Não foi possível obter dados da mídia: {str(e)}")

    if not info:
        raise ValueError("Não foi possível extrair informações da URL fornecida.")

    platform = detect_platform(url)
    title = info.get("title", "Sem Título")
    author = info.get("uploader") or info.get("channel") or info.get("creator") or platform
    duration = info.get("duration", 0)
    thumbnail = info.get("thumbnail") or (info.get("thumbnails", [{}])[-1].get("url") if info.get("thumbnails") else None)
    description = info.get("description", "")
    if description and len(description) > 300:
        description = description[:300] + "..."

    # Formatar duração HH:MM:SS
    duration_str = None
    if duration:
        hours = duration // 3600
        minutes = (duration % 3600) // 60
        seconds = duration % 60
        if hours > 0:
            duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            duration_str = f"{minutes:02d}:{seconds:02d}"

    # Filtrar formatos relevantes
    raw_formats = info.get("formats", [])
    parsed_formats: List[FormatOption] = []
    seen_resolutions = set()

    for f in raw_formats:
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")
        has_video = vcodec != "none"
        has_audio = acodec != "none"
        res = f.get("resolution") or (f"{f.get('height')}p" if f.get("height") else None)
        format_id = f.get("format_id", "")
        ext = f.get("ext", "mp4")
        note = f.get("format_note", "")
        filesize = f.get("filesize") or f.get("filesize_approx")

        if res and res not in seen_resolutions and has_video:
            seen_resolutions.add(res)
            parsed_formats.append(
                FormatOption(
                    format_id=format_id,
                    ext=ext,
                    resolution=res,
                    filesize_approx=filesize,
                    note=note,
                    vcodec=vcodec,
                    acodec=acodec,
                    has_video=has_video,
                    has_audio=has_audio
                )
            )

    return MediaInfoResponse(
        url=url,
        id=str(info.get("id", "")),
        title=title,
        author=author,
        channel_url=info.get("uploader_url") or info.get("channel_url"),
        duration=duration or 0,
        duration_string=duration_str,
        thumbnail=thumbnail,
        description=description,
        platform=platform,
        formats=parsed_formats,
        is_live=bool(info.get("is_live", False))
    )

def build_download_options(
    request: DownloadRequest,
    target_folder: Path,
    progress_hook: Callable[[Dict[str, Any]], None],
    cancel_event: asyncio.Event
) -> Dict[str, Any]:
    """Constrói o dicionário de opções do yt-dlp para download."""
    opts = get_base_ydl_opts()
    opts["progress_hooks"] = [progress_hook]

    # Template do nome do arquivo
    outtmpl = str(target_folder / "%(title)s [%(id)s].%(ext)s")
    if request.custom_title:
        safe_title = re.sub(r'[\\/*?:"<>|]', "", request.custom_title).strip()
        outtmpl = str(target_folder / f"{safe_title}.%(ext)s")
    opts["outtmpl"] = outtmpl

    # Corte de tempo (Time Range)
    if request.time_range_start or request.time_range_end:
        start = request.time_range_start or "0"
        end = request.time_range_end or "inf"
        opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(float(start) if start.replace(".", "", 1).isdigit() else start, float(end) if end.replace(".", "", 1).isdigit() else end)])
        opts["force_keyframes_at_cuts"] = True

    # Pós-processadores e formatos
    postprocessors = []

    if request.media_type == "audio":
        audio_fmt = request.audio_format or "mp3"
        opts["format"] = "bestaudio/best"
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_fmt,
            "preferredquality": "320" if audio_fmt == "mp3" else "0",
        })
    else:
        # Formato de vídeo
        if request.format_id:
            opts["format"] = f"{request.format_id}+bestaudio/best"
        elif request.quality_preset == "4k":
            opts["format"] = "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best"
        elif request.quality_preset == "1080p":
            opts["format"] = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
        elif request.quality_preset == "720p":
            opts["format"] = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
        elif request.quality_preset == "480p":
            opts["format"] = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
        else:
            opts["format"] = "bestvideo+bestaudio/best"

        opts["merge_output_format"] = "mp4"

    # Miniatura e metadados
    if request.download_thumbnail:
        opts["writethumbnail"] = True
        postprocessors.append({"key": "EmbedThumbnail"})

    postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
    opts["postprocessors"] = postprocessors

    return opts
