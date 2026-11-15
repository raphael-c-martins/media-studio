"""Testes para o processamento em lote via CLI (app.frames.batch_cli)."""
import json
import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.frames import batch_cli


def _make_sample_jpg(path: Path, width: int = 2000, height: int = 1000, orientation: int = 1) -> Path:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, : width // 2] = (220, 30, 30)
    img[:, width // 2 :] = (30, 30, 220)
    pil_img = Image.fromarray(img, mode="RGB")
    exif = Image.Exif()
    exif[274] = orientation
    pil_img.save(path, format="JPEG", exif=exif.tobytes(), quality=95)
    return path


def _write_sample_mp4(path: Path, width: int = 640, height: int = 360) -> Path:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 10.0, (width, height))
    try:
        for _ in range(5):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:, : width // 2] = (210, 40, 20)
            frame[:, width // 2 :] = (20, 40, 210)
            writer.write(frame)
    finally:
        writer.release()
    return path


def test_batch_cli_manifest_processes_mixed_media_without_overwriting(test_root, capsys):
    originals = test_root / "# Originais"
    originals.mkdir(parents=True, exist_ok=True)
    foto1 = _make_sample_jpg(originals / "Frente_Corcel.jpg", 2000, 1000, orientation=6)
    foto2 = _make_sample_jpg(originals / "Traseira_Padrão.jpg", 1600, 1200, orientation=1)
    clip = _write_sample_mp4(originals / "Ronco.mp4")

    out_dir = test_root / "Post 236 - Teste"
    out_dir.mkdir()
    # Arquivo existente com mesmo índice: não deve ser sobrescrito (vira 1 (2).png).
    (out_dir / "1.png").write_bytes(b"preservar")

    manifest = test_root / "manifesto.json"
    manifest.write_text(
        json.dumps(
            {
                "post_dir": str(test_root),
                "output_dir": str(out_dir),
                "default_aspect_ratio": "4:5",
                "default_format": "png",
                "default_standardize": True,
                "items": [
                    {"index": 1, "kind": "image", "source": str(foto1), "focus_x": 0.5, "focus_y": 0.5},
                    {"index": 2, "kind": "image", "source": str(foto2), "focus_x": 0.2, "fit_mode": "contain_blur"},
                    {"index": 3, "kind": "video_frame", "source": str(clip), "time": 0.0, "zoom": 1.2},
                    {"index": 4, "kind": "video_copy", "source": str(clip)},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Primeiro dry-run não deve criar novos arquivos além do 1.png prévio
    code_dry = batch_cli.main(["--manifest", str(manifest), "--dry-run"])
    assert code_dry == 0
    assert (out_dir / "1.png").read_bytes() == b"preservar"
    assert not (out_dir / "1 (2).png").exists()

    # Execução real
    code = batch_cli.main(["--manifest", str(manifest)])
    assert code == 0
    out_text = capsys.readouterr().out
    assert "errors_count" in out_text

    assert (out_dir / "1.png").read_bytes() == b"preservar"
    assert (out_dir / "1 (2).png").is_file()
    assert (out_dir / "2.png").is_file()
    assert (out_dir / "3.png").is_file()
    assert (out_dir / "4.mp4").is_file()

    # Originais permanecem intactos
    assert foto1.is_file() and foto2.is_file() and clip.is_file()

    img1 = cv2.imread(str(out_dir / "1 (2).png"))
    img2 = cv2.imread(str(out_dir / "2.png"))
    img3 = cv2.imread(str(out_dir / "3.png"))
    assert img1.shape == (1350, 1080, 3)
    assert img2.shape == (1350, 1080, 3)
    assert img3.shape == (1350, 1080, 3)


def test_batch_cli_strict_warnings_and_system_folder_blocked(test_root, capsys):
    src_dir = test_root / "orig"
    src_dir.mkdir()
    _make_sample_jpg(src_dir / "panoramica.jpg", 2000, 800, orientation=1)
    out_dir = test_root / "saida"

    # --strict deve retornar 2 quando há wide_crop
    code_strict = batch_cli.main(
        ["--input-dir", str(src_dir), "--output-dir", str(out_dir), "--dry-run", "--strict"]
    )
    assert code_strict == 2
    capsys.readouterr()

    # Pasta do sistema deve ser rejeitada com código 1
    sys_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) if os.name == "nt" else Path("/etc")
    code_sys = batch_cli.main(
        ["--input-dir", str(src_dir), "--output-dir", str(sys_dir), "--dry-run"]
    )
    assert code_sys == 1
    assert "error" in capsys.readouterr().out.lower()


def test_batch_cli_reports_dng_error_without_aborting_batch(test_root, capsys):
    src_dir = test_root / "misto"
    src_dir.mkdir()
    (src_dir / "01_camera.dng").write_bytes(b"RAW")
    _make_sample_jpg(src_dir / "02_ok.jpg", 1200, 1500, orientation=1)
    out_dir = test_root / "saida_misto"

    code = batch_cli.main(["--input-dir", str(src_dir), "--output-dir", str(out_dir)])
    assert code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["errors_count"] == 1
    assert report["processed"] == 1
    assert (out_dir / "2.png").is_file()
