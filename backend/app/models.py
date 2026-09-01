from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, HttpUrl, field_validator
import re

class UrlInspectRequest(BaseModel):
    url: str = Field(..., description="URL do vídeo ou post a inspecionar")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        clean_url = v.strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            raise ValueError("A URL deve iniciar com http:// ou https://")
        return clean_url

class FormatOption(BaseModel):
    format_id: str
    ext: str
    resolution: Optional[str] = None
    filesize_approx: Optional[int] = None
    note: Optional[str] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    has_video: bool = True
    has_audio: bool = True

class CarouselMediaItem(BaseModel):
    index: int
    media_type: str  # "image" ou "video"
    url: str
    thumbnail: str
    download_url: Optional[str] = None
    caption: Optional[str] = None

class MediaInfoResponse(BaseModel):
    url: str
    id: str
    title: str
    author: Optional[str] = None
    channel_url: Optional[str] = None
    duration: Optional[int] = 0
    duration_string: Optional[str] = None
    thumbnail: Optional[str] = None
    description: Optional[str] = None
    platform: str
    formats: List[FormatOption] = []
    is_live: bool = False
    media_type: str = "video"  # "video", "image", "carousel"
    is_carousel: bool = False
    carousel_items: List[CarouselMediaItem] = []

class DownloadRequest(BaseModel):
    url: str
    media_type: str = Field("video", description="'video' ou 'audio'")
    quality_preset: Optional[str] = Field("best", description="'best', '4k', '1080p', '720p', '480p', 'audio_best'")
    format_id: Optional[str] = None
    audio_format: Optional[str] = Field("mp3", description="'mp3', 'm4a', 'opus', 'wav', 'flac'")
    time_range_start: Optional[str] = Field(None, description="Formato HH:MM:SS ou segundos (ex: '00:00:10')")
    time_range_end: Optional[str] = Field(None, description="Formato HH:MM:SS ou segundos (ex: '00:01:30')")
    download_subtitles: bool = True
    download_thumbnail: bool = True
    custom_title: Optional[str] = None
    direct_media_url: Optional[str] = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        clean_url = v.strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            raise ValueError("A URL deve iniciar com http:// ou https://")
        return clean_url

class DownloadItemResponse(BaseModel):
    id: str
    url: str
    title: Optional[str] = None
    author: Optional[str] = None
    platform: Optional[str] = None
    format_id: Optional[str] = None
    format_note: Optional[str] = None
    media_type: str = "video"
    file_path: Optional[str] = None
    file_size: Optional[int] = 0
    duration: Optional[int] = 0
    thumbnail: Optional[str] = None
    status: str = "queued"  # queued, downloading, completed, error, cancelled
    progress: float = 0.0
    speed: Optional[str] = None
    eta: Optional[str] = None
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None

class AISummaryRequest(BaseModel):
    url: Optional[str] = None
    download_id: Optional[str] = None
    custom_prompt: Optional[str] = None

class AISummaryResponse(BaseModel):
    id: str
    download_id: Optional[str] = None
    url: str
    title: str
    summary: str
    key_points: List[str] = []
    transcript: Optional[str] = None
    model: str
    created_at: str

class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, str]
