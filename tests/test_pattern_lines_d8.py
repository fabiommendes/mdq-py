"""
Lazy lines and exact literals of a pattern in the body (docs/question-types/
short-answer.md, "Pattern lines" and "Content"; docs/references/patterns.md,
"Continuation lines" and "Exact literals"): a setext underline after the
content is a `parse-error`, an indented `>` or `!` line continues the
content, and an exact literal cannot open or close at a line ending.
"""

from __future__ import annotations

import pytest

import mdq
from mdq._exact import join_pattern_lines
from mdq.errors import InvalidDocument
from mdq.models import ShortAnswerQuestion

STEM = "Which river forms the Pantanal floodplain?\n\n"
FILL_IN = "O maior rio do Pantanal é o [^rio].\n\n"


def codes(source: str) -> list[tuple[str, tuple[str | int, ...]]]:
    with pytest.raises(InvalidDocument) as info:
        mdq.parse(source, format="mdq")
    return [(d.code, tuple(d.path)) for d in info.value.diagnostics]


def accept(source: str) -> list[str]:
    question = mdq.parse(source, format="mdq")
    assert isinstance(question, ShortAnswerQuestion)
    return [entry.pattern for entry in question.accept or []]


@pytest.mark.parametrize(
    "body",
    [
        "[short-answer]: Rio\n===\n",
        "[short-answer]: Rio\n---\n",
        "[short-answer]: Rio\n-\n",
        "[short-answer]: Rio\n=\n",
        "[short-answer]: Rio\n===   \n",
        "[short-answer]: Rio\n   ===\n",
        "[short-answer]: Rio\nParaguai\n===\n",
        "[short-answer]:\n===\n",
        "[short-answer]: Rio\n\n[short-answer/reject]: Mar\n===\n",
    ],
)
def test_setext_underline_after_the_content_is_a_parse_error(body: str) -> None:
    assert codes(STEM + body) == [("parse-error", ())]


@pytest.mark.parametrize(
    "body",
    [
        "[^rio/short-answer]: Paraguai\n===\n",
        "[^rio/short-answer]: Paraguai\n  Negro\n---\n",
        "[^rio/short-answer]: Paraguai\n\n[^rio/short-answer/reject]: Mar\n===\n",
    ],
)
def test_setext_underline_after_a_fill_in_definition_is_a_parse_error(
    body: str,
) -> None:
    assert codes(FILL_IN + body) == [("parse-error", ())]


@pytest.mark.parametrize("underline", ["===", "---", "=", "  ==="])
def test_setext_underline_after_a_list_item_pattern_is_a_parse_error(
    underline: str,
) -> None:
    body = f"[short-answer]:\n* Rio\n  {underline.strip()}\n"
    assert codes(STEM + body) == [("parse-error", ())]


def test_tab_indented_underline_is_continuation_text() -> None:
    assert accept(STEM + "[short-answer]: Rio\n\t---\n") == ["Rio ---"]


@pytest.mark.parametrize("marker", [">", "!"])
def test_tab_indented_marker_line_continues_the_content(marker: str) -> None:
    source = STEM + f"[short-answer]: Neblina\n\t{marker} Bandeira\n"
    assert accept(source) == [f"Neblina {marker} Bandeira"]


@pytest.mark.parametrize("marker", [">", "!"])
@pytest.mark.parametrize("indent", ["", " ", "   "])
def test_marker_line_with_up_to_three_spaces_is_a_parse_error(
    marker: str, indent: str
) -> None:
    source = STEM + f"[short-answer]: Neblina\n{indent}{marker} Bandeira\n"
    assert codes(source) == [("parse-error", ())]


@pytest.mark.parametrize(
    "body",
    [
        "[short-answer]: `\nmath.sqrt`\n",
        "[short-answer]: `math.sqrt\n`\n",
        "[short-answer]: `math\n`\n",
        "[short-answer]: ``\nmath.sqrt``\n",
        "[short-answer]:\n`\nmath.sqrt`\n",
        "[short-answer]:\n* `\n  math.sqrt`\n",
        "[short-answer]:\n* `math.sqrt\n  `\n",
    ],
)
def test_exact_literal_at_a_line_ending_is_a_parse_error(body: str) -> None:
    assert codes(STEM + body) == [("parse-error", ())]


def test_exact_literal_at_a_line_ending_in_an_item_with_feedback() -> None:
    source = STEM + "[short-answer]:\n* `math.sqrt\n  `\n  > Right.\n"
    assert codes(source) == [("parse-error", ())]


def test_exact_literal_at_a_line_ending_in_a_fill_in_blank() -> None:
    source = FILL_IN + "[^rio/short-answer]: `\nParaguai`\n"
    assert codes(source) == [("parse-error", ())]


@pytest.mark.parametrize(
    ("body", "pattern"),
    [
        ("[short-answer]: ``a`b\nc``\n", "``a`b c``"),
        ("[short-answer]: `a\n``b`\n", "`a ``b`"),
    ],
)
def test_exact_literal_that_wraps_inside_the_text_is_joined(
    body: str, pattern: str
) -> None:
    assert accept(STEM + body) == [pattern]


def test_frontmatter_pattern_with_a_line_ending_is_a_schema_error() -> None:
    source = (
        "---\nid: sa-fm\ntype: short-answer\npreAccept:\n"
        '  - "`\\nmath.sqrt`"\n---\n\n' + STEM + "[short-answer]: Rio\n"
    )
    result = mdq.load(source, format="mdq")
    assert [d.code for d in result.diagnostics if d.severity == "error"] == [
        "schema-error"
    ]


@pytest.mark.parametrize(
    ("lines", "joined"),
    [
        ([], ""),
        (["`a", "``b`"], "`a ``b`"),
    ],
)
def test_join_pattern_lines(lines: list[str], joined: str) -> None:
    assert join_pattern_lines(lines) == joined
