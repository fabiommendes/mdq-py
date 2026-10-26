"""
Tests for `dev/specs/to-do/unique-ids.md`.

The four rules -- `duplicate-choice-id`, `duplicate-choice-text`,
`duplicate-blank-id`, `duplicate-question-id` -- are model validators:
`load` reports them as `error` diagnostics, with `document=None`. The
corpus holds the cases (`examples/invalid/model-only/*duplicate*`,
`examples/invalid/exam-duplicate-question-id.mdq.md`); this module keeps
the duplicates inside the choices of a fill-in choice blank.

Written against the public `mdq.load` API only -- no parser/linter internals.
"""

from __future__ import annotations

from mdq import Diagnostic, load


def _codes(diagnostics: list[Diagnostic]) -> set[str]:
    return {d.code for d in diagnostics}


def _assert_is_error(diagnostics: list[Diagnostic], code: str) -> Diagnostic:
    """The first diagnostic with `code`, asserted to be an `error`."""
    matching = [d for d in diagnostics if d.code == code]
    assert len(matching) >= 1, f"expected a {code!r} diagnostic, got {_codes(diagnostics)}"
    diagnostic = matching[0]
    assert diagnostic.severity == "error"
    return diagnostic


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
