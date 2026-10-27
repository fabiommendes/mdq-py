"""
`examples/matching/query.yaml`: the `includeAll` query language
(docs/exam.md, "Include all"). The header of the file describes the format.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from mdq.models._query import QuerySyntaxError, is_standard_query, parse_query
from _corpus import EXAMPLES_ROOT

_FILE: dict[str, Any] = yaml.safe_load(
    (EXAMPLES_ROOT / "matching" / "query.yaml").read_text(encoding="utf-8")
)
CASES: list[dict[str, Any]] = _FILE["cases"]
_INDEX: dict[str, Any] = _FILE["index"]


class _Index:
    """The tag index of the file, as a `select` receives it."""

    def tagged(self, tag: str) -> set[str]:
        return set(_INDEX["tags"].get(tag, []))

    def ids(self) -> set[str]:
        return set(_INDEX["ids"])


def test_there_are_query_cases() -> None:
    assert CASES


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_query(case: dict[str, Any]) -> None:
    query = case["query"]
    assert is_standard_query(query) is case["standard"]
    if not case["standard"]:
        with pytest.raises(QuerySyntaxError):
            parse_query(query)
        return
    parsed = parse_query(query)
    for entry in case.get("matches", []):
        assert parsed.matches(set(entry["tags"]), entry.get("id", "q")) is entry["match"]
    if "select" in case:
        assert parsed.select(_Index()) == set(case["select"])
