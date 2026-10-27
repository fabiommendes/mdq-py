"""
base.md, "Frontmatter": a `null` value in any OPTIONAL field is the same
as an absent field, including nested objects such as choices and blanks.
The corpus covers the absence (`examples/normalize.yaml`, question
frontmatter in `null-fields`, `null-content-and-optionals`,
`null-diacritics`). What is left here is the default value a null exam
field takes.
"""

from __future__ import annotations

from typing import Any

import pytest

import mdq

MC_BODY = "Qual?\n\n* [*] [a] Bahia\n* [ ] [b] Maranhão\n"


def _errors(loaded: mdq.Loaded) -> list[str]:
    return [d.code for d in loaded.diagnostics if d.severity == "error"]


#
# Exam fields with a default
#
@pytest.mark.parametrize(
    ("line", "field", "value"),
    [
        ("grading: null", "grading", "symmetric"),
        ("penalty:", "penalty", "none"),
        ("shuffle: null", "shuffle", False),
    ],
)
def test_null_exam_field_takes_its_default(line: str, field: str, value: Any) -> None:
    source = f"---\n{line}\n---\n\n# Prova\n\n## Q1\n\n{MC_BODY}"
    loaded = mdq.load(source, kind="exam")
    assert _errors(loaded) == []
    assert getattr(loaded.document, field) == value
