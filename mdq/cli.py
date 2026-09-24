"""
Command-line interface for mdq.

Usage:
    mdq validate <question.json|question.yaml>
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.text import Text

from . import show as _show
from .convert import export_question, import_question
from .loading import Diagnostic, InvalidDocument, load, parse
from .scaffold import QUESTION_TYPES, default_output_path, render_template

app = typer.Typer(
    name="mdq",
    help="Tools for the MDQ (Markdown Questions) file format.",
    add_completion=False,
    no_args_is_help=True,
)


Level = Literal["default", "strict"]

stderr = Console(file=sys.stderr, highlight=False, force_terminal=True)


def main() -> None:
    """
    Main entry point to the CLI.
    """
    app()


@app.command()
def validate(
    file: Path = typer.Argument(
        ...,
        help="Path to a question or exam document (.mdq.md, .mdq, .yaml, .yml, or .json).",
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


@app.command()
def new(
    question_type: str = typer.Argument(
        ...,
        help=f"Question type to scaffold ({', '.join(QUESTION_TYPES)}).",
    ),
    output: Annotated[
        Path | None,
        typer.Option(
            ...,
            "-o",
            "--output",
            help="Where to write the new question file (default: <type>.mdq.md).",
        ),
    ] = None,
    complete: bool = typer.Option(
        False,
        "--complete",
        help=(
            "Illustrate every feature the question type supports, "
            "instead of a bare-bones example."
        ),
    ),
) -> None:
    """
    Scaffold a new question document.
    """

    try:
        content = render_template(question_type, complete=complete)
    except KeyError:
        valid = ", ".join(QUESTION_TYPES)
        typer.echo(
            f"error: unknown question type {question_type!r} (expected one of: {valid})",
            err=True,
        )
        raise typer.Exit(code=2)

    path = output or default_output_path(question_type)
    if path.exists():
        typer.echo(f"error: {path} already exists", err=True)
        raise typer.Exit(code=2)

    path.write_text(content, encoding="utf-8")
    typer.echo(f"wrote {path}")


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
        help="External format to import from (default: inferred from FILE's extension).",
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
            "External format to export to (default: inferred from -o's "
            "extension, falling back to 'aiken')."
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
        question = parse(source, kind="question")
    except InvalidDocument as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1)

    try:
        rendered = export_question(question, format=fmt)
    except (ValueError, TypeError, NotImplementedError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1)

    _write_output(rendered, output)


@app.command()
def show(
    file: Path = typer.Argument(
        ...,
        help="Path to a question or exam document (.mdq.md or .mdq), or - for stdin.",
    ),
    no_answer_key: bool = typer.Option(
        False,
        "--no-answer-key",
        help=(
            "Hide anything that reveals the correct answer (correctness "
            "marks, an essay's answer key, a numeric answer, ...), as if "
            "previewing the question for a student."
        ),
    ),
    width: int | None = typer.Option(
        None,
        "--width",
        help="Console width to render at (default: the terminal's own width).",
    ),
) -> None:
    """
    Show the parsed representation of a question or exam document.

    Renders rich-text fields (preamble, stem, epilogue, choice text,
    feedback, ...) as Markdown and everything else as structured
    metadata, so the document's shape is easy to check at a glance.
    """

    console = Console(
        file=sys.stdout,
        width=width,
        highlight=False,
        force_terminal=True,
    )
    error_console = Console(
        file=sys.stderr,
        highlight=False,
        force_terminal=True,
    )

    # Everything below that can embed a path or an exception message is
    # printed as a `Text` object, never spliced into a markup `str` --
    # `file` and `exc` can both carry document/filesystem content with
    # square brackets, which Rich would otherwise parse as markup (and,
    # for a stray closing tag like `[/]`, raise instead of print).
    #
    # A `Path` source resolves an exam's `include:` entries against its
    # own directory automatically (see `mdq.load`); stdin has no
    # directory to resolve against, so it is read as plain text instead.
    source = sys.stdin.read() if str(file) == "-" else file

    try:
        _show.show_source(source, console, show_answer_key=not no_answer_key)
    except OSError as exc:
        error_console.print("[b red]error:[/]", Text(f"could not read {file}: {exc}"))
        raise typer.Exit(code=2)
    except (ValueError, InvalidDocument) as exc:
        error_console.print("[b red]error:[/]", Text(str(exc)))
        raise typer.Exit(code=1)


#
# Utilities
#
FORMAT_SUFFIX_ALIASES = {"xml": "moodle-xml", "moodlexml": "moodle-xml"}


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


if __name__ == "__main__":
    main()
