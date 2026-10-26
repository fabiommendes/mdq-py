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
