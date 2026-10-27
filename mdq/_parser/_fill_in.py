"""
The body of a fill-in question: the `[^id]:` blank definitions, and the
frontmatter maps that go onto the blanks they key.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import assert_never, cast

from markdown_it.tree import SyntaxTreeNode as Node

from .._markdown import starts_after
from ..errors import ParseError, UndefinedBlank
from ..types import BlankDict, NumericBlankDict, ScoredChoiceDict, ShortAnswerBlankDict
from ._blocks import BlockCursor, parse_item_list
from ._choices import build_choices
from ._numeric import _parse_numeric_expression, numeric_fields
from ._short_answer import parse_answer_block
from ._tags import (
    BlankTag,
    ChoiceBlankTag,
    NumericBlankTag,
    ShortAnswerBlankTag,
    UnrecognizedBlankTag,
    check_no_tag_in_content,
    is_blank_colon_tag,
    read_blank_tag,
)


def parse_fill_in_body(
    cursor: BlockCursor, front: Mapping[str, object], tag: BlankTag, tag_node: Node
) -> dict[str, object]:
    """
    Read the fill-in fields from a run of `[^id...]:` definitions.

    A slug may be defined more than once -- a short answer blank
    spreads its accept block and its reject block over
    separate definitions -- so definitions accumulate into one blank
    per slug, keyed by the order the slug is first seen.

    Raises:
        ParseError: an unrecognized or misplaced tag suffix, a slug
            whose definitions disagree about the blank's kind, a
            repeated definition of the same form.
    """
    doc: dict[str, object] = {}

    numeric_maps = numeric_blank_maps(front)
    blanks: dict[str, BlankDict] = {}
    #: The (blank id, `accept`/`reject`) short-answer definitions seen.
    defined: set[tuple[str, str]] = set()
    while True:
        match tag:
            case UnrecognizedBlankTag(text=text):
                raise ParseError(f"unrecognized blank definition: {text!r}")
            case ChoiceBlankTag(id=blank_id, rest=rest):
                next_node = cursor.peek()
                if not rest and next_node is not None and next_node.type == "bullet_list":
                    if not starts_after(tag_node, next_node):
                        raise ParseError(
                            f"the choice list of [^{blank_id}] must start on the "
                            f"line right after its tag, with no blank line in between"
                        )
                    cursor.read()
                    cursor.check_no_adjacent_list(next_node)
                    raw_choices = parse_item_list(cursor.reader, next_node)
                    # The choices of a multiple-choice blank are scored choices.
                    choices = cast(
                        "list[ScoredChoiceDict]",
                        build_choices(
                            "multiple-choice",
                            raw_choices,
                            ("blanks", _blank_index(blanks, blank_id)),
                        ),
                    )
                    _add_blank(
                        blanks,
                        {"id": blank_id, "type": "multiple-choice", "choices": choices},
                    )
                elif not rest:
                    raise ParseError(
                        f"the choice blank [^{blank_id}]: has no choice list: the "
                        f"list starts on the line right after the tag"
                    )
                else:
                    raise ParseError(
                        f"the tag line of the choice blank [^{blank_id}] must be "
                        f"empty and the choice list must follow it; text after the "
                        f"colon is not a choice. For a text answer, write "
                        f"[^{blank_id}/short-answer]: {rest}"
                    )
            case NumericBlankTag(id=blank_id, unit=unit, rest=rest):
                check_no_tag_in_content(cursor.reader.raw_lines(tag_node)[1:])
                parsed = _parse_numeric_expression(rest)
                # A numeric blank is graded exactly like a numeric
                # question (fill-in.md), so the domain is inferred from
                # the written representation there too.
                blank: NumericBlankDict = {
                    "id": blank_id,
                    "type": "numeric",
                    "answer": parsed["answer"],
                }
                if unit:
                    blank["unit"] = unit
                # fill-in.md, "Frontmatter": the `domain` and `decimalPlaces`
                # maps win over the inferred values, as they do in a numeric
                # question (numeric.md, "Number type/domain").
                declared = {
                    key: numeric_maps[key][blank_id]
                    for key in ("domain", "decimalPlaces")
                    if blank_id in numeric_maps[key]
                }
                cast("dict[str, object]", blank).update(numeric_fields(parsed, declared))
                if "tolerance" in parsed:
                    blank["tolerance"] = parsed["tolerance"]
                _add_blank(blanks, blank)
            case ShortAnswerBlankTag(id=blank_id, role=role, rest=rest):
                if (blank_id, role) in defined:
                    raise ParseError(
                        f"repeated [^{blank_id}/short-answer] {role} definition"
                    )
                defined.add((blank_id, role))
                patterns = parse_answer_block(
                    cursor,
                    tag_node,
                    rest,
                    reject=role == "reject",
                    tag=f"^{blank_id}/short-answer",
                    path=("blanks", _blank_index(blanks, blank_id), role),
                )
                sa_blank: ShortAnswerBlankDict = {
                    "id": blank_id,
                    "type": "short-answer",
                }
                if patterns and role == "accept":
                    sa_blank["accept"] = patterns
                elif patterns:
                    sa_blank["reject"] = patterns
                _add_blank(blanks, sa_blank)
            case _:
                assert_never(tag)

        node = cursor.peek()
        cursor.reader.check_no_setext_tag(node, is_blank_colon_tag)
        if node is None or node.type != "paragraph":
            break
        next_tag = read_blank_tag(cursor.reader.raw_text(node))
        if next_tag is None:
            break
        tag = next_tag
        tag_node = cursor.read()

    distribute_blank_pattern_lists(front, blanks)
    distribute_numeric_blank_maps(numeric_maps, blanks)
    doc["blanks"] = list(blanks.values())
    return doc


def numeric_blank_maps(front: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    """
    The frontmatter `domain` and `decimalPlaces` maps of a fill-in
    question (fill-in.md, "Frontmatter"), each from a blank id to the
    value of the field of the same name. A missing map is empty. The
    values are not checked here: the schema checks them on the blank.

    Raises:
        ParseError: a map is not a mapping.
    """
    maps: dict[str, Mapping[str, object]] = {}
    for key in ("domain", "decimalPlaces"):
        mapping = front.get(key, {})
        if not isinstance(mapping, Mapping):
            raise ParseError(
                f"frontmatter {key!r} of a fill-in question must map blank "
                "ids to values",
                path=(key,),
            )
        maps[key] = mapping
    return maps


def distribute_numeric_blank_maps(
    maps: Mapping[str, Mapping[str, object]], blanks: dict[str, BlankDict]
) -> None:
    """
    Check the keys of the `domain` and `decimalPlaces` maps against the
    blanks. A numeric blank took its values when it was built; a key
    that is the id of another kind of blank puts the value on that
    blank, where the schema rejects it.

    Raises:
        UndefinedBlank: a key is not the id of a blank in `blanks`.
    """
    for key, mapping in maps.items():
        for blank_id, value in mapping.items():
            blank = blanks.get(blank_id)
            if blank is None:
                raise UndefinedBlank(str(blank_id), key)
            if blank["type"] != "numeric":
                _set_field(blank, key, value)


def distribute_blank_pattern_lists(
    front: Mapping[str, object], blanks: dict[str, BlankDict]
) -> None:
    """
    Move the frontmatter `preAccept`/`preReject`/`incorrectFeedback`
    maps onto the blanks they key (fill-in.md, "Frontmatter"). Each map
    goes from a blank id to a pattern list (a string for
    `incorrectFeedback`); the value becomes the field of the same name
    of that blank, whatever its kind -- the schema rejects `preAccept`
    and `preReject` on a choice or numeric blank, and `incorrectFeedback`
    on a choice blank.

    Raises:
        UndefinedBlank: a key is not the id of a blank in `blanks`.
        ParseError: a map is not a mapping of lists (of strings for
            `incorrectFeedback`).
    """
    for key in ("preAccept", "preReject", "incorrectFeedback"):
        if key not in front:
            continue
        mapping = front[key]
        is_text = key == "incorrectFeedback"
        if not isinstance(mapping, Mapping):
            raise ParseError(
                f"frontmatter {key!r} of a fill-in question must map "
                f"blank ids to {'strings' if is_text else 'pattern lists'}",
                path=(key,),
            )
        for blank_id, value in mapping.items():
            if is_text and not isinstance(value, str):
                raise ParseError(
                    f"frontmatter {key!r} entry {blank_id!r} must be a string",
                    path=(key, str(blank_id)),
                )
            if not is_text and not isinstance(value, list):
                raise ParseError(
                    f"frontmatter {key!r} entry {blank_id!r} must be "
                    "a list of patterns",
                    path=(key, str(blank_id)),
                )
            blank = blanks.get(blank_id)
            if blank is None:
                raise UndefinedBlank(str(blank_id), key)
            _set_field(blank, key, value)


def _add_blank(blanks: dict[str, BlankDict], new: BlankDict) -> None:
    """
    Merge one definition into the blank its slug names.

    Raises:
        ParseError: the slug is already defined with a different
            kind, or it is a repeated choice or numeric definition.
    """
    blank_id = new["id"]
    existing = blanks.get(blank_id)
    if existing is None:
        blanks[blank_id] = new
        return
    if existing["type"] != new["type"]:
        raise ParseError(
            f"blank {blank_id!r} is defined both as {existing['type']} "
            f"and as {new['type']}"
        )
    if existing["type"] != "short-answer":
        raise ParseError(f"repeated definition of blank {blank_id!r}")
    for key, value in new.items():
        if key not in ("id", "type"):
            # The caller rejects a repeated `accept` or `reject`
            # definition of a short-answer blank before it gets here.
            _set_field(existing, key, value)


def _blank_index(blanks: Mapping[str, BlankDict], blank_id: str) -> int:
    """The index `blank_id` has, or will have, in the `blanks` list."""
    return list(blanks).index(blank_id) if blank_id in blanks else len(blanks)


def _set_field(blank: BlankDict, key: str, value: object) -> None:
    """
    Set a field of a blank by name. The keys come from the frontmatter
    and from another definition of the same blank, so a blank of the wrong
    kind can get a field: the schema rejects it.
    """
    cast("dict[str, object]", blank)[key] = value
