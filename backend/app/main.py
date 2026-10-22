import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.database import init_db, recover_interrupted_downloads
from app.downloads import routes_download, routes_history, routes_info, routes_profile, routes_settings
from app.downloads.queue_manager import queue_manager
from app.frames import routes as frames_routes
from app.frames.registry import clear_cache_dir, registry
from app.routes_health import router as health_router
from app.security import LocalAccessMiddleware

logger = logging.getLogger("media_studio.main")


def configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(h, "_media_studio", False) for h in root.handlers):
        return
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        config.LOGS_DIR / "media-studio.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    console_handler = logging.StreamHandler(sys.stdout)
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        handler._media_studio = True
        root.addHandler(handler)
    root.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.validate_runtime()
    config.ensure_dirs()
    configure_logging()
    logger.info("Iniciando Media Studio %s", config.APP_VERSION)

    await init_db()
    interrupted = await recover_interrupted_downloads()
    if interrupted:
        logger.info("Downloads interrompidos na última execução marcados como erro: %s", interrupted)
    removed = clear_cache_dir()
    if removed:
        logger.info("Vídeos temporários antigos removidos: %s", removed)

    await queue_manager.start()
    cleanup_task = asyncio.create_task(frames_routes.cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        await queue_manager.stop()
        registry.clear()
        logger.info("Media Studio encerrado.")


app = FastAPI(title="Media Studio", version=config.APP_VERSION, lifespan=lifespan)
app.add_middleware(LocalAccessMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    messages = []
    for error in exc.errors():
        text = str(error.get("msg", "Valor inválido")).removeprefix("Value error, ")
        messages.append(text)
    return JSONResponse(status_code=422, content={"detail": " ".join(messages) or "Dados inválidos."})


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception):
    logger.error("Erro não tratado em %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Erro interno no servidor. Veja logs/media-studio.log."})


app.include_router(health_router)
app.include_router(routes_info.router)
app.include_router(routes_download.router)
app.include_router(routes_history.router)
app.include_router(routes_settings.router)
app.include_router(routes_profile.router)
app.include_router(frames_routes.router)

app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
