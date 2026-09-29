"""
The one path from Markdown/data to a validated model: parse, build the
pydantic model, then lint. An exam's include blocks stay unresolved; the
host resolves them with `Exam.resolve`.

Every caller -- the library's own top-level `parse`/`load` and the CLI --
goes through this module. It never raises for a problem *in* the document: a parse
failure, a pydantic-only rule violation (e.g. an `ordering` question's
`accept`/`reject` overlap), and a lint warning all come back as
`Diagnostic`s on the returned `Loaded`. It raises only for a problem
with the *call itself*: a file that does not exist, or an unknown
`format`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Literal, Mapping, TypeVar, overload

import yaml
from pydantic import ValidationError as PydanticValidationError

from . import _parser, models
from ._diagnostics import RANK, Diagnostic, Severity
from .errors import InvalidDocument, MdqError, UnresolvedInclude
from .types import Format, Ids, Kind, Source

__all__ = [
    "Diagnostic",
    "Severity",
    "Loaded",
    "InvalidDocument",
    "load",
    "parse",
]

D = TypeVar("D")

#: `Path` suffixes that select each format, checked against the whole
#: filename (not `Path.suffix`). `.md` also covers `.mdq.md`.
_MDQ_SUFFIXES = (".md", ".mdq")
_YAML_SUFFIXES = (".yaml", ".yml")
_JSON_SUFFIXES = (".json",)


@dataclass(frozen=True)
class Loaded(Generic[D]):
    """
    The result of `load`: the document, if one could be built, and every
    diagnostic collected along the way.

    `document` is `None` if and only if some diagnostic is an `error` --
    the two are never inconsistent, so checking one tells you the other.
    """

    document: D | None
    diagnostics: list[Diagnostic]

    def __bool__(self) -> bool:
        return self.document is not None

    def validate(self, raise_on: Severity = "error") -> D:
        """
        Return the document, or raise `InvalidDocument`.

        Raises:
            InvalidDocument: there is no document, or some diagnostic's
                severity is at or above `raise_on` (`error` > `warning`
                > `info`).
        """
        threshold = RANK[raise_on]
        if self.document is None or any(
            RANK[d.severity] >= threshold for d in self.diagnostics
        ):
            raise InvalidDocument(self.diagnostics)
        return self.document


# ---------------------------------------------------------------------
# `load` / `parse`
# ---------------------------------------------------------------------


@overload
def load(
    source: Source,
    *,
    kind: Literal["question"],
    format: Format | None = None,
    ids: Ids = "keep",
) -> Loaded[models.Question]: ...
@overload
def load(
    source: Source,
    *,
    kind: Literal["exam"],
    format: Format | None = None,
    ids: Ids = "keep",
) -> Loaded[models.Exam]: ...
@overload
def load(
    source: Source,
    *,
    kind: None = None,
    format: Format | None = None,
    ids: Ids = "keep",
) -> Loaded[models.Question | models.Exam]: ...
def load(
    source: Source,
    *,
    kind: Kind | None = None,
    format: Format | None = None,
    ids: Ids = "keep",
) -> Loaded[Any]:
    """
    Load a question or exam document, and lint it.

    Never raises for a problem in the document itself -- see the module
    docstring. Every problem comes back as a `Diagnostic` on the
    returned `Loaded`.

    Args:
        source: A `str` is always the document's own Markdown text (or
            other format, with `format`), never a path. A `Path`'s
            format comes from its suffix, unless `format` overrides it.
            An `IO[str]` is read, then handled as `str`. A
            `Mapping` is already-parsed data, and skips the parse step.
        kind: Narrows the return type and checks the document is the
            kind claimed. A mismatch is one `error` diagnostic, code
            `wrong-kind`, detected before any model validation runs.
        format: Overrides the format `source` would otherwise imply.
        ids: `"keep"` (the default) returns `Loaded.document` exactly as
            written. `"fill"` returns `document.with_ids()` instead, so
            every question and choice has an id. Lint always inspects
            the document as written, in both modes.

    Raises:
        OSError: `source` is a `Path` that cannot be read.
        ValueError: `format` cannot be determined, or is not recognized.
    """
    if isinstance(source, Mapping):
        return _load_data(dict(source), kind=kind, ids=ids)

    if isinstance(source, Path):
        fmt = format or _format_from_path(source)
        text = source.read_text(encoding="utf-8")
    elif isinstance(source, str):
        fmt = format or "mdq"
        text = source
    elif hasattr(source, "read"):
        fmt = format or "mdq"
        text = source.read()
    else:
        raise TypeError(f"unsupported source type: {type(source)!r}")

    return _load_text(text, fmt, kind=kind, ids=ids)


@overload
def parse(
    source: Source,
    *,
    kind: Literal["question"],
    format: Format | None = None,
    raise_on: Severity = "error",
    ids: Ids = "keep",
) -> models.Question: ...
@overload
def parse(
    source: Source,
    *,
    kind: Literal["exam"],
    format: Format | None = None,
    raise_on: Severity = "error",
    ids: Ids = "keep",
) -> models.Exam: ...
@overload
def parse(
    source: Source,
    *,
    kind: None = None,
    format: Format | None = None,
    raise_on: Severity = "error",
    ids: Ids = "keep",
) -> models.Question | models.Exam: ...
def parse(
    source: Source,
    *,
    kind: Kind | None = None,
    format: Format | None = None,
    raise_on: Severity = "error",
    ids: Ids = "keep",
) -> Any:
    """
    Shortcut for ``load(...).validate(raise_on)``.

    Raises:
        OSError: `source` is a `Path` that cannot be read.
        ValueError: `format` cannot be determined, or is not recognized.
        InvalidDocument: the document is invalid at `raise_on`. Neither
            a `ParseError` nor a pydantic `ValidationError` ever escapes
            -- both are folded into this.
    """
    return load(source, kind=kind, format=format, ids=ids).validate(
        raise_on
    )


# ---------------------------------------------------------------------
# Source -> format
# ---------------------------------------------------------------------


def _format_from_path(path: Path) -> Format:
    name = path.name.lower()
    if name.endswith(_MDQ_SUFFIXES):
        return "mdq"
    if name.endswith(_YAML_SUFFIXES):
        return "yaml"
    if name.endswith(_JSON_SUFFIXES):
        return "json"
    raise ValueError(
        f"cannot infer a format from {path}; pass format= explicitly "
        f"(expected one of {_MDQ_SUFFIXES + _YAML_SUFFIXES + _JSON_SUFFIXES})"
    )


def _load_text(
    text: str,
    fmt: str,
    *,
    kind: Kind | None,
    ids: Ids,
) -> Loaded[Any]:
    if fmt == "mdq":
        return _load_mdq_text(text, kind=kind, ids=ids)
    if fmt in ("yaml", "yml"):
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return Loaded(None, [_syntax_error("yaml-syntax-error", exc)])
        return _load_data(
            data if isinstance(data, dict) else {}, kind=kind, ids=ids
        )
    if fmt == "json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return Loaded(None, [_syntax_error("json-syntax-error", exc)])
        return _load_data(
            data if isinstance(data, dict) else {}, kind=kind, ids=ids
        )
    raise ValueError(f"unknown format {fmt!r}; expected one of 'mdq', 'yaml', 'json'")


def _syntax_error(code: str, exc: Exception) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=str(exc))


def _load_mdq_text(
    text: str,
    *,
    kind: Kind | None,
    ids: Ids,
) -> Loaded[Any]:
    is_exam_doc = _parser.is_exam(text)
    mismatch = _kind_mismatch(kind, is_exam_doc)
    if mismatch is not None:
        return Loaded(None, [mismatch])

    collected: list[Diagnostic] = []
    try:
        if is_exam_doc:
            data: dict[str, Any] = dict(
                _parser.parse_exam(text, warnings=collected)
            )
        else:
            data = dict(_parser.parse_question(text, warnings=collected))
    except MdqError as exc:
        return Loaded(None, [_parse_error(exc)])

    if is_exam_doc:
        return _load_exam(data, collected, ids=ids)
    return _load_question(data, collected, ids=ids)


def _load_data(
    data: Any,
    *,
    kind: Kind | None,
    ids: Ids = "keep",
) -> Loaded[Any]:
    if not isinstance(data, Mapping):
        return Loaded(
            None,
            [
                Diagnostic(
                    severity="error",
                    code="invalid-document",
                    message="document must be a mapping at the top level",
                )
            ],
        )

    is_exam_doc = _is_exam_data(data)
    mismatch = _kind_mismatch(kind, is_exam_doc)
    if mismatch is not None:
        return Loaded(None, [mismatch])

    if is_exam_doc:
        return _load_exam(dict(data), [], ids=ids)
    return _load_question(dict(data), [], ids=ids)


def _is_exam_data(data: Mapping[str, Any]) -> bool:
    if data.get("type") == "exam":
        return True
    return "type" not in data and "questions" in data


def _kind_mismatch(kind: Kind | None, is_exam_doc: bool) -> Diagnostic | None:
    if kind == "question" and is_exam_doc:
        return Diagnostic(
            severity="error",
            code="wrong-kind",
            message="expected a question document, but this is an exam",
        )
    if kind == "exam" and not is_exam_doc:
        return Diagnostic(
            severity="error",
            code="wrong-kind",
            message="expected an exam document, but this is a question",
        )
    return None


def _parse_error(exc: MdqError) -> Diagnostic:
    line = None
    node = getattr(exc, "node", None)
    if node is not None and node.map is not None:
        line = node.map[0] + 1
    code = getattr(exc, "code", "parse-error")
    return Diagnostic(severity="error", code=code, message=str(exc), line=line)


# ---------------------------------------------------------------------
# Model validation + lint
# ---------------------------------------------------------------------


def _strip_discriminator_tags(
    loc: tuple[str | int, ...], data: Any
) -> tuple[str | int, ...]:
    """
    Drop the segments pydantic inserts into `loc` for a discriminated
    union member (`models.Question`, `models.Blank`).

    Such a segment is the member's `type` tag, not a key or index of the
    document, and `Diagnostic.path` promises only keys and indices. A
    segment is a tag when the input value at that point is a dict whose
    `type` equals the segment and which has no key of that name. Walking
    `data` keeps real keys that happen to look like a tag, such as the
    question types used as keys of an exam's `grading`.
    """
    path: list[str | int] = []
    node = data
    for segment in loc:
        if (
            isinstance(node, dict)
            and segment not in node
            and node.get("type") == segment
        ):
            continue
        path.append(segment)
        try:
            node = node[segment]
        except (KeyError, IndexError, TypeError):
            node = None
    return tuple(path)


def _pydantic_diagnostics(exc: PydanticValidationError, data: Any) -> list[Diagnostic]:
    return [
        Diagnostic(
            severity="error",
            code=str(error["type"]),
            message=error["msg"],
            path=_strip_discriminator_tags(tuple(error["loc"]), data),
        )
        for error in exc.errors()
    ]


def _load_question(
    data: dict[str, Any], diagnostics: list[Diagnostic], *, ids: Ids = "keep"
) -> Loaded[Any]:
    diagnostics = list(diagnostics)
    try:
        question = models.QuestionRoot.model_validate(data).root
    except PydanticValidationError as exc:
        diagnostics.extend(_pydantic_diagnostics(exc, data))
        return Loaded(None, diagnostics)

    diagnostics.extend(question.lint())
    if ids == "fill":
        question = question.with_ids()
    return Loaded(question, diagnostics)


def _load_exam(
    data: dict[str, Any],
    diagnostics: list[Diagnostic],
    *,
    ids: Ids = "keep",
) -> Loaded[Any]:
    diagnostics = list(diagnostics)
    try:
        exam = models.Exam.model_validate(data)
    except PydanticValidationError as exc:
        diagnostics.extend(_pydantic_diagnostics(exc, data))
        return Loaded(None, diagnostics)

    diagnostics.extend(exam.lint())
    if ids == "fill":
        try:
            exam = exam.with_ids()
        except UnresolvedInclude as exc:
            diagnostics.append(
                Diagnostic(severity="error", code="unresolved-include-all", message=str(exc))
            )
            return Loaded(None, diagnostics)
    return Loaded(exam, diagnostics)
