"""Root conftest — ensures backend package is importable from project-root tests."""

import os
import sys
from pathlib import Path

# Set env vars BEFORE any app import — pydantic-settings reads them at class
# instantiation time, which happens the first time config.py is imported.
os.environ.setdefault("ARCHON_AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")

backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
