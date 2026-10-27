"""
`examples/normalize.yaml`: inputs the models accept and normalize (a nested
`null`, a YAML 1.1 form, a non-canonical duration), and, with
`normalize: true`, the result of `normalize()`. The header of the file
describes the format.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from mdq import load
from _corpus import EXAMPLES_ROOT

CASES: list[dict[str, Any]] = yaml.safe_load(
    (EXAMPLES_ROOT / "normalize.yaml").read_text(encoding="utf-8")
)["cases"]


def test_there_are_normalize_cases() -> None:
    assert CASES


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_load_normalizes_the_input(case: dict[str, Any]) -> None:
    kwargs: dict[str, Any] = {}
    if "kind" in case:
        kwargs["kind"] = case["kind"]
    if case.get("format") == "yaml":
        kwargs["format"] = "yaml"
    loaded = load(case["input"], **kwargs)
    assert [d for d in loaded.diagnostics if d.severity == "error"] == []
    assert loaded.document is not None
    document = loaded.document.normalize() if case.get("normalize") else loaded.document
    assert document.to_dict() == case["output"]
