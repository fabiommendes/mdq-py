"""
Tests for `dev/specs/to-do/unique-ids.md`.

Four rules -- `duplicate-choice-id`, `duplicate-choice-text`,
`duplicate-blank-id`, `duplicate-question-id` -- move from lint warnings
to pydantic model validators: `load` must report them as `error`
diagnostics, with `document=None`, using the same codes and paths the
linter used to report as warnings.

The parser side of the spec requires derived choice ids to disambiguate
(`mdq.slugify.loose`) instead of colliding silently, and to never step on
an explicit id in the same question.

Fixtures use Brazil-themed questions and exams, per AGENTS.md. Written
against the public `mdq.load` API only -- no parser/linter internals.
"""

from __future__ import annotations

import pytest

from mdq import Diagnostic, load
from mdq.loaders import DictLoader
from mdq.models import MultipleChoiceQuestion

#: The four rules this spec promotes from lint warnings to model errors.
_UNIQUE_ID_CODES = frozenset(
    {
        "duplicate-choice-id",
        "duplicate-choice-text",
        "duplicate-blank-id",
        "duplicate-question-id",
    }
)


def _codes(diagnostics: list[Diagnostic]) -> set[str]:
    return {d.code for d in diagnostics}


def _matching(diagnostics: list[Diagnostic], code: str) -> list[Diagnostic]:
    return [d for d in diagnostics if d.code == code]


def _assert_is_error(diagnostics: list[Diagnostic], code: str) -> Diagnostic:
    """
    The one diagnostic with `code`, asserted to be an `error` -- never a
    `warning`, which is what the linter used to report before this spec.
    """
    matching = _matching(diagnostics, code)
    assert len(matching) >= 1, f"expected a {code!r} diagnostic, got {_codes(diagnostics)}"
    diagnostic = matching[0]
    assert diagnostic.severity == "error"
    return diagnostic


# ---------------------------------------------------------------------
# duplicate-choice-id
# ---------------------------------------------------------------------


def test_duplicate_choice_id_is_a_model_error() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"id": "same", "text": "Rio de Janeiro", "score": 0},
            {"id": "same", "text": "Brasília", "score": 1},
        ],
    }
    loaded = load(doc)
    assert loaded.document is None
    assert bool(loaded) is False
    diagnostic = _assert_is_error(loaded.diagnostics, "duplicate-choice-id")
    # Path points at the second (colliding) occurrence.
    assert diagnostic.path[-3:] == ("choices", 1, "id")


def test_unique_choice_ids_do_not_error() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"id": "rio", "text": "Rio de Janeiro", "score": 0},
            {"id": "brasilia", "text": "Brasília", "score": 1},
        ],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert "duplicate-choice-id" not in _codes(loaded.diagnostics)


# ---------------------------------------------------------------------
# duplicate-choice-text
# ---------------------------------------------------------------------


def test_duplicate_choice_text_is_a_model_error() -> None:
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"id": "a", "text": "Rio de Janeiro", "score": 0},
            {"id": "b", "text": "Rio de Janeiro", "score": 1},
        ],
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_is_error(loaded.diagnostics, "duplicate-choice-text")
    assert diagnostic.path[-3:] == ("choices", 1, "text")


def test_duplicate_choice_text_after_whitespace_normalization_is_a_model_error() -> None:
    """
    `duplicate-choice-text` compares texts the way the linter's
    `_visual_key` does: whitespace runs collapse outside code spans, so
    two texts that only differ in incidental whitespace still collide.
    """
    doc = {
        "type": "multiple-choice",
        "stem": "Qual é a capital do Brasil?",
        "choices": [
            {"id": "a", "text": "Rio   de Janeiro", "score": 0},
            {"id": "b", "text": "Rio de  Janeiro", "score": 1},
        ],
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_is_error(loaded.diagnostics, "duplicate-choice-text")
    assert diagnostic.path[-3:] == ("choices", 1, "text")


def test_choice_text_that_differs_only_inside_a_code_span_does_not_error() -> None:
    """
    The `_visual_key` normalization leaves code spans untouched, so two
    texts that only differ in whitespace *inside* a code span are not a
    collision -- they render differently.
    """
    doc = {
        "type": "multiple-choice",
        "stem": "Qual comando lista arquivos?",
        "choices": [
            {"id": "a", "text": "`ls  -la`", "score": 1},
            {"id": "b", "text": "`ls -la`", "score": 0},
        ],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert "duplicate-choice-text" not in _codes(loaded.diagnostics)


# ---------------------------------------------------------------------
# duplicate-blank-id
# ---------------------------------------------------------------------


def test_duplicate_blank_id_is_a_model_error() -> None:
    doc = {
        "type": "fill-in",
        "stem": "O maior planeta do sistema solar é [^planeta].",
        "blanks": [
            {"id": "planeta", "type": "short-answer", "one_of": ["Júpiter"]},
            {"id": "planeta", "type": "numeric", "answer": 95},
        ],
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_is_error(loaded.diagnostics, "duplicate-blank-id")
    assert diagnostic.path[-3:] == ("blanks", 1, "id")


def test_unique_blank_ids_do_not_error() -> None:
    doc = {
        "type": "fill-in",
        "stem": "O maior planeta do sistema solar é [^planeta], com [^luas] luas.",
        "blanks": [
            {"id": "planeta", "type": "short-answer", "one_of": ["Júpiter"]},
            {"id": "luas", "type": "numeric", "answer": 95},
        ],
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert "duplicate-blank-id" not in _codes(loaded.diagnostics)


# ---------------------------------------------------------------------
# duplicate-choice-id / duplicate-choice-text inside a fill-in choice blank
# ---------------------------------------------------------------------


def test_duplicate_choice_id_inside_a_fill_in_choice_blank_is_a_model_error() -> None:
    doc = {
        "type": "fill-in",
        "stem": "A capital do Brasil é [^capital].",
        "blanks": [
            {
                "id": "capital",
                "type": "multiple-choice",
                "choices": [
                    {"id": "same", "text": "Brasília", "score": 1},
                    {"id": "same", "text": "Rio de Janeiro", "score": 0},
                ],
            },
        ],
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_is_error(loaded.diagnostics, "duplicate-choice-id")
    assert diagnostic.path[-3:] == ("choices", 1, "id")


def test_duplicate_choice_text_inside_a_fill_in_choice_blank_is_a_model_error() -> None:
    doc = {
        "type": "fill-in",
        "stem": "A capital do Brasil é [^capital].",
        "blanks": [
            {
                "id": "capital",
                "type": "multiple-choice",
                "choices": [
                    {"id": "a", "text": "Brasília", "score": 1},
                    {"id": "b", "text": "Brasília", "score": 0},
                ],
            },
        ],
    }
    loaded = load(doc)
    assert loaded.document is None
    diagnostic = _assert_is_error(loaded.diagnostics, "duplicate-choice-text")
    assert diagnostic.path[-3:] == ("choices", 1, "text")


# ---------------------------------------------------------------------
# duplicate-question-id (exam)
# ---------------------------------------------------------------------

_INCLUDED_CAPITAL = {
    "id": "capital",
    "type": "essay",
    "stem": "Qual é a capital do Brasil?",
}


def test_two_inline_questions_with_the_same_id_is_a_model_error() -> None:
    text = (
        "# Prova de Geografia do Brasil\n"
        "\n"
        "Responda a todas as questões.\n"
        "\n"
        "---\n"
        "id: capital\n"
        "---\n"
        "\n"
        "Qual é a capital do Brasil?\n"
        "\n"
        "[essay]\n"
        "\n"
        "---\n"
        "id: capital\n"
        "---\n"
        "\n"
        "Onde fica a capital do Brasil?\n"
        "\n"
        "[essay]\n"
    )
    loaded = load(text, kind="exam")
    assert loaded.document is None
    diagnostic = _assert_is_error(loaded.diagnostics, "duplicate-question-id")
    assert diagnostic.path[-2:] == ("questions", 1)


def test_the_same_included_question_twice_is_a_model_error() -> None:
    text = (
        "# Prova de Geografia do Brasil\n"
        "\n"
        "Responda a todas as questões.\n"
        "\n"
        "---\n"
        "include: capital\n"
        "---\n"
        "\n"
        "---\n"
        "include: capital\n"
        "---\n"
    )
    loader = DictLoader({"capital": _INCLUDED_CAPITAL})
    loaded = load(text, kind="exam", loader=loader)
    assert loaded.document is None
    diagnostic = _assert_is_error(loaded.diagnostics, "duplicate-question-id")
    assert diagnostic.path[-2:] == ("questions", 1)


def test_an_inline_id_equal_to_an_included_questions_id_is_a_model_error() -> None:
    text = (
        "# Prova de Geografia do Brasil\n"
        "\n"
        "Responda a todas as questões.\n"
        "\n"
        "---\n"
        "include: capital\n"
        "---\n"
        "\n"
        "---\n"
        "id: capital\n"
        "---\n"
        "\n"
        "Onde fica a capital do Brasil?\n"
        "\n"
        "[essay]\n"
    )
    loader = DictLoader({"capital": _INCLUDED_CAPITAL})
    loaded = load(text, kind="exam", loader=loader)
    assert loaded.document is None
    diagnostic = _assert_is_error(loaded.diagnostics, "duplicate-question-id")
    assert diagnostic.path[-2:] == ("questions", 1)


def test_declared_id_colliding_with_the_next_implicit_id_is_a_model_error() -> None:
    """
    docs/exam.md, Question ids: a declared `id: q2` on block 1 makes the
    exam malformed, because block 2's implicit id (position-based, never
    renamed) is also `q2`.
    """
    text = (
        "# Prova de Geografia do Brasil\n"
        "\n"
        "Responda a todas as questões.\n"
        "\n"
        "---\n"
        "id: q2\n"
        "---\n"
        "\n"
        "Qual é a capital do Brasil?\n"
        "\n"
        "[essay]\n"
        "\n"
        "===\n"
        "\n"
        "Onde fica a Floresta Amazônica?\n"
        "\n"
        "* [ ] Ásia\n"
        "* [*] América do Sul\n"
    )
    loaded = load(text, kind="exam")
    assert loaded.document is None
    diagnostic = _assert_is_error(loaded.diagnostics, "duplicate-question-id")
    assert diagnostic.path[-2:] == ("questions", 1)


def test_unique_question_ids_do_not_error() -> None:
    text = (
        "# Prova de Geografia do Brasil\n"
        "\n"
        "Responda a todas as questões.\n"
        "\n"
        "---\n"
        "id: capital\n"
        "---\n"
        "\n"
        "Qual é a capital do Brasil?\n"
        "\n"
        "[essay]\n"
        "\n"
        "===\n"
        "\n"
        "Onde fica a Floresta Amazônica?\n"
        "\n"
        "* [ ] Ásia\n"
        "* [*] América do Sul\n"
    )
    loaded = load(text, kind="exam")
    assert loaded.document is not None
    assert "duplicate-question-id" not in _codes(loaded.diagnostics)


# ---------------------------------------------------------------------
# Parser disambiguation: derived choice ids never collide
# ---------------------------------------------------------------------


@pytest.mark.xfail(reason="parser does not disambiguate derived ids; see dev spec derived-ids.md", strict=True)
def test_brasilia_and_brasilia_ascii_get_different_derived_ids() -> None:
    """
    `Brasília` and `Brasilia` both fold to the same ASCII slug; the
    parser must disambiguate the two derived ids instead of colliding,
    and the document must load with no diagnostics at all.
    """
    text = (
        "Qual grafia consta no censo demográfico?\n"
        "\n"
        "* [ ] Brasília\n"
        "* [*] Brasilia\n"
        "* [ ] Nenhuma das anteriores\n"
    )
    loaded = load(text)
    assert loaded.document is not None
    assert loaded.diagnostics == []
    assert isinstance(loaded.document, MultipleChoiceQuestion)
    ids = [choice.id for choice in loaded.document.choices]
    assert len(ids) == len(set(ids)), f"derived ids collided: {ids}"


@pytest.mark.xfail(reason="parser does not disambiguate derived ids; see dev spec derived-ids.md", strict=True)
def test_sao_paulo_bang_and_question_mark_get_different_derived_ids() -> None:
    """
    `São Paulo!` and `São Paulo?` both slugify to `sao-paulo` once
    punctuation is stripped; the parser must disambiguate.
    """
    text = (
        "Qual pontuação está correta?\n"
        "\n"
        "* [ ] São Paulo!\n"
        "* [*] São Paulo?\n"
        "* [ ] Rio de Janeiro\n"
    )
    loaded = load(text)
    assert loaded.document is not None
    assert loaded.diagnostics == []
    assert isinstance(loaded.document, MultipleChoiceQuestion)
    ids = [choice.id for choice in loaded.document.choices]
    assert len(ids) == len(set(ids)), f"derived ids collided: {ids}"


@pytest.mark.xfail(reason="parser does not disambiguate derived ids; see dev spec derived-ids.md", strict=True)
def test_derived_id_never_takes_an_explicit_id_of_the_same_question() -> None:
    """
    Choice 2 declares the explicit id `brasilia`; choice 1 has no
    explicit id but its text (`Brasília`) would naturally derive to
    `brasilia` too. The derived id must avoid the explicit one.
    """
    text = (
        "Qual é a capital do Brasil?\n"
        "\n"
        "* [ ] Brasília\n"
        "* [*] [brasilia] Distrito Federal, sede do governo\n"
        "* [ ] São Paulo\n"
    )
    loaded = load(text)
    assert loaded.document is not None
    assert loaded.diagnostics == []
    assert isinstance(loaded.document, MultipleChoiceQuestion)
    derived_id, explicit_id = (choice.id for choice in loaded.document.choices[:2])
    assert explicit_id == "brasilia"
    assert derived_id != "brasilia"
    assert derived_id is not None


# ---------------------------------------------------------------------
# These four codes are errors now, never warnings
# ---------------------------------------------------------------------


def test_unique_id_codes_are_never_reported_as_warnings() -> None:
    """
    Every fixture above that produces one of the four codes must report
    it at `error` severity. This sweeps every diagnostic collected from
    those fixtures and checks none of the four ever shows up as a
    `warning` -- the severity the linter used to give them.
    """
    fixtures = [
        load(
            {
                "type": "multiple-choice",
                "stem": "Qual é a capital do Brasil?",
                "choices": [
                    {"id": "same", "text": "Rio de Janeiro", "score": 0},
                    {"id": "same", "text": "Brasília", "score": 1},
                ],
            }
        ),
        load(
            {
                "type": "multiple-choice",
                "stem": "Qual é a capital do Brasil?",
                "choices": [
                    {"id": "a", "text": "Rio de Janeiro", "score": 0},
                    {"id": "b", "text": "Rio de Janeiro", "score": 1},
                ],
            }
        ),
        load(
            {
                "type": "fill-in",
                "stem": "O maior planeta do sistema solar é [^planeta].",
                "blanks": [
                    {"id": "planeta", "type": "short-answer", "one_of": ["Júpiter"]},
                    {"id": "planeta", "type": "numeric", "answer": 95},
                ],
            }
        ),
    ]
    for loaded in fixtures:
        for diagnostic in loaded.diagnostics:
            if diagnostic.code in _UNIQUE_ID_CODES:
                assert diagnostic.severity != "warning", (
                    f"{diagnostic.code!r} reported as a warning: {diagnostic}"
                )
