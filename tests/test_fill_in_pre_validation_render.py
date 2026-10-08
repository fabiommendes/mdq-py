"""
Rendering a fill-in question keeps the `preAccept` and `preReject` lists of
its short answer blanks (docs/question-types/fill-in.md "Frontmatter" [^7]).
In Markdown they are frontmatter maps from blank id to pattern list; the
serialization of each entry is the one of a short answer question.
"""

from __future__ import annotations

from typing import Any

import pytest

import mdq
from mdq import models

FEEDBACK: dict[str, str] = {"pattern": "/\\d+/", "feedback": "Write the name."}
COMMENT: dict[str, str] = {"pattern": "Rio Negro", "comment": "Meets the Solimões."}

ENTRIES: list[Any] = [
    pytest.param("Mato Grosso", id="plain-string"),
    pytest.param("/^[A-Za-z ]+$/i", id="regex-with-flags"),
    pytest.param("`Mato Grosso`", id="backtick-literal"),
    pytest.param(FEEDBACK, id="mapping-with-feedback"),
    pytest.param(COMMENT, id="mapping-with-comment"),
]

STEM = "The Pantanal lies in [^state] and floods in the [^season] season."


def _blank(blank_id: str, **fields: Any) -> dict[str, Any]:
    return {"id": blank_id, "type": "short-answer", "accept": ["rainy"], **fields}


def _question(blanks: list[dict[str, Any]], stem: str = STEM) -> Any:
    loaded = mdq.load(
        {"type": "fill-in", "stem": stem, "blanks": blanks}, kind="question"
    )
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    return loaded.document


def _roundtrip(question: Any) -> Any:
    loaded = mdq.load(str(question), kind="question")
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    return loaded.document


#
# AC4: frontmatter()
#
def test_frontmatter_maps_are_keyed_by_blank_id() -> None:
    question = _question(
        [
            _blank("state", preAccept=["/^[A-Za-z ]+$/"]),
            _blank("season", preReject=["/\\d+/m"]),
        ]
    )
    frontmatter = question.frontmatter()
    assert frontmatter["preAccept"] == {"state": ["/^[A-Za-z ]+$/"]}
    assert frontmatter["preReject"] == {"season": ["/\\d+/m"]}


def test_frontmatter_maps_follow_blank_order() -> None:
    question = _question(
        [
            _blank("season", preAccept=["/a/"]),
            _blank("state", preAccept=["/b/"]),
        ]
    )
    assert list(question.frontmatter()["preAccept"]) == ["season", "state"]


def test_frontmatter_skips_blanks_without_the_list() -> None:
    question = _question([_blank("state"), _blank("season", preAccept=["/a/"])])
    frontmatter = question.frontmatter()
    assert frontmatter["preAccept"] == {"season": ["/a/"]}
    assert "preReject" not in frontmatter


def test_frontmatter_has_neither_key_when_no_blank_has_the_lists() -> None:
    question = _question([_blank("state"), _blank("season")])
    frontmatter = question.frontmatter()
    assert "preAccept" not in frontmatter
    assert "preReject" not in frontmatter
    assert "preAccept" not in str(question)
    assert "preReject" not in str(question)


def test_frontmatter_has_neither_key_for_models_built_without_the_lists() -> None:
    question = models.FillInQuestion(
        stem=STEM,
        blanks=[
            models.ShortAnswerBlank(id="state", accept=["Mato Grosso"]),
            models.ShortAnswerBlank(id="season", accept=["rainy"]),
        ],
    )
    assert "preAccept" not in question.frontmatter()
    assert "preReject" not in question.frontmatter()


def test_frontmatter_from_models_keeps_lists_on_the_right_blank() -> None:
    question = models.FillInQuestion(
        stem=STEM,
        blanks=[
            models.ShortAnswerBlank(id="state", accept=["MT"], pre_accept=["/^\\w+$/"]),
            models.ShortAnswerBlank(
                id="season", accept=["rainy"], pre_reject=["/\\d/"]
            ),
        ],
    )
    frontmatter = question.frontmatter()
    assert frontmatter["preAccept"] == {"state": ["/^\\w+$/"]}
    assert frontmatter["preReject"] == {"season": ["/\\d/"]}


@pytest.mark.parametrize("key", ["preAccept", "preReject"])
@pytest.mark.parametrize("entry", ENTRIES)
def test_frontmatter_entries_keep_their_form(key: str, entry: Any) -> None:
    question = _question([_blank("state", **{key: [entry]}), _blank("season")])
    assert question.frontmatter()[key] == {"state": [entry]}


#
# AC5: render -> load fixed point
#
@pytest.mark.parametrize("key", ["preAccept", "preReject"])
@pytest.mark.parametrize("entry", ENTRIES)
def test_entry_forms_survive_the_round_trip(key: str, entry: Any) -> None:
    question = _question([_blank("state", **{key: [entry]}), _blank("season")])
    assert _roundtrip(question) == question


def test_all_entry_forms_in_one_list_survive_the_round_trip() -> None:
    entries = [p.values[0] for p in ENTRIES]
    question = _question([_blank("state", preAccept=entries), _blank("season")])
    assert _roundtrip(question) == question


def test_both_maps_on_one_blank_survive_the_round_trip() -> None:
    question = _question(
        [
            _blank("state", preAccept=["/^[A-Za-z ]+$/"], preReject=[FEEDBACK]),
            _blank("season"),
        ]
    )
    assert _roundtrip(question) == question


def test_maps_on_different_blanks_survive_the_round_trip() -> None:
    question = _question(
        [
            _blank("state", preAccept=["/^[A-Za-z ]+$/"]),
            _blank("season", preReject=[COMMENT, "`wet`"]),
        ]
    )
    assert _roundtrip(question) == question


def test_round_trip_with_numeric_and_choice_blanks() -> None:
    question = _question(
        [
            _blank("planet", preAccept=["/^[A-Za-z]+$/"], preReject=[FEEDBACK]),
            {"id": "moons", "type": "numeric", "answer": 95, "domain": "integer"},
            {
                "id": "feature",
                "type": "multiple-choice",
                "choices": [
                    # No score: whether `[ ]` reads back as 0 or as unset is
                    # a multiple-choice question, not this test's concern.
                    {"text": "mountain"},
                    {"text": "storm", "score": 1},
                ],
            },
        ],
        stem="The [^planet] has about [^moons] moons and a [^feature].",
    )
    assert _roundtrip(question) == question
