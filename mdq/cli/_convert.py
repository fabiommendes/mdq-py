"""
`mdq import`/`mdq export`: convert a question between MDQ Markdown and an
external question format.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, cast

import typer

from .._diagnostics import Diagnostic
from .._loading import InvalidDocument, parse
from ..convert import FORMATS, dump_question, load_question
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
HTML_MODES = ("block", "markdown")


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
    strict: bool = typer.Option(
        False, "--strict", help="Treat a warning as an error: write nothing and exit 1."
    ),
    verbose: bool = typer.Option(
        False, "-v", "--verbose", help="Also print the info diagnostics (data that only a note or an id held)."
    ),
    html: str = typer.Option(
        "block",
        "--html",
        help=(
            "How to convert HTML text: 'block' (one HTML block, the default) or "
            "'markdown' (needs the optional markdownify package: install mdq[html])."
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
    if html not in HTML_MODES:
        fail(f"Unknown --html value: {html} (expected one of {', '.join(HTML_MODES)})")
    try:
        converted = load_question(source, format=fmt, html=cast(Literal["block", "markdown"], html))
    except ImportError as exc:
        fail(str(exc))
    except (ValueError, NotImplementedError) as exc:
        fail(str(exc), EXIT_INVALID)

    _report(converted.diagnostics, strict, verbose)
    assert converted.value is not None
    _write_output(str(converted.value), output)


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
    strict: bool = typer.Option(
        False, "--strict", help="Treat a warning as an error: write nothing and exit 1."
    ),
    verbose: bool = typer.Option(
        False, "-v", "--verbose", help="Also print the info diagnostics (data that only a note or an id held)."
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
        converted = dump_question(question, format=fmt)
    except (ValueError, NotImplementedError) as exc:
        fail(str(exc), EXIT_INVALID)

    _report(converted.diagnostics, strict, verbose)
    assert converted.value is not None
    _write_output(converted.value, output)


def _report(diagnostics: list[Diagnostic], strict: bool, verbose: bool) -> None:
    """
    Print every diagnostic on stderr as `<severity>: <message> [<code>]`,
    followed by ` at <path>` if it has one; an info only with `verbose`.
    Exit with code 1 if one is an error, or a warning under `strict`: there
    is nothing to write.
    """
    for d in diagnostics:
        if d.severity == "info" and not verbose:
            continue
        line = f"{d.severity}: {d.message} [{d.code}]"
        if d.path:
            line += " at " + "/".join(str(part) for part in d.path)
        typer.echo(line, err=True)
    levels = ("error", "warning") if strict else ("error",)
    if any(d.severity in levels for d in diagnostics):
        raise typer.Exit(code=EXIT_INVALID)


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
