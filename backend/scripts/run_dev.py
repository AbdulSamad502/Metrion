"""Local dev entrypoint — loads `backend/.env` (uvicorn's CLI has no built-in env-file
flag) then runs the app with `--reload`. Not used in production; the real deployment
entrypoint sets its env vars through the platform, not a `.env` file."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env")
sys.path.insert(0, str(ROOT / "backend" / "src"))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
