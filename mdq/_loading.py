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
from collections.abc import Callable
from typing import Any, Generic, Literal, Mapping, TypeVar, get_args, overload

import yaml
from pydantic import ValidationError as PydanticValidationError
from pydantic_core.core_schema import ErrorType

from . import _parser, models
from ._banks import SOURCE_SUFFIXES
from ._diagnostics import RANK, Diagnostic, Severity
from ._include_keys import include_key_hint
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

D = TypeVar("D", covariant=True)

#: `Path` suffixes that select each format, checked against the whole
#: filename (not `Path.suffix`). `.md` also covers `.mdq.md`, the first of
#: the shared `SOURCE_SUFFIXES`.
_MDQ_SUFFIXES = SOURCE_SUFFIXES[1:]
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
) -> Loaded[models.Question | models.Exam]:
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


class UnknownSuffix(ValueError):
    """
    A `Path` source whose suffix selects no format.

    The message is worded for library callers (`format=`). The CLI catches
    this class and words the error for its own options, using `path` and
    `SUFFIXES`.
    """

    #: Every suffix `load` can infer a format from.
    SUFFIXES = _MDQ_SUFFIXES + _YAML_SUFFIXES + _JSON_SUFFIXES

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(
            f"cannot infer a format from {path}; pass format= explicitly "
            f"(expected one of {self.SUFFIXES})"
        )


def _format_from_path(path: Path) -> Format:
    name = path.name.lower()
    if name.endswith(_MDQ_SUFFIXES):
        return "mdq"
    if name.endswith(_YAML_SUFFIXES):
        return "yaml"
    if name.endswith(_JSON_SUFFIXES):
        return "json"
    raise UnknownSuffix(path)


def _load_text(
    text: str,
    fmt: str,
    *,
    kind: Kind | None,
    ids: Ids,
) -> Loaded[models.Question | models.Exam]:
    if fmt == "mdq":
        return _load_mdq_text(text, kind=kind, ids=ids)
    if fmt in ("yaml", "yml"):
        try:
            data = _parser.load_yaml(text)
        except yaml.YAMLError as exc:
            return Loaded(None, [_syntax_error("yaml-syntax-error", exc)])
        return _load_data(data, kind=kind, ids=ids)
    if fmt == "json":
        try:
            data = json.loads(
                text,
                object_pairs_hook=_json_object,
                parse_constant=_json_constant,
            )
        except ValueError as exc:
            return Loaded(None, [_syntax_error("json-syntax-error", exc)])
        return _load_data(data, kind=kind, ids=ids)
    raise ValueError(f"unknown format {fmt!r}; expected one of 'mdq', 'yaml', 'json'")


def _json_constant(name: str) -> Any:
    """`NaN`, `Infinity` and `-Infinity` are not JSON (RFC 8259, section 6)."""
    raise ValueError(f"{name} is not allowed in JSON (RFC 8259)")


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """A JSON object that repeats a key is an error, as in YAML."""
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"duplicate key {key!r} in a JSON object")
        data[key] = value
    return data


def _syntax_error(code: str, exc: Exception) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=str(exc))


def _load_mdq_text(
    text: str,
    *,
    kind: Kind | None,
    ids: Ids,
) -> Loaded[models.Question | models.Exam]:
    is_exam_doc = _parser.is_exam(text)
    mismatch = _kind_mismatch(kind, is_exam_doc)
    if mismatch is not None:
        return Loaded(None, [mismatch])

    # Reported even when parsing fails: a Unicode space before a tag is a
    # common reason for the failure.
    collected: list[Diagnostic] = _parser.find_unicode_spaces(text)
    try:
        if is_exam_doc:
            data: dict[str, Any] = dict(
                _parser.parse_exam(text, warnings=collected)
            )
        else:
            data = dict(_parser.parse_question(text, warnings=collected))
    except MdqError as exc:
        return Loaded(None, [*collected, _parse_error(exc)])

    # A key the frontmatter may not hold is an error of the parser: the
    # document it built is not the one the source describes.
    if any(d.severity == "error" for d in collected):
        return Loaded(None, collected)

    if is_exam_doc:
        return _load_exam(data, collected, ids=ids)
    return _load_question(data, collected, ids=ids)


def _load_data(
    data: Any,
    *,
    kind: Kind | None,
    ids: Ids = "keep",
) -> Loaded[models.Question | models.Exam]:
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
    if exc.node is not None and exc.node.map is not None:
        line = exc.node.map[0] + 1
    return Diagnostic(
        severity="error", code=exc.code, message=str(exc), line=line, path=exc.path
    )


# ---------------------------------------------------------------------
# Model validation + lint
# ---------------------------------------------------------------------


#: The tags of `models.ExamEntry`, the union of an exam's `questions`.
_EXAM_ENTRY_TAGS = frozenset({"question", "include", "includeAll"})


def _is_exam_entry_tag(loc: tuple[str | int, ...], index: int) -> bool:
    """`loc[index]` is the `ExamEntry` tag pydantic puts after `questions.N`."""
    return (
        index == 2
        and loc[0] == "questions"
        and isinstance(loc[1], int)
        and loc[index] in _EXAM_ENTRY_TAGS
    )


def _strip_discriminator_tags(
    loc: tuple[str | int, ...], data: Any, *, exam_entries: bool = False
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

    With `exam_entries`, the `ExamEntry` tag right after `questions.N`
    (`question`, `include`, `includeAll`) is dropped too. It cannot be
    told apart by walking `data`, since an include block has a key of
    the same name.

    A plain (non-discriminated) union, such as an exam's `grading`, gets
    one error per member, each with the member's type label in its `loc`
    (`literal['symmetric', ...]`, `dict[...]`). A label is never a key of
    the document, so it is dropped as well.

    A string-or-mapping shorthand (a bare pattern line, a choice text) is
    expanded into a mapping by a model validator, so an error on a field
    of the expansion has a `loc` that goes into a string of the document.
    The path stops at that string: it points into the document as
    written.
    """
    path: list[str | int] = []
    node = data
    for index, segment in enumerate(loc):
        if isinstance(node, str):
            break
        if (
            isinstance(node, dict)
            and segment not in node
            and node.get("type") == segment
        ):
            continue
        if exam_entries and _is_exam_entry_tag(loc, index):
            continue
        if isinstance(segment, str) and _is_union_member_label(segment):
            continue
        path.append(segment)
        try:
            node = node[segment]
        except (KeyError, IndexError, TypeError):
            node = None
    return tuple(path)


#: Labels pydantic uses for the members of a plain union in an error
#: `loc`, besides the parametrized forms (`literal[...]`, `dict[...]`),
#: which carry a `[`.
_BARE_UNION_LABELS = frozenset({"str", "int", "float", "bool", "none", "dict", "list"})


def _is_union_member_label(segment: str) -> bool:
    return "[" in segment or segment in _BARE_UNION_LABELS


#: pydantic's own error types (`missing`, `extra_forbidden`,
#: `value_error`, ...). docs/lint-codes.md, "Load errors", reports all of
#: them as one code, `schema-error`. A named MDQ rule raises a
#: `PydanticCustomError` with its own type, which is kept as the code.
_PYDANTIC_ERROR_TYPES: frozenset[str] = frozenset(get_args(ErrorType))


def _pydantic_error_code(error_type: str) -> str:
    return "schema-error" if error_type in _PYDANTIC_ERROR_TYPES else error_type


def _missing_tag_message(entry: Any, *, exam_entry: bool) -> str:
    """
    Replaces pydantic's "Unable to extract tag using discriminator
    'type'": a question with no `type`, or an exam entry that is neither
    a question nor an include block.
    """
    if exam_entry:
        return (
            "an entry of `questions` needs a `type`, or an `include` or "
            "`includeAll` key" + include_key_hint(entry)
        )
    return "a question needs a `type`"


def _pydantic_message(error: Mapping[str, Any], path: tuple[str | int, ...], exam: bool) -> str:
    if error["type"] != "union_tag_not_found":
        return str(error["msg"])
    if exam and len(path) == 2 and path[0] == "questions":
        return _missing_tag_message(error.get("input"), exam_entry=True)
    if not exam and not path:
        return _missing_tag_message(error.get("input"), exam_entry=False)
    return str(error["msg"])


def _pydantic_diagnostics(
    exc: PydanticValidationError, data: Any, *, exam: bool = False
) -> list[Diagnostic]:
    """
    One `Diagnostic` per pydantic error. A plain union reports one error
    per member for the same value; once the member labels are stripped
    from `loc`, those collapse into one diagnostic per code and path,
    keeping the first message.
    """
    diagnostics: list[Diagnostic] = []
    seen: set[tuple[str, tuple[str | int, ...]]] = set()
    for error in exc.errors():
        code = _pydantic_error_code(str(error["type"]))
        path = _strip_discriminator_tags(tuple(error["loc"]), data, exam_entries=exam)
        if (code, path) in seen:
            continue
        seen.add((code, path))
        diagnostics.append(
            Diagnostic(
                severity="error",
                code=code,
                message=_pydantic_message(error, path, exam),
                path=path,
            )
        )
    return diagnostics


def _validated[M: models.Question | models.Exam](
    validate: Callable[[dict[str, Any]], M],
    data: dict[str, Any],
    diagnostics: list[Diagnostic],
    *,
    exam: bool,
) -> Loaded[M]:
    """Build the model of `data` with `validate`, then lint it."""
    diagnostics = list(diagnostics)
    try:
        document = validate(data)
    except PydanticValidationError as exc:
        diagnostics.extend(_pydantic_diagnostics(exc, data, exam=exam))
        return Loaded(None, diagnostics)
    diagnostics.extend(document.lint())
    return Loaded(document, diagnostics)


def _load_question(
    data: dict[str, Any], diagnostics: list[Diagnostic], *, ids: Ids = "keep"
) -> Loaded[models.Question]:
    loaded = _validated(
        lambda data: models.QuestionRoot.model_validate(
            data, by_alias=True, by_name=False
        ).root,
        data,
        diagnostics,
        exam=False,
    )
    if ids == "fill" and loaded.document is not None:
        return Loaded(loaded.document.with_ids(), loaded.diagnostics)
    return loaded


def _load_exam(
    data: dict[str, Any],
    diagnostics: list[Diagnostic],
    *,
    ids: Ids = "keep",
) -> Loaded[models.Exam]:
    loaded = _validated(
        lambda data: models.Exam.model_validate(data, by_alias=True, by_name=False),
        data,
        diagnostics,
        exam=True,
    )
    if ids == "fill" and loaded.document is not None:
        try:
            return Loaded(loaded.document.with_ids(), loaded.diagnostics)
        except UnresolvedInclude as exc:
            loaded.diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="unresolved-include-all",
                    message=str(exc),
                )
            )
            return Loaded(None, loaded.diagnostics)
    return loaded
