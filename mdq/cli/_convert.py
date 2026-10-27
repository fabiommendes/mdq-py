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
from ._io import (
    EXIT_INVALID,
    display_name,
    fail,
    invalid_document,
    read_source,
    read_text,
    reading,
    writing,
)

FORMAT_SUFFIX_ALIASES = {"xml": "moodle-xml", "moodlexml": "moodle-xml"}


@app.command("import")
def import_(
    file: Path = typer.Argument(
        ...,
        help=(
            "Path to a question file in an external format (e.g. Aiken, GIFT), "
            "or - for stdin (needs --format)."
        ),
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

    source = read_text(file)
    fmt = _check_format(
        format or _format_from_suffix(file),
        f"cannot infer a format from {display_name(file)}; pass --format",
    )
    try:
        question = import_question(source, format=fmt)
    except (ValueError, NotImplementedError) as exc:
        fail(str(exc), EXIT_INVALID)

    _write_output(str(question), output)


@app.command()
def export(
    file: Path = typer.Argument(
        ...,
        help=(
            "Path to an MDQ question document (.mdq.md, .md, .mdq, .yaml, "
            ".yml, or .json), or - for stdin."
        ),
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

    fmt = _check_format(format or (output and _format_from_suffix(output)) or "aiken", "")
    source = read_source(file)
    try:
        with reading(file):
            question = parse(source, kind="question", ids="fill")
    except InvalidDocument as exc:
        invalid_document(exc)

    try:
        rendered = export_question(question, format=fmt)
    except (ValueError, TypeError, NotImplementedError) as exc:
        fail(str(exc), EXIT_INVALID)

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


def _check_format(fmt: str | None, missing_message: str) -> str:
    """
    `fmt` if it names a converter, else end the command with exit code 2:
    `missing_message` when there is no format, or an unknown-format error.
    """
    if fmt is None:
        fail(missing_message)
    if fmt.lower() not in FORMATS:
        fail(f"Unknown format: {fmt} (expected one of {', '.join(FORMATS)})")
    return fmt


def _write_output(content: str, output: Path | None) -> None:
    if output is None:
        typer.echo(content)
    else:
        with writing(output):
            output.write_text(content, encoding="utf-8")
        typer.echo(f"wrote {output}")
