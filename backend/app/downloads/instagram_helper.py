import asyncio
import logging
import re
import zipfile
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

import httpx
import instaloader

from app import config
from app.downloads.models import CarouselMediaItem, FormatOption, MediaInfoResponse
from app.downloads.storage import safe_filename, unique_path
from app.net_guard import BROWSER_HEADERS, download_public_file

logger = logging.getLogger("media_studio.instagram")

ProgressCallback = Callable[[float, str], Awaitable[None]]


def extract_shortcode(url: str) -> Optional[str]:
    match = re.search(r"instagram\.com/(?:p|reel|tv)/([a-zA-Z0-9_\-]+)", url)
    return match.group(1) if match else None


def _new_loader() -> instaloader.Instaloader:
    loader = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        save_metadata=False,
        compress_json=False,
        max_connection_attempts=1,
        sleep=False,
        quiet=True,
    )
    loader.context.user_agent = BROWSER_HEADERS["User-Agent"]
    return loader


async def extract_instagram_post_info(url: str) -> Optional[MediaInfoResponse]:
    shortcode = extract_shortcode(url)
    if not shortcode:
        return None

    def _load():
        try:
            post = instaloader.Post.from_shortcode(_new_loader().context, shortcode)
        except Exception as exc:
            logger.warning("Instaloader falhou para %s: %s", shortcode, exc)
            return None, []
        nodes = []
        if post.mediacount > 1:
            for idx, node in enumerate(post.get_sidecar_nodes(), start=1):
                nodes.append({
                    "index": idx,
                    "media_type": "video" if node.is_video else "image",
                    "thumbnail": node.display_url,
                    "download_url": node.video_url if node.is_video else node.display_url,
                })
        return post, nodes

    post, nodes = await asyncio.to_thread(_load)
    if not post:
        return None

    caption = post.caption or "Publicação do Instagram"
    title = caption.replace("\n", " ").strip()[:80] or f"Instagram {shortcode}"
    author = post.owner_username or "Instagram"
    formats: List[FormatOption] = []
    carousel_items: List[CarouselMediaItem] = []

    if post.is_video:
        media_type = "video"
        formats.append(FormatOption(format_id="best", ext="mp4", resolution="Vídeo original (MP4)",
                                    vcodec="h264", acodec="aac"))
    elif post.mediacount > 1:
        media_type = "carousel"
        for node in nodes:
            carousel_items.append(CarouselMediaItem(
                index=node["index"],
                media_type=node["media_type"],
                url=f"https://www.instagram.com/p/{shortcode}/?img_index={node['index']}",
                thumbnail=node["thumbnail"],
                download_url=node["download_url"],
                caption=f"Mídia {node['index']}",
            ))
        formats.append(FormatOption(format_id="carousel_all", ext="zip",
                                    resolution=f"Carrossel completo ({post.mediacount} mídias)",
                                    has_video=False, has_audio=False))
    else:
        media_type = "image"
        formats.append(FormatOption(format_id="photo_hd", ext="jpg", resolution="Foto original (JPG)",
                                    has_video=False, has_audio=False))

    duration = int(post.video_duration or 0) if post.is_video else 0
    return MediaInfoResponse(
        url=f"https://www.instagram.com/p/{shortcode}/",
        id=shortcode,
        title=title,
        author=author,
        channel_url=f"https://www.instagram.com/{author}/",
        duration=duration,
        duration_string=f"{duration}s" if duration else None,
        thumbnail=post.url,
        description=caption,
        platform="Instagram",
        formats=formats,
        media_type=media_type,
        is_carousel=post.mediacount > 1,
        carousel_items=carousel_items,
    )


async def download_instagram_media_direct(
    url: str,
    target_folder: Path,
    custom_title: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
) -> str:
    """Baixa foto, vídeo ou carrossel. No carrossel completo, os arquivos soltos ficam na pasta e um .zip
    com todos é devolvido para o navegador."""
    shortcode = extract_shortcode(url)
    if not shortcode:
        raise ValueError("URL de post do Instagram inválida.")

    index_match = re.search(r"[?&]img_index=(\d+)", url)
    target_index = int(index_match.group(1)) if index_match else None

    def _collect():
        post = instaloader.Post.from_shortcode(_new_loader().context, shortcode)
        if post.mediacount > 1:
            nodes = list(post.get_sidecar_nodes())
            if target_index is not None and 1 <= target_index <= len(nodes):
                node = nodes[target_index - 1]
                return post, [(node.video_url if node.is_video else node.display_url,
                               "mp4" if node.is_video else "jpg")]
            return post, [(n.video_url if n.is_video else n.display_url, "mp4" if n.is_video else "jpg")
                          for n in nodes]
        return post, [(post.video_url if post.is_video else post.url, "mp4" if post.is_video else "jpg")]

    post, media_items = await asyncio.to_thread(_collect)
    stem = safe_filename(custom_title or f"{post.owner_username}_{shortcode}")
    total = len(media_items)
    saved: List[Path] = []

    async with httpx.AsyncClient(timeout=60.0, headers=BROWSER_HEADERS) as client:
        for position, (media_url, ext) in enumerate(media_items, start=1):
            name = stem if total == 1 else f"{stem}_{position}"
            destination = unique_path(target_folder, name, ext)
            try:
                await download_public_file(media_url, destination, config.MAX_DIRECT_MEDIA_BYTES, client=client)
                saved.append(destination)
            except Exception as exc:
                logger.warning("Falha ao baixar mídia %s de %s: %s", position, shortcode, exc)
            if progress_callback:
                await progress_callback(round(position / total * 90, 1), f"Mídia {position} de {total}")

    if not saved:
        raise ValueError("Não foi possível baixar as mídias desse post.")
    if len(saved) == 1:
        return str(saved[0])

    zip_path = unique_path(target_folder, stem, "zip")
    if progress_callback:
        await progress_callback(95.0, "Compactando em .zip")

    def _zip():
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as archive:
            for item in saved:
                archive.write(item, arcname=item.name)

    await asyncio.to_thread(_zip)
    return str(zip_path)
