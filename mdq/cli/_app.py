"""
The `typer` application every command module registers itself against.

Split out from `__init__.py` so each command module (`_validate`,
`_new`, `_convert`, `_show`) can import `app` without importing
`mdq.cli` itself, which would still be mid-initialization while
`__init__.py` imports the command modules to register them.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="mdq",
    help="Tools for the MDQ (Markdown Questions) file format.",
    add_completion=False,
    no_args_is_help=True,
)


def main() -> None:
    """
    Main entry point to the CLI.
    """
    app()
