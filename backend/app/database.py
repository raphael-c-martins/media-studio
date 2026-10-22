"""Banco SQLite do Media Studio.

Regra do projeto: nada aqui apaga ou recria tabelas. Mudanças de estrutura
entram como migrations incrementais na lista MIGRATIONS, registradas na
tabela schema_migrations e aplicadas uma única vez.
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite

from app import config

logger = logging.getLogger("media_studio.database")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


@asynccontextmanager
async def get_db_connection():
    db = await aiosqlite.connect(config.DB_PATH, timeout=15)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA foreign_keys=ON;")
    try:
        yield db
    finally:
        await db.close()


MIGRATIONS = [
    (
        "001_tabelas_iniciais",
        [
            """
            CREATE TABLE IF NOT EXISTS downloads (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT,
                author TEXT,
                platform TEXT,
                format_id TEXT,
                format_note TEXT,
                media_type TEXT DEFAULT 'video',
                file_path TEXT,
                file_size INTEGER DEFAULT 0,
                duration INTEGER DEFAULT 0,
                thumbnail TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                progress REAL DEFAULT 0.0,
                speed TEXT,
                eta TEXT,
                time_range_start TEXT,
                time_range_end TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        ],
    ),
    (
        "002_indices_historico",
        [
            "CREATE INDEX IF NOT EXISTS idx_downloads_created_at ON downloads(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status)",
        ],
    ),
]

DEFAULT_SETTINGS = {
    "default_format": "best",
    "default_audio_format": "mp3",
    "theme": "system",
}


async def init_db() -> None:
    async with get_db_connection() as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        cursor = await db.execute("SELECT name FROM schema_migrations")
        applied = {row["name"] for row in await cursor.fetchall()}

        for name, statements in MIGRATIONS:
            if name in applied:
                continue
            for statement in statements:
                await db.execute(statement)
            await db.execute(
                "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)", (name, utc_now())
            )
            logger.info("Migration aplicada: %s", name)

        defaults = {**DEFAULT_SETTINGS, "download_folder": str(config.DOWNLOADS_DIR.resolve())}
        for key, value in defaults.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, utc_now()),
            )
        await db.commit()


async def recover_interrupted_downloads() -> int:
    """Downloads que estavam na fila quando o servidor parou não voltam sozinhos: marca como erro."""
    async with get_db_connection() as db:
        cursor = await db.execute(
            """
            UPDATE downloads
            SET status = 'error', error_message = 'Interrompido: o servidor foi reiniciado.', completed_at = ?
            WHERE status IN ('queued', 'downloading')
            """,
            (utc_now(),),
        )
        await db.commit()
        return cursor.rowcount or 0


async def get_setting(key: str, default: str = "") -> str:
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row and row["value"] else default
