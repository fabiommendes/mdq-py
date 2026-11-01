from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Literal, NoReturn

from pydantic import ValidationError

from .._diagnostics import Diagnostic
from ..errors import ConversionError, ParseError
from ..models import Question
from ..types import QuestionType
from ._codes import conversion_error

type Format = Literal["aiken", "gift", "moodle-xml"]

#: Every format `mdq.convert` can import from and export to.
FORMATS: tuple[Format, ...] = ("aiken", "gift", "moodle-xml")


class ParserError(ParseError):
    """
    A syntax error of an external format, with its place in the source.

    It is a `ParseError`, and so a `ValueError`. `lineno` and `colno` are
    0-based.
    """

    def __init__(self, message: str, lineno: int, colno: int):
        super().__init__(message)
        self.lineno = lineno
        self.colno = colno

    def __str__(self) -> str:
        return f"[line {self.lineno + 1}, col {self.colno + 1}]: {self.message}"


def fail_at(source: str, offset: int, message: str) -> NoReturn:
    """Raise a `ParserError` located at the character `offset` of `source`."""
    prefix = source[:offset]
    raise ParserError(message, prefix.count("\n"), offset - prefix.rfind("\n") - 1)


class ConversionBase[Q](ABC):
    """
    Base class for conversion types.
    """

    #: The question types the format imports and exports.
    supports: ClassVar[frozenset[QuestionType]]

    @abstractmethod
    def to_mdq(self, external: Q, /) -> Question:
        """
        Import question to a MDQ representation.
        """

    @abstractmethod
    def from_mdq(self, mdq: Question, /) -> Q:
        """
        Convert MDQ question to the external question format
        """

    def render(self, external: Q, /) -> str:
        """
        Render the external format as a string.
        """
        return str(external)

    @abstractmethod
    def parse(self, source: str, /) -> Q:
        """
        Parse source code in the external format into the internal
        representation.
        """


def load_converter(format: str) -> ConversionBase[Any]:
    """
    Return the converter of `format` (case-insensitive).

    A converter module is imported on first use, so importing `mdq.convert`
    never imports every converter. `Any` stands for the external type of
    the converter, which depends on the format.

    Raises:
        ValueError: `format` is not one of `FORMATS`.
    """
    format = format.lower()
    match format:
        case "aiken":
            from ._aiken import Aiken

            return Aiken()
        case "gift":
            from ._gift import Gift

            return Gift()
        case "moodle-xml":
            from ._moodle_xml import MoodleXml

            return MoodleXml()
        case _:
            raise ValueError(f"Unknown format: {format}")


def import_question(source: str, /, *, format: str) -> Question:
    """
    Load a question in the given format from source.

    Args:
        source: Source code from the external question.
        format: The external question format.

    Raises:
        ConversionError: the source has a syntax error (`syntax-error`,
            with its 1-based `line`), cannot be read as MDQ, or gives a
            question the models reject (`invalid-question`).
        ValueError: `format` is not one of `FORMATS`.
    """

    converter = load_converter(format)
    try:
        external = converter.parse(source)
    except ParserError as exc:
        diagnostic = Diagnostic(
            severity="error", code="syntax-error", message=str(exc), line=exc.lineno + 1
        )
        raise ConversionError([diagnostic]) from exc
    try:
        return converter.to_mdq(external)
    except ValidationError as exc:
        # The converter built a question the models reject: a converter
        # bug, or a source MDQ cannot hold.
        diagnostic = Diagnostic(severity="error", code="invalid-question", message=str(exc))
        raise ConversionError([diagnostic]) from exc


def export_question(question: Question, /, *, format: str) -> str:
    """
    Convert a mdq question to a different format.

    Renders the resulting source code.

    Args:
        source: Source code from the external question.
        format: The external question format.

    Raises:
        ConversionError: the format cannot hold the question.
        ValueError: `format` is not one of `FORMATS`.
    """
    converter = load_converter(format)
    if question.type not in converter.supports:
        msg = f"{format!r} does not support {question.type!r} questions"
        raise conversion_error("unsupported-type", msg)
    external = converter.from_mdq(question)
    return converter.render(external)
