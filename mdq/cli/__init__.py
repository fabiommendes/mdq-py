"""
Command-line interface for mdq.

Commands: `validate`, `show`, `new`, `import` and `export`. Run
`mdq --help` for the usage of each one.
"""

from ._app import app, main

# Each command module registers itself against `app` on import; nothing
# in this package calls into them directly.
from . import _convert, _new, _show, _validate  # noqa: F401

__all__ = ["app", "main"]
