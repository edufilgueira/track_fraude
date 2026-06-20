#!/usr/bin/env python3
"""Inicia o servidor web (painel de lojas)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

SERVER_DIR = Path(__file__).resolve().parent
ROOT = SERVER_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core" / "src"))

from server.app import create_app
from server.settings import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Servidor web — login, cadastro de lojas e OCR ROI."
    )
    parser.add_argument(
        "--settings",
        default=str(SERVER_DIR / "config" / "settings.yaml"),
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    settings = load_settings(args.settings)
    host = args.host or settings.host
    port = args.port or settings.port

    app = create_app(args.settings)
    print(f"Painel web (local): http://127.0.0.1:{port}/login")
    if host in {"0.0.0.0", "::"}:
        print(f"Painel web (rede):  http://<IP-do-servidor>:{port}/login")
    else:
        print(f"Painel web: http://{host}:{port}/login")
    print(f"Banco: {settings.database_dsn}")
    print(f"Usuário padrão: {settings.admin_username}")
    uvicorn.run(app, host=host, port=port, reload=args.reload)


if __name__ == "__main__":
    main()
