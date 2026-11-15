"""Decodificação e preparo de fotos estáticas (JPG, PNG, WebP, HEIC/HEIF) com EXIF e sRGB."""
import io
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import cv2
import numpy as np
import pillow_heif
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

from app import config
from app.frames import engine

logger = logging.getLogger("media_studio.frames.image_engine")

STATIC_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
RAW_IMAGE_EXTENSIONS = {".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2"}

pillow_heif.register_heif_opener()
Image.MAX_IMAGE_PIXELS = config.MAX_IMAGE_PIXELS
_SRGB_PROFILE = ImageCms.createProfile("sRGB")


def _to_srgb_rgb(image: Image.Image) -> Tuple[Image.Image, str]:
    """Converte perfil ICC (como Display P3 de iPhone) e canal alfa para RGB em sRGB."""
    icc_bytes = image.info.get("icc_profile")
    profile_name = "srgb"

    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, rgba).convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")

    if icc_bytes:
        try:
            src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes))
            profile_desc = (ImageCms.getProfileDescription(src_profile) or "icc").strip()
            image = ImageCms.profileToProfile(image, src_profile, _SRGB_PROFILE, outputMode="RGB")
            profile_name = f"{profile_desc} -> sRGB"
        except Exception as exc:
            logger.warning("Perfil ICC ignorado na conversão para sRGB: %s", exc)
            profile_name = "icc_fallback_rgb"

    return image, profile_name


def load_image_bgr(source: Union[Path, str, bytes]) -> Tuple[np.ndarray, Dict]:
    """Carrega bytes/caminho (Unicode seguro no Windows), aplica EXIF e devolve array BGR + metadados."""
    Image.MAX_IMAGE_PIXELS = config.MAX_IMAGE_PIXELS
    if isinstance(source, (bytes, bytearray)):
        raw_bytes = bytes(source)
    else:
        path = Path(source)
        suffix = path.suffix.lower()
        if suffix in RAW_IMAGE_EXTENSIONS:
            raise ValueError(
                f"Arquivo RAW ({suffix}) não é suportado diretamente. Converta para JPG, PNG ou HEIC."
            )
        if not path.is_file():
            raise ValueError("Arquivo de imagem não encontrado.")
        raw_bytes = path.read_bytes()

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            raw_width, raw_height = img.size
            if raw_width * raw_height > config.MAX_IMAGE_PIXELS:
                raise ValueError("A imagem ultrapassa o limite máximo de pixels permitido.")
            orientation = int(img.getexif().get(274, 1) or 1)
            img.load()
            transposed = ImageOps.exif_transpose(img)
            rgb_img, color_profile = _to_srgb_rgb(transposed)
    except Image.DecompressionBombError as exc:
        raise ValueError("A imagem ultrapassa o limite seguro de pixels permitido.") from exc
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Não foi possível abrir a imagem. O arquivo pode estar corrompido ou incompatível.") from exc

    rgb_array = np.asarray(rgb_img)
    bgr_array = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
    height, width = bgr_array.shape[:2]
    return bgr_array, {
        "raw_width": raw_width,
        "raw_height": raw_height,
        "width": width,
        "height": height,
        "orientation": orientation,
        "orientation_applied": orientation != 1,
        "color_profile": color_profile,
    }


def encode_image_preview(bgr_image: np.ndarray, max_width: int = engine.IMAGE_PREVIEW_WIDTH, quality: int = 84) -> bytes:
    """Gera prévia JPEG leve para o navegador sem manter imagem de 50 MP em memória."""
    height, width = bgr_image.shape[:2]
    preview = engine.resize_to_width(bgr_image, min(width, max_width)) if width > max_width else bgr_image
    ok, buffer = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("Falha ao gerar prévia da imagem.")
    return buffer.tobytes()


def probe_image(path: Path) -> Dict:
    """Valida a foto, lê dimensões após EXIF e devolve prévia pronta para cache de sessão."""
    bgr, meta = load_image_bgr(path)
    meta["preview_bytes"] = encode_image_preview(bgr)
    return meta


def process_image(
    path: Path,
    fmt: str = "png",
    aspect_ratio: str = "4:5",
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    zoom: float = 1.0,
    standardize: bool = True,
    output_size: Optional[Tuple[int, int]] = None,
    fit_mode: str = "crop",
) -> Tuple[bytes, str, Dict]:
    """Aplica recorte com ponto focal/zoom, padronização de saída e codifica no formato pedido."""
    bgr, meta = load_image_bgr(path)
    target_size = engine.resolve_output_size(aspect_ratio, standardize=standardize, output_size=output_size)
    geometry = engine.analyze_crop_geometry(
        meta["width"],
        meta["height"],
        aspect_ratio,
        focus_x=focus_x,
        focus_y=focus_y,
        zoom=zoom,
        output_size=target_size,
        fit_mode=fit_mode,
    )
    processed = engine.apply_aspect_ratio_crop(
        bgr,
        aspect_ratio,
        focus_x=focus_x,
        focus_y=focus_y,
        zoom=zoom,
        output_size=target_size,
        fit_mode=fit_mode,
    )
    content, mime = engine.encode(processed, fmt)
    info = {**meta, **geometry}
    return content, mime, info
