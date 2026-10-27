"""
Inexact comparison of plain literal patterns (docs/references/patterns.md,
"Inexact literals"). Exact literals and the regex `n` flag are covered by
the vectors of `examples/matching/`.

The shared vectors live in `examples/matching/inexact.yaml`; the tables in
`docs/references/inexact-tables.json`.
"""

from __future__ import annotations

import json
import unicodedata
from typing import Any, Literal

import pytest
import yaml

from mdq import models

from _corpus import EXAMPLES_ROOT, MDQ_ROOT

Mode = Literal["fold", "keep"]
MODES: tuple[Mode, ...] = ("fold", "keep")

_CASES: list[dict[str, Any]] = yaml.safe_load(
    (EXAMPLES_ROOT / "matching" / "inexact.yaml").read_text(encoding="utf-8")
)["cases"]
_TABLES: dict[str, Any] = json.loads(
    (MDQ_ROOT / "docs" / "references" / "inexact-tables.json").read_text(
        encoding="utf-8"
    )
)

VECTORS = [
    pytest.param(
        case["pattern"], case["response"], case[mode], mode, id=f"{case['name']}-{mode}"
    )
    for case in _CASES
    for mode in MODES
]


def short_answer_score(pattern: str, response: str, mode: Mode) -> float:
    question = models.ShortAnswerQuestion(
        stem="Qual é a capital do Brasil?", accept=[pattern], diacritics=mode
    )
    return question.score_response(response).score


def blank_score(pattern: str, response: str, mode: Mode) -> float:
    question = models.FillInQuestion(
        stem="A capital do Ceará é [^capital].",
        diacritics=mode,
        blanks=[models.ShortAnswerBlank(id="capital", accept=[pattern])],
    )
    return question.score_response({"capital": response}).score


def matches(pattern: str, response: str, mode: Mode = "fold") -> bool:
    return short_answer_score(pattern, response, mode) == 1.0


#
# Shared vectors
#
@pytest.mark.parametrize(("pattern", "response", "expected", "mode"), VECTORS)
def test_short_answer_vectors(
    pattern: str, response: str, expected: bool, mode: Mode
) -> None:
    assert short_answer_score(pattern, response, mode) == (1.0 if expected else 0.0)


@pytest.mark.parametrize(("pattern", "response", "expected", "mode"), VECTORS)
def test_fill_in_blank_vectors(
    pattern: str, response: str, expected: bool, mode: Mode
) -> None:
    assert blank_score(pattern, response, mode) == (1.0 if expected else 0.0)


#
# Direct properties
#
_ONCE = [
    (key, value)
    for key, value in _TABLES["letters"].items()
    if unicodedata.normalize("NFKC", key) == key
]


@pytest.mark.parametrize(
    "key", [key for key, _ in _ONCE], ids=lambda key: f"U+{ord(key):04X}"
)
def test_letters_entry_applies_with_fold(key: str) -> None:
    assert matches(key, _TABLES["letters"][key], "fold")


@pytest.mark.parametrize(
    "key", [key for key, _ in _ONCE], ids=lambda key: f"U+{ord(key):04X}"
)
def test_letters_replacement_is_applied_once(key: str) -> None:
    """The result of a replacement is not replaced again, so it never doubles up."""
    value = _TABLES["letters"][key]
    assert not matches(key, value + value, "fold")
