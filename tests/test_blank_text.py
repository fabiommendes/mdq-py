"""
`blank-text` (docs/lint-codes.md, "Errors"): a free-text field, or a
`tags` entry, that is defined but empty or whitespace only. The cases per
field live in the corpus (`examples/invalid/**/*blank*`, `*empty*`); this
module keeps only what the corpus cannot express: the models and the JSON
source.

Written against the public `mdq.load` API and the models.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

import mdq
from mdq import Diagnostic, models


def _errors(doc: Any, **kwargs: Any) -> list[Diagnostic]:
    loaded = mdq.load(doc, **kwargs)
    assert loaded.document is None
    return [d for d in loaded.diagnostics if d.severity == "error"]


def _assert_blank_text(doc: Any, path: tuple[str | int, ...], **kwargs: Any) -> None:
    errors = _errors(doc, **kwargs)
    assert [(d.code, d.path) for d in errors] == [("blank-text", path)]


#
# The check is on the models too, not only on `load`
#
def test_building_a_model_with_a_blank_field_raises() -> None:
    with pytest.raises(ValidationError) as excinfo:
        models.EssayQuestion(stem="Explique.", title="")
    assert [e["type"] for e in excinfo.value.errors()] == ["blank-text"]


def test_json_source_is_checked() -> None:
    _assert_blank_text(
        '{"type": "essay", "stem": "Explique.", "answerKey": "  "}',
        ("answerKey",),
        format="json",
    )
