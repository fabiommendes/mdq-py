"""
Test-only dispatch helpers mirroring the pre-restructure
`mdq._parser.parse_any`/`parse_file` -- not part of the package's public
surface (nothing in `mdq` needs the dict form outside a `Loaded`; see
`dev/refactor/mdq-py-restructure.md` phase 4), but plenty of tests still
want "parse this text/file and dispatch on exam vs. question" without
caring which.
"""

from __future__ import annotations

from pathlib import Path

from mdq._diagnostics import Diagnostic
from mdq._parser import is_exam, parse_exam, parse_question
from mdq.types import ExamDict, QuestionDict


def parse_any(
    text: str,
    *,
    warnings: list[Diagnostic] | None = None,
) -> QuestionDict | ExamDict:
    """Parse `text`, dispatching on whether it is an exam or a question."""

    if is_exam(text):
        return parse_exam(text, warnings=warnings)
    return parse_question(text, warnings=warnings)


def parse_file(path: Path) -> QuestionDict | ExamDict:
    """Parse the file at `path`, dispatching like `parse_any`."""

    path = Path(path)
    return parse_any(path.read_text(encoding="utf-8"))
