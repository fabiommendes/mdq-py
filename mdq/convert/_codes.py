"""
The codes of the problems a converter reports, each with one severity.

A code has one severity. An error stops the conversion: there is no result.
A warning means the target format cannot hold something and the converter did
its best. Info is metadata that does not change what the student sees or how
the response is graded. These codes are not rules of the MDQ specification:
`docs/lint-codes.md` does not list them.
"""

from __future__ import annotations

from .._diagnostics import Severity

#: Every code a converter reports, with its severity.
CONVERTER_CODES: dict[str, Severity] = {
    # Export: MDQ to the format.
    "score-rounded": "warning",
    "inexact-answer": "warning",
    "manual-grading-dropped": "warning",
    "regex-dropped": "warning",
    "no-accept": "error",
    "general-feedback-dropped": "warning",
    "unsupported-type": "error",
    "too-many-choices": "error",
    "multiple-blanks": "error",
    "blank-marker-mismatch": "error",
    "no-full-credit": "error",
    "cloze-text-changed": "warning",
    "invalid-xml-character": "error",
    "grading-changed": "warning",
    "diacritics-not-folded": "warning",
    "line-breaks-dropped": "warning",
    "indentation-lost": "warning",
    "field-dropped": "warning",
    "metadata-dropped": "info",
    # Export and import.
    "partial-credit-dropped": "warning",
    "answer-dropped": "warning",
    # Import: the format to MDQ.
    "wildcard-to-regex": "warning",
    "feedback-dropped": "warning",
    "multiple-questions": "error",
    "no-question": "error",
    "missing-word-joined": "warning",
    "blank-in-html-block": "error",
    "syntax-error": "error",
    "not-a-number": "error",
    "invalid-question": "error",
    "unsupported-cloze-kind": "error",
    "case-sensitivity-dropped": "warning",
    "blank-weight-dropped": "warning",
    "unit-changed": "warning",
    "embedded-file-dropped": "warning",
    "gift-blank-line": "warning",
}
