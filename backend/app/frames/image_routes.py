"""Rotas da API para preparo, recorte por ponto focal e conversão de fotos estáticas."""
import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from app import config
from app.frames import engine, image_engine
from app.frames.registry import ImageSession, image_registry
from app.frames.uploads import AspectRatio, FitMode, ImageFormat, save_temp_upload

logger = logging.getLogger("media_studio.frames.images")
router = APIRouter(prefix="/api/frames/images", tags=["Frames"])

RAW_REJECT_DETAILS = {
    ext: f"Arquivos RAW ({ext}) não são suportados diretamente. Exporte para JPG, PNG ou HEIC."
    for ext in image_engine.RAW_IMAGE_EXTENSIONS
}


def _image_or_404(image_id: str) -> ImageSession:
    session = image_registry.get(image_id)
    if not session:
        raise HTTPException(status_code=404, detail="Imagem não encontrada. Envie o arquivo novamente.")
    return session


@router.post("")
async def upload_image(request: Request, file: UploadFile = File(...)):
    path = await save_temp_upload(
        file,
        request,
        image_engine.STATIC_IMAGE_EXTENSIONS,
        config.MAX_IMAGE_UPLOAD_BYTES,
        prefix="ms_img_",
        unsupported_detail="Formato não suportado. Use JPG, PNG, WebP, HEIC ou HEIF.",
        too_large_detail="A imagem passa do tamanho máximo permitido.",
        rejected_details=RAW_REJECT_DETAILS,
    )
    try:
        meta = await asyncio.to_thread(image_engine.probe_image, path)
    except ValueError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session = ImageSession(
        image_id=path.stem,
        path=path,
        filename=Path(file.filename or "foto").name,
        width=meta["width"],
        height=meta["height"],
        orientation=meta["orientation"],
        orientation_applied=meta["orientation_applied"],
        color_profile=meta["color_profile"],
        preview_bytes=meta["preview_bytes"],
    )
    image_registry.add(session)
    logger.info("Imagem carregada no estúdio: %s (%sx%s)", session.filename, session.width, session.height)
    return {
        "image_id": session.image_id,
        "filename": session.filename,
        "width": session.width,
        "height": session.height,
        "orientation": session.orientation,
        "orientation_applied": session.orientation_applied,
        "color_profile": session.color_profile,
    }


@router.delete("/{image_id}")
async def close_image(image_id: str):
    image_registry.remove(image_id)
    return {"success": True}


@router.get("/{image_id}/preview")
async def get_image_preview(image_id: str):
    session = _image_or_404(image_id)
    if not session.preview_bytes:
        raise HTTPException(status_code=404, detail="Prévia indisponível. Envie a imagem novamente.")
    return Response(content=session.preview_bytes, media_type="image/jpeg")


@router.get("/{image_id}/analyze")
async def analyze_image_crop(
    image_id: str,
    aspect_ratio: AspectRatio = "4:5",
    focus_x: float = Query(0.5, ge=0.0, le=1.0),
    focus_y: float = Query(0.5, ge=0.0, le=1.0),
    zoom: float = Query(1.0, ge=1.0, le=4.0),
    standardize: bool = True,
    fit_mode: FitMode = "crop",
):
    session = _image_or_404(image_id)
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


@router.get("/{image_id}/crop")
async def crop_image(
    image_id: str,
    format: ImageFormat = "png",
    aspect_ratio: AspectRatio = "4:5",
    focus_x: float = Query(0.5, ge=0.0, le=1.0),
    focus_y: float = Query(0.5, ge=0.0, le=1.0),
    zoom: float = Query(1.0, ge=1.0, le=4.0),
    standardize: bool = True,
    fit_mode: FitMode = "crop",
):
    session = _image_or_404(image_id)
    try:
        content, mime, info = await asyncio.to_thread(
            image_engine.process_image,
            session.path,
            format,
            aspect_ratio,
            focus_x,
            focus_y,
            zoom,
            standardize,
            None,
            fit_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    headers = {"X-Crop-Warnings": ",".join(info["warnings"])} if info.get("warnings") else {}
    return Response(content=content, media_type=mime, headers=headers)
