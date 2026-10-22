import pytest

from app import config, security
from tests.conftest import LOCAL_HEADERS


def test_bloqueia_host_externo_dns_rebinding(client):
    response = client.get("/api/settings", headers={"host": "atacante.example.com"})
    assert response.status_code == 403


def test_aceita_localhost_e_127(client):
    assert client.get("/api/settings").status_code == 200
    assert client.get("/api/settings", headers={"host": "127.0.0.1:8810"}).status_code == 200


def test_acao_sem_cabecalho_e_recusada(client):
    response = client.put("/api/settings", json={"theme": "dark"})
    assert response.status_code == 403


def test_acao_com_origem_de_outro_site_e_recusada(client):
    headers = {**LOCAL_HEADERS, "origin": "https://site-malicioso.com"}
    response = client.put("/api/settings", json={"theme": "dark"}, headers=headers)
    assert response.status_code == 403


def test_acao_com_origem_local_e_aceita(client):
    headers = {**LOCAL_HEADERS, "origin": "http://localhost:8810"}
    response = client.put("/api/settings", json={"theme": "dark"}, headers=headers)
    assert response.status_code == 200


def test_cabecalhos_de_seguranca(client):
    response = client.get("/")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_sem_cors_para_outros_sites(client):
    response = client.options("/api/settings", headers={
        "origin": "https://site-malicioso.com", "access-control-request-method": "PUT",
    })
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


def test_modo_rede_exige_sessao(client, monkeypatch):
    monkeypatch.setattr(config, "ACCESS_TOKEN", "t" * 32)
    assert client.get("/api/settings", headers={"host": "192.168.0.10:8810"}).status_code == 401
    assert client.get("/health", headers={"host": "192.168.0.10:8810"}).status_code == 200

    login = client.get("/?token=" + "t" * 32, headers={"host": "192.168.0.10:8810"}, follow_redirects=False)
    assert login.status_code == 303
    cookie = login.cookies.get(security.SESSION_COOKIE)
    assert cookie
    ok = client.get("/api/settings", headers={"host": "192.168.0.10:8810"},
                    cookies={security.SESSION_COOKIE: cookie})
    assert ok.status_code == 200


def test_modo_rede_token_errado(client, monkeypatch):
    monkeypatch.setattr(config, "ACCESS_TOKEN", "t" * 32)
    response = client.get("/?token=errado", headers={"host": "192.168.0.10:8810"}, follow_redirects=False)
    assert response.status_code == 401


def test_recusa_iniciar_em_rede_sem_token(monkeypatch):
    monkeypatch.setattr(config, "HOST", "0.0.0.0")
    monkeypatch.setattr(config, "ACCESS_TOKEN", "")
    with pytest.raises(RuntimeError):
        config.validate_runtime()
    monkeypatch.setattr(config, "ACCESS_TOKEN", "curto")
    with pytest.raises(RuntimeError):
        config.validate_runtime()


def test_localhost_inicia_sem_token(monkeypatch):
    monkeypatch.setattr(config, "HOST", "127.0.0.1")
    monkeypatch.setattr(config, "ACCESS_TOKEN", "")
    config.validate_runtime()
