import asyncio
import logging
import re
import zipfile
from pathlib import Path
from typing import Optional, List, Dict, Any
import httpx
import instaloader

from app.models import MediaInfoResponse, FormatOption, CarouselMediaItem

logger = logging.getLogger("media_downloader.instagram_helper")

def extract_shortcode(url: str) -> Optional[str]:
    """Extrai o shortcode de uma URL de post/reels do Instagram."""
    m = re.search(r"instagram\.com/(?:p|reel|tv)/([a-zA-Z0-9_\-]+)", url)
    if m:
        return m.group(1)
    return None

async def extract_instagram_post_info(url: str) -> Optional[MediaInfoResponse]:
    """Extrai metadados completos de posts de fotos, vídeos e carrosséis do Instagram."""
    shortcode = extract_shortcode(url)
    if not shortcode:
        return None

    def _get_post_and_nodes():
        L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            save_metadata=False,
            compress_json=False,
            max_connection_attempts=1,
            sleep=False,
            quiet=True
        )
        L.context.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        try:
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            raw_nodes = []
            if post.mediacount > 1:
                for idx, node in enumerate(post.get_sidecar_nodes()):
                    raw_nodes.append({
                        "index": idx + 1,
                        "media_type": "video" if node.is_video else "image",
                        "thumbnail": node.display_url,
                        "download_url": node.video_url if node.is_video else node.display_url
                    })
            return post, raw_nodes
        except Exception as e:
            logger.warning(f"Instaloader falhou para shortcode {shortcode}: {e}")
            return None, []

    post, raw_nodes = await asyncio.to_thread(_get_post_and_nodes)
    if not post:
        return None

    caption = post.caption or "Publicação do Instagram"
    title = caption[:80].strip() if len(caption) > 80 else caption
    title = title.replace("\n", " ").strip() or f"Instagram Post [{shortcode}]"
    
    author = post.owner_username or "Instagram"
    thumbnail = post.url
    is_video = post.is_video
    mediacount = post.mediacount

    formats: List[FormatOption] = []
    carousel_items: List[CarouselMediaItem] = []
    
    if is_video:
        media_type = "video"
        formats.append(
            FormatOption(
                format_id="best",
                ext="mp4",
                resolution="Original HD (Vídeo MP4)",
                vcodec="h264",
                acodec="aac",
                has_video=True,
                has_audio=True
            )
        )
    elif mediacount > 1:
        media_type = "carousel"
        for n in raw_nodes:
            carousel_items.append(
                CarouselMediaItem(
                    index=n["index"],
                    media_type=n["media_type"],
                    url=f"https://www.instagram.com/p/{shortcode}/?img_index={n['index']}",
                    thumbnail=n["thumbnail"],
                    download_url=n["download_url"],
                    caption=f"Mídia #{n['index']}"
                )
            )

        formats.append(
            FormatOption(
                format_id="carousel_all",
                ext="jpg/mp4",
                resolution=f"Carrossel Completo ({mediacount} Mídias)",
                has_video=False,
                has_audio=False
            )
        )
        formats.append(
            FormatOption(
                format_id="photo_cover",
                ext="jpg",
                resolution="Capa Principal (Foto HD)",
                has_video=False,
                has_audio=False
            )
        )
    else:
        media_type = "image"
        formats.append(
            FormatOption(
                format_id="photo_hd",
                ext="jpg",
                resolution="Foto Original HD (JPG)",
                has_video=False,
                has_audio=False
            )
        )

    return MediaInfoResponse(
        url=f"https://www.instagram.com/p/{shortcode}/",
        id=shortcode,
        title=title,
        author=author,
        channel_url=f"https://www.instagram.com/{author}/",
        duration=int(post.video_duration or 0) if is_video else 0,
        duration_string=f"{int(post.video_duration)}s" if is_video and post.video_duration else None,
        thumbnail=thumbnail,
        description=caption,
        platform="Instagram",
        formats=formats,
        is_live=False,
        media_type=media_type,
        is_carousel=mediacount > 1,
        carousel_items=carousel_items
    )

async def download_instagram_media_direct(
    url: str,
    target_folder: Path,
    custom_title: Optional[str] = None,
    progress_callback = None
) -> str:
    """Baixa fotos, vídeos ou carrosséis do Instagram diretamente e salva na pasta de destino."""
    shortcode = extract_shortcode(url)
    if not shortcode:
        raise ValueError("URL de post do Instagram inválida.")

    # Verificar se a URL aponta para um item específico de carrossel (?img_index=N)
    target_index: Optional[int] = None
    m_idx = re.search(r"[?&]img_index=(\d+)", url)
    if m_idx:
        try:
            target_index = int(m_idx.group(1))
        except ValueError:
            target_index = None

    def _get_nodes():
        L = instaloader.Instaloader(quiet=True, max_connection_attempts=1, sleep=False)
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        if post.mediacount > 1:
            all_nodes = list(post.get_sidecar_nodes())
            
            # Se for requisitado um índice específico, pega estritamente aquele item!
            if target_index is not None and 1 <= target_index <= len(all_nodes):
                n = all_nodes[target_index - 1]
                m_url = n.video_url if n.is_video else n.display_url
                ext = "mp4" if n.is_video else "jpg"
                return post, [(m_url, ext)], True
            
            # Caso contrário (Baixar Todas as Mídias), pega todos os nós
            items = []
            for n in all_nodes:
                items.append((n.video_url if n.is_video else n.display_url, "mp4" if n.is_video else "jpg"))
            return post, items, False
        else:
            media_url = post.video_url if post.is_video else post.url
            ext = "mp4" if post.is_video else "jpg"
            return post, [(media_url, ext)], True

    post, media_items, is_single_item = await asyncio.to_thread(_get_nodes)
    safe_title = re.sub(r'[\\/*?:"<>|]', "", custom_title or post.owner_username + "_" + shortcode).strip()

    downloaded_paths = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    async with httpx.AsyncClient(timeout=45.0, follow_redirects=True, headers=headers) as client:
        total = len(media_items)
        for i, (m_url, ext) in enumerate(media_items):
            if is_single_item or total == 1:
                file_name = f"{safe_title}.{ext}"
            else:
                file_name = f"{safe_title}_{i+1}.{ext}"
            
            file_path = target_folder / file_name

            resp = await client.get(m_url)
            if resp.status_code == 200:
                file_path.write_bytes(resp.content)
                downloaded_paths.append(str(file_path))

            if progress_callback:
                percent = round(((i + 1) / total) * 90, 1)
                await progress_callback(percent, f"Baixando mídia {i+1} de {total}", str(file_path))

    if not downloaded_paths:
        raise ValueError("Não foi possível transferir as mídias do post do Instagram.")

    # Se houver mais de 1 mídia (Baixar Todas), empacota todas as mídias em um único arquivo .ZIP
    if len(downloaded_paths) > 1:
        zip_name = f"{safe_title}.zip"
        zip_path = target_folder / zip_name
        
        if progress_callback:
            await progress_callback(95.0, "Compactando mídias em arquivo .zip...", str(zip_path))
            
        def _create_zip():
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for p in downloaded_paths:
                    zf.write(p, arcname=Path(p).name)
            return str(zip_path)

        final_zip = await asyncio.to_thread(_create_zip)
        
        if progress_callback:
            await progress_callback(100.0, "Arquivo .zip pronto para download!", final_zip)
            
        return final_zip

    # Se for 1 única mídia, entrega o arquivo solto (.jpg ou .mp4)!
    return downloaded_paths[0]
