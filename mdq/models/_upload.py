"""
Upload questions: `UploadQuestion`, and the two helpers a host uses to
apply the limits of a question to the files it receives
(`max_size_bytes`, `matches_extensions`). See docs/question-types/upload.md.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, ClassVar, Iterable, Literal, Mapping, Self

from pydantic import AfterValidator, Field, StrictInt, StrictStr, field_validator, model_validator

from .. import _parser
from .. import types as t
from .._diagnostics import Diagnostic
from .._files import ASCII_FOLD, EXTENSION_RE, MAX_SAFE_INTEGER, size_to_bytes
from .._markdown import UNICODE_SPACE
from ..errors import NotAutoGradable, ResponseError
from ..types import Automation
from . import _lint
from ._base import BaseQuestion, FreeText, raise_model_error
from ._score import QuestionScore
from ._text import check_missing_answer_key

__all__ = ["UploadQuestion", "max_size_bytes", "matches_extensions"]


#: The `file-name` rule of schema/question-base.yaml.
_FILE_NAME = re.compile(
    rf"(?!\.\.?\Z)(?![{UNICODE_SPACE}]+\Z)[^/\\]+"
)

_RESPONSE_KEYS = frozenset({"name", "path", "size"})


def _check_extension(value: str) -> str:
    """
    Raises:
        ValueError: `value` is not an extension (upload.md, "Extensions").
    """
    if EXTENSION_RE.fullmatch(value) is None:
        raise ValueError("must start with '.' and use only a-z, 0-9, '.', '_', '+', '-'")
    return value


def max_size_bytes(question: UploadQuestion | Mapping[str, Any]) -> int | None:
    """
    The largest size in bytes of each file of an upload question, or `None`
    when it has no limit.

    `question` is the model or its public form (`public()`), where `maxSize`
    keeps the form of the document.

    Raises:
        ValueError: `maxSize` of a public dict is present, not `None`, and
            not a valid size (upload.md, "Size").
    """
    if isinstance(question, UploadQuestion):
        size = question.max_size
    else:
        size = question.get("maxSize")
    return None if size is None else size_to_bytes(size)


def matches_extensions(question: UploadQuestion | Mapping[str, Any], name: str) -> bool:
    """
    Whether `name` is accepted by the `extensions` of an upload question.

    Only the letters `A` to `Z` of the name are folded to lower case. A name
    matches an extension when it ends with it and is longer than it.
    """
    if isinstance(question, UploadQuestion):
        extensions = question.extensions
    else:
        extensions = question.get("extensions")
    if extensions is None:
        return True
    folded = name.translate(ASCII_FOLD)
    return any(
        len(folded) > len(extension) and folded.endswith(extension)
        for extension in extensions
    )


class UploadQuestion(BaseQuestion[t.UploadResponse]):
    type: Literal["upload"] = "upload"

    #: The most files a response holds.
    max_files: Annotated[StrictInt, Field(ge=1, le=MAX_SAFE_INTEGER)] = 1

    #: The largest size of each file, as written: bytes, or a size string.
    max_size: StrictInt | StrictStr | None = None

    #: The accepted extensions. Any file when `None`.
    extensions: (
        Annotated[
            list[Annotated[str, AfterValidator(_check_extension)]],
            Field(min_length=1),
        ]
        | None
    ) = None

    #: A model answer for the human grading this.
    answer_key: FreeText | None = None

    @field_validator("max_size")
    @classmethod
    def check_max_size(cls, value: int | str | None) -> int | str | None:
        """
        Raises:
            ValueError: `maxSize` is not a valid size (upload.md, "Size").
        """
        if value is not None:
            size_to_bytes(value)
        return value

    @field_validator("extensions")
    @classmethod
    def check_extensions_unique(cls, value: list[str] | None) -> list[str] | None:
        """
        Raises:
            ValueError: an extension is repeated.
        """
        if value is not None and len(set(value)) != len(value):
            raise ValueError("extensions must not repeat an item")
        return value

    @model_validator(mode="after")
    def check_answer_key_has_no_h1(self) -> Self:
        """upload.md, "Answer key": the section holds any block except an H1."""
        if self.answer_key:
            for description in _parser.find_answer_key_forbidden_elements(
                self.answer_key
            ):
                raise_model_error(
                    type(self).__name__,
                    "forbidden-block-element",
                    f"'answerKey' holds {description}, which upload.md's "
                    f"\"Answer key\" does not allow",
                    ("answerKey",),
                    self.answer_key,
                )
        return self

    @property
    def automation(self) -> Automation:
        """Always `manual` (upload.md)."""
        return "manual"

    def lint(self) -> list[Diagnostic]:
        """See `BaseQuestion.lint`."""
        diagnostics = super().lint()
        diagnostics.extend(check_missing_answer_key(self.answer_key))
        diagnostics.extend(
            _lint.check_unsafe_thematic_break(self.answer_key, ("answerKey",))
        )
        return diagnostics

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        data = super().frontmatter(skip_defaults=skip_defaults)
        if self.max_files != 1 or not skip_defaults:
            data["maxFiles"] = self.max_files
        if self.max_size is not None:
            data["maxSize"] = self.max_size
        if self.extensions is not None:
            data["extensions"] = list(self.extensions)
        return data

    def _render_body(self) -> Iterable[str]:
        yield ""
        yield "[upload]"

    _PUBLIC_KEYS: ClassVar[tuple[str, ...]] = (
        *BaseQuestion._PUBLIC_KEYS, "maxFiles", "maxSize", "extensions",
    )  # fmt: skip

    def correct_responses(self) -> list[t.UploadResponse]:
        """
        See `BaseQuestion.correct_responses`: always empty. A response is a
        list of files, which a document cannot write down, and the answer
        key is not a response.
        """
        return []

    def _parse_response(self, response: object) -> t.UploadResponse:
        """
        Raises:
            ResponseError: `response` breaks a rule of upload.md, "Response".
        """
        # A tuple is accepted as a list on purpose: JSON has no tuple, so this
        # is a Python-only leniency (mdq-js accepts only arrays).
        if not isinstance(response, (list, tuple)) or not response:
            raise ResponseError("An upload response must be a non-empty list of files")
        limit = max_size_bytes(self)
        names: set[str] = set()
        files: list[t.UploadFileDict] = []
        for index, item in enumerate(response):
            where = f"file {index}"
            if not isinstance(item, Mapping):
                raise ResponseError(f"{where} must be a mapping")
            if set(item) != _RESPONSE_KEYS:
                raise ResponseError(f"{where} must have exactly name, path and size")
            name, path, size = item["name"], item["path"], item["size"]
            if not isinstance(name, str) or _FILE_NAME.fullmatch(name) is None:
                raise ResponseError(f"{where} has an invalid name")
            if not isinstance(path, str) or not path:
                raise ResponseError(f"{where} must have a non-empty path")
            size = _parse_file_size(size, where)
            if name in names:
                raise ResponseError(f"{where} repeats the name {name!r}")
            names.add(name)
            if limit is not None and size > limit:
                raise ResponseError(f"{where} is larger than maxSize")
            if not matches_extensions(self, name):
                raise ResponseError(f"{where} has a name that matches no extension")
            files.append({"name": name, "path": path, "size": size})
        if len(files) > self.max_files:
            raise ResponseError(f"A response holds at most {self.max_files} files")
        return files

    def _score(self, response: t.UploadResponse) -> QuestionScore:
        """
        Never gradable automatically.

        Raises:
            NotAutoGradable: always.
        """
        raise NotAutoGradable("upload questions require manual grading")

    def _render_lines(self) -> Iterable[str]:
        yield from super()._render_lines()
        if self.answer_key is not None:
            yield ""
            yield "## [answer-key]"
            yield ""
            yield self.answer_key


def _parse_file_size(size: object, where: str) -> int:
    """
    The size of a response file as an integer: `1.0` is `1`.

    Raises:
        ResponseError: `size` is not an integer from 0 to 2^53 - 1.
    """
    if isinstance(size, float) and size.is_integer():
        size = int(size)
    if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_SAFE_INTEGER:
        raise ResponseError(f"{where} has an invalid size")
    return size
