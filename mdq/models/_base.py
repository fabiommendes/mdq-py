"""
`MdqModel`, the base class every model in the document tree extends, and
`BaseQuestion`, the fields and behavior every question type shares.

Also home to generic helpers with no question-type of their own: the
unique-id machinery shared by every "duplicate choice/id" rule
(dev/specs/to-do/unique-ids.md), the `locale`/blank-text-field/regex
validators reused across question and blank types, and the
preamble/stem/epilogue normalization helpers `BaseQuestion._normalize`
calls.
"""

from __future__ import annotations

import re
import unicodedata
import weakref
from typing import TYPE_CHECKING, Annotated, Any, Iterable, Mapping, Self, Sequence

import opt
import pydantic_core
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel
from pydantic_core import InitErrorDetails, PydanticCustomError

from .. import _parser
from .._diagnostics import Diagnostic
from . import _lint, _render
from ._regex import InvalidRegexError, RegexPattern

if TYPE_CHECKING:
    from ._exam import Exam
    from ._score import QuestionScore

__all__ = ["MdqModel", "BaseQuestion"]


class MdqModel(BaseModel):
    """
    Base configuration shared by every model in the document tree.

    `extra="forbid"` mirrors the schemas' `unevaluatedProperties: false`
    -- equal strictness, not more.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )

    def __str__(self) -> str:
        """
        Return a Markdown representation of the model.

        Same as `render()`.
        """
        return self.render()

    def to_dict(self, by_alias: bool = True) -> dict:
        """
        Return a dict representation of the model that is compatible with the
        JSON schema and the original document.
        """
        data = self.model_dump(
            by_alias=by_alias,
            exclude_none=True,
            exclude_defaults=True,
        )
        # `type` is a defaulted Literal on every discriminated model, so
        # `exclude_defaults` drops it -- on `self` and on every nested
        # model `model_dump` recurses into (a question inside an exam,
        # say). It is the one default worth keeping: without it the dict
        # no longer says which schema it validates against, and no
        # discriminated union can read it back.
        _reinject_type_discriminators(self, data)
        if "type" in type(self).model_fields:
            data = {"type": getattr(self, "type"), **data}
        return data

    def _render_lines(self) -> Iterable[str]:
        """
        Used by subclasses to implement `render_lines()`.

        Must return a generator yielding a Markdown representation of the model
        as an iterable of lines. The final rendering is the concatenation
        of these lines with newlines in between.
        """
        raise NotImplementedError("Subclasses must implement _render_lines()")

    def render(self) -> str:
        """
        Return a Markdown representation of the model.

        Joins the lines `_render_lines()` yields with newlines.
        """
        return "\n".join(self._render_lines())


#
# Unique ids: shared machinery for the four "duplicate" rules
# (dev/specs/to-do/unique-ids.md). These used to be `warning`-level lint
# checks in `mdq.models._lint`; they are model validators now, so a
# violation is an `error` that stops `load` from returning a document at
# all.
#

#: Runs of whitespace outside a code span. Splitting on backticks first
#: keeps `foo bar` and `foo  bar` distinct while still collapsing plain
#: prose -- the same normalization `mdq.models._lint` used to apply
#: under the name `_visual_key`, moved here so the models can use it too.
_CODE_SPAN_RE = re.compile(r"(`+[^`]*`+)")
_WHITESPACE_RE = re.compile(r"\s+")


def _visual_key(text: str) -> str:
    """
    Normalize `text` the way a Markdown renderer would, for comparing
    choice texts as a reader would see them once rendered: whitespace
    runs collapse to a single space in prose, but not inside code spans.
    """
    parts = _CODE_SPAN_RE.split(text)
    # Odd indices are the captured code spans; leave those untouched.
    normalized = [
        part if index % 2 else _WHITESPACE_RE.sub(" ", part)
        for index, part in enumerate(parts)
    ]
    return unicodedata.normalize("NFC", "".join(normalized)).strip()


def _raise_unique_id_error(
    model_name: str,
    code: str,
    message: str,
    loc: tuple[str | int, ...],
    input_value: Any,
) -> None:
    """
    Raise a pydantic `ValidationError` whose one error carries `code` as
    its `type` (so `mdq._loading` recovers it as the diagnostic `code`)
    and `loc` as its location, regardless of where in the model tree
    this runs -- `loc` is relative to whatever model raises, and
    pydantic prepends the path down to it (occasionally with a
    discriminated union's tag in between).
    """
    error = InitErrorDetails(
        type=PydanticCustomError(code, message), loc=loc, input=input_value
    )
    raise pydantic_core.ValidationError.from_exception_data(model_name, [error])


def _check_unique_choices(model_name: str, choices: Sequence[Any]) -> None:
    """
    Enforce `duplicate-choice-id` and `duplicate-choice-text` over one
    list of choices -- a question's own `choices`, or one fill-in choice
    blank's.

    Ids are compared as-is; texts are compared with `_visual_key`, so
    two texts that only differ in incidental whitespace collide too
    (multiple-choice.md, "Choices").
    """
    seen_ids: dict[str, int] = {}
    seen_visuals: dict[str, int] = {}

    for index, choice in enumerate(choices):
        choice_id = choice.id
        if choice_id is not None:
            first_index = seen_ids.get(choice_id)
            if first_index is not None:
                _raise_unique_id_error(
                    model_name,
                    "duplicate-choice-id",
                    f"choice id {choice_id!r} is already used by choices[{first_index}]",
                    ("choices", index, "id"),
                    choice_id,
                )
            seen_ids[choice_id] = index

        visual = _visual_key(choice.text)
        first_index = seen_visuals.get(visual)
        if first_index is not None:
            _raise_unique_id_error(
                model_name,
                "duplicate-choice-text",
                f"choice text {choice.text!r} is already used by choices[{first_index}]",
                ("choices", index, "text"),
                choice.text,
            )
        seen_visuals[visual] = index


#
# Model errors that used to be `warning`-level lint checks
# (dev/specs/to-do/lint-on-models.md, "New errors"): a document that
# violates one of these fails to build at all, the same way a duplicate
# id does above.
#

#: generic.md [^4]: `locale` must be a BCP 47 language tag. This is the
#: common `language[-Script][-REGION]` shape, which is what questions
#: actually use; a tag with private-use or extension subtags is rarer
#: than a language *name* written where a tag belongs, which is what
#: this catches.
_BCP47_RE = re.compile(r"^[a-z]{2,3}(-[A-Z][a-z]{3})?(-([A-Z]{2}|[0-9]{3}))?$")

#: `[^blank-id]` markers, as written in a fill-in stem.
_BLANK_MARKER_RE = re.compile(r"\[\^([^\]]+)\]")


def _validate_locale(value: str | None) -> str | None:
    """generic.md [^4]: raise `malformed-locale` for an ill-formed tag."""
    if value is not None and not _BCP47_RE.match(value):
        raise PydanticCustomError(
            "malformed-locale",
            f"{value!r} is not a BCP 47 language tag; expected a form "
            f"like 'en', 'pt-BR', or 'zh-Hans-CN'",
        )
    return value


def _validate_not_blank(value: str | None, field_name: str) -> str | None:
    """base.md: raise `blank-text-field` for a defined-but-blank value."""
    if value is not None and value.strip() == "":
        raise PydanticCustomError(
            "blank-text-field",
            f"'{field_name}' is defined but has no visible characters",
        )
    return value


def _validate_mdq_regex(value: str | None) -> str | None:
    """short-answer.md: raise `invalid-regex` for a pattern that doesn't compile."""
    if value is not None:
        try:
            RegexPattern(value)
        except InvalidRegexError as exc:
            raise PydanticCustomError(
                "invalid-regex", f"regex does not compile: {exc}"
            ) from exc
    return value


class BaseQuestion[R](MdqModel):
    """
    Fields every question type carries.

    `id` is optional here and required for grading: a document that
    lacks one is valid but not *addressable*, and the system using the
    library is expected to supply it.
    """

    id: str | None = None
    uuid: str | None = None
    title: str | None = None
    author: str | None = None
    stem: str
    preamble: str | None = None
    epilogue: str | None = None
    comment: str | None = None
    locale: str | None = None
    meta: dict[str, object] | None = None
    tags: list[str] = Field(default_factory=list)
    _exam: Annotated[weakref.ref[Exam] | None, Field(default=None, exclude=True)] = None

    @field_validator("locale")
    @classmethod
    def check_locale_is_well_formed(cls, value: str | None) -> str | None:
        return _validate_locale(value)

    @field_validator("preamble")
    @classmethod
    def check_preamble_is_not_blank(cls, value: str | None) -> str | None:
        return _validate_not_blank(value, "preamble")

    @field_validator("stem")
    @classmethod
    def check_stem_is_not_blank(cls, value: str) -> str:
        """
        base.md, "Additional Rules": raise `blank-text-field` for a stem
        without a visible character.
        """
        if not value.strip():
            raise PydanticCustomError(
                "blank-text-field", "'stem' has no visible characters"
            )
        return value

    @field_validator("epilogue")
    @classmethod
    def check_epilogue_is_not_blank(cls, value: str | None) -> str | None:
        return _validate_not_blank(value, "epilogue")

    @model_validator(mode="after")
    def check_no_forbidden_block_elements(self) -> Self:
        """
        base.md:250, "Forbidden elements": `preamble`, `stem` and
        `epilogue` may not hold an H1 heading, a heading or paragraph
        starting with `[` (the syntax a body tag or a fill-in blank
        marker use), or an unordered list whose items all start with
        `[` -- any of these could be mistaken for the question's body.
        Checked here (not only by `mdq._parser`), so a document built
        directly from a `dict`/YAML/JSON skips no less than a parsed one
        does (dev/specs/to-do/rule-conformance.md, section D).

        A leading `[slug]` prefix is exempt only on the very first block
        of the combined preamble+stem sequence (generic.md, "Slug") --
        the epilogue, which is never that first block, gets no exemption.
        """
        fields = (
            ("preamble", self.preamble, bool(self.preamble)),
            ("stem", self.stem, not self.preamble),
            ("epilogue", self.epilogue, False),
        )
        for field_name, text, allow_leading_bracket in fields:
            if not text:
                continue
            for description in _parser.find_forbidden_elements(
                text, allow_first_paragraph_bracket=allow_leading_bracket
            ):
                _raise_unique_id_error(
                    type(self).__name__,
                    "forbidden-block-element",
                    (
                        f"'{field_name}' holds {description}, which base.md's "
                        f"\"Forbidden elements\" reserves for the question body"
                    ),
                    (field_name,),
                    text,
                )
        return self

    @property
    def exam(self) -> Exam | None:
        if self._exam is not None:
            return self._exam()
        return None

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> Self:
        copy = super().model_copy(update=update, deep=deep)
        copy._exam = None  # unbind the copy from the exam.
        return copy

    def __eq__(self, other: object) -> bool:
        # `_exam` is a back-reference, not part of the question's value.
        # Pydantic compares private attributes, and a weakref compares its
        # referents, so including it would compare the owning exams, whose
        # questions point back to them -- infinite recursion.
        if not isinstance(other, BaseQuestion):
            return NotImplemented
        return type(self) is type(other) and self.__dict__ == other.__dict__

    #: How much this question counts towards its exam. An exam entry may
    #: override it, and resolution applies that override here, so the
    #: value on a resolved question is always the winning one.
    weight: Annotated[float, Field(ge=0)] = 1.0

    def frontmatter(self, skip_defaults: bool = False) -> dict[str, Any]:
        """
        Return a dict representation of the model that is compatible with the
        frontmatter of the original document.
        """

        data: dict[str, Any] = {
            "id": self.id,
            "uuid": self.uuid,
            "title": self.title,
            "author": self.author,
            "locale": self.locale,
            "meta": self.meta,
        }
        if skip_defaults:
            data = clear_nones(data)
        if self.weight != 1.0 or not skip_defaults:
            data["weight"] = self.weight
        if self.tags != [] or not skip_defaults:
            data["tags"] = self.tags
        return data

    def _render_lines(self) -> Iterable[str]:
        frontmatter = self.frontmatter(skip_defaults=True)

        id = self.id
        skip_frontmatter = (
            frontmatter.keys() == {"id"}
            and can_inline_id(self.preamble, self.stem)
            and not self.comment
        )
        if not skip_frontmatter:
            id = None
            if frontmatter or self.comment:
                yield from _render.yield_frontmatter(frontmatter, self.comment)
                yield ""

        yield from _render.yield_introduction(self, id=id)
        yield from self._render_body()
        yield from _render.yield_conclusion(self, skip_line=True)

    def _render_body(self) -> Iterable[str]:
        """
        model's body as an iterable of lines.
        """
        raise NotImplementedError("Subclasses must implement _render_body()")

    def normalize(self) -> Self:
        """
        Return a copy of the model with normalized fields.

        Two models that normalize to the same model should have the same
        markdown representation. Treat it as a canonical form for the model,
        useful for comparing two elements.
        """
        copy = self.model_copy()
        copy._normalize()
        return copy

    def _normalize(self) -> None:
        """
        Normalize *inplace*.

        Runs `mdq._parser`'s Markdown parser over `preamble`/`stem`/
        `epilogue` (via `normalize_intro`/`normalize_paragraphs`) to
        canonicalize them, so this is no longer a handful of cheap
        string operations -- fine at this project's scale, but worth
        knowing if it ever shows up in a profile.
        """
        # `preamble`/`epilogue`/`comment` are rendered as the mere
        # presence of raw lines (prose blocks, `#`-comment lines) with
        # no field marker of their own, so an empty string and no value
        # at all render identically and a parse can only ever produce
        # the latter. Collapsing an all-whitespace value to None here
        # keeps normalization a fixed point of that round trip.
        self.preamble, self.stem = normalize_intro(self.preamble, self.stem)
        self.epilogue = opt.map(normalize_paragraphs, self.epilogue) or None
        self.comment = opt.map(remove_trailing_ws, self.comment) or None
        self.tags = [tag.strip() for tag in self.tags if tag.strip()]
        self.author = opt.map(str.strip, self.author)

    def score_response(self, response: R) -> QuestionScore:
        """
        Return the score for one response to this question.
        """
        raise NotImplementedError("Subclasses must implement score_response()")

    def lint(self) -> list[Diagnostic]:
        """
        Run the lint rules common to every question type.

        Subclasses call `super().lint()` and add their own rules on top
        (dev/specs/to-do/lint-on-models.md). These are advisory
        (`warning`/`info`) checks only -- a rule serious enough to stop a
        document from loading at all is a model validator instead (see
        the module docstring).
        """
        diagnostics: list[Diagnostic] = []
        for field_name in ("title", "author", "comment"):
            diagnostics.extend(
                _lint.check_blank_text_field(getattr(self, field_name), field_name)
            )
        diagnostics.extend(_lint.check_uuid_version_and_variant(self.uuid))
        diagnostics.extend(_lint.check_tags(self.tags))
        diagnostics.extend(_lint.check_locale_language_subtag(self.locale))
        diagnostics.extend(_lint.check_stem_is_a_paragraph(self.stem))
        diagnostics.extend(_lint.check_stem_ellipsis_expanded(self.stem))
        diagnostics.extend(_lint.check_id_is_url_safe(self.id))
        diagnostics.extend(_lint.check_id_and_title_defined(self.id, self.title))
        return diagnostics

    def with_ids(self) -> Self:
        """
        Return a copy of this question with a derived id filled in for
        every choice that has none of its own (dev/specs/to-do/derived-ids.md).

        A question type with no choices (essay, numeric, short answer,
        ordering) has nothing to derive, so this returns a plain copy.
        Never changes `self`, never touches an id already written, and
        running it twice gives the same result as running it once.
        """
        return self.model_copy()



#
# Utilities
#

def _reinject_type_discriminators(model: BaseModel, data: dict[str, Any]) -> None:
    """
    Walk `model` and its already-dumped `data` in lockstep, re-adding the
    `type` discriminator `exclude_defaults` stripped from any nested
    `MdqModel` (a question inside an exam, a blank inside a fill-in).

    `model_dump`'s recursion applies `exclude_defaults` at every level, not
    just the top one `MdqModel.to_dict` patches up by hand, so a nested
    discriminated model loses `type` the same way the top-level one would
    without that patch. Mutates `data` in place; `model` itself is read-only.
    """
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        key = field.alias or name
        if key not in data:
            continue
        if isinstance(value, MdqModel):
            nested_data = data[key]
            _reinject_type_discriminators(value, nested_data)
            if "type" in type(value).model_fields and "type" not in nested_data:
                nested_data["type"] = getattr(value, "type")
        elif isinstance(value, list):
            for item, nested_data in zip(value, data[key], strict=False):
                if not isinstance(item, MdqModel):
                    continue
                _reinject_type_discriminators(item, nested_data)
                if "type" in type(item).model_fields and "type" not in nested_data:
                    nested_data["type"] = getattr(item, "type")


def clear_nones(d: dict[str, Any]) -> dict[str, Any]:
    """
    Return a copy of `d` with all `None` values removed.
    """
    return {k: v for k, v in d.items() if v is not None}




def can_inline_id(preamble: str | None, stem: str) -> bool:
    """
    Report whether an inline `[id]` prefix would parse back correctly.

    See the comment in `BaseQuestion._render_lines` for why: it only
    round-trips when the block receiving the prefix -- the *first* block
    of the combined preamble+stem sequence, per `MDQParser.split_intro`
    -- is a plain paragraph. That is the preamble's own first block when
    there is a preamble; otherwise it's the stem's first block, which is
    not guaranteed to be a paragraph either -- a `stem` may legally span
    more than one Markdown block (see `normalize_intro`) unless the
    caller already normalized the model.
    """
    combined = f"{preamble}\n\n{stem}" if preamble else stem
    blocks = _parser.reconstruct_blocks(combined.strip())
    return bool(blocks) and blocks[0][0] == "paragraph"


def normalize_paragraphs(src: str) -> str:
    """
    Normalize a string that is a Markdown paragraph or series of
    paragraphs.

    This is used to normalize the `preamble` and `epilogue` fields of
    questions, which are Markdown blocks but not full documents. Naively
    splitting on blank lines and stripping each chunk is not enough: a
    plain paragraph's soft-wrapped lines collapse to a single space once
    a render/parse round trip touches them (`MDQParser.raw_text`), while
    a list, blockquote, heading or code block survives byte-for-byte.
    `_parser.reconstruct_blocks` applies the parser's own rule for each
    block instead of guessing, so this function is a fixed point of
    render-then-parse: normalizing again after a round trip is a no-op.
    """
    return "\n\n".join(text for _, text in _parser.reconstruct_blocks(src))


def normalize_intro(preamble: str | None, stem: str) -> tuple[str | None, str]:
    """
    Normalize a question's `preamble` and `stem` fields together.

    `MDQParser.split_intro` does not care which field a block came from:
    it always assigns the *last* intro block to the stem and everything
    before it to the preamble. A `stem` spanning more than one Markdown
    block is legal per the schema (`schema/question-base.yaml`'s `stem`
    is just a non-empty string; `docs/question-types/generic.md` only
    *recommends* -- "SHOULD" -- a single paragraph), so it does not
    stay put on a render/parse round trip: every block but the last
    migrates into the preamble. Normalizing has to do the same to stay a
    fixed point of that round trip -- keeping only the first block
    (dropping the rest) or only the last would both be lossy, and either
    way would put the surviving block in the wrong field. Reconstructing
    `preamble` and `stem` together, rather than field by field, is what
    makes that possible.
    """
    combined = f"{preamble}\n\n{stem}" if preamble else stem
    blocks = _parser.reconstruct_blocks(combined.strip())
    if not blocks:
        return None, stem.strip()
    new_stem = blocks[-1][1]
    new_preamble = "\n\n".join(text for _, text in blocks[:-1]) or None
    return new_preamble, new_stem


def remove_trailing_ws(src: str) -> str:
    """
    Remove trailing whitespace from each line in a string.
    """
    return "\n".join(line.rstrip() for line in src.split("\n"))
