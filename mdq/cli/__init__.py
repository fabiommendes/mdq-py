"""
Command-line interface for mdq.

Usage:
    mdq validate <question.json|question.yaml>
"""

from ._app import app, main

# Each command module registers itself against `app` on import; nothing
# in this package calls into them directly.
from . import _convert, _new, _show, _validate  # noqa: F401

__all__ = ["app", "main"]
