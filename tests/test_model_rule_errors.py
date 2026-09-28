"""
Tests for the "New errors" table of `dev/specs/to-do/lint-on-models.md`
(candidate C2 of `dev/architecture-review.md`).

Seven rules that used to be `warning`-level lint checks in
`mdq.linter.lint_document` become pydantic model validators, raising
`PydanticCustomError(code, message)` the way `_check_unique_choices`
does (see `dev/specs/to-do/unique-ids.md` / `tests/test_unique_ids.py`,
which this file mirrors): `load` must report each one as an `error`
diagnostic with `document=None`, at the same path the old lint warning
used.

`blank-text-field` is the one exception: the spec allows the code
`blank-intro-field` for the error form of `preamble`/`epilogue`/`stem`,
if sharing one code across two severities causes a problem. Those tests
accept either code -- see `_BLANK_INTRO_CODES` -- and this is called out
in the report.

Fixtures use Brazil-themed questions, per AGENTS.md. Written against the
public `mdq.load` API only -- no parser/linter internals.
"""

from __future__ import annotations

import pytest

from mdq import Diagnostic, load

#: Either code is acceptable for the *error* form of `blank-text-field`
#: on `preamble`/`epilogue`/`stem` -- see the module docstring.
_BLANK_INTRO_CODES = frozenset({"blank-text-field", "blank-intro-field"})


def _codes(diagnostics: list[Diagnostic]) -> set[str]:
    return {d.code for d in diagnostics}


def _errors(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    return [d for d in diagnostics if d.severity == "error"]


def _assert_one_error(diagnostics: list[Diagnostic], codes: str | frozenset[str]) -> Diagnostic:
    wanted = {codes} if isinstance(codes, str) else codes
    matching = [d for d in diagnostics if d.code in wanted]
    assert len(matching) == 1, (
        f"expected exactly one diagnostic with code in {wanted!r}, "
        f"got {_codes(diagnostics)!r}"
    )
    diagnostic = matching[0]
    assert diagnostic.severity == "error"
    return diagnostic


# ---------------------------------------------------------------------
# invalid-regex
# ---------------------------------------------------------------------


def test_invalid_regex_in_short_answer_regex_field_is_a_model_error() -> None:
    doc = {
        "type": "short-answer",
        "stem": "Qual é a sigla do estado do Amazonas?",
        "regex": "/[AM/",
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_one_error(loaded.diagnostics, "invalid-regex")
    assert diagnostic.path == ("regex",)


def test_invalid_regex_in_accept_pattern_is_a_model_error() -> None:
    doc = {
        "type": "short-answer",
        "stem": "Qual é a sigla do estado do Amazonas?",
        "accept": ["/[AM/"],
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_one_error(loaded.diagnostics, "invalid-regex")
    assert diagnostic.path == ("accept", 0)


def test_invalid_regex_in_fill_in_short_answer_blank_is_a_model_error() -> None:
    doc = {
        "type": "fill-in",
        "stem": "A capital do Brasil é [^capital].",
        "blanks": [
            {
                "id": "capital",
                "type": "short-answer",
                "regex": "/[Br/",
            }
        ],
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_one_error(loaded.diagnostics, "invalid-regex")
    assert diagnostic.path == ("blanks", 0, "regex")


def test_valid_regex_does_not_error() -> None:
    doc = {
        "type": "short-answer",
        "stem": "Qual é a sigla do estado do Amazonas?",
        "regex": "/AM/",
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert "invalid-regex" not in _codes(loaded.diagnostics)


# ---------------------------------------------------------------------
# undefined-blank
# ---------------------------------------------------------------------


def test_undefined_blank_marker_is_a_model_error() -> None:
    doc = {
        "type": "fill-in",
        "stem": "O bioma [^bioma] abriga o [^rio].",
        "blanks": [
            {"id": "rio", "type": "short-answer", "oneOf": ["Amazonas"]},
        ],
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_one_error(loaded.diagnostics, "undefined-blank")
    assert diagnostic.path == ("stem",)


def test_every_marker_naming_a_declared_blank_does_not_error() -> None:
    doc = {
        "type": "fill-in",
        "stem": "O bioma [^bioma] abriga o rio [^rio].",
        "blanks": [
            {"id": "bioma", "type": "short-answer", "oneOf": ["Amazônia"]},
            {"id": "rio", "type": "short-answer", "oneOf": ["Amazonas"]},
        ],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert "undefined-blank" not in _codes(loaded.diagnostics)


# ---------------------------------------------------------------------
# unreferenced-blank
# ---------------------------------------------------------------------


def test_unreferenced_blank_is_a_model_error() -> None:
    doc = {
        "type": "fill-in",
        "stem": "O maior bioma brasileiro é a [^bioma].",
        "blanks": [
            {"id": "bioma", "type": "short-answer", "oneOf": ["Amazônia"]},
            {"id": "regiao", "type": "short-answer", "oneOf": ["Norte"]},
        ],
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_one_error(loaded.diagnostics, "unreferenced-blank")
    assert diagnostic.path == ("blanks", 1, "id")


def test_every_declared_blank_referenced_does_not_error() -> None:
    doc = {
        "type": "fill-in",
        "stem": "O maior bioma brasileiro é a [^bioma].",
        "blanks": [
            {"id": "bioma", "type": "short-answer", "oneOf": ["Amazônia"]},
        ],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert "unreferenced-blank" not in _codes(loaded.diagnostics)


# ---------------------------------------------------------------------
# malformed-locale
# ---------------------------------------------------------------------


def test_malformed_locale_is_a_model_error() -> None:
    doc = {
        "type": "essay",
        "stem": "Descreva as características do bioma Cerrado.",
        "input": "text",
        "locale": "brasil",
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_one_error(loaded.diagnostics, "malformed-locale")
    assert diagnostic.path == ("locale",)


@pytest.mark.parametrize("locale", ["pt", "pt-BR", "zh-Hans-CN", "en"])
def test_well_formed_locale_does_not_error(locale: str) -> None:
    doc = {
        "type": "essay",
        "stem": "Descreva as características do bioma Cerrado.",
        "input": "text",
        "locale": locale,
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert "malformed-locale" not in _codes(loaded.diagnostics)


# ---------------------------------------------------------------------
# reserved-true-false-marker
# ---------------------------------------------------------------------


def test_reserved_true_false_marker_is_a_model_error() -> None:
    doc = {
        "type": "true-false",
        "stem": "Julgue as afirmações sobre a fauna brasileira.",
        "choices": [
            {
                "id": "onca",
                "text": "A onça-pintada é o maior felino das Américas.",
                "correct": True,
                "marker": "X",
            },
            {
                "id": "capivara",
                "text": "A capivara é o maior roedor do mundo.",
                "correct": True,
                "marker": "T",
            },
        ],
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_one_error(loaded.diagnostics, "reserved-true-false-marker")
    assert diagnostic.path == ("choices", 0, "marker")


def test_non_reserved_true_false_marker_does_not_error() -> None:
    doc = {
        "type": "true-false",
        "stem": "Julgue as afirmações sobre a fauna brasileira.",
        "choices": [
            {
                "id": "onca",
                "text": "A onça-pintada é o maior felino das Américas.",
                "correct": True,
                "marker": "T",
            },
            {
                "id": "capivara",
                "text": "A capivara é o maior roedor do mundo.",
                "correct": True,
                "marker": "V",
            },
        ],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert "reserved-true-false-marker" not in _codes(loaded.diagnostics)


# ---------------------------------------------------------------------
# blank-text-field (error form): preamble, epilogue, stem
# ---------------------------------------------------------------------


@pytest.mark.parametrize("field_name", ["preamble", "stem", "epilogue"])
def test_blank_intro_field_is_a_model_error(field_name: str) -> None:
    doc = {
        "type": "essay",
        "stem": "Descreva o processo de fotossíntese na Mata Atlântica.",
        "input": "text",
        field_name: "   \n\t  ",
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_one_error(loaded.diagnostics, _BLANK_INTRO_CODES)
    assert diagnostic.path == (field_name,)


@pytest.mark.parametrize("field_name", ["title", "author", "comment"])
def test_blank_text_field_on_metadata_fields_stays_a_warning(field_name: str) -> None:
    """
    base.md's "critical" rule only covers `preamble`/`epilogue`/`stem`;
    `title`/`author`/`comment`/`answerKey` keep the same code at
    `warning`, per the spec's `blank-text-field` split.
    """
    doc = {
        "type": "essay",
        "stem": "Descreva o processo de fotossíntese na Mata Atlântica.",
        "input": "text",
        field_name: "   \n\t  ",
    }
    loaded = load(doc)
    assert loaded.document is not None
    matching = [d for d in loaded.diagnostics if d.code == "blank-text-field"]
    assert len(matching) == 1
    assert matching[0].severity == "warning"
    assert matching[0].path == (field_name,)


def test_blank_answer_key_stays_a_warning() -> None:
    doc = {
        "type": "essay",
        "stem": "Descreva o processo de fotossíntese na Mata Atlântica.",
        "input": "text",
        "answerKey": "   ",
    }
    loaded = load(doc)
    assert loaded.document is not None
    matching = [d for d in loaded.diagnostics if d.code == "blank-text-field"]
    assert len(matching) == 1
    assert matching[0].severity == "warning"
    assert matching[0].path == ("answerKey",)


def test_non_blank_intro_fields_do_not_error() -> None:
    doc = {
        "type": "essay",
        "stem": "Descreva o processo de fotossíntese na Mata Atlântica.",
        "preamble": "Considere um ambiente de luz solar plena.",
        "epilogue": "Seja objetivo.",
        "input": "text",
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert not _errors(loaded.diagnostics)


# ---------------------------------------------------------------------
# accept-reject-overlap (replaces the plain `value_error` today)
# ---------------------------------------------------------------------


def test_ordering_accept_reject_overlap_is_a_model_error() -> None:
    doc = {
        "type": "ordering",
        "stem": "Ordene as linhas do algoritmo de Euclides para o MDC.",
        "lines": [[0, "a, b = b, a % b"], [0, "return a"]],
        "accept": [{"lines": [[0, "a, b = b, a % b"], [0, "return a"]]}],
        "reject": [{"lines": [[0, "a, b = b, a % b"], [0, "return a"]]}],
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_one_error(loaded.diagnostics, "accept-reject-overlap")
    # The old `value_error` had no field to point at either; interpreted
    # here as the document root, same as a plain `ValueError` raised from
    # a whole-model `@model_validator(mode="after")` reports today (see
    # tests/test_loading.py::test_pydantic_only_rule_ordering_overlap_is_reported_as_an_error,
    # which currently asserts `code == "value_error"` at the same path
    # and is expected to be updated by the implementer per this spec).
    assert diagnostic.path == ()


def test_ordering_disjoint_accept_and_reject_does_not_error() -> None:
    doc = {
        "type": "ordering",
        "stem": "Ordene as linhas do algoritmo de Euclides para o MDC.",
        "lines": [[0, "a, b = b, a % b"], [0, "return a"]],
        "accept": [{"lines": [[0, "return a"], [0, "a, b = b, a % b"]]}],
        "reject": [{"lines": [[0, "a = b"], [0, "return b"]]}],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert "accept-reject-overlap" not in _codes(loaded.diagnostics)
