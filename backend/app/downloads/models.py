import re
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.net_guard import UnsafeUrlError, check_url_format

QualityPreset = Literal["best", "4k", "1080p", "720p", "480p"]
AudioFormat = Literal["mp3", "m4a", "opus", "wav", "flac"]
MediaType = Literal["video", "audio", "image"]

_TIMESTAMP = re.compile(r"^(?:(\d{1,2}):)?(?:(\d{1,2}):)?(\d{1,5}(?:\.\d{1,3})?)$")


def parse_timestamp(value: str) -> float:
    """Converte 'SS', 'MM:SS' ou 'HH:MM:SS' (com milissegundos opcionais) em segundos."""
    text = value.strip()
    match = _TIMESTAMP.match(text)
    if not match:
        raise ValueError(f"Tempo inválido: '{value}'. Use segundos ou HH:MM:SS.")
    parts = [p for p in text.split(":")]
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    if len(parts) > 1 and any(float(p) >= 60 for p in parts[1:]):
        raise ValueError(f"Tempo inválido: '{value}'. Minutos e segundos vão de 0 a 59.")
    return seconds


def _validate_http_url(value: str) -> str:
    clean = value.strip()
    try:
        check_url_format(clean)
    except UnsafeUrlError as exc:
        raise ValueError(str(exc)) from exc
    return clean


class UrlInspectRequest(BaseModel):
    url: str = Field(..., max_length=2048)

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_http_url(v)


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
    media_type: str
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
    media_type: str = "video"
    is_carousel: bool = False
    carousel_items: List[CarouselMediaItem] = []


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., max_length=2048)
    media_type: MediaType = "video"
    quality_preset: QualityPreset = "best"
    format_id: Optional[str] = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_\-+.]+$")
    audio_format: AudioFormat = "mp3"
    time_range_start: Optional[str] = Field(None, max_length=16)
    time_range_end: Optional[str] = Field(None, max_length=16)
    download_thumbnail: bool = True
    custom_title: Optional[str] = Field(None, max_length=180)
    direct_media_url: Optional[str] = Field(None, max_length=4096)

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_http_url(v)

    @field_validator("direct_media_url")
    @classmethod
    def _check_direct(cls, v: Optional[str]) -> Optional[str]:
        return _validate_http_url(v) if v else None

    @field_validator("time_range_start", "time_range_end")
    @classmethod
    def _check_time(cls, v: Optional[str]) -> Optional[str]:
        if v is None or not v.strip():
            return None
        parse_timestamp(v)
        return v.strip()

    @model_validator(mode="after")
    def _check_range(self):
        if self.time_range_start and self.time_range_end:
            if parse_timestamp(self.time_range_end) <= parse_timestamp(self.time_range_start):
                raise ValueError("O fim do trecho precisa ser depois do início.")
        return self


class DownloadItemResponse(BaseModel):
    id: str
    url: str
    title: Optional[str] = None
    author: Optional[str] = None
    platform: Optional[str] = None
    format_id: Optional[str] = None
    format_note: Optional[str] = None
    media_type: str = "video"
    file_name: Optional[str] = None
    file_size: Optional[int] = 0
    duration: Optional[int] = 0
    thumbnail: Optional[str] = None
    status: str = "queued"
    progress: float = 0.0
    speed: Optional[str] = None
    eta: Optional[str] = None
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "DownloadItemResponse":
        data = dict(row)
        file_path = data.pop("file_path", "") or ""
        data["file_name"] = re.split(r"[\\/]", file_path)[-1] if file_path else None
        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})


class SettingsResponse(BaseModel):
    download_folder: str
    default_format: str
    default_audio_format: str
    theme: str


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    download_folder: Optional[str] = Field(None, max_length=500)
    default_format: Optional[QualityPreset] = None
    default_audio_format: Optional[AudioFormat] = None
    theme: Optional[Literal["system", "light", "dark"]] = None
