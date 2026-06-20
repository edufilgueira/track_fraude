from __future__ import annotations

import argparse

import uvicorn

from atlas.platform.app import create_app
from atlas.platform.settings import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Atlas Platform API")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    settings = load_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    app = create_app(settings)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
