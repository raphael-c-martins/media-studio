"""Testes unitários e de API para recorte por ponto focal, .HEIC, EXIF e segurança de imagens."""
import io

import cv2
import numpy as np
import pillow_heif
from PIL import Image

from app import config
from app.frames import engine, image_engine
from app.frames.registry import image_registry

pillow_heif.register_heif_opener()

HEADERS = {"Host": "127.0.0.1:8810", "X-Media-Studio": "1"}


def _quadrant_image_bgr() -> np.ndarray:
    """Cria imagem 2000x1000 com metades esquerda (azul) e direita (vermelha) distintas."""
    img = np.zeros((1000, 2000, 3), dtype=np.uint8)
    img[:, :1000] = (230, 40, 20)
    img[:, 1000:] = (20, 40, 230)
    img[700:, :] = (30, 220, 30)
    return img


def _encode_jpeg_bytes(rgb: np.ndarray, orientation: int = 1) -> bytes:
    pil_img = Image.fromarray(rgb, mode="RGB")
    exif = Image.Exif()
    exif[274] = orientation
    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", exif=exif.tobytes(), quality=95)
    return buf.getvalue()


def _encode_heic_bytes(width: int = 1600, height: int = 1200) -> bytes:
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[:, : width // 2] = (15, 90, 240)
    rgb[:, width // 2 :] = (240, 180, 15)
    heif_file = pillow_heif.from_pillow(Image.fromarray(rgb, mode="RGB"))
    buf = io.BytesIO()
    heif_file.save(buf, quality=85)
    return buf.getvalue()


def test_focal_crop_respects_left_right_bottom_and_standard_1080x1350():
    bgr = _quadrant_image_bgr()
    left_crop = engine.apply_aspect_ratio_crop(
        bgr, "4:5", focus_x=0.1, focus_y=0.25, zoom=1.0, output_size=(1080, 1350)
    )
    right_crop = engine.apply_aspect_ratio_crop(
        bgr, "4:5", focus_x=0.9, focus_y=0.25, zoom=1.0, output_size=(1080, 1350)
    )
    bottom_crop = engine.apply_aspect_ratio_crop(
        bgr, "4:5", focus_x=0.5, focus_y=0.95, zoom=2.0, output_size=(1080, 1350)
    )

    assert left_crop.shape == (1350, 1080, 3)
    assert right_crop.shape == (1350, 1080, 3)
    assert bottom_crop.shape == (1350, 1080, 3)
    # Metade esquerda mantém canal B alto no topo; metade direita mantém canal R alto no topo.
    assert left_crop[200, 540, 0] > left_crop[200, 540, 2]
    assert right_crop[200, 540, 2] > right_crop[200, 540, 0]
    # Zoom 2x no terço inferior mantém a faixa verde.
    assert bottom_crop[540, 540, 1] > bottom_crop[540, 540, 0]


def test_contain_blur_preserves_full_width_and_reports_geometry_warnings():
    bgr = _quadrant_image_bgr()
    contained = engine.apply_aspect_ratio_crop(
        bgr, "4:5", focus_x=0.5, focus_y=0.5, output_size=(1080, 1350), fit_mode="contain_blur"
    )
    assert contained.shape == (1350, 1080, 3)
    # Faixa central preservada inteira: esquerda continua azul e direita vermelha.
    assert contained[520, 40, 0] > contained[520, 40, 2]
    assert contained[520, 1040, 2] > contained[520, 1040, 0]

    panoramic = engine.analyze_crop_geometry(4000, 2000, "4:5", output_size=(1080, 1350), fit_mode="crop")
    assert "wide_crop" in panoramic["warnings"]
    assert "low_resolution" not in panoramic["warnings"]

    zoomed_small = engine.analyze_crop_geometry(1200, 900, "4:5", zoom=2.0, output_size=(1080, 1350))
    assert "low_resolution" in zoomed_small["warnings"]


def test_api_heic_upload_preview_analyze_crop_and_delete(client):
    heic_bytes = _encode_heic_bytes(1600, 1200)
    up = client.post(
        "/api/frames/images",
        headers=HEADERS,
        files={"file": ("flagra_itaboraí.heic", heic_bytes, "image/heic")},
    )
    assert up.status_code == 200
    payload = up.json()
    image_id = payload["image_id"]
    assert payload["width"] == 1600
    assert payload["height"] == 1200

    preview = client.get(f"/api/frames/images/{image_id}/preview", headers=HEADERS)
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"

    analyze = client.get(
        f"/api/frames/images/{image_id}/analyze",
        headers=HEADERS,
        params={"aspect_ratio": "4:5", "zoom": 2.0, "standardize": "true"},
    )
    assert analyze.status_code == 200
    assert "low_resolution" in analyze.json()["warnings"]

    cropped = client.get(
        f"/api/frames/images/{image_id}/crop",
        headers=HEADERS,
        params={"format": "png", "aspect_ratio": "4:5", "focus_x": 0.2, "zoom": 2.0, "standardize": "true"},
    )
    assert cropped.status_code == 200
    assert cropped.headers["content-type"] == "image/png"
    assert "low_resolution" in cropped.headers.get("x-crop-warnings", "")
    decoded = cv2.imdecode(np.frombuffer(cropped.content, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (1350, 1080, 3)

    deleted = client.delete(f"/api/frames/images/{image_id}", headers=HEADERS)
    assert deleted.status_code == 200
    assert image_registry.get(image_id) is None


def test_exif_orientation_and_alpha_png_are_normalized(client, test_root):
    rgb = np.zeros((1000, 2000, 3), dtype=np.uint8)
    rgb[:, :1000] = (200, 20, 20)
    jpeg_rot = _encode_jpeg_bytes(rgb, orientation=6)

    up = client.post(
        "/api/frames/images",
        headers=HEADERS,
        files={"file": ("foto_vertical_celular.jpg", jpeg_rot, "image/jpeg")},
    )
    assert up.status_code == 200
    data = up.json()
    assert data["orientation"] == 6
    assert data["orientation_applied"] is True
    assert data["width"] == 1000
    assert data["height"] == 2000
    client.delete(f"/api/frames/images/{data['image_id']}", headers=HEADERS)

    # PNG com transparência e nome acentuado via disco (Windows Unicode safe)
    rgba_path = test_root / "Coração_Ação_RGBA.png"
    rgba_img = Image.new("RGBA", (1200, 1500), (10, 20, 30, 128))
    rgba_img.save(rgba_path, format="PNG")
    content, mime, info = image_engine.process_image(rgba_path, fmt="png", aspect_ratio="4:5", standardize=True)
    assert mime == "image/png"
    assert info["out_width"] == 1080 and info["out_height"] == 1350
    assert len(content) > 0


def test_security_dng_rejected_pixel_bomb_csrf_and_session_eviction(client, monkeypatch):
    # CSRF obrigatório no POST de imagem
    no_csrf = client.post(
        "/api/frames/images",
        headers={"Host": "127.0.0.1:8810"},
        files={"file": ("foto.heic", b"fake", "image/heic")},
    )
    assert no_csrf.status_code == 403

    # .DNG recusado com mensagem clara (415)
    raw_resp = client.post(
        "/api/frames/images",
        headers=HEADERS,
        files={"file": ("raw_camera.dng", b"II*\x00", "image/x-adobe-dng")},
    )
    assert raw_resp.status_code == 415
    assert "RAW (.dng)" in raw_resp.json()["detail"]

    # Proteção contra bomba de descompressão / limite de pixels
    monkeypatch.setattr(config, "MAX_IMAGE_PIXELS", 10_000)
    big_jpeg = _encode_jpeg_bytes(np.zeros((200, 200, 3), dtype=np.uint8))
    bomb_resp = client.post(
        "/api/frames/images",
        headers=HEADERS,
        files={"file": ("gigante.jpg", big_jpeg, "image/jpeg")},
    )
    assert bomb_resp.status_code == 422
    assert "limite" in bomb_resp.json()["detail"].lower()

    # Evicção de sessões simultâneas de imagem
    monkeypatch.setattr(config, "MAX_IMAGE_PIXELS", 120_000_000)
    monkeypatch.setattr(config, "MAX_IMAGE_SESSIONS", 2)
    small_jpeg = _encode_jpeg_bytes(np.zeros((100, 125, 3), dtype=np.uint8))
    ids = [
        client.post(
            "/api/frames/images",
            headers=HEADERS,
            files={"file": (f"img_{i}.jpg", small_jpeg, "image/jpeg")},
        ).json()["image_id"]
        for i in range(3)
    ]
    assert image_registry.get(ids[0]) is None
    assert image_registry.get(ids[2]) is not None
    for iid in ids[1:]:
        client.delete(f"/api/frames/images/{iid}", headers=HEADERS)


def _write_sample_mp4(path, width: int = 640, height: int = 360) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 10.0, (width, height))
    try:
        for idx in range(5):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:, : width // 2] = (200, 50, 20 + idx * 10)
            frame[:, width // 2 :] = (20, 50, 200)
            writer.write(frame)
    finally:
        writer.release()


def test_video_routes_accept_focal_params_and_analyze(client, test_root):
    sample_video = test_root / "clip_focal.mp4"
    _write_sample_mp4(sample_video)
    up = client.post(
        "/api/frames/videos",
        headers=HEADERS,
        files={"file": ("clip.mp4", sample_video.read_bytes(), "video/mp4")},
    )
    assert up.status_code == 200
    video_id = up.json()["video_id"]

    analyze = client.get(
        f"/api/frames/videos/{video_id}/analyze",
        headers=HEADERS,
        params={"aspect_ratio": "4:5", "focus_x": 0.2, "zoom": 1.5, "standardize": "true"},
    )
    assert analyze.status_code == 200
    assert analyze.json()["out_width"] == 1080
    assert analyze.json()["out_height"] == 1350

    frame = client.get(
        f"/api/frames/videos/{video_id}/frame",
        headers=HEADERS,
        params={
            "time": 0.0,
            "format": "png",
            "aspect_ratio": "4:5",
            "focus_x": 0.2,
            "focus_y": 0.8,
            "zoom": 1.2,
            "standardize": "true",
        },
    )
    assert frame.status_code == 200
    decoded = cv2.imdecode(np.frombuffer(frame.content, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (1350, 1080, 3)

    client.delete(f"/api/frames/videos/{video_id}", headers=HEADERS)
