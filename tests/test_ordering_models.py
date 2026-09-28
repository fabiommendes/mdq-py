"""
`OrderingQuestion`/`OrderingAlternative`: construction, defaults,
`to_dict()` and `effective_normalizations()`.

Local hypothesis strategies build lines/alternatives/questions directly --
this does not touch `mdq.hypothesis.documents`, which has no ordering
support yet. Accept/reject lines are tagged with a section-specific suffix
so generated questions never trip the accept/reject-disjoint rule by
accident; that collision is instead tested explicitly with a hand-built
fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from mdq.models import (
    OrderingAlternative,
    OrderingLine,
    OrderingQuestion,
    QuestionRoot,
)
from mdq.types import Indentation, Normalization
from _corpus import VALID_DIR, collect_files, relative_id

ORDERING_DIR = VALID_DIR / "ordering"
ORDERING_FIXTURES = collect_files(ORDERING_DIR)

NORMALIZATIONS: list[Normalization] = ["dedent", "skip-blanks"]
INDENTATIONS: list[Indentation] = ["fixed", "lenient", "strict"]


def lines(
    tag: str, min_size: int = 1, max_size: int = 4
) -> st.SearchStrategy[list[OrderingLine]]:
    """Lines whose text is tagged, so lines from different tags never collide."""
    text = st.text(alphabet="abcde", min_size=1, max_size=4).map(lambda s: f"{tag}-{s}")
    line = st.tuples(st.integers(min_value=0, max_value=4), text)
    return st.lists(line, min_size=min_size, max_size=max_size)


def alternatives(tag: str) -> st.SearchStrategy[list[OrderingAlternative]]:
    alternative = st.builds(
        OrderingAlternative,
        lines=lines(tag),
        feedback=st.none() | st.text(min_size=1, max_size=8),
        comment=st.none() | st.text(min_size=1, max_size=8),
    )
    return st.lists(alternative, max_size=2)


@st.composite
def ordering_questions(draw: st.DrawFn) -> OrderingQuestion:
    return draw(
        st.builds(
            OrderingQuestion,
            # Plain prose: a blank stem or one that starts a forbidden
            # block (an H1, say) is a model error, not what this tests.
            stem=st.from_regex(r"[A-Za-z][A-Za-z ]{0,9}", fullmatch=True),
            lines=lines("main", min_size=2),
            extra=lines("extra", min_size=0, max_size=3),
            accept=alternatives("accept"),
            reject=alternatives("reject"),
            indentation=st.sampled_from(INDENTATIONS),
            normalizations=st.lists(
                st.sampled_from(NORMALIZATIONS), unique=True, max_size=2
            ),
        )
    )


#
# Properties
#
@given(ordering_questions())
def test_round_trip_through_to_dict_is_identity(question: OrderingQuestion) -> None:
    rebuilt = QuestionRoot.model_validate(question.to_dict()).root
    assert rebuilt == question


@given(ordering_questions())
def test_effective_normalizations_equals_declared_plus_lenient_dedent(
    question: OrderingQuestion,
) -> None:
    expected = set(question.normalizations)
    if question.indentation == "lenient":
        expected.add("dedent")
    assert question.effective_normalizations() == expected


#
# Defaults and to_dict() omissions
#
MINIMAL = OrderingQuestion(stem="Order me", lines=[(0, "a"), (0, "b")])


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("content", "text"),
        ("indentation", "fixed"),
        ("unmatched", "manual"),
        ("extra", []),
        ("accept", []),
        ("reject", []),
        ("normalizations", []),
        ("highlight", None),
    ],
)
def test_defaults(field: str, expected: object) -> None:
    assert getattr(MINIMAL, field) == expected


def test_minimal_to_dict_omits_every_default_but_the_discriminator() -> None:
    assert MINIMAL.to_dict() == {
        "type": "ordering",
        "stem": "Order me",
        "lines": [(0, "a"), (0, "b")],
    }


def test_empty_accept_is_allowed_and_dropped_by_to_dict() -> None:
    question = OrderingQuestion(stem="s", lines=[(0, "a"), (0, "b")], accept=[])
    assert question.accept == []
    assert "accept" not in question.to_dict()


#
# Fixtures
#
def test_ordering_fixtures_exist() -> None:
    assert ORDERING_FIXTURES, f"no ordering fixtures found under {ORDERING_DIR}"


@pytest.mark.parametrize(
    "path", ORDERING_FIXTURES, ids=[relative_id(p) for p in ORDERING_FIXTURES]
)
def test_fixture_round_trips_through_the_model(path: Path) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    question = QuestionRoot.model_validate(document).root
    assert isinstance(question, OrderingQuestion)

    rebuilt = QuestionRoot.model_validate(question.to_dict()).root
    assert rebuilt == question


#
# Edge cases
#
def test_single_line_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OrderingQuestion(stem="s", lines=[(0, "a")])


def test_negative_indentation_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OrderingQuestion(stem="s", lines=[(-1, "a"), (0, "b")])


def test_three_element_line_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OrderingQuestion.model_validate(
            {"stem": "s", "lines": [[0, "a", "x"], [0, "b"]]}
        )


def test_same_lines_in_accept_and_reject_is_rejected() -> None:
    shared = [(0, "a"), (0, "b")]
    with pytest.raises(ValidationError):
        OrderingQuestion(
            stem="s",
            lines=[(0, "x"), (0, "y")],
            accept=[OrderingAlternative(lines=shared)],
            reject=[OrderingAlternative(lines=shared)],
        )


def test_same_lines_repeated_across_two_accept_entries_is_allowed() -> None:
    shared = [(0, "a"), (0, "b")]
    question = OrderingQuestion(
        stem="s",
        lines=[(0, "x"), (0, "y")],
        accept=[OrderingAlternative(lines=shared), OrderingAlternative(lines=shared)],
    )
    assert len(question.accept) == 2
