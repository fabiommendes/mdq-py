"""
Rendering a short answer question keeps `preAccept` and `preReject`
(docs/question-types/short-answer.md, frontmatter table). Both fields are
frontmatter-only: there is no body block for them.
"""

from __future__ import annotations

from typing import Any

import pytest
from _corpus import VALID_DIR

import mdq
from mdq import models

PATTERNS: list[Any] = [
    pytest.param("/\\d{4}/", id="regex"),
    pytest.param(
        {"pattern": "/\\d{4}/", "feedback": "Write only the year."}, id="feedback"
    ),
    pytest.param(
        {"pattern": "Rio Negro", "comment": "Both rivers meet at Manaus."}, id="comment"
    ),
    pytest.param("`Manaus`", id="backtick-literal"),
    pytest.param("*", id="asterisk-literal"),
    pytest.param("Amazonas: o maior estado", id="colon-space"),
    pytest.param("Cerrado # bioma", id="hash"),
    pytest.param("*Pantanal", id="leading-star"),
    pytest.param("/\\d{4}\\s*(?:AD|CE)/i", id="backslashes"),
]


def _question(**fields: Any) -> models.ShortAnswerQuestion:
    return models.ShortAnswerQuestion(
        stem="Em que ano o Brasil declarou a independência?", accept=["1822"], **fields
    )


def _roundtrip(question: models.ShortAnswerQuestion) -> Any:
    loaded = mdq.load(str(question), kind="question")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    return loaded.document


def _body(text: str) -> str:
    """The text after the YAML frontmatter and its blank line, if there is one."""
    if text.startswith("---\n"):
        return text.split("\n---\n", 1)[1].removeprefix("\n")
    return text


@pytest.mark.parametrize("field", ["pre_accept", "pre_reject"])
@pytest.mark.parametrize("entry", PATTERNS)
def test_entry_forms_survive_the_round_trip(field: str, entry: Any) -> None:
    question = mdq.load(
        {
            "type": "short-answer",
            "stem": "Em que ano o Brasil declarou a independência?",
            "accept": ["1822"],
            ("preAccept" if field == "pre_accept" else "preReject"): [entry],
        },
        kind="question",
    ).document
    assert _roundtrip(question) == question


@pytest.mark.parametrize(
    ("key", "field"), [("preAccept", "pre_accept"), ("preReject", "pre_reject")]
)
def test_set_field_is_written_to_the_frontmatter(key: str, field: str) -> None:
    question = _question(**{field: ["/\\d{4}/"]})
    text = str(question)
    assert text.startswith("---\n")
    assert key in text.split("\n---\n", 1)[0]
    assert key in question.frontmatter()


def test_unset_fields_are_omitted() -> None:
    text = str(_question())
    assert "preAccept" not in text
    assert "preReject" not in text
    assert "preAccept" not in _question().frontmatter()
    assert "preReject" not in _question().frontmatter()


def test_only_the_set_field_is_written() -> None:
    text = str(_question(pre_reject=["/\\d{4}\\s*CE/i"]))
    assert "preReject" in text
    assert "preAccept" not in text


def test_both_fields_round_trip_together() -> None:
    question = _question(
        pre_accept=["/\\d{4}/"],
        pre_reject=[
            {"pattern": "/\\d{4}\\s*(?:AD|CE)/i", "feedback": "Write only the year."}
        ],
    )
    assert _roundtrip(question) == question


def test_corpus_pre_validation_example_round_trips() -> None:
    path = VALID_DIR / "short-answer" / "pre-validation.yaml"
    original = mdq.load(path, kind="question").document
    assert _roundtrip(original) == original


def test_pre_validation_fields_do_not_change_the_body() -> None:
    plain = _question()
    extended = _question(pre_accept=["/\\d{4}/"], pre_reject=["/\\d{4}\\s*CE/i"])
    assert _body(str(extended)) == _body(str(plain))
