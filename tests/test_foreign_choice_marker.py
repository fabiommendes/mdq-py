"""
`foreign-choice-marker`: after the question type is inferred (or forced by
frontmatter), every bracket value must belong to the `value` rule of that
type (docs/question-types/base.md "Type inference"; docs/lint-codes.md;
multiple-choice.md, multiple-selection.md and true-false.md "Body").
"""

from __future__ import annotations

import json

import pytest
from _corpus import INVALID_DIR

import mdq
from mdq import errors
from mdq._parser._choices import foreign_choice_index

NBSP = " "


def _load(source: str) -> mdq.Loaded:
    return mdq.load(source, kind="question")


def _errors(loaded: mdq.Loaded) -> list[mdq.Diagnostic]:
    return [d for d in loaded.diagnostics if d.severity == "error"]


def _assert_foreign_at(loaded: mdq.Loaded, path: tuple[object, ...]) -> None:
    assert loaded.document is None
    [error] = _errors(loaded)
    assert error.code == "foreign-choice-marker"
    assert error.severity == "error"
    assert tuple(error.path) == path


def _list(*markers: str, frontmatter: str = "") -> str:
    items = "\n".join(f"* [{m or ' '}] Opção {i}" for i, m in enumerate(markers))
    return f"{frontmatter}Qual destas opções vale para o Pantanal?\n\n{items}\n"


#
# AC1: foreign_choice_index
#
@pytest.mark.parametrize(
    ("question_type", "values"),
    [
        ("multiple-choice", ["", "*", "50%", "-25%", "12.5%"]),
        ("multiple-choice", [""]),
        ("multiple-selection", ["", "x", "X"]),
        ("true-false", ["T", "f", "对", "偽", "é"]),
    ],
)
def test_accepted_values_have_no_foreign_index(
    question_type: str, values: list[str]
) -> None:
    assert foreign_choice_index(question_type, values) is None


@pytest.mark.parametrize(
    ("question_type", "values", "expected"),
    [
        ("multiple-choice", ["*", "x"], 1),
        ("multiple-selection", ["x", "*"], 1),
        ("multiple-selection", ["", "50%"], 1),
        ("multiple-selection", ["x", "?"], 1),
        ("multiple-selection", ["T"], 0),
        ("true-false", ["T", ""], 1),
        ("true-false", ["T", "x"], 1),
        ("true-false", ["X"], 0),
        ("true-false", ["T", "*"], 1),
        ("true-false", ["T", "TT"], 1),
        ("true-false", ["T", "1"], 1),
    ],
)
def test_first_offender_index(
    question_type: str, values: list[str], expected: int
) -> None:
    assert foreign_choice_index(question_type, values) == expected


@pytest.mark.parametrize(
    "question_type", ["multiple-choice", "multiple-selection", "true-false"]
)
@pytest.mark.parametrize("offender", ["?", "#", NBSP])
def test_symbols_and_nbsp_are_foreign_in_every_type(
    question_type: str, offender: str
) -> None:
    assert foreign_choice_index(question_type, [offender]) == 0


@pytest.mark.parametrize(
    ("question_type", "good"),
    [("multiple-choice", "*"), ("multiple-selection", "x"), ("true-false", "T")],
)
def test_first_of_several_offenders_is_returned(question_type: str, good: str) -> None:
    assert foreign_choice_index(question_type, [good, "?", "#", NBSP]) == 1


#
# AC2: inference, then check
#
@pytest.mark.parametrize(
    ("markers", "index"),
    [
        (["*", "x"], 1),
        (["x", "?"], 1),
        (["T", "", "F"], 1),
        (["", "?"], 1),
    ],
)
def test_inferred_type_rejects_foreign_marker(markers: list[str], index: int) -> None:
    _assert_foreign_at(_load(_list(*markers)), ("choices", index))


@pytest.mark.parametrize(
    ("markers", "question_type"),
    [
        (["*", "", "50%"], "multiple-choice"),
        (["", ""], "multiple-selection"),
        (["T", "F"], "true-false"),
        (["x", ""], "multiple-selection"),
    ],
)
def test_consistent_markers_load_with_the_inferred_type(
    markers: list[str], question_type: str
) -> None:
    loaded = _load(_list(*markers))
    assert _errors(loaded) == []
    assert loaded.document.type == question_type


#
# AC3: forced type
#
@pytest.mark.parametrize(
    ("forced", "markers", "index"),
    [
        ("multiple-selection", ["*", "x"], 0),
        ("multiple-choice", ["*", "x"], 1),
        ("true-false", ["T", ""], 1),
    ],
)
def test_forced_type_rejects_foreign_marker(
    forced: str, markers: list[str], index: int
) -> None:
    source = _list(*markers, frontmatter=f"---\ntype: {forced}\n---\n\n")
    _assert_foreign_at(_load(source), ("choices", index))


#
# AC4: fill-in choice blank
#
def _fill_in(*markers: str) -> str:
    items = "\n".join(f"* [{m or ' '}] Bioma {i}" for i, m in enumerate(markers))
    return f"O maior bioma do Brasil é a [^biome].\n\n[^biome]:\n{items}\n"


def test_fill_in_choice_blank_rejects_foreign_marker() -> None:
    _assert_foreign_at(_load(_fill_in("x", "")), ("blanks", 0, "choices", 0))


@pytest.mark.parametrize("markers", [["*", ""], ["*", "50%"], ["", "*", ""]])
def test_fill_in_choice_blank_accepts_multiple_choice_values(
    markers: list[str],
) -> None:
    loaded = _load(_fill_in(*markers))
    assert _errors(loaded) == []
    assert loaded.document.type == "fill-in"


#
# AC5: error class
#
def test_foreign_choice_marker_error_has_code_and_path() -> None:
    error = errors.ForeignChoiceMarker("x", "multiple-choice", ("choices", 1))
    assert isinstance(error, errors.ParseError)
    assert error.code == "foreign-choice-marker"
    assert tuple(error.path) == ("choices", 1)


#
# Corpus
#
@pytest.mark.parametrize(
    "name",
    [
        "multiple-choice-foreign-marker",
        "multiple-selection-forced-star",
        "multiple-selection-unknown-marker",
        "true-false-blank-marker",
        "fill-in-foreign-marker",
    ],
)
def test_corpus_example_reports_its_lint_json(name: str) -> None:
    expected = json.loads((INVALID_DIR / f"{name}.lint.json").read_text("utf-8"))
    loaded = mdq.load(INVALID_DIR / f"{name}.mdq.md", kind="question")
    assert loaded.document is None
    assert [
        {"code": d.code, "severity": d.severity, "path": list(d.path)}
        for d in loaded.diagnostics
    ] == [
        {"code": e["code"], "severity": e["severity"], "path": e["path"]}
        for e in expected
    ]
