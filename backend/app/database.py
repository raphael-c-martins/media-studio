import aiosqlite
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from app.config import DB_PATH

logger = logging.getLogger("media_downloader.database")

@asynccontextmanager
async def get_db_connection():
    """Context manager assíncrono para conexão segura com o SQLite em modo WAL."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA foreign_keys=ON;")
    try:
        yield db
    finally:
        await db.close()

async def init_db():
    """
    Inicializa o banco de dados executando migrações incrementais seguras.
    Nunca apaga ou reseta tabelas existentes.
    """
    async with get_db_connection() as db:
        # Tabela de Downloads e Histórico
        await db.execute("""
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
            );
        """)

        # Tabela de Configurações e Preferências
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # Tabela de Resumos e Análises de IA
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ai_summaries (
                id TEXT PRIMARY KEY,
                download_id TEXT,
                url TEXT NOT NULL,
                title TEXT,
                summary TEXT NOT NULL,
                key_points TEXT,
                transcript TEXT,
                model TEXT,
                created_at TEXT NOT NULL
            );
        """)

        # Configurações padrão iniciais (se não existirem)
        default_settings = [
            ("download_folder", str(DB_PATH.parent / "downloads")),
            ("default_format", "best"),
            ("default_audio_format", "mp3"),
            ("deepseek_api_key", ""),
            ("deepseek_model", "deepseek-chat"),
            ("auto_embed_thumbnail", "true"),
            ("auto_embed_subtitles", "true"),
            ("theme", "dark")
        ]

        for key, val in default_settings:
            await db.execute("""
                INSERT OR IGNORE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, val, datetime.utcnow().isoformat()))

        await db.commit()
        logger.info("Banco de dados SQLite inicializado com sucesso.")
