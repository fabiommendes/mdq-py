"""
Diagnostic paths from pydantic errors.

Regressions from the review of `dev/specs/to-do/lint-on-models.md`:
pydantic adds the `type` tag of a discriminated union member to an
error's `loc`. `load` removes that tag. The path of a blank inside a
fill-in question is not in the corpus.
"""

from __future__ import annotations

from mdq import load


def test_blank_error_path_has_no_blank_type_tag() -> None:
    loaded = load(
        {
            "type": "fill-in",
            "stem": "A capital do Brasil é [^capital].",
            "blanks": [
                {
                    "id": "capital",
                    "type": "multiple-choice",
                    "choices": [
                        {"id": "a", "text": "Brasília", "score": 1},
                        {"id": "a", "text": "Salvador", "score": 0},
                    ],
                }
            ],
        },
        kind="question",
    )
    assert loaded.document is None
    paths = [d.path for d in loaded.diagnostics if d.code == "duplicate-choice-id"]
    assert paths == [("blanks", 0, "choices", 1, "id")]
