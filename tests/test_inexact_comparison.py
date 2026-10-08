"""
Inexact comparison of plain literal patterns (docs/references/patterns.md,
"Inexact literals"), plus what it must not change: exact literals and the
regex `n` flag.

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
def test_vector_file_has_forty_cases() -> None:
    assert len(_CASES) == 40


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


# One case per step, spelled out so the blank coverage does not depend on the file.
@pytest.mark.parametrize(
    ("pattern", "response", "mode", "expected"),
    [
        pytest.param("Manaus", "Mana\u200bus", "keep", True, id="ignorable"),
        pytest.param("Ørsted", "Orsted", "fold", True, id="letters-fold"),
        pytest.param("Ørsted", "Orsted", "keep", False, id="letters-keep"),
        pytest.param("caixa d'água", "caixa d’água", "keep", True, id="punctuation"),
        pytest.param("ᲊ", "Ᲊ", "keep", True, id="case-folding-unicode-16"),
        pytest.param(
            "Rio Negro", "Rio\u00a0\u2003Negro", "fold", True, id="whitespace"
        ),
        pytest.param(
            "Rio Negro", "Rio\x1fNegro", "fold", False, id="control-not-space"
        ),
    ],
)
def test_fill_in_blank_one_case_per_step(
    pattern: str, response: str, mode: Mode, expected: bool
) -> None:
    assert blank_score(pattern, response, mode) == (1.0 if expected else 0.0)


#
# Exact literals are not compared inexactly
#
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "response", [" Manaus ", "\tManaus\n", "\u00a0Manaus\u2003", "Manaus"]
)
def test_exact_literal_trims_unicode_spaces_at_the_ends(
    response: str, mode: Mode
) -> None:
    assert short_answer_score("`Manaus`", response, mode) == 1.0


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "response",
    ["Manaus\x1f", "Mana\u200bus", "manaus", "Manaus’", "Man aus", "Manaus."],
    ids=[
        "control",
        "zero-width-space",
        "case",
        "extra-quote",
        "inner-space",
        "extra-dot",
    ],
)
def test_exact_literal_rejects_any_other_difference(response: str, mode: Mode) -> None:
    assert short_answer_score("`Manaus`", response, mode) == 0.0


def test_exact_literal_keeps_interior_whitespace_significant() -> None:
    assert short_answer_score("`Rio Negro`", "Rio  Negro", "fold") == 0.0


def test_exact_literal_does_not_fold_diacritics() -> None:
    assert short_answer_score("`Brasília`", "Brasilia", "fold") == 0.0


#
# Regex `n` flag: combining marks only, no `letters` table
#
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("pattern", "response", "expected"),
    [
        ("/Brasilia/n", "Brasília", True),
        ("/Brasilia/n", "Brasilia", True),
        ("/Orsted/n", "Ørsted", False),
        ("/Ørsted/n", "Ørsted", True),
        ("/Brasilia/", "Brasília", False),
    ],
)
def test_regex_n_flag_removes_combining_marks_only(
    pattern: str, response: str, expected: bool, mode: Mode
) -> None:
    assert short_answer_score(pattern, response, mode) == (1.0 if expected else 0.0)


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


def test_letters_replacement_is_not_reapplied_to_its_result() -> None:
    # "ß" becomes "ss"; a second pass over "ss" must not change anything else.
    assert matches("Straße", "STRASSE", "fold")
    assert not matches("Straße", "STRASSSE", "fold")
    assert matches("Cæsar", "caesar", "fold")
    assert not matches("Cæsar", "caaesar", "fold")


@pytest.mark.parametrize(
    ("pattern", "response"),
    [
        ("Ceará", "CEARÁ"),
        ("Straße", "STRASSE"),
        ("Brasília", "Brasi\u0301lia"),
        ("caixa d'água", "caixa d’água"),
        ("pau-brasil", "pau—brasil"),
        ("ᲊ", "Ᲊ"),
    ],
)
def test_keep_still_applies_case_folding_and_punctuation(
    pattern: str, response: str
) -> None:
    assert matches(pattern, response, "keep")


def test_keep_still_distinguishes_diacritics() -> None:
    assert not matches("Ceará", "Ceara", "keep")
    assert matches("Ceará", "Ceara", "fold")


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Straße", "STRASSE"),
        ("caixa d'água", "caixa d’água"),
        ("Manaus", "Mana\u200bus"),
        ("Rio Negro", "  rio \u00a0 negro "),
        ("Ørsted", "orsted"),
        ("Brasília", "Brasilia"),
        ("Belém", "Manaus"),
    ],
)
def test_comparison_is_symmetric(first: str, second: str, mode: Mode) -> None:
    assert matches(first, second, mode) == matches(second, first, mode)
