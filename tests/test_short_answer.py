"""
Short-answer accept/reject: the pattern mini-language, `effective_accept`,
the removed `oneOf`/`regex` fields, and the diacritics property.

The corpus covers the grading (`examples/grading/short-answer.yaml`), the
matching (`examples/matching/`) and the `[short-answer/accept]` /
`[short-answer/reject]` blocks of the parser; these cases cover the model
API.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from mdq import models
from _corpus import VALID_SOURCES, parsed_sibling, relative_id
from _parse import parse_file


#
# Pattern mini-language
#
def test_a_tab_and_line_feed_only_pattern_is_an_error() -> None:
    with pytest.raises(ValueError):
        models.AnswerPattern(pattern="\t\n")


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


def test_regex_in_accept_is_case_sensitive_without_the_i_flag() -> None:
    question = models.ShortAnswerQuestion(
        stem="Name a Brazilian biome.", accept=["/cerrado|amazonia/"]
    )
    assert [p.pattern for p in question.effective_accept()] == ["/cerrado|amazonia/"]
    assert question.score_response("cerrado").score == 1.0
    assert question.score_response("Cerrado").score == 0.0


@pytest.mark.parametrize("field", ["one_of", "regex"])
def test_short_answer_question_no_longer_has_one_of_or_regex(field: str) -> None:
    assert field not in models.ShortAnswerQuestion.model_fields
    assert field not in models.ShortAnswerBlank.model_fields


#
# Fixture round-trip
#
_NEW_FIXTURE_NAMES = frozenset(
    {
        "accept-reject.mdq.md",
        "accept-regex-flags.mdq.md",
        "exact-block.mdq.md",
        "pre-validation.mdq.md",
    }
)

_NEW_FIXTURES = [
    source
    for source in VALID_SOURCES
    if source.parent.name == "short-answer" and source.name in _NEW_FIXTURE_NAMES
]


def test_new_fixtures_are_present() -> None:
    """Guard against a rename making the parametrized test below a no-op."""
    assert {source.name for source in _NEW_FIXTURES} == _NEW_FIXTURE_NAMES


@pytest.mark.parametrize(
    "source", _NEW_FIXTURES, ids=[relative_id(p) for p in _NEW_FIXTURES]
)
def test_new_short_answer_fixture_round_trips(source: Path) -> None:
    got = parse_file(source)
    expected = yaml.safe_load(parsed_sibling(source).read_text(encoding="utf-8"))
    assert got == expected


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
