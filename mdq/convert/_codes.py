"""
The codes of the problems a converter reports, each with one severity.

Today every problem stops the conversion, so every code is an error. A
code keeps its name when its severity changes: the name describes what the
converter does, or will do, with the data it cannot keep.
"""

from __future__ import annotations

from .._diagnostics import Diagnostic, Severity
from ..errors import ConversionError

#: Every code a converter reports, with its severity.
CONVERTER_CODES: dict[str, Severity] = {
    # Export: MDQ to the format.
    "score-rounded": "error",
    "inexact-answer": "error",
    "manual-grading-dropped": "error",
    "regex-dropped": "error",
    "no-accept": "error",
    "general-feedback-dropped": "error",
    "unsupported-type": "error",
    "too-many-choices": "error",
    "multiple-blanks": "error",
    "blank-marker-mismatch": "error",
    "blank-line-after-blank": "error",
    "no-full-credit": "error",
    "cloze-text-changed": "error",
    # Import: the format to MDQ.
    "partial-credit-dropped": "error",
    "wildcard-to-regex": "error",
    "answer-dropped": "error",
    "multiple-questions": "error",
    "no-question": "error",
    "missing-word-boolean": "error",
    "missing-word-joined": "error",
    "blank-in-html-block": "error",
    "syntax-error": "error",
    "not-a-number": "error",
    "invalid-question": "error",
    "unsupported-cloze-kind": "error",
}


def conversion_error(code: str, message: str) -> ConversionError:
    """The error to raise for a problem `code` that stops the conversion."""
    severity = CONVERTER_CODES[code]
    assert severity == "error", f"{code!r} is not an error"
    return ConversionError([Diagnostic(severity=severity, code=code, message=message)])
