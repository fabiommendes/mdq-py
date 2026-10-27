"""
Short-answer model API: `effective_accept`, the removed `oneOf`/`regex`
fields, and the diacritics property.

The corpus covers the pattern language, the grading
(`examples/grading/short-answer.yaml`), the matching (`examples/matching/`)
and the `[short-answer/accept]` / `[short-answer/reject]` blocks of the parser.
"""

from __future__ import annotations

import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mdq import models


#
# `accept` is the only answer list
#
def test_effective_accept_returns_the_accept_list() -> None:
    question = models.ShortAnswerQuestion(
        stem="Name a primary colour.", accept=["red", "green", "blue"]
    )
    assert [p.pattern for p in question.effective_accept()] == ["red", "green", "blue"]
    assert question.score_response("Green").score == 1.0


def test_effective_accept_is_empty_without_accept() -> None:
    question = models.ShortAnswerQuestion(stem="Describe the Cerrado.")
    assert question.effective_accept() == []


@pytest.mark.parametrize("field", ["one_of", "regex"])
def test_short_answer_question_no_longer_has_one_of_or_regex(field: str) -> None:
    assert field not in models.ShortAnswerQuestion.model_fields
    assert field not in models.ShortAnswerBlank.model_fields


#
# Diacritics (docs/question-types/short-answer.md § Diacritics)
#
@given(
    st.text(
        alphabet=st.sampled_from("aeiouAEIOU áéíóúâêôãõàÁÉÍÓÚÂÊÔÃÕÀ "),
        min_size=1,
        max_size=15,
    ).filter(lambda s: s.strip())
)
def test_fold_always_matches_a_patterns_accent_stripped_form(word: str) -> None:
    """Property from the handoff: under `fold`, a pattern and its
    accent-stripped form always match."""
    stripped = unicodedata.normalize("NFKD", word)
    stripped = "".join(ch for ch in stripped if not unicodedata.combining(ch))
    pattern = models.AnswerPattern(pattern=word)
    assert pattern.matches(stripped, diacritics="fold") is True
