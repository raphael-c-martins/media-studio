"""Validação de URLs externas antes de o servidor buscar algo na internet.

Impede que o servidor seja usado para acessar a rede interna (SSRF): só são
aceitos endereços http/https que resolvem para IPs públicos, inclusive em cada
redirecionamento. Downloads diretos têm limite de tamanho.
"""
import asyncio
import ipaddress
import socket
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urljoin, urlsplit

import httpx

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
MAX_REDIRECTS = 4


class UnsafeUrlError(ValueError):
    """URL recusada por apontar para fora da internet pública ou por formato inválido."""


class DownloadTooLargeError(ValueError):
    """O conteúdo remoto passou do limite de tamanho permitido."""


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_url_format(url: str) -> Tuple[str, str]:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeUrlError("A URL deve começar com http:// ou https://.")
    if not parts.hostname:
        raise UnsafeUrlError("A URL não tem um endereço de site válido.")
    if parts.username or parts.password:
        raise UnsafeUrlError("URLs com usuário e senha embutidos não são aceitas.")
    return parts.scheme, parts.hostname


async def assert_public_url(url: str) -> None:
    _, hostname = check_url_format(url)
    try:
        ipaddress.ip_address(hostname)
        addresses = [hostname]
    except ValueError:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise UnsafeUrlError(f"Não foi possível localizar o site {hostname}.") from exc
        addresses = sorted({info[4][0] for info in infos})
    if not addresses or not all(_is_public_ip(addr) for addr in addresses):
        raise UnsafeUrlError("Endereços da rede local ou internos não são permitidos.")


async def _open_public_stream(client: httpx.AsyncClient, url: str):
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        await assert_public_url(current)
        request = client.build_request("GET", current)
        response = await client.send(request, stream=True, follow_redirects=False)
        if response.is_redirect:
            location = response.headers.get("location", "")
            await response.aclose()
            if not location:
                raise UnsafeUrlError("Redirecionamento sem destino.")
            current = urljoin(current, location)
            continue
        return response
    raise UnsafeUrlError("Redirecionamentos demais.")


async def fetch_public_bytes(url: str, max_bytes: int, timeout: float = 30.0) -> Tuple[bytes, str]:
    """Baixa o conteúdo para a memória, respeitando o limite. Retorna (conteúdo, content-type)."""
    async with httpx.AsyncClient(timeout=timeout, headers=BROWSER_HEADERS) as client:
        response = await _open_public_stream(client, url)
        try:
            if response.status_code != 200:
                raise ValueError(f"O site respondeu com HTTP {response.status_code}.")
            chunks, total = [], 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise DownloadTooLargeError("O arquivo remoto passou do limite de tamanho.")
                chunks.append(chunk)
            return b"".join(chunks), response.headers.get("content-type", "")
        finally:
            await response.aclose()


async def download_public_file(
    url: str, destination: Path, max_bytes: int, timeout: float = 60.0,
    client: Optional[httpx.AsyncClient] = None,
) -> int:
    """Grava o conteúdo remoto em disco em blocos. Remove o arquivo parcial em caso de falha."""
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout, headers=BROWSER_HEADERS)
    total = 0
    try:
        response = await _open_public_stream(client, url)
        try:
            if response.status_code != 200:
                raise ValueError(f"O site respondeu com HTTP {response.status_code}.")
            handle = await asyncio.to_thread(open, destination, "wb")
            try:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise DownloadTooLargeError("O arquivo remoto passou do limite de tamanho.")
                    await asyncio.to_thread(handle.write, chunk)
            finally:
                await asyncio.to_thread(handle.close)
        finally:
            await response.aclose()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        if owns_client:
            await client.aclose()
    return total
