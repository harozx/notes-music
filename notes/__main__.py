"""Chạy server: python -m notes"""

import os
import sys

import uvicorn

from .config import BASE_DIR

if sys.stdout is None or sys.stderr is None:  # chạy bằng pythonw: không có console
    sys.stdout = sys.stderr = open(BASE_DIR / "server.log", "a", buffering=1, encoding="utf-8")

from .main import app  # noqa: E402

uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")))
