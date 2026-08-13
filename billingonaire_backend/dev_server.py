"""
Local development server entry point.

Usage (called by start_local.sh / start_local.bat):
    TESTING=true python dev_server.py
"""

import os
import sys

# Keep the backend dir importable regardless of where the script is invoked from.
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
os.chdir(_backend_dir)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("RELOAD", "true").lower() not in ("0", "false", "no"),
    )
