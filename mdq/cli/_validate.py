"""
`mdq validate`: load a question or exam document, and print its
diagnostics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer

from .._loading import Diagnostic, load
from ._app import app

Level = Literal["default", "strict"]


@app.command()
def validate(
    file: Path = typer.Argument(
        ...,
        help="Path to a question or exam document (.mdq.md, .md, .mdq, .yaml, .yml, or .json).",
    ),
    level: Level = typer.Option(
        "default",
        "--level",
        case_sensitive=False,
        help=(
            "'default' prints errors and warnings; 'strict' also prints "
            "info-level diagnostics. Every lint rule always runs -- this "
            "only changes what gets printed."
        ),
    ),
) -> None:
    """
    Validate a question or exam file, and lint it for issues beyond
    what a schema can express.
    """

    try:
        loaded = load(file)
    except (OSError, ValueError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2)

    exit_code = _print_result(file, loaded.diagnostics, level=level)
    if exit_code:
        raise typer.Exit(code=exit_code)


def _print_result(file: Path, diagnostics: list[Diagnostic], *, level: Level) -> int:
    """
    Print one line per diagnostic and return the process exit code.

    `level="default"` hides `info`-severity diagnostics; `strict` prints
    everything. Either way, only an `error` fails the exit code -- a
    warning or an info diagnostic is advisory.
    """
    has_error = any(d.severity == "error" for d in diagnostics)
    typer.echo(f"{'FAIL' if has_error else 'OK':<5} {file}", err=has_error)

    shown = diagnostics if level == "strict" else [d for d in diagnostics if d.severity != "info"]
    for d in shown:
        location = "/".join(str(part) for part in d.path) or "<root>"
        if d.line is not None:
            location = f"{location}:{d.line}"
        typer.echo(f"  {d.severity:<7} [{d.code}] {location}: {d.message}", err=True)

    return 1 if has_error else 0
