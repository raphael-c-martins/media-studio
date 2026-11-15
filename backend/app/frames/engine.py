"""Decodificação de vídeo (OpenCV + PyAV). Funções síncronas: as rotas chamam via asyncio.to_thread."""
import base64
import logging
import math
from typing import Dict, List, Optional, Tuple

import av
import cv2
import numpy as np

logger = logging.getLogger("media_studio.frames.engine")

ASPECT_RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:5": 4 / 5}
STANDARD_OUTPUT_SIZES: Dict[str, Tuple[int, int]] = {
    "4:5": (1080, 1350),
    "1:1": (1080, 1080),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}
PREVIEW_WIDTH = 480
IMAGE_PREVIEW_WIDTH = 960
THUMB_WIDTH = 270
PREVIEW_STEP = 20  # chave do cache = round(tempo * 20), ou seja, um quadro a cada 0,05 s
MIN_FEED_WIDTH = 720
MIN_FEED_HEIGHT = 900
WIDE_CROP_KEEP_THRESHOLD = 0.55

IMAGE_FORMATS = {
    "png": (".png", "image/png", [cv2.IMWRITE_PNG_COMPRESSION, 3]),
    "jpeg": (".jpg", "image/jpeg", [cv2.IMWRITE_JPEG_QUALITY, 97]),
    "webp": (".webp", "image/webp", [cv2.IMWRITE_WEBP_QUALITY, 95]),
}


def preview_key(seconds: float) -> int:
    return int(round(seconds * PREVIEW_STEP))


def clamp_unit(value: float, default: float = 0.5) -> float:
    """Normaliza coordenadas de foco para o intervalo seguro [0.0, 1.0]."""
    if not math.isfinite(value):
        return default
    return max(0.0, min(1.0, float(value)))


def clamp_zoom(zoom: float) -> float:
    """Restringe o fator de zoom para o intervalo seguro [1.0, 4.0]."""
    if not math.isfinite(zoom):
        return 1.0
    return max(1.0, min(4.0, float(zoom)))


def resolve_output_size(
    aspect_ratio: str,
    standardize: bool = False,
    output_size: Optional[Tuple[int, int]] = None,
) -> Optional[Tuple[int, int]]:
    """Resolve a dimensão final de saída mantendo compatibilidade retroativa quando standardize=False."""
    if output_size is not None:
        return int(output_size[0]), int(output_size[1])
    if standardize and aspect_ratio in STANDARD_OUTPUT_SIZES:
        return STANDARD_OUTPUT_SIZES[aspect_ratio]
    return None


def resize_image(image: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    """Redimensiona usando INTER_AREA para redução e INTER_LANCZOS4 para ampliação."""
    height, width = image.shape[:2]
    if width == out_w and height == out_h:
        return image
    interpolation = cv2.INTER_AREA if (width >= out_w and height >= out_h) else cv2.INTER_LANCZOS4
    return cv2.resize(image, (out_w, out_h), interpolation=interpolation)


def compute_crop_box(
    width: int,
    height: int,
    aspect_ratio: str,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    zoom: float = 1.0,
) -> Tuple[int, int, int, int]:
    """Calcula a janela (x, y, crop_w, crop_h) centrada no ponto focal e limitada às bordas."""
    fx = clamp_unit(focus_x)
    fy = clamp_unit(focus_y)
    z = clamp_zoom(zoom)
    target = ASPECT_RATIOS.get(aspect_ratio) or (width / max(1, height))

    if width / max(1, height) > target:
        base_h = height
        base_w = min(width, max(1, int(height * target)))
    else:
        base_w = width
        base_h = min(height, max(1, int(width / target)))

    if z == 1.0:
        crop_w, crop_h = base_w, base_h
    else:
        crop_w = min(width, max(1, int(round(base_w / z))))
        crop_h = min(height, max(1, int(round(base_h / z))))

    cx = int(round(fx * width))
    cy = int(round(fy * height))
    x1 = max(0, min(width - crop_w, cx - crop_w // 2))
    y1 = max(0, min(height - crop_h, cy - crop_h // 2))
    return x1, y1, crop_w, crop_h


def analyze_crop_geometry(
    width: int,
    height: int,
    aspect_ratio: str,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    zoom: float = 1.0,
    output_size: Optional[Tuple[int, int]] = None,
    fit_mode: str = "crop",
) -> Dict:
    """Calcula métricas geométricas e alertas (recorte muito estreito ou baixa resolução)."""
    fx = clamp_unit(focus_x)
    fy = clamp_unit(focus_y)
    z = clamp_zoom(zoom)
    x1, y1, crop_w, crop_h = compute_crop_box(width, height, aspect_ratio, fx, fy, z)

    if fit_mode == "contain_blur" and output_size is None:
        target = ASPECT_RATIOS.get(aspect_ratio)
        if target:
            if width / max(1, height) >= target:
                out_w, out_h = width, max(1, int(round(width / target)))
            else:
                out_h, out_w = height, max(1, int(round(height * target)))
        else:
            out_w, out_h = width, height
    elif output_size is not None:
        out_w, out_h = int(output_size[0]), int(output_size[1])
    else:
        out_w, out_h = crop_w, crop_h

    width_kept = round(crop_w / max(1, width), 4)
    height_kept = round(crop_h / max(1, height), 4)
    warnings: List[str] = []
    if fit_mode == "crop":
        if aspect_ratio == "4:5" and width_kept < WIDE_CROP_KEEP_THRESHOLD:
            warnings.append("wide_crop")
        if (aspect_ratio == "4:5" or output_size is not None) and (
            crop_w < MIN_FEED_WIDTH or crop_h < MIN_FEED_HEIGHT
        ):
            warnings.append("low_resolution")
    elif output_size is not None and (width < MIN_FEED_WIDTH and height < MIN_FEED_HEIGHT):
        warnings.append("low_resolution")

    return {
        "src_width": width,
        "src_height": height,
        "x": x1,
        "y": y1,
        "crop_width": crop_w,
        "crop_height": crop_h,
        "out_width": out_w,
        "out_height": out_h,
        "focus_x": fx,
        "focus_y": fy,
        "zoom": z,
        "fit_mode": fit_mode,
        "width_kept_ratio": width_kept,
        "height_kept_ratio": height_kept,
        "warnings": warnings,
    }


def _render_contain_blur(
    image: np.ndarray,
    aspect_ratio: str,
    focus_x: float,
    focus_y: float,
    out_w: int,
    out_h: int,
) -> np.ndarray:
    """Encaixa a foto inteira sem corte sobre fundo desfocado na proporção de destino."""
    bg_crop = apply_aspect_ratio_crop(image, aspect_ratio, focus_x=focus_x, focus_y=focus_y, zoom=1.0, fit_mode="crop")
    bg = resize_image(bg_crop, out_w, out_h)
    ksize = max(31, (min(out_w, out_h) // 12) | 1)
    bg = cv2.GaussianBlur(bg, (ksize, ksize), 0)
    bg = cv2.convertScaleAbs(bg, alpha=0.68, beta=0)

    src_h, src_w = image.shape[:2]
    scale = min(out_w / max(1, src_w), out_h / max(1, src_h))
    fg_w = max(1, min(out_w, int(round(src_w * scale))))
    fg_h = max(1, min(out_h, int(round(src_h * scale))))
    fg = resize_image(image, fg_w, fg_h)

    x_off = (out_w - fg_w) // 2
    y_off = (out_h - fg_h) // 2
    bg[y_off:y_off + fg_h, x_off:x_off + fg_w] = fg
    return bg


def apply_aspect_ratio_crop(
    image: np.ndarray,
    aspect_ratio: str,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    zoom: float = 1.0,
    output_size: Optional[Tuple[int, int]] = None,
    fit_mode: str = "crop",
) -> np.ndarray:
    """Recorta ou encaixa a imagem na proporção alvo respeitando ponto focal, zoom e resolução final."""
    z = clamp_zoom(zoom)
    target = ASPECT_RATIOS.get(aspect_ratio)
    if not target and z == 1.0 and output_size is None:
        return image

    height, width = image.shape[:2]
    if fit_mode == "contain_blur" and target:
        geom = analyze_crop_geometry(
            width, height, aspect_ratio, focus_x, focus_y, z, output_size=output_size, fit_mode="contain_blur"
        )
        return _render_contain_blur(image, aspect_ratio, focus_x, focus_y, geom["out_width"], geom["out_height"])

    x1, y1, crop_w, crop_h = compute_crop_box(width, height, aspect_ratio, focus_x, focus_y, z)
    cropped = image[y1:y1 + crop_h, x1:x1 + crop_w]
    if output_size is not None:
        return resize_image(cropped, int(output_size[0]), int(output_size[1]))
    return cropped


def correct_orientation(image: np.ndarray, rotation: int) -> np.ndarray:
    if rotation == 90 and image.shape[0] < image.shape[1]:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if rotation == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if rotation == 270 and image.shape[0] < image.shape[1]:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def resize_to_width(image: np.ndarray, width: int) -> np.ndarray:
    height, current = image.shape[:2]
    return cv2.resize(image, (width, max(1, int(height * width / current))), interpolation=cv2.INTER_AREA)


def encode(image: np.ndarray, fmt: str) -> Tuple[bytes, str]:
    ext, mime, params = IMAGE_FORMATS.get(fmt, IMAGE_FORMATS["jpeg"])
    ok, buffer = cv2.imencode(ext, image, params)
    if not ok:
        raise ValueError("Falha ao codificar a imagem.")
    return buffer.tobytes(), mime


def encode_preview(image: np.ndarray, quality: int = 80) -> bytes:
    ok, buffer = cv2.imencode(".jpg", resize_to_width(image, PREVIEW_WIDTH), [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("Falha ao gerar a prévia.")
    return buffer.tobytes()


def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds % 1) * 1000)) % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def probe_video(path: str) -> Dict:
    """Lê metadados e o primeiro quadro (já como prévia)."""
    capture = cv2.VideoCapture(path)
    try:
        if not capture.isOpened():
            raise ValueError("Não foi possível abrir o vídeo. O arquivo pode estar corrompido.")
        capture.set(cv2.CAP_PROP_ORIENTATION_AUTO, 1)
        rotation = int(capture.get(cv2.CAP_PROP_ORIENTATION_META) or 0)
        raw_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        raw_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        ok, first_frame = capture.read()
    finally:
        capture.release()

    if raw_width <= 0 or raw_height <= 0:
        raise ValueError("O arquivo enviado não parece ser um vídeo válido.")
    width, height = (raw_height, raw_width) if rotation in (90, 270) and raw_width > raw_height else (raw_width, raw_height)
    first_preview = encode_preview(correct_orientation(first_frame, rotation), 85) if ok and first_frame is not None else None
    return {
        "rotation": rotation,
        "width": width,
        "height": height,
        "fps": round(fps, 2),
        "total_frames": total_frames,
        "duration": round(total_frames / fps, 3) if fps > 0 else 0.0,
        "first_preview": first_preview,
    }


def index_previews(path: str, rotation: int, cache: Dict[int, bytes], should_stop) -> None:
    """Preenche o cache de prévias (480 px) do vídeo inteiro para a navegação ficar instantânea."""
    with av.open(path) as container:
        stream = container.streams.video[0]
        time_base = float(stream.time_base)
        for frame in container.decode(stream):
            if should_stop():
                return
            seconds = float(frame.pts * time_base) if frame.pts is not None else 0.0
            key = preview_key(seconds)
            if key in cache:
                continue
            image = correct_orientation(frame.to_ndarray(format="bgr24"), rotation)
            cache[key] = encode_preview(image)


def _read_with_opencv(path: str, seconds: float) -> Optional[np.ndarray]:
    capture = cv2.VideoCapture(path)
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000.0)
        ok, frame = capture.read()
        return frame if ok and frame is not None else None
    finally:
        capture.release()


def read_frame(path: str, seconds: float) -> np.ndarray:
    """Quadro em resolução original mais próximo do tempo pedido (PyAV, com OpenCV como reserva)."""
    try:
        with av.open(path) as container:
            stream = container.streams.video[0]
            time_base = float(stream.time_base)
            container.seek(int(seconds / time_base), stream=stream)
            best, best_diff = None, float("inf")
            for frame in container.decode(stream):
                current = float(frame.pts * time_base) if frame.pts is not None else 0.0
                diff = abs(current - seconds)
                if diff < best_diff:
                    best, best_diff = frame, diff
                if current > seconds + 0.15:
                    break
            if best is not None:
                return best.to_ndarray(format="bgr24")
    except Exception as exc:
        logger.warning("PyAV falhou em %.3fs, usando OpenCV: %s", seconds, exc)
    frame = _read_with_opencv(path, seconds)
    if frame is None:
        raise ValueError("Não foi possível localizar esse quadro.")
    return frame


def read_preview_direct(path: str, seconds: float, rotation: int) -> bytes:
    frame = _read_with_opencv(path, seconds)
    if frame is None:
        raise ValueError("Não foi possível gerar a prévia.")
    return encode_preview(correct_orientation(frame, rotation))


def extract_frame(
    path: str,
    seconds: float,
    rotation: int,
    fmt: str,
    aspect_ratio: str,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    zoom: float = 1.0,
    standardize: bool = False,
    output_size: Optional[Tuple[int, int]] = None,
    fit_mode: str = "crop",
) -> Tuple[bytes, str]:
    image = correct_orientation(read_frame(path, seconds), rotation)
    target_size = resolve_output_size(aspect_ratio, standardize=standardize, output_size=output_size)
    cropped = apply_aspect_ratio_crop(
        image,
        aspect_ratio,
        focus_x=focus_x,
        focus_y=focus_y,
        zoom=zoom,
        output_size=target_size,
        fit_mode=fit_mode,
    )
    return encode(cropped, fmt)


def _data_url(content: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


def sample_keyframes(path: str, rotation: int, count: int) -> List[Dict]:
    """Miniaturas distribuídas pelo vídeo, usando só quadros-chave (rápido)."""
    keyframes: List[Tuple[float, np.ndarray]] = []
    with av.open(path) as container:
        stream = container.streams.video[0]
        stream.codec_context.skip_frame = "NONKEY"
        time_base = float(stream.time_base)
        for frame in container.decode(stream):
            seconds = float(frame.pts * time_base) if frame.pts is not None else 0.0
            image = correct_orientation(frame.to_ndarray(format="bgr24"), rotation)
            keyframes.append((seconds, resize_to_width(image, THUMB_WIDTH)))

    if len(keyframes) > count:
        step = len(keyframes) / count
        keyframes = [keyframes[int(i * step)] for i in range(count)]

    samples = []
    for seconds, thumb in keyframes:
        content, mime = encode(thumb, "jpeg")
        samples.append({"time": round(seconds, 3), "time_label": format_timestamp(seconds),
                        "data_url": _data_url(content, mime)})
    return samples


def extract_burst(
    path: str,
    rotation: int,
    start: float,
    end: float,
    count: int,
    fmt: str,
    aspect_ratio: str,
    focus_x: float = 0.5,
    focus_y: float = 0.5,
    zoom: float = 1.0,
    standardize: bool = False,
    output_size: Optional[Tuple[int, int]] = None,
    fit_mode: str = "crop",
) -> List[Dict]:
    timestamps = [start + i * (end - start) / (count - 1) for i in range(count)]
    target_size = resolve_output_size(aspect_ratio, standardize=standardize, output_size=output_size)
    frames = []
    for seconds in timestamps:
        frame = _read_with_opencv(path, seconds)
        if frame is None:
            logger.warning("Quadro do burst indisponível em %.3fs", seconds)
            continue
        image = apply_aspect_ratio_crop(
            correct_orientation(frame, rotation),
            aspect_ratio,
            focus_x=focus_x,
            focus_y=focus_y,
            zoom=zoom,
            output_size=target_size,
            fit_mode=fit_mode,
        )
        content, mime = encode(image, fmt)
        height, width = image.shape[:2]
        frames.append({"time": round(seconds, 3), "time_label": format_timestamp(seconds),
                       "data_url": _data_url(content, mime), "mime": mime, "width": width, "height": height})
    return frames
