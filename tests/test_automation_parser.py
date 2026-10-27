"""
Parser (grading examples) and render side of `unmatched`, `incorrectFeedback`
and the questions with no pattern (docs/question-types/short-answer.md "Frontmatter",
"Block with no pattern", "Grading"/"Examples"; fill-in.md "Frontmatter").
"""

from __future__ import annotations

from typing import Any

import pytest

import mdq
from mdq import models


def _load(source: str) -> mdq.Loaded:
    return mdq.load(source, kind="question")


def _errors(loaded: mdq.Loaded) -> list[mdq.Diagnostic]:
    return [d for d in loaded.diagnostics if d.severity == "error"]


def _roundtrip(question: Any) -> Any:
    loaded = _load(str(question))
    assert _errors(loaded) == []
    return loaded.document


def _frontmatter_block(text: str) -> str:
    return text.split("\n---\n", 1)[0] if text.startswith("---\n") else ""


#
# The six examples of short-answer.md "Examples" (Grading). Their parsing is
# in the example pairs and their `automation` in
# `examples/grading/automation.yaml`; here they must render back.
#
_STEM = "What is the capital of Brazil?\n\n"
EXAMPLES = {
    "automatic": ("[short-answer]: Brasília\n", "automatic"),
    "incorrect-feedback": (
        "---\nincorrectFeedback: This city was never the capital.\n---\n\n"
        + _STEM
        + "[short-answer]: Brasília\n\n[short-answer/reject]:\n"
        "* Rio de Janeiro\n  > It was the capital until 1960.\n",
        "automatic",
    ),
    "semi-accept-reject": (
        "---\nunmatched: manual\n---\n\nName a biome of central Brazil.\n\n"
        "[short-answer]:\n* Cerrado\n* Pantanal\n\n[short-answer/reject]:\n"
        "* Savana\n  > Savanna is the general term. Name the Brazilian biome.\n",
        "semi-automatic",
    ),
    "semi-accept-only": (
        "---\nunmatched: manual\n---\n\nName a biome of central Brazil.\n\n"
        "[short-answer]:\n* Cerrado\n* Pantanal\n",
        "semi-automatic",
    ),
    "semi-reject-only": (
        "Name a biome of central Brazil.\n\n[short-answer]\n\n[short-answer/reject]:\n"
        "* Savana\n  > Savanna is the general term. Name the Brazilian biome.\n",
        "semi-automatic",
    ),
    "manual": ("Name a biome of central Brazil.\n\n[short-answer]\n", "manual"),
}


@pytest.mark.parametrize("name", EXAMPLES)
def test_grading_example_round_trips(name: str) -> None:
    source, _ = EXAMPLES[name]
    if name == "automatic":
        source = _STEM + source
    loaded = _load(source)
    question = loaded.document
    assert _roundtrip(question) == question


#
# AC2: render
#
def _sa(**fields: Any) -> models.ShortAnswerQuestion:
    return models.ShortAnswerQuestion(stem="Qual é a capital do Brasil?", **fields)


@pytest.mark.parametrize(
    ("key", "field", "value"),
    [
        ("unmatched", "unmatched", "manual"),
        ("incorrectFeedback", "incorrect_feedback", "Tente de novo."),
    ],
)
def test_set_field_is_written_to_the_frontmatter_and_round_trips(
    key: str, field: str, value: str
) -> None:
    question = _sa(accept=["Brasília"], **{field: value})
    assert key in _frontmatter_block(str(question))
    assert _roundtrip(question) == question


def test_unset_fields_are_omitted_from_the_render() -> None:
    text = str(_sa(accept=["Brasília"]))
    assert "unmatched" not in text
    assert "incorrectFeedback" not in text


@pytest.mark.parametrize(
    "fields", [{}, {"unmatched": "manual"}, {"unmatched": "incorrect"}]
)
def test_question_with_no_accept_renders_a_tag_without_a_colon(fields: dict) -> None:
    question = _sa(**fields)
    text = str(question)
    assert text.rstrip("\n").endswith("[short-answer]")
    assert "openEnded" not in text
    assert _roundtrip(question) == question


def test_reject_only_question_renders_an_empty_accept_block_and_round_trips() -> None:
    question = _sa(
        reject=[models.AnswerPattern(pattern="Rio", feedback="Foi até 1960.")]
    )
    text = str(question)
    assert "[short-answer]\n\n[short-answer/reject]:" in text
    assert _roundtrip(question) == question


def test_literal_backtick_asterisk_keeps_its_backticks() -> None:
    question = _sa(accept=["`*`"])
    assert "[short-answer]: `*`" in str(question)
    assert _roundtrip(question) == question


def test_render_never_writes_open_ended() -> None:
    for question in (_sa(), _sa(accept=["Brasília"]), _sa(reject=["Rio"])):
        assert "openEnded" not in str(question)


def test_fill_in_unmatched_round_trips() -> None:
    question = models.FillInQuestion(
        stem="O rio [^rio] banha Manaus.",
        unmatched="manual",
        blanks=[models.ShortAnswerBlank(id="rio", accept=["Negro"])],
    )
    assert "unmatched" in _frontmatter_block(str(question))
    assert _roundtrip(question) == question


def test_fill_in_without_unmatched_omits_it() -> None:
    question = models.FillInQuestion(
        stem="O rio [^rio] banha Manaus.",
        blanks=[models.ShortAnswerBlank(id="rio", accept=["Negro"])],
    )
    assert "unmatched" not in str(question)


def test_fill_in_blank_with_no_accept_renders_an_empty_block_and_round_trips() -> None:
    question = models.FillInQuestion(
        stem="O rio [^rio] banha Manaus.",
        blanks=[models.ShortAnswerBlank(id="rio")],
    )
    assert "[^rio/short-answer]\n" in str(question) + "\n"
    assert "[^rio/short-answer]:" not in str(question)
    assert "openEnded" not in str(question)
    assert _roundtrip(question) == question
