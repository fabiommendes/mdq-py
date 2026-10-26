"""
`correct` is required on multiple-selection choices and true/false
statements (multiple-selection.md "Choices", true-false.md "Choices"):
the corpus covers the blank `[ ]` reading as `correct: false` and the
document that leaves the field out; this module covers the dump.
"""

from mdq.models import BooleanChoice


def test_false_verdict_survives_a_dump() -> None:
    choice = BooleanChoice(text="Lisbon", correct=False)
    assert choice.model_dump(exclude_defaults=True, exclude_none=True) == {
        "text": "Lisbon",
        "correct": False,
    }
