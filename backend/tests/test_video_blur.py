"""Testes unitários e de API para rastreamento de placa, corte e exportação MP4."""
from fractions import Fraction
import hashlib
import math
from pathlib import Path

import av
import cv2
import numpy as np
import pytest

from app import config
from app.frames import video_blur
from app.frames.registry import registry
from tests.conftest import LOCAL_HEADERS


def _draw_synthetic_plate(frame: np.ndarray, x: int, y: int, w: int, h: int) -> None:
    """Desenha uma 'placa' de alto contraste (fundo claro com faixas escuras internas)."""
    cv2.rectangle(frame, (x, y), (x + w, y + h), (242, 242, 245), -1)
    cv2.rectangle(frame, (x, y), (x + w, y + h), (35, 35, 45), 2)
    cv2.rectangle(frame, (x + 4, y + 4), (x + w - 4, y + 9), (30, 80, 190), -1)
    for bar_x in range(x + 8, x + w - 8, 9):
        cv2.line(frame, (bar_x, y + 12), (bar_x, y + h - 5), (25, 25, 25), 2)


def _create_plate_video(
    path: Path,
    *,
    width: int = 320,
    height: int = 240,
    fps: int = 15,
    total_frames: int = 30,
    vanish_after: int = 24,
    with_audio: bool = False,
    rotation: int = 0,
) -> Path:
    """Gera MP4 sintético via PyAV com retângulo de alto contraste em movimento e áudio opcional."""
    container = av.open(str(path), mode="w", format="mp4")
    vstream = container.add_stream("libx264", rate=fps)
    vstream.width = width
    vstream.height = height
    vstream.pix_fmt = "yuv420p"
    vstream.options = {"crf": "18", "preset": "ultrafast"}
    if rotation:
        vstream.metadata["rotate"] = str(rotation)

    astream = None
    if with_audio:
        astream = container.add_stream("aac", rate=44100, layout="mono")

    for i in range(total_frames):
        bg = np.full((height, width, 3), (45, 52, 60), dtype=np.uint8)
        # Fundo com listras suaves para validar preservação de nitidez fora da placa.
        cv2.rectangle(bg, (10, 14), (80, 44), (190, 90, 20), 2)
        if i < vanish_after:
            px = int(40 + i * 5)
            py = int(95 + round(math.sin(i * 0.2) * 12))
            _draw_synthetic_plate(bg, px, py, 68, 32)
        vf = av.VideoFrame.from_ndarray(bg, format="bgr24")
        for pkt in vstream.encode(vf):
            container.mux(pkt)

    for pkt in vstream.encode():
        container.mux(pkt)

    if astream is not None:
        sample_rate = 44100
        frame_size = astream.codec_context.frame_size or 1024
        total_samples = int(round((total_frames / fps) * sample_rate))
        pos = 0
        while pos < total_samples:
            chunk = min(frame_size, total_samples - pos)
            t_arr = (np.arange(chunk, dtype=np.float32) + pos) / sample_rate
            wave = (0.25 * np.sin(2.0 * np.pi * 440.0 * t_arr)).reshape(1, -1)
            af = av.AudioFrame.from_ndarray(wave, format="fltp", layout="mono")
            af.sample_rate = sample_rate
            af.pts = pos
            af.time_base = Fraction(1, sample_rate)
            pos += chunk
            for pkt in astream.encode(af):
                container.mux(pkt)
        for pkt in astream.encode():
            container.mux(pkt)

    container.close()
    return path


def _upload(client, path: Path) -> str:
    with path.open("rb") as handle:
        resp = client.post(
            "/api/frames/videos",
            files={"file": (path.name, handle, "video/mp4")},
            headers=LOCAL_HEADERS,
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["video_id"]


def test_interpolacao_nao_atravessa_lacuna_oculta():
    keyframes = [
        {"t": 0.0, "x": 0.1, "y": 0.2, "w": 0.2, "h": 0.1, "visible": True},
        {"t": 1.0, "x": 0.5, "y": 0.2, "w": 0.2, "h": 0.1, "visible": False},
        {"t": 2.0, "x": 0.6, "y": 0.4, "w": 0.2, "h": 0.1, "visible": True},
        {"t": 3.0, "x": 0.8, "y": 0.4, "w": 0.2, "h": 0.1, "visible": True},
    ]
    mid_visible = video_blur.resolve_box_at_time(keyframes, 0.5)
    assert mid_visible is not None and abs(mid_visible[0] - 0.1) < 1e-4

    inside_gap = video_blur.resolve_box_at_time(keyframes, 1.5)
    assert inside_gap is None

    reappeared = video_blur.resolve_box_at_time(keyframes, 2.5)
    assert reappeared is not None and abs(reappeared[0] - 0.7) < 1e-4


def test_rastreamento_acompanha_placa_em_movimento(client, tmp_path):
    video_path = _create_plate_video(tmp_path / "placa_mov.mp4", total_frames=30, vanish_after=24)
    video_id = _upload(client, video_path)
    try:
        # No quadro t=0.0, placa está em x=40..108 (0.125..0.3375), y=95..127 (0.395..0.529)
        resp = client.post(
            f"/api/frames/videos/{video_id}/track",
            json={
                "anchor_time": 0.0,
                "box": {"x": 0.125, "y": 0.395, "w": 0.2125, "h": 0.1333},
                "start_time": 0.0,
                "end_time": 2.0,
                "direction": "both",
            },
            headers=LOCAL_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["tracked_frames"] >= 20
        # Em torno de t=1.0s (frame 15), x esperado = (40 + 15*5)/320 = 115/320 = 0.359
        kf_mid = min(data["keyframes"], key=lambda k: abs(k["t"] - 1.0))
        assert kf_mid["visible"] is True
        assert abs(kf_mid["x"] - 0.359) <= 0.08
        # Nos últimos quadros após o desaparecimento, confiança cai ou desliga visibilidade
        assert data["keyframes"][-1]["visible"] is False or data["keyframes"][-1]["confidence"] < 0.5
    finally:
        client.delete(f"/api/frames/videos/{video_id}", headers=LOCAL_HEADERS)


@pytest.mark.parametrize("style", ["pixelate", "blur", "solid"])
def test_exportacao_aplica_desfoque_trim_e_preserva_original(client, tmp_path, style):
    video_path = _create_plate_video(tmp_path / f"export_{style}.mp4", total_frames=30, vanish_after=30)
    original_hash = hashlib.sha256(video_path.read_bytes()).hexdigest()
    video_id = _upload(client, video_path)
    try:
        resp = client.post(
            f"/api/frames/videos/{video_id}/export-video",
            json={
                "tracks": [{
                    "id": "p1",
                    "label": "Placa 1",
                    "style": style,
                    "strength": 18,
                    "margin": 0.15,
                    "keyframes": [
                        {"t": 0.0, "x": 0.125, "y": 0.395, "w": 0.2125, "h": 0.1333, "visible": True, "source": "manual", "confidence": 1.0},
                        {"t": 1.9, "x": 0.58, "y": 0.395, "w": 0.2125, "h": 0.1333, "visible": True, "source": "manual", "confidence": 1.0},
                    ],
                }],
                "trim_start": 0.4,
                "trim_end": 1.4,
                "mute_audio": False,
                "apply_crop": False,
            },
            headers=LOCAL_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "video/mp4"
        assert resp.headers["x-export-audio"] == "none"

        out_file = tmp_path / f"out_{style}.mp4"
        out_file.write_bytes(resp.content)

        with av.open(str(out_file)) as container:
            vstream = container.streams.video[0]
            assert vstream.width % 2 == 0 and vstream.height % 2 == 0
            assert vstream.codec_context.pix_fmt == "yuv420p"
            frames = [f.to_ndarray(format="bgr24") for f in container.decode(vstream)]
        assert 12 <= len(frames) <= 17

        # Confere queda acentuada de nitidez (variância do Laplaciano) dentro da ROI mascarada do 1º frame exportado
        # Em t=0.4s (frame 6), a caixa interpolada está em ~x=0.22..0.43 -> ~70..138 px.
        orig_cap = cv2.VideoCapture(str(video_path))
        orig_cap.set(cv2.CAP_PROP_POS_FRAMES, 6)
        _, orig_frame = orig_cap.read()
        orig_cap.release()
        orig_roi = cv2.cvtColor(orig_frame[90:132, 68:142], cv2.COLOR_BGR2GRAY)
        out_roi = cv2.cvtColor(frames[0][90:132, 68:142], cv2.COLOR_BGR2GRAY)
        orig_sharp = float(cv2.Laplacian(orig_roi, cv2.CV_64F).var())
        out_sharp = float(cv2.Laplacian(out_roi, cv2.CV_64F).var())
        assert out_sharp < orig_sharp * 0.25

        assert hashlib.sha256(video_path.read_bytes()).hexdigest() == original_hash
    finally:
        client.delete(f"/api/frames/videos/{video_id}", headers=LOCAL_HEADERS)


def test_exportacao_audio_preservado_e_silenciado(client, tmp_path):
    video_path = _create_plate_video(tmp_path / "com_audio.mp4", total_frames=30, with_audio=True)
    video_id = _upload(client, video_path)
    try:
        kept = client.post(
            f"/api/frames/videos/{video_id}/export-video",
            json={"tracks": [], "trim_start": 0.3, "trim_end": 1.3, "mute_audio": False},
            headers=LOCAL_HEADERS,
        )
        assert kept.status_code == 200, kept.text
        assert kept.headers["x-export-audio"] == "kept"
        kept_file = tmp_path / "kept.mp4"
        kept_file.write_bytes(kept.content)
        with av.open(str(kept_file)) as c:
            assert len(c.streams.video) == 1
            assert len(c.streams.audio) == 1
            vdur = float(c.streams.video[0].duration * c.streams.video[0].time_base)
            adur = float(c.streams.audio[0].duration * c.streams.audio[0].time_base)
            assert abs(vdur - adur) < 0.2

        muted = client.post(
            f"/api/frames/videos/{video_id}/export-video",
            json={"tracks": [], "trim_start": 0.0, "trim_end": 1.0, "mute_audio": True},
            headers=LOCAL_HEADERS,
        )
        assert muted.status_code == 200, muted.text
        assert muted.headers["x-export-audio"] == "muted"
        muted_file = tmp_path / "muted.mp4"
        muted_file.write_bytes(muted.content)
        with av.open(str(muted_file)) as c:
            assert len(c.streams.video) == 1
            assert len(c.streams.audio) == 0
    finally:
        client.delete(f"/api/frames/videos/{video_id}", headers=LOCAL_HEADERS)


def test_exportacao_recorte_4_5_contain_blur_e_rotacao(client, tmp_path):
    video_path = _create_plate_video(tmp_path / "rot90.mp4", width=320, height=240, total_frames=16, rotation=90)
    video_id = _upload(client, video_path)
    try:
        resp = client.post(
            f"/api/frames/videos/{video_id}/export-video",
            json={
                "tracks": [{
                    "id": "p1",
                    "label": "Placa 1",
                    "style": "solid",
                    "strength": 16,
                    "margin": 0.15,
                    "keyframes": [
                        {"t": 0.0, "x": 0.35, "y": 0.20, "w": 0.25, "h": 0.20, "visible": True, "source": "manual", "confidence": 1.0},
                    ],
                }],
                "apply_crop": True,
                "aspect_ratio": "4:5",
                "standardize": True,
                "fit_mode": "contain_blur",
            },
            headers=LOCAL_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["x-export-width"] == "1080"
        assert resp.headers["x-export-height"] == "1350"
        assert list(config.FRAMES_CACHE_DIR.glob("ms_exp_*.mp4")) == []
    finally:
        client.delete(f"/api/frames/videos/{video_id}", headers=LOCAL_HEADERS)


def test_seguranca_csrf_validacao_pydantic_e_hold_sessao(client, tmp_path):
    video_path = _create_plate_video(tmp_path / "sec.mp4", total_frames=15)
    video_id = _upload(client, video_path)
    try:
        # Sem cabeçalho X-Media-Studio -> 403
        no_csrf = client.post(
            f"/api/frames/videos/{video_id}/track",
            json={"anchor_time": 0.0, "box": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}},
        )
        assert no_csrf.status_code == 403

        # Campo extra -> 422 (extra="forbid")
        extra_field = client.post(
            f"/api/frames/videos/{video_id}/export-video",
            json={"tracks": [], "campo_proibido": True},
            headers=LOCAL_HEADERS,
        )
        assert extra_field.status_code == 422

        # Trim inválido -> 422
        bad_trim = client.post(
            f"/api/frames/videos/{video_id}/export-video",
            json={"tracks": [], "trim_start": 0.8, "trim_end": 0.5},
            headers=LOCAL_HEADERS,
        )
        assert bad_trim.status_code == 422

        # Vídeo inexistente -> 404
        missing = client.post(
            "/api/frames/videos/inexistente/export-video",
            json={"tracks": []},
            headers=LOCAL_HEADERS,
        )
        assert missing.status_code == 404

        # Sessão sob hold() não expira no expire_idle()
        session = registry.get(video_id)
        with session.hold():
            session.last_access -= config.FRAME_SESSION_TTL_SECONDS + 100
            assert registry.expire_idle() == 0
            assert registry.get(video_id) is not None
    finally:
        client.delete(f"/api/frames/videos/{video_id}", headers=LOCAL_HEADERS)
