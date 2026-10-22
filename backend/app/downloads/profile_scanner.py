import asyncio
import logging
import re
from typing import List, Optional
from pydantic import BaseModel
import instaloader
import yt_dlp

from app.downloads.downloader import get_base_ydl_opts

logger = logging.getLogger("media_studio.profile_scanner")

class ProfileMediaItem(BaseModel):
    id: str
    url: str
    media_type: str  # video, image, reel, carousel
    thumbnail: Optional[str] = None
    caption: Optional[str] = None
    date: Optional[str] = None
    likes: Optional[int] = 0
    comments: Optional[int] = 0
    duration: Optional[int] = 0

class ProfileScanResponse(BaseModel):
    platform: str
    username: str
    full_name: Optional[str] = None
    bio: Optional[str] = None
    profile_pic_url: Optional[str] = None
    followers_count: Optional[int] = 0
    posts_count: Optional[int] = 0
    items: List[ProfileMediaItem] = []

def clean_username(input_str: str, platform: str) -> str:
    """Extrai o nome de usuário limpo a partir de @username ou URL de perfil."""
    s = input_str.strip()
    if s.startswith("@"):
        return s[1:].strip()
    
    s = s.split("?")[0].rstrip("/")

    if platform.lower() == "instagram" or "instagram.com" in s.lower():
        m = re.search(r"instagram\.com/(?:[a-zA-Z0-9_\.]+/)?([a-zA-Z0-9_\.]+)", s)
        if m and m.group(1) not in ("p", "reel", "stories", "tv", "explore"):
            return m.group(1)
    elif platform.lower() in ("twitter", "twitter / x", "x") or "twitter.com" in s.lower() or "x.com" in s.lower():
        m = re.search(r"(?:twitter\.com|x\.com)/([a-zA-Z0-9_]+)", s)
        if m and m.group(1) not in ("i", "intent", "search"):
            return m.group(1)
    elif platform.lower() == "youtube" or "youtube.com" in s.lower():
        m = re.search(r"youtube\.com/@([a-zA-Z0-9_\.\-]+)", s)
        if m:
            return m.group(1)
    elif platform.lower() == "tiktok" or "tiktok.com" in s.lower():
        m = re.search(r"tiktok\.com/@([a-zA-Z0-9_\.\-]+)", s)
        if m:
            return m.group(1)

    return s.lstrip("@")

async def scan_instagram_profile(target: str, limit: int = 18) -> ProfileScanResponse:
    """Varre um perfil do Instagram e extrai posts públicos com timeout seguro."""
    username = clean_username(target, "instagram")

    def _scrape():
        L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
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
            profile = instaloader.Profile.from_username(L.context, username)
        except instaloader.exceptions.ProfileNotExistsException:
            raise ValueError(f"O perfil @{username} não foi encontrado no Instagram.")
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "Too Many Requests" in err_msg or "login" in err_msg.lower():
                raise ValueError(
                    f"O Instagram aplicou limite temporário de requisições anônimas para o perfil @{username}. "
                    "Para baixar, cole diretamente o link do Post ou Reels desejado (ex: https://instagram.com/p/... ou /reel/...)."
                )
            raise ValueError(f"Não foi possível carregar o perfil @{username}: {err_msg}")

        items = []
        count = 0
        try:
            for post in profile.get_posts():
                if count >= limit:
                    break
                
                m_type = "image"
                if post.is_video:
                    m_type = "reel"
                elif post.mediacount > 1:
                    m_type = "carousel"

                caption = (post.caption or "")
                if len(caption) > 120:
                    caption = caption[:120] + "..."

                items.append(ProfileMediaItem(
                    id=post.shortcode,
                    url=f"https://www.instagram.com/p/{post.shortcode}/",
                    media_type=m_type,
                    thumbnail=post.url,
                    caption=caption,
                    date=post.date_utc.strftime("%d/%m/%Y"),
                    likes=post.likes,
                    comments=post.comments
                ))
                count += 1
        except Exception as e:
            logger.warning(f"Erro ao paginar posts de @{username}: {e}")

        return ProfileScanResponse(
            platform="Instagram",
            username=profile.username,
            full_name=profile.full_name or profile.username,
            bio=profile.biography,
            profile_pic_url=profile.profile_pic_url,
            followers_count=profile.followers,
            posts_count=profile.mediacount,
            items=items
        )

    try:
        return await asyncio.wait_for(asyncio.to_thread(_scrape), timeout=12.0)
    except asyncio.TimeoutError:
        raise ValueError(
            f"Tempo limite excedido ao consultar o Instagram para @{username}. "
            "Recomendamos colar o link direto da publicação (Post/Reels) para download imediato."
        )

async def scan_generic_profile(url: str, platform: str, limit: int = 18) -> ProfileScanResponse:
    """Varredura genérica de canal/perfil via yt-dlp flat-playlist com timeout."""
    def _extract():
        opts = get_base_ydl_opts()
        opts["extract_flat"] = "in_playlist"
        opts["playlistend"] = limit
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        info = await asyncio.wait_for(asyncio.to_thread(_extract), timeout=15.0)
    except asyncio.TimeoutError:
        raise ValueError(f"Tempo limite excedido ao obter informações do perfil em {platform}.")
    except Exception as e:
        raise ValueError(f"Não foi possível obter dados do perfil em {platform}: {str(e)}")

    if not info:
        raise ValueError(f"Nenhuma mídia pública encontrada para este perfil em {platform}.")

    entries = info.get("entries", [])
    username = info.get("uploader") or info.get("channel") or info.get("id") or "Perfil"
    title = info.get("title") or username
    thumbnail = info.get("thumbnail") or (info.get("thumbnails", [{}])[-1].get("url") if info.get("thumbnails") else None)

    items: List[ProfileMediaItem] = []
    for e in entries:
        if not e:
            continue
        item_url = e.get("url") or e.get("webpage_url") or (f"https://www.youtube.com/watch?v={e.get('id')}" if platform == "YouTube" else "")
        if not item_url and e.get("id"):
            item_url = url

        thumb = e.get("thumbnail") or (e.get("thumbnails", [{}])[-1].get("url") if e.get("thumbnails") else None)
        cap = e.get("title") or e.get("description", "")
        if len(cap) > 120:
            cap = cap[:120] + "..."

        items.append(ProfileMediaItem(
            id=str(e.get("id", "")),
            url=item_url,
            media_type="video",
            thumbnail=thumb,
            caption=cap,
            duration=e.get("duration", 0)
        ))

    return ProfileScanResponse(
        platform=platform,
        username=username,
        full_name=title,
        bio=info.get("description", ""),
        profile_pic_url=thumbnail,
        followers_count=info.get("channel_follower_count", 0),
        posts_count=len(items),
        items=items
    )

async def scan_profile(target: str, platform: str = "auto", limit: int = 18) -> ProfileScanResponse:
    """Roteador inteligente para varredura de perfis por plataforma."""
    target_clean = target.strip()
    plat_lower = platform.lower()
    
    if plat_lower == "instagram" or "instagram.com" in target_clean.lower():
        return await scan_instagram_profile(target_clean, limit)
    elif plat_lower in ("twitter", "twitter / x", "x") or "twitter.com" in target_clean.lower() or "x.com" in target_clean.lower():
        u = clean_username(target_clean, "twitter")
        return await scan_generic_profile(f"https://x.com/{u}", "Twitter / X", limit)
    elif plat_lower == "youtube" or "youtube.com" in target_clean.lower():
        u = clean_username(target_clean, "youtube")
        url = target_clean if target_clean.startswith("http") else f"https://www.youtube.com/@{u}/videos"
        return await scan_generic_profile(url, "YouTube", limit)
    elif plat_lower == "tiktok" or "tiktok.com" in target_clean.lower():
        u = clean_username(target_clean, "tiktok")
        return await scan_generic_profile(f"https://www.tiktok.com/@{u}", "TikTok", limit)
    else:
        if target_clean.startswith("@"):
            return await scan_instagram_profile(target_clean, limit)
        return await scan_generic_profile(target_clean, "Outro site", limit)
