"""
Input, output and error reporting shared by the CLI commands.

Exit codes of every command:

- 0: success. Warnings do not change it.
- 1: the document is invalid, or a converter cannot convert it.
- 2: usage or I/O: a bad option, a file that is missing, unreadable or not
  UTF-8, an unknown suffix or format, an output path that cannot be written.

No command lets a traceback reach the user.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn

import typer

from .._loading import InvalidDocument, UnknownSuffix

#: The `file` argument that selects standard input.
STDIN = "-"
STDIN_LABEL = "<stdin>"

#: Exit code of an invalid document or a failed conversion.
EXIT_INVALID = 1
#: Exit code of a usage or I/O error.
EXIT_USAGE = 2


def fail(message: str, code: int = EXIT_USAGE) -> NoReturn:
    """
    Print `error: <message>` on stderr and exit with `code`.

    The `error:` label is colored only when stderr is a terminal.
    """
    typer.echo(typer.style("error:", fg=typer.colors.RED, bold=True) + f" {message}", err=True)
    raise typer.Exit(code=code)


def is_stdin(file: Path) -> bool:
    """Whether `file` is the `-` argument that selects standard input."""
    return str(file) == STDIN


def display_name(file: Path) -> str:
    """How messages refer to `file`."""
    return STDIN_LABEL if is_stdin(file) else str(file)


def read_source(file: Path) -> str | Path:
    """
    The `source` to pass to `mdq.load`: the text of stdin for `-`, else
    `file` itself, so that its suffix selects the format.

    Stdin that is not UTF-8 ends the command with exit code 2. Reading a
    `Path` happens inside `load`: wrap that call in `reading`.
    """
    if not is_stdin(file):
        return file
    try:
        return sys.stdin.read()
    except UnicodeDecodeError as exc:
        fail(_decode_message(STDIN_LABEL, exc))


def read_text(file: Path) -> str:
    """
    The text of `file`, or of stdin for `-`.

    A file that cannot be read, or is not UTF-8, ends the command with
    exit code 2.
    """
    source = read_source(file)
    if isinstance(source, str):
        return source
    with reading(file):
        return source.read_text(encoding="utf-8")


@contextmanager
def reading(file: Path, *, suffix_hint: str = "") -> Iterator[None]:
    """
    Turn the errors of reading `file` into exit code 2 with a message.

    Covers `OSError`, `UnicodeDecodeError` and `UnknownSuffix`. The last
    is worded by the command: `suffix_hint` tells which option or suffix
    fixes it, e.g. "pass --format".
    """
    try:
        yield
    except UnknownSuffix as exc:
        suffixes = ", ".join(exc.SUFFIXES)
        hint = suffix_hint or f"use a file with one of the suffixes {suffixes}"
        fail(f"cannot infer a format from {exc.path}; {hint}")
    except UnicodeDecodeError as exc:
        fail(_decode_message(str(file), exc))
    except OSError as exc:
        fail(f"cannot read {file}: {exc.strerror or exc}")


@contextmanager
def writing(path: Path) -> Iterator[None]:
    """Turn an `OSError` while writing `path` into exit code 2 with a message."""
    try:
        yield
    except OSError as exc:
        fail(f"cannot write {path}: {exc.strerror or exc}")


def invalid_document(exc: InvalidDocument) -> NoReturn:
    """
    End the command for an invalid document (exit code 1), printing its
    first `error` diagnostic only. `mdq validate` prints all of them.
    """
    first = next((d for d in exc.diagnostics if d.severity == "error"), None)
    if first is None:
        fail(str(exc), EXIT_INVALID)
    fail(f"{first.code}: {first.message}", EXIT_INVALID)


def _decode_message(where: str, exc: UnicodeDecodeError) -> str:
    return f"cannot read {where}: not UTF-8 ({exc.reason} at byte {exc.start})"
