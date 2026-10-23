import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import config
from app.downloads.models import DownloadRequest, SettingsUpdateRequest, parse_timestamp
from app.downloads.storage import StorageError, resolve_download_folder, safe_filename, unique_path


@pytest.mark.parametrize("text,expected", [
    ("10", 10.0), ("90.5", 90.5), ("01:30", 90.0), ("00:01:30", 90.0), ("1:02:03", 3723.0), ("00:00:10.250", 10.25),
])
def test_parse_timestamp(text, expected):
    assert parse_timestamp(text) == expected


@pytest.mark.parametrize("text", ["abc", "01:75", "1:2:3:4", "-5", "10s"])
def test_parse_timestamp_invalido(text):
    with pytest.raises(ValueError):
        parse_timestamp(text)


def test_trecho_com_fim_antes_do_inicio():
    with pytest.raises(ValidationError):
        DownloadRequest(url="https://youtube.com/watch?v=x", time_range_start="00:02:00", time_range_end="00:01:00")


def test_download_recusa_campos_desconhecidos_e_format_id_estranho():
    with pytest.raises(ValidationError):
        DownloadRequest(url="https://youtube.com/watch?v=x", campo_extra="x")
    with pytest.raises(ValidationError):
        DownloadRequest(url="https://youtube.com/watch?v=x", format_id="best; rm -rf")


def test_download_recusa_url_nao_http():
    with pytest.raises(ValidationError):
        DownloadRequest(url="file:///C:/Windows/win.ini")


def test_configuracoes_aceitam_somente_chaves_conhecidas():
    with pytest.raises(ValidationError):
        SettingsUpdateRequest(deepseek_api_key="x")
    with pytest.raises(ValidationError):
        SettingsUpdateRequest(theme="gold")


def test_pasta_do_sistema_e_recusada():
    system_root = os.environ.get("SystemRoot", r"C:\Windows") if os.name == "nt" else "/etc"
    with pytest.raises(StorageError):
        resolve_download_folder(system_root)
    appdata = os.environ.get("APPDATA")
    if appdata:
        startup = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        with pytest.raises(StorageError):
            resolve_download_folder(str(startup))


def test_raiz_do_disco_e_recusada():
    with pytest.raises(StorageError):
        resolve_download_folder(Path.cwd().anchor)


def test_pasta_vazia_usa_padrao():
    assert resolve_download_folder("") == config.DOWNLOADS_DIR.resolve()


def test_pasta_comum_e_aceita(test_root):
    target = test_root / "minhas-midias"
    assert resolve_download_folder(str(target)) == target.resolve()


def test_safe_filename():
    assert safe_filename('a<b>c:"d/e\\f|g?h*') == "abcdefgh"
    assert safe_filename("..") == "download"
    assert safe_filename("CON") == "download"


def test_unique_path_nao_sobrescreve(test_root):
    folder = test_root / "unique"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "video.mp4").write_bytes(b"1")
    assert unique_path(folder, "video", "mp4").name == "video (2).mp4"
