"""Lint codes on `preAccept`/`preReject`, same conditions as `accept`/`reject`.

Covers `redundant-regex-anchor` and `ignored-regex-flag` (lint-codes.md,
short-answer.md "Additional Rules" and footnotes 9 and 10, patterns.md "Regex
flags"). The `*` wildcard no longer exists, so `accept-wildcard` and
`unreachable-reject` are never reported.
"""

from __future__ import annotations

import pytest

from mdq import Diagnostic, load

ALL_CODES = [
    "redundant-regex-anchor",
    "ignored-regex-flag",
]
REMOVED_CODES = ["accept-wildcard", "unreachable-reject", "short-answer-not-gradable"]


def _diagnostics(doc: dict, code: str) -> list[Diagnostic]:
    return [d for d in load(doc, kind="question").diagnostics if d.code == code]


def _paths(doc: dict, code: str) -> list[tuple]:
    return [d.path for d in _diagnostics(doc, code)]


def _short_answer(**fields: object) -> dict:
    return {
        "type": "short-answer",
        "id": "rio",
        "title": "Rio",
        "stem": "Qual rio banha Manaus?",
        "accept": ["Negro"],
        **fields,
    }


def _fill_in(**blank_fields: object) -> dict:
    return {
        "type": "fill-in",
        "id": "bioma",
        "title": "Biomas",
        "stem": "O bioma [^x] cobre boa parte do Brasil central.",
        "blanks": [
            {"id": "x", "type": "short-answer", "accept": ["Cerrado"], **blank_fields}
        ],
    }


@pytest.mark.parametrize("field", ["preAccept", "preReject"])
@pytest.mark.parametrize(
    "regex",
    ["/^Negro/", "/Negro$/i", "/^Negro/b", "/^Rio Negro$/n"],
)
def test_implicit_anchor_in_pre_pattern_is_redundant(field: str, regex: str) -> None:
    doc = _short_answer(**{field: ["/\\d{4}/", regex]})
    diagnostics = _diagnostics(doc, "redundant-regex-anchor")
    assert [d.path for d in diagnostics] == [(field, 1)]
    assert diagnostics[0].severity == "info"


@pytest.mark.parametrize("field", ["preAccept", "preReject"])
def test_redundant_anchor_in_object_entry_is_reported(field: str) -> None:
    entry = {"pattern": "/^Tapajós/", "feedback": "Confira o formato."}
    assert _paths(_short_answer(**{field: [entry]}), "redundant-regex-anchor") == [
        (field, 0)
    ]


@pytest.mark.parametrize("field", ["preAccept", "preReject"])
@pytest.mark.parametrize(
    "entry",
    [
        "^Negro",  # plain literal, not `/`-delimited
        "Negro$",
        "/^Negro/f",  # `f` removes the implicit leading anchor
        "/Negro$/f",  # `f` removes the implicit trailing anchor
        "/Negro$/b",  # `b` removes the implicit trailing anchor
        "/Negro\\$/",  # escaped `$` is a literal
        "/Negro/",
    ],
)
def test_anchor_exceptions_are_not_reported_in_pre_patterns(
    field: str, entry: str
) -> None:
    assert _paths(_short_answer(**{field: [entry]}), "redundant-regex-anchor") == []


@pytest.mark.parametrize("field", ["preAccept", "preReject"])
@pytest.mark.parametrize("flag", list("mgsuvyd"))
def test_ignored_flag_in_pre_pattern_is_reported(field: str, flag: str) -> None:
    doc = _short_answer(**{field: ["/Tocantins/i", f"/Tocantins/{flag}"]})
    diagnostics = _diagnostics(doc, "ignored-regex-flag")
    assert [d.path for d in diagnostics] == [(field, 1)]
    assert diagnostics[0].severity == "info"


@pytest.mark.parametrize("field", ["preAccept", "preReject"])
def test_ignored_flag_in_object_entry_is_reported(field: str) -> None:
    entry = {"pattern": "/Tocantins/g", "feedback": "Confira o formato."}
    assert _paths(_short_answer(**{field: [entry]}), "ignored-regex-flag") == [
        (field, 0)
    ]


@pytest.mark.parametrize("field", ["preAccept", "preReject"])
@pytest.mark.parametrize("flags", list("inbf") + ["in", "nb"])
def test_effective_flags_are_not_reported_in_pre_patterns(
    field: str, flags: str
) -> None:
    assert (
        _paths(_short_answer(**{field: [f"/Tocantins/{flags}"]}), "ignored-regex-flag")
        == []
    )


@pytest.mark.parametrize("code", REMOVED_CODES)
@pytest.mark.parametrize("pattern", ["*", {"pattern": "*", "feedback": "Inválido."}])
def test_asterisk_in_pre_patterns_reports_no_removed_code(
    code: str, pattern: object
) -> None:
    doc = _short_answer(preAccept=[pattern, "Negro"], preReject=["Amazonas", pattern])
    assert _paths(doc, code) == []


@pytest.mark.parametrize(
    "fields, code, expected",
    [
        (
            {"preAccept": ["/^Cerrado/"]},
            "redundant-regex-anchor",
            [("blanks", 0, "preAccept", 0)],
        ),
        (
            {"preReject": ["/^Cerrado/"]},
            "redundant-regex-anchor",
            [("blanks", 0, "preReject", 0)],
        ),
        (
            {"preAccept": ["/Cerrado/m"]},
            "ignored-regex-flag",
            [("blanks", 0, "preAccept", 0)],
        ),
        (
            {"preReject": ["/Cerrado/y"]},
            "ignored-regex-flag",
            [("blanks", 0, "preReject", 0)],
        ),
    ],
)
def test_fill_in_blank_reports_pre_pattern_lints(
    fields: dict, code: str, expected: list[tuple]
) -> None:
    assert _paths(_fill_in(**fields), code) == expected


def test_fill_in_blank_index_follows_the_blank_position() -> None:
    doc = _fill_in(preAccept=["/\\d{4}/"])
    doc["stem"] += " Já o bioma [^y] fica no litoral."
    doc["blanks"].append(
        {
            "id": "y",
            "type": "short-answer",
            "accept": ["Mata Atlântica"],
            "preReject": ["/^Mata/"],
        }
    )
    assert _paths(doc, "redundant-regex-anchor") == [("blanks", 1, "preReject", 0)]


@pytest.mark.parametrize("code", ALL_CODES)
def test_clean_pre_patterns_report_none_of_the_codes(code: str) -> None:
    doc = _short_answer(preAccept=["/\\d{4}/"], preReject=["/[a-z]{40,}/i", "*"])
    assert _paths(doc, code) == []
    assert _paths(_fill_in(preAccept=["/\\d{4}/"], preReject=["*"]), code) == []


def test_existing_accept_reject_behavior_is_unchanged() -> None:
    doc = _short_answer(
        accept=["Negro", "/^Negro/", "/Negro/g", "*"], reject=["*", "Solimões"]
    )
    assert _paths(doc, "redundant-regex-anchor") == [("accept", 1)]
    assert _paths(doc, "ignored-regex-flag") == [("accept", 2)]
    for code in REMOVED_CODES:
        assert _paths(doc, code) == []
