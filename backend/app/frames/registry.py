"""Sessões temporárias de vídeo e foto abertas no extrator/editor de frames.

Cada arquivo enviado vira um temporário em cache até ser fechado, expirar por
inatividade ou ser descartado pelo limite simultâneo de sessões.
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Generic, List, Optional, TypeVar

from app import config

logger = logging.getLogger("media_studio.frames.registry")


@dataclass
class VideoSession:
    video_id: str
    path: Path
    filename: str
    rotation: int
    width: int
    height: int
    fps: float
    duration: float
    total_frames: int
    preview_cache: Dict[int, bytes] = field(default_factory=dict)
    is_indexed: bool = False
    closed: bool = False
    last_access: float = field(default_factory=time.monotonic)

    @property
    def session_id(self) -> str:
        return self.video_id

    def touch(self) -> None:
        self.last_access = time.monotonic()

    def clear_memory(self) -> None:
        self.preview_cache.clear()


@dataclass
class ImageSession:
    image_id: str
    path: Path
    filename: str
    width: int
    height: int
    orientation: int
    orientation_applied: bool
    color_profile: str
    preview_bytes: bytes = b""
    closed: bool = False
    last_access: float = field(default_factory=time.monotonic)

    @property
    def session_id(self) -> str:
        return self.image_id

    def touch(self) -> None:
        self.last_access = time.monotonic()

    def clear_memory(self) -> None:
        self.preview_bytes = b""


SessionT = TypeVar("SessionT", VideoSession, ImageSession)


class SessionRegistry(Generic[SessionT]):
    def __init__(self, max_sessions: Optional[Callable[[], int]] = None):
        self._sessions: Dict[str, SessionT] = {}
        self._lock = threading.Lock()
        self._max_sessions = max_sessions or (lambda: config.MAX_FRAME_SESSIONS)

    def __len__(self) -> int:
        return len(self._sessions)

    def add(self, session: SessionT) -> List[SessionT]:
        """Registra a sessão e devolve as que foram removidas para respeitar o limite."""
        limit = max(1, int(self._max_sessions()))
        with self._lock:
            self._sessions[session.session_id] = session
            evicted = []
            while len(self._sessions) > limit:
                oldest = min(self._sessions.values(), key=lambda s: s.last_access)
                evicted.append(self._sessions.pop(oldest.session_id))
        for item in evicted:
            self._dispose(item)
        return evicted

    def get(self, session_id: str) -> Optional[SessionT]:
        session = self._sessions.get(session_id)
        if session:
            session.touch()
        return session

    def remove(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            self._dispose(session)
        return session is not None

    def expire_idle(self) -> int:
        limit = time.monotonic() - config.FRAME_SESSION_TTL_SECONDS
        with self._lock:
            expired = [s for s in self._sessions.values() if s.last_access < limit]
            for session in expired:
                self._sessions.pop(session.session_id, None)
        for session in expired:
            self._dispose(session)
        return len(expired)

    def clear(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            self._dispose(session)

    @staticmethod
    def _dispose(session: SessionT) -> None:
        session.closed = True
        session.clear_memory()
        try:
            session.path.unlink(missing_ok=True)
        except OSError as exc:
            # O Windows mantém o arquivo travado enquanto a indexação lê; a limpeza da inicialização resolve.
            logger.warning("Arquivo temporário ainda em uso (%s): %s", session.path.name, exc)


def clear_cache_dir() -> int:
    """Apaga sobras de arquivos temporários de execuções anteriores (só a pasta de cache do extrator)."""
    removed = 0
    if not config.FRAMES_CACHE_DIR.exists():
        return 0
    for item in config.FRAMES_CACHE_DIR.iterdir():
        if item.is_file() and item.name.startswith("ms_"):
            try:
                item.unlink()
                removed += 1
            except OSError:
                pass
    return removed


registry: SessionRegistry[VideoSession] = SessionRegistry(lambda: config.MAX_FRAME_SESSIONS)
image_registry: SessionRegistry[ImageSession] = SessionRegistry(lambda: config.MAX_IMAGE_SESSIONS)
