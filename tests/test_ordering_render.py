"""
`OrderingQuestion.render()`/`frontmatter()`.

Reuses the local hypothesis strategy and fixture list from
`tests/test_ordering_models.py`, and the fixture loader from
`tests/test_ordering_scoring.py`, rather than redefining them.

Structural comparisons (fixture equivalence, section ordering, blank-line
placement) are done by re-parsing both the rendered Markdown and the
paired `.mdq.md` fixture with the small line-based parser below, rather
than by string equality -- the renderer normalizes away `content`/
`highlight` frontmatter and the choice of feedback/comment order, so byte
equality against the fixture file is not the right bar (see the cycle-3
handoff).
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pytest
from hypothesis import given

from mdq.models import OrderingAlternative, OrderingQuestion
from _corpus import relative_id
from test_ordering_models import MINIMAL, ORDERING_FIXTURES, ordering_questions
from test_ordering_scoring import load_fixture


#
# A small structural parser for the `[ordering]` body -- shared by the
# fixture-equivalence test and the focused rendering-rule tests below.
#
class ContentBlock(NamedTuple):
    kind: str  # "code" | "ul"
    lang: str | None
    lines: tuple[str, ...]


class Section(NamedTuple):
    heading: str
    feedback: tuple[str, ...]
    comment: tuple[str, ...]
    block: ContentBlock


def skip_blank(lines: list[str], i: int) -> int:
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    return i


def parse_content_block(lines: list[str], i: int) -> tuple[ContentBlock, int]:
    if lines[i].startswith("```"):
        lang = lines[i][3:].strip() or None
        i += 1
        content = []
        while lines[i].strip() != "```":
            content.append(lines[i])
            i += 1
        i += 1  # closing fence
        return ContentBlock("code", lang, tuple(content)), i

    items = []
    while i < len(lines) and lines[i].lstrip().startswith("* "):
        items.append(lines[i])
        i += 1
    return ContentBlock("ul", None, tuple(items)), i


def parse_observation_block(lines: list[str], i: int, prefix: str) -> tuple[list[str], int]:
    collected = []
    while i < len(lines) and lines[i].lstrip().startswith(prefix):
        collected.append(lines[i].lstrip()[len(prefix) :])
        i += 1
    return collected, i


def parse_section(lines: list[str], i: int) -> tuple[Section, int]:
    assert lines[i].startswith("## ["), lines[i]
    heading = lines[i].strip()
    i = skip_blank(lines, i + 1)

    feedback: list[str] = []
    comment: list[str] = []
    for _ in range(2):
        i = skip_blank(lines, i)
        if i < len(lines) and lines[i].lstrip().startswith("> ") and not feedback:
            feedback, i = parse_observation_block(lines, i, "> ")
        elif i < len(lines) and lines[i].lstrip().startswith("! ") and not comment:
            comment, i = parse_observation_block(lines, i, "! ")
        else:
            break

    i = skip_blank(lines, i)
    block, i = parse_content_block(lines, i)
    return Section(heading, tuple(feedback), tuple(comment), block), i


def parse_body(markdown: str) -> tuple[ContentBlock, list[Section]]:
    """
    Parse everything from the `[ordering]` tag onward into the main
    content block plus the list of `## [...]` sections that follow.

    Raises:
        ValueError: no `[ordering]` tag line in `markdown`.
    """
    lines = markdown.splitlines()
    try:
        start = lines.index("[ordering]")
    except ValueError as exc:
        raise ValueError("no [ordering] tag found") from exc

    i = start + 1
    assert i < len(lines) and lines[i].strip() != "", (
        "no blank line allowed between [ordering] and its content block"
    )
    main_block, i = parse_content_block(lines, i)

    sections = []
    i = skip_blank(lines, i)
    while i < len(lines):
        section, i = parse_section(lines, i)
        sections.append(section)
        i = skip_blank(lines, i)
    return main_block, sections


#
# Properties
#
@given(ordering_questions())
def test_render_contains_exactly_one_ordering_tag(question: OrderingQuestion) -> None:
    src = question.render()
    assert src.splitlines().count("[ordering]") == 1


@given(ordering_questions())
def test_main_content_line_count_matches_the_answer_key(
    question: OrderingQuestion,
) -> None:
    main_block, _ = parse_body(question.render())
    assert len(main_block.lines) == len(question.lines)


@given(ordering_questions())
def test_extra_and_alternative_line_counts_match_their_declarations(
    question: OrderingQuestion,
) -> None:
    _, sections = parse_body(question.render())

    extra_sections = [s for s in sections if s.heading == "## [extra]"]
    if question.extra:
        assert len(extra_sections) == 1
        assert len(extra_sections[0].block.lines) == len(question.extra)
    else:
        assert not extra_sections

    accept_sections = [s for s in sections if s.heading == "## [accept]"]
    assert len(accept_sections) == len(question.accept)
    for section, alt in zip(accept_sections, question.accept):
        assert len(section.block.lines) == len(alt.lines)

    reject_sections = [s for s in sections if s.heading == "## [reject]"]
    assert len(reject_sections) == len(question.reject)
    for section, alt in zip(reject_sections, question.reject):
        assert len(section.block.lines) == len(alt.lines)


@given(ordering_questions())
def test_no_heading_when_extra_accept_and_reject_are_all_empty(
    question: OrderingQuestion,
) -> None:
    question = question.model_copy(update={"extra": [], "accept": [], "reject": []})
    src = question.render()
    assert "##" not in src


#
# Fixture equivalence
#
def fixture_source(yaml_path: Path) -> Path:
    return yaml_path.with_suffix("").with_suffix(".mdq.md")


def expected_content_lines(
    content: str, lines: list[tuple[int, str]] | list
) -> tuple[str, ...]:
    """
    The canonical rendered text of a content block, per the render rules:
    `level * 4` spaces for code, `level * 2` before the `* ` marker for
    text (ordering.md#body / the cycle-3 handoff).
    """
    if content == "code":
        return tuple(" " * (4 * level) + text for level, text in lines)
    return tuple(" " * (2 * level) + f"* {text}" for level, text in lines)


def expected_lines(feedback_or_comment: str | None) -> tuple[str, ...]:
    return tuple(feedback_or_comment.splitlines()) if feedback_or_comment else ()


@pytest.mark.parametrize(
    "path", ORDERING_FIXTURES, ids=[relative_id(p) for p in ORDERING_FIXTURES]
)
def test_render_is_structurally_equivalent_to_its_fixture(path: Path) -> None:
    """
    Content lines and observations are checked against the model's own
    fields (the ground truth `load_fixture` already validated to
    round-trip through `to_dict()` in test_ordering_models.py), not
    against the fixture file's raw text: `lenient-indentation.yaml`
    deliberately authors its code block with a 1-space indentation unit
    to demonstrate unit inference, so a `level * 4` renderer reproduces
    the same *levels* but not the same raw spacing. What the fixture
    file *does* pin down, and what is checked directly against it, is
    the content kind (code/ul) and the section heading order.
    """
    question = load_fixture(path.name)
    source = fixture_source(path)
    assert source.exists(), f"no paired {source.name} for {path.name}"

    rendered_main, rendered_sections = parse_body(question.render())
    fixture_main, fixture_sections = parse_body(source.read_text(encoding="utf-8"))

    assert rendered_main.kind == fixture_main.kind
    assert [s.heading for s in rendered_sections] == [
        s.heading for s in fixture_sections
    ]

    assert rendered_main.lines == expected_content_lines(
        question.content, question.lines
    )

    by_heading: dict[str, list[Section]] = {}
    for section in rendered_sections:
        by_heading.setdefault(section.heading, []).append(section)

    if question.extra:
        (extra_section,) = by_heading.get("## [extra]", [])
        assert extra_section.block.lines == expected_content_lines(
            question.content, question.extra
        )
    else:
        assert "## [extra]" not in by_heading

    for heading, alternatives in (
        ("## [accept]", question.accept),
        ("## [reject]", question.reject),
    ):
        sections = by_heading.get(heading, [])
        assert len(sections) == len(alternatives)
        for section, alt in zip(sections, alternatives):
            assert section.block.lines == expected_content_lines(
                question.content, alt.lines
            )
            assert section.feedback == expected_lines(alt.feedback)
            assert section.comment == expected_lines(alt.comment)


@pytest.mark.parametrize(
    "path", ORDERING_FIXTURES, ids=[relative_id(p) for p in ORDERING_FIXTURES]
)
def test_render_never_emits_content_or_highlight(path: Path) -> None:
    question = load_fixture(path.name)
    frontmatter = question.frontmatter()
    assert "content" not in frontmatter
    assert "highlight" not in frontmatter


#
# Focused rendering rules
#
def test_no_blank_line_between_tag_and_content_block() -> None:
    src = MINIMAL.render()
    lines = src.splitlines()
    tag_index = lines.index("[ordering]")
    assert lines[tag_index + 1].strip() != ""


def test_code_content_indents_by_four_spaces_per_level() -> None:
    question = OrderingQuestion(
        stem="s",
        content="code",
        lines=[(0, "top"), (1, "one"), (2, "two")],
    )
    main_block, _ = parse_body(question.render())
    assert main_block.kind == "code"
    assert main_block.lines == ("top", "    one", "        two")


def test_text_content_indents_by_two_spaces_per_level() -> None:
    question = OrderingQuestion(
        stem="s",
        content="text",
        lines=[(0, "top"), (1, "one"), (2, "two")],
    )
    main_block, _ = parse_body(question.render())
    assert main_block.kind == "ul"
    assert main_block.lines == ("* top", "  * one", "    * two")


def test_code_fence_carries_the_highlight_language() -> None:
    question = OrderingQuestion(
        stem="s", content="code", highlight="python", lines=[(0, "a"), (0, "b")]
    )
    main_block, _ = parse_body(question.render())
    assert main_block.lang == "python"


def test_extra_and_alternative_fences_reuse_the_same_highlight() -> None:
    """
    The `[extra]`/`[accept]`/`[reject]` sections' fences carry the main
    block's `highlight`, even though the spec says the highlight on the
    way *in* is ignored for these sections (ordering.md#extra-lines).
    """
    question = OrderingQuestion(
        stem="s",
        content="code",
        highlight="python",
        lines=[(0, "a"), (0, "b")],
        extra=[(0, "c")],
        accept=[OrderingAlternative(lines=[(0, "b"), (0, "a")])],
    )
    _, sections = parse_body(question.render())
    assert all(section.block.lang == "python" for section in sections)


def test_feedback_renders_before_comment_regardless_of_field_order() -> None:
    question = OrderingQuestion(
        stem="s",
        lines=[(0, "a"), (0, "b")],
        reject=[
            OrderingAlternative(
                lines=[(0, "b"), (0, "a")],
                feedback="the feedback",
                comment="the comment",
            )
        ],
    )
    lines = question.render().splitlines()
    feedback_index = next(i for i, line in enumerate(lines) if "the feedback" in line)
    comment_index = next(i for i, line in enumerate(lines) if "the comment" in line)
    assert feedback_index < comment_index
    assert lines[feedback_index].lstrip().startswith("> ")
    assert lines[comment_index].lstrip().startswith("! ")


def test_multiline_feedback_prefixes_every_line() -> None:
    question = OrderingQuestion(
        stem="s",
        lines=[(0, "a"), (0, "b")],
        accept=[
            OrderingAlternative(
                lines=[(0, "b"), (0, "a")],
                feedback="first line\nsecond line",
            )
        ],
    )
    _, sections = parse_body(question.render())
    accept_section = next(s for s in sections if s.heading == "## [accept]")
    assert accept_section.feedback == ("first line", "second line")


def test_sections_render_in_extra_accept_reject_order() -> None:
    question = OrderingQuestion(
        stem="s",
        lines=[(0, "a"), (0, "b")],
        extra=[(0, "c")],
        accept=[OrderingAlternative(lines=[(0, "b"), (0, "a")])],
        reject=[OrderingAlternative(lines=[(0, "c"), (0, "a")])],
    )
    headings = [
        line.strip()
        for line in question.render().splitlines()
        if line.startswith("## [")
    ]
    assert headings == ["## [extra]", "## [accept]", "## [reject]"]


#
# frontmatter()
#
def test_frontmatter_omits_content_and_highlight_even_when_declared() -> None:
    question = OrderingQuestion(
        stem="s", content="code", highlight="python", lines=[(0, "a"), (0, "b")]
    )
    assert "content" not in question.frontmatter()
    assert "highlight" not in question.frontmatter()
    assert "content" not in question.frontmatter(skip_defaults=True)
    assert "highlight" not in question.frontmatter(skip_defaults=True)


def test_frontmatter_emits_non_default_indentation_unmatched_and_normalizations() -> (
    None
):
    question = OrderingQuestion(
        stem="s",
        lines=[(0, "a"), (0, "b")],
        indentation="strict",
        unmatched="incorrect",
        normalizations=["dedent"],
    )
    frontmatter = question.frontmatter(skip_defaults=True)
    assert frontmatter["indentation"] == "strict"
    assert frontmatter["unmatched"] == "incorrect"
    assert frontmatter["normalizations"] == ["dedent"]


def test_frontmatter_normalizations_is_always_a_list_never_bare_string() -> None:
    question = OrderingQuestion(
        stem="s", lines=[(0, "a"), (0, "b")], normalizations=["skip-blanks"]
    )
    frontmatter = question.frontmatter(skip_defaults=True)
    assert isinstance(frontmatter["normalizations"], list)
    assert frontmatter["normalizations"] == ["skip-blanks"]


def test_frontmatter_skip_defaults_omits_default_indentation_unmatched_normalizations() -> (
    None
):
    frontmatter = MINIMAL.frontmatter(skip_defaults=True)
    assert "indentation" not in frontmatter
    assert "unmatched" not in frontmatter
    assert "normalizations" not in frontmatter

