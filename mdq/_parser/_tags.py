"""
The tags of a question body: the regexes that read them, the typed values
`read_body_tag` returns, and the checks of the reserved tag labels
(question-base.md, "Body tags").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .._markdown import SLUG_BODY_RE, UNICODE_SPACE
from ..errors import ParseError

#
# Constants
#
#: One tag line: a bracketed label, then optionally a colon and the text
#: after it. `split_tag` reads it; `classify_label` checks the label.
TAG_SPLIT_RE = re.compile(
    r"^\[(?P<label>[^\]]+)\](?:[ \t]*(?P<colon>:)[ \t]*(?P<rest>.*))?$"
)
#: The start of a line that opens with the bare tag of a short answer and
#: goes on with something that is not a colon, a link or a reference.
SHORT_ANSWER_TAG_START_RE = re.compile(
    r"^(?P<tag>\[short-answer(?:/(?:accept|reject))?\])(?![ \t]*:)(?![(\[])(?P<after>.*)$"
)
#: The `UNIT` terminal of docs/references/grammar.md: any character
#: except a `UNICODE_SPACE` and the brackets `(`, `)`, `[`, `]`. It admits
#: `µm`, `°C`, `km/h`, `Ω`.
UNIT_RE = rf"[^()\[\]{UNICODE_SPACE}]+"
#: The text after the colon of a short-answer tag line.
TAG_REST_RE = re.compile(r"^[ \t]*\[[^\n]*?\][ \t]*:[ \t]*(?P<rest>.*)$")
#: The label of a tag in lower case, with its form: a body tag, or the kind
#: that follows `^id/` in a blank tag. Units attach to `numeric` and to
#: nothing else, and the accept/reject sublists to `short-answer` and
#: nothing else -- both restrictions are enforced by this alternation's
#: shape rather than by a follow-up check (fill-in.md#blank-definitions).
KIND_RE = re.compile(
    rf"(?:(?P<numeric>numeric)(?:\((?P<unit>{UNIT_RE})\))?"
    r"|(?P<short>short-answer)(?:/(?P<variant>accept|reject))?)"
)
#: A blank tag label. Deliberately permissive in `kind`: an unrecognized
#: kind must reach `classify_label` and give a real error, not fail to match
#: and get swallowed by the epilogue.
BLANK_LABEL_RE = re.compile(rf"^\^(?P<id>{SLUG_BODY_RE})(?:/(?P<kind>(?s:.+)))?$")
#: The names of the question types. A tag label that starts with one of them,
#: or that is a fill-in label `^id/...`, is reserved (question-base.md,
#: "Body tags").
TYPE_NAMES = (
    "essay",
    "numeric",
    "short-answer",
    "ordering",
    "true-false",
    "multiple-choice",
    "multiple-selection",
    "fill-in",
)
#: A reserved tag label: a type name followed by the end of the label, `/` or
#: `(`, or a fill-in label `^id/kind`. Case does not matter here, so that a
#: tag in the wrong case is found.
RESERVED_LABEL_RE = re.compile(
    rf"^(?:\^(?P<id>[^/]*)/(?P<kind>.*)|(?:{'|'.join(TYPE_NAMES)})(?:[/(].*)?)$",
    re.IGNORECASE,
)
#: A line in link reference definition form: a bracketed label and a colon.
TAG_COLON_LINE_RE = re.compile(r"^[ \t]*\[(?P<label>[^\[\]\r\n]+)\][ \t]*:")
#: A paragraph that holds only a bracketed label: a tag without a colon.
TAG_BARE_RE = re.compile(r"^[ \t]*\[(?P<label>[^\[\]\r\n]+)\][ \t]*$")
#: The frontmatter fields that look like a tag suffix.
FRONTMATTER_ONLY_SUFFIXES = {"preaccept": "preAccept", "prereject": "preReject"}


#: Whether a short-answer tag is `accept` (the default) or `reject`.
Role = Literal["accept", "reject"]


@dataclass(frozen=True)
class EssayTag:
    """`[essay]`."""


@dataclass(frozen=True)
class OrderingTag:
    """`[ordering]`; `rest` is the text after the colon, `None` with no colon."""

    rest: str | None


@dataclass(frozen=True)
class ShortAnswerTag:
    """`[short-answer]`, `[short-answer/accept]` or `[short-answer/reject]`."""

    role: Role
    #: The text after the colon, or `None` for a tag without a colon.
    rest: str | None


@dataclass(frozen=True)
class NumericTag:
    """`[numeric]:` or `[numeric(unit)]:`."""

    unit: str | None
    rest: str


@dataclass(frozen=True)
class ChoiceBlankTag:
    """`[^id]:`, the tag of a choice blank."""

    id: str
    rest: str


@dataclass(frozen=True)
class NumericBlankTag:
    """`[^id/numeric]:` or `[^id/numeric(unit)]:`."""

    id: str
    unit: str | None
    rest: str


@dataclass(frozen=True)
class ShortAnswerBlankTag:
    """`[^id/short-answer]` with an optional `/accept` or `/reject`."""

    id: str
    role: Role
    rest: str | None


@dataclass(frozen=True)
class UnrecognizedBlankTag:
    """A blank tag with a kind that no blank has; `text` is the tag line."""

    text: str


BlankTag = (
    ChoiceBlankTag | NumericBlankTag | ShortAnswerBlankTag | UnrecognizedBlankTag
)
BodyTag = EssayTag | OrderingTag | ShortAnswerTag | NumericTag | BlankTag


def _role(variant: str | None) -> Role:
    return "reject" if variant == "reject" else "accept"


def split_tag(line: str) -> tuple[str, bool, str] | None:
    """
    Split a tag line into the label between the brackets, whether a colon
    follows, and the text after the colon (empty with no colon). `None` if
    `line` is no bracketed label, alone or before a colon.
    """
    m = TAG_SPLIT_RE.match(line)
    if m is None:
        return None
    colon = m.group("colon") is not None
    return m.group("label"), colon, m.group("rest") if colon else ""


TagKind = Literal[
    "essay",
    "ordering",
    "numeric",
    "short-answer",
    "choice-blank",
    "numeric-blank",
    "short-answer-blank",
    "unrecognized-blank",
]


@dataclass(frozen=True)
class Label:
    """What a tag label is, as `classify_label` reads it."""

    kind: TagKind
    role: Role = "accept"
    unit: str | None = None
    #: The id of a blank tag.
    blank_id: str | None = None

    @property
    def is_known(self) -> bool:
        """Whether the label is a tag of some question type."""
        return self.kind != "unrecognized-blank"

    @property
    def needs_colon(self) -> bool:
        """Whether the tag has content, so it is written with a colon."""
        return self.kind in ("numeric", "numeric-blank", "choice-blank", "unrecognized-blank")


def classify_label(label: str) -> Label | None:
    """
    Read the text between the brackets of a tag line. `None` if it is the
    label of no tag. The case matters: `Essay` is no tag. A blank label of
    an unknown kind is `unrecognized-blank`, so that the caller reports it.
    """
    if label == "essay":
        return Label("essay")
    if label == "ordering":
        return Label("ordering")
    blank = BLANK_LABEL_RE.match(label)
    kind_text = label
    blank_id = None
    if blank is not None:
        blank_id = blank.group("id")
        if blank.group("kind") is None:
            return Label("choice-blank", blank_id=blank_id)
        kind_text = blank.group("kind")
    elif label.startswith("^"):
        return None
    km = KIND_RE.fullmatch(kind_text)
    if km is None:
        return Label("unrecognized-blank") if blank is not None else None
    role = _role(km.group("variant"))
    if km.group("numeric"):
        return Label("numeric-blank" if blank else "numeric", unit=km.group("unit"), blank_id=blank_id)
    return Label("short-answer-blank" if blank else "short-answer", role=role, blank_id=blank_id)


def read_body_tag(text: str) -> BodyTag | None:
    """Read the body or blank tag `text` is, or `None` if it is no tag."""
    split = split_tag(text)
    if split is None:
        return None
    label, colon, rest = split
    found = classify_label(label)
    if found is None or (found.needs_colon and not colon):
        return None
    blank_id = found.blank_id or ""
    match found.kind:
        case "essay":
            return None if colon else EssayTag()
        case "ordering":
            return OrderingTag(rest if colon else None)
        case "numeric":
            return NumericTag(found.unit, rest)
        case "short-answer":
            return ShortAnswerTag(found.role, rest if colon else None)
        case "choice-blank":
            return ChoiceBlankTag(blank_id, rest.strip(" \t"))
        case "numeric-blank":
            return NumericBlankTag(blank_id, found.unit, rest.strip(" \t"))
        case "short-answer-blank":
            return ShortAnswerBlankTag(
                blank_id, found.role, rest.strip(" \t") if colon else None
            )
        case "unrecognized-blank":
            return UnrecognizedBlankTag(text)


def read_short_answer_tag(text: str) -> ShortAnswerTag | None:
    """Read a short-answer tag line. `None` if `text` is no such tag."""
    tag = read_body_tag(text)
    return tag if isinstance(tag, ShortAnswerTag) else None


def is_short_answer_colon_tag(text: str) -> bool:
    """Whether `text` is a short-answer tag written with a colon."""
    tag = read_short_answer_tag(text)
    return tag is not None and tag.rest is not None


def is_blank_colon_tag(text: str) -> bool:
    """Whether `text` is a blank tag written with a colon, of any kind."""
    split = split_tag(text)
    return split is not None and split[1] and read_blank_tag(text) is not None


def read_blank_tag(text: str) -> BlankTag | None:
    """Read a blank definition tag line. `None` if `text` is no such tag."""
    tag = read_body_tag(text)
    if isinstance(tag, ChoiceBlankTag | NumericBlankTag | ShortAnswerBlankTag | UnrecognizedBlankTag):
        return tag
    return None


def _lower_label(label: str) -> str:
    """
    The label in lower case. The unit of `numeric(unit)` keeps its case:
    `Pa` and `pa` are different units.
    """
    if label.lower().startswith("numeric("):
        return "numeric" + label[len("numeric") :]
    return label.lower()


def tag_lines(text: str, lines: list[str]) -> list[tuple[str, bool]]:
    """
    The `(label, has_colon)` pairs of the tag-like lines of a paragraph: each
    line in link reference definition form, and the whole paragraph when it
    holds only a bracketed label.

    Args:
        text: The text of the paragraph, as `BlockReader.raw_text` gives it.
        lines: The raw source lines of the paragraph.
    """
    found: list[tuple[str, bool]] = []
    bare = TAG_BARE_RE.match(text)
    if bare is not None:
        found.append((bare.group("label"), False))
    for line in lines:
        colon = TAG_COLON_LINE_RE.match(line)
        if colon is not None:
            found.append((colon.group("label"), True))
    return found


def check_bare_tag_alone(text: str, lines: list[str]) -> None:
    """
    Raise a `ParseError` if a paragraph starts with the bare tag
    `[short-answer]` (or its `/accept` or `/reject` form) and holds more
    text, on the same line or on a lazy line: the bare tag is a paragraph of
    its own (short-answer.md, "Block with no pattern").

    Args:
        text: The text of the paragraph, as `BlockReader.raw_text` gives it.
        lines: The raw source lines of the paragraph.
    """
    m = SHORT_ANSWER_TAG_START_RE.match(lines[0]) if lines else None
    if m is None:
        return
    after = m.group("after").strip(" \t")
    if after or len(lines) > 1:
        raise ParseError(
            f"text follows the tag {m.group('tag')} in its paragraph: write "
            f"`{m.group('tag')}:` before a pattern, or leave the tag "
            "alone in its paragraph"
        )


def is_reserved_label(label: str) -> bool:
    """Whether `label` is reserved: it starts with a type name or is `^id/...`."""
    return RESERVED_LABEL_RE.match(label) is not None


def is_tag_line(line: str) -> bool:
    """
    Whether `line` starts with a tag that `LAZY_START` excludes
    (grammar.md, "Feedback and comment lines"): a reserved label or a blank
    label `^id`, between brackets, and a colon. A line with four or more
    columns of indentation is continuation text, so it is no tag line.
    """
    if len(line) - len(line.lstrip(" ")) >= 4 or line.startswith("\t"):
        return False
    m = TAG_COLON_LINE_RE.match(line)
    if m is None:
        return False
    label = m.group("label")
    return label.startswith("^") or is_reserved_label(label)


def tag_after_content_message(line: str) -> str:
    """The `ParseError` message for a tag `line` right after the content."""
    text = line.strip(" \t")
    return (
        f"the line {text!r} is a tag, so it cannot continue the content before "
        "it; add a blank line before the tag"
    )


def check_no_tag_in_content(lines: list[str]) -> None:
    """
    Raise a `ParseError` if one of the content lines that follow the tag
    line is a tag line itself (grammar.md, "Feedback and comment lines").

    Args:
        lines: The lines of the tag paragraph after its first line.
    """
    for line in lines:
        if is_tag_line(line):
            raise ParseError(tag_after_content_message(line))


def check_tag_label(label: str, colon: bool) -> None:
    """
    Raise a `ParseError` if `label`, the text between the brackets of a
    tag-like line, is reserved but is not a valid tag (question-base.md,
    "Body tags"). Do nothing for a label that is not reserved, such as the
    label of an ordinary link reference definition.

    Args:
        label: The text between the brackets.
        colon: Whether a colon follows the closing bracket.

    Raises:
        ParseError: The label has the wrong case, has an unknown suffix, is
            a frontmatter field, or has the wrong form for its tag.
    """
    reserved = RESERVED_LABEL_RE.match(label)
    if reserved is None:
        return
    written = f"`[{label}]{':' if colon else ''}`"
    blank_id = reserved.group("id")
    if blank_id is not None:
        if not re.fullmatch(SLUG_BODY_RE, blank_id):
            raise ParseError(
                f"{written} has an invalid blank id: it is a lower case slug, as in `[^capital/short-answer]:`"
            )
        fixed = f"^{blank_id}/{_lower_label(reserved.group('kind'))}"
    else:
        fixed = _lower_label(label)
    found = classify_label(fixed)
    known = found if found is not None and found.is_known else None
    needs_colon = known is not None and known.needs_colon
    if known is None:
        suffix = label.rsplit("/", 1)[-1].lower()
        if suffix in FRONTMATTER_ONLY_SUFFIXES:
            field = FRONTMATTER_ONLY_SUFFIXES[suffix]
            raise ParseError(
                f"unknown tag {written}: `{field}` is a field of the frontmatter "
                "only, not a tag"
            )
        raise ParseError(
            f"unknown tag {written}: a tag name that starts with a type name is "
            "reserved, see the tags of the question types"
        )
    shown = f"[{fixed}]{':' if colon else ''}"
    if fixed != label:
        raise ParseError(f"tags are lower case: write `{shown}`")
    if known is not None and known.kind == "essay" and colon:
        raise ParseError(
            "the tag of an essay has no content: write `[essay]` without a colon"
        )
    if needs_colon and not colon:
        raise ParseError(f"the tag `{shown}` needs a colon and its content: `{shown}:`")
