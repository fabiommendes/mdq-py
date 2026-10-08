"""
Exact comparison of a backtick-enclosed pattern (docs/references/patterns.md,
"Exact literals"): NFC, trim `UNICODE_SPACE` at the ends, then compare code
point for code point. The result never depends on `diacritics`.

The shared vectors live in `examples/matching/exact.yaml`.
"""

from __future__ import annotations

import unicodedata
from typing import Any, Literal

import pytest
import yaml
from _corpus import EXAMPLES_ROOT

from mdq import models

Mode = Literal["fold", "keep"]
MODES: tuple[Mode, ...] = ("fold", "keep")

_CASES: list[dict[str, Any]] = yaml.safe_load(
    (EXAMPLES_ROOT / "matching" / "exact.yaml").read_text(encoding="utf-8")
)["cases"]

VECTORS = [
    pytest.param(
        case["pattern"],
        case["response"],
        case["match"],
        mode,
        id=f"{case['name']}-{mode}",
    )
    for case in _CASES
    for mode in MODES
]


def short_answer_score(pattern: str, response: str, mode: Mode) -> float:
    question = models.ShortAnswerQuestion(
        stem="Qual é a capital do Brasil?", accept=[f"`{pattern}`"], diacritics=mode
    )
    return question.score_response(response).score


def blank_score(pattern: str, response: str, mode: Mode) -> float:
    question = models.FillInQuestion(
        stem="A capital do Ceará é [^capital].",
        diacritics=mode,
        blanks=[models.ShortAnswerBlank(id="capital", accept=[f"`{pattern}`"])],
    )
    return question.score_response({"capital": response}).score


def test_vector_file_has_seventeen_cases() -> None:
    assert len(_CASES) == 17


@pytest.mark.parametrize(("pattern", "response", "match", "mode"), VECTORS)
def test_short_answer_vectors(
    pattern: str, response: str, match: bool, mode: Mode
) -> None:
    assert short_answer_score(pattern, response, mode) == (1.0 if match else 0.0)


@pytest.mark.parametrize(("pattern", "response", "match", "mode"), VECTORS)
def test_fill_in_blank_vectors(
    pattern: str, response: str, match: bool, mode: Mode
) -> None:
    assert blank_score(pattern, response, mode) == (1.0 if match else 0.0)


#
# `reject` uses the same comparison
#
def _reject_question() -> models.ShortAnswerQuestion:
    return models.ShortAnswerQuestion(
        stem="Qual é a maior cidade da Amazônia?",
        accept=["Manaus"],
        reject=[{"pattern": "`Brasília`", "feedback": "Brasília fica no Cerrado."}],
    )


@pytest.mark.parametrize(
    "response",
    ["Brasília", "  Brasília\n", unicodedata.normalize("NFD", "Brasília")],
    ids=["same", "trimmed", "decomposed"],
)
def test_exact_literal_in_reject_gives_its_feedback(response: str) -> None:
    result = _reject_question().score_response(response)
    assert result.score == 0.0
    assert result.feedback == ["Brasília fica no Cerrado."]


@pytest.mark.parametrize("response", ["brasília", "Brasilia"])
def test_exact_literal_in_reject_does_not_match_a_different_text(response: str) -> None:
    assert _reject_question().score_response(response).feedback == []
