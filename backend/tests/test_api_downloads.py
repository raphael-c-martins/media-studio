import asyncio
import os
import uuid

from app.database import get_db_connection, recover_interrupted_downloads, utc_now
from tests.conftest import LOCAL_HEADERS


async def _insert_download(file_path: str, status: str = "completed") -> str:
    download_id = str(uuid.uuid4())
    async with get_db_connection() as db:
        await db.execute(
            "INSERT INTO downloads (id, url, title, status, file_path, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (download_id, "https://exemplo.com/v", "Teste", status, file_path, utc_now()),
        )
        await db.commit()
    return download_id


def test_configuracoes_nao_expoem_chaves_antigas(client):
    async def _legacy():
        async with get_db_connection() as db:
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('deepseek_api_key', 'segredo', ?)",
                (utc_now(),),
            )
            await db.commit()
    asyncio.run(_legacy())
    data = client.get("/api/settings").json()
    assert "deepseek_api_key" not in data
    assert set(data) == {"download_folder", "default_format", "default_audio_format", "theme"}


def test_configuracoes_recusam_chave_desconhecida(client):
    response = client.put("/api/settings", json={"qualquer": "x"}, headers=LOCAL_HEADERS)
    assert response.status_code == 422


def test_configuracoes_recusam_pasta_do_sistema(client):
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    response = client.put("/api/settings", json={"download_folder": system_root}, headers=LOCAL_HEADERS)
    assert response.status_code == 400


def test_nao_abre_nem_entrega_executavel(client, test_root):
    executable = test_root / "malicioso.exe"
    executable.write_bytes(b"MZ")
    download_id = asyncio.run(_insert_download(str(executable)))

    assert client.post(f"/api/history/{download_id}/open-file", headers=LOCAL_HEADERS).status_code == 404
    assert client.get(f"/api/history/{download_id}/file").status_code == 404


def test_excluir_historico_nao_apaga_executavel(client, test_root):
    executable = test_root / "importante.exe"
    executable.write_bytes(b"MZ")
    download_id = asyncio.run(_insert_download(str(executable)))

    response = client.delete(f"/api/history/{download_id}?delete_file=true", headers=LOCAL_HEADERS)
    assert response.status_code == 200
    assert executable.exists()


def test_entrega_arquivo_de_midia(client, test_root):
    media = test_root / "clipe teste.mp4"
    media.write_bytes(b"\x00" * 10)
    download_id = asyncio.run(_insert_download(str(media)))
    response = client.get(f"/api/history/{download_id}/file")
    assert response.status_code == 200
    assert "clipe" in response.headers["content-disposition"]

    history = client.get("/api/history").json()
    item = next(i for i in history if i["id"] == download_id)
    assert item["file_name"] == "clipe teste.mp4"
    assert "file_path" not in item


def test_downloads_interrompidos_viram_erro(client):
    queued = asyncio.run(_insert_download("", status="queued"))
    running = asyncio.run(_insert_download("", status="downloading"))
    assert asyncio.run(recover_interrupted_downloads()) >= 2
    history = {i["id"]: i for i in client.get("/api/history?limit=200").json()}
    assert history[queued]["status"] == "error"
    assert history[running]["status"] == "error"


def test_cancelar_inexistente_responde_404(client):
    assert client.delete("/api/downloads/nao-existe", headers=LOCAL_HEADERS).status_code == 404


def test_download_para_rede_interna_e_recusado(client):
    response = client.post("/api/downloads", json={"url": "http://192.168.0.1/video.mp4"}, headers=LOCAL_HEADERS)
    assert response.status_code == 400
    response = client.post("/api/downloads", json={
        "url": "https://8.8.8.8/post", "direct_media_url": "http://169.254.169.254/x.jpg",
    }, headers=LOCAL_HEADERS)
    assert response.status_code == 400


def test_capa_de_endereco_interno_e_recusada(client):
    response = client.get("/api/info/thumbnail", params={"url": "http://127.0.0.1:8810/health"})
    assert response.status_code == 400


def test_migrations_sao_idempotentes(client):
    from app.database import init_db
    asyncio.run(init_db())
    asyncio.run(init_db())

    async def _count():
        async with get_db_connection() as db:
            cursor = await db.execute("SELECT COUNT(*) AS n FROM schema_migrations")
            return (await cursor.fetchone())["n"]
    assert asyncio.run(_count()) == 2
