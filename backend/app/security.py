"""Proteções de acesso do servidor local.

1. Host: só aceita requisições endereçadas a localhost (bloqueia DNS rebinding,
   quando um site externo aponta o próprio domínio para 127.0.0.1).
2. Ações que alteram algo (POST/PUT/PATCH/DELETE) exigem o cabeçalho
   X-Media-Studio. Um site externo não consegue enviar esse cabeçalho sem a
   permissão de CORS, que este servidor nunca concede.
3. Modo rede (MS_ACCESS_TOKEN): exige um cookie de sessão, criado ao abrir
   /?token=<token> uma única vez.
"""
import hmac
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app import config

CSRF_HEADER = "x-media-studio"
SESSION_COOKIE = "ms_session"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https:; "
    "media-src 'self' blob: https:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)


def _hostname(value: str) -> str:
    if not value:
        return ""
    return (urlsplit(f"//{value}").hostname or "").lower()


def _origin_hostname(origin: str) -> str:
    return (urlsplit(origin).hostname or "").lower()


def _token_ok(candidate: str) -> bool:
    return bool(candidate) and hmac.compare_digest(candidate, config.ACCESS_TOKEN)


def _deny(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})


def apply_security_headers(response) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY


class LocalAccessMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        network_mode = config.token_required()
        host = _hostname(request.headers.get("host", ""))

        if not network_mode and not config.is_loopback_host(host):
            return _deny(403, "Acesso permitido apenas pelo endereço local (localhost).")

        if network_mode:
            query_token = request.query_params.get("token", "")
            if request.method == "GET" and request.url.path == "/" and _token_ok(query_token):
                response = RedirectResponse("/", status_code=303)
                response.set_cookie(
                    SESSION_COOKIE, config.ACCESS_TOKEN, httponly=True, samesite="strict"
                )
                return response
            if request.url.path != "/health" and not _token_ok(request.cookies.get(SESSION_COOKIE, "")):
                return _deny(401, "Sessão ausente. Abra o endereço com ?token= uma vez.")

        if request.method in UNSAFE_METHODS:
            if request.headers.get(CSRF_HEADER) != "1":
                return _deny(403, "Requisição recusada: cabeçalho de origem ausente.")
            origin = request.headers.get("origin")
            if origin and _origin_hostname(origin) != host:
                return _deny(403, "Requisição recusada: origem diferente do servidor.")

        response = await call_next(request)
        apply_security_headers(response)
        if not request.url.path.startswith("/api/"):
            # A interface é pequena e muda a cada versão: o navegador revalida em vez de usar cópia velha.
            response.headers["Cache-Control"] = "no-cache"
        return response
