"""Testes ponta a ponta (E2E) da interface web do Media Studio em Chromium headless."""
import re
from pathlib import Path

import cv2
import numpy as np
import pillow_heif
from PIL import Image
from playwright.sync_api import expect


def _write_wide_png(path: Path, width: int = 1920, height: int = 1080) -> Path:
    """Cria imagem 16:9 com sujeito deslocado à direita para validar recorte 4:5 e alerta wide_crop."""
    rgb = np.full((height, width, 3), (34, 34, 38), dtype=np.uint8)
    rgb[:, width // 2 :] = (232, 93, 4)
    Image.fromarray(rgb, mode="RGB").save(path, format="PNG")
    return path


def _write_heic(path: Path, width: int = 1600, height: int = 1200) -> Path:
    """Cria imagem .HEIC sintética para validar upload e conversão no fluxo real do navegador."""
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[:, : width // 2] = (25, 110, 220)
    rgb[:, width // 2 :] = (240, 175, 25)
    heif_file = pillow_heif.from_pillow(Image.fromarray(rgb, mode="RGB"))
    heif_file.save(path, quality=85)
    return path


def _write_video_mp4(path: Path, width: int = 320, height: int = 240, frames: int = 15) -> Path:
    """Cria vídeo .mp4 curto em pasta temporária."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (width, height))
    try:
        for index in range(frames):
            frame = np.full((height, width, 3), (index * 15) % 255, dtype=np.uint8)
            cv2.putText(frame, f"F{index}", (30, 140), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
            writer.write(frame)
    finally:
        writer.release()
    return path


def _assert_clean_telemetry(telemetry: dict) -> None:
    assert telemetry["console_errors"] == [], f"Erros de console JS: {telemetry['console_errors']}"
    assert telemetry["page_errors"] == [], f"Exceções JS não tratadas: {telemetry['page_errors']}"
    assert telemetry["http_errors"] == [], f"Respostas HTTP com erro: {telemetry['http_errors']}"


def _wait_preview_loaded(page, expected_src_pattern: str) -> None:
    frame_view = page.locator("#frame-view")
    expect(frame_view).to_have_attribute("src", re.compile(expected_src_pattern))
    page.wait_for_function(
        "() => { const img = document.getElementById('frame-view'); return Boolean(img && img.complete && img.naturalWidth > 0); }"
    )


def test_navegacao_inicial_sem_erros(page_with_telemetry):
    page, telemetry, base_url = page_with_telemetry
    page.goto(base_url, wait_until="networkidle")

    expect(page.locator("#h-download")).to_be_visible()
    for tab_hash, heading_id in (
        ("#historico", "#h-history"),
        ("#frames", "#h-frames"),
        ("#configuracoes", "#h-settings"),
        ("#baixar", "#h-download"),
    ):
        page.locator(f'.tab[href="{tab_hash}"]').click()
        expect(page.locator(heading_id)).to_be_visible()

    _assert_clean_telemetry(telemetry)


def test_fluxo_foto_larga_alerta_foco_e_contain_blur(page_with_telemetry, tmp_path):
    page, telemetry, base_url = page_with_telemetry
    wide_png = _write_wide_png(tmp_path / "larga_16_9.png")

    page.goto(f"{base_url}/#frames", wait_until="networkidle")
    page.locator("#video-file").set_input_files(str(wide_png))

    expect(page.locator("#frames-workspace")).to_be_visible()
    expect(page.locator("#meta-filename")).to_have_text("larga_16_9.png")
    expect(page.locator("#meta-resolution")).to_have_text("1920 x 1080")
    expect(page.locator("#btn-capture")).to_have_text("Exportar foto cortada")
    _wait_preview_loaded(page, r"/api/frames/images/.+/preview")

    expect(page.locator("#crop-guide")).to_be_visible()
    expect(page.locator("#crop-warning")).to_be_visible()
    expect(page.locator("#crop-warning")).to_contain_text("Foto larga para 4:5")

    # Clique fora da caixa central para deslocar o ponto focal pela interface
    frame_box = page.locator("#frame-view").bounding_box()
    assert frame_box is not None and frame_box["width"] > 0
    page.mouse.click(frame_box["x"] + frame_box["width"] * 0.9, frame_box["y"] + frame_box["height"] * 0.4)
    expect(page.locator("#focus-value")).not_to_have_text("Foco: 50%, 50%")

    # Ajuste de zoom atualiza indicador
    page.locator("#range-zoom").fill("1.5")
    expect(page.locator("#zoom-value")).to_have_text("1.50x")

    # Alternar para fundo desfocado remove guia de recorte e aviso de corte largo
    page.locator("#select-fit-mode").select_option("contain_blur")
    expect(page.locator("#crop-warning")).to_be_hidden()
    expect(page.locator("#crop-guide")).to_be_hidden()

    page.locator("#btn-capture").click()
    expect(page.locator("#gallery-count")).to_have_text("1")
    expect(page.locator("#gallery-grid .thumb")).to_have_count(1)
    expect(page.locator("#gallery-grid .thumb")).to_contain_text("1080x1350 PNG")

    _assert_clean_telemetry(telemetry)


def test_fluxo_heic_arrasto_modal_e_limpeza_galeria(page_with_telemetry, tmp_path):
    page, telemetry, base_url = page_with_telemetry
    heic_path = _write_heic(tmp_path / "carro_teste.heic")

    page.goto(f"{base_url}/#frames", wait_until="networkidle")
    page.locator("#video-file").set_input_files(str(heic_path))

    expect(page.locator("#meta-filename")).to_have_text("carro_teste.heic")
    expect(page.locator("#meta-resolution")).to_have_text("1600 x 1200")
    _wait_preview_loaded(page, r"/api/frames/images/.+/preview")
    expect(page.locator("#crop-guide")).to_be_visible()

    # Arrasta a guia laranja de recorte e verifica atualização do foco
    guide_box = page.locator("#crop-guide").bounding_box()
    assert guide_box is not None
    cx = guide_box["x"] + guide_box["width"] / 2
    cy = guide_box["y"] + guide_box["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx - 80, cy, steps=5)
    page.mouse.up()
    expect(page.locator("#focus-value")).not_to_have_text("Foco: 50%, 50%")

    page.locator("#btn-capture").click()
    expect(page.locator("#gallery-count")).to_have_text("1")
    expect(page.locator("#gallery-grid .thumb")).to_contain_text("1080x1350 PNG")

    # Abre modal ao clicar na miniatura e fecha com Escape
    page.locator("#gallery-grid .thumb img").click()
    expect(page.locator("#frame-modal")).to_be_visible()
    expect(page.locator("#frame-modal-info")).to_contain_text("1080 x 1350")
    page.keyboard.press("Escape")
    expect(page.locator("#frame-modal")).to_be_hidden()

    # Limpa a galeria aceitando a confirmação do navegador e valida estado vazio
    page.once("dialog", lambda dialog: dialog.accept())
    page.locator("#btn-gallery-clear").click()
    expect(page.locator("#gallery-count")).to_have_text("0")
    expect(page.locator("#gallery-empty")).to_be_visible()

    _assert_clean_telemetry(telemetry)


def test_fluxo_video_captura_sugestoes_e_troca_por_botao(page_with_telemetry, tmp_path):
    page, telemetry, base_url = page_with_telemetry
    video_path = _write_video_mp4(tmp_path / "amostra_e2e.mp4")
    second_img = _write_wide_png(tmp_path / "troca.png", width=1080, height=1350)

    page.goto(f"{base_url}/#frames", wait_until="networkidle")
    page.locator("#video-file").set_input_files(str(video_path))

    expect(page.locator("#meta-filename")).to_have_text("amostra_e2e.mp4")
    expect(page.locator("#timeline-box")).to_be_visible()
    expect(page.locator("#btn-capture")).to_have_text("Capturar quadro")
    _wait_preview_loaded(page, r"/api/frames/videos/.+/preview")

    page.locator("#btn-capture").click()
    expect(page.locator("#gallery-count")).to_have_text("1")

    page.locator("#select-sample-count").select_option("6")
    page.locator("#btn-samples").click()
    expect(page.locator("#samples-panel")).to_be_visible()
    expect(page.locator("#samples-grid .thumb")).not_to_have_count(0)

    # Troca de vídeo para imagem usando o seletor do botão "Trocar arquivo"
    with page.expect_file_chooser() as chooser_info:
        page.locator("#btn-change-video").click()
    chooser_info.value.set_files(str(second_img))

    expect(page.locator("#meta-filename")).to_have_text("troca.png")
    expect(page.locator("#timeline-box")).to_be_hidden()
    expect(page.locator("#samples-panel")).to_be_hidden()

    _assert_clean_telemetry(telemetry)


def test_extensao_raw_dng_exibe_toast_sem_erro_de_rede(page_with_telemetry, tmp_path):
    page, telemetry, base_url = page_with_telemetry
    fake_dng = tmp_path / "camera.dng"
    fake_dng.write_bytes(b"RAW-PLACEHOLDER")

    page.goto(f"{base_url}/#frames", wait_until="networkidle")
    page.locator("#video-file").set_input_files(str(fake_dng))

    toast_error = page.locator("#toasts .toast-error")
    expect(toast_error).to_be_visible()
    expect(toast_error).to_contain_text("RAW (.dng)")
    expect(page.locator("#frames-workspace")).to_be_hidden()

    _assert_clean_telemetry(telemetry)
