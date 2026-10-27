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
# Body-start detection.
ESSAY_TAG_RE = re.compile(r"^\[essay\]$")
SHORT_ANSWER_RE = re.compile(
    r"^\[short-answer(?:/(?P<variant>accept|reject))?\][ \t]*:[ \t]*(?P<rest>.*)$"
)
#: The start of a line that opens with the bare tag of a short answer and
#: goes on with something that is not a colon, a link or a reference.
SHORT_ANSWER_TAG_START_RE = re.compile(
    r"^(?P<tag>\[short-answer(?:/(?:accept|reject))?\])(?![ \t]*:)(?![(\[])(?P<after>.*)$"
)
#: The tag of a short answer with no pattern, written without a colon
#: (question-base.md, "Body tags").
SHORT_ANSWER_BARE_RE = re.compile(r"^\[short-answer(?:/(?P<variant>accept|reject))?\]$")
#: The `UNIT` terminal of docs/references/grammar.md: any character
#: except a `UNICODE_SPACE` and the brackets `(`, `)`, `[`, `]`. It admits
#: `µm`, `°C`, `km/h`, `Ω`.
UNIT_RE = rf"[^()\[\]{UNICODE_SPACE}]+"
NUMERIC_TAG_RE = re.compile(
    rf"^\[numeric(?:\((?P<unit>{UNIT_RE})\))?\][ \t]*:[ \t]*(?P<rest>.*)$"
)
# A blank definition tag. Deliberately permissive in `kind`: an
# unrecognized suffix must reach BLANK_KIND_RE and raise a real error,
# not fail to match and get swallowed by the epilogue.
BLANK_RE = re.compile(
    rf"^\[\^(?P<id>{SLUG_BODY_RE})(?:/(?P<kind>[^\]]+))?\][ \t]*:[ \t]*(?P<rest>.*)$"
)
#: The tag of a short answer blank with no pattern, written without a colon.
BLANK_BARE_RE = re.compile(
    rf"^\[\^(?P<id>{SLUG_BODY_RE})/short-answer(?:/(?P<variant>accept|reject))?\]$"
)
#: The text after the colon of a short-answer tag line.
TAG_REST_RE = re.compile(r"^[ \t]*\[[^\n]*?\][ \t]*:[ \t]*(?P<rest>.*)$")
# Validates that suffix. Units attach to `numeric` and to nothing else,
# and the accept/reject sublists to `short-answer` and nothing else --
# both restrictions are enforced by this alternation's shape rather than
# by a follow-up check (fill-in.md#blank-definitions).
BLANK_KIND_RE = re.compile(
    rf"^(?:"
    rf"(?P<numeric>numeric)(?:\((?P<unit>{UNIT_RE})\))?"
    r"|(?P<short>short-answer)(?:/(?P<variant>accept|reject))?"
    r")$"
)
ORDERING_TAG_RE = re.compile(r"^\[ordering\](?:[ \t]*:[ \t]*(?P<rest>.*))?$")
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
#: The label of a tag in lower case, with its form: `colon` or `bare`. Both
#: forms are valid for a short answer tag; the others have one form.
KNOWN_LABEL_RE = re.compile(
    rf"^(?:(?P<essay>essay)|(?P<ordering>ordering)"
    rf"|(?P<numeric>numeric(?:\({UNIT_RE}\))?)"
    r"|(?P<short>short-answer(?:/(?:accept|reject))?))$"
)
KNOWN_BLANK_KIND_RE = re.compile(
    rf"^(?:(?P<numeric>numeric(?:\({UNIT_RE}\))?)"
    r"|(?P<short>short-answer(?:/(?:accept|reject))?))$"
)
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


def read_short_answer_tag(text: str) -> ShortAnswerTag | None:
    """Read a short-answer tag line. `None` if `text` is no such tag."""
    m = SHORT_ANSWER_RE.match(text)
    if m is not None:
        return ShortAnswerTag(_role(m.group("variant")), m.group("rest"))
    m = SHORT_ANSWER_BARE_RE.match(text)
    if m is not None:
        return ShortAnswerTag(_role(m.group("variant")), None)
    return None


def read_blank_tag(text: str) -> BlankTag | None:
    """Read a blank definition tag line. `None` if `text` is no such tag."""
    m = BLANK_RE.match(text)
    if m is None:
        # An open short answer blank, written without a colon.
        bare = BLANK_BARE_RE.match(text)
        if bare is None:
            return None
        return ShortAnswerBlankTag(bare.group("id"), _role(bare.group("variant")), None)
    blank_id = m.group("id")
    rest = m.group("rest").strip(" \t")
    kind = m.group("kind")
    if kind is None:
        return ChoiceBlankTag(blank_id, rest)
    km = BLANK_KIND_RE.match(kind)
    if km is None:
        return UnrecognizedBlankTag(text)
    if km.group("numeric"):
        return NumericBlankTag(blank_id, km.group("unit"), rest)
    return ShortAnswerBlankTag(blank_id, _role(km.group("variant")), rest)


def read_body_tag(text: str) -> BodyTag | None:
    """Read the body or blank tag `text` is, or `None` if it is no tag."""
    if ESSAY_TAG_RE.match(text):
        return EssayTag()
    m = ORDERING_TAG_RE.match(text)
    if m is not None:
        return OrderingTag(m.group("rest"))
    short_answer = read_short_answer_tag(text)
    if short_answer is not None:
        return short_answer
    m = NUMERIC_TAG_RE.match(text)
    if m is not None:
        return NumericTag(m.group("unit"), m.group("rest"))
    return read_blank_tag(text)



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
        kind = _lower_label(reserved.group("kind"))
        known = KNOWN_BLANK_KIND_RE.match(kind)
        fixed = f"^{blank_id}/{kind}"
        needs_colon = bool(known and known.group("numeric"))
    else:
        fixed = _lower_label(label)
        known = KNOWN_LABEL_RE.match(fixed)
        needs_colon = bool(known and known.group("numeric"))
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
    if blank_id is None and known is not None and known.group("essay") and colon:
        raise ParseError(
            "the tag of an essay has no content: write `[essay]` without a colon"
        )
    if needs_colon and not colon:
        raise ParseError(f"the tag `{shown}` needs a colon and its content: `{shown}:`")
