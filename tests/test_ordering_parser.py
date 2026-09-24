"""
`mdq.parser`'s `[ordering]` body support: reading the tag, its content
block (fenced code or `ul`), the `## [extra]`/`## [accept]`/`## [reject]`
sections, and the indentation unit shared across all of them
(docs/question-types/ordering.md -- Body, Extra lines, Accepted/rejected
answers, Indentation).

The fixture-equality tests in `tests/test_parser.py`
(`test_parses_matches_fixture`) already cover the ten `examples/valid/
ordering/*.mdq.md` pairs' happy path -- this module does not repeat
them. What is here instead:

- a render -> parse property, tying cycle 3 (`OrderingQuestion.render()`)
  and cycle 4 (the parser) together: for a generated question, parsing
  its own rendered Markdown back must validate against the JSON schema
  and reproduce the normalized model.
- one focused test per parsing rule that carries a spec reason but that
  no fixture happens to pin exactly (see each test's docstring for the
  specific fixture-adjacent gap it fills).
- one test per malformed-body error the cycle-4 handoff calls out.
"""

from __future__ import annotations

from typing import cast

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mdq.errors import ParseError
from mdq.hypothesis import documents as doc_st
from mdq.models import (
    OrderingAlternative,
    OrderingLine,
    OrderingQuestion,
    QuestionRoot,
)
from mdq.parser import parse_question
from mdq.types import OrderingQuestionDict
from mdq import load


def parse_ordering(source: str) -> OrderingQuestionDict:
    """`parse_question`, cast to the `ordering`-specific dict shape.

    `parse_question` is typed for the full `QuestionDict` union since it
    handles every question type; every focused test below only ever
    feeds it an `[ordering]` body, so the cast documents that instead
    of scattering `# type: ignore`s at each dict-key access.
    """
    return cast(OrderingQuestionDict, parse_question(source))


#
# A local, parser-tailored strategy -- see the module docstring in
# `mdq/hypothesis/documents.py` for the "construct precisely, don't
# filter" style this follows. It is deliberately narrower than
# `test_ordering_models.ordering_questions` (which this module does not
# reuse): that one fixes `content` at its "text" default and allows
# arbitrary feedback/comment text, neither of which is safe for a
# render -> parse round trip the way this property needs.
#
_WORD_ALPHABET = "abcdefghij0123456789"


def _word(tag: str) -> st.SearchStrategy[str]:
    """
    A single "line" of text: a tag-prefixed alphanumeric word, with no
    whitespace, backtick or Markdown-special character. Safe verbatim
    inside a fenced code line (only a backtick/newline could break
    that) and as a `ul` item's raw source (no leading char that could
    be read as a different block, since it always follows a literal
    `* ` marker already written by the renderer) and safe as a single-
    line feedback/comment ('> '/'! ' prefixed, then rejoined with a
    single `join_prefixed_lines` pass -- no internal newline or
    leading/trailing whitespace for that join to normalize away).

    Tag-prefixed so lines drawn for different sections/alternatives
    never collide -- `OrderingQuestion.check_accept_and_reject_disjoint`
    would otherwise reject a draw whose `accept`/`reject` lines happen
    to match by construction, rather than by design.
    """
    return st.text(alphabet=_WORD_ALPHABET, min_size=1, max_size=6).map(
        lambda s: f"{tag}-{s}"
    )


def _lines(
    tag: str, min_size: int = 2, max_size: int = 4
) -> st.SearchStrategy[list[OrderingLine]]:
    """
    Lines at level 0 or 1 only. `_ordering_unit` is the GCD of every
    indented line's own width across the *whole* question (main,
    extra, every accept/reject); once more than one nonzero level is
    in play, two sections drawn independently can combine into a GCD
    neither expected on its own (e.g. widths {8} from one section and
    {12} from another give a combined GCD of 4, not 8 or 12), which
    would make this generator itself the source of a spurious failure
    rather than the parser under test. Keeping every level in {0, 1}
    keeps the width set a subset of {0, 4} (code) or {0, 2} (text) for
    the entire question, so the GCD is always exactly the per-level
    unit no matter how sections combine. The focused indentation tests
    below cover multi-level inference directly instead.
    """
    line = st.tuples(st.integers(min_value=0, max_value=1), _word(tag))
    return st.lists(
        line, min_size=min_size, max_size=max_size, unique_by=lambda pair: pair
    )


def _alternatives(
    tag: str, max_size: int = 2
) -> st.SearchStrategy[list[OrderingAlternative]]:
    return st.lists(
        st.builds(
            OrderingAlternative,
            lines=_lines(tag),
            feedback=st.none() | _word(f"{tag}-feedback"),
            comment=st.none() | _word(f"{tag}-comment"),
        ),
        max_size=max_size,
    )


@st.composite
def ordering_questions(draw: st.DrawFn) -> OrderingQuestion:
    """
    Generate an `OrderingQuestion` whose render() output is safe to
    parse back: content kind (code/text) varies, and `highlight` is
    only ever drawn for `content == "code"` -- `render()` never emits
    a `highlight` frontmatter field (cycle 3), so for `content ==
    "text"` there is no fence to carry one back through parsing either;
    mirrors `mdq.hypothesis.documents.essay_questions`'s
    `highlight=... if input == "code" else None`.
    """
    content = draw(st.sampled_from(["code", "text"]))
    highlight = (
        draw(doc_st.code_highlight_formats() | st.none())
        if content == "code"
        else None
    )
    return draw(
        st.builds(
            OrderingQuestion,
            stem=doc_st.md_paragraphs(),
            content=st.just(content),
            highlight=st.just(highlight),
            lines=_lines("main"),
            extra=_lines("extra", min_size=0, max_size=3),
            accept=_alternatives("accept"),
            reject=_alternatives("reject"),
            indentation=st.sampled_from(["fixed", "lenient", "strict"]),
            unmatched=st.sampled_from(["manual", "incorrect"]),
            normalizations=st.lists(
                st.sampled_from(["dedent", "skip-blanks"]), unique=True, max_size=2
            ),
        )
    )


#
# Property: render -> parse is a fixed point.
#
@settings(suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(ordering_questions())
def test_render_parse_is_a_fixed_point(question: OrderingQuestion) -> None:
    """
    Ties cycles 3 and 4 together (the cycle-4 handoff's own framing):
    parsing a generated question's own rendered Markdown must validate
    against `schema/ordering.yaml` and reproduce the normalized model.
    """
    document = parse_question(question.render())

    loaded = load(document)
    assert loaded, loaded.diagnostics

    rebuilt = QuestionRoot.model_validate(document).root
    assert rebuilt == question.normalize()


#
# Focused parsing rules with a spec reason but no fixture pinning them.
#
def test_tab_counts_as_four_spaces() -> None:
    """
    ordering.md#indentation: "normalizes a tabulation as 4 spaces".
    A single tab-indented line is the whole indented set, so its width
    (4, once expanded) is also the unit -- level 1.
    """
    source = "[ordering]\n```\na\n\tb\n```\n"
    document = parse_ordering("Order.\n\n" + source)
    assert document["lines"] == [[0, "a"], [1, "b"]]


def test_unit_is_inferred_from_a_non_four_space_indent() -> None:
    """
    ordering.md#indentation: the unit is the GCD of every indented
    line's leading whitespace, not a fixed 4 spaces. Two indented
    widths of 2 and 6 spaces have a GCD of 2, so they decode to levels
    1 and 3 -- if the unit were hardcoded to 4, neither would even be
    a whole multiple of it.
    """
    source = "[ordering]\n```\na\n  b\n      c\n```\n"
    document = parse_ordering("Order.\n\n" + source)
    assert document["lines"] == [[0, "a"], [1, "b"], [3, "c"]]


def test_unit_defaults_to_four_spaces_when_nothing_is_indented() -> None:
    """
    ordering.md#indentation: "If no indented line exists, the unit is
    4 spaces." With every line at level 0 the chosen unit cannot
    actually be observed in the parsed output (0 divided by any unit
    is still 0) -- this only pins that such a document parses cleanly,
    with every line at level 0, rather than raising or guessing a
    level for lines that were never indented at all.
    """
    source = "[ordering]\n```\na\nb\nc\n```\n"
    document = parse_ordering("Order.\n\n" + source)
    assert document["lines"] == [[0, "a"], [0, "b"], [0, "c"]]


def test_ul_line_keeps_its_raw_markdown_source_verbatim() -> None:
    """
    ordering.md#body: "Each line is derived from the respective list
    item, preserving its markdown source verbatim... two lines that
    render identically but are written differently -- `*emphasis*` and
    `_emphasis_`, say -- are two distinct lines."
    """
    source = "[ordering]\n* *alpha*\n* _alpha_\n"
    document = parse_ordering("Order.\n\n" + source)
    assert document["content"] == "text"
    assert document["lines"] == [[0, "*alpha*"], [0, "_alpha_"]]


def test_normalizations_bare_string_parses_to_a_list() -> None:
    """
    ordering.md#frontmatter (footnote 5): "A single normalization MAY
    be written as a bare string instead of a one-item list, exactly as
    `tags` allows"; like `tags`, the parsed document always holds a
    list. `examples/valid/ordering/skip-blanks.mdq.md` already pins
    the bare-string spelling for `skip-blanks` -- this exercises the
    same coercion for `dedent` instead, so the rule is checked
    independent of that one fixture.
    """
    source = "---\nnormalizations: dedent\n---\n\nOrder.\n\n[ordering]\n* a\n* b\n"
    document = parse_ordering(source)
    assert document["normalizations"] == ["dedent"]


def test_declared_content_and_highlight_override_the_body() -> None:
    """
    ordering.md#frontmatter (footnotes 1-2): `content`/`highlight` are
    inferred from the body when omitted, but "when given they override
    what the body implies". The body here is a `ul` list -- which on
    its own infers `content: text` and no `highlight` at all -- yet the
    declared frontmatter must win.
    """
    source = (
        "---\ncontent: code\nhighlight: c\n---\n\nOrder.\n\n[ordering]\n* a\n* b\n"
    )
    document = parse_ordering(source)
    assert document["content"] == "code"
    assert document["highlight"] == "c"
    # The body is still read as a `ul` for line extraction -- overriding
    # `content` is a metadata override, not a re-interpretation of the
    # actual block that follows the tag.
    assert document["lines"] == [[0, "a"], [0, "b"]]


#
# Malformed bodies: every case must raise `ParseError`, never
# `AssertionError`/`IndexError` (cycle-4 handoff's acceptance criteria).
#
def test_ordering_tag_followed_by_a_paragraph_is_a_parse_error() -> None:
    """An `[ordering]` tag must be followed by a code block or a `ul`."""
    source = "[ordering]\nJust a paragraph, not a block.\n"
    with pytest.raises(ParseError):
        parse_question("Order.\n\n" + source)


def test_section_with_a_different_block_kind_than_main_is_a_parse_error() -> None:
    """
    ordering.md#extra-lines / #accepted-rejected-answers: "it must use
    the same content block type (code block or `ul` list)" as the
    `[ordering]` block. Here the main block is a fenced code block and
    `## [extra]` is a `ul`.
    """
    source = "[ordering]\n```\na\nb\n```\n\n## [extra]\n* c\n* d\n"
    with pytest.raises(ParseError):
        parse_question("Order.\n\n" + source)


def test_two_extra_sections_is_a_parse_error() -> None:
    """ordering.md#extra-lines: "at most one `## [extra]` section"."""
    source = (
        "[ordering]\n* a\n* b\n\n## [extra]\n* c\n\n## [extra]\n* d\n"
    )
    with pytest.raises(ParseError):
        parse_question("Order.\n\n" + source)


def test_interleaved_feedback_and_comment_blocks_is_a_parse_error() -> None:
    """
    ordering.md#accepted-rejected-answers: "They MUST NOT interleave:
    once a `!` comment block has started, a `>` line ends the
    observations." Here a second `>` block follows a `!` block that
    itself followed a first `>` block.
    """
    source = (
        "[ordering]\n* a\n* b\n\n"
        "## [reject]\n\n"
        "> first feedback\n\n"
        "! a comment\n\n"
        "> a second feedback block\n\n"
        "* b\n* a\n"
    )
    with pytest.raises(ParseError):
        parse_question("Order.\n\n" + source)
