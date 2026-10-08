"""
`correct` is required on multiple-selection choices and true/false
statements (multiple-selection.md "Choices", true-false.md "Choices"):
every choice states its verdict, so a blank `[ ]` reads as `correct: false`
and a document that leaves the field out does not load.
"""

import pytest
from pydantic import ValidationError

from mdq.models import BooleanChoice, Statement
from _parse import parse_any


def test_blank_multiple_selection_choice_is_explicitly_false() -> None:
    parsed = parse_any("Which are prime?\n\n* [x] 2\n* [ ] 4\n")
    assert [c["correct"] for c in parsed["choices"]] == [True, False]


@pytest.mark.parametrize("model", [BooleanChoice, Statement])
def test_correct_is_required(model: type) -> None:
    with pytest.raises(ValidationError):
        model(text="Earth is flat.")


def test_false_verdict_survives_a_dump() -> None:
    choice = BooleanChoice(text="Lisbon", correct=False)
    assert choice.model_dump(exclude_defaults=True, exclude_none=True) == {
        "text": "Lisbon",
        "correct": False,
    }
