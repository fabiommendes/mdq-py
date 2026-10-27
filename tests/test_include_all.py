"""
`includeAll` blocks (docs/exam.md, "Include all"): the `select` API and the
bank index. The query language is in `examples/matching/query.yaml`; the
resolution of the documents is in `examples/valid/exam/*.resolved.yaml`.
"""

from __future__ import annotations

import pytest

from mdq import load
from mdq.errors import UnresolvedInclude
from mdq._banks import DictLoader, FileLoader
from mdq.models import Exam, select_random
from mdq.models._query import parse_query
from _corpus import VALID_DIR

BANK = DictLoader(
    {
        "amazonia": {"type": "essay", "stem": "Amazônia.", "tags": ["biome", "forest"]},
        "cerrado": {"type": "essay", "stem": "Cerrado.", "tags": ["biome", "savanna"]},
        "pantanal": {"type": "essay", "stem": "Pantanal.", "tags": ["biome", "wetland"]},
        "mata": {
            "type": "essay",
            "stem": "Mata Atlântica.",
            "tags": ["biome", "forest", "draft"],
        },
        "caju": "---\ntags: fruit\n---\n\nCaju.\n\n[essay]\n",
    }
)

def exam(*blocks: str) -> str:
    return "# [ex] Exam\n\n" + "\n\n".join(blocks) + "\n"


def include_all(query: str, max: int | None = None) -> str:
    lines = ["---", f"includeAll: {query}"]
    if max is not None:
        lines.append(f"max: {max}")
    return "\n".join(lines + ["---"])


def first(candidates: list[str], max: int | None) -> list[str]:
    """A deterministic `Select`: the first `max` candidates."""
    return candidates if max is None else candidates[:max]


def resolved(text: str, **kwargs) -> Exam:
    return load(text).validate().resolve(BANK, **kwargs)


def question_ids(text: str, select=first) -> list[str | None]:
    return [question.id for question in resolved(text, select=select).questions]


# ---------------------------------------------------------------------
# Query index
# ---------------------------------------------------------------------


class CountingIndex:
    """A tag index that records whether a query listed every id."""

    TAGS = {"a": {"1", "2"}, "b": {"2", "3"}, "d": {"3"}}

    def __init__(self) -> None:
        self.listed = False

    def tagged(self, tag: str) -> set[str]:
        return self.TAGS.get(tag, set())

    def ids(self) -> set[str]:
        self.listed = True
        return {"1", "2", "3", "4"}


@pytest.mark.parametrize(
    ("query", "lists_every_id"),
    [
        ("NOT b AND a", False),
        ("NOT a", True),
        ("NOT a AND NOT b", True),
        ("a OR NOT b", True),
        ("NOT d EXCEPT 4", True),
    ],
)
def test_select_lists_every_id_only_for_a_complement(query: str, lists_every_id: bool) -> None:
    index = CountingIndex()
    parse_query(query).select(index)
    assert index.listed is lists_every_id


# ---------------------------------------------------------------------
# Parsing and loading
# ---------------------------------------------------------------------


def test_with_ids_needs_a_resolved_include_all() -> None:
    document = load(exam(include_all("biome"))).validate()
    with pytest.raises(UnresolvedInclude):
        document.with_ids()
    loaded = load(exam(include_all("biome")), ids="fill")
    assert loaded.document is None
    assert "unresolved-include-all" in [d.code for d in loaded.diagnostics]


# ---------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------


def test_select_receives_the_candidates_and_max() -> None:
    calls = []

    def spy(candidates: list[str], max: int | None) -> list[str]:
        calls.append((candidates, max))
        return candidates[-1:]

    assert question_ids(exam(include_all("biome", max=2)), select=spy) == ["pantanal"]
    assert calls == [(["amazonia", "cerrado", "mata", "pantanal"], 2)]


def test_default_select_is_a_random_sample_of_max() -> None:
    seen = set()
    for _ in range(50):
        ids = question_ids(exam(include_all("biome", max=2)), select=None)
        assert len(ids) == 2
        assert set(ids) <= {"amazonia", "cerrado", "mata", "pantanal"}
        seen.update(ids)
    assert len(seen) > 2


def test_default_select_keeps_every_candidate_in_order_without_max() -> None:
    assert select_random(["a", "b", "c"], None) == ["a", "b", "c"]
    assert select_random(["a", "b", "c"], 5) == ["a", "b", "c"]


@pytest.mark.parametrize(
    "bad_select",
    [
        lambda candidates, max: ["tundra"],
        lambda candidates, max: candidates,
        lambda candidates, max: candidates[:1] * 2,
    ],
)
def test_select_must_return_at_most_max_distinct_candidates(bad_select) -> None:
    with pytest.raises(ValueError):
        resolved(exam(include_all("biome", max=2)), select=bad_select)


def test_file_loader_finds_questions_by_tag() -> None:
    bank = FileLoader(VALID_DIR / "exam")
    assert set(bank.tagged("wetland")) == {"pantanal-01", "pantanal-02"}
    assert "recursion-01" in bank.ids()
    assert "midterm" not in bank.ids()
