"""
Local development server entry point.

Pre-stubs spaCy before any app import to avoid the pydantic v1/v2
TypeError that fires when the installed spaCy 3.7.x is loaded on
Python 3.12 with pydantic 2.x.  MLEnhancedParser.SPACY_AVAILABLE will
be False and the parser degrades gracefully to pdfplumber-only mode —
no functional difference for local dev.

Usage (called by start_local.sh / start_local.bat):
    TESTING=true python dev_server.py
"""

import os
import sys
import types

# Keep the backend dir importable regardless of where the script is invoked from.
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
os.chdir(_backend_dir)

# Stub spaCy before any module that transitively imports it is loaded.
if "spacy" not in sys.modules:
    _spacy = types.ModuleType("spacy")
    _spacy_matcher = types.ModuleType("spacy.matcher")

    class _Matcher:
        pass

    _spacy_matcher.Matcher = _Matcher
    _spacy.matcher = _spacy_matcher
    sys.modules["spacy"] = _spacy
    sys.modules["spacy.matcher"] = _spacy_matcher

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("RELOAD", "true").lower() not in ("0", "false", "no"),
    )
