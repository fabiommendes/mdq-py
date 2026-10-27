"""
`blank-text` (docs/lint-codes.md, "Errors"): a free-text field, or a
`tags` entry, that is defined but empty or whitespace only. The cases per
field and per source format live in the corpus
(`examples/invalid/**/*blank*`, `*empty*`, including a `.json` source);
this module keeps only what the corpus cannot express: the models.

Written against the models.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mdq import models


#
# The check is on the models too, not only on `load`
#
def test_building_a_model_with_a_blank_field_raises() -> None:
    with pytest.raises(ValidationError) as excinfo:
        models.EssayQuestion(stem="Explique.", title="")
    assert [e["type"] for e in excinfo.value.errors()] == ["blank-text"]
