"""
Frontmatter parsing shared by every question type and by exams.

Splitting the leading `---`-fenced YAML block from the body
(`_split_frontmatter`), loading it (`_load_frontmatter_yaml`), and
flagging keys nothing consumes (`_unknown_frontmatter_warnings`) are
generic enough that `_question.MDQParser` and `_exam.parse_exam` both
need them as-is. The per-question-type "which keys are known" tables
(`COMMON_QUESTION_KEYS`/`TYPE_QUESTION_KEYS`) live here too, next to the
warnings helper that reads them; the exam equivalents
(`EXAM_FRONTMATTER_KEYS` & co.) live in `_exam` instead, since nothing
outside exam parsing needs them.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

import yaml

from .._diagnostics import Diagnostic
from .._markdown import split_lines, strip_bom
from ..errors import ParseError

__all__ = [
    "COMMON_QUESTION_KEYS",
    "GRADED_QUESTION_TYPES",
    "PATTERN_LIST_KEYS",
    "TYPE_QUESTION_KEYS",
]

#: Frontmatter keys every question type accepts, read by
#: `MDQParser.apply_common_frontmatter` -- except `type`, which is read
#: directly in `MDQParser.parse_question` to pick the parsing path before
#: any state exists to apply frontmatter onto.
COMMON_QUESTION_KEYS = frozenset(
    {"type", "id", "uuid", "title", "author", "locale", "tags", "meta", "weight"}
)

#: The question types that choose a grading strategy and may be shuffled,
#: read by `MDQParser.apply_type_specific_frontmatter`. Mirrors
#: `mdq.models.GradedQuestionType`, which cannot be imported here since
#: `mdq.models` imports this package.
GRADED_QUESTION_TYPES = ("multiple-choice", "multiple-selection", "true-false", "fill-in")


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """
    Split source text into (raw frontmatter body, remaining document text).

    Returns (None, text) if there is no frontmatter block at all. A byte
    order mark at the start of `text` is removed in both cases.
    """

    text = strip_bom(text)
    if not text.startswith("---"):
        return None, text

    lines = split_lines(text, keepends=True)
    if lines[0].rstrip("\r\n") != "---":
        return None, text

    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            frontmatter = "".join(lines[1:i])
            rest = "".join(lines[i + 1 :])
            return frontmatter, rest

    # Unterminated frontmatter marker: treat the whole thing as a document
    # with no frontmatter, rather than silently swallowing the file.
    return None, text


def _extract_comment(frontmatter_text: str) -> str | None:
    """
    Pull out the leading `#`-comment block, per the `comment_string` rule
    in docs/question-types/generic.md. A blank line breaks it.
    """

    lines = split_lines(frontmatter_text)
    i = 0
    # base.md, "Frontmatter": a blank line holds only spaces and tabs.
    while i < len(lines) and lines[i].strip(" \t") == "":
        i += 1

    comment_lines = []
    while i < len(lines) and lines[i].startswith("#"):
        content = lines[i][1:]
        if content.startswith(" "):
            content = content[1:]
        comment_lines.append(content)
        i += 1

    return " ".join(comment_lines) if comment_lines else None


class _FrontmatterLoader(yaml.SafeLoader):
    """
    `yaml.SafeLoader`, minus YAML 1.1's base-60 int/float resolution, and
    with no duplicate keys.

    A key written twice in one mapping is an error (base.md,
    "Frontmatter"), not last-value-wins as in PyYAML. Keys a `<<` merge
    brings in may be overridden, as YAML intends.

    PyYAML's `SafeLoader` reads an unquoted `1:30` as the sexagesimal
    integer `90` (`1*60 + 30`) -- a YAML 1.1 rule that YAML 1.2 dropped.
    MDQ needs `1:30` to stay the string `"1:30"` so `HH:MM` durations
    need no quoting in the frontmatter (see `mdq._schedule`), so this
    loader keeps every other implicit resolver -- timestamps included --
    and only replaces `int`/`float`'s regex with one that drops the
    `H:MM[:SS]` alternative.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
                seen.add(key)
            except TypeError:  # an unhashable key; the base class reports it
                continue
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
        return super().construct_mapping(node, deep=deep)


#: `tag:yaml.org,2002:int`'s pattern, minus the sexagesimal alternative.
_INT_RE = re.compile(
    r"""^(?:[-+]?0b[0-1_]+
        |[-+]?0[0-7_]+
        |[-+]?(?:0|[1-9][0-9_]*)
        |[-+]?0x[0-9a-fA-F_]+)$""",
    re.VERBOSE,
)

#: `tag:yaml.org,2002:float`'s pattern, minus the sexagesimal alternative.
_FLOAT_RE = re.compile(
    r"""^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?
        |\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?
        |[-+]?\.(?:inf|Inf|INF)
        |\.(?:nan|NaN|NAN))$""",
    re.VERBOSE,
)

_FrontmatterLoader.yaml_implicit_resolvers = {
    first_char: [
        (tag, _INT_RE)
        if tag == "tag:yaml.org,2002:int"
        else (tag, _FLOAT_RE)
        if tag == "tag:yaml.org,2002:float"
        else (tag, regexp)
        for tag, regexp in resolvers
    ]
    for first_char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


class YamlSyntaxError(ParseError):
    """The frontmatter is not valid YAML, or repeats a key."""

    code = "yaml-syntax-error"


def load_yaml(text: str) -> Any:
    """
    Load MDQ YAML: a Markdown frontmatter or a YAML document. See
    `_FrontmatterLoader`.

    Raises:
        yaml.YAMLError: `text` is not valid YAML, or repeats a key.
    """
    return yaml.load(text, Loader=_FrontmatterLoader)


def _load_frontmatter_yaml(text: str) -> dict[str, Any]:
    """
    Raises:
        YamlSyntaxError: the frontmatter is not valid YAML, or repeats a key.
    """
    try:
        data = load_yaml(text)
    except yaml.YAMLError as exc:
        raise YamlSyntaxError(f"invalid YAML frontmatter: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _unknown_frontmatter_warnings(
    front: Mapping[str, Any],
    known: frozenset[str],
    path_prefix: tuple[str | int, ...] = (),
) -> list[Diagnostic]:
    """
    One `unknown-frontmatter-key` `Diagnostic` per key of `front` that is
    not in `known`, in frontmatter order.

    The parser is the only component that knows which keys it actually
    consumes, so it is the one reporting the ones it doesn't -- a typo
    like `auther:`, or a field that simply does not exist, otherwise
    vanishes without a trace.
    """
    return [
        Diagnostic(
            severity="warning",
            code="unknown-frontmatter-key",
            path=path_prefix + (key,),
            message=f"{key!r} is not a recognized frontmatter field and is ignored",
        )
        for key in front
        if key not in known
    ]


#: Frontmatter keys holding pattern lists, copied through verbatim.
PATTERN_LIST_KEYS = ("accept", "reject", "preAccept", "preReject")


def _copy_pattern_lists(front: Mapping[str, Any], doc: Any) -> None:
    """Copy the frontmatter's pattern lists onto the parsed document."""
    for key in PATTERN_LIST_KEYS:
        if key in front and key not in doc:
            doc[key] = front[key]


#: Per-type frontmatter keys, one entry per question type that reads
#: fields of its own beyond `COMMON_QUESTION_KEYS`. Each set is declared
#: next to the method that actually consumes it:
#:
#: * multiple-choice/multiple-selection/true-false/fill-in `shuffle` and
#:   `grading`: `MDQParser.apply_type_specific_frontmatter` (fill-in also
#:   reads its own `shuffle` and `diacritics` directly in
#:   `MDQParser.parse_fill_in_body`).
#: * essay `input`/`highlight`: `MDQParser.parse_essay_body`.
#: * ordering: `MDQParser.parse_ordering_body`.
#: * short-answer `openEnded`/`regex`/`diacritics`/pattern lists:
#:   `MDQParser.parse_short_answer_body` and `_copy_pattern_lists`.
#: * numeric `domain`/`decimalPlaces`/`unit`: `MDQParser.parse_numeric_body`.
TYPE_QUESTION_KEYS: dict[str, frozenset[str]] = {
    "multiple-choice": frozenset({"shuffle", "grading"}),
    "multiple-selection": frozenset({"shuffle", "grading"}),
    "true-false": frozenset({"shuffle", "grading"}),
    "fill-in": frozenset({"shuffle", "grading", "diacritics"}),
    "essay": frozenset({"input", "highlight"}),
    "ordering": frozenset(
        {"content", "highlight", "indentation", "unmatched", "normalizations"}
    ),
    "short-answer": frozenset({"openEnded", "regex", "diacritics", *PATTERN_LIST_KEYS}),
    "numeric": frozenset({"domain", "decimalPlaces", "unit"}),
}


def _question_frontmatter_warnings(
    front: Mapping[str, Any], question_type: str
) -> list[Diagnostic]:
    """`unknown-frontmatter-key` warnings for one question's frontmatter."""
    known = COMMON_QUESTION_KEYS | TYPE_QUESTION_KEYS.get(question_type, frozenset())
    return _unknown_frontmatter_warnings(front, known)


def _normalize_tags(tags: Any) -> Any:
    """
    generic.md: `tags` is a list, or a single comma-delimited string that
    is split into one. Exams and questions share the rule. Any other
    value is returned as it is, for the model to report.
    """
    if isinstance(tags, str):
        return [part.strip() for part in tags.split(",") if part.strip()]
    if isinstance(tags, list | tuple):
        return list(tags)
    return tags
