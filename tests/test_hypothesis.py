"""
Unit tests for the Markdown-related strategies in `mdq.hypothesis`.

These check the strategies *themselves*, independent of the question
models: that each one produces the specific CommonMark block it claims
to (via `markdown_it`'s own tokenizer), and that it round-trips through
`mdq.parser.reconstruct_blocks` -- the same reconstruction
`mdq.models.normalize_paragraphs`/`normalize_intro` use to canonicalize a
`preamble`/`epilogue`/`stem` field. `tests/test_render.py`'s
`test_render_question_roundtrip` already exercises these strategies
end-to-end through real question models; this file is about the
building blocks.
"""

from __future__ import annotations

import re

from hypothesis import example, given
from hypothesis import strategies as st
from markdown_it.tree import SyntaxTreeNode as Node

from mdq import models, parse
from mdq.hypothesis import documents as _st
from mdq.parser import SLUG_BODY_RE, md, reconstruct_blocks

_SLUG_RE = re.compile(rf"^{SLUG_BODY_RE}$")


def _tokenize(src: str) -> list[Node]:
    """Return the top-level block nodes `mdq.parser` would see for `src`."""
    return list(Node(md.parse(src)).children)


#
# Leaf strategies
#
@given(_st.slugs())
def test_slug_matches_the_parsers_slug_regex(slug: str) -> None:
    """
    `slug()` feeds a question's `id`, which the parser only ever
    recovers from an inline `[id]` prefix when it matches
    `SLUG_BODY_RE` -- ASCII alphanumeric groups joined by `-`/`_`.
    """
    assert _SLUG_RE.match(slug), slug


#
# md_paragraph
#
@given(_st.md_paragraphs())
@example("A")
@example("A\nB")
@example("A\nB\nC")
def test_paragraph_tokenizes_as_a_single_paragraph(text: str) -> None:
    nodes = _tokenize(text)
    assert len(nodes) == 1
    assert nodes[0].type == "paragraph"


@given(_st.md_paragraphs())
def test_paragraph_round_trips_soft_wraps_collapsed(text: str) -> None:
    """
    A multi-line (soft-wrapped) paragraph collapses to a single line
    (no `\\n` survives) and that collapsed form is already a fixed
    point of a second pass -- exactly the property `mdq.models.
    normalize_intro` relies on. This checks idempotency rather than a
    hand-derived `str.replace` formula: CommonMark also trims a
    paragraph's own leading/trailing whitespace (independent of
    newline collapsing), which `_safe_line`'s alphabet can produce on
    any line, so `text.replace("\\n", " ")` is not always the exact
    reconstructed value.
    """
    [(kind, once)] = reconstruct_blocks(text)
    assert kind == "paragraph"
    assert "\n" not in once

    [(_, twice)] = reconstruct_blocks(once)
    assert twice == once


#
# md_heading
#
@given(_st.md_headings())
def test_heading_tokenizes_as_an_h2_through_h6(text: str) -> None:
    nodes = _tokenize(text)
    assert len(nodes) == 1
    assert nodes[0].type == "heading"
    assert nodes[0].tag in ("h2", "h3", "h4", "h5", "h6")


#
# md_blockquote
#
@given(_st.md_blockquotes())
@example("> A")
@example("> A\n> B")
def test_blockquote_tokenizes_as_a_single_blockquote(text: str) -> None:
    nodes = _tokenize(text)
    assert len(nodes) == 1
    assert nodes[0].type == "blockquote"


@given(_st.md_blockquotes())
def test_blockquote_round_trips_verbatim(text: str) -> None:
    """
    Unlike a paragraph, a blockquote's raw source lines are always
    reconstructed byte-for-byte -- see `MDQParser.raw_text`.
    """
    [(kind, reconstructed)] = reconstruct_blocks(text)
    assert kind == "blockquote"
    assert reconstructed == text


#
# md_list
#
@given(_st.md_lists())
@example("- A")
@example("1. A")
@example("- A\n  - B")
def test_list_tokenizes_as_a_single_bullet_or_ordered_list(text: str) -> None:
    nodes = _tokenize(text)
    assert len(nodes) == 1
    assert nodes[0].type in ("bullet_list", "ordered_list")


@given(_st.md_lists())
def test_list_round_trips_verbatim(text: str) -> None:
    [(_, reconstructed)] = reconstruct_blocks(text)
    assert reconstructed == text


@given(_st.md_lists(max_depth=2))
def test_nested_list_still_round_trips_verbatim(text: str) -> None:
    [(kind, reconstructed)] = reconstruct_blocks(text)
    assert kind in ("bullet_list", "ordered_list")
    assert reconstructed == text


#
# md_code_block
#
@given(_st.md_code_blocks())
@example("```\n```")
@example("```python\nx = 1\n```")
@example("~~~\n~~~")
@example("    indented")
def test_code_block_tokenizes_as_a_fence_or_indented_code_block(text: str) -> None:
    nodes = _tokenize(text)
    assert len(nodes) == 1
    assert nodes[0].type in ("fence", "code_block")


@given(_st.md_code_blocks())
def test_code_block_round_trips_verbatim(text: str) -> None:
    [(kind, reconstructed)] = reconstruct_blocks(text)
    assert kind in ("fence", "code_block")
    assert reconstructed == text


#
# md_safe_block / md_safe_blocks
#
@given(_st.md_safe_blocks())
def test_safe_block_is_a_single_top_level_block(text: str) -> None:
    """
    Every `md_safe_block` draw is a *single* block on its own -- the
    thing `md_safe_blocks` composes multiple of. If a draw ever spanned
    two top-level nodes on its own, joining several with blank lines
    would not mean what `md_safe_blocks`'s docstring says it does.
    """
    nodes = _tokenize(text)
    assert len(nodes) == 1


@given(_st.md_safe_multi_blocks())
def test_safe_blocks_reconstruct_to_a_fixed_point(text: str) -> None:
    """
    `reconstruct_blocks` should already be idempotent on anything
    `md_safe_blocks` can produce: normalizing a preamble/epilogue twice
    must give the same result as normalizing it once (`mdq.models.
    BaseQuestion.normalize` relies on exactly this).
    """
    once = "\n\n".join(t for _, t in reconstruct_blocks(text))
    twice = "\n\n".join(t for _, t in reconstruct_blocks(once))
    assert once == twice


#
# End-to-end: the blocks composed into a full question
#
@given(
    id=st.none() | _st.slugs(),
    preamble=st.none() | _st.md_safe_multi_blocks(),
    epilogue=st.none() | _st.md_safe_multi_blocks(),
    stem=_st.md_paragraphs(),
)
@example(id="q1", preamble="```python\nx = 1\n```", epilogue=None, stem="A")
@example(id="q1", preamble="- A\n- B", epilogue=None, stem="A")
@example(id="q1", preamble="> A", epilogue=None, stem="A")
@example(id="q1", preamble="## A", epilogue=None, stem="A")
def test_generated_blocks_round_trip_through_a_full_question(
    id: str | None,
    preamble: str | None,
    epilogue: str | None,
    stem: str,
) -> None:
    """
    Regression coverage for the `[id]`-inlining bug `can_inline_id`
    fixes: when the only frontmatter field is `id`, `BaseQuestion.
    _render_lines` used to always inline it into the preamble, which
    corrupts a preamble that does not start with a plain paragraph (a
    code block's opening fence, a list marker, ...). The `@example`s
    above pin exactly that scenario for every non-paragraph block kind
    `md_safe_block` can produce as the first preamble block.
    """
    question = models.EssayQuestion(
        id=id, preamble=preamble, epilogue=epilogue, stem=stem
    ).normalize()
    src = question.render()
    round_tripped = parse(src, kind="question")
    assert round_tripped == question, src
