"""
Nolan — Databricks Apps entry point.
Pre-sets all critical env vars, then imports and runs the FastAPI app directly.
"""
import os
import sys
from pathlib import Path

# ── Must happen BEFORE backend imports (they read env at module level) ─────
os.environ.setdefault("NOLAN_SESSIONS_DIR", "/tmp/nolan-sessions")
Path("/tmp/nolan-sessions").mkdir(parents=True, exist_ok=True)

ROOT = Path(__file__).parent
BACKEND = ROOT / "backend"

# Put backend on the path so 'import main' and its siblings work
sys.path.insert(0, str(BACKEND))

# Databricks runs the app from the snapshot root; uvicorn / pydub need
# to resolve relative paths from inside backend/
os.chdir(str(BACKEND))

import uvicorn  # noqa: E402
from main import app  # noqa: E402  # type: ignore

port = int(os.environ.get("PORT", 8000))
uvicorn.run(app, host="0.0.0.0", port=port, workers=1)
