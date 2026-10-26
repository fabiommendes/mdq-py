"""fill-in.md, "Frontmatter": the `domain` and `decimalPlaces` maps."""

from __future__ import annotations

import mdq

STEM = "The Pico da Bandeira is [^height] meters high."


def _load(front: str, tag: str = "[^height/numeric(m)]: 2892 +- 5", extra: str = ""):
    source = f"---\n{front}\n---\n\n{STEM}\n\n{tag}\n{extra}"
    return mdq.load(source, format="mdq")


def _errors(loaded) -> list[tuple[str, tuple]]:
    return [(d.code, d.path) for d in loaded.diagnostics if d.severity == "error"]


def test_a_map_that_is_not_a_mapping_is_an_error() -> None:
    assert _errors(_load("domain: decimal")) != []


def test_the_maps_are_written_back_and_read_again() -> None:
    first = _load("domain:\n  height: decimal\ndecimalPlaces:\n  height: 1").document
    front = first.frontmatter()
    assert front["domain"] == {"height": "decimal"}
    assert front["decimalPlaces"] == {"height": 1}
    again = mdq.load(first.render(), format="mdq").document
    assert again.blanks == first.blanks
