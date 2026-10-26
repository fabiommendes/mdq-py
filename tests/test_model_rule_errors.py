"""
Model-level rules that `load` reports as errors (invalid regex, undefined
or unreferenced blanks, malformed locale, blank text, accept/reject
overlap, malformed numeric answer, schema length limits) are pinned by
the invalid examples in `examples/invalid/` and `examples/invalid/model-only/`.
Only the well-formed counterparts that the corpus does not repeat live here.
"""

from __future__ import annotations

import pytest

from mdq import load


@pytest.mark.parametrize("answer", ["42", "0"])
def test_well_formed_numeric_answer_does_not_error(answer: str) -> None:
    doc = {
        "type": "numeric",
        "stem": "Que fração do território do Brasil fica no bioma Amazônia?",
        "answer": answer,
    }
    loaded = load(doc)
    assert loaded.document is not None
    assert "malformed-numeric-answer" not in {d.code for d in loaded.diagnostics}
