"""
The rubric item syntax (docs/references/rubric.md) and the annotations of a
test source (docs/question-types/code.md, "Annotations").

`parse_item_line` reads the first line of a rubric item, in a list of
`## [rubric]` or after the `mdq:` marker of an annotation. `scan_annotations`
reads the lines of a test source: its items, their regions and the problems
the lines have. Both are pure functions of text, so the parser (a Markdown
rubric list) and the models (the `text` of a test source and the `text` of a
rubric item, in every form of the document) share one reading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .._markdown import has_visible_character, split_lines
from ._choices import join_paragraph_lines

__all__ = [
    "Annotation",
    "AnnotationProblem",
    "Annotations",
    "RubricLine",
    "RubricSyntaxError",
    "check_criterion_start",
    "is_blank_line",
    "parse_item_line",
    "scan_annotations",
]

#: The `RUBRIC_VALUE` terminal of docs/references/rubric.md.
_VALUE_RE = re.compile(r"\[(?P<number>[+-]?(?:[1-9][0-9]*|0)(?:[.][0-9]+)?)\](?![(\[])")
#: A modifier: a lower case name between braces.
_MODIFIER_RE = re.compile(r"\{(?P<name>[a-z]+(?:-[a-z]+)*)\}")
#: A bracket that starts an inline, full or collapsed link.
_LINK_START_RE = re.compile(r"\[[^\[\]\r\n]*\][(\[]")
#: The `ANNOTATION_START` terminal of docs/question-types/code.md.
_ANNOTATION_START_RE = re.compile(r"[ \t!-/:-@\[-`{-~]*mdq:")

#: The modifiers of an annotation, and of an item of `## [rubric]`.
ANNOTATION_MODIFIERS = frozenset({"public", "example"})
LIST_MODIFIERS = frozenset({"manual"})

#: The codes a problem of an annotation can have.
ProblemCode = Literal["invalid-rubric-item", "blank-text"]


class RubricSyntaxError(ValueError):
    """A rubric item that breaks the syntax of docs/references/rubric.md."""


@dataclass(frozen=True)
class RubricLine:
    """
    The first line of a rubric item.

    Attributes:
        value: The number between brackets, `None` when the item has none.
        modifiers: The names between braces, in order, repeats included.
        criterion: The text after the value and the modifiers. It can be
            blank: the caller reports `blank-text`.
    """

    value: int | float | None
    modifiers: tuple[str, ...]
    criterion: str


def _number(text: str) -> int | float:
    """The value of the number of a `RUBRIC_VALUE`; `-0` is 0."""
    number: int | float = float(text) if "." in text else int(text)
    return 0 * number if number == 0 else number


def check_criterion_start(text: str) -> None:
    """
    Raise a `RubricSyntaxError` if `text`, a non-blank criterion, starts
    with a character that the criterion grammar excludes: `{`, `>`, a `!`
    not followed by `[`, or a `[` that does not start a link.
    """
    if text.startswith("{"):
        raise RubricSyntaxError(
            "a `{` that does not open a modifier: a criterion that starts "
            "with a brace writes `\\{`"
        )
    if text.startswith(">") or (text.startswith("!") and not text.startswith("![")):
        raise RubricSyntaxError(
            f"a criterion does not start with {text[0]!r}, which marks feedback "
            f"or a comment: write `\\{text[0]}`"
        )
    if text.startswith("[") and not _LINK_START_RE.match(text):
        raise RubricSyntaxError(
            "a criterion that starts with `[` must start a link: a malformed "
            "value such as `[ 3 ]`, `[3,5]` or `[50%]`, or a `[slug]`, is an "
            "error (write `\\[` for a literal bracket)"
        )


def parse_item_line(line: str) -> RubricLine:
    """
    Read the first line of a rubric item: an optional value, optional
    modifiers and the criterion (docs/references/rubric.md, "Item").

    Args:
        line: The line after the list marker, or after the `mdq:` marker.

    Raises:
        RubricSyntaxError: A `{` that does not open a modifier, or a
            criterion that starts with a character the grammar excludes.
    """
    rest = line.strip(" \t")
    value: int | float | None = None
    found = _VALUE_RE.match(rest)
    if found is not None:
        value = _number(found.group("number"))
        rest = rest[found.end() :].lstrip(" \t")
    modifiers: list[str] = []
    while rest.startswith("{"):
        modifier = _MODIFIER_RE.match(rest)
        if modifier is None:
            check_criterion_start(rest)  # raises: a brace that opens nothing
        else:
            modifiers.append(modifier.group("name"))
            rest = rest[modifier.end() :].lstrip(" \t")
    if rest:
        check_criterion_start(rest)
    return RubricLine(value, tuple(modifiers), rest)


def is_blank_line(line: str) -> bool:
    """Whether `line` is empty or has only spaces and tabs."""
    return not line.strip(" \t")


@dataclass(frozen=True)
class AnnotationProblem:
    """One violation of the rules of an annotation, on a line of the source."""

    code: ProblemCode
    message: str
    #: The line of the source, counted from 1.
    line: int


@dataclass(frozen=True)
class Annotation:
    """
    One rubric item that an annotation declares, with its region.

    Attributes:
        line: The line of the item line, counted from 1.
        end: The last line of the region of the item, counted from 1.
        value: The value of the item, `None` when it has none (it is 1).
        public: `{public}` or `{example}`.
        example: `{example}`.
        text: The criterion.
        feedback: The feedback, if any.
        comment: The comment, if any.
        annotation_lines: How many lines the item line, its feedback and its
            comment use.
    """

    line: int
    end: int
    value: int | float | None
    public: bool
    example: bool
    text: str
    feedback: str | None
    comment: str | None
    annotation_lines: int


@dataclass
class Annotations:
    """
    What `scan_annotations` found in the text of a test source.

    Attributes:
        lines: The lines of the text, without their endings.
        items: The valid items, in order. With `problems`, the regions are
            not reliable.
        problems: The violations of the rules, in order.
        annotated: Whether the source has at least one item line, valid or
            not.
    """

    lines: list[str]
    items: list[Annotation] = field(default_factory=list)
    problems: list[AnnotationProblem] = field(default_factory=list)
    annotated: bool = False

    def public_text(self, item: Annotation) -> tuple[str, int] | None:
        """
        The text of the region of `item` and its first line, for display
        (docs/question-types/code.md, "Public regions"). `None` when the
        region has no non-blank line after the lines of the annotation.
        """
        body = self.lines[item.line - 1 + item.annotation_lines : item.end]
        first = item.line + item.annotation_lines
        while body and is_blank_line(body[0]):
            body = body[1:]
            first += 1
        while body and is_blank_line(body[-1]):
            body = body[:-1]
        if not body:
            return None
        return "\n".join(body), first


def _split_observation(rest: str) -> tuple[Literal[">", "!"], str] | None:
    """The kind and content of a feedback or comment line, else `None`."""
    if rest.startswith(">"):
        return ">", rest[1:].strip(" \t")
    if rest.startswith("!") and not rest.startswith("!["):
        return "!", rest[1:].strip(" \t")
    return None


@dataclass
class _Draft:
    """An item line and the observation lines read after it so far."""

    line: int
    parsed: RubricLine | None = None
    lines: int = 1
    feedback: list[str] | None = None
    comment: list[str] | None = None
    #: The kind of the observation block that is open, if any.
    open_kind: str | None = None
    #: The kinds of the blocks that ended.
    closed: set[str] = field(default_factory=set)


_BLOCK_NAMES = {">": "feedback", "!": "comment"}


def scan_annotations(text: str) -> Annotations:
    """
    Read the annotations of the `text` of a test source
    (docs/question-types/code.md, "Annotations" and "Regions").

    The scan never raises: a violation is an `AnnotationProblem`. A line
    that has no annotation marker is ordinary text.
    """
    lines = split_lines(text)
    result = Annotations(lines)
    drafts: list[_Draft] = []
    #: The item that the next observation line can still extend.
    current: _Draft | None = None
    for number, line in enumerate(lines, start=1):
        marker = _ANNOTATION_START_RE.match(line)
        if marker is None:
            current = None
            continue
        rest = line[marker.end() :].strip(" \t")
        observation = _split_observation(rest)
        if observation is None:
            result.annotated = True
            current = _Draft(number)
            drafts.append(current)
            current.parsed = _read_item(rest, number, result)
            continue
        kind, content = observation
        if current is None:
            result.problems.append(
                AnnotationProblem(
                    "invalid-rubric-item",
                    "a feedback or comment line must follow an item line or "
                    "another line of the same annotation",
                    number,
                )
            )
            continue
        current.lines += 1
        if kind != current.open_kind:
            if kind in current.closed:
                result.problems.append(
                    AnnotationProblem(
                        "invalid-rubric-item",
                        f"an annotation has at most one {_BLOCK_NAMES[kind]} block",
                        number,
                    )
                )
                continue
            if current.open_kind is not None:
                current.closed.add(current.open_kind)
            current.open_kind = kind
            if kind == ">":
                current.feedback = []
            else:
                current.comment = []
        block = current.feedback if kind == ">" else current.comment
        assert block is not None  # opened above
        block.append(content)

    for draft in drafts:
        if draft.parsed is not None:
            _check_blocks(draft, result)
    result.items = _regions(drafts, len(lines))
    return result


def _read_item(rest: str, number: int, result: Annotations) -> RubricLine | None:
    """Parse the item line `rest`, or record why it fails and return `None`."""
    try:
        parsed = parse_item_line(rest)
    except RubricSyntaxError as exc:
        result.problems.append(AnnotationProblem("invalid-rubric-item", str(exc), number))
        return None
    names = parsed.modifiers
    bad = next((n for n in names if n not in ANNOTATION_MODIFIERS), None)
    if bad is not None:
        hint = (
            "`{manual}` is the binding of an item of `## [rubric]`"
            if bad == "manual"
            else "an annotation accepts `{public}` and `{example}`"
        )
        result.problems.append(
            AnnotationProblem("invalid-rubric-item", f"the modifier {{{bad}}}: {hint}", number)
        )
        return None
    if len(set(names)) != len(names):
        result.problems.append(
            AnnotationProblem("invalid-rubric-item", "a modifier repeats in one item", number)
        )
        return None
    if not has_visible_character(parsed.criterion):
        result.problems.append(
            AnnotationProblem(
                "blank-text", "the criterion of the annotation has no visible character", number
            )
        )
        return None
    return parsed


def _check_blocks(draft: _Draft, result: Annotations) -> None:
    """Record a feedback or comment of `draft` that has no visible character."""
    for name, block in (("feedback", draft.feedback), ("comment", draft.comment)):
        if block is not None and not has_visible_character(join_paragraph_lines(block)):
            result.problems.append(
                AnnotationProblem(
                    "blank-text",
                    f"the {name} of the annotation has no visible character",
                    draft.line,
                )
            )


def _regions(drafts: list[_Draft], total: int) -> list[Annotation]:
    """The valid items with the last line of their regions."""
    found: list[Annotation] = []
    for index, draft in enumerate(drafts):
        parsed = draft.parsed
        if parsed is None:
            continue
        end = drafts[index + 1].line - 1 if index + 1 < len(drafts) else total
        names = parsed.modifiers
        found.append(
            Annotation(
                line=draft.line,
                end=end,
                value=parsed.value,
                public="public" in names or "example" in names,
                example="example" in names,
                text=parsed.criterion,
                feedback=None if draft.feedback is None else join_paragraph_lines(draft.feedback),
                comment=None if draft.comment is None else join_paragraph_lines(draft.comment),
                annotation_lines=draft.lines,
            )
        )
    return found
