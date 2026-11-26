"""Rotas da API para rastreamento de placas, corte e exportação MP4."""
import asyncio
import logging
import math
import os
import tempfile
import threading
from pathlib import Path
from typing import List, Literal, Optional, Set

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.background import BackgroundTask

from app import config
from app.downloads.storage import safe_filename
from app.frames import video_blur
from app.frames.registry import VideoSession, registry
from app.frames.uploads import AspectRatio, FitMode

logger = logging.getLogger("media_studio.frames.video")
router = APIRouter(prefix="/api/frames/videos", tags=["Frames"])

_EXPORT_SEMAPHORE = asyncio.Semaphore(2)
_busy_lock = threading.Lock()
_busy_sessions: Set[str] = set()


def _acquire_session_lock(video_id: str) -> None:
    with _busy_lock:
        if video_id in _busy_sessions:
            raise HTTPException(
                status_code=409,
                detail="Já existe um rastreamento ou exportação em andamento para este vídeo.",
            )
        _busy_sessions.add(video_id)


def _release_session_lock(video_id: str) -> None:
    with _busy_lock:
        _busy_sessions.discard(video_id)


def _session_or_404(video_id: str) -> VideoSession:
    session = registry.get(video_id)
    if not session:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado. Envie o arquivo novamente.")
    return session


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("Arquivo temporário ainda em uso ao limpar (%s): %s", path.name, exc)


def _check_finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"Campo '{name}' precisa ser um número finito.")
    return float(value)


class BlurBoxIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(..., ge=0.0, lt=1.0)
    y: float = Field(..., ge=0.0, lt=1.0)
    w: float = Field(..., ge=0.004, le=1.0)
    h: float = Field(..., ge=0.004, le=1.0)

    @field_validator("x", "y", "w", "h")
    @classmethod
    def validate_finite(cls, value: float, info) -> float:
        return _check_finite(value, info.field_name)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.x + self.w > 1.001 or self.y + self.h > 1.001:
            raise ValueError("A área marcada ultrapassa os limites da imagem.")
        self.w = min(self.w, 1.0 - self.x)
        self.h = min(self.h, 1.0 - self.y)
        return self


class BlurKeyframeIn(BlurBoxIn):
    t: float = Field(..., ge=0.0)
    visible: bool = True
    source: Literal["manual", "auto"] = "manual"
    confidence: float = Field(1.0, ge=0.0, le=1.0)

    @field_validator("t", "confidence")
    @classmethod
    def validate_kf_finite(cls, value: float, info) -> float:
        return _check_finite(value, info.field_name)


class BlurTrackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    label: str = Field("Placa", min_length=1, max_length=80)
    style: Literal["pixelate", "blur", "solid"] = "pixelate"
    strength: int = Field(16, ge=4, le=40)
    margin: float = Field(0.15, ge=0.0, le=0.5)
    keyframes: List[BlurKeyframeIn] = Field(..., min_length=1, max_length=3000)

    @field_validator("margin")
    @classmethod
    def validate_margin(cls, value: float) -> float:
        return _check_finite(value, "margin")


class TrackVideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_time: float = Field(..., ge=0.0)
    box: BlurBoxIn
    start_time: float = Field(0.0, ge=0.0)
    end_time: Optional[float] = Field(None, ge=0.0)
    direction: Literal["both", "forward", "backward"] = "both"

    @field_validator("anchor_time", "start_time")
    @classmethod
    def validate_times_finite(cls, value: float, info) -> float:
        return _check_finite(value, info.field_name)

    @field_validator("end_time")
    @classmethod
    def validate_end_finite(cls, value: Optional[float]) -> Optional[float]:
        if value is not None:
            return _check_finite(value, "end_time")
        return None


class ExportVideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tracks: List[BlurTrackIn] = Field(default_factory=list, max_length=config.MAX_BLUR_TRACKS)
    trim_start: float = Field(0.0, ge=0.0)
    trim_end: Optional[float] = Field(None, ge=0.0)
    mute_audio: bool = False
    apply_crop: bool = False
    aspect_ratio: AspectRatio = "original"
    focus_x: float = Field(0.5, ge=0.0, le=1.0)
    focus_y: float = Field(0.5, ge=0.0, le=1.0)
    zoom: float = Field(1.0, ge=1.0, le=4.0)
    standardize: bool = False
    fit_mode: FitMode = "crop"

    @field_validator("trim_start", "focus_x", "focus_y", "zoom")
    @classmethod
    def validate_export_finite(cls, value: float, info) -> float:
        return _check_finite(value, info.field_name)

    @field_validator("trim_end")
    @classmethod
    def validate_trim_end_finite(cls, value: Optional[float]) -> Optional[float]:
        if value is not None:
            return _check_finite(value, "trim_end")
        return None


@router.post("/{video_id}/track")
async def track_plate(video_id: str, payload: TrackVideoRequest):
    session = _session_or_404(video_id)
    if payload.anchor_time > session.duration + 0.25:
        raise HTTPException(status_code=422, detail="O tempo inicial da marcação passa da duração do vídeo.")
    if payload.start_time > session.duration + 0.1:
        raise HTTPException(status_code=422, detail="O início do intervalo passa da duração do vídeo.")

    end_time = payload.end_time
    if end_time is not None:
        if end_time <= payload.start_time + 0.02:
            raise HTTPException(status_code=422, detail="O fim do intervalo deve ser maior que o início.")
        if end_time > session.duration + 0.25:
            raise HTTPException(status_code=422, detail="O fim do intervalo passa da duração do vídeo.")
        end_time = min(end_time, session.duration)

    anchor_time = min(payload.anchor_time, session.duration)
    _acquire_session_lock(video_id)
    try:
        async with _EXPORT_SEMAPHORE:
            with session.hold():
                result = await asyncio.to_thread(
                    video_blur.track_region_in_video,
                    str(session.path),
                    session.rotation,
                    anchor_time,
                    payload.box.model_dump(),
                    payload.start_time,
                    end_time,
                    payload.direction,
                    lambda: session.closed,
                )
        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        _release_session_lock(video_id)


@router.post("/{video_id}/export-video")
async def export_video(video_id: str, payload: ExportVideoRequest):
    session = _session_or_404(video_id)
    if payload.trim_start >= max(0.05, session.duration):
        raise HTTPException(status_code=422, detail="O início do corte precisa ficar antes do fim do vídeo.")

    trim_end = payload.trim_end
    if trim_end is not None:
        if trim_end <= payload.trim_start + 0.05:
            raise HTTPException(status_code=422, detail="O corte final deve ficar pelo menos 0,05 s após o início.")
        if trim_end > session.duration + 0.25:
            raise HTTPException(status_code=422, detail="O corte final passa da duração do vídeo.")
        trim_end = min(trim_end, session.duration)

    normalized_tracks = []
    for track in payload.tracks:
        tdata = track.model_dump()
        tdata["keyframes"] = sorted(tdata["keyframes"], key=lambda k: k["t"])
        normalized_tracks.append(tdata)

    config.FRAMES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="ms_exp_", suffix=".mp4", dir=config.FRAMES_CACHE_DIR)
    os.close(fd)
    out_path = Path(temp_name)

    _acquire_session_lock(video_id)
    try:
        async with _EXPORT_SEMAPHORE:
            with session.hold():
                summary = await asyncio.to_thread(
                    video_blur.export_processed_video,
                    str(session.path),
                    str(out_path),
                    session.rotation,
                    normalized_tracks,
                    payload.trim_start,
                    trim_end,
                    payload.mute_audio,
                    payload.apply_crop,
                    payload.aspect_ratio,
                    payload.focus_x,
                    payload.focus_y,
                    payload.zoom,
                    payload.standardize,
                    payload.fit_mode,
                    lambda: session.closed,
                )
    except RuntimeError as exc:
        _safe_unlink(out_path)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        _safe_unlink(out_path)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _safe_unlink(out_path)
        logger.error("Falha ao exportar MP4 de %s: %s", session.filename, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Não foi possível exportar o vídeo editado.") from exc
    finally:
        _release_session_lock(video_id)

    stem = safe_filename(Path(session.filename).stem, "video_editado")
    download_name = f"{stem}_editado.mp4"
    headers = {
        "X-Export-Width": str(summary["width"]),
        "X-Export-Height": str(summary["height"]),
        "X-Export-Duration": str(summary["duration"]),
        "X-Export-Frames": str(summary["frames"]),
        "X-Export-Audio": str(summary["audio"]),
    }
    return FileResponse(
        path=out_path,
        media_type="video/mp4",
        filename=download_name,
        headers=headers,
        background=BackgroundTask(_safe_unlink, out_path),
    )
