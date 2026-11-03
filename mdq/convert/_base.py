from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, NoReturn

from pydantic import ValidationError

from .._diagnostics import RANK, Diagnostic, Severity
from ..errors import ConversionError, ConversionWarning, ParseError
from ..models import Question
from ..types import QuestionType
from ._codes import CONVERTER_CODES

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


type HtmlMode = Literal["block", "markdown"]


@dataclass
class Report:
    """
    Collects the diagnostics of one conversion.

    `path` arguments are relative to the question or blank that
    `under` selects, and a diagnostic always carries the full path in the
    MDQ question (of the source question on export, of the produced one on
    import).
    """

    #: The display name of the format, used in messages: "GIFT", "Moodle XML", "Aiken".
    format: str
    #: How an import converts HTML text: see `load_question`.
    html: HtmlMode = "block"
    diagnostics: list[Diagnostic] = field(default_factory=list)
    _prefix: tuple[str | int, ...] = field(default=(), repr=False)

    @contextmanager
    def under(self, *path: str | int) -> Iterator[None]:
        """Prefix the path of every diagnostic reported inside the block with `path`."""
        saved = self._prefix
        self._prefix = saved + path
        try:
            yield
        finally:
            self._prefix = saved

    def _add(
        self,
        severity: Severity,
        code: str,
        message: str,
        path: tuple[str | int, ...],
        line: int | None,
    ) -> None:
        assert CONVERTER_CODES[code] == severity, f"{code!r} is not a {severity}"
        self.diagnostics.append(
            Diagnostic(
                severity=severity, code=code, message=message, path=self._prefix + path, line=line
            )
        )

    def warning(
        self, code: str, message: str, path: tuple[str | int, ...] = (), line: int | None = None
    ) -> None:
        """Report that the conversion changed or dropped something. It goes on."""
        self._add("warning", code, message, path, line)

    def info(
        self, code: str, message: str, path: tuple[str | int, ...] = (), line: int | None = None
    ) -> None:
        """Report metadata that the conversion dropped. It goes on."""
        self._add("info", code, message, path, line)

    def error(
        self, code: str, message: str, path: tuple[str | int, ...] = (), line: int | None = None
    ) -> NoReturn:
        """
        Stop the conversion with the problem `code`.

        Raises:
            ConversionError: always, with every diagnostic reported so far.
        """
        self._add("error", code, message, path, line)
        raise ConversionError(self.diagnostics)


class ConversionBase[Q](ABC):
    """
    Base class for conversion types.
    """

    #: The display name of the format, used in messages.
    name: ClassVar[str]

    #: The question types the format imports and exports.
    supports: ClassVar[frozenset[QuestionType]]

    @abstractmethod
    def to_mdq(self, external: Q, report: Report, /) -> Question:
        """
        Import question to a MDQ representation.
        """

    @abstractmethod
    def from_mdq(self, mdq: Question, report: Report, /) -> Q:
        """
        Convert MDQ question to the external question format
        """

    def render(self, external: Q, /) -> str:
        """
        Render the external format as a string.
        """
        return str(external)

    @abstractmethod
    def parse(self, source: str, report: Report | None = None, /) -> Q:
        """
        Parse source code in the external format into the internal
        representation. A problem that does not stop the parser goes to
        `report`.

        Raises:
            ParserError: the source has a syntax error.
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


@dataclass(frozen=True)
class Converted[T]:
    """
    The result of a conversion, with every diagnostic found.

    `bool(converted)` is true if there is a `value`.
    """

    #: The result, `None` if some diagnostic is an error.
    value: T | None
    #: In the order found.
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.value is not None

    def validate(self, raise_on: Severity = "error") -> T:
        """
        Return `value`.

        Raises:
            ConversionError: there is no `value`, or a diagnostic is at or
                above `raise_on`.
        """
        if self.value is None or any(RANK[d.severity] >= RANK[raise_on] for d in self.diagnostics):
            raise ConversionError(self.diagnostics, raise_on)
        return self.value


def require_markdownify() -> None:
    """
    Raise `ImportError` if the optional `markdownify` package is missing.

    Raises:
        ImportError: install `mdq[html]`.
    """
    try:
        import markdownify  # noqa: F401
    except ImportError:
        raise ImportError(
            'html="markdown" needs the markdownify package: install mdq[html]'
        ) from None


def _load(source: str, format: str, html: HtmlMode) -> tuple[Converted[Question], Exception | None]:
    """`load_question`, and the exception that stopped the conversion, if any."""
    converter = load_converter(format)
    if html not in ("block", "markdown"):
        raise ValueError(f"Unknown html mode: {html!r} (expected 'block' or 'markdown')")
    if html == "markdown":
        require_markdownify()
    report = Report(converter.name, html)
    try:
        try:
            external = converter.parse(source, report)
        except (ParserError, ConversionError):
            raise
        except ValueError as exc:
            # A value the parser cannot read, such as a fraction that is not a number.
            raise ParserError(str(exc), 0, 0) from exc
        try:
            question = converter.to_mdq(external, report)
        except (ConversionError, ValidationError):
            raise
        except ValueError as exc:
            report.error("invalid-question", str(exc))
        return Converted(question, report.diagnostics), None
    except ParserError as exc:
        report.diagnostics.append(
            Diagnostic(
                severity="error", code="syntax-error", message=str(exc), line=exc.lineno + 1
            )
        )
        return Converted(None, report.diagnostics), exc
    except ConversionError as exc:
        return Converted(None, report.diagnostics), exc
    except ValidationError as exc:
        # The converter built a question the models reject: a converter
        # bug, or a source MDQ cannot hold.
        report.diagnostics.append(
            Diagnostic(severity="error", code="invalid-question", message=str(exc))
        )
        return Converted(None, report.diagnostics), exc


def load_question(
    source: str, /, *, format: str, html: HtmlMode = "block"
) -> Converted[Question]:
    """
    Load a question in the given format from source, with the diagnostics.

    It never raises for a problem in the source: a syntax error
    (`syntax-error`, with its 1-based `line`), a source that cannot be read
    as MDQ, or a question the models reject (`invalid-question`) is an error
    diagnostic, and `value` is `None`.

    Args:
        source: Source code from the external question.
        format: The external question format.
        html: How to convert the HTML text of the source. `"block"` makes one
            HTML block of it. `"markdown"` converts it to Markdown with the
            optional `markdownify` package (extra `mdq[html]`).

    Raises:
        ValueError: `format` is not one of `FORMATS`, or `html` is unknown.
        ImportError: `html` is `"markdown"` and `markdownify` is missing.
    """
    return _load(source, format, html)[0]


def dump_question(question: Question, /, *, format: str) -> Converted[str]:
    """
    Convert a mdq question to a different format, with the diagnostics.

    Renders the resulting source code. It never raises for a problem in the
    question: a type the format does not support is the error
    `unsupported-type`.

    Args:
        question: The question to convert.
        format: The external question format.

    Raises:
        ValueError: `format` is not one of `FORMATS`.
    """
    return _dump(question, format)[0]


def _dump(question: Question, format: str) -> tuple[Converted[str], Exception | None]:
    converter = load_converter(format)
    report = Report(converter.name)
    try:
        if question.type not in converter.supports:
            report.error(
                "unsupported-type",
                f"{format!r} does not support {question.type!r} questions",
            )
        external = converter.from_mdq(question, report)
        return Converted(converter.render(external), report.diagnostics), None
    except ConversionError as exc:
        return Converted(None, report.diagnostics), exc


def _unwrap(result: Converted[Any], cause: Exception | None, strict: bool) -> Any:
    """The value of `result`, with each warning emitted as a `ConversionWarning`."""
    try:
        value = result.validate("warning" if strict else "error")
    except ConversionError as exc:
        raise exc from (None if isinstance(cause, ConversionError) else cause)
    for diagnostic in result.diagnostics:
        if diagnostic.severity == "warning":
            warnings.warn(ConversionWarning(diagnostic), stacklevel=3)
    return value


def import_question(
    source: str, /, *, format: str, strict: bool = False, html: HtmlMode = "block"
) -> Question:
    """
    Load a question in the given format from source.

    Each warning is emitted with `warnings.warn` as a `ConversionWarning`.

    Args:
        source: Source code from the external question.
        format: The external question format.
        strict: Raise on a warning too.
        html: See `load_question`.

    Raises:
        ConversionError: the source has a syntax error (`syntax-error`,
            with its 1-based `line`), cannot be read as MDQ, or gives a
            question the models reject (`invalid-question`); or, if
            `strict`, a warning. `__cause__` is the `ParserError` of a
            syntax error.
        ValueError: `format` is not one of `FORMATS`, or `html` is unknown.
        ImportError: `html` is `"markdown"` and `markdownify` is missing.
    """
    result, cause = _load(source, format, html)
    question: Question = _unwrap(result, cause, strict)
    return question


def export_question(question: Question, /, *, format: str, strict: bool = False) -> str:
    """
    Convert a mdq question to a different format.

    Renders the resulting source code. Each warning is emitted with
    `warnings.warn` as a `ConversionWarning`.

    Args:
        question: The question to convert.
        format: The external question format.
        strict: Raise on a warning too.

    Raises:
        ConversionError: the format cannot hold the question
            (`unsupported-type` for a type it does not support); or, if
            `strict`, a warning.
        ValueError: `format` is not one of `FORMATS`.
    """
    result, cause = _dump(question, format)
    text: str = _unwrap(result, cause, strict)
    return text
