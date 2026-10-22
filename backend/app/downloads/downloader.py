import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List

import yt_dlp

from app.downloads.ffmpeg_helper import get_ffmpeg_path
from app.downloads.models import DownloadRequest, FormatOption, MediaInfoResponse, parse_timestamp
from app.downloads.storage import safe_filename

logger = logging.getLogger("media_studio.downloader")

PLATFORMS = [
    (("youtube.com", "youtu.be"), "YouTube"),
    (("instagram.com",), "Instagram"),
    (("twitter.com", "x.com"), "Twitter / X"),
    (("tiktok.com",), "TikTok"),
    (("facebook.com", "fb.watch"), "Facebook"),
    (("reddit.com", "redd.it"), "Reddit"),
    (("twitch.tv",), "Twitch"),
    (("vimeo.com",), "Vimeo"),
]

QUALITY_FORMATS = {
    "4k": "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
    "best": "bestvideo+bestaudio/best",
}


def detect_platform(url: str) -> str:
    url_lower = url.lower()
    for domains, name in PLATFORMS:
        if any(domain in url_lower for domain in domains):
            return name
    return "Outro site"


def is_instagram_post(url: str) -> bool:
    lower = url.lower()
    return "instagram.com" in lower and any(part in lower for part in ("/p/", "/reel/", "/tv/"))


def get_base_ydl_opts() -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "logtostderr": False,
        "extract_flat": False,
        "concurrent_fragment_downloads": 4,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    }
    ffmpeg_bin = get_ffmpeg_path()
    if ffmpeg_bin:
        opts["ffmpeg_location"] = ffmpeg_bin
    return opts


def _format_duration(duration: int) -> str:
    hours, rest = divmod(int(duration), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


async def extract_media_info(url: str) -> MediaInfoResponse:
    if is_instagram_post(url):
        from app.downloads.instagram_helper import extract_instagram_post_info
        try:
            insta_info = await extract_instagram_post_info(url)
            if insta_info:
                return insta_info
        except Exception as exc:
            logger.warning("Extrator do Instagram falhou: %s", exc)

    def _extract():
        with yt_dlp.YoutubeDL(get_base_ydl_opts()) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.to_thread(_extract)
    except Exception as exc:
        if "instagram.com" in url.lower():
            from app.downloads.instagram_helper import extract_instagram_post_info
            insta_info = await extract_instagram_post_info(url)
            if insta_info:
                return insta_info
        raise ValueError(f"Não foi possível obter os dados da mídia: {exc}") from exc

    if not info:
        raise ValueError("Não foi possível extrair informações dessa URL.")

    platform = detect_platform(url)
    duration = int(info.get("duration") or 0)
    thumbnails = info.get("thumbnails") or []
    thumbnail = info.get("thumbnail") or (thumbnails[-1].get("url") if thumbnails else None)
    description = info.get("description") or ""
    if len(description) > 300:
        description = description[:300] + "..."

    formats: List[FormatOption] = []
    seen_resolutions = set()
    for item in info.get("formats") or []:
        vcodec = item.get("vcodec", "none")
        acodec = item.get("acodec", "none")
        resolution = item.get("resolution") or (f"{item.get('height')}p" if item.get("height") else None)
        if not resolution or vcodec == "none" or resolution in seen_resolutions:
            continue
        seen_resolutions.add(resolution)
        formats.append(FormatOption(
            format_id=str(item.get("format_id", "")),
            ext=item.get("ext", "mp4"),
            resolution=resolution,
            filesize_approx=item.get("filesize") or item.get("filesize_approx"),
            note=item.get("format_note", ""),
            vcodec=vcodec,
            acodec=acodec,
            has_video=True,
            has_audio=acodec != "none",
        ))

    return MediaInfoResponse(
        url=url,
        id=str(info.get("id", "")),
        title=info.get("title") or "Sem título",
        author=info.get("uploader") or info.get("channel") or info.get("creator") or platform,
        channel_url=info.get("uploader_url") or info.get("channel_url"),
        duration=duration,
        duration_string=_format_duration(duration) if duration else None,
        thumbnail=thumbnail,
        description=description,
        platform=platform,
        formats=formats,
        is_live=bool(info.get("is_live", False)),
    )


def build_download_options(
    request: DownloadRequest, target_folder: Path, progress_hook: Callable[[Dict[str, Any]], None]
) -> Dict[str, Any]:
    opts = get_base_ydl_opts()
    opts["progress_hooks"] = [progress_hook]

    if request.custom_title:
        stem = safe_filename(request.custom_title)
        opts["outtmpl"] = str(target_folder / f"{stem}.%(ext)s")
    else:
        opts["outtmpl"] = str(target_folder / "%(title).150B [%(id)s].%(ext)s")
    opts["windowsfilenames"] = True

    if request.time_range_start or request.time_range_end:
        start = parse_timestamp(request.time_range_start) if request.time_range_start else 0.0
        end = parse_timestamp(request.time_range_end) if request.time_range_end else float("inf")
        opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(start, end)])
        opts["force_keyframes_at_cuts"] = True

    postprocessors = []
    if request.media_type == "audio":
        opts["format"] = "bestaudio/best"
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": request.audio_format,
            "preferredquality": "320" if request.audio_format == "mp3" else "0",
        })
    else:
        if request.format_id:
            opts["format"] = f"{request.format_id}+bestaudio/best"
        else:
            opts["format"] = QUALITY_FORMATS.get(request.quality_preset, QUALITY_FORMATS["best"])
        opts["merge_output_format"] = "mp4"

    if request.download_thumbnail:
        opts["writethumbnail"] = True
        postprocessors.append({"key": "EmbedThumbnail"})

    postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
    opts["postprocessors"] = postprocessors
    return opts
