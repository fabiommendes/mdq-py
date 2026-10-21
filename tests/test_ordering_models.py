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
    return draw(
        st.builds(
            OrderingQuestion,
            # Plain prose: a blank stem or one that starts a forbidden
            # block (an H1, say) is a model error, not what this tests.
            stem=st.from_regex(r"[A-Za-z][A-Za-z ]{0,9}", fullmatch=True),
            # Levels are arbitrary: `content: text` would require an outline.
            content=st.just("code"),
            lines=st.just(main),
            extra=lines("extra", min_size=0, max_size=3),
            accept=alternatives("accept", within=main),
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
MINIMAL = OrderingQuestion(content="text", stem="Order me", lines=[(0, "a"), (0, "b")])


@pytest.mark.parametrize(
    ("field", "expected"),
    [
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
        "content": "text",
        "stem": "Order me",
        "lines": [(0, "a"), (0, "b")],
    }


def test_empty_accept_is_rejected_like_the_schema_min_items() -> None:
    with pytest.raises(ValidationError):
        OrderingQuestion(
            content="text", stem="s", lines=[(0, "a"), (0, "b")], accept=[]
        )


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
        OrderingQuestion(content="text", stem="s", lines=[(0, "a")])


def test_negative_indentation_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OrderingQuestion(content="text", stem="s", lines=[(-1, "a"), (0, "b")])


def test_three_element_line_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OrderingQuestion.model_validate(
            {"stem": "s", "lines": [[0, "a", "x"], [0, "b"]]}
        )


def test_same_lines_in_accept_and_reject_is_rejected() -> None:
    shared = [(0, "a"), (0, "b")]
    with pytest.raises(ValidationError):
        OrderingQuestion(
            content="text",
            stem="s",
            lines=[(0, "x"), (0, "y")],
            accept=[OrderingAlternative(lines=shared)],
            reject=[OrderingAlternative(lines=shared)],
        )


def test_same_lines_repeated_across_two_accept_entries_is_allowed() -> None:
    shared = [(0, "x"), (0, "y")]
    question = OrderingQuestion(
        content="text",
        stem="s",
        lines=[(0, "x"), (0, "y"), (0, "z")],
        accept=[OrderingAlternative(lines=shared), OrderingAlternative(lines=shared)],
    )
    assert len(question.accept) == 2


#
# `content` and `highlight` (ordering.md#body, D19)
#
def test_content_is_required() -> None:
    with pytest.raises(ValidationError, match="content"):
        OrderingQuestion.model_validate({"stem": "s", "lines": [(0, "a"), (0, "b")]})


def test_highlight_with_text_content_is_rejected() -> None:
    with pytest.raises(ValidationError, match="highlight"):
        OrderingQuestion(
            content="text", highlight="python", stem="s", lines=[(0, "a"), (0, "b")]
        )


def test_empty_highlight_is_rejected() -> None:
    with pytest.raises(ValidationError, match="highlight"):
        OrderingQuestion(
            content="code", highlight="", stem="s", lines=[(0, "a"), (0, "b")]
        )


def test_code_content_without_highlight_is_valid_and_lints_clean() -> None:
    question = OrderingQuestion(content="code", stem="s", lines=[(0, "a"), (0, "b")])
    codes = {d.code for d in question.lint()}
    assert not codes & {"code-content-without-highlight", "ignored-highlight"}


#
# Outline levels with `content: text` (ordering.md, "Additional Rules")
#
def _text_doc(**fields: object) -> dict:
    return {
        "type": "ordering",
        "content": "text",
        "stem": "Order me",
        "lines": [[0, "a"], [1, "b"], [2, "c"]],
        **fields,
    }


@pytest.mark.parametrize(
    ("fields", "path"),
    [
        ({"lines": [[0, "a"], [2, "b"]]}, ("lines",)),
        ({"lines": [[1, "a"], [1, "b"]]}, ("lines",)),
        (
            {"accept": [{"lines": [[0, "a"], [2, "c"]]}]},
            ("accept", 0, "lines"),
        ),
        (
            {"reject": [{"lines": [[1, "a"]]}]},
            ("reject", 0, "lines"),
        ),
    ],
)
def test_text_blocks_must_be_outlines(fields: dict, path: tuple) -> None:
    from mdq import load

    loaded = load(_text_doc(**fields), kind="question")
    assert loaded.document is None
    assert [(d.code, d.path) for d in loaded.diagnostics if d.severity == "error"] == [
        ("invalid-outline-level", path)
    ]


def test_text_extra_and_code_blocks_may_jump() -> None:
    from mdq import load

    assert load(_text_doc(extra=[[3, "z"]]), kind="question").document is not None
    code = _text_doc(content="code", lines=[[0, "a"], [3, "b"]])
    assert load(code, kind="question").document is not None
