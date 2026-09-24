"""
The one path from Markdown/data to a validated model: parse, resolve
`include:` references, build the pydantic model, then lint.

Every caller -- the library's own top-level `parse`/`load`, the CLI, and
include resolution for an exam's nested questions -- goes through this
module. It never raises for a problem *in* the document: a parse
failure, a pydantic-only rule violation (e.g. an `ordering` question's
`accept`/`reject` overlap), and a lint warning all come back as
`Diagnostic`s on the returned `Loaded`. It raises only for a problem
with the *call itself*: a file that does not exist, or an unknown
`format`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Any, Generic, Literal, Mapping, TypeVar, overload

import yaml
from pydantic import ValidationError as PydanticValidationError

from . import linter, models, parser
from ._diagnostics import RANK, Diagnostic, Severity
from .errors import MdqError
from .loaders import FileLoader, IncludeNotFound, QuestionLoader

__all__ = [
    "Diagnostic",
    "Severity",
    "Loaded",
    "InvalidDocument",
    "load",
    "parse",
]

D = TypeVar("D")

#: Anything `load` accepts as a document source.
Source = str | Path | IO[str] | Mapping[str, Any]

#: The three surface syntaxes a document may be written in.
Format = Literal["mdq", "yaml", "json"]

Kind = Literal["question", "exam"]

#: `Path` suffixes that select each format, checked against the whole
#: filename (not `Path.suffix`) since `.mdq.md` is a compound suffix.
_MDQ_SUFFIXES = (".mdq.md", ".mdq")
_YAML_SUFFIXES = (".yaml", ".yml")
_JSON_SUFFIXES = (".json",)


class InvalidDocument(MdqError):
    """
    Raised by `Loaded.validate` when a diagnostic meets the severity
    threshold it was asked to enforce -- or there is no document at all.

    Carries every diagnostic `load` produced, not just the ones that
    triggered it, so a caller that only catches this exception still
    sees the full picture.
    """

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        summary = "; ".join(f"{d.severity} {d.code}: {d.message}" for d in diagnostics)
        super().__init__(summary or "invalid document")


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
    loader: QuestionLoader | None = None,
) -> Loaded[models.Question]: ...
@overload
def load(
    source: Source,
    *,
    kind: Literal["exam"],
    format: Format | None = None,
    loader: QuestionLoader | None = None,
) -> Loaded[models.Exam]: ...
@overload
def load(
    source: Source,
    *,
    kind: None = None,
    format: Format | None = None,
    loader: QuestionLoader | None = None,
) -> Loaded[models.Question | models.Exam]: ...
def load(
    source: Source,
    *,
    kind: Kind | None = None,
    format: Format | None = None,
    loader: QuestionLoader | None = None,
) -> Loaded[Any]:
    """
    Load a question or exam document, and lint it.

    Never raises for a problem in the document itself -- see the module
    docstring. Every problem comes back as a `Diagnostic` on the
    returned `Loaded`.

    Args:
        source: A `str` is always the document's own Markdown text (or
            other format, with `format`), never a path. A `Path`'s
            format comes from its suffix, unless `format` overrides it;
            when `loader` is `None`, `FileLoader(source.parent)` resolves
            its includes. An `IO[str]` is read, then handled as `str`. A
            `Mapping` is already-parsed data, and skips the parse step.
        kind: Narrows the return type and checks the document is the
            kind claimed. A mismatch is one `error` diagnostic, code
            `wrong-kind`, detected before any model validation runs.
        format: Overrides the format `source` would otherwise imply.
        loader: Resolves an exam's `include:` references.

    Raises:
        OSError: `source` is a `Path` that cannot be read.
        ValueError: `format` cannot be determined, or is not recognized.
    """
    if isinstance(source, Mapping):
        return _load_data(dict(source), kind=kind, loader=loader)

    if isinstance(source, Path):
        fmt = format or _format_from_path(source)
        text = source.read_text(encoding="utf-8")
        if loader is None:
            loader = FileLoader(source.parent)
    elif isinstance(source, str):
        fmt = format or "mdq"
        text = source
    elif hasattr(source, "read"):
        fmt = format or "mdq"
        text = source.read()
    else:
        raise TypeError(f"unsupported source type: {type(source)!r}")

    return _load_text(text, fmt, kind=kind, loader=loader)


@overload
def parse(
    source: Source,
    *,
    kind: Literal["question"],
    format: Format | None = None,
    loader: QuestionLoader | None = None,
    raise_on: Severity = "error",
) -> models.Question: ...
@overload
def parse(
    source: Source,
    *,
    kind: Literal["exam"],
    format: Format | None = None,
    loader: QuestionLoader | None = None,
    raise_on: Severity = "error",
) -> models.Exam: ...
@overload
def parse(
    source: Source,
    *,
    kind: None = None,
    format: Format | None = None,
    loader: QuestionLoader | None = None,
    raise_on: Severity = "error",
) -> models.Question | models.Exam: ...
def parse(
    source: Source,
    *,
    kind: Kind | None = None,
    format: Format | None = None,
    loader: QuestionLoader | None = None,
    raise_on: Severity = "error",
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
    return load(source, kind=kind, format=format, loader=loader).validate(raise_on)


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
    loader: QuestionLoader | None,
) -> Loaded[Any]:
    if fmt == "mdq":
        return _load_mdq_text(text, kind=kind, loader=loader)
    if fmt in ("yaml", "yml"):
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return Loaded(None, [_syntax_error("yaml-syntax-error", exc)])
        return _load_data(data if isinstance(data, dict) else {}, kind=kind, loader=loader)
    if fmt == "json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return Loaded(None, [_syntax_error("json-syntax-error", exc)])
        return _load_data(data if isinstance(data, dict) else {}, kind=kind, loader=loader)
    raise ValueError(f"unknown format {fmt!r}; expected one of 'mdq', 'yaml', 'json'")


def _syntax_error(code: str, exc: Exception) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=str(exc))


def _load_mdq_text(
    text: str,
    *,
    kind: Kind | None,
    loader: QuestionLoader | None,
) -> Loaded[Any]:
    is_exam_doc = parser.is_exam(text)
    mismatch = _kind_mismatch(kind, is_exam_doc)
    if mismatch is not None:
        return Loaded(None, [mismatch])

    collected: list[Diagnostic] = []
    try:
        if is_exam_doc:
            data: dict[str, Any] = dict(
                parser.parse_exam(text, loader=None, warnings=collected)
            )
        else:
            data = dict(parser.parse_question(text, warnings=collected))
    except MdqError as exc:
        return Loaded(None, [_parse_error(exc)])

    if is_exam_doc:
        return _load_exam(data, collected, loader)
    return _load_question(data, collected)


def _load_data(
    data: Any,
    *,
    kind: Kind | None,
    loader: QuestionLoader | None = None,
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
        return _load_exam(dict(data), [], loader)
    return _load_question(dict(data), [])


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
    return Diagnostic(severity="error", code="parse-error", message=str(exc), line=line)


# ---------------------------------------------------------------------
# Model validation + lint
# ---------------------------------------------------------------------


def _pydantic_diagnostics(exc: PydanticValidationError) -> list[Diagnostic]:
    return [
        Diagnostic(
            severity="error",
            code=str(error["type"]),
            message=error["msg"],
            path=tuple(error["loc"]),
        )
        for error in exc.errors()
    ]


def _load_question(data: dict[str, Any], diagnostics: list[Diagnostic]) -> Loaded[Any]:
    diagnostics = list(diagnostics)
    try:
        question = models.QuestionRoot.model_validate(data).root
    except PydanticValidationError as exc:
        diagnostics.extend(_pydantic_diagnostics(exc))
        return Loaded(None, diagnostics)

    diagnostics.extend(linter.lint_document(data, data.get("type", "")))
    return Loaded(question, diagnostics)


def _load_exam(
    data: dict[str, Any],
    diagnostics: list[Diagnostic],
    loader: QuestionLoader | None,
) -> Loaded[Any]:
    diagnostics = list(diagnostics)
    entries = list(data.get("questions") or [])
    ok = True
    resolved: list[Any] = []

    for index, entry in enumerate(entries):
        if _is_unresolved_include(entry):
            question_dict, entry_diagnostics = _resolve_include(loader, entry["include"], data)
        else:
            question_dict, entry_diagnostics = dict(entry), []

        diagnostics.extend(
            replace(d, path=("questions", index) + d.path) for d in entry_diagnostics
        )
        if question_dict is None:
            ok = False
            continue

        diagnostics.extend(
            replace(d, path=("questions", index) + d.path)
            for d in linter.lint_document(question_dict, question_dict.get("type", ""))
        )
        resolved.append(question_dict)

    if not ok:
        return Loaded(None, diagnostics)

    data = {**data, "questions": resolved}
    try:
        exam = models.Exam.model_validate(data)
    except PydanticValidationError as exc:
        diagnostics.extend(_pydantic_diagnostics(exc))
        return Loaded(None, diagnostics)

    diagnostics.extend(linter.lint_document(data, "exam"))
    return Loaded(exam, diagnostics)


def _is_unresolved_include(entry: Any) -> bool:
    return isinstance(entry, Mapping) and "include" in entry and "type" not in entry


#: Fields a question inherits from the exam when it declares none itself
#: -- mirrors `mdq.parser.INHERITED_FIELDS`.
_INHERITED_FIELDS = ("locale", "author")


def _resolve_include(
    loader: QuestionLoader | None,
    target: Any,
    exam: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[Diagnostic]]:
    target = str(target)
    if loader is None:
        return None, [
            Diagnostic(
                severity="error",
                code="include-not-found",
                message=f"cannot resolve included question {target!r}: no loader given",
            )
        ]

    try:
        source = loader.load(target)
    except IncludeNotFound as exc:
        return None, [Diagnostic(severity="error", code="include-not-found", message=str(exc))]

    diagnostics: list[Diagnostic] = []
    if isinstance(source, str):
        try:
            data = dict(parser.parse_question(source, warnings=diagnostics))
        except MdqError as exc:
            return None, [_parse_error(exc)]
    else:
        data = dict(source)

    data.setdefault("id", target)
    for field_name in _INHERITED_FIELDS:
        if field_name not in data and field_name in exam:
            data[field_name] = exam[field_name]

    return data, diagnostics
