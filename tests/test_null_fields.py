"""
base.md, "Frontmatter": a `null` value in any OPTIONAL field is the same
as an absent field, including nested objects such as choices and blanks.
The corpus covers question frontmatter (`null-fields`,
`null-content-and-optionals`, `null-diacritics`); the JSON schema forbids
`null`, so nested objects and exam fields are tested here.
"""

from __future__ import annotations

from typing import Any

import pytest

import mdq

MC_BODY = "Qual?\n\n* [*] [a] Bahia\n* [ ] [b] Maranhão\n"


def _errors(loaded: mdq.Loaded) -> list[str]:
    return [d.code for d in loaded.diagnostics if d.severity == "error"]


def _mc_md(frontmatter: str) -> mdq.Loaded:
    return mdq.load(f"---\n{frontmatter}\n---\n\n{MC_BODY}", kind="question")


#
# Nested objects in a dict (the JSON schema forbids `null` in the corpus)
#
def test_null_in_a_nested_choice_is_absent() -> None:
    loaded = mdq.load(
        {
            "type": "multiple-choice",
            "stem": "Qual?",
            "choices": [
                {"text": "a", "score": 1, "feedback": None, "id": None},
                {"text": "b", "score": None, "comment": None},
            ],
        },
        kind="question",
    )
    assert _errors(loaded) == []
    first, second = loaded.document.choices
    assert first.feedback is None and first.id is None
    assert second.score is None and second.comment is None


def test_null_in_a_nested_blank_is_absent() -> None:
    loaded = mdq.load(
        {
            "type": "fill-in",
            "stem": "Quanto [^x]?",
            "blanks": [{"id": "x", "type": "numeric", "answer": 42, "tolerance": None}],
        },
        kind="question",
    )
    assert _errors(loaded) == []
    assert loaded.document.blanks[0].tolerance is None


#
# AC3: exam fields, including the ones the parser converts
#
@pytest.mark.parametrize(
    ("line", "field", "value"),
    [
        ("duration:", "duration", None),
        ("start: ~", "start", None),
        ("grading: null", "grading", "symmetric"),
        ("penalty:", "penalty", "none"),
        ("shuffle: null", "shuffle", False),
        ("author:", "author", None),
        ("course: ~", "course", None),
    ],
)
def test_null_exam_field_is_absent(line: str, field: str, value: Any) -> None:
    source = f"---\n{line}\n---\n\n# Prova\n\n## Q1\n\n{MC_BODY}"
    loaded = mdq.load(source, kind="exam")
    assert _errors(loaded) == []
    assert getattr(loaded.document, field) == value
