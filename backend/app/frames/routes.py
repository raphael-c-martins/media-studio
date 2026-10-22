import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import Response

from app import config
from app.frames import engine
from app.frames.registry import VideoSession, registry

logger = logging.getLogger("media_studio.frames")
router = APIRouter(prefix="/api/frames", tags=["Frames"])

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".ogg"}
ImageFormat = Literal["png", "jpeg", "webp"]
AspectRatio = Literal["original", "16:9", "9:16", "1:1", "4:5"]
CHUNK_SIZE = 4 * 1024 * 1024


def _session_or_404(video_id: str) -> VideoSession:
    session = registry.get(video_id)
    if not session:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado. Envie o arquivo novamente.")
    return session


def _index_in_background(session: VideoSession) -> None:
    try:
        engine.index_previews(str(session.path), session.rotation, session.preview_cache, lambda: session.closed)
        session.is_indexed = not session.closed
    except Exception as exc:
        logger.warning("Indexação de prévias falhou para %s: %s", session.filename, exc)


async def _save_upload(file: UploadFile, request: Request) -> Path:
    declared = int(request.headers.get("content-length") or 0)
    if declared > config.MAX_VIDEO_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="O vídeo passa do tamanho máximo permitido.")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Formato não suportado. Use MP4, MOV, MKV, WebM, M4V ou AVI.")

    fd, temp_name = tempfile.mkstemp(prefix="ms_", suffix=suffix, dir=config.FRAMES_CACHE_DIR)
    os.close(fd)
    destination = Path(temp_name)
    total = 0
    try:
        with destination.open("wb") as handle:
            while chunk := await file.read(CHUNK_SIZE):
                total += len(chunk)
                if total > config.MAX_VIDEO_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="O vídeo passa do tamanho máximo permitido.")
                await asyncio.to_thread(handle.write, chunk)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


@router.post("/videos")
async def upload_video(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    path = await _save_upload(file, request)
    try:
        meta = await asyncio.to_thread(engine.probe_video, str(path))
    except ValueError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session = VideoSession(
        video_id=path.stem, path=path, filename=Path(file.filename or "video").name,
        rotation=meta["rotation"], width=meta["width"], height=meta["height"], fps=meta["fps"],
        duration=meta["duration"], total_frames=meta["total_frames"],
    )
    if meta["first_preview"]:
        session.preview_cache[0] = meta["first_preview"]
    registry.add(session)
    background_tasks.add_task(_index_in_background, session)
    logger.info("Vídeo carregado no extrator: %s (%sx%s)", session.filename, session.width, session.height)

    return {
        "video_id": session.video_id, "filename": session.filename, "width": session.width,
        "height": session.height, "fps": session.fps, "total_frames": session.total_frames,
        "duration": session.duration,
    }


@router.delete("/videos/{video_id}")
async def close_video(video_id: str):
    registry.remove(video_id)
    return {"success": True}


@router.get("/videos/{video_id}/preview")
async def get_preview(video_id: str, time: float = Query(0.0, ge=0)):
    session = _session_or_404(video_id)
    key = engine.preview_key(min(time, session.duration))
    cache = session.preview_cache
    if key in cache:
        return Response(content=cache[key], media_type="image/jpeg")
    if cache:
        nearest = min(list(cache.keys()), key=lambda k: abs(k - key))
        if abs(nearest - key) <= engine.PREVIEW_STEP or session.is_indexed:
            return Response(content=cache[nearest], media_type="image/jpeg")
    try:
        content = await asyncio.to_thread(engine.read_preview_direct, str(session.path), time, session.rotation)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(content=content, media_type="image/jpeg")


@router.get("/videos/{video_id}/frame")
async def get_frame(video_id: str, time: float = Query(0.0, ge=0), format: ImageFormat = "png",
                    aspect_ratio: AspectRatio = "original"):
    session = _session_or_404(video_id)
    try:
        content, mime = await asyncio.to_thread(
            engine.extract_frame, str(session.path), min(time, session.duration), session.rotation, format, aspect_ratio
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(content=content, media_type=mime)


@router.get("/videos/{video_id}/samples")
async def get_samples(video_id: str, count: int = Query(12, ge=1, le=48)):
    session = _session_or_404(video_id)
    try:
        samples = await asyncio.to_thread(engine.sample_keyframes, str(session.path), session.rotation, count)
    except Exception as exc:
        logger.warning("Amostragem falhou para %s: %s", session.filename, exc)
        raise HTTPException(status_code=500, detail="Não foi possível gerar as sugestões.") from exc
    return {"samples": samples}


@router.get("/videos/{video_id}/burst")
async def get_burst(video_id: str, start: float = Query(0.0, ge=0), end: float = Query(0.0, ge=0),
                    count: int = Query(6, ge=2, le=30), format: ImageFormat = "jpeg",
                    aspect_ratio: AspectRatio = "original"):
    session = _session_or_404(video_id)
    end = session.duration if end <= start or end > session.duration else end
    start = min(start, end)
    frames = await asyncio.to_thread(
        engine.extract_burst, str(session.path), session.rotation, start, end, count, format, aspect_ratio
    )
    return {"frames": frames}


async def cleanup_loop(interval_seconds: int = 300) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        expired = registry.expire_idle()
        if expired:
            logger.info("Sessões de vídeo encerradas por inatividade: %s", expired)
