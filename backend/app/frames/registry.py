"""Sessões de vídeo abertas no extrator de frames.

Cada vídeo enviado vira um arquivo temporário e um cache de prévias em memória.
Sessões sem uso por mais que FRAME_SESSION_TTL_SECONDS são encerradas e o
arquivo temporário é apagado. Há também um limite de sessões simultâneas.
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

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

    def touch(self) -> None:
        self.last_access = time.monotonic()


class SessionRegistry:
    def __init__(self):
        self._sessions: Dict[str, VideoSession] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._sessions)

    def add(self, session: VideoSession) -> List[VideoSession]:
        """Registra a sessão e devolve as que foram removidas para respeitar o limite."""
        with self._lock:
            self._sessions[session.video_id] = session
            evicted = []
            while len(self._sessions) > config.MAX_FRAME_SESSIONS:
                oldest = min(self._sessions.values(), key=lambda s: s.last_access)
                evicted.append(self._sessions.pop(oldest.video_id))
        for item in evicted:
            self._dispose(item)
        return evicted

    def get(self, video_id: str) -> Optional[VideoSession]:
        session = self._sessions.get(video_id)
        if session:
            session.touch()
        return session

    def remove(self, video_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(video_id, None)
        if session:
            self._dispose(session)
        return session is not None

    def expire_idle(self) -> int:
        limit = time.monotonic() - config.FRAME_SESSION_TTL_SECONDS
        with self._lock:
            expired = [s for s in self._sessions.values() if s.last_access < limit]
            for session in expired:
                self._sessions.pop(session.video_id, None)
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
    def _dispose(session: VideoSession) -> None:
        session.closed = True
        session.preview_cache.clear()
        try:
            session.path.unlink(missing_ok=True)
        except OSError as exc:
            # O Windows mantém o arquivo travado enquanto a indexação lê; a limpeza da inicialização resolve.
            logger.warning("Arquivo temporário ainda em uso (%s): %s", session.path.name, exc)


def clear_cache_dir() -> int:
    """Apaga sobras de vídeos temporários de execuções anteriores (só a pasta de cache do extrator)."""
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


registry = SessionRegistry()
