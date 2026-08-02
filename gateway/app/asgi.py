"""uvicorn entrypoint: uvicorn app.asgi:app"""

from __future__ import annotations

import logging

from .main import create_app

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = create_app()
