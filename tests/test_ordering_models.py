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


def alternatives(
    tag: str, within: list[OrderingLine] | None = None
) -> st.SearchStrategy[list[OrderingAlternative]]:
    """
    Alternatives with their own tagged lines or, given `within`, a
    non-empty sub-multiset of it (an `accept` entry may only leave
    lines of the answer key out).
    """
    if within is None:
        alt_lines = lines(tag)
    else:
        alt_lines = st.permutations(within).flatmap(
            lambda perm: st.integers(1, len(perm)).map(lambda n: list(perm[:n]))
        )
    alternative = st.builds(
        OrderingAlternative,
        lines=alt_lines,
        feedback=st.none() | st.text(alphabet="abcde", min_size=1, max_size=8),
        comment=st.none() | st.text(alphabet="abcde", min_size=1, max_size=8),
    )
    # An explicit empty list breaks the schema (`minItems: 1`); omit it instead.
    return st.lists(alternative, min_size=1, max_size=2)


@st.composite
def ordering_questions(draw: st.DrawFn) -> OrderingQuestion:
    main = draw(lines("main", min_size=2))
    # An explicit empty `extra` breaks the schema (`minItems: 1`); omit it.
    extra = draw(lines("extra", max_size=3) | st.none())
    optional = {} if extra is None else {"extra": extra}
    return draw(
        st.builds(
            OrderingQuestion,
            # Plain prose: a blank stem or one that starts a forbidden
            # block (an H1, say) is a model error, not what this tests.
            stem=st.from_regex(r"[A-Za-z][A-Za-z ]{0,9}", fullmatch=True),
            # Levels are arbitrary: `content: text` would require an outline.
            content=st.just("code"),
            lines=st.just(main),
            accept=alternatives("accept", within=main),
            reject=alternatives("reject"),
            indentation=st.sampled_from(INDENTATIONS),
            normalizations=st.lists(
                st.sampled_from(NORMALIZATIONS), unique=True, max_size=2
            ),
            **{k: st.just(v) for k, v in optional.items()},
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
MINIMAL = OrderingQuestion(content="text", stem="Order me", lines=[(0, "a"), (0, "b")])


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("indentation", "fixed"),
        ("unmatched", "incorrect"),
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
        "content": "text",
        "stem": "Order me",
        "lines": [(0, "a"), (0, "b")],
    }


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
