"""`unmatchable-regex-escape` and the `n` flag (patterns.md, "Regex flags")."""

from __future__ import annotations

import pytest

from mdq import load
from mdq.models._regex import escaped_code_points

CODE = "unmatchable-regex-escape"


def _short_answer(**fields: object) -> dict:
    return {
        "type": "short-answer",
        "id": "agua",
        "title": "Água",
        "stem": "Como se escreve water em português?",
        "accept": ["Água"],
        **fields,
    }


def _paths(doc: dict) -> list[tuple]:
    return [d.path for d in load(doc, kind="question").diagnostics if d.code == CODE]


@pytest.mark.parametrize("field", ["accept", "reject", "preAccept", "preReject"])
@pytest.mark.parametrize(
    "regex",
    [r"/\xe1gua/n", r"/\u{e1}gua/n", r"/a\u{300}/in"],
)
def test_changed_escape_under_n_is_reported(field: str, regex: str) -> None:
    doc = _short_answer(**{field: ["/ok/", regex]})
    assert _paths(doc) == [(field, 1)]


@pytest.mark.parametrize(
    "regex",
    [r"/\u0061gua/n"],
)
def test_unchanged_escape_or_no_n_is_not_reported(regex: str) -> None:
    assert _paths(_short_answer(accept=[regex])) == []


def test_fill_in_blank_is_reported() -> None:
    doc = {
        "type": "fill-in",
        "id": "bioma",
        "title": "Biomas",
        "stem": "O bioma [^x] cobre o Brasil central.",
        "blanks": [{"id": "x", "type": "short-answer", "accept": [r"/\xe1/n"]}],
    }
    diagnostics = [d for d in load(doc, kind="question").diagnostics if d.code == CODE]
    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "info"


def test_escaped_code_points() -> None:
    body = r"\u00e1\xE9\u{1F600}\\u00e1\."
    assert escaped_code_points(body) == [0xE1, 0xE9, 0x1F600]
