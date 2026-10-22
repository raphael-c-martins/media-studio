import asyncio

import pytest

from app.net_guard import UnsafeUrlError, assert_public_url, check_url_format


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://localhost:8810/api/settings",
    "http://10.0.0.5/admin",
    "http://192.168.0.1/",
    "http://172.16.3.4/",
    "http://169.254.169.254/latest/meta-data",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://0.0.0.0/",
])
def test_recusa_enderecos_internos(url):
    with pytest.raises(UnsafeUrlError):
        asyncio.run(assert_public_url(url))


@pytest.mark.parametrize("url", ["file:///C:/Windows/win.ini", "ftp://exemplo.com/a", "javascript:alert(1)", "http://"])
def test_recusa_esquemas_invalidos(url):
    with pytest.raises(UnsafeUrlError):
        check_url_format(url)


def test_recusa_credenciais_embutidas():
    with pytest.raises(UnsafeUrlError):
        check_url_format("https://usuario:senha@exemplo.com/")


def test_aceita_ip_publico():
    asyncio.run(assert_public_url("https://8.8.8.8/"))
