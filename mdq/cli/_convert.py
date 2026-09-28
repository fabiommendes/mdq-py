"""
`mdq import`/`mdq export`: convert a question between MDQ Markdown and an
external question format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from .._loading import InvalidDocument, parse
from ..convert import FORMATS, export_question, import_question
from ._app import app

FORMAT_SUFFIX_ALIASES = {"xml": "moodle-xml", "moodlexml": "moodle-xml"}


@app.command("import")
def import_(
    file: Path = typer.Argument(
        ...,
        help="Path to a question file in an external format (e.g. Aiken, GIFT).",
    ),
    output: Annotated[
        Path | None,
        typer.Option(
            "-o",
            "--output",
            help="Where to write the imported MDQ document (default: print to stdout).",
        ),
    ] = None,
    format: str | None = typer.Option(
        None,
        "--format",
        help=(
            f"External format to import from ({', '.join(FORMATS)}; "
            "default: inferred from FILE's extension)."
        ),
    ),
) -> None:
    """
    Import a question from an external format into MDQ Markdown.
    """

    if not file.is_file():
        typer.echo(f"error: file not found: {file}", err=True)
        raise typer.Exit(code=2)

    fmt = format or _format_from_suffix(file)
    if fmt is None:
        typer.echo(
            f"error: cannot infer format from {file} -- pass --format",
            err=True,
        )
        raise typer.Exit(code=2)

    source = file.read_text(encoding="utf-8")
    try:
        question = import_question(source, format=fmt)
    except (ValueError, NotImplementedError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1)

    _write_output(str(question), output)


@app.command()
def export(
    file: Path = typer.Argument(
        ...,
        help="Path to an MDQ question document (.mdq.md or .mdq).",
    ),
    output: Annotated[
        Path | None,
        typer.Option(
            "-o",
            "--output",
            help="Where to write the exported document (default: print to stdout).",
        ),
    ] = None,
    format: str | None = typer.Option(
        None,
        "--format",
        help=(
            f"External format to export to ({', '.join(FORMATS)}; "
            "default: inferred from -o's extension, falling back to 'aiken')."
        ),
    ),
) -> None:
    """
    Export an MDQ question document to an external format.
    """

    if not file.is_file():
        typer.echo(f"error: file not found: {file}", err=True)
        raise typer.Exit(code=2)

    fmt = format or (output and _format_from_suffix(output)) or "aiken"

    source = file.read_text(encoding="utf-8")
    try:
        question = parse(source, kind="question", ids="fill")
    except InvalidDocument as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1)

    try:
        rendered = export_question(question, format=fmt)
    except (ValueError, TypeError, NotImplementedError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1)

    _write_output(rendered, output)


def _format_from_suffix(file: Path) -> str | None:
    """
    Infer a converter format name from a file's extension, e.g. `.aiken`
    -> "aiken". Returns None if the file has no extension.
    """
    suffix = file.suffix.lstrip(".")
    if not suffix:
        return None
    return FORMAT_SUFFIX_ALIASES.get(suffix, suffix)


def _write_output(content: str, output: Path | None) -> None:
    if output is None:
        typer.echo(content)
    else:
        output.write_text(content, encoding="utf-8")
        typer.echo(f"wrote {output}")
