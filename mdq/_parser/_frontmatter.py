"""
Frontmatter parsing shared by every question type and by exams.

Splitting the leading `---`-fenced YAML block from the body
(`_split_frontmatter`), loading it (`_load_frontmatter_yaml`), and
flagging the keys a frontmatter may not hold
(`_invalid_frontmatter_fields`) are generic enough that
`_question.MDQParser` and `_exam.parse_exam` both need them as-is. The
allowed keys come from the frontmatter schemas of the bundle
(`$defs/frontmatter-<type>`), which the spec builds from the frontmatter
tables.
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources
from typing import Any, Mapping

import yaml

from .._diagnostics import Diagnostic
from .._markdown import split_lines, strip_bom
from ..errors import ParseError

__all__: list[str] = []


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

    # The joined string is stripped; an empty result is not stored.
    return " ".join(comment_lines).strip() or None


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


def _construct_core_int(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> int:
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


def _load_frontmatter_yaml(text: str) -> dict[str, Any]:
    """
    Load the frontmatter mapping. A key with a `null` value is the same
    as an absent key (base.md, "Frontmatter"), so it is dropped.

    Raises:
        YamlSyntaxError: the frontmatter is not valid YAML, or repeats a key.
    """
    try:
        data = load_yaml(text)
    except yaml.YAMLError as exc:
        raise YamlSyntaxError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if v is not None}


@cache
def _bundle() -> dict[str, Any]:
    """The bundled schema shipped with the package (`mdq.schema.json`)."""
    text = resources.files("mdq").joinpath("mdq.schema.json").read_text("utf-8")
    bundle: dict[str, Any] = json.loads(text)
    return bundle


@cache
def _frontmatter_fields(document_type: str) -> frozenset[str]:
    """
    The keys a frontmatter may hold, from the frontmatter schema of the
    bundle (`$defs/frontmatter-<type>`, built from the frontmatter tables).
    """
    schema = _bundle()["$defs"][f"frontmatter-{document_type}"]
    return frozenset(schema["properties"])


@cache
def _schema_fields(document_type: str) -> frozenset[str]:
    """
    Every field of the document type in the bundle, wherever its schema
    declares it. The fields that are not in the frontmatter schema are the
    ones the body sets.
    """
    defs = _bundle()["$defs"]
    fields: set[str] = set()
    for stem in (document_type, "question-base"):
        schema = defs[stem]
        fields.update(schema.get("properties", {}))
        for member in schema.get("allOf", []):
            if isinstance(member, dict):
                fields.update(member.get("properties", {}))
    return frozenset(fields)


#: How the body sets each field a frontmatter cannot hold, as a hint for
#: the `invalid-frontmatter-field` message. A `(type, field)` entry takes
#: precedence over the entry of the `field` alone.
_BODY_SYNTAX: dict[str | tuple[str, str], str] = {
    "stem": "the stem is the text before the body",
    "epilogue": "the epilogue is the text after the body",
    "comment": "the comment is the leading `#` lines of the frontmatter",
    "choices": "write the choices as the items of a list, such as `* [*] Brasília`",
    "answer": "write `[numeric(unit)]: value +- tolerance`",
    "tolerance": "write `[numeric(unit)]: value +- tolerance`",
    "unit": "write `[numeric(unit)]: value`",
    ("short-answer", "accept"): "write a `[short-answer]:` block",
    ("short-answer", "reject"): "write a `[short-answer/reject]:` block",
    ("ordering", "accept"): "write a `## [accept]` section",
    ("ordering", "reject"): "write a `## [reject]` section",
    ("ordering", "content"): "a code block implies `code`, a list implies `text`",
    ("ordering", "highlight"): "the language of the `[ordering]:` fence is the highlight",
    "lines": "write the lines under the `[ordering]:` tag",
    "extra": "write a `## [extra]` section",
    "blanks": "write `[^id]` markers in the stem and `[^id]:` definitions",
    "answerKey": "write a `## [answer-key]` section",
    "instructions": "write the text between the title and the first question",
    "questions": "write the questions as blocks separated by `===`",
}


def _invalid_frontmatter_fields(
    front: Mapping[str, Any],
    document_type: str,
    path_prefix: tuple[str | int, ...] = (),
) -> list[Diagnostic]:
    """
    One `invalid-frontmatter-field` error `Diagnostic` per key of `front`
    that is not in the frontmatter schema of `document_type`, in
    frontmatter order (base.md, "Frontmatter"). A `document_type` with no
    schema, such as `quiz`, has no diagnostic here.

    The message says when the key is a field the body sets, and how.
    """
    if f"frontmatter-{document_type}" not in _bundle()["$defs"]:
        return []  # not a document type: the schema reports the `type`
    allowed = _frontmatter_fields(document_type)
    body_fields = _schema_fields(document_type) - allowed
    diagnostics = []
    for key in front:
        if key in allowed:
            continue
        if key in body_fields:
            hint = _BODY_SYNTAX.get((document_type, key)) or _BODY_SYNTAX.get(key)
            message = f"{key!r} is a field the body sets, not a frontmatter field"
            message += f": {hint}" if hint else ""
        else:
            message = f"{key!r} is not a frontmatter field of a {document_type}"
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="invalid-frontmatter-field",
                path=path_prefix + (key,),
                message=message,
            )
        )
    return diagnostics


#: Frontmatter keys the parser reads one by one, for every document type.
_TRANSFORMED_KEYS = frozenset({"type", "id", "tags", "normalizations", "start", "duration"})

#: Further keys a fill-in question or a numeric question reads itself: the
#: frontmatter maps go onto the blanks, and the numeric fields weigh the
#: frontmatter against the body.
_TRANSFORMED_KEYS_OF_TYPE: dict[str, frozenset[str]] = {
    "fill-in": frozenset(
        {"domain", "decimalPlaces", "preAccept", "preReject", "incorrectFeedback"}
    ),
    "numeric": frozenset({"domain", "decimalPlaces"}),
}


def copy_passthrough_fields(
    front: Mapping[str, Any], doc: dict[str, Any], document_type: object
) -> None:
    """
    Copy onto `doc` the frontmatter fields that need no transform: those
    the frontmatter table of `document_type` allows, except the keys read
    one by one (`_TRANSFORMED_KEYS`). A field the body already set is kept.
    A `document_type` with no frontmatter schema copies nothing.
    """
    if not isinstance(document_type, str) or (
        f"frontmatter-{document_type}" not in _bundle()["$defs"]
    ):
        return
    skipped = _TRANSFORMED_KEYS | _TRANSFORMED_KEYS_OF_TYPE.get(document_type, frozenset())
    for key in sorted(_frontmatter_fields(document_type) - skipped):
        if key in front and key not in doc:
            doc[key] = front[key]


def common_frontmatter(front: Mapping[str, Any], comment: str | None) -> dict[str, Any]:
    """
    The document fields that exams and questions take from the frontmatter
    and from its leading comment (base.md, "Frontmatter").

    Values pass through unconverted: `id: 2024` is not a string, and the
    model reports it. A null `id` or `tags` is absent.
    """
    fields: dict[str, Any] = {}
    if comment is not None:
        fields["comment"] = comment
    if front.get("id") is not None:
        fields["id"] = front["id"]
    for key in ("uuid", "title", "author", "locale"):
        if key in front:
            fields[key] = front[key]
    if front.get("tags") is not None:
        fields["tags"] = _normalize_tags(front["tags"])
    if "meta" in front:
        fields["meta"] = front["meta"]
    return fields


def _normalize_tags(tags: object) -> object:
    """
    generic.md: `tags` is a list, or a single comma-delimited string that
    is split into one. Exams and questions share the rule. An empty part
    after a final comma is dropped; any other empty part is kept, for the
    model to report as `blank-text`. Any other value is returned as it
    is, for the model to report.
    """
    if isinstance(tags, str):
        parts = [part.strip() for part in tags.split(",")]
        if len(parts) > 1 and parts[-1] == "":
            parts.pop()
        return parts
    return _normalize_list(tags)


def _normalize_list(value: object) -> object:
    """
    A list, or a single comma-delimited string split into one, with the
    empty parts dropped. Any other value is returned as it is.
    """
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list | tuple):
        return list(value)
    return value
