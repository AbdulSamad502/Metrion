"""Local dev entrypoint — loads `backend/.env` (uvicorn's CLI has no built-in env-file
flag) then runs the app with `--reload`. Not used in production; the real deployment
entrypoint sets its env vars through the platform, not a `.env` file."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

import dev_env

ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = ROOT / "backend" / ".env"
_SHELL_BEFORE_LOAD = {k: os.environ.get(k) for k in dev_env.DATABASE_KEYS}  # load_dotenv never overrides these, so remember what the shell had
load_dotenv(_ENV_FILE)
sys.path.insert(0, str(ROOT / "backend" / "src"))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    for line in dev_env.database_report({k: os.environ.get(k) for k in dev_env.DATABASE_KEYS}, _SHELL_BEFORE_LOAD, dotenv_values(_ENV_FILE)):
        print(line, flush=True)
    uvicorn.run("backend.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
