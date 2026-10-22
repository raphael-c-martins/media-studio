"""Inicia o servidor: python -m app (a partir da pasta backend)."""
import uvicorn

from app import config


def main() -> None:
    config.validate_runtime()
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="info", proxy_headers=False)


if __name__ == "__main__":
    main()
