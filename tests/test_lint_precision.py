"""
Rules made more precise after the lint-codes audit:

* `accept-reject-overlap` compares ordering lines after all forms of
  normalization (ordering.md, "Accepted/rejected answers").
* `accept-outside-answer-key` and `unreachable-alternative` compare
  `accept`/`reject` lines with the `lines`/`extra` pool after
  normalization (ordering.md, "Accepted/rejected answers").
* `domain-mismatch` infers the domain from the answer and the absolute
  tolerance (numeric.md, "Number type/domain").
* `redundant-regex-anchor` reports only an anchor that is already
  implicit, given the `f`/`b` flags, in delimited
  `accept`/`reject` entries (short-answer.md, "Regex flags").
"""

from __future__ import annotations

import pytest

from mdq import Diagnostic, load


def _load(doc: dict) -> list[Diagnostic]:
    return load(doc, kind="question").diagnostics


def _paths(doc: dict, code: str) -> list[tuple]:
    return [d.path for d in _load(doc) if d.code == code]


# ---------------------------------------------------------------------
# accept-reject-overlap: after normalization
# ---------------------------------------------------------------------


def _ordering(accept: list, reject: list, **fields: object) -> dict:
    return {
        "type": "ordering",
        "content": "code",
        "id": "ciclo",
        "title": "Ciclo da água",
        "stem": "Ordene as etapas do ciclo da água na Amazônia.",
        "lines": [[0, "evaporação"], [0, "condensação"], [0, "precipitação"]],
        "accept": [{"lines": accept}],
        "reject": [{"lines": reject}],
        **fields,
    }


def test_overlap_after_dedent_is_an_error() -> None:
    doc = _ordering(
        accept=[[0, "condensação"], [0, "evaporação"]],
        reject=[[1, "condensação"], [1, "evaporação"]],
        normalizations=["dedent"],
    )
    loaded = load(doc, kind="question")
    assert loaded.document is None
    assert [d.code for d in loaded.diagnostics if d.severity == "error"] == [
        "accept-reject-overlap"
    ]


def test_overlap_after_skip_blanks_is_an_error() -> None:
    doc = _ordering(
        accept=[[0, "condensação"], [0, ""], [0, "evaporação"]],
        reject=[[0, "condensação"], [0, "evaporação"]],
        normalizations=["skip-blanks"],
    )
    loaded = load(doc, kind="question")
    assert loaded.document is None
    assert "accept-reject-overlap" in {d.code for d in loaded.diagnostics}


def test_lines_that_differ_after_normalization_do_not_overlap() -> None:
    doc = _ordering(
        accept=[[0, "condensação"], [0, "evaporação"]],
        reject=[[1, "condensação"], [1, "evaporação"]],
        indentation="strict",
    )
    loaded = load(doc, kind="question")
    assert loaded.document is not None, loaded.diagnostics


def _errors(doc: dict) -> list[tuple[str, tuple]]:
    loaded = load(doc, kind="question")
    return [(d.code, d.path) for d in loaded.diagnostics if d.severity == "error"]


def test_reject_equal_to_the_answer_key_is_an_overlap() -> None:
    doc = _ordering(accept=[[0, "evaporação"]], reject=[[0, "evaporação"]])
    doc["reject"] = [{"lines": [list(line) for line in doc["lines"]]}]
    assert _errors(doc) == [("accept-reject-overlap", ("reject", 0))]


def test_reject_equal_to_the_answer_key_after_dedent_is_an_overlap() -> None:
    doc = {
        "type": "ordering",
        "content": "text",
        "stem": "Ordene as linhas.",
        "lines": [[0, "for i in range(3):"], [1, "print(i)"]],
        "reject": [{"lines": [[0, "for i in range(3):"], [0, "print(i)"]]}],
        "indentation": "lenient",
    }
    assert _errors(doc) == [("accept-reject-overlap", ("reject", 0))]


def test_reject_equal_to_the_answer_key_under_strict_is_fine() -> None:
    doc = {
        "type": "ordering",
        "content": "text",
        "stem": "Ordene as linhas.",
        "lines": [[0, "for i in range(3):"], [1, "print(i)"]],
        "reject": [{"lines": [[0, "for i in range(3):"], [0, "print(i)"]]}],
        "indentation": "strict",
    }
    assert _errors(doc) == []


# ---------------------------------------------------------------------
# accept-outside-answer-key: an accept is a sub-multiset of the key
# ---------------------------------------------------------------------


def _with_accept(accept: list, **fields: object) -> dict:
    return {
        "type": "ordering",
        "content": "code",
        "stem": "Ordene as etapas do ciclo da água na Amazônia.",
        "lines": [[0, "evaporação"], [0, "condensação"], [0, "precipitação"]],
        "extra": [[0, "erosão"]],
        "accept": [{"lines": accept}],
        **fields,
    }


def test_accept_may_leave_lines_out() -> None:
    doc = _with_accept([[0, "precipitação"], [0, "evaporação"]])
    assert _errors(doc) == []


def test_accept_with_a_distractor_is_an_error() -> None:
    doc = _with_accept([[0, "evaporação"], [0, "erosão"]])
    assert _errors(doc) == [("accept-outside-answer-key", ("accept", 0))]


def test_accept_with_a_foreign_line_is_an_error() -> None:
    doc = _with_accept([[0, "evaporação"], [0, "transpiração"]])
    assert _errors(doc) == [("accept-outside-answer-key", ("accept", 0))]


def test_accept_with_an_extra_copy_of_a_line_is_an_error() -> None:
    doc = _with_accept([[0, "evaporação"], [0, "evaporação"]])
    assert _errors(doc) == [("accept-outside-answer-key", ("accept", 0))]


def test_accept_may_use_as_many_copies_as_the_key_has() -> None:
    doc = _with_accept([[0, "a"], [0, "a"]], lines=[[0, "a"], [0, "a"], [0, "b"]])
    del doc["extra"]  # an explicit empty `extra` is invalid: omit it
    assert _errors(doc) == []


def test_accept_identifies_lines_as_the_response_check_does() -> None:
    doc = _with_accept([[2, "condensação"]], indentation="lenient")
    assert _errors(doc) == []
    doc = _with_accept([[2, "condensação"]], indentation="strict")
    assert _errors(doc) == []
    doc = _with_accept([[2, "condensação"]])
    assert _errors(doc) == [("accept-outside-answer-key", ("accept", 0))]
    doc = _with_accept([[0, "condensação"], [0, ""]], normalizations=["skip-blanks"])
    assert _errors(doc) == []


# ---------------------------------------------------------------------
# unreachable-alternative: reject needs lines the pool lacks
# ---------------------------------------------------------------------


def _with_reject(reject: list, **fields: object) -> dict:
    return {
        "type": "ordering",
        "content": "code",
        "stem": "Ordene as etapas do ciclo da água na Amazônia.",
        "lines": [[0, "evaporação"], [0, "condensação"], [0, "precipitação"]],
        "extra": [[0, "erosão"]],
        "reject": [{"lines": reject}],
        **fields,
    }


def test_reject_with_a_foreign_line_is_unreachable() -> None:
    doc = _with_reject([[0, "evaporação"], [0, "transpiração"]])
    assert _errors(doc) == []
    assert _paths(doc, "unreachable-alternative") == [("reject", 0, "lines")]


def test_reject_with_more_copies_than_the_pool_is_unreachable() -> None:
    doc = _with_reject([[0, "erosão"], [0, "erosão"]])
    assert _paths(doc, "unreachable-alternative") == [("reject", 0, "lines")]


def test_reject_may_use_a_distractor() -> None:
    doc = _with_reject([[0, "evaporação"], [0, "erosão"]])
    assert _paths(doc, "unreachable-alternative") == []


def test_reject_reachability_uses_the_normalized_pool() -> None:
    doc = _with_reject([[3, "erosão"]], indentation="lenient")
    assert _paths(doc, "unreachable-alternative") == []
    doc = _with_reject([[3, "erosão"]], indentation="strict")
    assert _paths(doc, "unreachable-alternative") == []
    doc = _with_reject([[3, "erosão"]])
    assert _paths(doc, "unreachable-alternative") == [("reject", 0, "lines")]


# ---------------------------------------------------------------------
# domain-mismatch: answer and absolute tolerance
# ---------------------------------------------------------------------


def _numeric(**fields: object) -> dict:
    return {
        "type": "numeric",
        "id": "altitude",
        "title": "Altitude",
        "stem": "Qual a altitude média de Brasília, em metros?",
        **fields,
    }


def test_decimal_absolute_tolerance_widens_the_inferred_domain() -> None:
    doc = _numeric(answer=1172, domain="decimal", tolerance={"absolute": 0.5})
    assert _paths(doc, "domain-mismatch") == []


def test_integer_domain_disagrees_with_a_decimal_absolute_tolerance() -> None:
    doc = _numeric(answer=1172, domain="integer", tolerance={"absolute": 0.5})
    assert _paths(doc, "domain-mismatch") == [("domain",)]


def test_relative_tolerance_takes_no_part_in_the_inferred_domain() -> None:
    doc = _numeric(answer=1172, domain="integer", tolerance={"relative": 0.05})
    assert _paths(doc, "domain-mismatch") == []


def test_numeric_blank_domain_uses_the_absolute_tolerance() -> None:
    doc = {
        "type": "fill-in",
        "id": "altitude",
        "title": "Altitude",
        "stem": "Brasília fica a [^h] metros de altitude.",
        "blanks": [
            {
                "id": "h",
                "type": "numeric",
                "answer": 1172,
                "domain": "decimal",
                "tolerance": {"absolute": 0.5},
            }
        ],
    }
    assert _paths(doc, "domain-mismatch") == []


# ---------------------------------------------------------------------
# redundant-regex-anchor: only an implicit anchor, in every pattern
# ---------------------------------------------------------------------


def _short_answer(**fields: object) -> dict:
    return {
        "type": "short-answer",
        "id": "rio",
        "title": "Rio",
        "stem": "Qual rio banha Manaus?",
        **fields,
    }


@pytest.mark.parametrize(
    "regex",
    ["/^Negro/", "/Negro$/i", "/^Negro/b", "/^Rio Negro$/n"],
)
def test_implicit_anchor_in_regex_is_redundant(regex: str) -> None:
    assert _paths(_short_answer(accept=[regex]), "redundant-regex-anchor") == [
        ("accept", 0)
    ]


def test_implicit_anchor_in_a_simple_block_pattern_is_redundant() -> None:
    """`[short-answer]: /^Negro/` parses to `accept: ["/^Negro/"]`."""
    doc = _short_answer(accept=["/^Negro$/"])
    assert _paths(doc, "redundant-regex-anchor") == [("accept", 0)]


@pytest.mark.parametrize(
    "regex",
    [
        "Negro",
        "^Negro",
        "Negro$",
        "/Negro$/b",
        "/^Negro/f",
        "/Negro$/f",
        "/^Negro$/fb",
        r"Negro\$",
        r"/Negro\$/",
    ],
)
def test_explicit_or_literal_anchor_in_regex_is_not_redundant(regex: str) -> None:
    assert _paths(_short_answer(accept=[regex]), "redundant-regex-anchor") == []


@pytest.mark.parametrize("section", ["accept", "reject"])
def test_implicit_anchor_in_a_delimited_pattern_is_redundant(section: str) -> None:
    fields: dict[str, object] = {
        section: [{"pattern": "Negro"}, {"pattern": "/^Solimões/"}]
    }
    if section == "reject":
        fields["accept"] = ["Negro"]
    doc = _short_answer(**fields)
    assert _paths(doc, "redundant-regex-anchor") == [(section, 1)]


@pytest.mark.parametrize("pattern", ["^Negro", "/Negro$/b", "/^Negro/f"])
def test_literal_or_needed_anchor_in_accept_is_not_redundant(pattern: str) -> None:
    doc = _short_answer(accept=[{"pattern": pattern}])
    assert _paths(doc, "redundant-regex-anchor") == []


# ---------------------------------------------------------------------
# The parser derives `domain` from the value and the absolute tolerance
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "domain"),
    [
        ("0 +- 0.01", "decimal"),
        ("42 +- 1", "integer"),
        ("42 +- 5%", "integer"),
        ("42 +- 0.5 +- 5%", "decimal"),
        ("1/3 +- 1", "fraction"),
        ("1/3 +- 0.01", "decimal"),
        ("3.5 +- 1", "decimal"),
    ],
)
def test_parser_domain_is_the_wider_of_value_and_absolute_tolerance(
    body: str, domain: str
) -> None:
    text = f"Qual a altitude do Pico da Bandeira?\n\n[numeric]: {body}\n"
    loaded = load(text, kind="question")
    assert loaded.document is not None, loaded.diagnostics
    assert loaded.document.domain == domain
    assert "domain-mismatch" not in {d.code for d in loaded.diagnostics}


def test_parser_numeric_blank_domain_uses_the_absolute_tolerance() -> None:
    text = "O Pico da Bandeira tem [^h] km.\n\n[^h/numeric]: 3 +- 0.1\n"
    loaded = load(text, kind="question")
    assert loaded.document is not None, loaded.diagnostics
    assert loaded.document.blanks[0].domain == "decimal"


def test_a_float_answer_is_a_decimal_not_a_fraction() -> None:
    """numeric.md, "Answer representation": with `domain: fraction`, the
    answer is a fraction string or an integer. A float that is not whole
    is a decimal only (see also test_numeric_domain_rules.py)."""
    assert (
        _paths(
            _numeric(answer=0.75, domain="decimal", tolerance={"absolute": 1}),
            "answer-outside-domain",
        )
        == []
    )
    assert _paths(
        _numeric(answer=0.75, domain="fraction", tolerance={"absolute": 1}),
        "answer-outside-domain",
    ) == [("answer",)]
    # A whole absolute tolerance is not a decimal: no `domain-mismatch`.
    assert (
        _paths(
            _numeric(answer=0.75, domain="fraction", tolerance={"absolute": 1}),
            "domain-mismatch",
        )
        == []
    )


def test_a_float_answer_with_a_decimal_tolerance_is_not_a_fraction() -> None:
    doc = _numeric(answer=0.75, domain="fraction", tolerance={"absolute": 0.01})
    assert _paths(doc, "domain-mismatch") == [("domain",)]
