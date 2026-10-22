"""Decodificação de vídeo (OpenCV + PyAV). Funções síncronas: as rotas chamam via asyncio.to_thread."""
import base64
import logging
from typing import Dict, List, Optional, Tuple

import av
import cv2
import numpy as np

logger = logging.getLogger("media_studio.frames.engine")

ASPECT_RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:5": 4 / 5}
PREVIEW_WIDTH = 480
THUMB_WIDTH = 270
PREVIEW_STEP = 20  # chave do cache = round(tempo * 20), ou seja, um quadro a cada 0,05 s

IMAGE_FORMATS = {
    "png": (".png", "image/png", [cv2.IMWRITE_PNG_COMPRESSION, 3]),
    "jpeg": (".jpg", "image/jpeg", [cv2.IMWRITE_JPEG_QUALITY, 97]),
    "webp": (".webp", "image/webp", [cv2.IMWRITE_WEBP_QUALITY, 95]),
}


def preview_key(seconds: float) -> int:
    return int(round(seconds * PREVIEW_STEP))


def apply_aspect_ratio_crop(image: np.ndarray, aspect_ratio: str) -> np.ndarray:
    target = ASPECT_RATIOS.get(aspect_ratio)
    if not target:
        return image
    height, width = image.shape[:2]
    if width / height > target:
        new_width = int(height * target)
        start = (width - new_width) // 2
        return image[:, start:start + new_width]
    new_height = int(width / target)
    start = (height - new_height) // 2
    return image[start:start + new_height, :]


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


def extract_frame(path: str, seconds: float, rotation: int, fmt: str, aspect_ratio: str) -> Tuple[bytes, str]:
    image = correct_orientation(read_frame(path, seconds), rotation)
    return encode(apply_aspect_ratio_crop(image, aspect_ratio), fmt)


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


def extract_burst(path: str, rotation: int, start: float, end: float, count: int, fmt: str,
                  aspect_ratio: str) -> List[Dict]:
    timestamps = [start + i * (end - start) / (count - 1) for i in range(count)]
    frames = []
    for seconds in timestamps:
        frame = _read_with_opencv(path, seconds)
        if frame is None:
            logger.warning("Quadro do burst indisponível em %.3fs", seconds)
            continue
        image = apply_aspect_ratio_crop(correct_orientation(frame, rotation), aspect_ratio)
        content, mime = encode(image, fmt)
        height, width = image.shape[:2]
        frames.append({"time": round(seconds, 3), "time_label": format_timestamp(seconds),
                       "data_url": _data_url(content, mime), "mime": mime, "width": width, "height": height})
    return frames
