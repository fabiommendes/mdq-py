"""
Short answer: two blocks, `[short-answer]` and `[short-answer/reject]` (see
`dev/specs/to-do/short-answer-two-blocks.md`).

`[short-answer]` is the accept block and `[short-answer/accept]` is only an
alias of it. Each block takes one pattern on the tag line or a bullet list on
the lines right after the tag. A tag with a colon and no content on its line
needs its list right after it: a blank line in between is a `parse-error`.
A pattern-less block is written `[short-answer]`, without a colon. Both
spellings of the accept block in one document are a `parse-error`.

The parse behavior (blocks, lists, errors) is covered by the corpus under
`examples/`. This module keeps what the corpus cannot express: error
message texts and the render API.

Naming: `test_b2_*` and `test_b3_*` (error messages, in short-answer
questions and in fill-in blanks), `test_b4_*` (render and docs).
"""

from __future__ import annotations

import pytest

from mdq import Diagnostic, load
from mdq.models import (
    AnswerPattern,
    FillInQuestion,
    ShortAnswerBlank,
    ShortAnswerQuestion,
)

STEM = "Qual é a capital do Brasil?"
FILL_STEM = "O maior bioma brasileiro é a [^bioma]."

ACCEPT_TAGS = ["[short-answer]", "[short-answer/accept]"]
_BLANK_TAGS = ["[^bioma/short-answer]", "[^bioma/short-answer/accept]"]


def _q(body: str) -> str:
    return f"{STEM}\n\n{body}"


def _f(body: str) -> str:
    return f"{FILL_STEM}\n\n{body}"


def _codes(diagnostics: list[Diagnostic]) -> list[str]:
    return [d.code for d in diagnostics]


def _errors(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diagnostics if d.severity == "error"]


def _doc(source: str) -> dict:
    loaded = load(source, format="mdq")
    assert loaded.document is not None, [d.code for d in loaded.diagnostics]
    return loaded.document.to_dict()


def _assert_parse_error(source: str) -> None:
    loaded = load(source, format="mdq")
    assert loaded.document is None
    assert "parse-error" in _codes(_errors(loaded.diagnostics))


def _error_messages(source: str) -> list[str]:
    loaded = load(source, format="mdq")
    return [d.message for d in _errors(loaded.diagnostics)]


#
# AC4: blank line, no content on the tag line
#
@pytest.mark.parametrize("tag", ACCEPT_TAGS)
def test_b2_empty_tag_and_detached_list_is_a_parse_error(tag: str) -> None:
    source = _q(f"{tag}:\n\n* Cite a evaporação.\n* Cite os rios voadores.\n")
    _assert_parse_error(source)
    assert "right after the tag" in _error_messages(source)[0]


@pytest.mark.parametrize("tag", ACCEPT_TAGS)
def test_b2_empty_tag_and_blank_line_and_text_is_a_parse_error(tag: str) -> None:
    source = _q(f"{tag}:\n\nBrasília.\n")
    _assert_parse_error(source)
    assert "for a manual question" in _error_messages(source)[0]


def test_b2_tag_without_a_colon_and_a_glued_list_is_a_parse_error() -> None:
    source = _q("[short-answer]\n* Cite a evaporação.\n")
    _assert_parse_error(source)
    assert "[short-answer]:" in _error_messages(source)[0]


#
# AC9: blank line or no content in a blank
#
@pytest.mark.parametrize("tag", _BLANK_TAGS)
def test_b3_empty_blank_and_detached_list_is_a_parse_error(tag: str) -> None:
    source = _f(f"{tag}:\n\n* Cite o rio Negro.\n")
    _assert_parse_error(source)
    assert "right after the tag" in _error_messages(source)[0]


def test_b3_choice_blank_without_a_list_is_a_parse_error() -> None:
    source = _f("[^bioma]:\n")
    _assert_parse_error(source)
    assert "choice list" in _error_messages(source)[0]


#
# AC10: render
#
def test_b4_render_single_plain_accept_as_line() -> None:
    question = ShortAnswerQuestion(stem="Qual a capital?", accept=["Brasília"])
    assert question.render() == "Qual a capital?\n\n[short-answer]: Brasília"


def test_b4_render_single_exact_and_regex_accept_as_line() -> None:
    exact = ShortAnswerQuestion(stem="Qual função?", accept=["`math.isnan`"])
    regex = ShortAnswerQuestion(stem="Quando?", accept=["/1822-0?9-0?7/i"])
    assert exact.render().endswith("[short-answer]: `math.isnan`")
    assert regex.render().endswith("[short-answer]: /1822-0?9-0?7/i")


def test_b4_render_two_patterns_as_list_under_short_answer() -> None:
    question = ShortAnswerQuestion(stem="Qual a capital?", accept=["Brasília", "DF"])
    assert question.render() == "Qual a capital?\n\n[short-answer]:\n* Brasília\n* DF"


@pytest.mark.parametrize(
    ("item", "tail"),
    [
        (
            AnswerPattern(pattern="Brasília", feedback="Certo!"),
            "* Brasília\n  > Certo!",
        ),
        (
            AnswerPattern(pattern="Brasília", comment="Oficial"),
            "* Brasília\n  ! Oficial",
        ),
        (
            AnswerPattern(pattern="Brasília", feedback="Certo!", comment="Oficial"),
            "* Brasília\n  > Certo!\n  ! Oficial",
        ),
    ],
    ids=["feedback", "comment-only", "feedback-and-comment"],
)
def test_b4_render_single_annotated_accept_as_list(
    item: AnswerPattern, tail: str
) -> None:
    question = ShortAnswerQuestion(stem="Qual a capital?", accept=[item])
    assert question.render() == f"Qual a capital?\n\n[short-answer]:\n{tail}"


def test_b4_render_single_accept_with_reject_uses_lists() -> None:
    question = ShortAnswerQuestion(
        stem="Qual a capital?", accept=["Brasília"], reject=["Rio de Janeiro"]
    )
    assert question.render() == (
        "Qual a capital?\n\n"
        "[short-answer]:\n* Brasília\n\n"
        "[short-answer/reject]:\n* Rio de Janeiro"
    )


def test_b4_render_reject_is_always_a_list() -> None:
    question = ShortAnswerQuestion(
        stem="Qual a capital?",
        accept=["Brasília"],
        reject=[AnswerPattern(pattern="Rio", feedback="Não.")],
    )
    assert "[short-answer/reject]:\n* Rio\n  > Não." in question.render()


@pytest.mark.parametrize(
    "question",
    [
        ShortAnswerQuestion(stem="Qual a capital?", accept=["Brasília"]),
        ShortAnswerQuestion(stem="Qual a capital?", accept=["Brasília", "DF"]),
        ShortAnswerQuestion(
            stem="Qual a capital?",
            accept=[AnswerPattern(pattern="Brasília", comment="x")],
        ),
        ShortAnswerQuestion(
            stem="Qual a capital?", accept=["Brasília"], reject=["Rio"]
        ),
        ShortAnswerQuestion(stem="Qual a capital?"),
    ],
    ids=["line", "list", "comment", "with-reject", "no-pattern"],
)
def test_b4_render_never_uses_the_accept_alias(question: ShortAnswerQuestion) -> None:
    assert "short-answer/accept" not in question.render()


_ROUND_TRIP_BODIES = {
    "line": "[short-answer]: Brasília\n",
    "alias-line": "[short-answer/accept]: Brasília\n",
    "exact": "[short-answer]: `math.isnan`\n",
    "regex": "[short-answer]: /1822-0?9-0?7/i\n",
    "no-pattern": "[short-answer]\n",
    "list": "[short-answer]:\n* Brasília\n* DF\n",
    "alias-list": "[short-answer/accept]:\n* Brasília\n* DF\n",
    "feedback": "[short-answer]:\n* Brasília\n  > Certo!\n",
    "comment-only": "[short-answer]:\n* Brasília\n  ! Nome oficial\n",
    "feedback-and-comment": "[short-answer]:\n* Brasília\n  > Certo!\n  ! Nome oficial\n",
    "with-reject-line": "[short-answer]: Brasília\n\n[short-answer/reject]: Rio\n",
    "with-reject-list": "[short-answer]:\n* Brasília\n\n[short-answer/reject]:\n* Rio\n  ! Foi capital\n",
    "bare-and-detached-list": "[short-answer]\n\n* Cite a evaporação.\n",
    "line-and-detached-list": "[short-answer]: Brasília\n\n* Rio de Janeiro\n",
}


@pytest.mark.parametrize(
    "body", list(_ROUND_TRIP_BODIES.values()), ids=list(_ROUND_TRIP_BODIES)
)
def test_b4_question_render_round_trips_through_load(body: str) -> None:
    first = load(_q(body), format="mdq").document
    assert first is not None
    again = load(first.render(), format="mdq").document
    assert again is not None
    assert again.to_dict() == first.to_dict()


def test_b4_blank_render_single_plain_accept_as_line() -> None:
    question = FillInQuestion(
        stem=FILL_STEM, blanks=[ShortAnswerBlank(id="bioma", accept=["Amazônia"])]
    )
    src = question.render()
    assert "[^bioma/short-answer]: Amazônia" in src
    assert "short-answer/accept" not in src


def test_b4_blank_render_two_patterns_as_list() -> None:
    question = FillInQuestion(
        stem=FILL_STEM,
        blanks=[ShortAnswerBlank(id="bioma", accept=["Amazônia", "Amazon"])],
    )
    assert "[^bioma/short-answer]:\n* Amazônia\n* Amazon" in question.render()


@pytest.mark.parametrize(
    "blank",
    [
        ShortAnswerBlank(id="bioma", accept=["Amazônia", "Amazon"]),
        ShortAnswerBlank(
            id="bioma", accept=[AnswerPattern(pattern="Amazônia", comment="x")]
        ),
        ShortAnswerBlank(id="bioma", accept=["Amazônia"], reject=["Cerrado"]),
        ShortAnswerBlank(id="bioma"),
    ],
    ids=["list", "comment", "with-reject", "no-pattern"],
)
def test_b4_blank_render_never_uses_the_accept_alias(blank: ShortAnswerBlank) -> None:
    src = FillInQuestion(stem=FILL_STEM, blanks=[blank]).render()
    assert "short-answer/accept" not in src


def test_b4_blank_render_reject_is_a_list() -> None:
    blank = ShortAnswerBlank(id="bioma", accept=["Amazônia"], reject=["Cerrado"])
    src = FillInQuestion(stem=FILL_STEM, blanks=[blank]).render()
    assert "[^bioma/short-answer/reject]:\n* Cerrado" in src


_BLANK_ROUND_TRIP_BODIES = {
    "line": "[^bioma/short-answer]: Amazônia\n",
    "alias-line": "[^bioma/short-answer/accept]: Amazônia\n",
    "regex": "[^bioma/short-answer]: /Amaz[oô]nia/i\n",
    "no-pattern": "[^bioma/short-answer]\n",
    "list": "[^bioma/short-answer]:\n* Amazônia\n* Amazon\n",
    "alias-list": "[^bioma/short-answer/accept]:\n* Amazônia\n* Amazon\n",
    "comment-only": "[^bioma/short-answer]:\n* Amazônia\n  ! Nome oficial\n",
    "feedback": "[^bioma/short-answer]:\n* Amazônia\n  > Certo!\n",
    "with-reject-line": "[^bioma/short-answer]: Amazônia\n\n[^bioma/short-answer/reject]: Cerrado\n",
    "with-reject-list": "[^bioma/short-answer]:\n* Amazônia\n\n[^bioma/short-answer/reject]:\n* Cerrado\n",
    "bare-and-detached-list": "[^bioma/short-answer]\n\n* Cite o rio Negro.\n",
}


@pytest.mark.parametrize(
    "body", list(_BLANK_ROUND_TRIP_BODIES.values()), ids=list(_BLANK_ROUND_TRIP_BODIES)
)
def test_b4_fill_in_render_round_trips_through_load(body: str) -> None:
    first = load(_f(body), format="mdq").document
    assert first is not None
    again = load(first.render(), format="mdq").document
    assert again is not None
    assert again.to_dict() == first.to_dict()


#
# AC11: docs
#
def test_b4_lint_codes_doc_has_no_detached_answer_list() -> None:
    from pathlib import Path

    doc = Path(__file__).resolve().parents[2] / "docs" / "lint-codes.md"
    assert "detached-answer-list" not in doc.read_text(encoding="utf-8")
