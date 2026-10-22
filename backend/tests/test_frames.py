import time

import cv2
import numpy as np
import pytest

from app import config
from app.frames.registry import registry
from tests.conftest import LOCAL_HEADERS


@pytest.fixture(scope="module")
def sample_video(test_root):
    """Vídeo sintético de 2 s (320x180, 10 fps) gerado na hora."""
    path = test_root / "amostra.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 180))
    for index in range(20):
        frame = np.full((180, 320, 3), index * 12, dtype=np.uint8)
        cv2.putText(frame, str(index), (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 3, (255, 255, 255), 4)
        writer.write(frame)
    writer.release()
    return path


def _upload(client, path, name="amostra.mp4"):
    with path.open("rb") as handle:
        return client.post("/api/frames/videos", files={"file": (name, handle, "video/mp4")}, headers=LOCAL_HEADERS)


def test_fluxo_completo_do_extrator(client, sample_video):
    response = _upload(client, sample_video)
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["width"], data["height"]) == (320, 180)
    video_id = data["video_id"]

    preview = client.get(f"/api/frames/videos/{video_id}/preview", params={"time": 1.0})
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/jpeg"

    for fmt, mime in (("png", "image/png"), ("jpeg", "image/jpeg"), ("webp", "image/webp")):
        frame = client.get(f"/api/frames/videos/{video_id}/frame", params={"time": 0.5, "format": fmt})
        assert frame.status_code == 200
        assert frame.headers["content-type"] == mime

    square = client.get(f"/api/frames/videos/{video_id}/frame", params={"time": 0.5, "format": "png", "aspect_ratio": "1:1"})
    image = cv2.imdecode(np.frombuffer(square.content, np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[0] == image.shape[1] == 180

    burst = client.get(f"/api/frames/videos/{video_id}/burst",
                       params={"start": 0.2, "end": 1.5, "count": 4, "format": "jpeg"}).json()
    assert len(burst["frames"]) == 4
    assert all(f["mime"] == "image/jpeg" and f["data_url"].startswith("data:image/jpeg") for f in burst["frames"])

    samples = client.get(f"/api/frames/videos/{video_id}/samples", params={"count": 3}).json()
    assert 1 <= len(samples["samples"]) <= 3

    temp_file = registry.get(video_id).path
    assert client.delete(f"/api/frames/videos/{video_id}", headers=LOCAL_HEADERS).status_code == 200
    assert client.get(f"/api/frames/videos/{video_id}/preview").status_code == 404
    for _ in range(20):
        if not temp_file.exists():
            break
        time.sleep(0.1)
    assert not temp_file.exists()


def test_recusa_arquivo_que_nao_e_video(client, test_root):
    fake = test_root / "programa.exe"
    fake.write_bytes(b"MZ")
    assert _upload(client, fake, "programa.exe").status_code == 415


def test_recusa_video_corrompido(client, test_root):
    broken = test_root / "quebrado.mp4"
    broken.write_bytes(b"isto nao e um video")
    assert _upload(client, broken, "quebrado.mp4").status_code == 422


def test_parametros_fora_do_limite(client, sample_video):
    video_id = _upload(client, sample_video).json()["video_id"]
    assert client.get(f"/api/frames/videos/{video_id}/samples", params={"count": 500}).status_code == 422
    assert client.get(f"/api/frames/videos/{video_id}/frame", params={"format": "exe"}).status_code == 422
    assert client.get(f"/api/frames/videos/{video_id}/preview", params={"time": -1}).status_code == 422
    client.delete(f"/api/frames/videos/{video_id}", headers=LOCAL_HEADERS)


def test_sessoes_inativas_expiram(client, sample_video, monkeypatch):
    video_id = _upload(client, sample_video).json()["video_id"]
    session = registry.get(video_id)
    session.last_access -= config.FRAME_SESSION_TTL_SECONDS + 1
    assert registry.expire_idle() >= 1
    assert registry.get(video_id) is None


def test_limite_de_sessoes_simultaneas(client, sample_video, monkeypatch):
    monkeypatch.setattr(config, "MAX_FRAME_SESSIONS", 2)
    ids = [_upload(client, sample_video).json()["video_id"] for _ in range(3)]
    assert registry.get(ids[0]) is None
    assert registry.get(ids[2]) is not None
    for video_id in ids[1:]:
        client.delete(f"/api/frames/videos/{video_id}", headers=LOCAL_HEADERS)
