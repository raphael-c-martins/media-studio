import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from app import config
from app.frames import engine
from app.frames.registry import VideoSession, image_registry, registry
from app.frames.uploads import AspectRatio, FitMode, ImageFormat, save_temp_upload

logger = logging.getLogger("media_studio.frames")
router = APIRouter(prefix="/api/frames", tags=["Frames"])

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".ogg"}


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


@router.post("/videos")
async def upload_video(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    path = await save_temp_upload(
        file,
        request,
        VIDEO_EXTENSIONS,
        config.MAX_VIDEO_UPLOAD_BYTES,
        prefix="ms_",
        unsupported_detail="Formato não suportado. Use MP4, MOV, MKV, WebM, M4V ou AVI.",
        too_large_detail="O vídeo passa do tamanho máximo permitido.",
    )
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


@router.get("/videos/{video_id}/analyze")
async def analyze_video_crop(
    video_id: str,
    aspect_ratio: AspectRatio = "original",
    focus_x: float = Query(0.5, ge=0.0, le=1.0),
    focus_y: float = Query(0.5, ge=0.0, le=1.0),
    zoom: float = Query(1.0, ge=1.0, le=4.0),
    standardize: bool = False,
    fit_mode: FitMode = "crop",
):
    session = _session_or_404(video_id)
    output_size = engine.resolve_output_size(aspect_ratio, standardize=standardize)
    return engine.analyze_crop_geometry(
        session.width,
        session.height,
        aspect_ratio,
        focus_x=focus_x,
        focus_y=focus_y,
        zoom=zoom,
        output_size=output_size,
        fit_mode=fit_mode,
    )


@router.get("/videos/{video_id}/frame")
async def get_frame(
    video_id: str,
    time: float = Query(0.0, ge=0),
    format: ImageFormat = "png",
    aspect_ratio: AspectRatio = "original",
    focus_x: float = Query(0.5, ge=0.0, le=1.0),
    focus_y: float = Query(0.5, ge=0.0, le=1.0),
    zoom: float = Query(1.0, ge=1.0, le=4.0),
    standardize: bool = False,
    fit_mode: FitMode = "crop",
):
    session = _session_or_404(video_id)
    output_size = engine.resolve_output_size(aspect_ratio, standardize=standardize)
    geom = engine.analyze_crop_geometry(
        session.width,
        session.height,
        aspect_ratio,
        focus_x=focus_x,
        focus_y=focus_y,
        zoom=zoom,
        output_size=output_size,
        fit_mode=fit_mode,
    )
    try:
        content, mime = await asyncio.to_thread(
            engine.extract_frame,
            str(session.path),
            min(time, session.duration),
            session.rotation,
            format,
            aspect_ratio,
            focus_x,
            focus_y,
            zoom,
            standardize,
            output_size,
            fit_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    headers = {"X-Crop-Warnings": ",".join(geom["warnings"])} if geom["warnings"] else {}
    return Response(content=content, media_type=mime, headers=headers)


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
async def get_burst(
    video_id: str,
    start: float = Query(0.0, ge=0),
    end: float = Query(0.0, ge=0),
    count: int = Query(6, ge=2, le=30),
    format: ImageFormat = "jpeg",
    aspect_ratio: AspectRatio = "original",
    focus_x: float = Query(0.5, ge=0.0, le=1.0),
    focus_y: float = Query(0.5, ge=0.0, le=1.0),
    zoom: float = Query(1.0, ge=1.0, le=4.0),
    standardize: bool = False,
    fit_mode: FitMode = "crop",
):
    session = _session_or_404(video_id)
    end = session.duration if end <= start or end > session.duration else end
    start = min(start, end)
    frames = await asyncio.to_thread(
        engine.extract_burst,
        str(session.path),
        session.rotation,
        start,
        end,
        count,
        format,
        aspect_ratio,
        focus_x,
        focus_y,
        zoom,
        standardize,
        None,
        fit_mode,
    )
    return {"frames": frames}


async def cleanup_loop(interval_seconds: int = 300) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        expired_videos = registry.expire_idle()
        expired_images = image_registry.expire_idle()
        if expired_videos or expired_images:
            logger.info(
                "Sessões encerradas por inatividade: %s vídeo(s), %s imagem(ns)",
                expired_videos,
                expired_images,
            )
