"""
`include-all` blocks and their query language (docs/exam.md, "Include all").
"""

from __future__ import annotations

import pytest

from mdq import load
from mdq.errors import UnresolvedInclude
from mdq.loaders import DictLoader, FileLoader
from mdq.models import Exam, IncludeAll, select_random
from mdq.parser import parse_exam
from mdq.query import QuerySyntaxError, is_standard_query, parse_query
from mdq.testing import VALID_DIR

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

#: The diagnostics this module is about. Other rules (a missing title,
#: say) also fire on these small documents, and are ignored here.
CODES = {
    "empty-include-all",
    "exam-without-questions",
    "nonstandard-include-query",
    "separator-before-include",
    "undeclared-id-after-include-all",
    "unresolved-include-all",
    "unknown-frontmatter-key",
}


def exam(*blocks: str) -> str:
    return "# [ex] Exam\n\n" + "\n\n".join(blocks) + "\n"


def include_all(query: str, max: int | None = None) -> str:
    lines = ["---", f"include-all: {query}"]
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


def relevant(diagnostics) -> list:
    return [d for d in diagnostics if d.code in CODES]


def codes(text: str) -> list[str]:
    return [d.code for d in relevant(load(text).diagnostics)]


# ---------------------------------------------------------------------
# Query language
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "tags", "expected"),
    [
        ("biome", {"biome"}, True),
        ("biome", {"forest"}, False),
        ("biome AND forest", {"biome", "forest"}, True),
        ("biome AND forest", {"biome"}, False),
        ("savanna OR wetland", {"wetland"}, True),
        ("NOT draft", set(), True),
        ("NOT NOT draft", {"draft"}, True),
        ("a OR b AND c", {"a"}, True),
        ("(a OR b) AND c", {"a"}, False),
        ("biome AND NOT draft", {"biome", "draft"}, False),
        ("física", {"física"}, True),
        ("and", {"and"}, True),
        ("ANDROID", {"ANDROID"}, True),
    ],
)
def test_query_matches_tags(query: str, tags: set[str], expected: bool) -> None:
    assert parse_query(query).matches(tags, "q") is expected


def test_except_removes_listed_ids() -> None:
    query = parse_query("biome EXCEPT cerrado, pantanal")
    assert query.matches({"biome"}, "amazonia")
    assert not query.matches({"biome"}, "cerrado")
    assert not query.matches({"biome"}, "pantanal")


@pytest.mark.parametrize(
    "query",
    ["", "AND", "biome AND", "(biome", "biome)", "biome EXCEPT", "#biome OR", "a b"],
)
def test_invalid_query_is_rejected(query: str) -> None:
    with pytest.raises(QuerySyntaxError):
        parse_query(query)
    assert not is_standard_query(query)


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
    ("query", "expected", "lists_every_id"),
    [
        ("a", {"1", "2"}, False),
        ("a AND b", {"2"}, False),
        ("a OR b", {"1", "2", "3"}, False),
        ("a AND NOT b", {"1"}, False),
        ("NOT b AND a", {"1"}, False),
        ("(a OR b) AND NOT d", {"1", "2"}, False),
        ("b EXCEPT 2", {"3"}, False),
        ("NOT a", {"3", "4"}, True),
        ("NOT a AND NOT b", {"4"}, True),
        ("a OR NOT b", {"1", "2", "4"}, True),
        ("NOT d EXCEPT 4", {"1", "2"}, True),
    ],
)
def test_select_lists_every_id_only_for_a_complement(
    query: str, expected: set[str], lists_every_id: bool
) -> None:
    index = CountingIndex()
    assert parse_query(query).select(index) == expected
    assert index.listed is lists_every_id


# ---------------------------------------------------------------------
# Parsing and loading
# ---------------------------------------------------------------------


def test_parser_keeps_include_all_as_written() -> None:
    doc = parse_exam(exam(include_all("biome", max=2)))
    assert doc["questions"] == [{"include-all": "biome", "max": 2}]


def test_load_keeps_include_all_unresolved() -> None:
    document = load(exam(include_all("biome", max=2))).validate()
    assert document.questions == [IncludeAll(include_all="biome", max=2)]
    assert document.to_dict()["questions"] == [{"include-all": "biome", "max": 2}]


def test_unknown_key_in_include_all_block_warns() -> None:
    text = exam("---\ninclude-all: biome\ncount: 2\n---")
    assert "unknown-frontmatter-key" in codes(text)


@pytest.mark.parametrize("value", ["0", "-1", "two", "true"])
def test_max_must_be_a_positive_integer(value: str) -> None:
    text = exam(f"---\ninclude-all: biome\nmax: {value}\n---")
    assert load(text).document is None


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


def test_include_all_adds_every_match_sorted() -> None:
    assert question_ids(exam(include_all("biome AND NOT draft"))) == [
        "amazonia",
        "cerrado",
        "pantanal",
    ]


def test_markdown_source_in_the_bank_is_matched_by_its_tags() -> None:
    assert question_ids(exam(include_all("fruit"))) == ["caju"]


def test_select_receives_the_candidates_and_max() -> None:
    calls = []

    def spy(candidates: list[str], max: int | None) -> list[str]:
        calls.append((candidates, max))
        return candidates[-1:]

    assert question_ids(exam(include_all("biome", max=2)), select=spy) == ["pantanal"]
    assert calls == [(["amazonia", "cerrado", "mata", "pantanal"], 2)]


def test_include_all_skips_an_explicit_include_even_a_later_one() -> None:
    text = exam(include_all("biome AND NOT draft"), "---\ninclude: cerrado\n---")
    assert question_ids(text) == ["amazonia", "pantanal", "cerrado"]


def test_max_applies_after_skipping() -> None:
    text = exam("---\ninclude: amazonia\n---", include_all("biome", max=2))
    assert question_ids(text) == ["amazonia", "cerrado", "mata"]


def test_include_all_skips_a_declared_inline_id() -> None:
    inline = "---\nid: pantanal\n---\n\nOutro Pantanal.\n\n[essay]"
    warnings: list = []
    exam_ = resolved(exam(include_all("wetland"), inline), warnings=warnings)
    assert [q.id for q in exam_.questions] == ["pantanal"]
    assert [d.code for d in warnings] == ["empty-include-all"]


def test_later_include_all_skips_what_an_earlier_one_added() -> None:
    text = exam(include_all("forest AND NOT draft"), include_all("biome AND NOT draft"))
    assert question_ids(text) == ["amazonia", "cerrado", "pantanal"]


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


def test_included_questions_inherit_from_the_exam() -> None:
    text = "---\nlocale: pt-BR\n---\n\n" + exam(include_all("savanna"))
    assert resolved(text).questions[0].locale == "pt-BR"


def test_derived_ids_count_positions_after_resolution() -> None:
    text = exam(include_all("biome AND NOT draft"), "===\n\nNova questão.\n\n[essay]")
    exam_ = resolved(text, select=first).with_ids()
    assert exam_.questions[-1].id == "q4"


def test_a_nonstandard_query_adds_nothing() -> None:
    text = exam(include_all("tags ~ savanna"), "---\ninclude: cerrado\n---")
    assert question_ids(text) == ["cerrado"]


def test_file_loader_finds_questions_by_tag() -> None:
    bank = FileLoader(VALID_DIR / "exam")
    assert set(bank.tagged("wetland")) == {"pantanal-01", "pantanal-02"}
    assert "recursion-01" in bank.ids()
    assert "midterm" not in bank.ids()


# ---------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------


def test_nonstandard_query_is_a_warning() -> None:
    loaded = load(exam(include_all("tags ~ savanna")))
    assert loaded.document is not None
    assert [(d.code, d.severity, d.path) for d in relevant(loaded.diagnostics)] == [
        ("nonstandard-include-query", "warning", ("questions", 0, "include-all"))
    ]


def test_inline_question_without_id_after_include_all_warns() -> None:
    inline = "===\n\nNova questão.\n\n[essay]"
    assert "undeclared-id-after-include-all" in codes(exam(include_all("savanna"), inline))
    assert "undeclared-id-after-include-all" not in codes(
        exam(inline, include_all("savanna"))
    )


@pytest.mark.parametrize("block", ["---\ninclude: cerrado\n---", include_all("savanna")])
def test_separator_before_include_block_warns(block: str) -> None:
    loaded = load(exam("===\n\n" + block))
    assert [(d.code, d.path) for d in relevant(loaded.diagnostics)] == [
        ("separator-before-include", ("questions", 0))
    ]
