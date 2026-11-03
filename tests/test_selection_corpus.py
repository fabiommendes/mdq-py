"""
`select_seeded` (docs/exam.md, "Seeded selection"): the cases of
`examples/selection.yaml`, whose header describes the format, and the
seeded selection through `Exam.resolve`.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
import yaml

from mdq import load
from mdq._banks import DictLoader
from mdq.models import select_seeded
from _corpus import EXAMPLES_ROOT

CORPUS: dict[str, Any] = yaml.safe_load(
    (EXAMPLES_ROOT / "selection.yaml").read_text(encoding="utf-8")
)
CASES: list[dict[str, Any]] = CORPUS["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_selection_case(case: dict[str, Any]) -> None:
    select = select_seeded(case["seed"])
    assert select(case["candidates"], case.get("max")) == case["selected"]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_selection_digests(case: dict[str, Any]) -> None:
    for candidate, expected in case["digests"].items():
        data = f"{case['seed']}\0{candidate}".encode()
        assert hashlib.sha256(data).hexdigest() == expected


@pytest.mark.parametrize("seed", CORPUS["rejectedSeeds"])
def test_rejected_seed(seed: str) -> None:
    with pytest.raises(ValueError):
        select_seeded(seed)


def test_resolve_with_a_seed_gives_the_same_exam() -> None:
    case = CASES[0]
    bank = DictLoader(
        {
            id: {"type": "essay", "stem": f"Bioma {id}.", "tags": ["biome"]}
            for id in case["candidates"]
        }
    )
    source = f"# [ex] Biomas\n\n---\nincludeAll: biome\nmax: {case['max']}\n---\n"
    exam = load(source).validate()
    for _ in range(3):
        resolved = exam.resolve(bank, select=select_seeded(case["seed"]))
        assert [question.id for question in resolved.questions] == case["selected"]
