"""
`foreign-choice-marker`: the error class. The lint behavior is covered by the
`foreign-choice-marker` examples in `examples/invalid`.
"""

from __future__ import annotations

from mdq import errors


def test_foreign_choice_marker_error_has_code_and_path() -> None:
    error = errors.ForeignChoiceMarker("x", "multiple-choice", ("choices", 1))
    assert isinstance(error, errors.ParseError)
    assert error.code == "foreign-choice-marker"
    assert tuple(error.path) == ("choices", 1)


def test_message_shows_a_blank_marker_with_its_space() -> None:
    error = errors.ForeignChoiceMarker("", "true-false", ("choices", 1))
    assert str(error) == "[ ] is not a true-false choice marker"


def test_message_shows_the_marker_value() -> None:
    error = errors.ForeignChoiceMarker("x", "true-false", ("choices", 1))
    assert str(error) == "[x] is not a true-false choice marker"
