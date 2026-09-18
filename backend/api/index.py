"""Vercel serverless entry point.

Vercel's Python runtime serves the ASGI application exported as `app` from
this module. The rest of the codebase is unchanged and still runs unmodified
under uvicorn on any container host.
"""

import sys
from pathlib import Path

# The function executes from this directory, so the project root has to be on
# the path before `app.main` can be imported.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

__all__ = ["app"]
