"""Configuração central do Media Studio.

Tudo que muda entre máquinas vem de variáveis de ambiente com prefixo MS_.
Nenhum segredo tem valor padrão: sem MS_ACCESS_TOKEN o servidor só aceita
conexões da própria máquina.
"""
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"

DATA_DIR = Path(os.getenv("MS_DATA_DIR", ROOT_DIR / "data"))
LOGS_DIR = Path(os.getenv("MS_LOGS_DIR", ROOT_DIR / "logs"))
DOWNLOADS_DIR = Path(os.getenv("MS_DOWNLOADS_DIR", ROOT_DIR / "downloads"))
TEMP_DIR = Path(os.getenv("MS_TEMP_DIR", ROOT_DIR / "temp"))
FRAMES_CACHE_DIR = TEMP_DIR / "frames"
DB_PATH = DATA_DIR / "media_studio.db"

APP_VERSION = "2.0.0"

HOST = os.getenv("MS_HOST", "127.0.0.1").strip()
PORT = int(os.getenv("MS_PORT", "8810"))

# Token exigido apenas quando o servidor escuta fora da própria máquina.
ACCESS_TOKEN = os.getenv("MS_ACCESS_TOKEN", "").strip()
MIN_TOKEN_LENGTH = 24
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MS_MAX_CONCURRENT_DOWNLOADS", "3"))

# Limites de tamanho (em bytes)
MAX_VIDEO_UPLOAD_BYTES = int(os.getenv("MS_MAX_UPLOAD_MB", "4096")) * 1024 * 1024
MAX_DIRECT_MEDIA_BYTES = int(os.getenv("MS_MAX_DIRECT_MEDIA_MB", "1024")) * 1024 * 1024
MAX_THUMBNAIL_BYTES = 15 * 1024 * 1024

# Sessões de vídeo do extrator de frames
FRAME_SESSION_TTL_SECONDS = int(os.getenv("MS_FRAME_SESSION_TTL_MIN", "30")) * 60
MAX_FRAME_SESSIONS = int(os.getenv("MS_MAX_FRAME_SESSIONS", "4"))


def is_loopback_host(host: str) -> bool:
    return host.strip("[]").lower() in LOOPBACK_HOSTS


def token_required() -> bool:
    return bool(ACCESS_TOKEN)


def validate_runtime() -> None:
    """Recusa iniciar em modo de rede sem um token forte."""
    if is_loopback_host(HOST):
        return
    if len(ACCESS_TOKEN) < MIN_TOKEN_LENGTH:
        raise RuntimeError(
            f"MS_HOST={HOST} expõe o servidor na rede. Defina MS_ACCESS_TOKEN com pelo menos "
            f"{MIN_TOKEN_LENGTH} caracteres ou use MS_HOST=127.0.0.1."
        )


def ensure_dirs() -> None:
    for folder in (DATA_DIR, LOGS_DIR, DOWNLOADS_DIR, FRAMES_CACHE_DIR):
        folder.mkdir(parents=True, exist_ok=True)
