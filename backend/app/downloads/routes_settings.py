import asyncio
import logging
import subprocess

from fastapi import APIRouter, HTTPException

from app.database import DEFAULT_SETTINGS, get_db_connection, utc_now
from app.downloads.models import SettingsResponse, SettingsUpdateRequest
from app.downloads.storage import StorageError, resolve_download_folder

logger = logging.getLogger("media_studio.api.settings")
router = APIRouter(prefix="/api/settings", tags=["Settings"])

PUBLIC_KEYS = ("download_folder", "default_format", "default_audio_format", "theme")


@router.get("", response_model=SettingsResponse)
async def get_settings():
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT key, value FROM settings WHERE key IN (?, ?, ?, ?)", PUBLIC_KEYS)
        stored = {row["key"]: row["value"] for row in await cursor.fetchall()}
    values = {**DEFAULT_SETTINGS, "download_folder": "", **stored}
    if values["theme"] not in ("system", "light", "dark"):
        values["theme"] = "system"
    return SettingsResponse(**{key: values[key] for key in PUBLIC_KEYS})


@router.put("", response_model=dict)
async def update_settings(payload: SettingsUpdateRequest):
    changes = payload.model_dump(exclude_none=True)
    if "download_folder" in changes:
        try:
            folder = resolve_download_folder(changes["download_folder"])
        except StorageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        folder.mkdir(parents=True, exist_ok=True)
        changes["download_folder"] = str(folder)

    async with get_db_connection() as db:
        for key, value in changes.items():
            await db.execute(
                """
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, utc_now()),
            )
        await db.commit()
    return {"success": True, "settings": changes}


@router.post("/choose-folder", response_model=dict)
async def choose_folder_dialog():
    """Abre a janela nativa do Windows para escolher a pasta de downloads."""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$f.Description = 'Pasta para salvar os downloads'; "
        "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }"
    )

    def _pick() -> str:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=120,
        )
        return result.stdout.strip()

    try:
        selected = await asyncio.to_thread(_pick)
    except subprocess.TimeoutExpired:
        return {"success": False, "detail": "A janela de seleção ficou aberta tempo demais."}
    return {"success": bool(selected), "path": selected}
