"""fill-in.md, "Frontmatter": the `domain` and `decimalPlaces` maps."""

from __future__ import annotations

import mdq

STEM = "The Pico da Bandeira is [^height] meters high."


def _load(front: str, tag: str = "[^height/numeric(m)]: 2892 +- 5", extra: str = ""):
    source = f"---\n{front}\n---\n\n{STEM}\n\n{tag}\n{extra}"
    return mdq.load(source, format="mdq")


def _errors(loaded) -> list[tuple[str, tuple]]:
    return [(d.code, d.path) for d in loaded.diagnostics if d.severity == "error"]


def test_the_maps_set_the_fields_of_the_blank() -> None:
    loaded = _load("domain:\n  height: decimal\ndecimalPlaces:\n  height: 1")
    assert _errors(loaded) == []
    blank = loaded.document.blanks[0]
    assert (blank.domain, blank.decimal_places) == ("decimal", 1)


def test_without_the_maps_the_blank_takes_the_inferred_values() -> None:
    blank = _load("id: x").document.blanks[0]
    assert (blank.domain, blank.decimal_places) == ("integer", None)


def test_the_domain_map_alone_infers_the_places() -> None:
    blank = _load("domain:\n  height: decimal", "[^height/numeric(m)]: 2892.25 +- 5").document.blanks[0]
    assert (blank.domain, blank.decimal_places) == ("decimal", 2)


def test_the_decimal_places_map_wins_over_the_inferred_places() -> None:
    blank = _load("decimalPlaces:\n  height: 3", "[^height/numeric(m)]: 2892.25 +- 5").document.blanks[0]
    assert blank.decimal_places == 3


def test_a_key_that_is_not_a_blank_is_undefined() -> None:
    assert _errors(_load("domain:\n  altura: decimal")) == [("undefined-blank", ("domain", "altura"))]
    assert _errors(_load("decimalPlaces:\n  altura: 1")) == [
        ("undefined-blank", ("decimalPlaces", "altura"))
    ]


def test_a_key_of_a_short_answer_blank_is_a_schema_error() -> None:
    loaded = _load(
        "decimalPlaces:\n  height: 1",
        "[^height/short-answer]: 2892",
    )
    assert _errors(loaded) == [("schema-error", ("blanks", 0, "decimalPlaces"))]


def test_a_value_out_of_range_is_a_schema_error() -> None:
    assert _errors(_load("decimalPlaces:\n  height: -1")) == [
        ("schema-error", ("blanks", 0, "decimalPlaces"))
    ]
    assert _errors(_load("domain:\n  height: real")) == [("schema-error", ("blanks", 0, "domain"))]


def test_a_map_that_is_not_a_mapping_is_an_error() -> None:
    assert _errors(_load("domain: decimal")) != []


def test_the_maps_are_written_back_and_read_again() -> None:
    first = _load("domain:\n  height: decimal\ndecimalPlaces:\n  height: 1").document
    front = first.frontmatter()
    assert front["domain"] == {"height": "decimal"}
    assert front["decimalPlaces"] == {"height": 1}
    again = mdq.load(first.render(), format="mdq").document
    assert again.blanks == first.blanks
