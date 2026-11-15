"""Configuração isolada para testes E2E em navegador Chromium headless.

Sobe um servidor Uvicorn temporário em 127.0.0.1 apontando para pastas
temporárias (MS_DATA_DIR, MS_LOGS_DIR, MS_DOWNLOADS_DIR, MS_TEMP_DIR),
garantindo que banco, logs e downloads reais nunca sejam tocados e que
nenhuma janela visível do navegador seja aberta.
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(base_url: str, proc: subprocess.Popen, timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_error = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stderr = proc.stderr.read() if proc.stderr else ""
            stdout = proc.stdout.read() if proc.stdout else ""
            raise RuntimeError(
                f"Servidor E2E encerrou cedo (exit={proc.returncode}).\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
            )
        try:
            resp = httpx.get(f"{base_url}/health", timeout=2.0)
            if resp.status_code == 200 and resp.json().get("status") == "healthy":
                return
            last_error = f"HTTP {resp.status_code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"Servidor E2E não respondeu em {base_url}/health ({last_error}).")


@pytest.fixture(scope="session")
def live_server() -> str:
    """Inicia uma instância isolada do Media Studio para os testes E2E."""
    temp_root = Path(tempfile.mkdtemp(prefix="media_studio_e2e_"))
    port = _free_loopback_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env.pop("MS_ACCESS_TOKEN", None)
    env.update(
        {
            "MS_HOST": "127.0.0.1",
            "MS_PORT": str(port),
            "MS_DATA_DIR": str(temp_root / "data"),
            "MS_LOGS_DIR": str(temp_root / "logs"),
            "MS_DOWNLOADS_DIR": str(temp_root / "downloads"),
            "MS_TEMP_DIR": str(temp_root / "temp"),
            "PYTHONUTF8": "1",
        }
    )

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        _wait_for_health(base_url, proc)
        yield base_url
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()
        shutil.rmtree(temp_root, ignore_errors=True)


@pytest.fixture(scope="session")
def headless_browser():
    """Mantém uma única sessão Chromium estritamente em modo headless."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture()
def page_with_telemetry(headless_browser, live_server):
    """Abre contexto limpo 1920x1080 com coleta automática de erros JS e HTTP."""
    context = headless_browser.new_context(
        viewport={"width": 1920, "height": 1080},
        accept_downloads=True,
    )
    context.set_default_timeout(10_000)
    context.set_default_navigation_timeout(30_000)
    page = context.new_page()

    telemetry = {
        "console_errors": [],
        "page_errors": [],
        "http_errors": [],
    }
    page.on(
        "console",
        lambda msg: telemetry["console_errors"].append(msg.text) if msg.type == "error" else None,
    )
    page.on("pageerror", lambda err: telemetry["page_errors"].append(str(err)))
    page.on(
        "response",
        lambda resp: telemetry["http_errors"].append((resp.status, resp.url)) if resp.status >= 400 else None,
    )

    try:
        yield page, telemetry, live_server
    finally:
        context.close()
