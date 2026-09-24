"""
Cross-check each surface-syntax example against the parsed document it
claims to produce.

Every `<name>.mdq.md` under examples/valid/ is paired with a
`<name>.yaml` holding the document a conforming parser should produce
from it. Nothing in this repo parses Markdown, so the pair can silently
drift -- an edit to one side that never reaches the other. These tests
check the parts of the correspondence that can be verified without a
parser: that both halves exist, that frontmatter keys agree with the
parsed fields, and that the body's shape matches the parsed structure.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from mdq import schedule
from mdq.scripts.schema_bundle import TYPE_SCHEMAS
from mdq.testing import VALID_SOURCES, parsed_sibling, relative_id

#: `* [x] text`, `- [ ] text`, `+ [50%] text` -- a body choice item. The
#: bracket is what separates a choice from an ordinary list item.
_CHOICE_ITEM_RE = re.compile(r"^\s{0,3}[-*+]\s+\[", re.MULTILINE)

#: `[^name]:` or `[^name/type]:` at the start of a line -- a fill-in
#: blank definition.
_BLANK_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:", re.MULTILINE)

#: Frontmatter keys whose surface form is written differently from the
#: parsed form, by a rule the spec spells out. Compared separately, or
#: not at all.
_SHORTHAND_KEYS = frozenset({"tags", "normalizations", "start", "duration"})


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """
    Return ``(frontmatter, body)``. The frontmatter is the YAML between a
    leading pair of `---` separators; a document may legitimately have
    none, in which case an empty mapping is returned.
    """
    if not text.startswith("---"):
        return {}, text

    lines = text.split("\n")
    for index in range(1, len(lines)):
        if lines[index].rstrip() == "---":
            block = "\n".join(lines[1:index])
            loaded = yaml.safe_load(block) if block.strip() else None
            return (loaded or {}), "\n".join(lines[index + 1 :])
    return {}, text


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _ids(paths: list[Path]) -> list[str]:
    return [relative_id(p) for p in paths]


def load_document(path: Path) -> Any:
    """The parsed sibling's own data, loaded straight off disk."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_there_are_source_examples() -> None:
    """Guard against a renamed extension making every test below a no-op."""
    assert VALID_SOURCES


@pytest.mark.parametrize("source", VALID_SOURCES, ids=_ids(VALID_SOURCES))
def test_source_has_a_parsed_sibling(source: Path) -> None:
    sibling = parsed_sibling(source)
    assert sibling.exists(), (
        f"{relative_id(source)} has no {sibling.name} describing the document "
        f"it should parse into"
    )


@pytest.mark.parametrize("source", VALID_SOURCES, ids=_ids(VALID_SOURCES))
def test_frontmatter_agrees_with_the_parsed_document(source: Path) -> None:
    """
    Any frontmatter key that is carried through unchanged must hold the
    same value on both sides. Keys the document omits are not checked --
    a parser is free to infer `type` from the body, for instance.
    """
    frontmatter, _ = _split_frontmatter(source.read_text(encoding="utf-8"))
    parsed = load_document(parsed_sibling(source))

    for key, value in frontmatter.items():
        if key in _SHORTHAND_KEYS:
            continue
        assert key in parsed, (
            f"{relative_id(source)} sets {key!r} in its frontmatter, but the "
            f"parsed document has no such field"
        )
        expected = parsed[key]
        # generic.md: a numeric `id` is read as its decimal string form.
        if key == "id":
            assert str(value) == str(expected), (
                f"{relative_id(source)}: frontmatter id {value!r} != parsed "
                f"id {expected!r}"
            )
        else:
            assert value == expected, (
                f"{relative_id(source)}: frontmatter {key}={value!r} != "
                f"parsed {key}={expected!r}"
            )


@pytest.mark.parametrize("source", VALID_SOURCES, ids=_ids(VALID_SOURCES))
def test_comma_delimited_tags_expand_to_the_parsed_list(source: Path) -> None:
    """generic.md: `tags` accepts a list or a single comma-delimited string."""
    frontmatter, _ = _split_frontmatter(source.read_text(encoding="utf-8"))
    if "tags" not in frontmatter:
        return

    tags = frontmatter["tags"]
    written = (
        [part.strip() for part in tags.split(",")] if isinstance(tags, str) else tags
    )
    assert written == load_document(parsed_sibling(source)).get("tags"), (
        f"{relative_id(source)}: frontmatter tags do not expand to the parsed list"
    )


@pytest.mark.parametrize("source", VALID_SOURCES, ids=_ids(VALID_SOURCES))
def test_start_and_duration_normalize_to_the_parsed_canonical_form(
    source: Path,
) -> None:
    """
    docs/exam.md: `start`/`duration` keep their meaning but not their
    spelling -- the frontmatter's surface form (an unquoted YAML
    timestamp, a shorthand duration) must resolve to exactly what
    `mdq.schedule.parse_*`/`format_*` would produce from it.
    """
    frontmatter, _ = _split_frontmatter(source.read_text(encoding="utf-8"))
    parsed = load_document(parsed_sibling(source))

    if "start" in frontmatter:
        assert schedule.format_start(schedule.parse_start(frontmatter["start"])) == (
            parsed.get("start")
        ), f"{relative_id(source)}: frontmatter start does not match parsed start"

    if "duration" in frontmatter:
        assert schedule.format_duration(
            schedule.parse_duration(frontmatter["duration"])
        ) == parsed.get("duration"), (
            f"{relative_id(source)}: frontmatter duration does not match parsed duration"
        )


@pytest.mark.parametrize("source", VALID_SOURCES, ids=_ids(VALID_SOURCES))
def test_body_shape_matches_the_parsed_document(source: Path) -> None:
    """
    The body's choice items and blank definitions must line up with the
    parsed `choices` / `blanks`.

    Blank definitions are deduplicated first: a short answer blank may
    spread its answer, its accept list and its reject list over several
    definitions sharing one slug, and the parser merges them into a
    single blank keyed by where the slug first appears
    (fill-in.md#blank-definitions).
    """
    _, body = _split_frontmatter(source.read_text(encoding="utf-8"))
    parsed = load_document(parsed_sibling(source))

    if isinstance(parsed.get("blanks"), list):
        names = list(
            dict.fromkeys(
                name.split("/", 1)[0] for name in _BLANK_DEF_RE.findall(body)
            )
        )
        assert names == [blank["id"] for blank in parsed["blanks"]], (
            f"{relative_id(source)}: the blanks defined in the body do not "
            f"match the parsed 'blanks', in this order"
        )
        return

    if isinstance(parsed.get("choices"), list):
        written = len(_CHOICE_ITEM_RE.findall(body))
        assert written == len(parsed["choices"]), (
            f"{relative_id(source)}: the body has {written} choice item(s) "
            f"but the parsed document has {len(parsed['choices'])}"
        )


@pytest.mark.parametrize("source", VALID_SOURCES, ids=_ids(VALID_SOURCES))
def test_parsed_stem_appears_in_the_body(source: Path) -> None:
    """
    The stem is prose lifted out of the document, so it must actually be
    findable there -- modulo the line wrapping that YAML folding removes.
    """
    _, body = _split_frontmatter(source.read_text(encoding="utf-8"))
    stem = load_document(parsed_sibling(source)).get("stem")
    if not isinstance(stem, str):
        return
    assert _collapse(stem) in _collapse(body), (
        f"{relative_id(source)}: the parsed stem does not appear in the body"
    )


@pytest.mark.parametrize("source", VALID_SOURCES, ids=_ids(VALID_SOURCES))
def test_parsed_type_is_a_known_question_type(source: Path) -> None:
    parsed = load_document(parsed_sibling(source))
    assert parsed.get("type") in TYPE_SCHEMAS, (
        f"{relative_id(source)}: parsed type {parsed.get('type')!r} is not a "
        f"registered question type"
    )
