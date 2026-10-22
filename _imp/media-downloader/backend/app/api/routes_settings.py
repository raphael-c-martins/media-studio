import asyncio
import subprocess
import logging
from datetime import datetime
from typing import Dict
from pathlib import Path
from fastapi import APIRouter, HTTPException

from app.config import BASE_DIR
from app.database import get_db_connection
from app.models import SettingsUpdateRequest

logger = logging.getLogger("media_downloader.api.settings")
router = APIRouter(prefix="/api/settings", tags=["Settings"])

@router.get("", response_model=Dict[str, str])
async def get_settings():
    """Retorna todas as configurações persistidas no banco."""
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT key, value FROM settings")
        rows = await cursor.fetchall()
        return {r["key"]: r["value"] for r in rows}

@router.put("", response_model=dict)
async def update_settings(payload: SettingsUpdateRequest):
    """Atualiza configurações de forma incremental e segura."""
    async with get_db_connection() as db:
        now = datetime.utcnow().isoformat()
        for k, v in payload.settings.items():
            # Validar pasta de download se fornecida
            if k == "download_folder" and v:
                p = Path(v)
                if not p.is_absolute():
                    p = (BASE_DIR / p).resolve()
                else:
                    p = p.resolve()
                p.mkdir(parents=True, exist_ok=True)
                v = str(p)

            await db.execute("""
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """, (k, v, now))
        await db.commit()

    return {"success": True, "message": "Configurações atualizadas com sucesso."}

@router.post("/choose-folder", response_model=dict)
async def choose_folder_dialog():
    """Abre o diálogo nativo do Windows para selecionar uma pasta de destino de forma assíncrona (não-bloqueante)."""
    def _pick():
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$f.Description = 'Selecione a pasta para salvar os downloads'; "
            "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=45
        )
        return res.stdout.strip()

    try:
        selected_path = await asyncio.to_thread(_pick)
        if selected_path:
            return {"success": True, "path": selected_path}
        return {"success": False, "message": "Nenhuma pasta selecionada."}
    except Exception as e:
        logger.error(f"Erro ao abrir diálogo de seleção de pasta: {e}")
        return {"success": False, "error": str(e)}

