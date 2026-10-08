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

    # A joined string with no character is not stored; blank text is.
    return " ".join(comment_lines) or None


class _FrontmatterLoader(yaml.SafeLoader):
    """
    `yaml.SafeLoader` with the implicit resolvers of the YAML 1.2 Core
    schema (base.md, "Frontmatter") and with no duplicate keys.

    A key written twice in one mapping is an error (base.md,
    "Frontmatter"), not last-value-wins as in PyYAML.

    PyYAML implements YAML 1.1: `yes`/`on` are booleans, `1:30` is the
    sexagesimal integer 90, `2026-03-10` is a date, `010` is octal. MDQ
    documents follow the Core schema, where all of these are plain
    strings or decimal numbers, so the resolvers are replaced wholesale
    (`_CORE_RESOLVERS`) and the int constructor reads decimal, `0o` and
    `0x` only (`_construct_core_int`).
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
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


#: The implicit resolvers of the YAML 1.2 Core schema
#: (https://yaml.org/spec/1.2.2/#103-core-schema), in place of PyYAML's
#: YAML 1.1 ones: no `yes`/`no`/`on`/`off` booleans, no timestamps, no
#: base-60 `1:30`, no `0b`/`_` numbers, no merge key. Each pattern is
#: anchored by PyYAML; the first characters are the ones a match can start
#: with.
_CORE_RESOLVERS: list[tuple[str, re.Pattern[str], str]] = [
    ("tag:yaml.org,2002:null", re.compile(r"^(?:~|null|Null|NULL|)$"), "~nN"),
    ("tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), "tTfF"),
    (
        "tag:yaml.org,2002:int",
        re.compile(r"^(?:[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$"),
        "-+0123456789",
    ),
    (
        "tag:yaml.org,2002:float",
        re.compile(
            r"""^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?
                |[-+]?\.(?:inf|Inf|INF)
                |\.(?:nan|NaN|NAN))$""",
            re.VERBOSE,
        ),
        "-+.0123456789",
    ),
]



def _core_resolver_table() -> dict[str | None, list[tuple[str, re.Pattern[str]]]]:
    """PyYAML's `yaml_implicit_resolvers` table for `_CORE_RESOLVERS`."""
    table: dict[str | None, list[tuple[str, re.Pattern[str]]]] = {}
    for tag, regexp, first in _CORE_RESOLVERS:
        for char in first:
            table.setdefault(char, []).append((tag, regexp))
    # The empty scalar resolves to null: PyYAML keys it under `None`.
    table[None] = [(_CORE_RESOLVERS[0][0], _CORE_RESOLVERS[0][1])]
    return table


_FrontmatterLoader.yaml_implicit_resolvers = _core_resolver_table()


class _FrontmatterDumper(yaml.SafeDumper):
    """
    `yaml.SafeDumper` with the Core schema resolvers, so that a string the
    Core schema would read as something else (`"0e0"`, `"010"`, `"true"`)
    is quoted, and one YAML 1.1 would (`yes`, `1:30`, a date) is not.
    """


_FrontmatterDumper.yaml_implicit_resolvers = _core_resolver_table()


def _construct_core_int(loader: yaml.SafeLoader, node: yaml.Node) -> int:
    """
    YAML 1.2 Core integers: decimal, `0o` octal, `0x` hex. PyYAML's own
    constructor reads a leading zero as YAML 1.1 octal (`010` is 8), and
    `_` separators and base-60; the Core schema has none of these.
    """
    value = loader.construct_scalar(node)
    assert isinstance(value, str)
    if value.startswith("0o"):
        return int(value[2:], 8)
    if value.startswith("0x"):
        return int(value[2:], 16)
    return int(value, 10)


_FrontmatterLoader.add_constructor("tag:yaml.org,2002:int", _construct_core_int)


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


def dump_yaml(data: Any) -> str:
    """
    Dump `data` as YAML that `load_yaml` reads back unchanged: block style,
    sorted keys, strings quoted exactly when the Core schema needs it.
    """
    return yaml.dump(data, Dumper=_FrontmatterDumper)


def _load_frontmatter_yaml(
    text: str, keep_null: tuple[str, ...] = ()
) -> dict[str, Any]:
    """
    Load the frontmatter mapping. A key with a `null` value is the same
    as an absent key (base.md, "Frontmatter"), so it is dropped, except
    the keys in `keep_null`.

    Raises:
        YamlSyntaxError: the frontmatter is not valid YAML, or repeats a key.
    """
    try:
        data = load_yaml(text)
    except yaml.YAMLError as exc:
        raise YamlSyntaxError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if v is not None or k in keep_null}


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
#:   `MDQParser.parse_fill_in_body`). Fill-in `preAccept`/`preReject` are
#:   maps from blank id to pattern list:
#:   `MDQParser.distribute_blank_pattern_lists` moves them onto the blanks.
#: * essay `input`/`highlight`: `MDQParser.parse_essay_body`.
#: * ordering: `MDQParser.parse_ordering_body`.
#: * short-answer `diacritics`/`unmatched`/`incorrectFeedback`/pattern lists:
#:   `MDQParser.parse_short_answer_body` and `_copy_pattern_lists`.
#: * numeric `domain`/`decimalPlaces`/`unit`: `MDQParser.parse_numeric_body`.
TYPE_QUESTION_KEYS: dict[str, frozenset[str]] = {
    "multiple-choice": frozenset({"shuffle", "grading"}),
    "multiple-selection": frozenset({"shuffle", "grading"}),
    "true-false": frozenset({"shuffle", "grading"}),
    "fill-in": frozenset(
        {"shuffle", "grading", "diacritics", "unmatched", "preAccept", "preReject"}
    ),
    "essay": frozenset({"input", "highlight"}),
    "ordering": frozenset(
        {"content", "highlight", "indentation", "unmatched", "normalizations"}
    ),
    "short-answer": frozenset(
        {"diacritics", "unmatched", "incorrectFeedback", *PATTERN_LIST_KEYS}
    ),
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
