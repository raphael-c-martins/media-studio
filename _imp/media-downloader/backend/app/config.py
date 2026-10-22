import os
import sys
from pathlib import Path

# Raiz do projeto e diretório backend no sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = BASE_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

LOGS_DIR = BASE_DIR / "logs"
DOWNLOADS_DIR = BASE_DIR / "downloads"
DB_PATH = BASE_DIR / "media_downloader.db"

# Garantir existência dos diretórios críticos
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
(LOGS_DIR / "logs-cmd").mkdir(parents=True, exist_ok=True)

# Configurações do Servidor
PORT = int(os.getenv("PORT", 8800))
HOST = os.getenv("HOST", "0.0.0.0")

# CORS
CORS_ORIGINS = [
    "http://localhost:3030",
    "http://127.0.0.1:3030",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "*"
]

# Configurações do DeepSeek AI
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Limites de Concorrência
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3"))
