"""Regras de disco: pasta de destino, nomes de arquivo e tipos que o sistema pode abrir ou apagar."""
import os
import re
from pathlib import Path
from typing import Iterable

from app import config

MEDIA_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov", ".m4v",
    ".mp3", ".m4a", ".opus", ".ogg", ".wav", ".flac", ".aac",
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".zip",
}

_FORBIDDEN_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


# Pastas do sistema em Linux/macOS (o servidor também pode rodar fora do Windows, como no CI)
_POSIX_PROTECTED = ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc", "/root", "/sbin", "/sys", "/usr")


class StorageError(ValueError):
    pass


def _protected_dirs() -> Iterable[Path]:
    env = os.environ
    candidates = [
        env.get("SystemRoot"), env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), env.get("ProgramData"),
    ]
    appdata = env.get("APPDATA")
    if appdata:
        candidates.append(str(Path(appdata) / "Microsoft" / "Windows" / "Start Menu"))
    if os.name != "nt":
        candidates.extend(_POSIX_PROTECTED)
    for item in candidates:
        if item:
            yield Path(item).resolve()


def _is_within(child: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath([str(child), str(parent)]) == str(parent)
    except ValueError:
        return False


def resolve_download_folder(raw: str) -> Path:
    """Valida a pasta escolhida pelo usuário. Vazio significa a pasta padrão do projeto."""
    text = (raw or "").strip()
    if not text:
        return config.DOWNLOADS_DIR.resolve()
    folder = Path(text)
    if not folder.is_absolute():
        folder = config.ROOT_DIR / folder
    folder = folder.resolve()
    if folder == Path(folder.anchor):
        raise StorageError("Escolha uma pasta, não a raiz do disco.")
    for protected in _protected_dirs():
        if _is_within(folder, protected):
            raise StorageError("Essa pasta é do sistema e não pode receber downloads.")
    return folder


def safe_filename(name: str, fallback: str = "download", max_length: int = 150) -> str:
    clean = _FORBIDDEN_CHARS.sub("", name or "").strip().strip(".")
    clean = re.sub(r"\s+", " ", clean)[:max_length].strip()
    if not clean or clean.upper() in _RESERVED_NAMES:
        return fallback
    return clean


def unique_path(folder: Path, stem: str, ext: str) -> Path:
    """Evita sobrescrever arquivos existentes: acrescenta (2), (3)... ao nome."""
    ext = ext.lstrip(".")
    candidate = folder / f"{stem}.{ext}"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({counter}).{ext}"
        counter += 1
    return candidate


def is_allowed_media_file(path_value: str) -> bool:
    if not path_value:
        return False
    path = Path(path_value)
    return path.suffix.lower() in MEDIA_EXTENSIONS and path.is_file()
