"""Helpers compartilhados para uploads temporários e parâmetros de recorte."""
import asyncio
import os
import tempfile
from pathlib import Path
from typing import Dict, Literal, Optional, Set

from fastapi import HTTPException, Request, UploadFile

from app import config

CHUNK_SIZE = 4 * 1024 * 1024

ImageFormat = Literal["png", "jpeg", "webp"]
AspectRatio = Literal["original", "16:9", "9:16", "1:1", "4:5"]
FitMode = Literal["crop", "contain_blur"]


async def save_temp_upload(
    file: UploadFile,
    request: Request,
    allowed_extensions: Set[str],
    max_bytes: int,
    *,
    prefix: str = "ms_",
    unsupported_detail: str = "Formato não suportado.",
    too_large_detail: str = "O arquivo passa do tamanho máximo permitido.",
    rejected_details: Optional[Dict[str, str]] = None,
) -> Path:
    """Salva o upload em blocos respeitando o teto de bytes e as extensões permitidas."""
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > max_bytes:
        raise HTTPException(status_code=413, detail=too_large_detail)

    suffix = Path(file.filename or "").suffix.lower()
    if rejected_details and suffix in rejected_details:
        raise HTTPException(status_code=415, detail=rejected_details[suffix])
    if suffix not in allowed_extensions:
        raise HTTPException(status_code=415, detail=unsupported_detail)

    config.FRAMES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=config.FRAMES_CACHE_DIR)
    os.close(fd)
    destination = Path(temp_name)
    total = 0
    try:
        with destination.open("wb") as handle:
            while chunk := await file.read(CHUNK_SIZE):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail=too_large_detail)
                await asyncio.to_thread(handle.write, chunk)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination
