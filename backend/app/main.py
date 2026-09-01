import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import LOGS_DIR, CORS_ORIGINS
from app.database import init_db
from app.services.queue_manager import queue_manager
from app.api.routes_health import router as health_router
from app.api.routes_info import router as info_router
from app.api.routes_download import router as download_router
from app.api.routes_history import router as history_router
from app.api.routes_ai import router as ai_router
from app.api.routes_settings import router as settings_router
from app.api.routes_profile import router as profile_router

# Configuração de Logging Persistente
log_file = LOGS_DIR / "backend.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("media_downloader.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida do servidor (inicialização e encerramento)."""
    logger.info("Iniciando MediaDownloader Pro API...")
    await init_db()
    await queue_manager.start()
    yield
    logger.info("Encerrando MediaDownloader Pro API...")
    await queue_manager.stop()

app = FastAPI(
    title="MediaDownloader Pro API",
    description="API assíncrona de alta performance para download e processamento de mídias online",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tratamento global de exceções
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Erro não tratado na rota {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "detail": "Ocorreu um erro interno no servidor.", "error": str(exc)}
    )

# Registrar Rotas
app.include_router(health_router)
app.include_router(info_router)
app.include_router(download_router)
app.include_router(history_router)
app.include_router(ai_router)
app.include_router(settings_router)
app.include_router(profile_router)

@app.get("/")
async def root():
    return {
        "message": "MediaDownloader Pro API Operante",
        "documentation": "/docs",
        "health": "/health"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8800, reload=True)
