"""
Registry of the `warning`/`info` lint codes `lint()` reports, and the
one factory that builds their `Diagnostic`s.

The severity of a diagnostic is a function of its code
(`docs/lint-codes.md` tables it), so a check names the code only and
`SEVERITY` supplies the rest. A misspelled code is a type error.
`Diagnostic.code` itself stays a plain `str`: the public type also
carries parser and model error codes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from .._diagnostics import Diagnostic, Severity

LintCode = Literal[
    "accept-repeats-answer-key",
    "all-choices-correct",
    "answer-outside-domain",
    "blank-ordering-line",
    "case-variant-blank-id",
    "code-content-without-highlight",
    "domain-mismatch",
    "duplicate-alternative-lines",
    "empty-include-all",
    "exam-without-questions",
    "false-friend-true-false-marker",
    "ignored-decimal-places",
    "ignored-regex-flag",
    "locale-lookalike-language",
    "locale-mismatched-true-false-marker",
    "many-correct-choices",
    "missing-answer-key",
    "missing-choice-id",
    "missing-id",
    "missing-title",
    "missing-tolerance",
    "no-correct-answer",
    "no-correct-choice",
    "non-nfkc-true-false-marker",
    "nonstandard-include-query",
    "redundant-regex-anchor",
    "redundant-strict-indentation",
    "reject-without-feedback",
    "relative-tolerance-around-zero",
    "relative-tolerance-over-one",
    "setext-heading",
    "stray-choice-marker",
    "undeclared-id-after-include-all",
    "uniform-true-false-answers",
    "unknown-highlight-language",
    "unlisted-true-false-marker",
    "unmatchable-regex-escape",
    "unreachable-alternative",
    "unsafe-id",
    "unsafe-thematic-break",
    "unsplit-tag-list",
    "uuid-unknown-variant",
    "uuid-unknown-version",
    "visually-identical-choices",
    "visually-identical-lines",
]

SEVERITY: Mapping[LintCode, Severity] = {
    "accept-repeats-answer-key": "warning",
    "all-choices-correct": "info",
    "answer-outside-domain": "warning",
    "blank-ordering-line": "info",
    "case-variant-blank-id": "warning",
    "code-content-without-highlight": "info",
    "domain-mismatch": "info",
    "duplicate-alternative-lines": "warning",
    "empty-include-all": "warning",
    "exam-without-questions": "warning",
    "false-friend-true-false-marker": "warning",
    "ignored-decimal-places": "info",
    "ignored-regex-flag": "info",
    "locale-lookalike-language": "info",
    "locale-mismatched-true-false-marker": "warning",
    "many-correct-choices": "info",
    "missing-answer-key": "info",
    "missing-choice-id": "info",
    "missing-id": "info",
    "missing-title": "info",
    "missing-tolerance": "info",
    "no-correct-answer": "warning",
    "no-correct-choice": "info",
    "non-nfkc-true-false-marker": "info",
    "nonstandard-include-query": "warning",
    "redundant-regex-anchor": "info",
    "redundant-strict-indentation": "warning",
    "reject-without-feedback": "info",
    "relative-tolerance-around-zero": "warning",
    "relative-tolerance-over-one": "info",
    "setext-heading": "warning",
    "stray-choice-marker": "warning",
    "undeclared-id-after-include-all": "warning",
    "uniform-true-false-answers": "info",
    "unknown-highlight-language": "info",
    "unlisted-true-false-marker": "warning",
    "unmatchable-regex-escape": "info",
    "unreachable-alternative": "warning",
    "unsafe-id": "warning",
    "unsafe-thematic-break": "warning",
    "unsplit-tag-list": "warning",
    "uuid-unknown-variant": "warning",
    "uuid-unknown-version": "warning",
    "visually-identical-choices": "info",
    "visually-identical-lines": "info",
}


def diag(code: LintCode, path: tuple[str | int, ...], message: str) -> Diagnostic:
    """The `Diagnostic` of `code`, with the severity `SEVERITY` assigns it."""
    return Diagnostic(severity=SEVERITY[code], code=code, path=path, message=message)
